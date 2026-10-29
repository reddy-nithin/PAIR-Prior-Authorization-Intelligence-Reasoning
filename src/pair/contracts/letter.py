"""``Claim`` and ``Letter``: the drafted appeal, one cited claim per record fact (steps 5 and 6).

A met criterion backed by several facts gets several claims, each with one policy
quote and one record quote (ADR-0018). The schema is unchanged.
"""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from pair.contracts._base import ContractModel, NonEmptyStr, Probability, check_span


class ClaimDecision(StrEnum):
    """What the verifier decided about a claim."""

    KEEP = "keep"
    FLAG = "flag"
    DROP = "drop"


class PolicyCitation(ContractModel):
    """A verbatim quote from a policy source."""

    source_id: NonEmptyStr
    quote: NonEmptyStr


class EvidenceCitation(ContractModel):
    """A verbatim quote from a patient record, with its offsets."""

    doc_id: NonEmptyStr
    char_start: int = Field(ge=0)
    char_end: int
    quote: NonEmptyStr

    @model_validator(mode="after")
    def _check_span(self) -> Self:
        """Offsets must be ordered and agree with the quote length."""
        check_span(self.quote, self.char_start, self.char_end)
        return self


class Claim(ContractModel):
    """One sentence of the appeal, with exactly one policy and one record citation.

    Attributes:
        criterion_id: The criterion this claim argues.
        text: The sentence shown to the patient.
        policy_cite: The policy clause it relies on.
        evidence_cite: The record line it relies on.
        score: Verifier support score, set in step 6.
        decision: Verifier decision, set in step 6 (requires ``score``).
    """

    criterion_id: NonEmptyStr
    text: NonEmptyStr
    policy_cite: PolicyCitation
    evidence_cite: EvidenceCitation
    score: Probability | None = None
    decision: ClaimDecision | None = None

    @model_validator(mode="after")
    def _check_decision(self) -> Self:
        """A verifier decision is only traceable with the score behind it."""
        if self.decision is not None and self.score is None:
            raise ValueError("decision requires a score")
        return self


class Letter(ContractModel):
    """An appeal letter's claims for one policy."""

    policy_id: NonEmptyStr
    claims: list[Claim]
