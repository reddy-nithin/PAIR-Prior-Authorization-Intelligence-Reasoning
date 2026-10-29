"""Claim wording: the LLM turns one claim slot into one checked sentence (step 5, ADR-0018).

The LLM sees the requirement's plain text and the record quote, never the policy
clause, so a sentence can only restate what the record says. Each reply is
checked in code: one sentence, no number missing from the quote, no conclusion
words ("meets", "qualifies"). A failed check is retried once with the reason. If
both attempts fail, the claim quotes the record verbatim instead, and the
fallback is counted and logged. The entailment verifier (step 6) still scores
every sentence afterwards.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pair.contracts import Checklist, Claim, Letter
from pair.draft.claims import ClaimSlot
from pair.llm import LLMClient, LLMResponseError, LLMUsage

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
MAX_CHARS = 280
SENTENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"sentence": {"type": "string"}},
    "required": ["sentence"],
    "additionalProperties": False,
}

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_CONCLUSION = re.compile(r"\b(meets?|met|qualif\w*|satisf\w*|eligib\w*|approv\w*|requirements?|criteri\w*)\b", re.IGNORECASE)
_ABBREVIATION = re.compile(r"\b(Dr|Mr|Mrs|Ms|vs|e\.g|i\.e)\.", re.IGNORECASE)
_SENTENCE_BREAK = re.compile(r"[.!?]\s+\S")

PROMPT = """You help a Medicare patient write one sentence of an appeal letter, in the first person ("I", "my").

Requirement this sentence is about: {criterion_text}
Record quote, the only facts you may use: "{quote}"

Rules:
- Write exactly one plain sentence at a grade 8 reading level, at most {max_chars} characters.
- State only what the record quote says. Copy every number and date exactly as the quote gives it. Add no other numbers.
- Don't say whether a requirement is met, satisfied or qualifies, and don't mention the policy.
{exemplars}
Reply as JSON: {{"sentence": "..."}}"""

EXEMPLARS = """
Independent reviewers wrote these about similar cases. Use them only for tone. Never copy their facts.
{items}
"""

RETRY = "\n\nYour previous reply was rejected: {error}. Write the sentence again and follow every rule."


class SentenceError(ValueError):
    """A worded sentence breaks a wording rule."""


class DraftError(ValueError):
    """Claim slots don't belong to the checklist being drafted."""


@dataclass(frozen=True)
class WordingResult:
    """Worded claims plus how they were produced.

    Attributes:
        letter: One unverified claim per slot, in slot order.
        attempts: LLM attempts used per claim.
        fallbacks: Claims that fell back to quoting the record verbatim.
        usage: Token usage of every LLM call.
    """

    letter: Letter
    attempts: tuple[int, ...]
    fallbacks: int
    usage: tuple[LLMUsage, ...]


def word_claims(
    slots: Sequence[ClaimSlot], checklist: Checklist, client: LLMClient, exemplars: Sequence[str] = ()
) -> WordingResult:
    """Word each claim slot as one checked sentence.

    Args:
        slots: Claim slots from ``plan_claims``, in letter order.
        checklist: The checklist the slots come from.
        client: The LLM backend (thinking off, JSON schema).
        exemplars: IMR findings used as tone examples only.

    Returns:
        The unverified letter and wording statistics.

    Raises:
        DraftError: If a slot names a criterion the checklist doesn't have.
        LLMError: If the backend fails (not retried; a bad reply is).
    """
    texts = {criterion.id: criterion.text for criterion in checklist.criteria}
    unknown = sorted({slot.criterion_id for slot in slots} - set(texts))
    if unknown:
        raise DraftError(f"slots name criteria not in {checklist.id}: {unknown}")
    examples = EXEMPLARS.format(items="\n".join(f"- {item}" for item in exemplars)) if exemplars else ""

    claims: list[Claim] = []
    attempts: list[int] = []
    usage: list[LLMUsage] = []
    fallbacks = 0
    for slot in slots:
        quote = slot.evidence_cite.quote
        prompt = PROMPT.format(
            criterion_text=texts[slot.criterion_id], quote=quote, max_chars=MAX_CHARS, exemplars=examples
        )
        sentence, used = _word_one(client, prompt, quote, usage)
        if sentence is None:
            fallbacks += 1
            sentence = f'My records state: "{quote}".'
            logger.warning("claim %s: wording fallback to the verbatim quote", slot.criterion_id)
        attempts.append(used)
        claims.append(
            Claim(
                criterion_id=slot.criterion_id,
                text=sentence,
                policy_cite=slot.policy_cite,
                evidence_cite=slot.evidence_cite,
            )
        )
    logger.info("worded %d claims for %s, %d fallbacks", len(claims), checklist.id, fallbacks)
    return WordingResult(Letter(policy_id=checklist.id, claims=claims), tuple(attempts), fallbacks, tuple(usage))


def _word_one(client: LLMClient, prompt: str, quote: str, usage: list[LLMUsage]) -> tuple[str | None, int]:
    """Up to ``MAX_ATTEMPTS`` tries; returns the checked sentence (or None) and attempts used."""
    error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        full_prompt = prompt if attempt == 1 else prompt + RETRY.format(error=error)
        try:
            result = client.generate_json(full_prompt, SENTENCE_SCHEMA)
            usage.append(result.usage)
            return check_sentence(str(result.data.get("sentence", "")), quote), attempt
        except (SentenceError, LLMResponseError) as exc:
            error = str(exc)
            logger.warning("wording attempt %d failed: %s", attempt, error)
    return None, MAX_ATTEMPTS


def check_sentence(sentence: str, quote: str) -> str:
    """Check one worded sentence against its record quote.

    Returns:
        The sentence, stripped.

    Raises:
        SentenceError: If it is empty, too long, more than one sentence, has a
            number the quote doesn't have, or uses a conclusion word.
    """
    text = sentence.strip()
    if not text:
        raise SentenceError("sentence is empty")
    if len(text) > MAX_CHARS:
        raise SentenceError(f"sentence is too long ({len(text)} > {MAX_CHARS} characters)")
    if _SENTENCE_BREAK.search(_ABBREVIATION.sub("", text)):
        raise SentenceError("write one sentence only")
    allowed = {float(number) for number in _NUMBER.findall(quote)}
    extra = [number for number in _NUMBER.findall(text) if float(number) not in allowed]
    if extra:
        raise SentenceError(f"numbers not in the record quote: {', '.join(extra)}")
    conclusion = _CONCLUSION.search(text)
    if conclusion:
        raise SentenceError(
            f"uses a conclusion word ({conclusion.group(0)!r}); say only what the record says"
        )
    return text
