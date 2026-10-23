"""Case planners: target state per criterion → planted phrases + gold statuses (spec §5.3).

A *unit* is one criterion, or a group of criteria that share variables (the two
oxygen blood-gas groups share ``pao2``/``spo2``). Each unit has named states
(present, failing, absent, negated, conflicting, vague, out_of_window). A state
returns the exact phrases to plant and the status each of its criteria must get.
``plan_case`` checks those declared statuses against the rule engine on the
planted values, so a planner bug can't silently produce wrong gold labels.
"""

import datetime as dt
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pair.contracts import (
    Checklist,
    CriterionStatus,
    Evidence,
    EvidenceStatus,
    EvidenceValue,
)
from pair.eval.cases import CaseType
from pair.rules.engine import run_rules

logger = logging.getLogger(__name__)

MET, UNMET, INSUFFICIENT = CriterionStatus.MET, CriterionStatus.UNMET, CriterionStatus.INSUFFICIENT
CLINIC, REPORT = "clinic", "report"
"""The two documents every case has: a clinic note and a test/device report."""

TRICKY_STATES: tuple[str, ...] = ("negated", "conflicting", "vague", "out_of_window")
GAP_STATES: tuple[str, ...] = ("absent", "vague")
ALT_MET_STATES: tuple[str, ...] = ("group2",)
"""Other ways to meet a unit (oxygen Group II instead of Group I); used for "present" at random."""


class PlanError(ValueError):
    """A case plan is inconsistent (declared gold status ≠ rule engine)."""


@dataclass(frozen=True)
class Plant:
    """One phrase to plant in a note, and the value it carries.

    Attributes:
        criterion_ids: Criteria whose variable this phrase supplies.
        variable: The rule variable.
        phrase: Exact text the note must contain.
        value: The normalized value a perfect extractor returns.
        doc_id: The note it goes in.
        status: How the phrase states the fact.
    """

    criterion_ids: tuple[str, ...]
    variable: str
    phrase: str
    value: EvidenceValue
    doc_id: str
    status: EvidenceStatus = EvidenceStatus.ASSERTED


@dataclass(frozen=True)
class StateOutcome:
    """What a unit state plants and the gold status of each criterion in the unit."""

    plants: tuple[Plant, ...]
    expected: dict[str, CriterionStatus]


StateFn = Callable[[dict[str, dt.date]], StateOutcome]


@dataclass(frozen=True)
class Unit:
    """A planning unit: criteria planned together, and their states."""

    name: str
    criterion_ids: tuple[str, ...]
    states: dict[str, StateFn]
    absent_topic: str
    """What the note writer must not mention when the unit is absent."""
    forbidden: str = ""
    """Regex that must not match the notes when the unit is absent (catches leaked values)."""


@dataclass(frozen=True)
class CaseSpec:
    """A planned case: states, plants, context and declared gold statuses."""

    policy_id: str
    case_type: CaseType
    states: dict[str, str]
    plants: tuple[Plant, ...]
    expected: dict[str, CriterionStatus]
    context: dict[str, bool | None]
    dates: dict[str, dt.date]
    absent_topics: tuple[str, ...]
    forbidden: tuple[str, ...]
    focus_criterion: str
    """The criterion the denial letter's reason is about."""


def _d(day: dt.date) -> str:
    """Dates are planted in US numeric form, e.g. 02/03/2026."""
    return day.strftime("%m/%d/%Y")


def _p(criteria: str | tuple[str, ...], variable: str, phrase: str, value: Any, doc: str, status: str = "asserted") -> Plant:
    """Shorthand for a Plant."""
    ids = (criteria,) if isinstance(criteria, str) else criteria
    return Plant(ids, variable, phrase, value, doc, EvidenceStatus(status))


def _out(expected: dict[str, CriterionStatus], *plants: Plant) -> StateOutcome:
    """Shorthand for a StateOutcome."""
    return StateOutcome(plants=plants, expected=expected)


# ── PAP for OSA ─────────────────────────────────────────────────────────────


def _pap_dates(rng: random.Random) -> dict[str, dt.date]:
    visit = dt.date(2026, 1, 5) + dt.timedelta(days=rng.randint(0, 120))
    test = visit + dt.timedelta(days=rng.randint(7, 28))
    start = test + dt.timedelta(days=rng.randint(10, 21))
    return {
        "visit": visit,
        "test": test,
        "start": start,
        "reeval": start + dt.timedelta(days=rng.randint(40, 80)),
        "late_reeval": start + dt.timedelta(days=rng.randint(110, 140)),
        "denial": start + dt.timedelta(days=rng.randint(95, 105)),
    }


F2F = "f2f_visit"
AHI = "ahi_threshold"
ADH = "adherence"
REEVAL = "reevaluation"

PAP_UNITS: tuple[Unit, ...] = (
    Unit(
        F2F,
        (F2F,),
        {
            "present": lambda d: _out(
                {F2F: MET},
                _p(F2F, "evaluation_date", f"Sleep medicine visit {_d(d['visit'])}", d["visit"], CLINIC),
                _p(F2F, "sleep_test_date", f"Home sleep test {_d(d['test'])}", d["test"], REPORT),
            ),
            "out_of_window": lambda d: _out(
                {F2F: UNMET},
                _p(F2F, "evaluation_date", f"Sleep medicine visit {_d(d['test'] + dt.timedelta(days=9))}",
                   d["test"] + dt.timedelta(days=9), CLINIC),
                _p(F2F, "sleep_test_date", f"Home sleep test {_d(d['test'])}", d["test"], REPORT),
            ),
            "absent": lambda d: _out(
                {F2F: INSUFFICIENT},
                _p(F2F, "sleep_test_date", f"Home sleep test {_d(d['test'])}", d["test"], REPORT),
            ),
            "conflicting": lambda d: _out(
                {F2F: INSUFFICIENT},
                _p(F2F, "evaluation_date", f"Sleep medicine visit {_d(d['visit'])}", d["visit"], CLINIC),
                _p(F2F, "sleep_test_date", f"Home sleep test {_d(d['test'])}", d["test"], REPORT),
                _p(F2F, "sleep_test_date", f"sleep study was done on {_d(d['test'] + dt.timedelta(days=12))}",
                   d["test"] + dt.timedelta(days=12), CLINIC),
            ),
        },
        "an in-person visit date before the sleep test",
    ),
    Unit(
        AHI,
        (AHI,),
        {
            "present": lambda d: _out(
                {AHI: MET},
                _p(AHI, "ahi", "AHI 22.4 events/hour", 22.4, REPORT),
                _p(AHI, "event_count", "131 total respiratory events", 131, REPORT),
                _p(AHI, "symptoms_or_conditions", "daytime sleepiness", ["daytime sleepiness"], CLINIC),
            ),
            "failing": lambda d: _out(
                {AHI: UNMET},
                _p(AHI, "ahi", "AHI 3.1 events/hour", 3.1, REPORT),
                _p(AHI, "event_count", "18 total respiratory events", 18, REPORT),
            ),
            "absent": lambda d: _out({AHI: INSUFFICIENT}),
            "negated": lambda d: _out(
                {AHI: INSUFFICIENT},
                _p(AHI, "ahi", "AHI 9.6 events/hour", 9.6, REPORT),
                _p(AHI, "event_count", "52 total respiratory events", 52, REPORT),
                _p(AHI, "symptoms_or_conditions", "denies daytime sleepiness", ["daytime sleepiness"], CLINIC, "negated"),
            ),
            "conflicting": lambda d: _out(
                {AHI: INSUFFICIENT},
                _p(AHI, "ahi", "AHI 18.2 events/hour", 18.2, REPORT),
                _p(AHI, "event_count", "106 total respiratory events", 106, REPORT),
                _p(AHI, "ahi", "AHI of 11.0", 11.0, CLINIC),
            ),
            "vague": lambda d: _out(
                {AHI: INSUFFICIENT},
                _p(AHI, "ahi", "moderate obstructive sleep apnea", None, REPORT),
            ),
        },
        "any sleep test result numbers (AHI, RDI or event counts) or sleep apnea symptoms",
        r"\b(AHI|RDI|apnea-hypopnea)\b",
    ),
    Unit(
        ADH,
        (ADH,),
        {
            "present": lambda d: _out(
                {ADH: MET},
                _p(ADH, "pct_nights_4h_best_30d", "used 4 hours or more on 78% of nights", 78, REPORT),
                _p(ADH, "window_in_first_90_days", "30 consecutive days within the first 3 months", True, REPORT),
            ),
            "failing": lambda d: _out(
                {ADH: UNMET},
                _p(ADH, "pct_nights_4h_best_30d", "used 4 hours or more on 52% of nights", 52, REPORT),
                _p(ADH, "window_in_first_90_days", "30 consecutive days within the first 3 months", True, REPORT),
            ),
            "absent": lambda d: _out({ADH: INSUFFICIENT}),
            "out_of_window": lambda d: _out(
                {ADH: UNMET},
                _p(ADH, "pct_nights_4h_best_30d", "used 4 hours or more on 81% of nights", 81, REPORT),
                _p(ADH, "window_in_first_90_days", "best 30-day stretch was in month 5, after the first 3 months",
                   False, REPORT),
            ),
        },
        "CPAP usage or adherence data",
        r"% of nights|hours (per|a|each) night",
    ),
    Unit(
        REEVAL,
        (REEVAL,),
        {
            "present": lambda d: _out(
                {REEVAL: MET},
                _p(REEVAL, "therapy_start_date", f"CPAP started {_d(d['start'])}", d["start"], CLINIC),
                _p(REEVAL, "reevaluation_date", f"Follow-up visit {_d(d['reeval'])}", d["reeval"], CLINIC),
                _p(REEVAL, "symptoms_improved", "sleepiness much improved on CPAP", True, CLINIC),
            ),
            "failing": lambda d: _out(
                {REEVAL: UNMET},
                _p(REEVAL, "therapy_start_date", f"CPAP started {_d(d['start'])}", d["start"], CLINIC),
                _p(REEVAL, "reevaluation_date", f"Follow-up visit {_d(d['reeval'])}", d["reeval"], CLINIC),
                _p(REEVAL, "symptoms_improved", "no improvement in sleepiness on CPAP", False, CLINIC),
            ),
            "absent": lambda d: _out(
                {REEVAL: INSUFFICIENT},
                _p(REEVAL, "therapy_start_date", f"CPAP started {_d(d['start'])}", d["start"], CLINIC),
            ),
            "out_of_window": lambda d: _out(
                {REEVAL: UNMET},
                _p(REEVAL, "therapy_start_date", f"CPAP started {_d(d['start'])}", d["start"], CLINIC),
                _p(REEVAL, "reevaluation_date", f"Follow-up visit {_d(d['late_reeval'])}", d["late_reeval"], CLINIC),
                _p(REEVAL, "symptoms_improved", "sleepiness much improved on CPAP", True, CLINIC),
            ),
        },
        "a follow-up visit after starting CPAP or whether symptoms improved",
        r"follow-?up|re-?evaluat|improv",
    ),
)  # fmt: skip


# ── Home oxygen ─────────────────────────────────────────────────────────────


def _oxygen_dates(rng: random.Random) -> dict[str, dt.date]:
    visit = dt.date(2026, 2, 2) + dt.timedelta(days=rng.randint(0, 150))
    return {"visit": visit, "denial": visit + dt.timedelta(days=rng.randint(10, 30))}


ORD = "ordered_and_evaluated"
QT = "qualified_tester"
G1, G2 = "group1_blood_gas", "group2_blood_gas"
HB = "home_benefit"

OXYGEN_UNITS: tuple[Unit, ...] = (
    Unit(
        ORD,
        (ORD,),
        {
            "present": lambda d: _out(
                {ORD: MET},
                _p(ORD, "practitioner_ordered_and_reviewed", "I ordered resting oximetry and reviewed the results", True, CLINIC),
                _p(ORD, "rx_from_inpatient_stay", "seen as an outpatient, no recent hospital stay", False, CLINIC),
                _p(ORD, "symptoms_noted_at_test", "tested during this visit while short of breath", True, CLINIC),
            ),
            "failing": lambda d: _out(
                {ORD: UNMET},
                _p(ORD, "practitioner_ordered_and_reviewed", "I ordered resting oximetry and reviewed the results", True, CLINIC),
                _p(ORD, "rx_from_inpatient_stay", "seen as an outpatient, no recent hospital stay", False, CLINIC),
                _p(ORD, "symptoms_noted_at_test", "tested at a routine visit with no shortness of breath or other symptoms",
                   False, CLINIC),
            ),
            "absent": lambda d: _out({ORD: INSUFFICIENT}),
        },
        "who ordered or reviewed the oxygen test, or when it was done relative to symptoms",
    ),
    Unit(
        QT,
        (QT,),
        {
            "present": lambda d: _out(
                {QT: MET},
                _p(QT, "tested_by_qualified_provider", "Hospital outpatient lab performed the test", True, REPORT),
            ),
            "failing": lambda d: _out(
                {QT: UNMET},
                _p(QT, "tested_by_qualified_provider", "test performed by the oxygen supplier's technician", False, REPORT),
            ),
            "absent": lambda d: _out({QT: INSUFFICIENT}),
        },
        "who performed the oxygen test",
        r"performed by|laborator|\blab\b|technician|supplier",
    ),
    Unit(
        "blood_gas",
        (G1, G2),
        {
            "present": lambda d: _out(
                {G1: MET, G2: INSUFFICIENT},
                _p(G1, "at_rest_on_room_air", "at rest on room air", True, REPORT),
                _p((G1, G2), "spo2", "SpO2 87%", 87, REPORT),
            ),
            "group2": lambda d: _out(
                {G1: INSUFFICIENT, G2: MET},
                _p(G1, "at_rest_on_room_air", "at rest on room air", True, REPORT),
                _p((G1, G2), "spo2", "SpO2 89%", 89, REPORT),
                _p(G2, "group2_conditions", "ankle edema from congestive heart failure",
                   ["edema from congestive heart failure"], CLINIC),
            ),
            "failing": lambda d: _out(
                {G1: UNMET, G2: UNMET},
                _p(G1, "at_rest_on_room_air", "at rest on room air", True, REPORT),
                _p((G1, G2), "pao2", "PaO2 72 mmHg", 72, REPORT),
                _p((G1, G2), "spo2", "SpO2 94%", 94, REPORT),
            ),
            "absent": lambda d: _out({G1: INSUFFICIENT, G2: INSUFFICIENT}),
            "conflicting": lambda d: _out(
                {G1: INSUFFICIENT, G2: INSUFFICIENT},
                _p(G1, "at_rest_on_room_air", "at rest on room air", True, REPORT),
                _p((G1, G2), "spo2", "SpO2 87%", 87, REPORT),
                _p((G1, G2), "spo2", "oxygen saturation of 93%", 93, CLINIC),
            ),
        },
        "any oxygen level, saturation or blood gas numbers",
        r"SpO2|PaO2|PO2|saturation|\d+\s*mmHg",
    ),
    Unit(
        HB,
        (HB,),
        {
            "present": lambda d: _out(
                {HB: MET},
                _p(HB, "expected_to_improve", "home oxygen is expected to improve dyspnea", True, CLINIC),
            ),
            "failing": lambda d: _out(
                {HB: UNMET},
                _p(HB, "expected_to_improve", "home oxygen is not expected to change her symptoms", False, CLINIC),
            ),
            "absent": lambda d: _out({HB: INSUFFICIENT}),
        },
        "whether home oxygen is expected to help",
        r"expected to (?:improve|help|benefit)|will (?:improve|help|benefit)",
    ),
)  # fmt: skip


# ── Facet joint ─────────────────────────────────────────────────────────────


def _facet_dates(rng: random.Random) -> dict[str, dt.date]:
    visit = dt.date(2026, 1, 12) + dt.timedelta(days=rng.randint(0, 160))
    return {"visit": visit, "denial": visit + dt.timedelta(days=rng.randint(10, 30))}


PF = "pain_and_function"
DUR = "duration_and_conservative_care"
RAD = "no_untreated_radiculopathy"
PATH = "no_other_pathology"
BLK = "diagnostic_block_relief"

FACET_UNITS: tuple[Unit, ...] = (
    Unit(
        PF,
        (PF,),
        {
            "present": lambda d: _out(
                {PF: MET},
                _p(PF, "pain_is_axial", "axial low back pain", True, CLINIC),
                _p(PF, "pain_score", "rated 7/10", 7, CLINIC),
                _p(PF, "functional_deficit_documented", "limits walking and work (ODI 42%)", True, CLINIC),
            ),
            "failing": lambda d: _out(
                {PF: UNMET},
                _p(PF, "pain_is_axial", "axial low back pain", True, CLINIC),
                _p(PF, "pain_score", "rated 2/10", 2, CLINIC),
                _p(PF, "functional_deficit_documented", "limits walking and work (ODI 42%)", True, CLINIC),
            ),
            "absent": lambda d: _out({PF: INSUFFICIENT}),
            "vague": lambda d: _out(
                {PF: INSUFFICIENT},
                _p(PF, "pain_is_axial", "axial low back pain", True, CLINIC),
                _p(PF, "pain_score", "bothersome back pain", None, CLINIC),
                _p(PF, "functional_deficit_documented", "limits walking and work (ODI 42%)", True, CLINIC),
            ),
        },
        "a pain score or rating (mild, moderate, severe) or how the pain limits function",
        r"\b\d+\s*/\s*10\b|ODI|\b(?:mild|moderate|severe)(?:ly)?\b[^.]{0,30}\bpain\b",
    ),
    Unit(
        DUR,
        (DUR,),
        {
            "present": lambda d: _out(
                {DUR: MET},
                _p(DUR, "pain_duration_months", "for 8 months", 8, CLINIC),
                _p(DUR, "conservative_care_failed", "Failed 12 weeks of physical therapy and NSAIDs", True, CLINIC),
            ),
            "failing": lambda d: _out(
                {DUR: UNMET},
                _p(DUR, "pain_duration_months", "for 2 months", 2, CLINIC),
                _p(DUR, "conservative_care_failed", "Failed 12 weeks of physical therapy and NSAIDs", True, CLINIC),
            ),
            "absent": lambda d: _out({DUR: INSUFFICIENT}),
        },
        "how long the pain has lasted or any prior treatments like physical therapy",
        r"\b\d+\s*(?:months?|weeks?|years?)\b|physical therapy|\bNSAIDs?\b",
    ),
    Unit(
        RAD,
        (RAD,),
        {
            "present": lambda d: _out(
                {RAD: MET},
                _p(RAD, "untreated_radiculopathy", "No radicular symptoms", False, CLINIC),
                _p(RAD, "untreated_neurogenic_claudication", "no neurogenic claudication", False, CLINIC),
            ),
            "failing": lambda d: _out(
                {RAD: UNMET},
                _p(RAD, "untreated_radiculopathy", "untreated L5 radiculopathy with pain below the knee", True, CLINIC),
            ),
            "absent": lambda d: _out({RAD: INSUFFICIENT}),
        },
        "radiating leg pain, radiculopathy, neurogenic claudication or nerve symptoms",
        r"radicul|radiat|sciatica|claudicat",
    ),
    Unit(
        PATH,
        (PATH,),
        {
            "present": lambda d: _out(
                {PATH: MET}, _p(PATH, "other_pathology_found", "no fracture, tumor or infection", False, REPORT)
            ),
            "failing": lambda d: _out(
                {PATH: UNMET}, _p(PATH, "other_pathology_found", "acute L3 compression fracture", True, REPORT)
            ),
            "absent": lambda d: _out({PATH: INSUFFICIENT}),
        },
        "imaging findings such as fracture, tumor or infection",
        r"fracture|tumou?r|infection|malignan|metasta",
    ),
    Unit(
        BLK,
        (BLK,),
        {
            "present": lambda d: _out(
                {BLK: MET},
                _p(BLK, "blocks_with_80pct_relief", "Two medial branch blocks each gave 85% relief", 2, REPORT),
                _p(BLK, "relief_duration_consistent_with_agent", "relief lasted as long as expected for the anesthetic used",
                   True, REPORT),
            ),
            "failing": lambda d: _out(
                {BLK: UNMET},
                _p(BLK, "blocks_with_80pct_relief", "only one of two medial branch blocks gave 80% or more relief", 1, REPORT),
            ),
            "absent": lambda d: _out({BLK: INSUFFICIENT}),
            "conflicting": lambda d: _out(
                {BLK: INSUFFICIENT},
                _p(BLK, "blocks_with_80pct_relief", "Two medial branch blocks each gave 85% relief", 2, REPORT),
                _p(BLK, "blocks_with_80pct_relief", "one diagnostic block helped", 1, CLINIC),
            ),
        },
        "results of diagnostic medial branch blocks",
        r"% relief|branch block",
    ),
)  # fmt: skip

UNITS: dict[str, tuple[Unit, ...]] = {"pap-osa": PAP_UNITS, "home-oxygen": OXYGEN_UNITS, "facet-joint": FACET_UNITS}
DATES: dict[str, Callable[[random.Random], dict[str, dt.date]]] = {
    "pap-osa": _pap_dates,
    "home-oxygen": _oxygen_dates,
    "facet-joint": _facet_dates,
}
CONTEXT: dict[str, dict[str, bool | None]] = {
    "pap-osa": {"initial": False},
    "home-oxygen": {},
    "facet-joint": {"diagnostic_only": False},
}
"""PAP cases are continued-coverage reviews (all 4 criteria apply); facet cases request RFA."""


def choose_states(policy_id: str, case_type: CaseType, rng: random.Random, critical: set[str]) -> dict[str, str]:
    """Pick a state per unit for the case type.

    A: all present. B: one or two units absent or vague. C: one unit failing
    (critical criteria preferred). D: one unit in a tricky state.
    """
    units = UNITS[policy_id]
    states = {unit.name: rng.choice(["present", *[s for s in ALT_MET_STATES if s in unit.states]]) for unit in units}
    if case_type is CaseType.FIXABLE_GAP:
        for unit in rng.sample(list(units), k=rng.choice([1, 2])):
            options = [s for s in GAP_STATES if s in unit.states]
            states[unit.name] = rng.choice(options)
    elif case_type is CaseType.CORRECTLY_DENIED:
        failing = [u for u in units if "failing" in u.states]
        preferred = [u for u in failing if critical & set(u.criterion_ids)] or failing
        states[rng.choice(preferred).name] = "failing"
    elif case_type is CaseType.TRICKY:
        tricky = [(u, s) for u in units for s in TRICKY_STATES if s in u.states]
        unit, state = rng.choice(tricky)
        states[unit.name] = state
    return states


def plan_case(checklist: Checklist, case_type: CaseType, rng: random.Random) -> CaseSpec:
    """Plan one case: states, plants, dates, context and declared gold statuses.

    Raises:
        PlanError: If the policy has no planner or a unit doesn't cover its criteria.
    """
    policy_id = checklist.id
    if policy_id not in UNITS:
        raise PlanError(f"no case planner for policy {policy_id!r}")
    units = UNITS[policy_id]
    covered = [cid for unit in units for cid in unit.criterion_ids]
    if sorted(covered) != sorted(c.id for c in checklist.criteria):
        raise PlanError(f"planner units for {policy_id} don't match its criteria")
    critical = {c.id for c in checklist.criteria if c.critical}
    dates = DATES[policy_id](rng)
    states = choose_states(policy_id, case_type, rng, critical)
    return plan_from_states(checklist, case_type, states, dates, rng)


def plan_from_states(
    checklist: Checklist,
    case_type: CaseType,
    states: dict[str, str],
    dates: dict[str, dt.date],
    rng: random.Random,
) -> CaseSpec:
    """Build and verify a spec from explicit unit states.

    Raises:
        PlanError: If a state is unknown or the declared gold statuses disagree with the engine.
    """
    policy_id = checklist.id
    units = UNITS[policy_id]
    unknown = {name: state for name, state in states.items() if state not in _unit(units, name).states}
    if unknown:
        raise PlanError(f"unknown states for {policy_id}: {unknown}")
    plants: list[Plant] = []
    expected: dict[str, CriterionStatus] = {}
    absent: list[str] = []
    forbidden: list[str] = []
    for unit in units:
        outcome = unit.states[states[unit.name]](dates)
        plants.extend(outcome.plants)
        expected.update(outcome.expected)
        if states[unit.name] == "absent":
            absent.append(unit.absent_topic)
            if unit.forbidden:
                forbidden.append(unit.forbidden)
    focus = _focus(units, states, rng)
    spec = CaseSpec(
        policy_id=policy_id,
        case_type=case_type,
        states=states,
        plants=tuple(plants),
        expected=expected,
        context=dict(CONTEXT[policy_id]),
        dates=dates,
        absent_topics=tuple(absent),
        forbidden=tuple(forbidden),
        focus_criterion=focus,
    )
    verify_plan(spec, checklist)
    return spec


def find_phrase(text: str, phrase: str) -> int:
    """Case-insensitive ``str.find`` (lowercasing keeps offsets for these ASCII phrases)."""
    return text.lower().find(phrase.lower())


def planted_evidence(plants: tuple[Plant, ...], texts: dict[str, str]) -> list[Evidence]:
    """Gold Evidence for each plant at its first occurrence in its note, ignoring case.

    The gold ``span_text`` is the note's own text at that position, so it keeps
    the note's capitalization ("no radicular symptoms" mid-sentence).

    Raises:
        PlanError: If a phrase isn't in its note.
    """
    evidence: list[Evidence] = []
    for plant in plants:
        text = texts.get(plant.doc_id, "")
        start = find_phrase(text, plant.phrase)
        if start < 0:
            raise PlanError(f"phrase {plant.phrase!r} not found in note {plant.doc_id!r}")
        span = text[start : start + len(plant.phrase)]
        evidence.extend(
            Evidence(
                criterion_id=criterion_id,
                variable=plant.variable,
                value=plant.value,
                span_text=span,
                char_start=start,
                char_end=start + len(plant.phrase),
                doc_id=plant.doc_id,
                status=plant.status,
            )
            for criterion_id in plant.criterion_ids
        )
    return evidence


def verify_plan(spec: CaseSpec, checklist: Checklist) -> dict[str, CriterionStatus]:
    """Run the rule engine on the planted values and check the declared gold statuses.

    Returns:
        Gold statuses per criterion plus ``"__overall__"``.

    Raises:
        PlanError: If any criterion's engine status differs from the declared one.
    """
    texts: dict[str, str] = {}
    for plant in spec.plants:
        texts[plant.doc_id] = texts.get(plant.doc_id, "") + plant.phrase + "\n"
    verdict = run_rules(checklist, planted_evidence(spec.plants, texts), spec.context, lambda _c, _s: "gap")
    got = {result.criterion_id: result.status for result in verdict.results}
    if got != spec.expected:
        diff = {cid: (spec.expected.get(cid), got.get(cid)) for cid in got if got[cid] != spec.expected.get(cid)}
        raise PlanError(f"{spec.policy_id} plan {spec.states}: declared vs engine differ {diff}")
    return {**got, "__overall__": verdict.overall}


def _unit(units: tuple[Unit, ...], name: str) -> Unit:
    """Find a unit by name."""
    for unit in units:
        if unit.name == name:
            return unit
    raise PlanError(f"no unit {name!r}")


def _focus(units: tuple[Unit, ...], states: dict[str, str], rng: random.Random) -> str:
    """The criterion the denial reason names: the changed unit, or any unit for type A."""
    changed = [u for u in units if states[u.name] != "present"]
    unit = changed[0] if changed else rng.choice(list(units))
    return unit.criterion_ids[0]
