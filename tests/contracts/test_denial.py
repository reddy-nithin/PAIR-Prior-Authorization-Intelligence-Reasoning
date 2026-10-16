"""Tests for the ``Denial`` contract."""

import pydantic
import pytest

from pair.contracts import Denial, ReasonCategory
from tests.contracts.factories import valid_denial


def test_valid_denial_round_trips() -> None:
    """A valid denial survives a JSON round-trip unchanged."""
    denial = Denial.model_validate(valid_denial())
    assert Denial.model_validate_json(denial.model_dump_json()) == denial
    assert denial.reason_category is ReasonCategory.INSUFFICIENT_DOCUMENTATION


def test_denial_is_frozen() -> None:
    """Contracts are immutable once built."""
    denial = Denial.model_validate(valid_denial())
    with pytest.raises(pydantic.ValidationError):
        denial.service = "Oxygen"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("reason_category", "because"),
        ("plan_type", "commercial_ppo"),
        ("date", "not-a-date"),
        ("service", ""),
        ("codes", [""]),
    ],
)
def test_denial_rejects_bad_values(field: str, bad_value: object) -> None:
    """Out-of-vocabulary or empty values fail validation."""
    with pytest.raises(pydantic.ValidationError):
        Denial.model_validate({**valid_denial(), field: bad_value})


def test_denial_rejects_unknown_field() -> None:
    """Unknown fields are an error, not silently dropped."""
    with pytest.raises(pydantic.ValidationError):
        Denial.model_validate({**valid_denial(), "member_id": "123"})


def test_policy_ref_is_optional() -> None:
    """Many denial letters cite no policy; that must be representable."""
    assert Denial.model_validate({**valid_denial(), "policy_ref": None}).policy_ref is None
