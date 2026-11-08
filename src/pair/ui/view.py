"""``CaseView``: everything the demo screens show for one case, as one JSON-ready model (ADR-0023).

Live runs and cached runs both become a ``CaseView``; the Next.js app reads
nothing else. The view adds no decisions: statuses, gaps, claim decisions and
the strength come from the pipeline. It adds only display text (status labels,
plain-language denial reasons, who to ask) and offsets that let the UI make each
letter sentence clickable. When the strength abstains, no number is shown.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from pair.contracts import (
    Checklist,
    Claim,
    ClaimDecision,
    CriterionStatus,
    ReasonCategory,
)
from pair.contracts._base import ContractModel, NonEmptyStr, Probability
from pair.ui.copy import mid_sentence

if TYPE_CHECKING:  # the cached demo reads CaseView with no LLM code loaded (ADR-0023)
    from pair.draft.template import LetterTemplate
    from pair.pipeline import CoreRun, Resources, TrustRun
    from pair.score.strength import ShipLink

logger = logging.getLogger(__name__)

SCHEMA_VERSION: Literal[1] = 1
UNMET_WHO = "Your doctor"
_INTERNAL_TAG = re.compile(r"\s*\([^()]*\bADR-\d{4}[^()]*\)")

Mode = Literal["cached", "live"]


class ViewError(ValueError):
    """The runs can't be shown together (e.g. a letter without a verdict)."""


class Decision(StrEnum):
    """What the verifier decided about a sentence, in display terms."""

    KEPT = "kept"
    FLAGGED = "flagged"
    NOT_EVALUATED = "not_evaluated"
    DROPPED = "dropped"
    QUOTED = "quoted"


class StatusView(ContractModel):
    """A criterion status as icon name + words (color is never the only signal)."""

    status: CriterionStatus
    icon: NonEmptyStr
    label: NonEmptyStr


STATUS_DISPLAY: dict[CriterionStatus, StatusView] = {
    CriterionStatus.MET: StatusView(status=CriterionStatus.MET, icon="check", label="Met"),
    CriterionStatus.UNMET: StatusView(status=CriterionStatus.UNMET, icon="cross", label="Not met"),
    CriterionStatus.INSUFFICIENT: StatusView(
        status=CriterionStatus.INSUFFICIENT, icon="question", label="Not enough information"
    ),
}

REASON_PLAIN: dict[ReasonCategory, str] = {
    ReasonCategory.CRITERIA_NOT_MET: "The plan says your records don't meet the coverage rule for this service.",
    ReasonCategory.INSUFFICIENT_DOCUMENTATION: (
        "The plan says your records are missing something the coverage rule asks for."
    ),
    ReasonCategory.NOT_MEDICALLY_NECESSARY: "The plan says this service isn't medically needed for you.",
    ReasonCategory.NOT_COVERED_BENEFIT: "The plan says your plan doesn't cover this service.",
    ReasonCategory.ADMINISTRATIVE: "The plan says a form or step was missing. This isn't a medical reason.",
    ReasonCategory.OTHER: "The plan gave a reason that doesn't fit the usual groups.",
}

DECISION_LABEL: dict[Decision, str] = {
    Decision.KEPT: "Checked against your records",
    Decision.FLAGGED: "Not confirmed. Check this against your records yourself.",
    Decision.NOT_EVALUATED: "Not checked by PAIR",
    Decision.DROPPED: "Removed because its quote didn't match your records",
    Decision.QUOTED: "Quoted word for word from your records",
}

_DECISIONS: dict[ClaimDecision | None, Decision] = {
    ClaimDecision.KEEP: Decision.KEPT,
    ClaimDecision.FLAG: Decision.FLAGGED,
    ClaimDecision.DROP: Decision.DROPPED,
    ClaimDecision.QUOTE: Decision.QUOTED,
    None: Decision.NOT_EVALUATED,
}


class SourceSpan(ContractModel):
    """Exact characters in one record."""

    doc_id: NonEmptyStr
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    quote: NonEmptyStr


class PolicyRef(ContractModel):
    """One coverage document, e.g. ``LCD L33718``, with its MCD link."""

    label: NonEmptyStr
    title: NonEmptyStr
    url: NonEmptyStr


class PolicyClause(ContractModel):
    """A verbatim clause and the document it is from."""

    source: PolicyRef
    clause: NonEmptyStr


class DenialView(ContractModel):
    """Screen 2: why they said no."""

    service: NonEmptyStr
    codes: list[str]
    date: NonEmptyStr
    reason_text: NonEmptyStr
    reason_plain: NonEmptyStr
    policy_ref: str | None
    cited_rule: PolicyRef | None


class CriterionView(ContractModel):
    """Screen 3: one row of "where you stand"."""

    id: NonEmptyStr
    heading: NonEmptyStr
    status: StatusView
    critical: bool
    quotes: list[SourceSpan]
    policy: PolicyClause
    trace: NonEmptyStr


class GapItem(ContractModel):
    """One thing to ask for."""

    criterion_id: NonEmptyStr
    heading: NonEmptyStr
    status: StatusView
    message: NonEmptyStr


class GapGroup(ContractModel):
    """Screen 4: the gaps one person or office can fix."""

    who: NonEmptyStr
    items: list[GapItem]


class SentenceView(ContractModel):
    """One letter sentence with its sources; offsets into the letter when it is shown there."""

    criterion_id: NonEmptyStr
    text: NonEmptyStr
    decision: Decision
    decision_label: NonEmptyStr
    score: Probability | None
    letter_start: int | None
    letter_end: int | None
    record: SourceSpan
    policy: PolicyClause


class NotArgued(ContractModel):
    """A criterion the letter leaves out, and what would let it be argued."""

    criterion_id: NonEmptyStr
    heading: NonEmptyStr
    status: StatusView
    message: NonEmptyStr


class LetterView(ContractModel):
    """Screen 5: the letter, its clickable sentences, and what was kept out."""

    text: NonEmptyStr
    sentences: list[SentenceView]
    unconfirmed: list[SentenceView]
    dropped: int = Field(ge=0)
    not_argued: list[NotArgued]


class StepView(ContractModel):
    """One criterion's effect on the estimate."""

    criterion_id: NonEmptyStr
    heading: NonEmptyStr
    status: StatusView
    effect: Literal["raises", "lowers", "no change"]


class ImproveView(ContractModel):
    """What helps, with the estimate if fixed (None when abstaining)."""

    criterion_id: NonEmptyStr
    heading: NonEmptyStr
    action: NonEmptyStr
    p_if_fixed: Probability | None


class StrengthView(ContractModel):
    """Screen 6: the range and breakdown, or "get a human" with no numbers."""

    abstain: bool
    reason: str | None
    p: Probability | None
    low: Probability | None
    high: Probability | None
    base_rate: Probability | None
    n_similar: int = Field(ge=0)
    steps: list[StepView]
    improve: list[ImproveView]
    data_note: NonEmptyStr


class LinkView(ContractModel):
    """A place to get free help."""

    name: NonEmptyStr
    url: NonEmptyStr
    note: str


class DocumentView(ContractModel):
    """A record the source panel can show and highlight."""

    doc_id: NonEmptyStr
    title: NonEmptyStr
    text: str


class CaseView(ContractModel):
    """Everything the 7 screens show for one case."""

    schema_version: Literal[1] = SCHEMA_VERSION
    case_id: NonEmptyStr
    mode: Mode
    supported: bool
    unsupported_reason: str | None
    policy_id: str | None
    policy_title: str | None
    denial: DenialView | None
    overall: StatusView | None
    criteria: list[CriterionView]
    gap_groups: list[GapGroup]
    letter: LetterView | None
    strength: StrengthView | None
    documents: list[DocumentView]
    help_links: list[LinkView]
    safety_notice: NonEmptyStr
    run: dict[str, str]


def caseview_schema() -> dict[str, Any]:
    """The JSON Schema the TypeScript types are generated from."""
    return CaseView.model_json_schema()


def build_view(
    case_id: str,
    core: CoreRun,
    trust: TrustRun | None,
    resources: Resources,
    template: LetterTemplate,
    ship_links: Sequence[ShipLink],
    documents: Mapping[str, str],
    titles: Mapping[str, str] | None = None,
    mode: Mode = "cached",
    headings: Mapping[str, str] | None = None,
) -> CaseView:
    """Turn one pipeline run into the view the screens render.

    Args:
        case_id: Id shown in the URL and the cache.
        core: Steps 1 to 4.
        trust: Steps 5 to 7, or None if they weren't run.
        resources: Loaded policies and gap templates.
        template: The letter template (for the safety notice).
        ship_links: Get-a-human links.
        documents: Record texts by doc id.
        titles: Record titles by doc id (defaults to the doc id).
        mode: Whether this view comes from the cache or a live run.
        headings: UI headings keyed ``policy/criterion`` (``policies/_ui.yaml``);
            missing ones fall back to the criterion text without internal tags.

    Raises:
        ViewError: If ``trust`` is given for a core run with no verdict.
    """
    if trust is not None and core.verdict is None:
        raise ViewError("a letter and strength need a verdict from steps 1 to 4")
    checklist = resources.checklists[core.verdict.policy_id] if core.verdict is not None else None
    headings = _headings(checklist, headings or {})
    view = CaseView(
        case_id=case_id,
        mode=mode,
        supported=checklist is not None,
        unsupported_reason=None if checklist is not None else core.selection.reason,
        policy_id=checklist.id if checklist else None,
        policy_title=checklist.title if checklist else None,
        denial=_denial(core, checklist),
        overall=STATUS_DISPLAY[core.verdict.overall] if core.verdict is not None else None,
        criteria=_criteria(core, checklist, headings),
        gap_groups=_gap_groups(core, resources, headings),
        letter=_letter(trust, checklist, headings) if trust is not None and checklist else None,
        strength=_strength(trust, headings) if trust is not None and trust.strength is not None else None,
        documents=[
            DocumentView(doc_id=doc_id, title=(titles or {}).get(doc_id, doc_id), text=text)
            for doc_id, text in documents.items()
        ],
        help_links=[LinkView(name=link.name, url=link.url, note=link.note) for link in ship_links],
        safety_notice=template.notice,
        run={**(trust.verified.metadata if trust else {}), "seconds": f"{core.seconds:.1f}"},
    )
    logger.info("view %s: %d criteria, mode %s", case_id, len(view.criteria), mode)
    return view


def patient_heading(text: str) -> str:
    """Criterion text without internal tags such as ``(NCD 240.2; ADR-0015)``."""
    return _INTERNAL_TAG.sub("", text).strip()


def _headings(checklist: Checklist | None, ui: Mapping[str, str]) -> dict[str, str]:
    """Patient heading per criterion id: the UI heading, else the tag-free criterion text."""
    if checklist is None:
        return {}
    return {c.id: ui.get(f"{checklist.id}/{c.id}", patient_heading(c.text)) for c in checklist.criteria}


def _plain(text: str, headings: Mapping[str, str]) -> str:
    """Replace criterion ids in pipeline text with their patient headings, read mid-sentence."""
    for criterion_id, heading in headings.items():
        replacement = mid_sentence(heading).replace("\\", "\\\\")
        text = re.sub(rf"\b{re.escape(criterion_id)}\b", replacement, text)
    return text


def _sources(checklist: Checklist) -> dict[str, PolicyRef]:
    """PolicyRef per source id."""
    return {
        s.id: PolicyRef(label=f"{s.type} {s.id}", title=s.title, url=s.url) for s in checklist.sources
    }


def _denial(core: CoreRun, checklist: Checklist | None) -> DenialView | None:
    """Screen 2, or None when the denial couldn't be read."""
    if core.denial is None:
        return None
    denial = core.denial.denial
    cited = _sources(checklist).get(denial.policy_ref or "") if checklist else None
    return DenialView(
        service=denial.service,
        codes=list(denial.codes),
        date=denial.date.isoformat(),
        reason_text=denial.reason_text,
        reason_plain=REASON_PLAIN[denial.reason_category],
        policy_ref=denial.policy_ref,
        cited_rule=cited,
    )


def _criteria(core: CoreRun, checklist: Checklist | None, headings: Mapping[str, str]) -> list[CriterionView]:
    """Screen 3 rows in checklist order."""
    if core.verdict is None or checklist is None:
        return []
    sources = _sources(checklist)
    results = {r.criterion_id: r for r in core.verdict.results}
    rows = []
    for criterion in checklist.criteria:
        result = results[criterion.id]
        spans = {(e.doc_id, e.char_start, e.char_end): e.span_text for e in result.evidence}
        rows.append(
            CriterionView(
                id=criterion.id,
                heading=headings[criterion.id],
                status=STATUS_DISPLAY[result.status],
                critical=criterion.critical,
                quotes=[SourceSpan(doc_id=d, char_start=s, char_end=e, quote=q) for (d, s, e), q in sorted(spans.items())],
                policy=PolicyClause(source=sources[criterion.source_id], clause=criterion.clause),
                trace=result.trace,
            )
        )
    return rows


def _gap_groups(core: CoreRun, resources: Resources, headings: Mapping[str, str]) -> list[GapGroup]:
    """Screen 4: gaps grouped by who to ask, in first-seen order."""
    if core.verdict is None:
        return []
    status = {r.criterion_id: r.status for r in core.verdict.results}
    groups: dict[str, list[GapItem]] = {}
    for gap in core.verdict.gaps:
        state = status[gap.criterion_id]
        who = UNMET_WHO if state is CriterionStatus.UNMET else resources.gaps.who(core.verdict.policy_id, gap.criterion_id)
        groups.setdefault(who, []).append(
            GapItem(criterion_id=gap.criterion_id, heading=headings[gap.criterion_id],
                    status=STATUS_DISPLAY[state], message=gap.message)
        )  # fmt: skip
    return [GapGroup(who=who, items=items) for who, items in groups.items()]


def _sentence(claim: Claim, sources: Mapping[str, PolicyRef], clauses: Mapping[str, str],
              span: tuple[int, int] | None) -> SentenceView:  # fmt: skip
    """One claim as a display sentence."""
    decision = _DECISIONS[claim.decision]
    cite = claim.evidence_cite
    source_id = claim.policy_cite.source_id
    return SentenceView(
        criterion_id=claim.criterion_id,
        text=claim.text,
        decision=decision,
        decision_label=DECISION_LABEL[decision],
        score=claim.score,
        letter_start=span[0] if span else None,
        letter_end=span[1] if span else None,
        record=SourceSpan(doc_id=cite.doc_id, char_start=cite.char_start, char_end=cite.char_end, quote=cite.quote),
        policy=PolicyClause(source=sources[source_id], clause=clauses[claim.criterion_id]),
    )


def _letter(trust: TrustRun, checklist: Checklist, headings: Mapping[str, str]) -> LetterView:
    """Screen 5: shown sentences located in the letter text, in letter order."""
    text = trust.rendered.text
    sources = _sources(checklist)
    clauses = {c.id: c.clause for c in checklist.criteria}
    order = {cid: i for i, cid in enumerate(checklist.criterion_ids)}
    shown = sorted(
        (c for c in trust.quoted.letter.claims if c.decision in (ClaimDecision.KEEP, ClaimDecision.QUOTE, None)),
        key=lambda c: (order[c.criterion_id], c.evidence_cite.doc_id, c.evidence_cite.char_start),
    )
    sentences = []
    cursor = 0
    for claim in shown:
        start = text.find(claim.text, cursor)
        if start < 0:
            raise ViewError(f"claim for {claim.criterion_id} not found in the rendered letter")
        cursor = start + len(claim.text)
        sentences.append(_sentence(claim, sources, clauses, (start, cursor)))
    status = {s.criterion_id: s.status for s in trust.plan.skipped}
    return LetterView(
        text=text,
        sentences=sentences,
        unconfirmed=[_sentence(c, sources, clauses, None) for c in trust.rendered.unconfirmed],
        dropped=len(trust.rendered.dropped),
        not_argued=[
            NotArgued(criterion_id=s.criterion_id, heading=headings[s.criterion_id],
                      status=STATUS_DISPLAY[status[s.criterion_id]], message=s.message)
            for s in trust.plan.skipped
        ],
    )  # fmt: skip


def _strength(trust: TrustRun, headings: Mapping[str, str]) -> StrengthView:
    """Screen 6; every number is hidden when the strength abstains."""
    from pair.score.strength import IMR_NOTE

    strength = trust.strength
    assert strength is not None
    hide = strength.abstain
    explanation = strength.explanation
    return StrengthView(
        abstain=hide,
        reason=_plain(strength.abstain_reason, headings) if strength.abstain_reason else None,
        p=None if hide else strength.p,
        low=None if hide else strength.interval.low,
        high=None if hide else strength.interval.high,
        base_rate=None if hide else explanation.base_rate,
        n_similar=explanation.n_similar,
        steps=[
            StepView(criterion_id=s.criterion_id, heading=headings[s.criterion_id], status=STATUS_DISPLAY[s.status],
                     effect="raises" if s.shift > 1 else "lowers" if s.shift < 1 else "no change")
            for s in explanation.steps
        ],
        improve=[
            ImproveView(criterion_id=i.criterion_id, heading=headings[i.criterion_id],
                        action=_plain(i.action, headings), p_if_fixed=None if hide else i.p_if_fixed)
            for i in explanation.improve
        ],
        data_note=IMR_NOTE,
    )  # fmt: skip
