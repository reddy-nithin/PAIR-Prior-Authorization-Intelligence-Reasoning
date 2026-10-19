"""Assemble synthetic cases: plan → notes → planted-span check → gold labels → denial letter."""

import logging
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pair.contracts import Checklist
from pair.eval.cases import CaseBundle, CaseType, PatientProfile, save_case
from pair.eval.synth.denials import render_denial
from pair.eval.synth.notes import NoteGenerationError, write_notes
from pair.eval.synth.planners import PlanError, plan_case, planted_evidence
from pair.llm import LLMClient
from pair.rules.engine import run_rules

logger = logging.getLogger(__name__)

TYPE_MIX: tuple[CaseType, ...] = (
    CaseType.WRONGLY_DENIED,
    CaseType.WRONGLY_DENIED,
    CaseType.WRONGLY_DENIED,
    CaseType.FIXABLE_GAP,
    CaseType.FIXABLE_GAP,
    CaseType.FIXABLE_GAP,
    CaseType.CORRECTLY_DENIED,
    CaseType.CORRECTLY_DENIED,
    CaseType.TRICKY,
    CaseType.TRICKY,
)
"""Ten cases per policy, A to D balanced 3/3/2/2."""


@dataclass(frozen=True)
class CaseRequest:
    """One case to generate."""

    case_id: str
    policy_id: str
    case_type: CaseType
    seed: int


def suite(policy_ids: list[str], base_seed: int, per_policy: int = len(TYPE_MIX)) -> list[CaseRequest]:
    """The case list: ``per_policy`` cases per policy, types cycled from ``TYPE_MIX``."""
    return [
        CaseRequest(
            case_id=f"{policy_id}-{index + 1:02d}",
            policy_id=policy_id,
            case_type=TYPE_MIX[index % len(TYPE_MIX)],
            seed=base_seed * 1000 + p_index * 100 + index,
        )
        for p_index, policy_id in enumerate(sorted(policy_ids))
        for index in range(per_policy)
    ]


def generate_case(
    request: CaseRequest,
    checklist: Checklist,
    profile: PatientProfile,
    client: LLMClient,
    generator: dict[str, str],
) -> CaseBundle:
    """Generate one case bundle with gold labels by construction.

    Raises:
        PlanError: If the gold labels from the written notes disagree with the plan.
        NoteGenerationError: If the notes never pass the planted-span check.
    """
    rng = random.Random(request.seed)
    spec = plan_case(checklist, request.case_type, rng)
    written = write_notes(spec, profile, checklist.title, client)
    texts = {note.doc_id: note.text for note in written.notes}
    gold_evidence = planted_evidence(spec.plants, texts)
    verdict = run_rules(checklist, gold_evidence, spec.context, lambda _c, _s: "gap")
    statuses = {result.criterion_id: result.status for result in verdict.results}
    if statuses != spec.expected:
        raise PlanError(f"{request.case_id}: gold statuses changed after note writing")
    letter = render_denial(checklist.id, spec.focus_criterion, spec.dates["denial"], rng)
    logger.info(
        "%s: type %s, states %s, overall %s, notes in %d attempt(s)",
        request.case_id, request.case_type.value, spec.states, verdict.overall.value, written.attempts,
    )  # fmt: skip
    return CaseBundle(
        id=request.case_id,
        policy_id=checklist.id,
        case_type=request.case_type,
        context=spec.context,
        profile=profile,
        states=spec.states,
        notes=list(written.notes),
        denial_text=letter.text,
        gold_denial=letter.denial,
        gold_statuses=statuses,
        gold_overall=verdict.overall,
        gold_evidence=gold_evidence,
        synthetic=True,
        seed=request.seed,
        generator={**generator, "note_attempts": str(written.attempts)},
        usage_prompt_tokens=sum(u.prompt_tokens or 0 for u in written.usage),
        usage_output_tokens=sum((u.output_tokens or 0) + (u.thinking_tokens or 0) for u in written.usage),
    )


AUDIT_SHARE: float = 0.2
AUDIT_HEAD: str = """# Hand audit (20% of synthetic cases)

For each case, open `<policy>/<id>.json` and check:
1. Realism: the notes read like real clinic notes and test reports (style, order, abbreviations).
2. Labels: each `gold_statuses` value is what a careful reviewer would conclude from the notes alone.
3. Leaks: nothing in the notes adds a second value or fills in a fact the case says is missing.
4. Denial: the letter's reason and citation match `gold_denial`.

Tick a case when all four pass; write a one-line note when one fails.

"""


@dataclass
class SuiteSummary:
    """What a batch run produced."""

    written: int = 0
    skipped: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    prompt_tokens: int = 0
    output_tokens: int = 0


def generate_suite(
    requests: Sequence[CaseRequest],
    checklists: Mapping[str, Checklist],
    profiles: Sequence[PatientProfile],
    client: LLMClient,
    out_dir: Path,
    generator: dict[str, str],
) -> SuiteSummary:
    """Generate every requested case into ``out_dir/<policy>/<id>.json`` and write ``AUDIT.md``.

    Existing case files are kept (delete them to regenerate). Cases whose notes
    never pass the span check are listed in ``failed`` instead of stopping the run.

    Raises:
        ValueError: If there are no profiles.
    """
    if not profiles:
        raise ValueError("no patient profiles to build cases from")
    summary = SuiteSummary()
    for index, request in enumerate(requests):
        path = out_dir / request.policy_id / f"{request.case_id}.json"
        if path.exists():
            summary.skipped += 1
            continue
        profile = profiles[index % len(profiles)]
        try:
            case = generate_case(request, checklists[request.policy_id], profile, client, generator)
        except (NoteGenerationError, PlanError) as exc:
            logger.error("%s failed: %s", request.case_id, exc)
            summary.failed.append((request.case_id, str(exc)))
            continue
        save_case(case, path)
        summary.written += 1
        summary.prompt_tokens += case.usage_prompt_tokens
        summary.output_tokens += case.usage_output_tokens
    _write_audit(requests, out_dir)
    return summary


def _write_audit(requests: Sequence[CaseRequest], out_dir: Path) -> None:
    """Pick 20% of cases, spread across policies and types, for the hand audit."""
    by_policy: dict[str, list[CaseRequest]] = {}
    for request in requests:
        by_policy.setdefault(request.policy_id, []).append(request)
    lines = [AUDIT_HEAD]
    for policy_id, items in sorted(by_policy.items()):
        count = max(1, round(len(items) * AUDIT_SHARE))
        rng = random.Random(policy_id)
        picked = sorted(rng.sample(items, k=min(count, len(items))), key=lambda r: r.case_id)
        lines.extend(f"- [ ] `{r.case_id}` (type {r.case_type.value}) · notes:" for r in picked)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
