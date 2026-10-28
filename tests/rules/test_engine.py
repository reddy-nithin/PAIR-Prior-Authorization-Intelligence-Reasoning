"""Tests for the deterministic rule engine (spec §6.1, ADR-0012)."""

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from pair.contracts import Checklist, CriterionStatus, Evidence, VariableType, Verdict
from pair.policies.loader import load_all
from pair.rules.engine import RuleEngineError, _fits, run_rules

MET, UNMET, INSUFFICIENT = CriterionStatus.MET, CriterionStatus.UNMET, CriterionStatus.INSUFFICIENT
D0 = dt.date(2026, 3, 1)


@pytest.fixture(scope="module")
def policies(repo_root: Path) -> dict[str, Checklist]:
    """The shipped policy checklists."""
    return load_all(repo_root / "policies")


def gap_message(criterion_id: str, status: CriterionStatus) -> str:
    """A stand-in gap template: names the criterion and status."""
    return f"gap:{criterion_id}:{status.value}"


def ev(criterion_id: str, variable: str, value: Any, status: str = "asserted", text: str | None = None, doc_id: str = "note-1") -> Evidence:
    """Build one Evidence item whose span matches its offsets."""
    span = text or f"{variable} {value}"
    return Evidence(
        criterion_id=criterion_id,
        variable=variable,
        value=value,
        span_text=span,
        char_start=10,
        char_end=10 + len(span),
        doc_id=doc_id,
        status=status,  # type: ignore[arg-type]
    )


def pap_met() -> list[Evidence]:
    """Evidence that meets every PAP criterion."""
    return [
        ev("f2f_visit", "evaluation_date", D0),
        ev("f2f_visit", "sleep_test_date", D0 + dt.timedelta(days=14)),
        ev("ahi_threshold", "ahi", 22.5),
        ev("ahi_threshold", "event_count", 140),
        ev("adherence", "pct_nights_4h_best_30d", 80),
        ev("adherence", "window_in_first_90_days", True),
        ev("reevaluation", "therapy_start_date", D0),
        ev("reevaluation", "reevaluation_date", D0 + dt.timedelta(days=60)),
        ev("reevaluation", "symptoms_improved", True),
    ]


def status_of(verdict: Verdict, criterion_id: str) -> CriterionStatus:
    """Return one criterion's status from a verdict."""
    return next(r.status for r in verdict.results if r.criterion_id == criterion_id)


def result_of(verdict: Verdict, criterion_id: str) -> Any:
    """Return one criterion's result from a verdict."""
    return next(r for r in verdict.results if r.criterion_id == criterion_id)


def test_all_met_gives_met_verdict_and_no_gaps(policies: dict[str, Checklist]) -> None:
    """Every criterion met: overall met, no gaps, results in checklist order."""
    verdict = run_rules(policies["pap-osa"], pap_met(), {"initial": False}, gap_message)
    assert verdict.overall is MET
    assert verdict.gaps == []
    assert [r.criterion_id for r in verdict.results] == list(policies["pap-osa"].criterion_ids)
    assert verdict.policy_id == "pap-osa"


def test_no_evidence_is_insufficient_everywhere(policies: dict[str, Checklist]) -> None:
    """A silent record makes every criterion insufficient, with one gap each."""
    for checklist in policies.values():
        context = dict.fromkeys(checklist.context, True)
        verdict = run_rules(checklist, [], context, gap_message)
        assert {r.status for r in verdict.results} == {INSUFFICIENT}, checklist.id
        assert len(verdict.gaps) == len(checklist.criteria)


@pytest.mark.parametrize(
    ("ahi", "events", "symptoms", "expected"),
    [
        (15, 30, None, MET),
        (15, 29, None, UNMET),
        (14, 10, ["hypertension"], MET),
        (14, 9, ["hypertension"], UNMET),
        (5, 10, ["insomnia"], MET),
        (14, 40, None, INSUFFICIENT),
        (4.9, 40, None, UNMET),
        (18, None, None, INSUFFICIENT),
    ],
)
def test_ahi_boundaries(policies: dict[str, Checklist], ahi: float, events: int | None, symptoms: list[str] | None, expected: CriterionStatus) -> None:
    """AHI 15 / 14 / 5 boundaries with their minimum event counts on a short recording (LCD L33718)."""
    evidence = [ev("ahi_threshold", "ahi", ahi), ev("ahi_threshold", "sleep_or_recording_hours", 1.5)]
    if events is not None:
        evidence.append(ev("ahi_threshold", "event_count", events))
    if symptoms is not None:
        evidence.append(ev("ahi_threshold", "symptoms_or_conditions", symptoms))
    verdict = run_rules(policies["pap-osa"], evidence, {"initial": True}, gap_message)
    assert status_of(verdict, "ahi_threshold") is expected


def test_negated_symptom_alone_stays_insufficient(policies: dict[str, Checklist]) -> None:
    """'Denies daytime sleepiness' binds nothing, so AHI 10 is insufficient, not unmet."""
    evidence = [
        ev("ahi_threshold", "ahi", 10),
        ev("ahi_threshold", "event_count", 60),
        ev("ahi_threshold", "symptoms_or_conditions", ["excessive daytime sleepiness"], status="negated", text="denies daytime sleepiness"),
    ]
    verdict = run_rules(policies["pap-osa"], evidence, {"initial": True}, gap_message)
    result = result_of(verdict, "ahi_threshold")
    assert result.status is INSUFFICIENT
    assert len(result.evidence) == 3
    assert "negated" in result.trace


def test_uncertain_value_binds_nothing(policies: dict[str, Checklist]) -> None:
    """A hedged AHI ('possibly around 20') doesn't count as evidence."""
    evidence = [ev("ahi_threshold", "ahi", 20, status="uncertain"), ev("ahi_threshold", "event_count", 120)]
    verdict = run_rules(policies["pap-osa"], evidence, {"initial": True}, gap_message)
    assert status_of(verdict, "ahi_threshold") is INSUFFICIENT
    assert "uncertain" in result_of(verdict, "ahi_threshold").trace


def test_list_items_from_several_mentions_are_merged(policies: dict[str, Checklist]) -> None:
    """Symptoms found in separate notes add up; a plain string counts as one item."""
    evidence = [
        ev("ahi_threshold", "ahi", 8),
        ev("ahi_threshold", "event_count", 30),
        ev("ahi_threshold", "symptoms_or_conditions", "hypertension", doc_id="note-2"),
        ev("ahi_threshold", "symptoms_or_conditions", ["insomnia", "hypertension"], doc_id="note-3"),
    ]
    verdict = run_rules(policies["pap-osa"], evidence, {"initial": True}, gap_message)
    result = result_of(verdict, "ahi_threshold")
    assert result.status is MET
    assert "['hypertension', 'insomnia']" in result.trace


def test_conflicting_values_are_insufficient_with_both_spans(policies: dict[str, Checklist]) -> None:
    """Two different AHI values: insufficient, both shown, even though both exceed 15."""
    evidence = [
        ev("ahi_threshold", "ahi", 18.0, text="AHI 18", doc_id="note-1"),
        ev("ahi_threshold", "ahi", 22.0, text="AHI of 22", doc_id="note-2"),
        ev("ahi_threshold", "event_count", 120),
    ]
    verdict = run_rules(policies["pap-osa"], evidence, {"initial": True}, gap_message)
    result = result_of(verdict, "ahi_threshold")
    assert result.status is INSUFFICIENT
    assert "conflict" in result.trace
    assert "AHI 18" in result.trace and "AHI of 22" in result.trace


def test_repeated_identical_value_is_not_a_conflict(policies: dict[str, Checklist]) -> None:
    """The same AHI quoted in two notes agrees with itself."""
    evidence = [
        ev("ahi_threshold", "ahi", 18, doc_id="note-1"),
        ev("ahi_threshold", "ahi", 18.0, doc_id="note-2"),
        ev("ahi_threshold", "event_count", 120),
    ]
    verdict = run_rules(policies["pap-osa"], evidence, {"initial": True}, gap_message)
    assert status_of(verdict, "ahi_threshold") is MET


def test_missing_sleep_test_date_is_insufficient(policies: dict[str, Checklist]) -> None:
    """The visit date alone can't show it came before the test."""
    verdict = run_rules(policies["pap-osa"], [ev("f2f_visit", "evaluation_date", D0)], {"initial": True}, gap_message)
    assert status_of(verdict, "f2f_visit") is INSUFFICIENT


def test_visit_after_sleep_test_is_unmet(policies: dict[str, Checklist]) -> None:
    """An out-of-order visit is a definite fail."""
    evidence = [ev("f2f_visit", "evaluation_date", D0 + dt.timedelta(days=1)), ev("f2f_visit", "sleep_test_date", D0)]
    verdict = run_rules(policies["pap-osa"], evidence, {"initial": True}, gap_message)
    assert status_of(verdict, "f2f_visit") is UNMET


@pytest.mark.parametrize(("pct", "expected"), [(70, MET), (69.9, UNMET)])
def test_adherence_threshold(policies: dict[str, Checklist], pct: float, expected: CriterionStatus) -> None:
    """At least 70% of nights with 4+ hours."""
    evidence = [ev("adherence", "pct_nights_4h_best_30d", pct), ev("adherence", "window_in_first_90_days", True)]
    verdict = run_rules(policies["pap-osa"], evidence, {"initial": False}, gap_message)
    assert status_of(verdict, "adherence") is expected


@pytest.mark.parametrize(("days", "expected"), [(29, UNMET), (30, MET), (90, MET), (91, MET)])
def test_reevaluation_window(policies: dict[str, Checklist], days: int, expected: CriterionStatus) -> None:
    """Re-evaluation no sooner than the 31st day (gap 30); a later visit still counts (ADR-0015)."""
    evidence = [
        ev("reevaluation", "therapy_start_date", D0),
        ev("reevaluation", "reevaluation_date", D0 + dt.timedelta(days=days)),
        ev("reevaluation", "symptoms_improved", True),
    ]
    verdict = run_rules(policies["pap-osa"], evidence, {"initial": False}, gap_message)
    assert status_of(verdict, "reevaluation") is expected


def test_initial_coverage_skips_adherence(policies: dict[str, Checklist]) -> None:
    """For initial coverage, missing adherence data doesn't block an overall met."""
    evidence = [e for e in pap_met() if e.criterion_id in {"f2f_visit", "ahi_threshold"}]
    verdict = run_rules(policies["pap-osa"], evidence, {"initial": True}, gap_message)
    assert verdict.overall is MET
    assert status_of(verdict, "adherence") is INSUFFICIENT
    assert {g.criterion_id for g in verdict.gaps} == {"adherence", "reevaluation"}


def test_missing_context_flag_is_unknown(policies: dict[str, Checklist]) -> None:
    """Without the ``initial`` flag, missing adherence leaves the overall result insufficient."""
    evidence = [e for e in pap_met() if e.criterion_id in {"f2f_visit", "ahi_threshold"}]
    verdict = run_rules(policies["pap-osa"], evidence, {}, gap_message)
    assert verdict.overall is INSUFFICIENT


def test_unmet_critical_criterion_makes_overall_unmet(policies: dict[str, Checklist]) -> None:
    """One definite fail in an AND-ed criterion fails the checklist."""
    evidence = [e for e in pap_met() if e.variable != "ahi"] + [ev("ahi_threshold", "ahi", 3)]
    verdict = run_rules(policies["pap-osa"], evidence, {"initial": False}, gap_message)
    assert verdict.overall is UNMET
    assert verdict.gaps[0].message == "gap:ahi_threshold:unmet"


def oxygen_base() -> list[Evidence]:
    """Home-oxygen evidence meeting everything except the blood-gas groups."""
    return [
        ev("ordered_and_evaluated", "practitioner_ordered_and_reviewed", True),
        ev("ordered_and_evaluated", "rx_from_inpatient_stay", False),
        ev("ordered_and_evaluated", "symptoms_noted_at_test", True),
        ev("qualified_tester", "tested_by_qualified_provider", True),
        ev("home_benefit", "expected_to_improve", True),
    ]


def test_oxygen_group1_or_group2(policies: dict[str, Checklist]) -> None:
    """Group I met is enough even when group II has no evidence."""
    evidence = [*oxygen_base(), ev("group1_blood_gas", "spo2", 86), ev("group1_blood_gas", "at_rest_on_room_air", True)]
    verdict = run_rules(policies["home-oxygen"], evidence, {}, gap_message)
    assert status_of(verdict, "group1_blood_gas") is MET
    assert status_of(verdict, "group2_blood_gas") is INSUFFICIENT
    assert verdict.overall is MET


def test_oxygen_group2_with_condition(policies: dict[str, Checklist]) -> None:
    """Group II: SpO2 89 plus a qualifying condition."""
    evidence = [
        *oxygen_base(),
        ev("group2_blood_gas", "spo2", 89),
        ev("group2_blood_gas", "group2_conditions", ["dependent edema"]),
        ev("group1_blood_gas", "spo2", 89),
        ev("group1_blood_gas", "at_rest_on_room_air", True),
    ]
    verdict = run_rules(policies["home-oxygen"], evidence, {}, gap_message)
    # SpO2 89 fails group I, but no PaO2 was taken, and a PaO2 <= 55 would still qualify.
    assert status_of(verdict, "group1_blood_gas") is INSUFFICIENT
    assert status_of(verdict, "group2_blood_gas") is MET
    assert verdict.overall is MET


def facet_base() -> list[Evidence]:
    """Facet evidence meeting every general criterion."""
    return [
        ev("pain_and_function", "pain_score", 6),
        ev("pain_and_function", "pain_is_axial", True),
        ev("pain_and_function", "functional_deficit_documented", True),
        ev("pain_and_function", "disability_scale_at_baseline", True),
        ev("duration_and_conservative_care", "pain_duration_months", 7),
        ev("duration_and_conservative_care", "conservative_care_failed", True),
        ev("no_untreated_radiculopathy", "untreated_radiculopathy", False, text="no radicular symptoms"),
        ev("no_untreated_radiculopathy", "untreated_neurogenic_claudication", False, text="no neurogenic claudication"),
        ev("no_other_pathology", "other_pathology_found", False),
    ]


@pytest.mark.parametrize(("diagnostic_only", "expected"), [(True, MET), (False, INSUFFICIENT)])
def test_facet_diagnostic_only_skips_block_relief(policies: dict[str, Checklist], diagnostic_only: bool, expected: CriterionStatus) -> None:
    """A first diagnostic block doesn't need prior block relief; RFA does."""
    verdict = run_rules(policies["facet-joint"], facet_base(), {"diagnostic_only": diagnostic_only}, gap_message)
    assert verdict.overall is expected


@pytest.mark.parametrize(("score", "expected"), [(3, UNMET), (4, MET)])
def test_pain_score_four_is_moderate(policies: dict[str, Checklist], score: int, expected: CriterionStatus) -> None:
    """PAIR reads 'moderate' as 4 or more on 0 to 10 (ADR-0015, Boonstra et al. 2014)."""
    evidence = [e for e in facet_base() if e.variable != "pain_score"] + [ev("pain_and_function", "pain_score", score)]
    verdict = run_rules(policies["facet-joint"], evidence, {"diagnostic_only": True}, gap_message)
    assert status_of(verdict, "pain_and_function") is expected


def test_trace_names_rule_values_and_spans(policies: dict[str, Checklist]) -> None:
    """The trace shows the rule, each bound value with its source, and the outcome."""
    evidence = [ev("ahi_threshold", "ahi", 22.5, text="AHI 22.5 events/hr", doc_id="psg-report"), ev("ahi_threshold", "event_count", 140)]
    trace = result_of(run_rules(policies["pap-osa"], evidence, {"initial": True}, gap_message), "ahi_threshold").trace
    assert policies["pap-osa"].criteria[1].rule in trace
    assert "ahi = 22.5" in trace
    assert "psg-report" in trace and "AHI 22.5 events/hr" in trace
    assert "symptoms_or_conditions = missing" in trace
    assert trace.rstrip().endswith("met")


def test_wrongly_typed_value_is_ignored_and_noted(policies: dict[str, Checklist]) -> None:
    """A text value for a number variable can't be used; the trace says why."""
    evidence = [ev("ahi_threshold", "ahi", "eighteen"), ev("ahi_threshold", "event_count", 120)]
    result = result_of(run_rules(policies["pap-osa"], evidence, {"initial": True}, gap_message), "ahi_threshold")
    assert result.status is INSUFFICIENT
    assert "ignored" in result.trace


@pytest.mark.parametrize(
    ("value", "variable", "usable"),
    [(True, "symptoms_improved", True), (1, "symptoms_improved", False), (True, "pct_nights_4h_best_30d", False), ("2026-03-01", "therapy_start_date", False)],
)
def test_value_type_checks(policies: dict[str, Checklist], value: Any, variable: str, usable: bool) -> None:
    """Bools aren't numbers, numbers aren't bools, and dates must be real dates."""
    criterion = "reevaluation" if variable in {"symptoms_improved", "therapy_start_date"} else "adherence"
    result = result_of(run_rules(policies["pap-osa"], [ev(criterion, variable, value)], {"initial": False}, gap_message), criterion)
    assert ("ignored" not in result.trace) is usable


def test_mention_without_value_binds_nothing(policies: dict[str, Checklist]) -> None:
    """An asserted mention with no value (e.g. 'sleep study done') leaves the variable missing."""
    result = result_of(run_rules(policies["pap-osa"], [ev("ahi_threshold", "ahi", None, text="sleep study done")], {"initial": True}, gap_message), "ahi_threshold")
    assert "ahi = missing" in result.trace


def test_evidence_for_unknown_criterion_is_an_error(policies: dict[str, Checklist]) -> None:
    """Evidence must name a criterion of the checklist being applied."""
    with pytest.raises(RuleEngineError, match="not_a_criterion"):
        run_rules(policies["pap-osa"], [ev("not_a_criterion", "ahi", 18)], {"initial": True}, gap_message)


def test_evidence_for_undeclared_variable_is_an_error(policies: dict[str, Checklist]) -> None:
    """Evidence must supply a variable the criterion's rule declares."""
    with pytest.raises(RuleEngineError, match="spo2"):
        run_rules(policies["pap-osa"], [ev("ahi_threshold", "spo2", 88)], {"initial": True}, gap_message)


def test_unknown_context_flag_is_an_error(policies: dict[str, Checklist]) -> None:
    """Context flags must be declared by the checklist."""
    with pytest.raises(RuleEngineError, match="urgent"):
        run_rules(policies["pap-osa"], [], {"urgent": True}, gap_message)


def test_non_bool_context_flag_is_an_error(policies: dict[str, Checklist]) -> None:
    """A context flag must be True, False or missing."""
    with pytest.raises(RuleEngineError, match="initial"):
        run_rules(policies["pap-osa"], [], {"initial": "yes"}, gap_message)  # type: ignore[dict-item]


@pytest.mark.parametrize(
    ("var_type", "value", "fits"),
    [
        (VariableType.TEXT, "left L4-L5", True),
        (VariableType.TEXT, 4, False),
        (VariableType.LIST, "insomnia", True),
        (VariableType.LIST, ["insomnia"], True),
        (VariableType.LIST, 3, False),
        (VariableType.DATE, D0, True),
    ],
)
def test_value_fits_declared_type(var_type: VariableType, value: Any, fits: bool) -> None:
    """Each variable type accepts only its own normalized values."""
    assert _fits(var_type, value) is fits
