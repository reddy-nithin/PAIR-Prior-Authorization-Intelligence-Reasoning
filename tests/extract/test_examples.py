"""The few-shot examples must match the real checklists (T8)."""

import pytest

from pair.extract.examples import examples_for
from pair.policies.loader import load_all
from tests.conftest import REPO_ROOT

CHECKLISTS = load_all(REPO_ROOT / "policies")
STATUSES = {"asserted", "negated", "uncertain"}


@pytest.mark.parametrize("policy_id", sorted(CHECKLISTS))
def test_examples_cover_every_variable(policy_id: str) -> None:
    """Every rule variable of the policy appears as an extraction class."""
    checklist = CHECKLISTS[policy_id]
    variables = {name for criterion in checklist.criteria for name in criterion.variables}
    classes = {e.extraction_class for ex in examples_for(policy_id) for e in ex.extractions}
    assert classes == variables


@pytest.mark.parametrize("policy_id", sorted(CHECKLISTS))
def test_example_spans_are_verbatim_with_value_and_status(policy_id: str) -> None:
    """Each example span is copied from its text and carries value + status attributes."""
    for example in examples_for(policy_id):
        for extraction in example.extractions:
            assert extraction.extraction_text in example.text, extraction.extraction_text
            assert extraction.attributes is not None
            assert set(extraction.attributes) == {"value", "status"}
            assert extraction.attributes["status"] in STATUSES


def test_examples_show_negation() -> None:
    """At least one example teaches the negated status."""
    statuses = {
        e.attributes["status"]
        for policy_id in CHECKLISTS
        for ex in examples_for(policy_id)
        for e in ex.extractions
        if e.attributes
    }
    assert {"asserted", "negated"} <= statuses


def test_unknown_policy_raises() -> None:
    """Asking for examples of an unmodeled policy is an error."""
    with pytest.raises(KeyError):
        examples_for("knee-brace")
