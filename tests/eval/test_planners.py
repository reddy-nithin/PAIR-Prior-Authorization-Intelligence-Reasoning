"""Every planned state must give the gold statuses the rule engine computes (T9)."""

import random
import re

import pytest

from pair.contracts import CriterionStatus
from pair.eval.cases import CaseType
from pair.eval.synth.planners import (
    DATES,
    UNITS,
    PlanError,
    plan_case,
    plan_from_states,
    verify_plan,
)
from pair.policies.loader import load_all
from tests.conftest import REPO_ROOT

CHECKLISTS = load_all(REPO_ROOT / "policies")
ALL_STATES = [
    (policy_id, unit.name, state)
    for policy_id, units in UNITS.items()
    for unit in units
    for state in unit.states
]


@pytest.mark.parametrize(("policy_id", "unit", "state"), ALL_STATES)
def test_every_state_matches_the_engine(policy_id: str, unit: str, state: str) -> None:
    """Cross-check: declared status == engine status on the planted values, for every state."""
    checklist = CHECKLISTS[policy_id]
    rng = random.Random(1)
    states = {u.name: "present" for u in UNITS[policy_id]}
    states[unit] = state
    spec = plan_from_states(
        checklist, CaseType.TRICKY, states, DATES[policy_id](rng), rng
    )
    gold = verify_plan(spec, checklist)
    assert {k: v for k, v in gold.items() if k != "__overall__"} == spec.expected


def test_planners_cover_every_policy() -> None:
    """Each real policy has a planner whose units cover all its criteria."""
    assert set(UNITS) == set(CHECKLISTS)
    for policy_id, units in UNITS.items():
        covered = sorted(c for u in units for c in u.criterion_ids)
        assert covered == sorted(c.id for c in CHECKLISTS[policy_id].criteria)


def test_same_seed_gives_same_spec() -> None:
    """Plans are deterministic for a seed."""
    a = plan_case(CHECKLISTS["pap-osa"], CaseType.FIXABLE_GAP, random.Random(7))
    b = plan_case(CHECKLISTS["pap-osa"], CaseType.FIXABLE_GAP, random.Random(7))
    assert a == b


@pytest.mark.parametrize("policy_id", sorted(CHECKLISTS))
@pytest.mark.parametrize("seed", range(15))
def test_case_types_give_their_outcome(policy_id: str, seed: int) -> None:
    """A is met overall, B insufficient (no unmet), C unmet, D has one tricky unit."""
    checklist = CHECKLISTS[policy_id]
    outcomes = {}
    for case_type in CaseType:
        spec = plan_case(checklist, case_type, random.Random(seed))
        outcomes[case_type] = (spec, verify_plan(spec, checklist)["__overall__"])
    assert outcomes[CaseType.WRONGLY_DENIED][1] is CriterionStatus.MET
    b_spec, b_overall = outcomes[CaseType.FIXABLE_GAP]
    assert b_overall is CriterionStatus.INSUFFICIENT
    assert CriterionStatus.UNMET not in b_spec.expected.values()
    assert outcomes[CaseType.CORRECTLY_DENIED][1] is CriterionStatus.UNMET
    d_states = outcomes[CaseType.TRICKY][0].states.values()
    assert (
        sum(s in {"negated", "conflicting", "vague", "out_of_window"} for s in d_states)
        == 1
    )


def test_correctly_denied_prefers_critical_criteria() -> None:
    """Type C fails a critical criterion when one can fail."""
    checklist = CHECKLISTS["facet-joint"]
    critical = {c.id for c in checklist.criteria if c.critical}
    for seed in range(10):
        spec = plan_case(checklist, CaseType.CORRECTLY_DENIED, random.Random(seed))
        failed = [
            cid
            for cid, status in spec.expected.items()
            if status is CriterionStatus.UNMET
        ]
        assert set(failed) <= critical


def test_absent_units_list_topics_and_forbidden_patterns() -> None:
    """An absent AHI unit tells the writer what to leave out and how to detect a leak."""
    checklist = CHECKLISTS["pap-osa"]
    rng = random.Random(3)
    states = {u.name: "present" for u in UNITS["pap-osa"]}
    states["ahi_threshold"] = "absent"
    spec = plan_from_states(
        checklist, CaseType.FIXABLE_GAP, states, DATES["pap-osa"](rng), rng
    )
    assert any("AHI" in topic for topic in spec.absent_topics)
    assert spec.forbidden


def test_facet_vague_pain_is_not_a_verbal_rating() -> None:
    """A verbal "moderate"/"severe" now meets the rule (ADR-0015), so the vague phrase can't be one."""
    outcome = next(
        u for u in UNITS["facet-joint"] if u.name == "pain_and_function"
    ).states["vague"]({})
    phrase = next(
        p.phrase for p in outcome.plants if p.variable == "pain_score"
    ).lower()
    assert not any(word in phrase for word in ("mild", "moderate", "severe"))


def test_oxygen_conflict_readings_share_test_conditions() -> None:
    """Both conflicting SpO2 readings are at rest on room air, or they aren't a conflict (seed-02)."""
    outcome = next(u for u in UNITS["home-oxygen"] if u.name == "blood_gas").states[
        "conflicting"
    ]({})
    readings = [p.phrase.lower() for p in outcome.plants if p.variable == "spo2"]
    assert len(readings) == 2
    assert all("at rest" in r and "room air" in r for r in readings)


def test_oxygen_failing_time_of_need_is_an_inpatient_test_outside_two_days() -> None:
    """The failing state is a real L33797 failure: inpatient test more than 2 days before discharge (seed-06)."""
    dates = DATES["home-oxygen"](random.Random(4))
    outcome = next(
        u for u in UNITS["home-oxygen"] if u.name == "ordered_and_evaluated"
    ).states["failing"](dates)
    values = {p.variable: p.value for p in outcome.plants}
    assert values["rx_from_inpatient_stay"] is True
    assert (values["discharge_date"] - values["test_date"]).days > 2


def test_pap_sleep_test_states_give_recording_time() -> None:
    """A sleep report with an AHI number also states its recording time, in the report."""
    unit = next(u for u in UNITS["pap-osa"] if u.name == "ahi_threshold")
    for name, state in unit.states.items():
        plants = state({})
        if any(p.variable == "ahi" and p.value is not None for p in plants.plants):
            hours = [
                p for p in plants.plants if p.variable == "sleep_or_recording_hours"
            ]
            assert hours and all(p.doc_id == "report" for p in hours), name


def test_plant_phrases_use_no_gendered_pronouns() -> None:
    """Phrases are planted for patients of either sex, so they can't say he or she (pap-osa-04)."""
    pronoun = re.compile(r"\b(he|she|his|her|him|hers)\b", re.IGNORECASE)
    for policy_id, units in UNITS.items():
        dates = DATES[policy_id](random.Random(0))
        for unit in units:
            for name, state in unit.states.items():
                for plant in state(dates).plants:
                    assert not pronoun.search(plant.phrase), (
                        policy_id,
                        unit.name,
                        name,
                        plant.phrase,
                    )


def test_unknown_state_or_policy_raises() -> None:
    """Bad states and unplanned policies fail loudly."""
    checklist = CHECKLISTS["pap-osa"]
    rng = random.Random(0)
    with pytest.raises(PlanError, match="unknown states"):
        plan_from_states(
            checklist,
            CaseType.TRICKY,
            {"adherence": "teleported"},
            DATES["pap-osa"](rng),
            rng,
        )
    other = checklist.model_copy(update={"id": "knee-brace"})
    with pytest.raises(PlanError, match="no case planner"):
        plan_case(other, CaseType.TRICKY, rng)


def test_planner_units_must_match_criteria() -> None:
    """A checklist whose criteria differ from the planner's units is rejected."""
    checklist = CHECKLISTS["pap-osa"]
    trimmed = checklist.model_copy(update={"criteria": checklist.criteria[:2]})
    with pytest.raises(PlanError, match="don't match"):
        plan_case(trimmed, CaseType.TRICKY, random.Random(0))


def test_declared_status_mismatch_is_caught() -> None:
    """If a declared status is wrong, verify_plan raises."""
    checklist = CHECKLISTS["pap-osa"]
    rng = random.Random(0)
    spec = plan_case(checklist, CaseType.WRONGLY_DENIED, rng)
    broken = type(spec)(
        **{
            **spec.__dict__,
            "expected": {**spec.expected, "f2f_visit": CriterionStatus.UNMET},
        }
    )
    with pytest.raises(PlanError, match="differ"):
        verify_plan(broken, checklist)


def test_phrase_missing_from_note_and_unknown_unit_raise() -> None:
    """planted_evidence needs every phrase in its note; unknown unit names are rejected."""
    from pair.eval.synth.planners import planted_evidence

    checklist = CHECKLISTS["pap-osa"]
    spec = plan_case(checklist, CaseType.WRONGLY_DENIED, random.Random(0))
    with pytest.raises(PlanError, match="not found"):
        planted_evidence(spec.plants, {"clinic": "", "report": ""})
    rng = random.Random(0)
    with pytest.raises(PlanError, match="no unit"):
        plan_from_states(
            checklist, CaseType.TRICKY, {"ghost": "present"}, DATES["pap-osa"](rng), rng
        )


def _state(policy_id: str, unit: str, state: str, seed: int = 4):  # type: ignore[no-untyped-def]
    """One unit state's outcome on seeded dates."""
    dates = DATES[policy_id](random.Random(seed))
    return next(u for u in UNITS[policy_id] if u.name == unit).states[state](dates)


def test_pap_event_counts_match_ahi_and_hours() -> None:
    """events / hours = AHI to one decimal, or the report contradicts itself (Step 8, R2)."""
    unit = next(u for u in UNITS["pap-osa"] if u.name == "ahi_threshold")
    for name, state in unit.states.items():
        values = {p.variable: p.value for p in state({}).plants if p.doc_id == "report"}
        if {"ahi", "event_count", "sleep_or_recording_hours"} <= set(values):
            assert (
                round(values["event_count"] / values["sleep_or_recording_hours"], 1)
                == values["ahi"]
            ), name


def test_oxygen_failing_time_of_need_dates_the_reported_test() -> None:
    """The dated inpatient test is the one whose values are reported, not a second undated test (Step 8, B1)."""
    test_date = next(
        p
        for p in _state("home-oxygen", "ordered_and_evaluated", "failing").plants
        if p.variable == "test_date"
    )
    assert test_date.doc_id == "report"


def test_oxygen_symptoms_phrase_does_not_say_where_the_test_was_done() -> None:
    """'Tested during this visit' reads as an office test and fills an absent tester (Step 8, test oxygen-05)."""
    for plant in _state("home-oxygen", "ordered_and_evaluated", "present").plants:
        assert (
            "visit" not in plant.phrase.lower() and "office" not in plant.phrase.lower()
        )


def test_pap_failing_adherence_covers_the_first_90_days() -> None:
    """A failing download must cover all of the first 3 months, or a later window could pass (Step 8, B5)."""
    phrases = " ".join(
        p.phrase for p in _state("pap-osa", "adherence", "failing").plants
    )
    assert "days 1 to 90" in phrases
    assert "best 30 consecutive days" in phrases


def test_facet_block_phrases_state_the_relief() -> None:
    """Every phrase that counts 80%-relief blocks names the relief, or the span overstates it (Step 8, B6)."""
    for state in ("present", "failing", "conflicting"):
        for plant in _state("facet-joint", "diagnostic_block_relief", state).plants:
            if plant.variable == "blocks_with_80pct_relief":
                assert re.search(r"\d+% (or more )?relief", plant.phrase), plant.phrase


def test_focus_skips_alternate_ways_of_meeting() -> None:
    """Group II meets the blood gas, so a type B letter must name the real gap (Step 8, test oxygen-06)."""
    checklist = CHECKLISTS["home-oxygen"]
    rng = random.Random(0)
    states = {u.name: "present" for u in UNITS["home-oxygen"]}
    states.update(blood_gas="group2", home_benefit="absent")
    spec = plan_from_states(
        checklist, CaseType.FIXABLE_GAP, states, DATES["home-oxygen"](rng), rng
    )
    assert spec.focus_criterion == "home_benefit"
    assert spec.focus_state == "absent"


@pytest.mark.parametrize(
    ("unit", "state", "leak"),
    [
        ("ahi_threshold", "vague", "AHI of 18.5"),
        ("ahi_threshold", "vague", "18 events per hour"),
        ("ahi_threshold", "absent", "severe obstructive sleep apnea"),
        ("ahi_threshold", "negated", "Essential hypertension"),
    ],
)
def test_hidden_states_list_their_leak_patterns(
    unit: str, state: str, leak: str
) -> None:
    """Vague and negated states hide facts too: a number or a qualifying condition fills them (Step 8, B2 to B4)."""
    checklist = CHECKLISTS["pap-osa"]
    rng = random.Random(3)
    states = {u.name: "present" for u in UNITS["pap-osa"]}
    states[unit] = state
    spec = plan_from_states(
        checklist, CaseType.TRICKY, states, DATES["pap-osa"](rng), rng
    )
    assert spec.absent_topics
    assert any(re.search(p, leak, re.IGNORECASE) for p in spec.forbidden)


def test_pap_reevaluation_phrases_imply_no_qualifying_symptom() -> None:
    """'Sleepiness improved on CPAP' says the patient was sleepy, which fills a negated AHI (Step 8 v3, dev pap-osa-09)."""
    for state in ("present", "failing", "out_of_window"):
        for plant in _state("pap-osa", "reevaluation", state).plants:
            assert not re.search(
                r"sleep(iness|y)|tired|insomnia|mood|cognit",
                plant.phrase,
                re.IGNORECASE,
            ), plant.phrase


def test_negated_ahi_catches_general_symptom_wording() -> None:
    """A negated-symptoms case can't also say the patient had OSA symptoms."""
    checklist = CHECKLISTS["pap-osa"]
    rng = random.Random(3)
    states = {u.name: "present" for u in UNITS["pap-osa"]}
    states["ahi_threshold"] = "negated"
    spec = plan_from_states(
        checklist, CaseType.TRICKY, states, DATES["pap-osa"](rng), rng
    )
    leak = "documented severe symptoms of obstructive sleep apnea"
    assert any(re.search(p, leak, re.IGNORECASE) for p in spec.forbidden)
    planted = " ".join(p.phrase for p in spec.plants)
    assert not any(re.search(p, planted, re.IGNORECASE) for p in spec.forbidden)


def test_oxygen_tester_phrase_fits_an_inpatient_test() -> None:
    """The qualified tester can't be an outpatient lab when the test is inpatient (Step 8 v3, test oxygen-08)."""
    phrase = _state("home-oxygen", "qualified_tester", "present").plants[0].phrase
    assert "outpatient" not in phrase.lower()


def test_failing_facet_pain_hides_any_other_pain_score() -> None:
    """A second, higher score ('baseline pain is rated 7/10') would make a failing pain criterion met (dev-v4 facet-joint-08)."""
    checklist = CHECKLISTS["facet-joint"]
    rng = random.Random(3)
    states = {u.name: "present" for u in UNITS["facet-joint"]}
    states["pain_and_function"] = "failing"
    spec = plan_from_states(checklist, CaseType.CORRECTLY_DENIED, states, DATES["facet-joint"](rng), rng)
    planted = [p.phrase for p in spec.plants if p.variable == "pain_score"]
    assert planted == ["rated 2/10"]
    assert any(re.search(p, "Her baseline pain is rated 7/10", re.IGNORECASE) for p in spec.forbidden)
    assert not any(re.search(p, phrase, re.IGNORECASE) for p in spec.forbidden for phrase in planted)
