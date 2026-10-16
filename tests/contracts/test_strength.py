"""Tests for the ``Strength`` contract (ADR-0007)."""

import copy

import pydantic
import pytest

from pair.contracts import Strength
from tests.contracts.factories import valid_strength


def test_valid_strength_round_trips() -> None:
    """A valid strength with explanation round-trips."""
    strength = Strength.model_validate(valid_strength())
    assert Strength.model_validate_json(strength.model_dump_json()) == strength
    assert strength.explanation.improve[0].p_if_fixed == pytest.approx(0.71)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"p": 1.2}, "p"),
        ({"interval": {"low": 0.7, "high": 0.5}}, "low must not exceed high"),
        ({"p": 0.9}, "p must lie inside the interval"),
        ({"abstain": True}, "abstain_reason is required"),
        ({"abstain_reason": "too wide"}, "only when abstaining"),
    ],
)
def test_strength_rejects_inconsistent_values(overrides: dict[str, object], message: str) -> None:
    """Probabilities, intervals and abstention must agree."""
    with pytest.raises(pydantic.ValidationError, match=message):
        Strength.model_validate({**valid_strength(), **overrides})


def test_abstaining_strength_is_valid() -> None:
    """Abstention with a reason is a valid result."""
    kwargs = {**valid_strength(), "abstain": True, "abstain_reason": "critical criterion insufficient"}
    assert Strength.model_validate(kwargs).abstain


def test_improve_only_for_insufficient_steps() -> None:
    """There is no 'raise your odds' path for met or unmet criteria (ADR-0007)."""
    kwargs = copy.deepcopy(valid_strength())
    kwargs["explanation"]["improve"][0]["criterion_id"] = "ahi_threshold"
    with pytest.raises(pydantic.ValidationError, match="only insufficient criteria"):
        Strength.model_validate(kwargs)


def test_shift_must_be_positive_odds_multiplier() -> None:
    """Shifts multiply odds, so they must be positive."""
    kwargs = copy.deepcopy(valid_strength())
    kwargs["explanation"]["steps"][0]["shift"] = 0
    with pytest.raises(pydantic.ValidationError, match="shift"):
        Strength.model_validate(kwargs)
