"""Tests for the claim funnel, claim records, letter outcomes and the RESULTS section (T10)."""

from pathlib import Path

import pytest

from pair.contracts import ClaimDecision
from pair.eval.claims import ClaimRecord, Label
from pair.eval.trust_metrics import (
    claim_funnel,
    exchangeability,
    letter_outcomes,
    trust_markdown,
    write_trust_results,
)
from pair.eval.trust_stats import RateEstimate

KEEP, FLAG, DROP = ClaimDecision.KEEP, ClaimDecision.FLAG, ClaimDecision.DROP


def rec(cid: str, case: str, criterion: str, decision: ClaimDecision | None, kind: str = "natural") -> ClaimRecord:
    """A minimal claim record."""
    return ClaimRecord(
        claim_id=cid, case_id=case, patient_id=f"p-{case}", policy_id="pap-osa", criterion_id=criterion,
        text="t", doc_id="d", char_start=0, char_end=1, quote="q", premise="q", score=0.5, decision=decision,
        drafter="gemma4:e4b", verifier_backend="minicheck", verifier_model="bespoke-minicheck", premise_rule="adr-0022", kind=kind,  # type: ignore[arg-type]
    )


RECORDS = [
    rec("a1", "A", "f2f_visit", KEEP),
    rec("a2", "A", "ahi_threshold", FLAG),
    rec("a3", "A", "ahi_threshold", DROP),
    rec("b1", "B", "f2f_visit", KEEP),
    rec("s1", "B", "f2f_visit", None, kind="fault"),
]
LABELS: dict[str, Label] = {"a1": "supported", "a2": "partly", "b1": "unsupported"}
GOLD = {"A": frozenset({"f2f_visit", "ahi_threshold", "adherence"}), "B": frozenset({"f2f_visit"})}


def test_funnel_stages_add_up() -> None:
    """Coverage over gold-met criteria, verbatim over claims, support over labeled, CCR over kept."""
    funnel = claim_funnel(RECORDS, LABELS, GOLD)
    assert (funnel.coverage.k, funnel.coverage.n) == (3, 4)
    assert (funnel.verbatim.k, funnel.verbatim.n) == (3, 4)
    assert (funnel.lenient.k, funnel.lenient.n) == (2, 3)
    assert (funnel.strict.k, funnel.strict.n) == (1, 3)
    assert (funnel.ccr_after.k, funnel.ccr_after.n) == (1, 2)
    assert funnel.verbatim.n == funnel.n_claims


def test_letter_outcomes_group_natural_claims_by_case() -> None:
    """Seeded claims are left out; each case keeps its patient and gold-met set."""
    outcomes = letter_outcomes(RECORDS, LABELS, GOLD)
    assert [o.case_id for o in outcomes] == ["A", "B"]
    assert outcomes[1].patient_id == "p-B" and len(outcomes[1].claims) == 1
    assert outcomes[0].claims[1].label == "partly"


def estimate(k: int, n: int) -> RateEstimate:
    """A rate with dummy intervals."""
    return RateEstimate(k, n, k / n, 0.0, 0.4, 0.0, 0.5)


def test_markdown_says_relative_to_critic_labels_and_never_pass_when_inconclusive() -> None:
    """The report states the label source, the exit verdict and the population caveat."""
    rates = {"leak": estimate(2, 20), "empty": estimate(1, 30), "support": estimate(20, 29), "precision": estimate(40, 45),
             "worst_leak": estimate(3, 22)}
    text = trust_markdown(claim_funnel(RECORDS, LABELS, GOLD), rates, verdict="inconclusive", leak_bound=0.086,
                          imr={"auroc": 0.72, "brier": 0.186, "coverage": 0.917, "coverage_low": 0.91,
                               "coverage_high": 0.924, "share_both": 0.53, "n": 5991},
                          meta={"drafter": "gemma4:e4b", "verifier_backend": "minicheck", "config_hash": "abc"})
    assert "relative to critic labels" in text
    assert "inconclusive" in text and "pass" not in text.replace("pass only", "")
    assert "not a guarantee for Medicare Advantage" in text
    assert "—" not in text and "–" not in text


def test_results_section_written_between_markers(tmp_path: Path) -> None:
    """The phase3-trust block is replaced in place and the rest of RESULTS.md is kept."""
    results = tmp_path / "RESULTS.md"
    results.write_text("# PAIR results\n\n<!-- phase2-core:start -->\nold core\n<!-- phase2-core:end -->\n")
    write_trust_results(results, "first")
    write_trust_results(results, "second")
    text = results.read_text()
    assert "old core" in text and "second" in text and "first" not in text
    assert text.count("<!-- phase3-trust:start -->") == 1


@pytest.mark.parametrize("bad", [{"Z": frozenset()}])
def test_unknown_case_in_gold_is_ignored(bad: dict[str, frozenset[str]]) -> None:
    """Gold for a case with no claims adds its met criteria to coverage only."""
    funnel = claim_funnel(RECORDS, LABELS, {**GOLD, **bad, "C": frozenset({"x"})})
    assert funnel.coverage.n == 5


def scored(cid: str, policy: str, criterion: str, score: float) -> ClaimRecord:
    """A natural claim with a policy, criterion and verifier score."""
    base = rec(cid, cid, criterion, FLAG)
    return base.model_copy(update={"policy_id": policy, "score": score})


def test_exchangeability_compares_mix_and_unsupported_scores() -> None:
    """Policy shares per side, total variation over criteria, and a KS test on unsupported scores."""
    calib = [scored("c1", "pap-osa", "x", 0.1), scored("c2", "pap-osa", "y", 0.2), scored("c3", "oxygen", "x", 0.9)]
    test = [scored("t1", "pap-osa", "x", 0.15), scored("t2", "oxygen", "x", 0.3), scored("t3", "oxygen", "y", 0.8)]
    calib_labels: dict[str, Label] = {"c1": "unsupported", "c2": "partly", "c3": "supported"}
    test_labels: dict[str, Label] = {"t1": "partly", "t2": "unsupported", "t3": "supported"}
    shift = exchangeability(calib, calib_labels, test, test_labels)
    assert shift.policy_mix["pap-osa"] == pytest.approx((2 / 3, 1 / 3))
    assert shift.criterion_tv == pytest.approx(1 / 3)
    assert (shift.n_calib, shift.n_test) == (2, 2)
    assert shift.median_calib == pytest.approx(0.15) and shift.median_test == pytest.approx(0.225)
    assert 0.0 <= shift.ks_p <= 1.0


def test_markdown_reports_agreement_shift_and_reliability() -> None:
    """Both kappas and AC1 sit next to the leak rate; the shift check and the reliability table are shown."""
    rates = {"leak": estimate(1, 47)}
    agreement = {"n": 86, "kappa": 0.55, "kappa_low": 0.39, "kappa_high": 0.71, "ac1": 0.80,
                 "kappa_binary": 0.80, "kappa_binary_low": 0.63, "kappa_binary_high": 0.94, "ac1_binary": 0.92}
    calib = [scored("c1", "pap-osa", "x", 0.1)]
    shift = exchangeability(calib, {"c1": "unsupported"}, calib, {"c1": "unsupported"})
    imr = {"auroc": 0.72, "brier": 0.186, "coverage": 0.917, "coverage_low": 0.91, "coverage_high": 0.924,
           "share_both": 0.53, "n": 5991,
           "reliability": [{"low": 0.0, "high": 0.1, "n": 9, "mean_predicted": 0.06, "observed": 0.44}]}
    text = trust_markdown(claim_funnel(RECORDS, LABELS, GOLD), rates, verdict="pass", leak_bound=0.01, imr=imr,
                          meta={}, agreement=agreement, agreement_source="dev", shift=shift)
    assert "binary kappa 0.80 [0.63, 0.94], AC1 0.92" in text and "3-class kappa 0.55 [0.39, 0.71], AC1 0.80" in text
    assert "dev" in text and "Exchangeability" in text and "KS" in text
    assert "| 0.0 to 0.1 | 9 | 0.060 | 0.440 |" in text
    assert "—" not in text and "–" not in text
