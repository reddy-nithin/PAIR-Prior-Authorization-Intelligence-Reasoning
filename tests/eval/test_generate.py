"""End-to-end case assembly with a fake note writer, plus the bundle model (T9)."""

import json
from pathlib import Path

import pytest

from pair.contracts import CriterionStatus
from pair.eval.cases import CaseBundle, CaseLoadError, CaseType, load_case, save_case
from pair.eval.synth.generate import TYPE_MIX, CaseRequest, generate_case, suite
from pair.eval.synth.planners import PlanError
from pair.policies.loader import load_all
from pair.rules.engine import run_rules
from tests.conftest import REPO_ROOT
from tests.eval.helpers import PROFILE, PhraseWriter

CHECKLISTS = load_all(REPO_ROOT / "policies")
GEN = {"backend": "fake", "model": "fake-writer"}


def make(
    policy_id: str = "pap-osa", case_type: CaseType = CaseType.TRICKY, seed: int = 11
) -> CaseBundle:
    """Generate one case with the fake writer."""
    request = CaseRequest(f"{policy_id}-01", policy_id, case_type, seed)
    return generate_case(request, CHECKLISTS[policy_id], PROFILE, PhraseWriter(), GEN)


def test_suite_is_balanced() -> None:
    """Ten cases per policy, 3/3/2/2 across A to D, unique ids and seeds."""
    requests = suite(sorted(CHECKLISTS), base_seed=2026)
    assert len(requests) == 30
    for policy_id in CHECKLISTS:
        types = [r.case_type for r in requests if r.policy_id == policy_id]
        assert types.count(CaseType.WRONGLY_DENIED) == 3
        assert types.count(CaseType.FIXABLE_GAP) == 3
        assert types.count(CaseType.CORRECTLY_DENIED) == 2
        assert types.count(CaseType.TRICKY) == 2
    assert len({r.case_id for r in requests}) == 30
    assert len({r.seed for r in requests}) == 30
    assert len(TYPE_MIX) == 10


@pytest.mark.parametrize("policy_id", sorted(CHECKLISTS))
@pytest.mark.parametrize("case_type", list(CaseType))
def test_generated_case_is_consistent(policy_id: str, case_type: CaseType) -> None:
    """Gold spans slice the notes, and the engine on gold evidence reproduces the gold labels."""
    case = make(policy_id, case_type)
    assert case.synthetic is True
    texts = case.record_text()
    for item in case.gold_evidence:
        assert texts[item.doc_id][item.char_start : item.char_end] == item.span_text
    verdict = run_rules(
        CHECKLISTS[policy_id], case.gold_evidence, case.context, lambda _c, _s: "g"
    )
    assert {r.criterion_id: r.status for r in verdict.results} == case.gold_statuses
    assert verdict.overall is case.gold_overall
    assert case.gold_denial.service in case.denial_text


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """A saved bundle loads back equal, including dates in evidence."""
    case = make()
    path = save_case(case, tmp_path / "cases" / "c.json")
    assert load_case(path) == case
    assert json.loads(path.read_text())["synthetic"] is True


def test_load_errors(tmp_path: Path) -> None:
    """Missing or invalid files raise CaseLoadError."""
    with pytest.raises(CaseLoadError, match="no case file"):
        load_case(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    with pytest.raises(CaseLoadError, match="invalid"):
        load_case(bad)


def test_bundle_rejects_a_span_that_does_not_slice_its_note() -> None:
    """The bundle validator catches wrong offsets and unknown notes."""
    case = make()
    data = case.model_dump()
    data["gold_evidence"][0] = {
        **data["gold_evidence"][0],
        "char_start": data["gold_evidence"][0]["char_start"] + 1,
        "char_end": data["gold_evidence"][0]["char_end"] + 1,
    }
    with pytest.raises(ValueError, match="does not match"):
        CaseBundle.model_validate(data)
    data = case.model_dump()
    data["gold_evidence"][0] = {**data["gold_evidence"][0], "doc_id": "fax"}
    with pytest.raises(ValueError, match="unknown note"):
        CaseBundle.model_validate(data)
    data = case.model_dump()
    data["notes"] = [data["notes"][0], data["notes"][0]]
    with pytest.raises(ValueError, match="unique"):
        CaseBundle.model_validate(data)


def test_repeated_identical_phrase_keeps_gold() -> None:
    """A planted phrase repeated with the same value is not a conflict; the first occurrence is the gold span."""
    writer = PhraseWriter(extra="AHI 21.1 events/hour")
    request = CaseRequest("pap-osa-01", "pap-osa", CaseType.WRONGLY_DENIED, 3)
    case = generate_case(request, CHECKLISTS["pap-osa"], PROFILE, writer, GEN)
    assert case.gold_overall is CriterionStatus.MET


def test_plan_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """A gold mismatch after writing raises PlanError."""
    from pair.eval.synth import generate as gen

    def fake_run_rules(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        verdict = run_rules(*args, **kwargs)  # type: ignore[arg-type]
        results = [
            r.model_copy(update={"status": CriterionStatus.UNMET})
            for r in verdict.results
        ]
        return verdict.model_copy(update={"results": results})

    monkeypatch.setattr(gen, "run_rules", fake_run_rules)
    with pytest.raises(PlanError, match="changed after note writing"):
        make()


def test_generate_suite_writes_cases_and_audit(tmp_path: Path) -> None:
    """The batch writes one JSON per case, skips existing ones, totals usage and picks 20% for audit."""
    from pair.eval.synth.generate import generate_suite

    requests = suite(sorted(CHECKLISTS), base_seed=1, per_policy=10)
    profiles = [PROFILE, PROFILE.model_copy(update={"synthea_id": "syn-2", "sex": "M"})]
    summary = generate_suite(
        requests, CHECKLISTS, profiles, PhraseWriter(), tmp_path, GEN
    )
    assert summary.written == 30
    assert summary.failed == []
    assert summary.prompt_tokens == 100 * 30
    assert len(list(tmp_path.glob("*/*.json"))) == 30
    audit = (tmp_path / "AUDIT.md").read_text()
    assert audit.count("- [ ] `") == 6
    for policy_id in CHECKLISTS:
        assert audit.count(f"`{policy_id}-") == 2
    again = generate_suite(
        requests, CHECKLISTS, profiles, PhraseWriter(), tmp_path, GEN
    )
    assert again.written == 0
    assert again.skipped == 30


def test_generate_suite_records_failures(tmp_path: Path) -> None:
    """A case whose notes never pass the span check is reported, not fatal."""
    from pair.eval.synth.generate import generate_suite

    requests = suite(["pap-osa"], base_seed=1, per_policy=1)

    class Dropper(PhraseWriter):
        def generate_json(self, prompt, schema):  # type: ignore[no-untyped-def]
            result = super().generate_json(prompt, schema)
            data = {
                k: v.replace("CPAP started", "CPAP began")
                for k, v in result.data.items()
            }
            return result.__class__(**{**result.__dict__, "data": data})

    summary = generate_suite(requests, CHECKLISTS, [PROFILE], Dropper(), tmp_path, GEN)
    assert summary.written == 0
    assert [case_id for case_id, _ in summary.failed] == ["pap-osa-01"]


def test_generate_suite_needs_profiles(tmp_path: Path) -> None:
    """No profiles is an error."""
    from pair.eval.synth.generate import generate_suite

    with pytest.raises(ValueError, match="profiles"):
        generate_suite(
            suite(["pap-osa"], 1, 1), CHECKLISTS, [], PhraseWriter(), tmp_path, GEN
        )


def test_profile_conditions_that_fill_a_hidden_fact_are_dropped() -> None:
    """Hypertension qualifies AHI 5 to 14, so it can't stay in a negated-symptoms profile (Step 8, B4)."""
    from pair.eval.synth.generate import without_conditions

    profile = PROFILE.model_copy(
        update={"conditions": ["Essential hypertension", "Obesity"]}
    )
    kept = without_conditions(profile, (r"hypertens",))
    assert kept.conditions == ["Obesity"]
    assert without_conditions(profile, ()) == profile
