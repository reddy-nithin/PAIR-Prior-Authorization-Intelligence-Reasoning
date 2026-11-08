"""Tests for quote sentences replacing flagged paraphrases of met criteria (ADR-0024)."""

import pytest

from pair.contracts import (
    Claim,
    ClaimDecision,
    EvidenceCitation,
    Letter,
    PolicyCitation,
)
from pair.verify.nli import build_premise
from pair.verify.quote import QUOTE_PREFIX, QuoteError, quote_flagged

DOC = (
    "Home sleep test 03/10/2026. During this monitoring period, there were 131 total respiratory events, "
    "yielding an overall AHI 21.1 events/hour. The patient used 4 hours or more on 78% of nights."
)
NOTES = {"report": DOC}


def claim(criterion_id: str, quote: str, text: str, decision: ClaimDecision | None, score: float = 0.3) -> Claim:
    """A claim citing ``quote`` in ``DOC``."""
    start = DOC.index(quote)
    return Claim(
        criterion_id=criterion_id,
        text=text,
        policy_cite=PolicyCitation(source_id="L33718", quote="clause"),
        evidence_cite=EvidenceCitation(doc_id="report", char_start=start, char_end=start + len(quote), quote=quote),
        score=None if decision is None else score,
        decision=decision,
    )


def letter(*claims: Claim) -> Letter:
    """A PAP letter."""
    return Letter(policy_id="pap-osa", claims=list(claims))


def test_flagged_claim_of_met_criterion_becomes_the_record_sentence() -> None:
    """The paraphrase is replaced by the verbatim premise sentence, cited at its exact offsets."""
    flagged = claim("ahi_threshold", "AHI 21.1 events/hour", "My record states an AHI of 21.1 events/hour.",
                    ClaimDecision.FLAG, score=0.51)  # fmt: skip

    result = quote_flagged(letter(flagged), NOTES, met={"ahi_threshold"})

    [quoted] = result.letter.claims
    premise = build_premise(DOC, flagged.evidence_cite.char_start, flagged.evidence_cite.char_end)
    cite = quoted.evidence_cite
    assert quoted.decision is ClaimDecision.QUOTE
    assert cite.quote == premise == DOC[cite.char_start:cite.char_end]
    assert quoted.text == f'{QUOTE_PREFIX}"{premise}"'  # verbatim, so the letter cites it without repeating it
    assert quoted.score == 0.51 and quoted.policy_cite == flagged.policy_cite
    assert result.replaced == (flagged,)


def test_criteria_that_are_not_met_keep_their_flag() -> None:
    """Unmet or insufficient criteria are never argued with a quote."""
    flagged = claim("adherence", "used 4 hours or more on 78% of nights", "I used it 78% of nights.", ClaimDecision.FLAG)

    result = quote_flagged(letter(flagged), NOTES, met={"ahi_threshold"})

    assert result.letter.claims == [flagged] and result.replaced == ()


def test_kept_dropped_and_unscored_claims_are_untouched() -> None:
    """Only FLAG is replaced; a failed citation check (DROP) is never quoted."""
    kept = claim("ahi_threshold", "AHI 21.1 events/hour", "My AHI was 21.1.", ClaimDecision.KEEP, score=0.9)
    dropped = claim("adherence", "78% of nights", "I used it every night.", ClaimDecision.DROP)
    unscored = claim("adherence", "used 4 hours", "I used it 4 hours.", None)

    result = quote_flagged(letter(kept, dropped, unscored), NOTES, met={"ahi_threshold", "adherence"})

    assert result.letter.claims == [kept, dropped, unscored] and result.replaced == ()


def test_two_flagged_claims_on_one_sentence_give_one_quote() -> None:
    """Both paraphrases point at the same record sentence, so it is quoted once."""
    first = claim("ahi_threshold", "131 total respiratory events", "My record shows 131 events.", ClaimDecision.FLAG)
    second = claim("ahi_threshold", "AHI 21.1 events/hour", "My AHI was 21.1.", ClaimDecision.FLAG)

    result = quote_flagged(letter(first, second), NOTES, met={"ahi_threshold"})

    assert [c.decision for c in result.letter.claims] == [ClaimDecision.QUOTE]
    assert result.replaced == (first, second)


def test_sentence_already_backing_a_kept_claim_is_not_quoted_again() -> None:
    """A kept paraphrase from the same record sentence already argues it; the flagged one stays flagged."""
    kept = claim("ahi_threshold", "131 total respiratory events", "There were 131 events.", ClaimDecision.KEEP, 0.9)
    flagged = claim("ahi_threshold", "AHI 21.1 events/hour", "My AHI was 21.1.", ClaimDecision.FLAG)

    result = quote_flagged(letter(kept, flagged), NOTES, met={"ahi_threshold"})

    assert result.letter.claims == [kept, flagged] and result.replaced == ()


def test_quote_keeps_claim_order() -> None:
    """The quote takes the place of the first paraphrase it replaces."""
    a = claim("ahi_threshold", "Home sleep test 03/10/2026", "I had a sleep test.", ClaimDecision.KEEP, 0.9)
    b = claim("ahi_threshold", "AHI 21.1 events/hour", "My AHI was 21.1.", ClaimDecision.FLAG)
    c = claim("adherence", "78% of nights", "I used it 78% of nights.", ClaimDecision.KEEP, 0.9)

    result = quote_flagged(letter(a, b, c), NOTES, met={"ahi_threshold", "adherence"})

    assert [x.decision for x in result.letter.claims] == [ClaimDecision.KEEP, ClaimDecision.QUOTE, ClaimDecision.KEEP]


def test_unknown_record_is_an_error() -> None:
    """A flagged claim citing a record we don't have can't be quoted, and says so."""
    flagged = claim("ahi_threshold", "AHI 21.1 events/hour", "My AHI was 21.1.", ClaimDecision.FLAG)

    with pytest.raises(QuoteError, match="unknown record 'report'"):
        quote_flagged(letter(flagged), {}, met={"ahi_threshold"})


def test_quote_without_end_punctuation_gets_a_period() -> None:
    """A record line with no final period still reads as a sentence; the quote inside stays verbatim."""
    notes = {"report": "AHI 21.1 events/hour\nOther line"}
    start = 0
    flagged = Claim(
        criterion_id="ahi_threshold", text="My AHI was 21.1.",
        policy_cite=PolicyCitation(source_id="L33718", quote="clause"),
        evidence_cite=EvidenceCitation(doc_id="report", char_start=start, char_end=20, quote="AHI 21.1 events/hour"),
        score=0.3, decision=ClaimDecision.FLAG,
    )  # fmt: skip

    [quoted] = quote_flagged(letter(flagged), notes, met={"ahi_threshold"}).letter.claims

    assert quoted.text == f'{QUOTE_PREFIX}"AHI 21.1 events/hour".'
