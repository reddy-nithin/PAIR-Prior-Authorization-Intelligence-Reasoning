"""``Evidence``: one grounded fact extracted from a patient record (step 3)."""

import datetime as dt
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from pair.contracts._base import ContractModel, Identifier, NonEmptyStr, check_span

EvidenceValue = float | int | bool | dt.date | str | list[str] | None
"""A normalized value, e.g. ``18.2`` for "AHI of 18.2 events/hr"."""


class EvidenceStatus(StrEnum):
    """How the record states the fact."""

    ASSERTED = "asserted"
    NEGATED = "negated"
    UNCERTAIN = "uncertain"


class Evidence(ContractModel):
    """A value for one rule variable, tied to exact characters in a record.

    Attributes:
        criterion_id: The criterion this evidence is for.
        variable: The rule variable it supplies (ADR-0008), e.g. ``ahi``.
        value: The normalized value, or None if only the mention was found.
        span_text: The exact text from the record.
        char_start: Inclusive start offset of ``span_text`` in the record.
        char_end: Exclusive end offset of ``span_text`` in the record.
        doc_id: Id of the record (note, report) the span comes from.
        status: Whether the record asserts, negates or hedges the fact.
    """

    criterion_id: NonEmptyStr
    variable: Identifier
    value: EvidenceValue
    span_text: NonEmptyStr
    char_start: int = Field(ge=0)
    char_end: int
    doc_id: NonEmptyStr
    status: EvidenceStatus

    @model_validator(mode="after")
    def _check_span(self) -> Self:
        """Offsets must be ordered and agree with the span length."""
        check_span(self.span_text, self.char_start, self.char_end)
        return self
