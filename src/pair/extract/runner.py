"""Grounded evidence extraction with LangExtract (step 3, spec §6.2).

The LLM only *finds* facts: each extraction must align to exact characters in
the record. Extractions LangExtract couldn't align (``char_interval=None``) are
dropped and counted, because an ungrounded fact can't be cited. Values are
normalized here, and statuses (asserted / negated / uncertain) come from the
extraction attributes; the rule engine decides what they mean (ADR-0012).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import langextract as lx
from langextract.resolver import ResolverParsingError

from pair.contracts import Checklist, Evidence, EvidenceStatus, VariableType
from pair.extract.examples import examples_for
from pair.extract.normalize import normalize
from pair.extract.tolerant_format import TolerantFormatHandler
from pair.llm import TEMPERATURE, Backend, LLMConfig

logger = logging.getLogger(__name__)

MAX_CHAR_BUFFER: int = 4000
"""Chunk size in characters; synthetic notes fit in one or two chunks, which keeps dates in context."""

ExtractFn = Callable[..., Any]

PROMPT_HEAD: str = """Extract facts from a patient's medical record for a Medicare coverage checklist.
Use exactly these extraction classes (one per fact; the same class may appear more than once):
{variables}
For each extraction:
- extraction_text: copy the shortest exact phrase from the record that states the fact. Never paraphrase.
  It is always quoted text from the record, never true, false or null.
- value: the fact as plain text. Numbers without units ("18.2"), dates as YYYY-MM-DD, true/false for yes/no
  facts. A yes/no fact states its own truth: "no radiculopathy" gives value "false" with status asserted.
  Only use values the record states; never turn words into numbers ("moderate pain" has no pain score,
  so its value is "").
- status: "asserted" if the record clearly states it, "negated" if the record says the item is absent
  ("denies headaches"), "uncertain" if it is hedged ("possible", "may", "?").
Only extract what the record says. If a fact isn't in the record, don't extract it."""


RETRY_NOTE: str = """

Your previous answer could not be parsed ({error}). Every extraction_text must be a phrase copied from the
record as a JSON string; put true/false only in the value attribute."""
MAX_ATTEMPTS: int = 2


@dataclass(frozen=True)
class ExtractionResult:
    """Evidence from one document, plus grounding counts for the eval.

    Attributes:
        evidence: Grounded evidence, one item per (extraction, criterion) pair.
        n_total: Non-empty extractions LangExtract returned (the grounding denominator).
        n_dropped: Non-empty extractions without a character interval, plus items the
            model wrote with a non-text span (both ungrounded).
        n_unknown: Extractions whose class isn't a checklist variable.
        n_empty: Blank placeholders the model emits for facts it didn't find; not
            facts, so they're excluded from grounding.
        n_failed: 1 if the model's output for this document couldn't be parsed
            after a retry (no evidence then), else 0.
    """

    evidence: tuple[Evidence, ...]
    n_total: int
    n_dropped: int
    n_unknown: int
    n_empty: int = 0
    n_failed: int = 0

    @property
    def grounding_rate(self) -> float | None:
        """Share of extractions with a valid character interval, or None if there were none."""
        if self.n_total == 0:
            return None
        return (self.n_total - self.n_dropped) / self.n_total


def build_prompt(checklist: Checklist) -> str:
    """The extraction instructions, naming each variable with its type and criterion."""
    lines = []
    seen: set[str] = set()
    for criterion in checklist.criteria:
        for name, var_type in criterion.variables.items():
            if name in seen:
                continue
            seen.add(name)
            lines.append(f"- {name} ({var_type.value}): for '{criterion.text}'")
    return PROMPT_HEAD.format(variables="\n".join(lines))


def model_kwargs(config: LLMConfig) -> dict[str, Any]:
    """LangExtract model arguments for the configured backend (ADR-0010, ADR-0011)."""
    if config.backend is Backend.GEMINI:
        return {
            "model_id": config.model,
            "temperature": TEMPERATURE,
            "language_model_params": {
                "vertexai": True,
                "project": config.gcp_project,
                "location": config.gcp_location,
                "thinking_config": {"thinking_level": "MINIMAL"},
            },
        }
    return {
        "model_id": config.model,
        "model_url": config.ollama_url,
        "fence_output": False,
        "temperature": TEMPERATURE,
        "language_model_params": {"timeout": int(config.timeout_s), "num_ctx": config.num_ctx, "think": False},
    }


def extract_evidence(
    text: str,
    doc_id: str,
    checklist: Checklist,
    config: LLMConfig,
    extract_fn: ExtractFn = lx.extract,
) -> ExtractionResult:
    """Extract grounded evidence for one checklist from one document.

    Args:
        text: The record text.
        doc_id: Id used in citations.
        checklist: The selected policy checklist.
        config: LLM backend settings.
        extract_fn: ``langextract.extract`` (injectable for tests).

    Returns:
        Evidence items with exact offsets, and grounding counts.
    """
    if not text.strip():
        return ExtractionResult(evidence=(), n_total=0, n_dropped=0, n_unknown=0)
    prompt = build_prompt(checklist)
    handler = TolerantFormatHandler()
    annotated: Any = None
    error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        handler.reset()
        try:
            annotated = extract_fn(
                text_or_documents=text,
                prompt_description=prompt if attempt == 1 else prompt + RETRY_NOTE.format(error=error),
                examples=examples_for(checklist.id),
                max_char_buffer=MAX_CHAR_BUFFER,
                show_progress=False,
                resolver_params={"suppress_parse_errors": False, "format_handler": handler},
                **model_kwargs(config),
            )
            break
        except ResolverParsingError as exc:
            error = str(exc)
            logger.warning("%s/%s: model output not parseable (attempt %d): %s", checklist.id, doc_id, attempt, exc)
    else:
        logger.error("%s/%s: extraction failed after %d attempts: %s", checklist.id, doc_id, MAX_ATTEMPTS, error)
        return ExtractionResult(evidence=(), n_total=0, n_dropped=0, n_unknown=0, n_failed=1)
    targets = _targets(checklist)
    evidence: list[Evidence] = []
    returned = list(annotated.extractions or [])
    extractions = [item for item in returned if item.extraction_text and item.extraction_text.strip()]
    empty = len(returned) - len(extractions) + handler.nulls
    dropped = handler.malformed
    unknown = 0
    for extraction in extractions:
        interval = extraction.char_interval
        if interval is None or interval.start_pos is None or interval.end_pos is None:
            dropped += 1
            continue
        criteria = targets.get(extraction.extraction_class)
        if criteria is None:
            unknown += 1
            continue
        evidence.extend(_evidence(extraction, text, doc_id, criteria, interval.start_pos, interval.end_pos))
    logger.info(
        "%s/%s: %d extractions (+%d empty), %d ungrounded, %d unknown class, %d evidence",
        checklist.id, doc_id, len(extractions), empty, dropped, unknown, len(evidence),
    )  # fmt: skip
    return ExtractionResult(
        evidence=tuple(evidence), n_total=len(extractions) + handler.malformed, n_dropped=dropped, n_unknown=unknown, n_empty=empty
    )


def _targets(checklist: Checklist) -> dict[str, list[tuple[str, VariableType]]]:
    """Map each variable to the criteria (and type) that use it."""
    targets: dict[str, list[tuple[str, VariableType]]] = {}
    for criterion in checklist.criteria:
        for name, var_type in criterion.variables.items():
            targets.setdefault(name, []).append((criterion.id, var_type))
    return targets


def _evidence(
    extraction: Any,
    text: str,
    doc_id: str,
    criteria: list[tuple[str, VariableType]],
    start: int,
    end: int,
) -> list[Evidence]:
    """One Evidence per criterion using this variable; the span is the document slice."""
    attributes = extraction.attributes or {}
    raw = attributes.get("value", extraction.extraction_text)
    status = _status(attributes.get("status"))
    span = text[start:end]
    return [
        Evidence(
            criterion_id=criterion_id,
            variable=extraction.extraction_class,
            value=normalize(var_type, raw),
            span_text=span,
            char_start=start,
            char_end=end,
            doc_id=doc_id,
            status=status,
        )
        for criterion_id, var_type in criteria
    ]


def _status(raw: Any) -> EvidenceStatus:
    """Parse a status attribute: missing means asserted; anything unrecognized is ``uncertain``."""
    if raw is None:
        return EvidenceStatus.ASSERTED
    try:
        return EvidenceStatus(str(raw).strip().lower())
    except ValueError:
        return EvidenceStatus.UNCERTAIN
