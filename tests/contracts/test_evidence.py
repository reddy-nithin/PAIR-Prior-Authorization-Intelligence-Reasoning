"""Tests for the ``Evidence`` contract."""

import pydantic
import pytest

from pair.contracts import Evidence, EvidenceStatus
from tests.contracts.factories import NOTE_TEXT, valid_evidence


def test_valid_evidence_points_at_its_span() -> None:
    """Char offsets slice the source note back to the span text."""
    evidence = Evidence.model_validate(valid_evidence())
    assert NOTE_TEXT[evidence.char_start : evidence.char_end] == evidence.span_text
    assert evidence.status is EvidenceStatus.ASSERTED


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"char_start": -1}, "char_start"),
        ({"char_end": 5, "char_start": 5}, "char_end must be greater"),
        ({"span_text": "AHI of 18"}, "span length"),
        ({"status": "maybe"}, "status"),
        ({"criterion_id": ""}, "criterion_id"),
    ],
)
def test_evidence_rejects_inconsistent_spans(overrides: dict[str, object], message: str) -> None:
    """Offsets must be ordered and agree with the span text length."""
    with pytest.raises(pydantic.ValidationError, match=message):
        Evidence.model_validate({**valid_evidence(), **overrides})


@pytest.mark.parametrize("value", [18.2, 15, True, "loud snoring", ["fatigue"], None])
def test_evidence_accepts_normalized_value_types(value: object) -> None:
    """Values may be numbers, flags, text, lists, or absent."""
    assert Evidence.model_validate({**valid_evidence(), "value": value}).value == value


def test_evidence_is_frozen() -> None:
    """Evidence can't be edited after extraction."""
    evidence = Evidence.model_validate(valid_evidence())
    with pytest.raises(pydantic.ValidationError):
        evidence.value = 3.0
