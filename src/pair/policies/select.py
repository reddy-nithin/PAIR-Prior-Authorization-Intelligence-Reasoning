"""Deterministic policy selection: which checklist applies to a denial (step 2).

The denial's own NCD/LCD citation wins. If it cites nothing PAIR models, the
service codes are looked up in ``policies/_service-codes.yaml``. If that
doesn't give exactly one policy, the answer is "unsupported". PAIR never guesses.
"""

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from pair.contracts import Checklist

logger = logging.getLogger(__name__)

_REF_PREFIX = re.compile(r"^(?:LCD|NCD)[\s\-:]*", re.IGNORECASE)


class PolicySelectionError(ValueError):
    """The service-code table is malformed or names unknown policies."""


@dataclass(frozen=True)
class Selection:
    """The chosen checklist, or None when unsupported, with the reason shown to the user."""

    policy_id: str | None
    reason: str


def normalize_ref(ref: str) -> str:
    """Normalize a policy reference: ``" lcd L33718 "`` → ``"L33718"``, ``"NCD 240.4"`` → ``"240.4"``."""
    return _REF_PREFIX.sub("", ref.strip()).strip().upper()


def load_service_codes(path: Path, checklists: Mapping[str, Checklist]) -> dict[str, str]:
    """Load the code table as ``{CODE: policy_id}``.

    Raises:
        PolicySelectionError: If the file isn't a mapping of known policy ids to
            lists of code strings, or a code appears twice.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        logger.error("service-code table %s is not valid YAML: %s", path, error)
        raise PolicySelectionError(f"{path}: not valid YAML: {error}") from error
    if not isinstance(data, dict):
        raise PolicySelectionError(f"{path}: top level must map policy ids to code lists")
    table: dict[str, str] = {}
    for policy_id, codes in data.items():
        if policy_id not in checklists:
            raise PolicySelectionError(f"{path}: unknown policy {policy_id!r}")
        if not isinstance(codes, list) or not all(isinstance(code, str) for code in codes):
            raise PolicySelectionError(f"{path}: {policy_id} must list codes as strings")
        for code in codes:
            key = code.strip().upper()
            if key in table:
                raise PolicySelectionError(f"{path}: code {key} listed for {table[key]} and {policy_id}")
            table[key] = policy_id
    return table


def select_policy(
    policy_ref: str | None,
    service_codes: Sequence[str],
    checklists: Mapping[str, Checklist],
    code_table: Mapping[str, str],
) -> Selection:
    """Pick the checklist for a denial, or say it's unsupported.

    Args:
        policy_ref: The NCD/LCD id the denial cites, if any.
        service_codes: HCPCS/CPT codes from the denial.
        checklists: Loaded checklists keyed by policy id.
        code_table: ``{CODE: policy_id}`` from ``load_service_codes``.

    Returns:
        The selection and a plain reason.
    """
    if policy_ref:
        ref = normalize_ref(policy_ref)
        for checklist in checklists.values():
            if any(source.id.upper() == ref for source in checklist.sources):
                return Selection(checklist.id, f"policy_ref {ref} is quoted by {checklist.id}")
        logger.info("policy_ref %s not modeled, trying service codes", ref)
    matches = sorted({code_table[c.strip().upper()] for c in service_codes if c.strip().upper() in code_table})
    if len(matches) == 1:
        return Selection(matches[0], f"service code maps to {matches[0]}")
    if len(matches) > 1:
        return Selection(None, f"unsupported: codes point to more than one policy ({', '.join(matches)})")
    cited = f"policy {policy_ref!r}" if policy_ref else "no policy"
    return Selection(None, f"unsupported: PAIR doesn't cover {cited} or codes {list(service_codes)} yet")
