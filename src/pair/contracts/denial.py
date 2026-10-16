"""``Denial``: the structured form of a prior authorization denial letter (step 1).

CMS-0057-F requires plans to give a *specific* reason for a denial but does not
define a fixed list of reason codes, so ``ReasonCategory`` is PAIR's own small
taxonomy for routing a denial to the right explanation and checklist.
"""

import datetime as dt
from enum import StrEnum

from pair.contracts._base import ContractModel, NonEmptyStr


class ReasonCategory(StrEnum):
    """Why the plan said no, in PAIR's routing taxonomy."""

    CRITERIA_NOT_MET = "criteria_not_met"
    INSUFFICIENT_DOCUMENTATION = "insufficient_documentation"
    NOT_MEDICALLY_NECESSARY = "not_medically_necessary"
    NOT_COVERED_BENEFIT = "not_covered_benefit"
    ADMINISTRATIVE = "administrative"
    OTHER = "other"


class PlanType(StrEnum):
    """The kind of plan that issued the denial. PAIR v2 supports MA only."""

    MEDICARE_ADVANTAGE = "medicare_advantage"
    OTHER = "other"


class Denial(ContractModel):
    """A parsed denial letter.

    Attributes:
        service: The item or service that was denied, in the letter's words.
        codes: HCPCS or CPT codes named in the letter (may be empty).
        reason_text: The denial reason quoted from the letter.
        reason_category: PAIR's category for the reason.
        policy_ref: The NCD/LCD id the letter cites, if any.
        plan_type: The plan type that issued the denial.
        date: The date on the denial letter.
    """

    service: NonEmptyStr
    codes: list[NonEmptyStr]
    reason_text: NonEmptyStr
    reason_category: ReasonCategory
    policy_ref: NonEmptyStr | None
    plan_type: PlanType
    date: dt.date
