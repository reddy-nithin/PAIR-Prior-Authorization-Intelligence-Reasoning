"""Tests for the claim builder: one claim slot per bound record fact (ADR-0018)."""

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from pair.contracts import Checklist, CriterionStatus, Evidence, Verdict
from pair.draft.claims import ClaimPlanError, plan_claims
from pair.policies.loader import load_all
from pair.rules.engine import run_rules

MET, UNMET, INSUFFICIENT = CriterionStatus.MET, CriterionStatus.UNMET, CriterionStatus.INSUFFICIENT

NOTE = (
    "Seen in sleep clinic on 2026-03-02 for snoring. "
    "Home sleep test on 2026-03-10: AHI 18.2 events/hr over 6.5 hours of recording. "
    "Download shows use of 4 hours or more on 82% of nights in the best 30-day window, "
    "within the first 90 days. "
    "Patient denies morning headaches."
)
DOC_ID = "note-1"


@pytest.fixture(scope="module")
def pap(repo_root: Path) -> Checklist:
    """The shipped PAP checklist."""
    return load_all(repo_root / "policies")["pap-osa"]


def gap_message(criterion_id: str, status: CriterionStatus) -> str:
    """A stand-in gap template."""
    return f"gap:{criterion_id}:{status.value}"


def ev(criterion_id: str, variable: str, value: Any, span: str, status: str = "asserted") -> Evidence:
    """Evidence whose span is found verbatim in ``NOTE``."""
    start = NOTE.index(span)
    return Evidence(
        criterion_id=criterion_id,
        variable=variable,
        value=value,
        span_text=span,
        char_start=start,
        char_end=start + len(span),
        doc_id=DOC_ID,
        status=status,  # type: ignore[arg-type]
    )


def f2f_and_ahi() -> list[Evidence]:
    """Evidence that makes ``f2f_visit`` and ``ahi_threshold`` met."""
    return [
        ev("f2f_visit", "evaluation_date", dt.date(2026, 3, 2), "Seen in sleep clinic on 2026-03-02"),
        ev("f2f_visit", "sleep_test_date", dt.date(2026, 3, 10), "Home sleep test on 2026-03-10"),
        ev("ahi_threshold", "ahi", 18.2, "AHI 18.2 events/hr"),
        ev("ahi_threshold", "sleep_or_recording_hours", 6.5, "6.5 hours of recording"),
    ]


def verdict(checklist: Checklist, evidence: list[Evidence], initial: bool | None = True) -> Verdict:
    """Run the real rule engine."""
    return run_rules(checklist, evidence, {"initial": initial}, gap_message)


def test_met_criterion_gets_one_slot_per_fact(pap: Checklist) -> None:
    """f2f_visit needs two dates from two spans, so it gets two claim slots."""
    plan = plan_claims(pap, verdict(pap, f2f_and_ahi()))

    f2f = [slot for slot in plan.slots if slot.criterion_id == "f2f_visit"]
    assert [slot.variables for slot in f2f] == [("evaluation_date",), ("sleep_test_date",)]
    assert [slot.evidence_cite.quote for slot in f2f] == [
        "Seen in sleep clinic on 2026-03-02",
        "Home sleep test on 2026-03-10",
    ]


def test_policy_cite_is_the_criterion_clause(pap: Checklist) -> None:
    """The policy quote is the verbatim clause, cited to its source."""
    plan = plan_claims(pap, verdict(pap, f2f_and_ahi()))
    criterion = next(c for c in pap.criteria if c.id == "ahi_threshold")

    for slot in (s for s in plan.slots if s.criterion_id == "ahi_threshold"):
        assert slot.policy_cite.quote == criterion.clause
        assert slot.policy_cite.source_id == criterion.source_id


def test_evidence_cite_offsets_point_at_the_quote(pap: Checklist) -> None:
    """Every record quote equals the document text at its offsets."""
    plan = plan_claims(pap, verdict(pap, f2f_and_ahi()))

    assert plan.slots
    for slot in plan.slots:
        cite = slot.evidence_cite
        assert cite.doc_id == DOC_ID
        assert NOTE[cite.char_start : cite.char_end] == cite.quote


def test_one_span_supplying_two_variables_is_one_slot(pap: Checklist) -> None:
    """One quote is one fact for the letter, even when it fills two rule variables."""
    span = "use of 4 hours or more on 82% of nights in the best 30-day window"
    evidence = [
        *f2f_and_ahi(),
        ev("adherence", "pct_nights_4h_best_30d", 82, span),
        ev("adherence", "window_in_first_90_days", True, span),
        ev("reevaluation", "symptoms_improved", True, "snoring"),
    ]
    plan = plan_claims(pap, verdict(pap, evidence))

    adherence = [slot for slot in plan.slots if slot.criterion_id == "adherence"]
    assert len(adherence) == 1
    assert adherence[0].variables == ("pct_nights_4h_best_30d", "window_in_first_90_days")


def test_multi_variable_criterion_splits_by_span(pap: Checklist) -> None:
    """adherence from two different spans gives two slots."""
    evidence = [
        *f2f_and_ahi(),
        ev("adherence", "pct_nights_4h_best_30d", 82, "82% of nights"),
        ev("adherence", "window_in_first_90_days", True, "within the first 90 days"),
    ]
    plan = plan_claims(pap, verdict(pap, evidence))

    adherence = [slot for slot in plan.slots if slot.criterion_id == "adherence"]
    assert [slot.variables for slot in adherence] == [
        ("pct_nights_4h_best_30d",),
        ("window_in_first_90_days",),
    ]


def test_unmet_and_insufficient_criteria_get_no_slots(pap: Checklist) -> None:
    """Only met criteria are argued; the others are skipped with their gap message."""
    evidence = [
        *f2f_and_ahi()[:2],
        ev("ahi_threshold", "ahi", 3.1, "AHI 18.2 events/hr"),
        ev("ahi_threshold", "sleep_or_recording_hours", 6.5, "6.5 hours of recording"),
    ]
    result = verdict(pap, evidence)
    plan = plan_claims(pap, result)

    assert {slot.criterion_id for slot in plan.slots} == {"f2f_visit"}
    skipped = {item.criterion_id: item for item in plan.skipped}
    assert skipped["ahi_threshold"].status is UNMET
    assert skipped["ahi_threshold"].message == "gap:ahi_threshold:unmet"
    assert skipped["adherence"].status is INSUFFICIENT
    assert set(skipped) == {"ahi_threshold", "adherence", "reevaluation"}


def test_conflicting_evidence_never_yields_a_slot(pap: Checklist) -> None:
    """Two different AHI values make the criterion insufficient, so nothing is claimed."""
    evidence = [*f2f_and_ahi(), ev("ahi_threshold", "ahi", 25.0, "AHI 18.2 events/hr")]
    plan = plan_claims(pap, verdict(pap, evidence))

    assert all(slot.criterion_id != "ahi_threshold" for slot in plan.slots)
    assert any(item.criterion_id == "ahi_threshold" and item.status is INSUFFICIENT for item in plan.skipped)


def test_unbound_evidence_on_a_met_criterion_is_not_claimed(pap: Checklist) -> None:
    """Negated, uncertain, valueless and wrong-type items aren't facts the rule used."""
    evidence = [
        *f2f_and_ahi(),
        ev("ahi_threshold", "symptoms_or_conditions", ["morning headaches"], "denies morning headaches", "negated"),
        ev("ahi_threshold", "event_count", None, "events/hr over 6.5 hours"),
        ev("ahi_threshold", "event_count", "many", "AHI 18.2 events/hr over"),
        ev("ahi_threshold", "event_count", 118, "over 6.5 hours", "uncertain"),
    ]
    result = verdict(pap, evidence)
    assert next(r for r in result.results if r.criterion_id == "ahi_threshold").status is MET

    plan = plan_claims(pap, result)
    quotes = {slot.evidence_cite.quote for slot in plan.slots if slot.criterion_id == "ahi_threshold"}
    assert quotes == {"AHI 18.2 events/hr", "6.5 hours of recording"}


def test_slots_follow_checklist_order_then_document_order(pap: Checklist) -> None:
    """Criteria in checklist order; within a criterion, by document position."""
    evidence = list(reversed(f2f_and_ahi()))
    plan = plan_claims(pap, verdict(pap, evidence))

    assert [slot.criterion_id for slot in plan.slots] == ["f2f_visit", "f2f_visit", "ahi_threshold", "ahi_threshold"]
    starts = [slot.evidence_cite.char_start for slot in plan.slots if slot.criterion_id == "ahi_threshold"]
    assert starts == sorted(starts)


def test_verdict_for_another_policy_is_rejected(pap: Checklist) -> None:
    """A verdict must belong to the checklist it is planned against."""
    other = verdict(pap, f2f_and_ahi()).model_copy(update={"policy_id": "home-oxygen"})

    with pytest.raises(ClaimPlanError, match="home-oxygen"):
        plan_claims(pap, other)


def test_result_for_unknown_criterion_is_rejected(pap: Checklist) -> None:
    """A result naming a criterion the checklist lacks is an error, not skipped silently."""
    result = verdict(pap, f2f_and_ahi())
    bad = result.results[0].model_copy(update={"criterion_id": "made_up"})
    broken = Verdict.model_construct(**{**dict(result), "results": [bad, *result.results[1:]]})

    with pytest.raises(ClaimPlanError, match="made_up"):
        plan_claims(pap, broken)


def test_missing_result_for_a_criterion_is_rejected(pap: Checklist) -> None:
    """Every checklist criterion must have a result; a gap in the verdict is an error."""
    result = verdict(pap, f2f_and_ahi())
    partial = Verdict.model_construct(**{**dict(result), "results": result.results[1:]})

    with pytest.raises(ClaimPlanError, match="f2f_visit"):
        plan_claims(pap, partial)
