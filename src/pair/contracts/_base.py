"""Shared base model and validators for every PAIR contract."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
"""A string that must contain at least one character."""

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*$")]
"""A lowercase identifier such as ``ahi_threshold`` or ``pap-osa``."""

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]*$")]
"""A rule-language variable name such as ``ahi`` (ADR-0008)."""

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
"""A float in the closed interval [0, 1]."""


class ContractModel(BaseModel):
    """Base for all contracts: immutable, and unknown fields are an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def check_span(span_text: str, char_start: int, char_end: int) -> None:
    """Validate that character offsets are ordered and match the span text.

    Args:
        span_text: The quoted text taken from the source document.
        char_start: Inclusive start offset in the source document.
        char_end: Exclusive end offset in the source document.

    Raises:
        ValueError: If ``char_end <= char_start`` or the span length disagrees
            with the offsets.
    """
    if char_end <= char_start:
        raise ValueError(f"char_end must be greater than char_start ({char_start}, {char_end})")
    if len(span_text) != char_end - char_start:
        raise ValueError(
            f"span length {len(span_text)} does not match offsets {char_start}..{char_end}"
        )
