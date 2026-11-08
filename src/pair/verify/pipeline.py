"""Step 6 as one call: citation checks, then entailment, then the conformal threshold.

Claims that fail a citation check are DROPPED and never scored. The rest are
scored against ``build_premise``. With a fitted threshold for the running
(drafter, verifier) pair, a claim is KEPT or FLAGGED. Without one, nothing is
KEPT: claims the verifier answers "No" to (P(Yes) < 0.5) are FLAGGED, the rest
keep their score with no decision and are shown as "not evaluated" (ADR-0018).
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pair.contracts import Checklist, ClaimDecision, Evidence, Letter
from pair.verify.conformal import ConformalError, Threshold, decide
from pair.verify.nli import PREMISE_RULE, Verifier, build_premise
from pair.verify.span import CitationCheck, apply_citation_checks

logger = logging.getLogger(__name__)

NO_THRESHOLD_FLAG_BELOW = 0.5


@dataclass(frozen=True)
class VerifiedLetter:
    """The letter with scores and decisions, plus what produced them.

    Attributes:
        letter: Claims with ``score`` and ``decision`` set where available.
        citations: Citation check per claim, in letter order.
        premises: The premise each claim was scored on (None if dropped).
        metadata: Drafter, verifier backend/model/host and threshold status.
    """

    letter: Letter
    citations: tuple[CitationCheck, ...]
    premises: tuple[str | None, ...]
    metadata: dict[str, str]


def verify_letter(
    letter: Letter,
    checklist: Checklist,
    documents: Mapping[str, str],
    evidence: Sequence[Evidence],
    verifier: Verifier,
    threshold: Threshold | None,
    drafter: str,
) -> VerifiedLetter:
    """Verify every claim of one letter.

    Args:
        letter: Worded claims with no decisions yet.
        checklist: The checklist the letter argues.
        documents: Record texts by document id.
        evidence: The evidence the rule engine used.
        verifier: The entailment backend.
        threshold: The fitted threshold for (drafter, verifier), or None.
        drafter: The model tag that worded the claims.

    Returns:
        The verified letter and run metadata.

    Raises:
        ConformalError: If ``threshold`` belongs to another (drafter, verifier) pair.
        LLMError: If the verifier backend fails.
    """
    info = verifier.describe()
    key = (drafter, info["verifier_backend"], info["verifier_model"])
    if threshold is not None and threshold.key != key:
        raise ConformalError(f"threshold is for {threshold.key}, not {key}")
    if threshold is not None and threshold.premise_rule != PREMISE_RULE:
        raise ConformalError(f"threshold was fit on premise rule {threshold.premise_rule}, not {PREMISE_RULE} (ADR-0022)")
    checked, citations = apply_citation_checks(letter, checklist, documents, evidence)
    claims = []
    premises: list[str | None] = []
    for claim, citation in zip(checked.claims, citations, strict=True):
        if not citation.ok:
            claims.append(claim)
            premises.append(None)
            continue
        cite = claim.evidence_cite
        premise = build_premise(documents[cite.doc_id], cite.char_start, cite.char_end)
        score = verifier.score(claim.text, premise)
        if threshold is not None:
            decision: ClaimDecision | None = decide(score, threshold)
        else:
            decision = ClaimDecision.FLAG if score < NO_THRESHOLD_FLAG_BELOW else None
        claims.append(claim.model_copy(update={"score": score, "decision": decision}))
        premises.append(premise)
    metadata = {"drafter": drafter, **info, "premise_rule": PREMISE_RULE,
                "threshold": "fitted" if threshold is not None else "none"}
    logger.info("verified %d claims for %s with %s", len(claims), checklist.id, metadata)
    return VerifiedLetter(checked.model_copy(update={"claims": claims}), citations, tuple(premises), metadata)
