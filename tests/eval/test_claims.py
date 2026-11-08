"""Tests for claim labeling: records, the seeded-claim gate, S1 import, spot checks, agreement (ADR-0020)."""

import json
from pathlib import Path

import pytest

from pair.contracts import ClaimDecision, Evidence, EvidenceStatus
from pair.eval.claims import (
    ClaimRecord,
    Label,
    LabelImport,
    agreement,
    blind_batches,
    build_gate_set,
    disagreement_queue,
    export_batch,
    finalize_labels,
    gwet_ac1,
    import_labels,
    load_label_file,
    overlaps_gold,
    pick_human_naturals,
    read_records,
    score_gate,
    spot_check_sample,
    unblind,
    write_records,
)


def record(i: int, quote: str | None = None, label_kind: str = "natural", criterion: str = "ahi_threshold") -> ClaimRecord:
    """A natural claim record with a numeric quote."""
    text = quote or f"AHI {10 + i}.5 events/hr on test {i}"
    return ClaimRecord(
        claim_id=f"c{i:03d}", case_id=f"case-{i % 6}", patient_id=f"p{i % 3}", policy_id="pap-osa",
        criterion_id=criterion, text=f"My test showed {text}.", doc_id="note", char_start=10,
        char_end=10 + len(text), quote=text, premise=f"Home study: {text}.", score=0.8,
        decision=ClaimDecision.KEEP, drafter="gemma4:e4b", verifier_backend="minicheck",
        verifier_model="bespoke-minicheck", kind=label_kind,  # type: ignore[arg-type]
    )


RECORDS = [record(i, criterion=f"crit{i % 4}") for i in range(40)]


# --- records ----------------------------------------------------------------------------


def test_records_round_trip_through_jsonl(tmp_path: Path) -> None:
    """Rows are written and read back unchanged."""
    path = tmp_path / "claims.jsonl"
    write_records(RECORDS[:3], path)
    assert read_records(path) == RECORDS[:3]


# --- seeded gate ------------------------------------------------------------------------


def test_gate_set_has_enough_faults_and_clean_twins_and_is_seeded() -> None:
    """At least 30 faults and 30 clean twins, identical for the same seed."""
    first = build_gate_set(RECORDS, seed=7)
    again = build_gate_set(RECORDS, seed=7)
    assert first == again
    faults = [r for r in first if r.kind == "fault"]
    clean = [r for r in first if r.kind == "clean"]
    assert len(faults) >= 30 and len(clean) >= 30
    assert {r.fault_type for r in faults} == {"number_swap", "overclaim", "wrong_criterion", "negation_flip"}
    assert len({r.claim_id for r in first}) == len(first)


def test_clean_twin_quotes_its_premise_and_faults_change_the_fact() -> None:
    """A clean twin is the record quote verbatim; a number swap changes a number in it."""
    gate = build_gate_set(RECORDS, seed=7)
    clean = next(r for r in gate if r.kind == "clean")
    assert clean.quote in clean.text and clean.quote in clean.premise
    swap = next(r for r in gate if r.fault_type == "number_swap")
    assert swap.quote not in swap.text


def test_gate_set_needs_enough_source_claims() -> None:
    """Too few natural claims to seed from is an error, not a smaller gate."""
    with pytest.raises(ValueError, match="30"):
        build_gate_set(RECORDS[:10], seed=7)


def test_batch_hides_kind_fault_type_and_scores() -> None:
    """The critic sees claim id, claim text and premise only."""
    rows = export_batch(build_gate_set(RECORDS, seed=7))
    assert set(rows[0]) == {"claim_id", "claim", "premise"}


def gate_labels(gate: list[ClaimRecord], miss: int = 0, false_flags: int = 0) -> dict[str, Label]:
    """Critic labels that miss ``miss`` faults and flag ``false_flags`` clean twins."""
    labels: dict[str, Label] = {}
    faults = [r for r in gate if r.kind == "fault"]
    clean = [r for r in gate if r.kind == "clean"]
    for i, r in enumerate(faults):
        labels[r.claim_id] = "supported" if i < miss else "unsupported"
    for i, r in enumerate(clean):
        labels[r.claim_id] = "partly" if i < false_flags else "supported"
    return labels


NATURAL: dict[str, Label] = {f"n{i}": "supported" for i in range(20)}


def test_gate_passes_at_the_bar() -> None:
    """>= 90% catch, <= 10% clean flags, >= 80% agreement on >= 20 natural claims."""
    gate = build_gate_set(RECORDS, seed=7)
    n_faults = sum(r.kind == "fault" for r in gate)
    result = score_gate(gate, gate_labels(gate, miss=n_faults // 10), NATURAL, NATURAL)
    assert result.passed, result.reasons


@pytest.mark.parametrize(
    ("miss", "false_flags", "natural_human", "reason"),
    [
        (99, 0, NATURAL, "catch"),
        (0, 99, NATURAL, "clean"),
        (0, 0, dict(list(NATURAL.items())[:19]), "natural"),
        (0, 0, {k: ("unsupported" if i < 5 else "supported") for i, k in enumerate(NATURAL)}, "agreement"),
    ],
)
def test_gate_fails_on_any_miss(miss: int, false_flags: int, natural_human: dict[str, str], reason: str) -> None:
    """Missing any of the three bars fails the gate."""
    gate = build_gate_set(RECORDS, seed=7)
    labels = gate_labels(gate, miss=miss, false_flags=false_flags)
    result = score_gate(gate, labels, NATURAL, natural_human)  # type: ignore[arg-type]
    assert not result.passed
    assert any(reason in r for r in result.reasons)


def test_unlabeled_seeded_claim_counts_as_a_miss() -> None:
    """A fault the critic didn't label isn't caught."""
    gate = build_gate_set(RECORDS, seed=7)
    labels = gate_labels(gate)
    for r in [r for r in gate if r.kind == "fault"][:4]:
        del labels[r.claim_id]
    result = score_gate(gate, labels, NATURAL, NATURAL)
    assert result.caught == result.n_faults - 4


# --- S1 import --------------------------------------------------------------------------


def s1(claim_id: str, label: str, quote: str) -> str:
    """One S1 verdict line."""
    return json.dumps({"claim_id": claim_id, "check_id": "S1", "label": label,
                       "quotes": [{"text": quote}], "reasoning": "r"})


def test_import_keeps_quoted_labels_and_queues_unquoted_for_rerun(tmp_path: Path) -> None:
    """A verdict needs a verbatim quote from its premise; otherwise it is re-run once."""
    premises = {r.claim_id: r.premise for r in RECORDS[:4]}
    path = tmp_path / "s1.jsonl"
    path.write_text("\n".join([
        s1("c000", "supported", RECORDS[0].quote),
        s1("c001", "supported", "made up text"),
        json.dumps({"claim_id": "c002", "check_id": "S1", "label": "supported", "quotes": []}),
        s1("c003", "maybe", RECORDS[3].quote),
        "not json",
    ]))
    result = import_labels(path, premises)

    assert result.labels == {"c000": "supported"}
    assert set(result.rerun) == {"c001", "c002", "c003"}
    assert len(result.rejected) == 4


def test_import_tolerates_whitespace_differences_in_quotes(tmp_path: Path) -> None:
    """Quotes are matched after collapsing whitespace, like the case critic."""
    path = tmp_path / "s1.jsonl"
    path.write_text(s1("c000", "partly", RECORDS[0].quote.replace(" ", "  ")))
    assert import_labels(path, {"c000": RECORDS[0].premise}).labels == {"c000": "partly"}


def test_claim_never_labeled_is_queued_too(tmp_path: Path) -> None:
    """A claim with no verdict line at all is re-run."""
    path = tmp_path / "s1.jsonl"
    path.write_text("")
    assert import_labels(path, {"c000": "p"}).rerun == ("c000",)


def test_after_one_rerun_still_unlabeled_claims_are_excluded_and_counted() -> None:
    """Re-run once; what's still missing is left out and counted."""
    first = LabelImport(labels={"a": "supported"}, rerun=("b", "c"), rejected=())
    second = LabelImport(labels={"b": "unsupported"}, rerun=("c",), rejected=())
    final = finalize_labels(first, second)
    assert final.labels == {"a": "supported", "b": "unsupported"}
    assert final.excluded == ("c",)


def test_finalize_without_a_rerun_excludes_the_queue() -> None:
    """If no rerun happened, the queued claims are excluded."""
    final = finalize_labels(LabelImport(labels={}, rerun=("x",), rejected=()), None)
    assert final.excluded == ("x",)


# --- gold overlap, disagreement queue, spot check ---------------------------------------


def gold(criterion: str, start: int, end: int, doc: str = "note") -> Evidence:
    """A gold evidence span."""
    return Evidence(criterion_id=criterion, variable="ahi", value=1.0, span_text="x" * (end - start),
                    char_start=start, char_end=end, doc_id=doc, status=EvidenceStatus.ASSERTED)


def test_gold_overlap_needs_same_doc_criterion_and_overlapping_range() -> None:
    """Overlap is by document, criterion and character range."""
    r = record(0)
    assert overlaps_gold(r, [gold("ahi_threshold", r.char_end - 2, r.char_end + 5)])
    assert not overlaps_gold(r, [gold("ahi_threshold", r.char_end, r.char_end + 5)])
    assert not overlaps_gold(r, [gold("f2f_visit", r.char_start, r.char_end)])
    assert not overlaps_gold(r, [gold("ahi_threshold", r.char_start, r.char_end, doc="other")])


def test_disagreement_queue() -> None:
    """Gold overlap but unsupported, or no overlap but supported."""
    labels = {"a": "unsupported", "b": "supported", "c": "supported", "d": "partly"}
    overlap = {"a": True, "b": False, "c": True, "d": False}
    assert disagreement_queue(labels, overlap) == ("a", "b")  # type: ignore[arg-type]


def test_spot_check_sample_covers_random_queue_and_twenty_negatives() -> None:
    """Random 10% plus the queue plus extra negatives until at least 20 are in."""
    labels = {f"s{i}": "supported" for i in range(200)} | {f"u{i}": "unsupported" for i in range(25)}
    sample = spot_check_sample(labels, queue=("s5",), seed=3)  # type: ignore[arg-type]
    assert "s5" in sample
    assert sum(labels[i] != "supported" for i in sample) >= 20
    assert len(sample) >= 23
    assert sample == spot_check_sample(labels, queue=("s5",), seed=3)  # type: ignore[arg-type]


def test_spot_check_takes_all_negatives_when_fewer_than_twenty() -> None:
    """With only 5 negatives, all 5 are checked."""
    labels = {f"s{i}": "supported" for i in range(50)} | {f"u{i}": "partly" for i in range(5)}
    sample = spot_check_sample(labels, queue=(), seed=0)  # type: ignore[arg-type]
    assert {f"u{i}" for i in range(5)} <= set(sample)


# --- agreement --------------------------------------------------------------------------


def test_gwet_ac1_on_a_known_table() -> None:
    """21 claims, 19 agreements; AC1 uses all three S1 classes (q = 3), so pe divides by q - 1 = 2."""
    a = ["supported"] * 18 + ["unsupported"] * 1 + ["supported"] + ["unsupported"]
    b = ["supported"] * 18 + ["unsupported"] * 1 + ["unsupported"] + ["supported"]
    pa = 19 / 21
    pi_s = 38 / 42
    pi_u = 4 / 42
    pe = (pi_s * (1 - pi_s) + pi_u * (1 - pi_u)) / 2
    assert gwet_ac1(a, b) == pytest.approx((pa - pe) / (1 - pe))  # type: ignore[arg-type]


def test_agreement_report_flags_low_kappa() -> None:
    """Percent and per-class agreement, kappa with a bootstrap CI, AC1; kappa < 0.7 means labels don't count."""
    critic = {f"x{i}": ("supported" if i % 2 else "unsupported") for i in range(40)}
    human_good = dict(critic)
    human_bad = {k: ("supported" if i % 3 else "unsupported") for i, k in enumerate(critic)}

    good = agreement(critic, human_good, seed=0)  # type: ignore[arg-type]
    bad = agreement(critic, human_bad, seed=0)  # type: ignore[arg-type]

    assert good.percent == 1.0 and good.kappa == pytest.approx(1.0) and good.labels_count
    assert good.per_class["supported"] == 1.0
    assert bad.kappa < 0.7 and not bad.labels_count
    assert bad.kappa_low <= bad.kappa <= bad.kappa_high
    assert good.n == 40


def test_agreement_uses_only_claims_both_labeled() -> None:
    """Claims missing from either side are left out."""
    report = agreement({"a": "supported", "b": "partly"}, {"a": "supported"}, seed=0)
    assert report.n == 1


def test_label_file_is_validated(tmp_path: Path) -> None:
    """Nithin's labels file must hold S1 classes only and be JSON."""
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"a": "supported"}))
    assert load_label_file(path) == {"a": "supported"}
    path.write_text(json.dumps({"a": "yes"}))
    with pytest.raises(ValueError, match="unknown"):
        load_label_file(path)
    path.write_text("{")
    with pytest.raises(ValueError):
        load_label_file(path)


def test_kappa_matches_scikit_learn() -> None:
    """The hand-rolled kappa equals scikit-learn's on a mixed table."""
    from sklearn.metrics import cohen_kappa_score

    critic = {f"x{i}": LABELS_CYCLE[i % 3] for i in range(30)}
    human = {f"x{i}": LABELS_CYCLE[(i * 2) % 3] if i % 4 else LABELS_CYCLE[i % 3] for i in range(30)}
    report = agreement(critic, human, seed=0, n_boot=10)  # type: ignore[arg-type]
    ids = sorted(critic)
    expected = cohen_kappa_score([critic[i] for i in ids], [human[i] for i in ids])
    assert report.kappa == pytest.approx(expected)


LABELS_CYCLE = ("supported", "partly", "unsupported")


# --- blind export ---------------------------------------------------------------------------


def test_blind_batches_hide_ids_and_kinds_and_are_seeded() -> None:
    """Rows carry an opaque id, the claim and the premise only; the key maps back; same seed, same order."""
    gate = build_gate_set(RECORDS, seed=1)
    blind = blind_batches(gate, seed=3, batch_size=25, prefix="g")
    rows = [row for batch in blind.batches for row in batch]
    assert [len(b) for b in blind.batches] == [25, 25, 10]
    assert all(set(row) == {"claim_id", "claim", "premise"} for row in rows)
    assert all(row["claim_id"].startswith("g-") and "clean" not in row["claim_id"] for row in rows)
    assert sorted(blind.key.values()) == sorted(r.claim_id for r in gate)
    assert blind_batches(gate, seed=3, batch_size=25, prefix="g") == blind
    kinds = [next(g.kind for g in gate if g.claim_id == blind.key[r["claim_id"]]) for r in rows[:10]]
    assert len(set(kinds)) == 2


def test_unblind_maps_labels_back_and_ignores_unknown_ids() -> None:
    """Critic labels keyed by blind id come back keyed by the original claim id."""
    labels: dict[str, Label] = {"g-001": "supported", "g-999": "partly"}
    assert unblind(labels, {"g-001": "c001"}) == {"c001": "supported"}


def test_human_naturals_split_by_score_and_avoid_gate_sources() -> None:
    """Half below 0.5, half at or above, none sharing a premise with a gate claim, seeded."""
    records = [record(i, criterion=f"crit{i % 4}").model_copy(update={"score": (i % 10) / 10}) for i in range(60)]
    gate = build_gate_set(records, seed=1)
    picked = pick_human_naturals(records, gate, n=6, seed=2)
    gate_premises = {g.premise for g in gate}
    assert len(picked) == 6 and not any(r.premise in gate_premises for r in picked)
    assert sum(r.score is not None and r.score < 0.5 for r in picked) == 3
    assert pick_human_naturals(records, gate, n=6, seed=2) == picked


def test_human_naturals_refuse_when_too_few_left() -> None:
    """Not enough non-gate claims in one score half: a clear error."""
    with pytest.raises(ValueError, match="human"):
        pick_human_naturals(RECORDS[:31], build_gate_set(RECORDS[:31], seed=1), n=20, seed=0)


def test_number_swap_skips_digits_inside_words() -> None:
    """"SpO2 87%" swaps the 87, never the 2 in SpO2."""
    records = [record(i, quote=f"SpO2 {80 + i}% at rest", criterion=f"crit{i % 4}") for i in range(40)]
    swaps = [g for g in build_gate_set(records, seed=0) if g.fault_type == "number_swap"]
    assert swaps and all("SpO2 " in g.text and "SpO9" not in g.text for g in swaps)


def test_wrong_criterion_quotes_another_criterion_of_the_same_case() -> None:
    """The wrong quote comes from the same case, a different criterion, and isn't in the premise; it varies."""
    records = [record(i, quote=f"fact {i} noted", criterion=f"crit{i % 4}") for i in range(60)]
    by_id = {r.claim_id: r for r in records}
    faults = [g for g in build_gate_set(records, seed=0) if g.fault_type == "wrong_criterion"]
    for fault in faults:
        source = by_id[fault.claim_id.removesuffix("-wrong_criterion")]
        quoted = fault.text.split('"')[1]
        other = next(r for r in records if r.quote == quoted)
        assert other.case_id == source.case_id and other.criterion_id != source.criterion_id
        assert quoted not in source.premise
    assert len({g.text for g in faults}) == len(faults)


def test_labels_count_is_decided_on_the_binary_split() -> None:
    """ADR-0020 clarification: partly vs unsupported disagreements don't sink the labels; both kappas are reported."""
    critic = {f"x{i}": ("supported" if i < 20 else "unsupported") for i in range(40)}
    human = {k: ("partly" if v == "unsupported" and i % 2 else v) for i, (k, v) in enumerate(critic.items())}
    report = agreement(critic, human, seed=0)  # type: ignore[arg-type]
    assert report.kappa < 0.7 <= report.kappa_binary
    assert report.kappa_binary == pytest.approx(1.0) and report.ac1_binary == pytest.approx(1.0)
    assert report.kappa_binary_low <= report.kappa_binary <= report.kappa_binary_high
    assert report.labels_count
