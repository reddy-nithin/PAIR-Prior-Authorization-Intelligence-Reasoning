"""Load and strictly validate policy checklist YAML files.

A policy file must parse as YAML, match the ``Checklist`` contract, and every
rule and the ``logic`` string must pass the ADR-0008 validator. Any problem
raises ``PolicyValidationError`` naming the file, so a bad policy can never
reach the rule engine.
"""

import logging
from pathlib import Path

import pydantic
import yaml

from pair.contracts import Checklist
from pair.rules.expressions import RuleSyntaxError, parse_rule, referenced_names

logger = logging.getLogger(__name__)

POLICY_GLOB = "*.yaml"
HELPER_PREFIX = "_"


class PolicyValidationError(ValueError):
    """A policy file is malformed or breaks the checklist contract."""


def load_policy(path: Path) -> Checklist:
    """Load one policy YAML file into a validated ``Checklist``.

    Args:
        path: Path to ``<policy-id>.yaml``.

    Returns:
        The validated checklist.

    Raises:
        PolicyValidationError: If the file can't be parsed or fails any check.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise PolicyValidationError("top level must be a mapping")
        checklist = Checklist.model_validate(data)
        _check_file_name(checklist, path)
        _check_rules(checklist)
    except (yaml.YAMLError, pydantic.ValidationError, RuleSyntaxError, PolicyValidationError) as error:
        logger.error("invalid policy %s: %s", path, error)
        raise PolicyValidationError(f"{path}: {error}") from error
    return checklist


def load_all(directory: Path) -> dict[str, Checklist]:
    """Load every policy in ``directory``, skipping helper files that start with ``_``.

    Returns:
        Checklists keyed by policy id, in file-name order.

    Raises:
        PolicyValidationError: If any file is invalid or none are found.
    """
    paths = sorted(p for p in directory.glob(POLICY_GLOB) if not p.name.startswith(HELPER_PREFIX))
    if not paths:
        raise PolicyValidationError(f"no policy files found in {directory}")
    checklists = [load_policy(path) for path in paths]
    return {checklist.id: checklist for checklist in checklists}


def _check_file_name(checklist: Checklist, path: Path) -> None:
    """The file stem must equal the checklist id."""
    if checklist.id != path.stem:
        raise PolicyValidationError(f"id {checklist.id!r} does not match file name {path.name!r}")


def _check_rules(checklist: Checklist) -> None:
    """Validate each rule against its declared variables, and ``logic`` against ids + context."""
    for criterion in checklist.criteria:
        tree = parse_rule(criterion.rule, criterion.variables.keys())
        unused = sorted(set(criterion.variables) - referenced_names(tree))
        if unused:
            raise PolicyValidationError(f"criterion {criterion.id} declares unused variables: {unused}")
    parse_rule(checklist.logic, set(checklist.criterion_ids) | set(checklist.context))
