"""The fixed letter skeleton and how verified claims are placed into it (step 5, ADR-0018).

Only claim sentences come from the LLM. Everything else, including each
criterion's "this requirement is met" conclusion, is fixed text from
``policies/_letter.yaml``. What the patient sees follows the verifier
(ADR-0020): KEPT claims are in the letter; FLAGGED claims are removed and listed
separately; DROPPED claims are removed; claims with no decision (no fitted
threshold for the running drafter and verifier) are shown and listed as "not
evaluated". A conclusion is written only when every claim of its criterion is KEPT.
"""

import logging
import string
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import Field, ValidationError

from pair.contracts import Checklist, Claim, ClaimDecision, Denial, Letter, PlanType
from pair.contracts._base import ContractModel

logger = logging.getLogger(__name__)

_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "header": frozenset(),
    "subject": frozenset({"service", "codes", "denial_date"}),
    "opening": frozenset({"service", "denial_date", "reason_text"}),
    "ma_argument": frozenset({"policy_sources"}),
    "policy_intro": frozenset(),
    "criterion_heading": frozenset({"criterion_text"}),
    "policy_quote": frozenset({"clause", "source"}),
    "record_cite": frozenset({"doc_id", "quote"}),
    "record_ref": frozenset({"doc_id"}),
    "conclusion": frozenset(),
    "closing": frozenset({"service"}),
    "notice": frozenset(),
}


class LetterTemplateError(ValueError):
    """The letter template is malformed, or a letter doesn't fit its checklist."""


class LetterTemplate(ContractModel):
    """Every fixed section of the appeal letter, with ``{placeholder}`` fields."""

    header: str
    subject: str
    opening: str
    ma_argument: str
    policy_intro: str
    criterion_heading: str
    policy_quote: str
    record_cite: str
    record_ref: str
    conclusion: str
    closing: str
    notice: str
    headings: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class RenderedLetter:
    """The letter text plus the claims kept out of it or shown without a verifier check.

    Attributes:
        text: The letter the patient can send.
        unconfirmed: FLAGGED claims, removed from the text and listed for review.
        not_evaluated: Claims in the text with no verifier decision.
        dropped: Claims removed because a citation failed its check.
        unargued: Criteria whose claims were all removed, so they have no paragraph.
    """

    text: str
    unconfirmed: tuple[Claim, ...]
    not_evaluated: tuple[Claim, ...]
    dropped: tuple[Claim, ...]
    unargued: tuple[str, ...]


def load_letter_template(path: Path) -> LetterTemplate:
    """Load the letter skeleton and check every placeholder name.

    Raises:
        LetterTemplateError: If a section is missing or unknown, or a section uses
            a placeholder it isn't given.
    """
    try:
        template = LetterTemplate.model_validate(yaml.safe_load(path.read_text()))
    except (ValidationError, yaml.YAMLError) as error:
        logger.error("invalid letter template %s: %s", path, error)
        raise LetterTemplateError(f"{path}: {error}") from error
    for section, allowed in _PLACEHOLDERS.items():
        used = {field for _, field, _, _ in string.Formatter().parse(getattr(template, section)) if field}
        unknown = sorted(used - allowed)
        if unknown:
            raise LetterTemplateError(f"{path}: section {section} uses unknown placeholders {unknown}")
    return template


def render_letter(letter: Letter, checklist: Checklist, denial: Denial, template: LetterTemplate) -> RenderedLetter:
    """Place verified claims into the skeleton, one paragraph per argued criterion.

    Args:
        letter: Worded claims, with verifier decisions where available.
        checklist: The checklist the claims argue.
        denial: The parsed denial being appealed.
        template: The fixed letter text.

    Returns:
        The letter text and the lists of claims kept out of it or not evaluated.

    Raises:
        LetterTemplateError: If the letter is for another policy or a claim names
            a criterion the checklist doesn't have.
    """
    if letter.policy_id != checklist.id:
        raise LetterTemplateError(f"letter is for policy {letter.policy_id}, not {checklist.id}")
    criteria = {criterion.id: criterion for criterion in checklist.criteria}
    unknown = sorted({claim.criterion_id for claim in letter.claims} - set(criteria))
    if unknown:
        raise LetterTemplateError(f"claims name criteria not in {checklist.id}: {unknown}")

    sources = {source.id: f"{source.type} {source.id}" for source in checklist.sources}
    paragraphs: list[str] = []
    unconfirmed: list[Claim] = []
    not_evaluated: list[Claim] = []
    dropped: list[Claim] = []
    unargued: list[str] = []
    for criterion in checklist.criteria:
        claims = sorted(
            (claim for claim in letter.claims if claim.criterion_id == criterion.id),
            key=lambda claim: (claim.evidence_cite.doc_id, claim.evidence_cite.char_start),
        )
        if not claims:
            continue
        shown = [claim for claim in claims if claim.decision in (ClaimDecision.KEEP, None)]
        unconfirmed += [claim for claim in claims if claim.decision is ClaimDecision.FLAG]
        dropped += [claim for claim in claims if claim.decision is ClaimDecision.DROP]
        not_evaluated += [claim for claim in shown if claim.decision is None]
        if not shown:
            unargued.append(criterion.id)
            continue
        body = [template.policy_quote.format(clause=criterion.clause, source=sources[criterion.source_id])]
        body += [f"{claim.text} {_cite(template, claim)}" for claim in shown]
        if all(claim.decision is ClaimDecision.KEEP for claim in claims):
            body.append(template.conclusion)
        heading = template.headings.get(f"{checklist.id}/{criterion.id}", criterion.text)
        paragraphs.append(f"{template.criterion_heading.format(criterion_text=heading)}\n{' '.join(body)}")

    text = "\n\n".join(_frame(template, denial, checklist, sources, paragraphs))
    logger.info(
        "letter %s: %d paragraphs, %d unconfirmed, %d not evaluated, %d dropped",
        checklist.id, len(paragraphs), len(unconfirmed), len(not_evaluated), len(dropped),
    )
    return RenderedLetter(text, tuple(unconfirmed), tuple(not_evaluated), tuple(dropped), tuple(unargued))


def _cite(template: LetterTemplate, claim: Claim) -> str:
    """The record citation, without repeating a quote the sentence already contains."""
    cite = claim.evidence_cite
    if cite.quote in claim.text:
        return template.record_ref.format(doc_id=cite.doc_id)
    return template.record_cite.format(doc_id=cite.doc_id, quote=cite.quote)


def _frame(
    template: LetterTemplate, denial: Denial, checklist: Checklist, sources: dict[str, str], paragraphs: list[str]
) -> list[str]:
    """The letter's sections in order, around the criterion paragraphs."""
    date = denial.date.isoformat()
    codes = f" ({', '.join(denial.codes)})" if denial.codes else ""
    sections = [
        template.header,
        template.subject.format(service=denial.service, codes=codes, denial_date=date),
        template.opening.format(service=denial.service, denial_date=date, reason_text=denial.reason_text),
    ]
    if denial.plan_type is PlanType.MEDICARE_ADVANTAGE:
        sections.append(template.ma_argument.format(policy_sources=" and ".join(sources.values())))
    else:
        logger.warning("plan type %s is not Medicare Advantage; CMS-4201-F argument left out", denial.plan_type.value)
    if paragraphs:
        sections.append(template.policy_intro)
    return [*sections, *paragraphs, template.closing.format(service=denial.service), template.notice]
