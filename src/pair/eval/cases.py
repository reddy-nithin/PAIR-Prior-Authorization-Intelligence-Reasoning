"""``CaseBundle``: one synthetic evaluation case (spec §5.3).

Eval data, not a pipeline contract: notes + denial letter as the pipeline
sees them, plus gold labels known by construction (planted evidence with exact
offsets, criterion statuses, the gold ``Denial``). Always ``synthetic: true``.
"""

import json
import logging
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, ValidationError, model_validator

from pair.contracts import CriterionStatus, Denial, Evidence
from pair.contracts._base import ContractModel, NonEmptyStr, Slug

logger = logging.getLogger(__name__)


class CaseType(StrEnum):
    """Case types balanced per policy (spec §5.3)."""

    WRONGLY_DENIED = "A"
    FIXABLE_GAP = "B"
    CORRECTLY_DENIED = "C"
    TRICKY = "D"


class PatientProfile(ContractModel):
    """The Synthea facts a case uses: no names, addresses or identifiers."""

    synthea_id: NonEmptyStr
    age: int = Field(ge=0, le=120)
    sex: Literal["F", "M"]
    conditions: list[NonEmptyStr]


class Note(ContractModel):
    """One synthetic clinical document."""

    doc_id: Slug
    title: NonEmptyStr
    text: NonEmptyStr


class CaseBundle(ContractModel):
    """A synthetic case with its gold labels.

    Attributes:
        id: Case id, e.g. ``pap-osa-07``.
        policy_id: The checklist the case is built for.
        case_type: A to D.
        context: Case-level flags for the checklist (e.g. ``initial``).
        profile: Synthea demographics and conditions.
        states: Planted state per planning unit (criterion or criterion group).
        notes: The record documents.
        denial_text: The denial letter.
        gold_denial: What a perfect parser returns for ``denial_text``.
        gold_statuses: Gold status per criterion.
        gold_overall: Gold checklist outcome.
        gold_evidence: Planted evidence with exact offsets into ``notes``.
        synthetic: Always true.
        seed: RNG seed that produced the spec.
        generator: Model, backend and config hash used to write the notes.
        usage_prompt_tokens: Prompt tokens spent writing the notes (all attempts).
        usage_output_tokens: Output + thinking tokens spent writing the notes.
    """

    id: Slug
    policy_id: Slug
    case_type: CaseType
    context: dict[str, bool | None]
    profile: PatientProfile
    states: dict[str, str]
    notes: list[Note] = Field(min_length=1)
    denial_text: NonEmptyStr
    gold_denial: Denial
    gold_statuses: dict[str, CriterionStatus]
    gold_overall: CriterionStatus
    gold_evidence: list[Evidence]
    synthetic: Literal[True]
    seed: int
    generator: dict[str, str]
    usage_prompt_tokens: int = 0
    usage_output_tokens: int = 0

    @model_validator(mode="after")
    def _check_gold_spans(self) -> Self:
        """Every gold span must slice its note exactly."""
        texts = {note.doc_id: note.text for note in self.notes}
        if len(texts) != len(self.notes):
            raise ValueError("note doc_ids must be unique")
        for item in self.gold_evidence:
            text = texts.get(item.doc_id)
            if text is None:
                raise ValueError(f"gold evidence cites unknown note {item.doc_id!r}")
            if text[item.char_start : item.char_end] != item.span_text:
                raise ValueError(f"gold span {item.span_text!r} does not match {item.doc_id} at {item.char_start}")
        return self

    def record_text(self) -> dict[str, str]:
        """The notes as ``{doc_id: text}``."""
        return {note.doc_id: note.text for note in self.notes}


class CaseLoadError(ValueError):
    """A case file is missing or invalid."""


def load_case(path: Path) -> CaseBundle:
    """Load and validate a case bundle JSON file.

    Raises:
        CaseLoadError: If the file is missing or doesn't validate.
    """
    try:
        return CaseBundle.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CaseLoadError(f"no case file at {path}") from exc
    except ValidationError as exc:
        logger.error("case %s is invalid: %s", path, exc)
        raise CaseLoadError(f"{path}: invalid case bundle: {exc}") from exc


def save_case(case: CaseBundle, path: Path) -> Path:
    """Write a case bundle as pretty JSON (creating folders)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(case.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
