"""Tests for active criteria and any-of groups (ADR-0019)."""

from pathlib import Path

import pytest

from pair.contracts import Checklist
from pair.policies.loader import load_all
from pair.rules.active import ContextFlag, active_criteria, any_of_groups, bind_context


@pytest.fixture(scope="module")
def checklists(repo_root: Path) -> dict[str, Checklist]:
    """All shipped checklists."""
    return load_all(repo_root / "policies")


SOURCED_TRUE = ContextFlag(value=True, source="denial: 'initial request'")


def test_sourced_initial_true_turns_off_continued_coverage_criteria(checklists: dict[str, Checklist]) -> None:
    """PAP initial request: adherence and re-evaluation can't change the result."""
    active = active_criteria(checklists["pap-osa"], {"initial": SOURCED_TRUE})
    assert active == ("f2f_visit", "ahi_threshold")


def test_sourced_initial_false_keeps_every_criterion(checklists: dict[str, Checklist]) -> None:
    """Continued coverage: all four criteria matter."""
    active = active_criteria(checklists["pap-osa"], {"initial": ContextFlag(False, "user input")})
    assert active == checklists["pap-osa"].criterion_ids


@pytest.mark.parametrize("flags", [{}, {"initial": ContextFlag(True, None)}, {"initial": ContextFlag(None, "x")}])
def test_missing_or_unsourced_flag_is_unknown_and_keeps_both_branches(
    checklists: dict[str, Checklist], flags: dict[str, ContextFlag]
) -> None:
    """A flag with no source counts as Unknown: both branches stay active."""
    assert active_criteria(checklists["pap-osa"], flags) == checklists["pap-osa"].criterion_ids


def test_facet_diagnostic_only_turns_off_block_relief(checklists: dict[str, Checklist]) -> None:
    """A first diagnostic block doesn't need prior block relief."""
    active = active_criteria(checklists["facet-joint"], {"diagnostic_only": ContextFlag(True, "denial")})
    assert "diagnostic_block_relief" not in active
    assert len(active) == len(checklists["facet-joint"].criteria) - 1


def test_oxygen_groups_are_both_active(checklists: dict[str, Checklist]) -> None:
    """Either blood-gas group can decide the result, so both are active."""
    assert active_criteria(checklists["home-oxygen"], {}) == checklists["home-oxygen"].criterion_ids


def test_only_oxygen_has_an_any_of_group(checklists: dict[str, Checklist]) -> None:
    """An any-of group is an 'or' over bare criterion ids; flag-mixed 'or's don't count."""
    assert any_of_groups(checklists["home-oxygen"]) == (("group1_blood_gas", "group2_blood_gas"),)
    assert any_of_groups(checklists["pap-osa"]) == ()
    assert any_of_groups(checklists["facet-joint"]) == ()


def test_bind_context_keeps_sourced_values_only() -> None:
    """Unsourced or missing flags bind to None."""
    assert bind_context({"a": ContextFlag(True, "span"), "b": ContextFlag(False, None)}) == {"a": True, "b": None}


def test_unknown_flag_name_is_rejected(checklists: dict[str, Checklist]) -> None:
    """A flag the checklist doesn't declare is a caller error."""
    with pytest.raises(ValueError, match="nope"):
        active_criteria(checklists["pap-osa"], {"nope": SOURCED_TRUE})
