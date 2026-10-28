"""The three shipped policy checklists load and quote the MCD verbatim."""

import datetime as dt
from pathlib import Path

import pytest

from pair.contracts import Checklist, PolicySource
from pair.policies.loader import load_all
from pair.policies.mcd import MCDDocument, MCDExport
from pair.rules.evaluate import evaluate_rule

EXPECTED_POLICIES: dict[str, set[str]] = {
    "pap-osa": {"240.4", "L33718"},
    "home-oxygen": {"240.2", "L33797"},
    "facet-joint": {"L38841"},
}


@pytest.fixture(scope="module")
def policies(repo_root: Path) -> dict[str, Checklist]:
    """Load every shipped policy once."""
    return load_all(repo_root / "policies")


def test_all_three_policies_load(policies: dict[str, Checklist]) -> None:
    """Exactly the three Phase 1 policies load, citing the expected documents."""
    assert set(policies) == set(EXPECTED_POLICIES)
    for policy_id, source_ids in EXPECTED_POLICIES.items():
        assert {s.id for s in policies[policy_id].sources} == source_ids


def test_every_policy_has_a_critical_criterion(policies: dict[str, Checklist]) -> None:
    """Abstention (ADR-0007) needs at least one critical criterion per policy."""
    for checklist in policies.values():
        assert any(c.critical for c in checklist.criteria), checklist.id


def test_silent_record_is_insufficient_for_every_criterion(policies: dict[str, Checklist]) -> None:
    """With no evidence at all, every rule is Unknown, never unmet (ADR-0012).

    Catches ``is not None`` guards, which turn a missing value into False.
    """
    for checklist in policies.values():
        for criterion in checklist.criteria:
            bindings = dict.fromkeys(criterion.variables)
            assert evaluate_rule(criterion.rule, bindings) is None, f"{checklist.id}.{criterion.id}"


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"pao2": 52, "spo2": None, "at_rest_on_room_air": True}, True),
        ({"pao2": None, "spo2": 87, "at_rest_on_room_air": True}, True),
        ({"pao2": 60, "spo2": 92, "at_rest_on_room_air": True}, False),
        ({"pao2": 60, "spo2": None, "at_rest_on_room_air": True}, None),
        ({"pao2": 52, "spo2": None, "at_rest_on_room_air": False}, False),
    ],
)
def test_oxygen_group1_either_test_qualifies(
    policies: dict[str, Checklist], values: dict[str, object], expected: bool | None
) -> None:
    """Group I: one qualifying PaO2 or SpO2 suffices; one failing test with the other missing is Unknown."""
    criterion = next(c for c in policies["home-oxygen"].criteria if c.id == "group1_blood_gas")
    assert evaluate_rule(criterion.rule, values) is expected


@pytest.mark.parametrize(
    ("evaluation", "test", "expected"),
    [
        (dt.date(2026, 3, 1), dt.date(2026, 3, 10), True),
        (dt.date(2026, 3, 10), dt.date(2026, 3, 10), True),
        (dt.date(2026, 3, 11), dt.date(2026, 3, 10), False),
        (None, dt.date(2026, 3, 10), None),
    ],
)
def test_pap_f2f_before_sleep_test(
    policies: dict[str, Checklist], evaluation: dt.date | None, test: dt.date, expected: bool | None
) -> None:
    """The face-to-face visit must be on or before the sleep test; a missing date is insufficient."""
    criterion = next(c for c in policies["pap-osa"].criteria if c.id == "f2f_visit")
    values = {"evaluation_date": evaluation, "sleep_test_date": test}
    assert evaluate_rule(criterion.rule, values) is expected


def rule_of(policies: dict[str, Checklist], policy_id: str, criterion_id: str) -> str:
    """One shipped criterion's rule expression."""
    return next(c.rule for c in policies[policy_id].criteria if c.id == criterion_id)


SYMPTOM = ["hypertension"]
D_START = dt.date(2026, 3, 1)


@pytest.mark.parametrize(
    ("ahi", "hours", "events", "symptoms", "expected"),
    [
        (22, 6.0, None, None, True),  # full-night study reporting only the AHI
        (15, 2.0, None, None, True),  # exactly 2 hours is not "less than 2 hours"
        (15, 1.5, 29, None, False),
        (15, 1.5, 30, None, True),
        (18, None, None, None, None),  # no recording time and no count: route still open
        (18, None, 40, None, True),
        (10, 6.0, None, SYMPTOM, True),
        (10, 1.5, 9, SYMPTOM, False),
        (10, 1.5, 10, SYMPTOM, True),
        (10, 6.0, None, None, None),
        (14.5, 6.0, None, SYMPTOM, True),  # between the LCD's integer bands: read as the lower band (ADR-0015)
        (14.5, 6.0, None, None, None),
        (4, 6.0, None, SYMPTOM, False),
    ],
)
def test_pap_event_minimum_applies_only_under_two_hours(
    policies: dict[str, Checklist],
    ahi: float,
    hours: float | None,
    events: int | None,
    symptoms: list[str] | None,
    expected: bool | None,
) -> None:
    """L33718 asks for 30/10 events only when the AHI rests on less than 2 hours (ADR-0015)."""
    values = {"ahi": ahi, "sleep_or_recording_hours": hours, "event_count": events, "symptoms_or_conditions": symptoms}
    assert evaluate_rule(rule_of(policies, "pap-osa", "ahi_threshold"), values) is expected


@pytest.mark.parametrize(
    ("gap", "expected"), [(29, False), (30, True), (31, True), (90, True), (91, True), (92, True), (140, True)]
)
def test_pap_reevaluation_counts_start_as_day_one(policies: dict[str, Checklist], gap: int, expected: bool) -> None:
    """No sooner than day 31 (start = day 1, gap 30). A visit after day 91 still counts, with coverage from its date."""
    values = {"therapy_start_date": D_START, "reevaluation_date": D_START + dt.timedelta(days=gap), "symptoms_improved": True}
    assert evaluate_rule(rule_of(policies, "pap-osa", "reevaluation"), values) is expected


@pytest.mark.parametrize(
    ("inpatient", "test_offset", "symptoms", "expected"),
    [
        (False, None, True, True),  # outpatient tested while symptomatic
        (False, None, False, False),  # outpatient tested with no symptoms noted
        (False, None, None, None),
        (True, -2, None, True),  # inpatient tested 2 days before discharge
        (True, 0, None, True),
        (True, -3, None, False),  # 3 days before discharge is outside "within 2 days"
        (True, 1, None, False),  # after discharge
        (True, None, None, None),  # discharge-relative timing unknown
        (None, -1, True, True),  # setting unknown, both readings satisfied
        (None, -1, None, None),
    ],
)
def test_oxygen_time_of_need_by_setting(
    policies: dict[str, Checklist],
    inpatient: bool | None,
    test_offset: int | None,
    symptoms: bool | None,
    expected: bool | None,
) -> None:
    """Inpatient: test within 2 days before discharge (L33797). Outpatient: symptoms noted (NCD 240.2)."""
    values = {
        "practitioner_ordered_and_reviewed": True,
        "rx_from_inpatient_stay": inpatient,
        "test_date": None if test_offset is None else D_START + dt.timedelta(days=test_offset),
        "discharge_date": None if test_offset is None else D_START,
        "symptoms_noted_at_test": symptoms,
    }
    assert evaluate_rule(rule_of(policies, "home-oxygen", "ordered_and_evaluated"), values) is expected


@pytest.mark.parametrize(
    ("score", "verbal", "baseline_disability", "expected"),
    [
        (4, None, True, True),
        (3, None, True, False),
        (None, "moderate", True, True),  # verbal rating scale, accepted by the LCD footnote
        (None, "severe", True, True),
        (None, "mild", True, False),
        (None, None, True, None),  # e.g. only a disability scale recorded
        (3, "moderate", True, False),  # a numeric score decides when both are recorded
        (6, None, None, None),  # the footnote's baseline disability scale isn't documented
        (6, None, False, False),
    ],
)
def test_facet_moderate_pain_numeric_or_verbal(
    policies: dict[str, Checklist],
    score: int | None,
    verbal: str | None,
    baseline_disability: bool | None,
    expected: bool | None,
) -> None:
    """Moderate pain is 4+ on 0 to 10 or a verbal "moderate"/"severe" rating, with a baseline disability scale."""
    values = {
        "pain_score": score,
        "pain_severity_verbal": verbal,
        "pain_is_axial": True,
        "functional_deficit_documented": True,
        "disability_scale_at_baseline": baseline_disability,
    }
    assert evaluate_rule(rule_of(policies, "facet-joint", "pain_and_function"), values) is expected


@pytest.mark.parametrize(
    ("radiculopathy", "cyst", "claudication", "expected"),
    [
        (False, None, False, True),
        (False, None, True, False),
        (True, False, False, False),
        (True, True, False, True),  # radiculopathy from a facet synovial cyst is excepted
        (True, None, False, None),  # the cause isn't stated
        (False, None, None, None),
    ],
)
def test_facet_radiculopathy_claudication_and_cyst_exception(
    policies: dict[str, Checklist],
    radiculopathy: bool,
    cyst: bool | None,
    claudication: bool | None,
    expected: bool | None,
) -> None:
    """Untreated radiculopathy or claudication fails, except radiculopathy caused by a facet synovial cyst."""
    values = {
        "untreated_radiculopathy": radiculopathy,
        "radiculopathy_from_synovial_cyst": cyst,
        "untreated_neurogenic_claudication": claudication,
    }
    assert evaluate_rule(rule_of(policies, "facet-joint", "no_untreated_radiculopathy"), values) is expected


@pytest.mark.parametrize(
    ("blocks", "duration_ok", "spacing", "expected"),
    [
        (2, True, 21, True),
        (2, None, 21, None),
        (2, False, 21, False),
        (1, True, 21, False),
        (2, True, 14, True),  # "a minimum of 2 weeks after the initial diagnostic procedure"
        (2, True, 13, False),
        (2, True, None, None),
    ],
)
def test_facet_block_relief_sustained_and_two_weeks_apart(
    policies: dict[str, Checklist], blocks: int, duration_ok: bool | None, spacing: int | None, expected: bool | None
) -> None:
    """Relief lasts as expected for the agent, and the second block is at least 2 weeks after the first (L38841)."""
    values = {
        "blocks_with_80pct_relief": blocks,
        "relief_duration_consistent_with_agent": duration_ok,
        "first_block_date": None if spacing is None else D_START,
        "second_block_date": None if spacing is None else D_START + dt.timedelta(days=spacing),
    }
    assert evaluate_rule(rule_of(policies, "facet-joint", "diagnostic_block_relief"), values) is expected


@pytest.fixture(scope="module")
def export(mcd_export_dir: Path) -> MCDExport:
    """One cached reader over the downloaded export."""
    return MCDExport(mcd_export_dir)


def find_source(export: MCDExport, source: PolicySource) -> MCDDocument:
    """Look up a policy source in the MCD export."""
    return export.find_ncd(source.id) if source.type == "NCD" else export.find_lcd(source.id)


@pytest.mark.mcd
def test_sources_match_current_mcd_versions(policies: dict[str, Checklist], export: MCDExport) -> None:
    """Source versions, titles and URLs match the downloaded export (catches policy drift)."""
    for checklist in policies.values():
        for source in checklist.sources:
            document = find_source(export, source)
            assert (source.version, source.url) == (document.version, document.url), source.id
            assert source.title == document.title, source.id


@pytest.mark.mcd
def test_every_clause_is_verbatim_in_its_source(policies: dict[str, Checklist], export: MCDExport) -> None:
    """Each clause appears word for word (whitespace-insensitive) in the cited document."""
    for checklist in policies.values():
        sources = {s.id: s for s in checklist.sources}
        for criterion in checklist.criteria:
            document = find_source(export, sources[criterion.source_id])
            assert document.contains(criterion.clause), f"{checklist.id}.{criterion.id}"
