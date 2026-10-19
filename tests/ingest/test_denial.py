"""Tests for the denial parser (T7, step 1). The LLM is faked."""

import datetime as dt
from typing import Any

import pytest

from pair.contracts import Denial
from pair.contracts.denial import PlanType, ReasonCategory
from pair.ingest.denial import DENIAL_SCHEMA, DenialParseError, parse_denial
from pair.llm import LLMError
from tests.contracts.factories import valid_denial
from tests.fakes import FakeLLM

LETTER = (
    "SYNTHETIC TEST LETTER\nNotice of Denial of Medical Coverage\nDate: September 1, 2026\n"
    "We denied: CPAP device (E0601). Reason: Records do not show a face-to-face evaluation "
    "before the sleep test. Policy: LCD L33718.\n"
)


def reply(**overrides: Any) -> dict[str, Any]:
    """A JSON reply as the LLM would send it (date as an ISO string)."""
    data = {**valid_denial(), "date": "2026-09-01"}
    data.update(overrides)
    return data


def test_schema_lists_every_field_and_enum() -> None:
    """The schema sent to the LLM covers the whole Denial contract, with enums inlined."""
    assert set(DENIAL_SCHEMA["properties"]) == set(Denial.model_fields)
    assert set(DENIAL_SCHEMA["required"]) == set(Denial.model_fields)
    props = DENIAL_SCHEMA["properties"]
    assert props["reason_category"]["enum"] == [c.value for c in ReasonCategory]
    assert props["plan_type"]["enum"] == [p.value for p in PlanType]
    assert "$ref" not in str(DENIAL_SCHEMA)


def test_valid_reply_parses_first_try() -> None:
    """A schema-valid reply becomes a Denial after one call; the letter is in the prompt."""
    fake = FakeLLM([reply()])
    parsed = parse_denial(LETTER, fake)
    assert parsed.denial == Denial(**valid_denial())
    assert parsed.attempts == 1
    assert LETTER in fake.prompts[0]
    assert fake.schemas[0] is DENIAL_SCHEMA


def test_codes_are_cleaned() -> None:
    """Codes are stripped, upper-cased and de-duplicated; blank codes are dropped."""
    parsed = parse_denial(LETTER, FakeLLM([reply(codes=[" e0601 ", "E0601", ""])]))
    assert parsed.denial.codes == ["E0601"]


def test_blank_policy_ref_becomes_none() -> None:
    """An empty policy_ref string means the letter cites no policy."""
    parsed = parse_denial(LETTER, FakeLLM([reply(policy_ref="  ")]))
    assert parsed.denial.policy_ref is None


def test_invalid_then_valid_retries_once_with_the_error() -> None:
    """A validation error is fed back in a second prompt, which can succeed."""
    fake = FakeLLM([reply(reason_category="denied"), reply()])
    parsed = parse_denial(LETTER, fake)
    assert parsed.attempts == 2
    assert parsed.denial.reason_category is ReasonCategory.INSUFFICIENT_DOCUMENTATION
    assert "reason_category" in fake.prompts[1]
    assert LETTER in fake.prompts[1]


def test_non_json_reply_counts_as_a_failed_attempt() -> None:
    """A reply that isn't a JSON object is retried like a validation error."""
    fake = FakeLLM(["not json", reply()])
    assert parse_denial(LETTER, fake).attempts == 2


def test_invalid_twice_raises() -> None:
    """Two bad replies raise DenialParseError with the last error."""
    fake = FakeLLM([reply(date="someday"), reply(date="someday")])
    with pytest.raises(DenialParseError, match="date"):
        parse_denial(LETTER, fake)
    assert len(fake.prompts) == 2


def test_transport_error_is_not_retried() -> None:
    """A transport failure isn't the model's fault, so it propagates at once."""
    fake = FakeLLM([LLMError("tunnel down"), reply()])
    with pytest.raises(LLMError, match="tunnel down"):
        parse_denial(LETTER, fake)
    assert len(fake.prompts) == 1


def test_empty_letter_is_rejected_without_a_call() -> None:
    """Blank input fails fast."""
    fake = FakeLLM([])
    with pytest.raises(DenialParseError, match="empty"):
        parse_denial("   ", fake)
    assert fake.prompts == []


def test_date_parses_to_a_date() -> None:
    """The ISO date string becomes a ``datetime.date``."""
    assert parse_denial(LETTER, FakeLLM([reply()])).denial.date == dt.date(2026, 9, 1)


def test_codes_as_a_string_is_a_validation_failure() -> None:
    """A non-list ``codes`` is left for Pydantic to reject, then retried."""
    fake = FakeLLM([reply(codes="E0601"), reply()])
    assert parse_denial(LETTER, fake).attempts == 2
