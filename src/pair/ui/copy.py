"""Plain-language UI headings per criterion (``policies/_ui.yaml``) and small copy helpers (Phase 4 T3).

The UI can't show ``criterion.text``: it carries internal tags and is the
drafter's prompt input, so editing it would change claims and void the fitted
threshold (ADR-0020). The UI headings live here instead, checked like the gap
templates: one per criterion, non-empty, no dashes, no internal tags.
"""

import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from pair.contracts import Checklist

logger = logging.getLogger(__name__)

_DASHES = ("—", "–")
_KEEP_CASE = re.compile(r"^(Group\b|[A-Z0-9]{2,}\b)")


class UiCopyError(ValueError):
    """The UI heading file doesn't cover the policies exactly, or is malformed."""


def load_ui_headings(path: Path, checklists: Mapping[str, Checklist]) -> dict[str, str]:
    """Load UI headings keyed ``policy/criterion`` and check them against the checklists.

    Raises:
        UiCopyError: If the file isn't valid YAML, or the headings are missing,
            unknown, empty, use a dash as punctuation, or carry an ADR tag.
    """
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        logger.error("UI copy %s is not valid YAML: %s", path, error)
        raise UiCopyError(f"{path}: not valid YAML: {error}") from error
    headings = data.get("headings") if isinstance(data, dict) else None
    if not isinstance(headings, dict):
        raise UiCopyError(f"{path}: headings must be a mapping")
    expected = {f"{c.id}/{criterion.id}" for c in checklists.values() for criterion in c.criteria}
    missing, unknown = sorted(expected - set(headings)), sorted(set(headings) - expected)
    if missing or unknown:
        raise UiCopyError(f"{path}: missing headings {missing}, unknown keys {unknown}")
    out = {}
    for key, value in headings.items():
        text = str(value or "").strip()
        if not text:
            raise UiCopyError(f"{path}: {key} is empty")
        if any(dash in text for dash in _DASHES):
            raise UiCopyError(f"{path}: {key} uses a dash as punctuation")
        if "ADR" in text:
            raise UiCopyError(f"{path}: {key} carries an internal ADR tag")
        out[key] = text
    return out


def mid_sentence(heading: str) -> str:
    """The heading as it reads after a colon mid-sentence: lowercase first letter, unless a name or acronym."""
    if _KEEP_CASE.match(heading):
        return heading
    return heading[:1].lower() + heading[1:]
