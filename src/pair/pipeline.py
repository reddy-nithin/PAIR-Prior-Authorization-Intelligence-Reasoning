"""The core pipeline, steps 1 to 4: parse the denial, select the checklist, extract evidence, run rules.

The LLM reads (steps 1 and 3). Policy selection and the verdict are deterministic.
"""

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import langextract as lx

from pair.contracts import Checklist, Evidence, Verdict
from pair.extract.runner import ExtractFn, ExtractionResult, extract_evidence
from pair.ingest.denial import DenialParseError, ParsedDenial, parse_denial
from pair.llm import LLMClient, LLMConfig
from pair.policies.loader import load_all
from pair.policies.select import Selection, load_service_codes, select_policy
from pair.rules.engine import run_rules
from pair.rules.gaps import GapBook, load_gaps

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resources:
    """Everything loaded from ``policies/``."""

    checklists: Mapping[str, Checklist]
    code_table: Mapping[str, str]
    gaps: GapBook


def load_resources(policies_dir: Path) -> Resources:
    """Load checklists, the service-code table and gap templates (each validated loudly)."""
    checklists = load_all(policies_dir)
    return Resources(
        checklists=checklists,
        code_table=load_service_codes(policies_dir / "_service-codes.yaml", checklists),
        gaps=load_gaps(policies_dir / "_gaps.yaml", checklists),
    )


@dataclass(frozen=True)
class CoreRun:
    """The result of steps 1 to 4 for one case.

    Attributes:
        denial: The parsed denial, or None if parsing failed.
        denial_error: Why parsing failed, if it did.
        selection: The policy selection from the parsed denial.
        extractions: Extraction result per document id (empty if no checklist applied).
        verdict: The verdict, or None when no checklist applies.
        seconds: Wall-clock time for the run.
    """

    denial: ParsedDenial | None
    denial_error: str | None
    selection: Selection
    extractions: Mapping[str, ExtractionResult]
    verdict: Verdict | None
    seconds: float

    @property
    def evidence(self) -> list[Evidence]:
        """All grounded evidence across documents."""
        return [item for result in self.extractions.values() for item in result.evidence]

    @property
    def failed_docs(self) -> int:
        """Documents whose extraction output couldn't be parsed."""
        return sum(r.n_failed for r in self.extractions.values())

    @property
    def grounding(self) -> tuple[int, int, int]:
        """(non-empty extractions, ungrounded, empty placeholders) across documents."""
        results = self.extractions.values()
        return (sum(r.n_total for r in results), sum(r.n_dropped for r in results), sum(r.n_empty for r in results))


def run_core(
    denial_text: str,
    notes: Mapping[str, str],
    resources: Resources,
    client: LLMClient,
    config: LLMConfig,
    context: Mapping[str, bool | None] | None = None,
    extract_fn: ExtractFn = lx.extract,
    policy_override: str | None = None,
) -> CoreRun:
    """Run steps 1 to 4.

    Args:
        denial_text: The denial letter text.
        notes: Record documents as ``{doc_id: text}``.
        resources: Loaded policy resources.
        client: LLM client for the denial parser.
        config: LLM settings for extraction.
        context: Case flags for the checklist (missing flags are Unknown).
        extract_fn: ``langextract.extract`` (injectable for tests).
        policy_override: Evaluate this checklist regardless of selection (eval only,
            so extraction is scored even when parsing or selection fails).

    Returns:
        The run; ``verdict`` is None when no checklist applies.

    Raises:
        KeyError: If ``policy_override`` names an unknown policy.
        LLMError: If an LLM can't be reached.
    """
    started = time.perf_counter()
    if policy_override is not None and policy_override not in resources.checklists:
        raise KeyError(f"unknown policy {policy_override!r}")
    parsed: ParsedDenial | None = None
    error: str | None = None
    try:
        parsed = parse_denial(denial_text, client)
    except DenialParseError as exc:
        error = str(exc)
        logger.warning("denial parse failed: %s", exc)
    if parsed is not None:
        selection = select_policy(
            parsed.denial.policy_ref, parsed.denial.codes, resources.checklists, resources.code_table
        )
    else:
        selection = Selection(None, f"unsupported: the denial letter could not be read ({error})")
    policy_id = policy_override or selection.policy_id
    if policy_id is None:
        return CoreRun(parsed, error, selection, {}, None, time.perf_counter() - started)
    checklist = resources.checklists[policy_id]
    extractions = {
        doc_id: extract_evidence(text, doc_id, checklist, config, extract_fn=extract_fn)
        for doc_id, text in notes.items()
    }
    evidence = [item for result in extractions.values() for item in result.evidence]
    verdict = run_rules(checklist, evidence, dict(context or {}), resources.gaps.for_policy(policy_id))
    return CoreRun(parsed, error, selection, extractions, verdict, time.perf_counter() - started)
