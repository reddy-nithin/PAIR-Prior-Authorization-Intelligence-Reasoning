"""Tests for the ``Claim`` and ``Letter`` contracts."""

import pydantic
import pytest

from pair.contracts import Claim, ClaimDecision, Letter
from tests.contracts.factories import valid_claim


def test_valid_letter_round_trips() -> None:
    """A letter with one verified claim round-trips."""
    claim = {**valid_claim(), "score": 0.91, "decision": "keep"}
    letter = Letter.model_validate({"policy_id": "pap-osa", "claims": [claim]})
    assert Letter.model_validate_json(letter.model_dump_json()) == letter
    assert letter.claims[0].decision is ClaimDecision.KEEP


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"score": 1.5}, "score"),
        ({"decision": "maybe"}, "decision"),
        ({"text": ""}, "text"),
        ({"policy_cite": {"source_id": "L33718", "quote": ""}}, "quote"),
    ],
)
def test_claim_rejects_bad_values(overrides: dict[str, object], message: str) -> None:
    """Scores are probabilities, decisions are known, quotes are non-empty."""
    with pytest.raises(pydantic.ValidationError, match=message):
        Claim.model_validate({**valid_claim(), **overrides})


def test_evidence_citation_offsets_must_match_quote() -> None:
    """The record quote length must agree with its offsets."""
    cite = {**valid_claim()["evidence_cite"], "quote": "AHI"}
    with pytest.raises(pydantic.ValidationError, match="span length"):
        Claim.model_validate({**valid_claim(), "evidence_cite": cite})


def test_decision_requires_score() -> None:
    """A verifier decision without a score is not traceable."""
    with pytest.raises(pydantic.ValidationError, match="decision requires a score"):
        Claim.model_validate({**valid_claim(), "decision": "keep"})
