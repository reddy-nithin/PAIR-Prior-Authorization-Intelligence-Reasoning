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
