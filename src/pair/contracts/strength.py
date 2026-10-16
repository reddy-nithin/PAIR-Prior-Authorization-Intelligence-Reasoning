"""``Strength``: calibrated appeal strength with an explanation (step 7, ADR-0007)."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from pair.contracts._base import ContractModel, NonEmptyStr, Probability
from pair.contracts.verdict import CriterionStatus


class Interval(ContractModel):
    """A probability range shown to the patient."""

    low: Probability
    high: Probability

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        """The lower bound can't exceed the upper bound."""
        if self.low > self.high:
            raise ValueError(f"low must not exceed high ({self.low} > {self.high})")
        return self


class Step(ContractModel):
    """One adjustment from the base rate: an odds multiplier for one criterion."""

    criterion_id: NonEmptyStr
    status: CriterionStatus
    shift: Annotated[float, Field(gt=0.0)]
    why: NonEmptyStr


class Improvement(ContractModel):
    """What the patient can do about one insufficient criterion, and its effect."""

    criterion_id: NonEmptyStr
    action: NonEmptyStr
    p_if_fixed: Probability


class Explanation(ContractModel):
    """How the estimate was built (steps) and what would raise it (improve)."""

    base_rate: Probability
    n_similar: int = Field(ge=0)
    imr_category: NonEmptyStr
    steps: list[Step]
    improve: list[Improvement]

    @model_validator(mode="after")
    def _check_improve_targets(self) -> Self:
        """Only insufficient criteria get a 'what helps' path (ADR-0007)."""
        insufficient = {s.criterion_id for s in self.steps if s.status is CriterionStatus.INSUFFICIENT}
        for item in self.improve:
            if item.criterion_id not in insufficient:
                raise ValueError(
                    f"improve may target only insufficient criteria, not {item.criterion_id}"
                )
        return self


class Strength(ContractModel):
    """Appeal strength: point estimate, range, abstention and explanation.

    Attributes:
        p: Point estimate of the chance the appeal is overturned.
        interval: Calibrated range around ``p``.
        abstain: True when PAIR should say "get a human" instead of a number.
        abstain_reason: Why it abstained; required iff ``abstain``.
        explanation: Base rate, adjustment steps and improvement options.
    """

    p: Probability
    interval: Interval
    abstain: bool
    abstain_reason: NonEmptyStr | None
    explanation: Explanation

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        """``p`` lies in its interval, and a reason is given exactly when abstaining."""
        if not self.interval.low <= self.p <= self.interval.high:
            raise ValueError(f"p must lie inside the interval ({self.p} not in {self.interval})")
        if self.abstain and self.abstain_reason is None:
            raise ValueError("abstain_reason is required when abstaining")
        if not self.abstain and self.abstain_reason is not None:
            raise ValueError("abstain_reason is allowed only when abstaining")
        return self
