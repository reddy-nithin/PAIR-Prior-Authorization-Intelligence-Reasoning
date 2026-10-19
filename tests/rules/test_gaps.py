"""Tests for the plain-language gap templates (spec §6.7)."""

from pathlib import Path

import pytest

from pair.contracts import Checklist, CriterionStatus
from pair.policies.loader import load_all
from pair.rules.engine import run_rules
from pair.rules.gaps import GapBook, GapTemplateError, load_gaps

MAX_MESSAGE_CHARS = 240


@pytest.fixture(scope="module")
def policies(repo_root: Path) -> dict[str, Checklist]:
    """The shipped policy checklists."""
    return load_all(repo_root / "policies")


@pytest.fixture(scope="module")
def book(repo_root: Path, policies: dict[str, Checklist]) -> GapBook:
    """The shipped gap templates, validated against the policies."""
    return load_gaps(repo_root / "policies" / "_gaps.yaml", policies)


def write(tmp_path: Path, text: str) -> Path:
    """Write a gaps file and return its path."""
    path = tmp_path / "_gaps.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_every_criterion_has_both_messages(book: GapBook, policies: dict[str, Checklist]) -> None:
    """Each criterion has an 'insufficient' and an 'unmet' message."""
    for checklist in policies.values():
        for criterion in checklist.criteria:
            for status in (CriterionStatus.INSUFFICIENT, CriterionStatus.UNMET):
                assert book.message(checklist.id, criterion.id, status)


def test_messages_are_plain_and_short(book: GapBook) -> None:
    """Patient text: no em/en dashes, at most a few sentences."""
    for message in book.all_messages():
        assert "—" not in message and "–" not in message, message
        assert len(message) <= MAX_MESSAGE_CHARS, message


def test_unmet_messages_never_promise_better_odds(book: GapBook, policies: dict[str, Checklist]) -> None:
    """A clearly unmet item gets no 'raise your chances' path (ADR-0007)."""
    for checklist in policies.values():
        for criterion in checklist.criteria:
            message = book.message(checklist.id, criterion.id, CriterionStatus.UNMET).lower()
            assert "chance" not in message and "odds" not in message, criterion.id


def test_met_has_no_gap(book: GapBook) -> None:
    """Asking for a gap on a met criterion is a programming error."""
    with pytest.raises(ValueError, match="met"):
        book.message("pap-osa", "f2f_visit", CriterionStatus.MET)


def test_for_policy_plugs_into_the_engine(book: GapBook, policies: dict[str, Checklist]) -> None:
    """``for_policy`` gives the engine's gap callback."""
    verdict = run_rules(policies["pap-osa"], [], {"initial": True}, book.for_policy("pap-osa"))
    expected = book.message("pap-osa", "f2f_visit", CriterionStatus.INSUFFICIENT)
    assert verdict.gaps[0].message == expected


GOOD = """
pap-osa:
  f2f_visit: {insufficient: "Ask for the visit note.", unmet: "Ask about other options."}
"""


def small_policies(policies: dict[str, Checklist]) -> dict[str, Checklist]:
    """A one-criterion version of pap-osa for structural tests."""
    pap = policies["pap-osa"]
    return {"pap-osa": pap.model_copy(update={"criteria": pap.criteria[:1], "logic": "f2f_visit"})}


def test_small_valid_file_loads(tmp_path: Path, policies: dict[str, Checklist]) -> None:
    """A file covering exactly the policies' criteria loads."""
    book = load_gaps(write(tmp_path, GOOD), small_policies(policies))
    assert book.message("pap-osa", "f2f_visit", CriterionStatus.UNMET) == "Ask about other options."


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("pap-osa: {}\n", "f2f_visit"),
        (GOOD + "home-oxygen:\n  x: {insufficient: a, unmet: b}\n", "home-oxygen"),
        (GOOD.replace("f2f_visit:", "f2f_visit_typo:"), "f2f_visit"),
        (GOOD.replace('unmet: "Ask about other options."', 'unmet: ""'), "empty"),
        (GOOD.replace("unmet:", "met:"), "unmet"),
        (GOOD.replace("Ask for", "Ask — for"), "dash"),
        (GOOD.replace("unmet:", "note: x, unmet:"), "unknown keys"),
        ("- not a mapping\n", "mapping"),
        ("pap-osa: [1, 2]\n", "mapping"),
        ("pap-osa:\n  f2f_visit: just text\n", "mapping"),
        ("pap-osa: {f2f_visit: {insufficient: a, unmet: b\n", "YAML"),
    ],
)
def test_bad_files_fail_loudly(tmp_path: Path, policies: dict[str, Checklist], text: str, match: str) -> None:
    """Missing, extra, empty or malformed templates raise ``GapTemplateError``."""
    with pytest.raises(GapTemplateError, match=match):
        load_gaps(write(tmp_path, text), small_policies(policies))
