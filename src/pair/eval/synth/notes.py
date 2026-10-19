"""LLM-written synthetic notes with planted phrases, plus the planted-span check.

The LLM writes realistic text around exact phrases. A case is accepted only if
every phrase appears verbatim in its note and no absent unit's values leaked in;
otherwise it is regenerated with the problems fed back (spec §5.3).
"""

import logging
import re
from dataclasses import dataclass

from pair.eval.cases import Note, PatientProfile
from pair.eval.synth.planners import CLINIC, REPORT, CaseSpec, find_phrase
from pair.llm import LLMClient, LLMResponseError, LLMUsage

logger = logging.getLogger(__name__)

MAX_ATTEMPTS: int = 3
HEADER: str = "SYNTHETIC RECORD - not a real patient.\n"

NOTE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {CLINIC: {"type": "string"}, REPORT: {"type": "string"}},
    "required": [CLINIC, REPORT],
}

TITLES: dict[str, dict[str, str]] = {
    "pap-osa": {CLINIC: "Sleep medicine clinic notes", REPORT: "Home sleep test and CPAP device report"},
    "home-oxygen": {CLINIC: "Pulmonology clinic note", REPORT: "Oxygen testing report"},
    "facet-joint": {CLINIC: "Pain clinic note", REPORT: "Imaging and procedure report"},
}

PROMPT: str = """Write two short synthetic medical documents for a fictional Medicare patient.
They are test data for software; nothing is about a real person. Do not use any names.

Patient: {age}-year-old {sex}. Other history: {conditions}.
Topic: {topic}.

Return JSON with two fields:
- "clinic": {clinic_title}, 120 to 220 words.
- "report": {report_title}, 80 to 160 words.

Each document MUST contain these exact phrases, copied character for character (same words, numbers,
dates and punctuation; capitalization may change to fit the sentence). Work them naturally into sentences.
clinic:
{clinic_phrases}
report:
{report_phrases}

Do not state any other value, date or result for the facts in those phrases.
{absent_block}Write in a plain clinical style with common abbreviations. No markdown, no headings with #."""

RETRY: str = """

Your previous answer was rejected:
{problems}
Write both documents again, fixing these problems."""


class NoteGenerationError(RuntimeError):
    """The notes failed the planted-span check after every attempt."""


@dataclass(frozen=True)
class WrittenNotes:
    """Accepted notes and how many attempts they took."""

    notes: tuple[Note, ...]
    attempts: int
    usage: tuple[LLMUsage, ...]


def build_prompt(spec: CaseSpec, profile: PatientProfile, topic: str) -> str:
    """The note-writing prompt for a planned case."""
    titles = TITLES[spec.policy_id]

    def phrases(doc_id: str) -> str:
        items = sorted({plant.phrase for plant in spec.plants if plant.doc_id == doc_id})
        return "\n".join(f'- "{item}"' for item in items) or "- (none)"

    absent = ""
    if spec.absent_topics:
        topics = "; ".join(spec.absent_topics)
        absent = f"Leave these out completely, they must not appear anywhere: {topics}.\n"
    return PROMPT.format(
        age=profile.age,
        sex="woman" if profile.sex == "F" else "man",
        conditions=", ".join(profile.conditions) or "none notable",
        topic=topic,
        clinic_title=titles[CLINIC],
        report_title=titles[REPORT],
        clinic_phrases=phrases(CLINIC),
        report_phrases=phrases(REPORT),
        absent_block=absent,
    )


def check_notes(spec: CaseSpec, texts: dict[str, str]) -> list[str]:
    """Planted-span check: missing phrases and leaked absent-unit values. Empty means OK."""
    problems = [
        f'the {plant.doc_id} document is missing the exact phrase "{plant.phrase}"'
        for plant in spec.plants
        if find_phrase(texts.get(plant.doc_id, ""), plant.phrase) < 0
    ]
    joined = "\n".join(texts.values())
    for pattern in spec.forbidden:
        match = re.search(pattern, joined, flags=re.IGNORECASE)
        if match:
            problems.append(f'"{match.group()}" must not appear (that information is meant to be missing)')
    return list(dict.fromkeys(problems))


def write_notes(spec: CaseSpec, profile: PatientProfile, topic: str, client: LLMClient) -> WrittenNotes:
    """Generate the two notes for a case, retrying until the planted-span check passes.

    Raises:
        NoteGenerationError: If no attempt passes the check.
        LLMError: If the LLM can't be reached.
    """
    prompt = build_prompt(spec, profile, topic)
    usage: list[LLMUsage] = []
    problems: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        full = prompt if attempt == 1 else prompt + RETRY.format(problems="\n".join(f"- {p}" for p in problems))
        try:
            result = client.generate_json(full, NOTE_SCHEMA)
        except LLMResponseError as exc:
            problems = [f"the answer was not valid JSON ({exc})"]
            continue
        usage.append(result.usage)
        texts = {doc_id: HEADER + str(result.data.get(doc_id, "")).strip() for doc_id in (CLINIC, REPORT)}
        problems = check_notes(spec, texts)
        if not problems:
            titles = TITLES[spec.policy_id]
            notes = tuple(Note(doc_id=d, title=titles[d], text=texts[d]) for d in (CLINIC, REPORT))
            return WrittenNotes(notes=notes, attempts=attempt, usage=tuple(usage))
        logger.warning("notes attempt %d rejected: %s", attempt, problems)
    raise NoteGenerationError(f"notes failed the planted-span check {MAX_ATTEMPTS} times: {problems}")
