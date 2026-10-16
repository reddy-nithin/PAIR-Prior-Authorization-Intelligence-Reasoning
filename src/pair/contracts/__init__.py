"""Typed contracts between PAIR's pipeline steps (spec §4).

Every model is frozen and rejects unknown fields, so components can be built and
tested in isolation against these shapes.
"""

from pair.contracts.checklist import (
    Checklist,
    Criterion,
    EvidenceType,
    PolicySource,
    VariableType,
)
from pair.contracts.denial import Denial, PlanType, ReasonCategory
from pair.contracts.evidence import Evidence, EvidenceStatus, EvidenceValue
from pair.contracts.letter import (
    Claim,
    ClaimDecision,
    EvidenceCitation,
    Letter,
    PolicyCitation,
)
from pair.contracts.strength import Explanation, Improvement, Interval, Step, Strength
from pair.contracts.verdict import CriterionResult, CriterionStatus, Gap, Verdict

__all__ = [
    "Checklist",
    "Claim",
    "ClaimDecision",
    "Criterion",
    "CriterionResult",
    "CriterionStatus",
    "Denial",
    "Evidence",
    "EvidenceCitation",
    "EvidenceStatus",
    "EvidenceType",
    "EvidenceValue",
    "Explanation",
    "Gap",
    "Improvement",
    "Interval",
    "Letter",
    "PlanType",
    "PolicyCitation",
    "PolicySource",
    "ReasonCategory",
    "Step",
    "Strength",
    "VariableType",
    "Verdict",
]
