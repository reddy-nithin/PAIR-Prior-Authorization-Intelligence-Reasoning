"""``Verdict``: the rule engine's per-criterion result and gap list (step 4)."""

from enum import StrEnum
from typing import Self

from pydantic import model_validator

from pair.contracts._base import ContractModel, NonEmptyStr
from pair.contracts.evidence import Evidence


class CriterionStatus(StrEnum):
    """Outcome of one criterion.

    ``met``: evidence satisfies the rule. ``unmet``: evidence contradicts it.
    ``insufficient``: no usable evidence, or only negated, vague or conflicting
    evidence.
    """

    MET = "met"
    UNMET = "unmet"
    INSUFFICIENT = "insufficient"


class CriterionResult(ContractModel):
    """Result for one criterion, with the evidence and trace behind it."""

    criterion_id: NonEmptyStr
    status: CriterionStatus
    evidence: list[Evidence]
    trace: NonEmptyStr


class Gap(ContractModel):
    """A plain-language request for what's missing for one criterion."""

    criterion_id: NonEmptyStr
    message: NonEmptyStr


class Verdict(ContractModel):
    """The checklist outcome for one case.

    Attributes:
        policy_id: The checklist that was applied.
        results: One result per criterion.
        overall: Outcome of the checklist ``logic``.
        gaps: One entry per unmet or insufficient criterion.
    """

    policy_id: NonEmptyStr
    results: list[CriterionResult]
    overall: CriterionStatus
    gaps: list[Gap]

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        """Results are unique, evidence matches its criterion, gaps match non-met results."""
        status_by_id: dict[str, CriterionStatus] = {}
        for result in self.results:
            if result.criterion_id in status_by_id:
                raise ValueError(f"duplicate result for criterion {result.criterion_id}")
            status_by_id[result.criterion_id] = result.status
            for item in result.evidence:
                if item.criterion_id != result.criterion_id:
                    raise ValueError(
                        f"evidence for {item.criterion_id} belongs to another criterion "
                        f"than {result.criterion_id}"
                    )
        needs_gap = {cid for cid, status in status_by_id.items() if status is not CriterionStatus.MET}
        gap_ids = {gap.criterion_id for gap in self.gaps}
        extra = gap_ids - needs_gap
        if extra:
            raise ValueError(f"gap given for criteria that are not unmet or insufficient: {sorted(extra)}")
        missing = needs_gap - gap_ids
        if missing:
            raise ValueError(f"missing gap for criteria: {sorted(missing)}")
        return self
