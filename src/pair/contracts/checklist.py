"""``Checklist`` and ``Criterion``: a coverage policy as an executable checklist (step 2).

Rule and logic strings are validated against ADR-0008 by the policy loader;
this module checks structure only.
"""

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from pair.contracts._base import ContractModel, Identifier, NonEmptyStr, Slug


class EvidenceType(StrEnum):
    """The kind of record that supplies evidence for a criterion."""

    ENCOUNTER = "encounter"
    LAB_VALUE = "lab_value"
    DEVICE_REPORT = "device_report"
    THERAPY_HISTORY = "therapy_history"


class VariableType(StrEnum):
    """Types a rule variable or context flag may take (ADR-0008)."""

    NUMBER = "number"
    BOOL = "bool"
    DATE = "date"
    TEXT = "text"
    LIST = "list"


HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://\S+$")]


class PolicySource(ContractModel):
    """One official coverage document a checklist is built from.

    Attributes:
        type: NCD, LCD or a policy article.
        id: The document id, e.g. ``240.4`` or ``L33718``.
        title: The document title as published in the MCD.
        url: Link to the document in the Medicare Coverage Database.
        version: The document version the clauses were copied from.
        retrieved: The date the clause text was pulled from the MCD export.
    """

    type: Literal["NCD", "LCD", "Article"]
    id: NonEmptyStr
    title: NonEmptyStr
    url: HttpsUrl
    version: NonEmptyStr | None
    retrieved: dt.date


class Criterion(ContractModel):
    """One checkable requirement of a coverage policy.

    Attributes:
        id: Identifier used in rule traces, ``logic`` and citations (no dashes).
        text: Plain-language summary of the requirement.
        clause: Verbatim policy text the requirement comes from.
        source_id: Id of the ``PolicySource`` the clause is quoted from.
        evidence_type: The kind of record that can satisfy it.
        variables: Names and types the rule reads (ADR-0008).
        rule: Restricted Python expression over ``variables`` (ADR-0008).
        critical: If insufficient, the strength score abstains (ADR-0007).
    """

    id: Identifier
    text: NonEmptyStr
    clause: NonEmptyStr
    source_id: NonEmptyStr
    evidence_type: EvidenceType
    variables: dict[Identifier, VariableType] = Field(min_length=1)
    rule: NonEmptyStr
    critical: bool


class Checklist(ContractModel):
    """A coverage policy as a list of criteria plus a combining ``logic`` expression.

    Attributes:
        id: Policy slug, e.g. ``pap-osa``; matches the YAML file name.
        title: Human-readable policy title.
        sources: Official documents the criteria quote.
        context: Case-level flags ``logic`` may read, e.g. ``initial``.
        criteria: The criteria, in display order.
        logic: Expression over criterion ids and context flags (ADR-0008).
    """

    id: Slug
    title: NonEmptyStr
    sources: list[PolicySource] = Field(min_length=1)
    context: dict[Identifier, VariableType] = Field(default_factory=dict)
    criteria: list[Criterion] = Field(min_length=1)
    logic: NonEmptyStr

    @property
    def criterion_ids(self) -> tuple[str, ...]:
        """Return criterion ids in display order."""
        return tuple(criterion.id for criterion in self.criteria)

    @model_validator(mode="after")
    def _check_ids_and_sources(self) -> Self:
        """Reject duplicate criterion ids and criteria quoting undeclared sources."""
        seen: set[str] = set()
        for criterion_id in self.criterion_ids:
            if criterion_id in seen:
                raise ValueError(f"duplicate criterion id: {criterion_id}")
            seen.add(criterion_id)
        source_ids = {source.id for source in self.sources}
        for criterion in self.criteria:
            if criterion.source_id not in source_ids:
                raise ValueError(
                    f"criterion {criterion.id} cites unknown source {criterion.source_id}"
                )
        return self
