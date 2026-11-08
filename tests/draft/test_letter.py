"""Tests for claim wording: the LLM words one slot at a time and is checked (ADR-0018)."""

import logging
from pathlib import Path

import pytest

from pair.contracts import Checklist, EvidenceCitation, PolicyCitation
from pair.draft.claims import ClaimSlot
from pair.draft.letter import (
    SENTENCE_SCHEMA,
    SentenceError,
    check_sentence,
    word_claims,
)
from pair.llm import LLMError, LLMResponseError
from pair.policies.loader import load_all
from tests.fakes import FakeLLM

QUOTE = "Home sleep test on 2026-03-10: AHI 18.2 events/hr"


@pytest.fixture(scope="module")
def pap(repo_root: Path) -> Checklist:
    """The shipped PAP checklist."""
    return load_all(repo_root / "policies")["pap-osa"]


def slot(pap: Checklist, criterion_id: str = "ahi_threshold", quote: str = QUOTE) -> ClaimSlot:
    """A slot citing ``quote`` and its criterion's clause."""
    criterion = next(c for c in pap.criteria if c.id == criterion_id)
    return ClaimSlot(
        criterion_id=criterion_id,
        variables=("ahi",),
        policy_cite=PolicyCitation(source_id=criterion.source_id, quote=criterion.clause),
        evidence_cite=EvidenceCitation(doc_id="note-1", char_start=40, char_end=40 + len(quote), quote=quote),
    )


GOOD = {"sentence": "My home sleep test on 2026-03-10 showed an AHI of 18.2 events per hour."}


def test_claims_keep_their_citations_and_have_no_decision(pap: Checklist) -> None:
    """Wording fills ``text`` only; citations come from the slot; the verifier decides later."""
    result = word_claims([slot(pap)], pap, FakeLLM([GOOD]))

    (claim,) = result.letter.claims
    assert claim.text == GOOD["sentence"]
    assert claim.evidence_cite == slot(pap).evidence_cite
    assert claim.policy_cite == slot(pap).policy_cite
    assert claim.score is None and claim.decision is None
    assert result.letter.policy_id == "pap-osa"
    assert result.attempts == (1,) and result.fallbacks == 0


def test_prompt_has_quote_criterion_and_exemplars_but_not_the_clause(pap: Checklist) -> None:
    """A claim may assert only its record quote, so the policy clause isn't in the prompt."""
    fake = FakeLLM([GOOD])
    word_claims([slot(pap)], pap, fake, exemplars=("The reviewer found the sleep study met the threshold.",))

    prompt = fake.prompts[0]
    criterion = next(c for c in pap.criteria if c.id == "ahi_threshold")
    assert QUOTE in prompt and criterion.text in prompt
    assert "The reviewer found the sleep study" in prompt
    assert criterion.clause not in prompt
    assert fake.schemas[0] == SENTENCE_SCHEMA


def test_added_number_is_rejected_then_retried(pap: Checklist) -> None:
    """A number that isn't in the quote fails the check; the retry prompt says why."""
    fake = FakeLLM([{"sentence": "My AHI was 18.2, well above 15."}, GOOD])
    result = word_claims([slot(pap)], pap, fake)

    assert result.letter.claims[0].text == GOOD["sentence"]
    assert result.attempts == (2,)
    assert "15" in fake.prompts[1] and "not in the record quote" in fake.prompts[1]


def test_two_failed_attempts_fall_back_to_the_quote(pap: Checklist, caplog: pytest.LogCaptureFixture) -> None:
    """After two bad replies the claim quotes the record verbatim, and this is counted and logged."""
    fake = FakeLLM([{"sentence": "This meets the requirement."}, "not json"])
    with caplog.at_level(logging.WARNING):
        result = word_claims([slot(pap)], pap, fake)

    assert result.letter.claims[0].text == f'My records state: "{QUOTE}".'
    assert result.fallbacks == 1 and result.attempts == (2,)
    assert "fallback" in caplog.text


def test_transport_error_is_not_retried(pap: Checklist) -> None:
    """A backend failure (not a bad reply) propagates instead of burning the retry."""
    with pytest.raises(LLMError):
        word_claims([slot(pap)], pap, FakeLLM([LLMError("tunnel down")]))


def test_bad_json_reply_counts_as_a_failed_attempt(pap: Checklist) -> None:
    """A malformed reply is retried like a failed check."""
    fake = FakeLLM([LLMResponseError("reply is not JSON"), GOOD])
    assert word_claims([slot(pap)], pap, fake).attempts == (2,)


def test_slots_from_another_policy_are_rejected(pap: Checklist) -> None:
    """Slots must name criteria of the checklist being drafted."""
    bad = ClaimSlot("made_up", ("x",), slot(pap).policy_cite, slot(pap).evidence_cite)

    with pytest.raises(ValueError, match="made_up"):
        word_claims([bad], pap, FakeLLM([GOOD]))


@pytest.mark.parametrize(
    "sentence",
    [
        "My home sleep test on 2026-03-10 showed an AHI of 18.2.",
        "On March 10, 2026, my home sleep test showed an AHI of 18.2 events per hour.",
    ],
)
def test_check_sentence_accepts_faithful_wording(sentence: str) -> None:
    """Same numbers (dates may be reformatted) and no conclusion words."""
    assert check_sentence(sentence, QUOTE) == sentence


@pytest.mark.parametrize(
    ("sentence", "reason"),
    [
        ("", "empty"),
        ("My AHI was 18.2 and my oxygen was 88.", "88"),
        ("My test on 2026-03-10 qualifies me for CPAP.", "conclusion"),
        ("My AHI of 18.2 meets the policy.", "conclusion"),
        ("My test was on 2026-03-10. It showed an AHI of 18.2.", "one sentence"),
        ("My test showed AHI 18.2. " + "word " * 80, "long"),
    ],
)
def test_check_sentence_rejects(sentence: str, reason: str) -> None:
    """Empty, new numbers, conclusion words, several sentences, or too long."""
    with pytest.raises(SentenceError, match=reason):
        check_sentence(sentence, QUOTE)
