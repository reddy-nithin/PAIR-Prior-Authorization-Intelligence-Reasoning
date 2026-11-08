"""Plain-language gap templates: what's missing and who to ask (spec §6.7).

``policies/_gaps.yaml`` holds an ``insufficient`` and an ``unmet`` message for
every criterion, plus ``who``: who holds the missing record, so the UI can group
the gap list by who to ask. The loader checks the file against the loaded checklists and
fails loudly on any missing, extra, empty or malformed entry.
"""

import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pair.contracts import Checklist, CriterionStatus
from pair.rules.engine import GapMessage

logger = logging.getLogger(__name__)

GAP_STATUSES: tuple[CriterionStatus, ...] = (CriterionStatus.INSUFFICIENT, CriterionStatus.UNMET)
WHO_KEY = "who"
_DASHES = ("—", "–")


class GapTemplateError(ValueError):
    """The gap template file doesn't cover the policies exactly, or is malformed."""


@dataclass(frozen=True)
class GapBook:
    """Validated gap messages keyed by policy, criterion and status."""

    messages: Mapping[tuple[str, str, CriterionStatus], str]
    whos: Mapping[tuple[str, str], str]

    def message(self, policy_id: str, criterion_id: str, status: CriterionStatus) -> str:
        """Return the gap text for one non-met criterion.

        Raises:
            ValueError: If ``status`` is met (met criteria have no gap).
            KeyError: If the policy or criterion has no template.
        """
        if status is CriterionStatus.MET:
            raise ValueError(f"criterion {criterion_id} is met and has no gap")
        return self.messages[(policy_id, criterion_id, status)]

    def who(self, policy_id: str, criterion_id: str) -> str:
        """Return who to ask for one criterion's missing record.

        Raises:
            KeyError: If the policy or criterion has no template.
        """
        return self.whos[(policy_id, criterion_id)]

    def for_policy(self, policy_id: str) -> GapMessage:
        """Return the engine's gap callback for one policy."""

        def gap_message(criterion_id: str, status: CriterionStatus) -> str:
            return self.message(policy_id, criterion_id, status)

        return gap_message

    def all_messages(self) -> Iterator[str]:
        """Yield every message, for text checks."""
        yield from self.messages.values()
        yield from self.whos.values()


def load_gaps(path: Path, checklists: Mapping[str, Checklist]) -> GapBook:
    """Load and validate the gap templates for the given checklists.

    Args:
        path: Path to ``_gaps.yaml``.
        checklists: Loaded checklists keyed by policy id.

    Returns:
        The validated gap book.

    Raises:
        GapTemplateError: If the file isn't valid YAML, or doesn't hold exactly
            one non-empty insufficient and unmet message per criterion.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        logger.error("gap templates %s are not valid YAML: %s", path, error)
        raise GapTemplateError(f"{path}: not valid YAML: {error}") from error
    try:
        messages, whos = _collect(data, checklists)
    except GapTemplateError as error:
        logger.error("invalid gap templates %s: %s", path, error)
        raise GapTemplateError(f"{path}: {error}") from error
    return GapBook(messages=messages, whos=whos)


def _collect(
    data: Any, checklists: Mapping[str, Checklist]
) -> tuple[dict[tuple[str, str, CriterionStatus], str], dict[tuple[str, str], str]]:
    """Check the parsed file against the checklists and flatten it into messages and whos."""
    policies = _mapping(data, "top level")
    extra_policies = sorted(set(policies) - set(checklists))
    if extra_policies:
        raise GapTemplateError(f"templates for unknown policies: {extra_policies}")
    messages: dict[tuple[str, str, CriterionStatus], str] = {}
    whos: dict[tuple[str, str], str] = {}
    for policy_id, checklist in checklists.items():
        criteria = _mapping(policies.get(policy_id, {}), policy_id)
        expected = set(checklist.criterion_ids)
        missing, extra = sorted(expected - set(criteria)), sorted(set(criteria) - expected)
        if missing or extra:
            raise GapTemplateError(f"{policy_id}: missing templates {missing}, unknown criteria {extra}")
        for criterion_id in checklist.criterion_ids:
            entry = _mapping(criteria[criterion_id], f"{policy_id}.{criterion_id}")
            where = f"{policy_id}.{criterion_id}"
            for status in GAP_STATUSES:
                messages[(policy_id, criterion_id, status)] = _text(entry, status.value, where)
            whos[(policy_id, criterion_id)] = _text(entry, WHO_KEY, where)
            unknown = sorted(set(entry) - {s.value for s in GAP_STATUSES} - {WHO_KEY})
            if unknown:
                raise GapTemplateError(f"{policy_id}.{criterion_id}: unknown keys {unknown}")
    return messages, whos


def _mapping(value: Any, where: str) -> dict[str, Any]:
    """Require a YAML mapping."""
    if not isinstance(value, dict):
        raise GapTemplateError(f"{where} must be a mapping, got {type(value).__name__}")
    return value


def _text(entry: dict[str, Any], key: str, where: str) -> str:
    """Require a non-empty, dash-free value for ``key`` (a status message or ``who``)."""
    if key not in entry:
        raise GapTemplateError(f"{where}: no {key}" + ("" if key == WHO_KEY else " message"))
    text = str(entry[key]).strip()
    if not text:
        raise GapTemplateError(f"{where}: {key}" + ("" if key == WHO_KEY else " message") + " is empty")
    if any(dash in text for dash in _DASHES):
        raise GapTemplateError(f"{where}: {key} uses a dash as punctuation")
    return text
