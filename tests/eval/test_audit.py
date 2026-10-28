"""Mechanical audit pre-check (ADR-0013, critic plan Step 4)."""

import json
from pathlib import Path

import pytest

from pair.cli import main
from pair.contracts import CriterionStatus
from pair.eval.audit import (
    PrecheckFinding,
    Severity,
    check_case,
    check_policy_sources,
    precheck_paths,
)
from pair.eval.cases import CaseBundle, CaseType, Note, save_case
from pair.eval.synth.generate import CaseRequest, generate_case
from pair.policies.loader import load_all
from pair.policies.mcd import MCDExport
from tests.conftest import REPO_ROOT
from tests.eval.helpers import PROFILE, PhraseWriter

CHECKLISTS = load_all(REPO_ROOT / "policies")
GEN = {"backend": "fake", "model": "fake-writer"}


def make(
    policy_id: str = "pap-osa",
    case_type: CaseType = CaseType.WRONGLY_DENIED,
    seed: int = 11,
) -> CaseBundle:
    """Generate one case with the fake writer."""
    request = CaseRequest(f"{policy_id}-01", policy_id, case_type, seed)
    return generate_case(request, CHECKLISTS[policy_id], PROFILE, PhraseWriter(), GEN)


def with_state(policy_id: str, unit: str, state: str) -> CaseBundle:
    """The first fake-written case (by seed) whose ``unit`` is in ``state``."""
    for case_type in (CaseType.FIXABLE_GAP, CaseType.TRICKY, CaseType.CORRECTLY_DENIED):
        for seed in range(1, 300):
            case = make(policy_id, case_type, seed)
            if case.states.get(unit) == state:
                return case
    raise AssertionError(f"no seed gives {unit}={state}")


def append_to_note(case: CaseBundle, doc_id: str, extra: str) -> CaseBundle:
    """Append text to one note (gold offsets stay valid)."""
    notes = [
        Note(doc_id=n.doc_id, title=n.title, text=n.text + extra)
        if n.doc_id == doc_id
        else n
        for n in case.notes
    ]
    return case.model_copy(update={"notes": notes})


def ids(findings: list[PrecheckFinding], severity: Severity | None = None) -> set[str]:
    """Check ids among findings, optionally only one severity."""
    return {f.check_id for f in findings if severity is None or f.severity is severity}


@pytest.mark.parametrize("policy_id", sorted(CHECKLISTS))
@pytest.mark.parametrize("case_type", list(CaseType))
def test_clean_case_has_no_blockers(policy_id: str, case_type: CaseType) -> None:
    """A correctly generated case passes every blocker check."""
    findings = check_case(make(policy_id, case_type), CHECKLISTS)
    assert ids(findings, Severity.BLOCKER) == set()


def test_flipped_gold_label_is_a_blocker() -> None:
    """A gold status the rule engine can't reproduce is flagged (L1)."""
    case = make()
    cid = next(iter(case.gold_statuses))
    wrong = (
        CriterionStatus.UNMET
        if case.gold_statuses[cid] is not CriterionStatus.UNMET
        else CriterionStatus.MET
    )
    bad = case.model_copy(update={"gold_statuses": {**case.gold_statuses, cid: wrong}})
    findings = check_case(bad, CHECKLISTS)
    assert any(
        f.check_id == "L1" and f.target == cid and f.severity is Severity.BLOCKER
        for f in findings
    )


def test_flipped_overall_is_a_blocker() -> None:
    """A gold overall outcome that doesn't follow from the evidence is flagged (L2)."""
    case = make()
    wrong = (
        CriterionStatus.UNMET
        if case.gold_overall is not CriterionStatus.UNMET
        else CriterionStatus.MET
    )
    assert "L2" in ids(
        check_case(case.model_copy(update={"gold_overall": wrong}), CHECKLISTS),
        Severity.BLOCKER,
    )


def test_leak_into_absent_unit_is_a_blocker() -> None:
    """A value for a unit meant to be missing is flagged (K1)."""
    case = with_state("pap-osa", "ahi_threshold", "absent")
    assert "K1" not in ids(check_case(case, CHECKLISTS))
    leaked = append_to_note(case, "report", " Overall AHI 17 per hour.")
    findings = check_case(leaked, CHECKLISTS)
    assert any(f.check_id == "K1" and f.target == "ahi_threshold" for f in findings)


def test_number_in_a_vague_unit_is_a_blocker() -> None:
    """A vague AHI that states a number is filled in, so the gold label is wrong (K1, Step 8 B2)."""
    case = with_state("pap-osa", "ahi_threshold", "vague")
    assert "K1" not in ids(check_case(case, CHECKLISTS))
    leaked = append_to_note(case, "report", " Overall AHI of 18.5.")
    findings = check_case(leaked, CHECKLISTS)
    assert any(f.check_id == "K1" and f.target == "ahi_threshold" for f in findings)


def test_second_value_is_flagged() -> None:
    """A second, unplanned AHI next to the planted one is flagged for review (K2)."""
    case = with_state("pap-osa", "ahi_threshold", "present")
    assert "K2" not in ids(check_case(case, CHECKLISTS))
    findings = check_case(
        append_to_note(case, "clinic", " Prior AHI 7.5 on an older study."), CHECKLISTS
    )
    k2 = [f for f in findings if f.check_id == "K2"]
    assert k2 and k2[0].severity is Severity.MAJOR
    assert "7.5" in k2[0].message


def test_filler_word_is_not_a_label() -> None:
    """ "for 8 months" gives no label, so "for 90 seconds" elsewhere isn't flagged."""
    case = with_state("facet-joint", "duration_and_conservative_care", "present")
    findings = check_case(
        append_to_note(case, "report", " Lesions were made for 90 seconds."), CHECKLISTS
    )
    assert not [f for f in findings if f.check_id == "K2" and "90" in f.message]


def test_planted_conflict_is_not_a_second_value() -> None:
    """A conflict the case plants on purpose (two gold values) isn't flagged."""
    case = with_state("pap-osa", "ahi_threshold", "conflicting")
    assert "K2" not in ids(check_case(case, CHECKLISTS))


def test_denial_field_mismatch_is_a_blocker() -> None:
    """Codes in gold_denial that the letter doesn't show are flagged (D1)."""
    case = make()
    bad = case.model_copy(
        update={"gold_denial": case.gold_denial.model_copy(update={"codes": ["E9999"]})}
    )
    assert "D1" in ids(check_case(bad, CHECKLISTS), Severity.BLOCKER)


def test_missing_reason_text_is_a_blocker() -> None:
    """The letter must contain the gold reason text (D1)."""
    case = make()
    bad = case.model_copy(
        update={
            "denial_text": case.denial_text.replace(
                case.gold_denial.reason_text, "We said no."
            )
        }
    )
    assert "D1" in ids(check_case(bad, CHECKLISTS), Severity.BLOCKER)


def test_reason_category_mismatch_is_major() -> None:
    """A reason category that doesn't match its reason template is flagged (D2)."""
    case = make()
    other = next(
        c
        for c in type(case.gold_denial.reason_category)
        if c is not case.gold_denial.reason_category
    )
    bad = case.model_copy(
        update={
            "gold_denial": case.gold_denial.model_copy(
                update={"reason_category": other}
            )
        }
    )
    assert "D2" in ids(check_case(bad, CHECKLISTS), Severity.MAJOR)


def test_unknown_policy_is_a_blocker() -> None:
    """A case for a policy that isn't loaded can't be checked (M0)."""
    case = make().model_copy(update={"policy_id": "nope"})
    assert ids(check_case(case, CHECKLISTS)) == {"M0"}


def test_precheck_paths_reports_unloadable_files(tmp_path: Path) -> None:
    """A broken case file becomes an M0 blocker instead of a crash."""
    good = save_case(make(), tmp_path / "pap-osa" / "pap-osa-01.json")
    broken = tmp_path / "pap-osa" / "pap-osa-02.json"
    broken.write_text("{}", encoding="utf-8")
    findings = precheck_paths([good, broken], CHECKLISTS)
    assert [(f.case_id, f.check_id) for f in findings] == [("pap-osa-02", "M0")]


def test_finding_serializes() -> None:
    """Findings round-trip to JSON for the critic."""
    finding = PrecheckFinding("c-1", "K1", "ahi", Severity.BLOCKER, "leak")
    assert json.loads(json.dumps(finding.to_json()))["severity"] == "blocker"


@pytest.mark.mcd
def test_real_policy_clauses_are_verbatim(mcd_export_dir: Path) -> None:
    """Every clause in the shipped policies is found in the MCD export (P1, mechanical part)."""
    assert check_policy_sources(CHECKLISTS, MCDExport(mcd_export_dir)) == []


def test_cli_precheck_writes_jsonl(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``pair audit precheck`` needs no LLM config and writes one JSONL with a meta line."""
    save_case(make(), tmp_path / "cases" / "pap-osa" / "pap-osa-01.json")
    out = tmp_path / "audit"
    code = main(
        [
            "audit",
            "precheck",
            "--cases",
            str(tmp_path / "cases"),
            "--out",
            str(out),
            "--no-mcd",
        ]
    )
    assert code == 0
    logs = list(out.glob("precheck-*.jsonl"))
    assert len(logs) == 1
    lines = [
        json.loads(line) for line in logs[0].read_text(encoding="utf-8").splitlines()
    ]
    assert lines[0]["kind"] == "meta" and lines[0]["n_cases"] == 1
    assert "0 blocker" in capsys.readouterr().out
