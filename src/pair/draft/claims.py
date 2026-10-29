"""Claim slots: what the letter may argue, one slot per record fact (step 5, ADR-0018).

A slot is a claim before wording: the criterion it argues, the verbatim policy
clause, and one record quote the rule engine actually used. Only met criteria
get slots. Unmet and insufficient criteria are listed as skipped, with their gap
message, so the UI can say why they aren't argued. The LLM words each slot in a
later step; it never chooses what to claim.
"""

import logging
from dataclasses import dataclass

from pair.contracts import (
    Checklist,
    Criterion,
    CriterionResult,
    CriterionStatus,
    Evidence,
    EvidenceCitation,
    EvidenceStatus,
    PolicyCitation,
    Verdict,
)
from pair.rules.engine import value_fits

logger = logging.getLogger(__name__)


class ClaimPlanError(ValueError):
    """The verdict doesn't belong to the checklist it is planned against."""


@dataclass(frozen=True)
class ClaimSlot:
    """One fact the letter may claim, with its two citations.

    Attributes:
        criterion_id: The met criterion this fact supports.
        variables: The rule variables this record quote supplied, in rule order.
        policy_cite: The criterion's verbatim clause and its source.
        evidence_cite: The record quote and its offsets.
    """

    criterion_id: str
    variables: tuple[str, ...]
    policy_cite: PolicyCitation
    evidence_cite: EvidenceCitation


@dataclass(frozen=True)
class SkippedCriterion:
    """A criterion the letter doesn't argue, and the gap message explaining why."""

    criterion_id: str
    status: CriterionStatus
    message: str


@dataclass(frozen=True)
class ClaimPlan:
    """Claim slots in letter order, plus the criteria left out."""

    slots: tuple[ClaimSlot, ...]
    skipped: tuple[SkippedCriterion, ...]


def plan_claims(checklist: Checklist, verdict: Verdict) -> ClaimPlan:
    """Turn a verdict into claim slots: one per distinct record quote of each met criterion.

    Args:
        checklist: The checklist the verdict was produced from.
        verdict: The rule engine's verdict for one case.

    Returns:
        Slots in checklist order, then document order within a criterion, and the
        skipped (unmet or insufficient) criteria with their gap messages.

    Raises:
        ClaimPlanError: If the verdict is for another policy or names a criterion
            the checklist doesn't have.
    """
    if verdict.policy_id != checklist.id:
        raise ClaimPlanError(f"verdict is for policy {verdict.policy_id}, not {checklist.id}")
    criteria = {criterion.id: criterion for criterion in checklist.criteria}
    results = {result.criterion_id: result for result in verdict.results}
    unknown = sorted(set(results) - set(criteria))
    if unknown:
        raise ClaimPlanError(f"verdict has results for criteria not in {checklist.id}: {unknown}")
    missing = [criterion_id for criterion_id in checklist.criterion_ids if criterion_id not in results]
    if missing:
        raise ClaimPlanError(f"verdict has no result for criteria of {checklist.id}: {missing}")
    gaps = {gap.criterion_id: gap.message for gap in verdict.gaps}

    slots: list[ClaimSlot] = []
    skipped: list[SkippedCriterion] = []
    for criterion_id in checklist.criterion_ids:
        result = results[criterion_id]
        if result.status is CriterionStatus.MET:
            slots.extend(_slots_for(criteria[criterion_id], result))
        else:
            skipped.append(SkippedCriterion(criterion_id, result.status, gaps.get(criterion_id, "")))
    logger.info("policy %s: %d claim slots, %d criteria skipped", checklist.id, len(slots), len(skipped))
    return ClaimPlan(slots=tuple(slots), skipped=tuple(skipped))


def _slots_for(criterion: Criterion, result: CriterionResult) -> list[ClaimSlot]:
    """One slot per distinct span among the evidence the rule could bind."""
    by_span: dict[tuple[str, int, int], list[Evidence]] = {}
    for item in result.evidence:
        if _is_bound(criterion, item):
            by_span.setdefault((item.doc_id, item.char_start, item.char_end), []).append(item)
    policy_cite = PolicyCitation(source_id=criterion.source_id, quote=criterion.clause)
    order = list(criterion.variables)
    slots = []
    for (doc_id, start, end), items in sorted(by_span.items()):
        variables = tuple(sorted({item.variable for item in items}, key=order.index))
        cite = EvidenceCitation(doc_id=doc_id, char_start=start, char_end=end, quote=items[0].span_text)
        slots.append(ClaimSlot(criterion.id, variables, policy_cite, cite))
    return slots


def _is_bound(criterion: Criterion, item: Evidence) -> bool:
    """Whether the engine used this item: asserted, with a value of the declared type."""
    return (
        item.status is EvidenceStatus.ASSERTED
        and item.value is not None
        and value_fits(criterion.variables[item.variable], item.value)
    )
