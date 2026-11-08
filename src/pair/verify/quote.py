"""Quote sentences: a flagged paraphrase of a met criterion becomes the record sentence, word for word (ADR-0024).

The verifier scores the letter's first-person wording ("I used…") against a record
written about "the patient", and flags some true facts. When the rule engine has
already marked the criterion met from that record span, the letter quotes the
premise sentence (``build_premise``) verbatim instead. A verbatim quote says only
what the record says, so it is checked by exact string match, not by the verifier.
This runs after step 6, so the conformal metrics on generated claims are unchanged.
"""

import logging
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from pair.contracts import Claim, ClaimDecision, EvidenceCitation, Letter
from pair.verify.nli import build_premise

logger = logging.getLogger(__name__)

QUOTE_PREFIX = "My records state: "
SEARCH_BACK = 1000  # premises reach at most ~600 characters before the quote (ADR-0022 caps)


class QuoteError(ValueError):
    """A premise could not be located in its record."""


@dataclass(frozen=True)
class QuotedLetter:
    """The letter after quoting, and the flagged paraphrases that quotes replaced.

    Attributes:
        letter: Claims in their original order, with replaced paraphrases swapped for QUOTE claims.
        replaced: The FLAGGED claims now covered by a quote (kept for the run log).
    """

    letter: Letter
    replaced: tuple[Claim, ...]


def _premise_span(document: str, char_start: int, char_end: int) -> tuple[int, int, str]:
    """The premise of a span and its offsets in ``document``.

    Raises:
        QuoteError: If the premise isn't a slice covering the span (it always should be).
    """
    premise = build_premise(document, char_start, char_end)
    start = document.find(premise, max(0, char_start - SEARCH_BACK), char_start + len(premise))
    if start < 0 or start > char_start or start + len(premise) < char_end:
        raise QuoteError(f"premise for {char_start}..{char_end} is not a slice around the quote")
    return start, start + len(premise), premise


def _inside(claim: Claim, doc_id: str, start: int, end: int) -> bool:
    """Whether the claim cites a span inside ``[start, end)`` of ``doc_id``."""
    cite = claim.evidence_cite
    return cite.doc_id == doc_id and start <= cite.char_start and cite.char_end <= end


def quote_flagged(letter: Letter, notes: Mapping[str, str], met: AbstractSet[str]) -> QuotedLetter:
    """Replace FLAGGED claims of met criteria with one verbatim quote per record sentence.

    Args:
        letter: The verified letter (step 6 output).
        notes: Record text by doc id.
        met: Criterion ids the rule engine marked met.

    Returns:
        The letter with quotes in place of the paraphrases they cover.

    Raises:
        QuoteError: If a cited record is missing or a premise can't be located.
    """
    claims: list[Claim] = []
    replaced: list[Claim] = []
    quoted: set[tuple[str, str, int]] = set()
    for claim in letter.claims:
        if claim.decision is not ClaimDecision.FLAG or claim.criterion_id not in met:
            claims.append(claim)
            continue
        cite = claim.evidence_cite
        if cite.doc_id not in notes:
            raise QuoteError(f"claim cites unknown record {cite.doc_id!r}")
        start, end, premise = _premise_span(notes[cite.doc_id], cite.char_start, cite.char_end)
        key = (claim.criterion_id, cite.doc_id, start)
        if key in quoted:
            replaced.append(claim)
            continue
        kept_same = any(
            other.decision is ClaimDecision.KEEP and other.criterion_id == claim.criterion_id
            and _inside(other, cite.doc_id, start, end)
            for other in letter.claims
        )  # fmt: skip
        if kept_same:
            claims.append(claim)
            continue
        quoted.add(key)
        replaced.append(claim)
        claims.append(
            claim.model_copy(update={
                "text": f'{QUOTE_PREFIX}"{premise}"' + ("" if premise[-1] in ".!?" else "."),
                "evidence_cite": EvidenceCitation(doc_id=cite.doc_id, char_start=start, char_end=end, quote=premise),
                "decision": ClaimDecision.QUOTE,
            })
        )  # fmt: skip
    if replaced:
        logger.info("letter %s: %d flagged claim(s) covered by %d quote(s)", letter.policy_id, len(replaced), len(quoted))
    return QuotedLetter(letter.model_copy(update={"claims": claims}), tuple(replaced))
