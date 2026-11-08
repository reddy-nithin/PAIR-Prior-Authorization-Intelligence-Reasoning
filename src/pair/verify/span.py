"""Deterministic citation checks, run before the entailment model (step 6, ADR-0018).

Three checks, all exact (no whitespace or case normalizing):

- the record quote equals ``document[char_start:char_end]``;
- the policy quote is a verbatim part of the claim's criterion clause, from that
  clause's source (clauses were checked against the MCD export when loaded);
- the criterion link: the record span is an asserted ``Evidence`` item bound to
  the claim's own criterion. This catches the "wrong criterion" fault in code.

A claim that fails any check is DROPPED with score 0 and never reaches the
entailment model or the conformal sets.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pair.contracts import (
    Checklist,
    Claim,
    ClaimDecision,
    Evidence,
    EvidenceStatus,
    Letter,
)

logger = logging.getLogger(__name__)


class CitationError(ValueError):
    """A letter is checked against a checklist for another policy."""


@dataclass(frozen=True)
class CitationCheck:
    """The outcome for one claim: ``ok``, or the first reason it failed."""

    ok: bool
    reason: str | None = None


def check_citations(
    claim: Claim, checklist: Checklist, documents: Mapping[str, str], evidence: Sequence[Evidence]
) -> CitationCheck:
    """Check one claim's record quote, policy quote and criterion link.

    Args:
        claim: The worded claim.
        checklist: The checklist the claim argues.
        documents: Record texts by document id.
        evidence: The evidence the rule engine used for this case.

    Returns:
        ``CitationCheck(ok=True)``, or ``ok=False`` with the first failed check.
    """
    criterion = next((c for c in checklist.criteria if c.id == claim.criterion_id), None)
    if criterion is None:
        return CitationCheck(False, f"criterion {claim.criterion_id} is not in {checklist.id}")
    cite = claim.evidence_cite
    document = documents.get(cite.doc_id)
    if document is None:
        return CitationCheck(False, f"record quote cites unknown document {cite.doc_id}")
    if document[cite.char_start : cite.char_end] != cite.quote:
        return CitationCheck(False, f"record quote differs from {cite.doc_id}[{cite.char_start}:{cite.char_end}]")
    policy = claim.policy_cite
    if policy.source_id != criterion.source_id or policy.quote not in criterion.clause:
        return CitationCheck(False, f"policy quote is not verbatim from the {criterion.id} clause")
    linked = any(
        item.criterion_id == claim.criterion_id
        and item.status is EvidenceStatus.ASSERTED
        and (item.doc_id, item.char_start, item.char_end) == (cite.doc_id, cite.char_start, cite.char_end)
        for item in evidence
    )
    if not linked:
        return CitationCheck(False, f"criterion link: span is not asserted evidence for {claim.criterion_id}")
    return CitationCheck(True)


def apply_citation_checks(
    letter: Letter, checklist: Checklist, documents: Mapping[str, str], evidence: Sequence[Evidence]
) -> tuple[Letter, tuple[CitationCheck, ...]]:
    """Run ``check_citations`` on every claim and DROP the failures.

    Returns:
        The letter with failed claims set to DROP and score 0 (passing claims are
        unchanged), and one check result per claim in letter order.

    Raises:
        CitationError: If the letter is for another policy.
    """
    if letter.policy_id != checklist.id:
        raise CitationError(f"letter is for policy {letter.policy_id}, not {checklist.id}")
    results = tuple(check_citations(claim, checklist, documents, evidence) for claim in letter.claims)
    claims = [
        claim if result.ok else claim.model_copy(update={"score": 0.0, "decision": ClaimDecision.DROP})
        for claim, result in zip(letter.claims, results, strict=True)
    ]
    for claim, result in zip(letter.claims, results, strict=True):
        if not result.ok:
            logger.warning("claim for %s dropped: %s", claim.criterion_id, result.reason)
    return letter.model_copy(update={"claims": claims}), results
