"""Tests for the ``Criterion``, ``PolicySource`` and ``Checklist`` contracts."""

import pydantic
import pytest

from pair.contracts import Checklist, Criterion, EvidenceType, PolicySource
from tests.contracts.factories import valid_checklist, valid_criterion, valid_source


def test_valid_checklist_round_trips() -> None:
    """A valid checklist survives a JSON round-trip and exposes typed criteria."""
    checklist = Checklist.model_validate(valid_checklist())
    assert Checklist.model_validate_json(checklist.model_dump_json()) == checklist
    assert checklist.criteria[0].evidence_type is EvidenceType.LAB_VALUE
    assert checklist.criterion_ids == ("ahi_threshold", "f2f_visit")


def test_duplicate_criterion_ids_rejected() -> None:
    """Two criteria with one id would make verdicts ambiguous."""
    kwargs = {**valid_checklist(), "criteria": [valid_criterion("a"), valid_criterion("a")]}
    with pytest.raises(pydantic.ValidationError, match="duplicate criterion id"):
        Checklist.model_validate(kwargs)


def test_criterion_source_must_exist() -> None:
    """Each criterion's clause must come from a declared source."""
    criterion = {**valid_criterion(), "source_id": "L99999"}
    with pytest.raises(pydantic.ValidationError, match="unknown source"):
        Checklist.model_validate({**valid_checklist(), "criteria": [criterion]})


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("id", "Has Spaces"),
        ("id", "has-dash"),
        ("clause", ""),
        ("rule", ""),
        ("evidence_type", "vibes"),
        ("variables", {"ahi": "complex"}),
        ("variables", {"Bad-Name": "number"}),
    ],
)
def test_criterion_rejects_bad_values(field: str, bad_value: object) -> None:
    """Criterion ids are slugs, clauses and rules are non-empty, types are known."""
    with pytest.raises(pydantic.ValidationError):
        Criterion.model_validate({**valid_criterion(), field: bad_value})


def test_source_requires_https_url() -> None:
    """Sources must link to the official page over HTTPS."""
    with pytest.raises(pydantic.ValidationError):
        PolicySource.model_validate({**valid_source(), "url": "ftp://example.org"})


def test_checklist_needs_criteria_and_sources() -> None:
    """An empty checklist or one without sources is invalid."""
    with pytest.raises(pydantic.ValidationError):
        Checklist.model_validate({**valid_checklist(), "criteria": []})
    with pytest.raises(pydantic.ValidationError):
        Checklist.model_validate({**valid_checklist(), "sources": []})


def test_checklist_rejects_unknown_field() -> None:
    """Unknown top-level YAML keys fail loudly."""
    with pytest.raises(pydantic.ValidationError):
        Checklist.model_validate({**valid_checklist(), "notes": "x"})
