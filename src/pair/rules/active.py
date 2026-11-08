"""Which criteria can still change the result, given the case's context flags (ADR-0019).

A criterion is *active* if some outcome of the other criteria makes the checklist
``logic`` depend on it, once the context flags are bound. PAP's
``initial or (adherence and reevaluation)`` makes adherence inactive for an
initial request, for example. A flag counts only if it cites where it came from
(a record or denial span, or explicit user input); a missing or unsourced flag
is Unknown, and Unknown keeps both branches active. The rule engine's gap list is
never changed here; callers filter inactive gaps downstream.
"""

import ast
import itertools
from collections.abc import Mapping
from dataclasses import dataclass

from pair.contracts import Checklist
from pair.rules.evaluate import evaluate
from pair.rules.expressions import parse_rule


@dataclass(frozen=True)
class ContextFlag:
    """A context flag value and where it came from (None: no source, so Unknown)."""

    value: bool | None
    source: str | None


def bind_context(flags: Mapping[str, ContextFlag]) -> dict[str, bool | None]:
    """Flag values for the logic: the value when sourced, else None (Unknown)."""
    return {name: flag.value if flag.source else None for name, flag in flags.items()}


def _logic(checklist: Checklist) -> ast.Expression:
    """The parsed checklist logic."""
    return parse_rule(checklist.logic, [*checklist.criterion_ids, *checklist.context])


def active_criteria(checklist: Checklist, flags: Mapping[str, ContextFlag]) -> tuple[str, ...]:
    """Criterion ids, in checklist order, that can still change the overall result.

    Raises:
        ValueError: If a flag isn't declared in the checklist context.
    """
    unknown = sorted(set(flags) - set(checklist.context))
    if unknown:
        raise ValueError(f"{checklist.id} declares no context flags {unknown}")
    tree = _logic(checklist)
    bound = bind_context(flags)
    open_flags = [name for name in checklist.context if bound.get(name) is None]
    ids = checklist.criterion_ids
    return tuple(cid for cid in ids if _depends_on(tree, cid, [c for c in ids if c != cid], open_flags, bound))


def _depends_on(
    tree: ast.Expression, criterion_id: str, others: list[str], open_flags: list[str], bound: Mapping[str, bool | None]
) -> bool:
    """Whether some outcome of the other criteria and open flags makes the logic turn on ``criterion_id``."""
    for flag_values in itertools.product((True, False), repeat=len(open_flags)):
        for values in itertools.product((True, False), repeat=len(others)):
            rest = {**bound, **dict(zip(open_flags, flag_values, strict=True)), **dict(zip(others, values, strict=True))}
            if evaluate(tree, {**rest, criterion_id: True}) != evaluate(tree, {**rest, criterion_id: False}):
                return True
    return False


def any_of_groups(checklist: Checklist) -> tuple[tuple[str, ...], ...]:
    """Every ``or`` in the logic whose operands are all bare criterion ids."""
    ids = set(checklist.criterion_ids)
    return tuple(
        tuple(value.id for value in node.values if isinstance(value, ast.Name))
        for node in ast.walk(_logic(checklist))
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
        and all(isinstance(value, ast.Name) and value.id in ids for value in node.values)
    )
