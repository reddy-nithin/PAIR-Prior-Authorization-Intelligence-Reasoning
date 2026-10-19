"""Denial parser: letter text → validated ``Denial`` (step 1, spec §5.3).

The LLM only *reads* the letter into the ``Denial`` schema. Pydantic decides
whether the reply is valid. One retry feeds the validation error back; a second
failure raises, so a bad parse never flows silently into policy selection.
"""

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from pair.contracts import Denial, PlanType, ReasonCategory
from pair.llm import LLMClient, LLMResponseError, LLMUsage

logger = logging.getLogger(__name__)

MAX_ATTEMPTS: int = 2

DENIAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "service": {"type": "string", "description": "The denied item or service, in the letter's words"},
        "codes": {"type": "array", "items": {"type": "string"}, "description": "HCPCS or CPT codes in the letter"},
        "reason_text": {"type": "string", "description": "The denial reason, quoted from the letter"},
        "reason_category": {"type": "string", "enum": [c.value for c in ReasonCategory]},
        "policy_ref": {
            "type": ["string", "null"],
            "description": "The NCD or LCD id the letter cites (e.g. L33718 or 240.4), or null",
        },
        "plan_type": {"type": "string", "enum": [p.value for p in PlanType]},
        "date": {"type": "string", "description": "The letter's date as YYYY-MM-DD"},
    },
    "required": ["service", "codes", "reason_text", "reason_category", "policy_ref", "plan_type", "date"],
}
"""Hand-written, flat JSON schema for the ``Denial`` contract (no ``$ref``, which some backends reject)."""

PROMPT: str = """You read a health plan's prior authorization denial letter and copy facts from it into JSON.
Rules:
- Copy, don't infer. Use the letter's own words for service and reason_text.
- codes: every HCPCS/CPT code printed in the letter (e.g. E0601, 64490); [] if none.
- policy_ref: the NCD or LCD number the letter cites, or null if it cites none.
- reason_category: criteria_not_met (a coverage rule isn't met), insufficient_documentation
  (records are missing or don't show something), not_medically_necessary, not_covered_benefit,
  administrative (paperwork, timing, network), or other.
- plan_type: medicare_advantage if the letter is from a Medicare Advantage plan, else other.
- date: the date printed on the letter, as YYYY-MM-DD.

Letter:
<<<
{letter}
>>>"""

RETRY: str = """

Your previous answer was rejected:
{error}
Answer again with corrected JSON only."""


class DenialParseError(ValueError):
    """The letter couldn't be parsed into a valid ``Denial``."""


@dataclass(frozen=True)
class ParsedDenial:
    """A parsed denial and how it was obtained."""

    denial: Denial
    attempts: int
    usage: tuple[LLMUsage, ...]


def parse_denial(letter: str, client: LLMClient) -> ParsedDenial:
    """Parse denial-letter text with the LLM and validate it.

    Args:
        letter: The letter's text (from ``read_document``).
        client: Any LLM client.

    Returns:
        The validated denial, the number of attempts and the token usage.

    Raises:
        DenialParseError: If the letter is empty or both attempts fail validation.
        LLMError: If the LLM can't be reached (not retried).
    """
    if not letter.strip():
        raise DenialParseError("denial letter is empty")
    prompt = PROMPT.format(letter=letter)
    usage: list[LLMUsage] = []
    error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        full_prompt = prompt if attempt == 1 else prompt + RETRY.format(error=error)
        try:
            result = client.generate_json(full_prompt, DENIAL_SCHEMA)
            usage.append(result.usage)
            denial = Denial.model_validate(_clean(result.data))
        except (ValidationError, LLMResponseError) as exc:
            error = str(exc)
            logger.warning("denial parse attempt %d failed: %s", attempt, error)
            continue
        return ParsedDenial(denial=denial, attempts=attempt, usage=tuple(usage))
    logger.error("denial parse failed after %d attempts", MAX_ATTEMPTS)
    raise DenialParseError(f"denial parse failed after {MAX_ATTEMPTS} attempts: {error}")


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Tidy harmless LLM formatting before validation (returns a new dict)."""
    cleaned = dict(data)
    codes = cleaned.get("codes")
    if isinstance(codes, list):
        tidy = [code.strip().upper() for code in codes if isinstance(code, str) and code.strip()]
        cleaned["codes"] = list(dict.fromkeys(tidy))
    ref = cleaned.get("policy_ref")
    if isinstance(ref, str) and not ref.strip():
        cleaned["policy_ref"] = None
    return cleaned
