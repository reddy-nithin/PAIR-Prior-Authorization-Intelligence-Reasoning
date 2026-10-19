"""Three-valued evaluator for policy rules and checklist logic (ADR-0008, ADR-0012).

Walks a tree already validated by ``parse_rule``. Missing values are ``None``
and propagate as Unknown through Kleene's strong logic, so a silent record
becomes "insufficient" rather than "unmet". Nothing is ever passed to ``eval``.
"""

import ast
import datetime as dt
import operator
from collections.abc import Callable, Mapping
from typing import Any

from pair.rules.expressions import parse_rule

Truth = bool | None
"""True, False, or Unknown (``None``)."""

# Every comparison operator Python has, except ``is`` / ``is not`` (handled first).
_COMPARE: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}


class RuleEvaluationError(ValueError):
    """A rule can't be evaluated with the given bindings (wrong type or missing name)."""


def kleene_and(values: list[Truth]) -> Truth:
    """False if any value is False, else Unknown if any is Unknown, else True."""
    if any(value is False for value in values):
        return False
    if any(value is None for value in values):
        return None
    return True


def kleene_or(values: list[Truth]) -> Truth:
    """True if any value is True, else Unknown if any is Unknown, else False."""
    if any(value is True for value in values):
        return True
    if any(value is None for value in values):
        return None
    return False


def evaluate(tree: ast.Expression, bindings: Mapping[str, Any]) -> Truth:
    """Evaluate a validated rule tree to True, False or Unknown.

    Args:
        tree: A tree returned by ``parse_rule``.
        bindings: A value for every name the tree reads; ``None`` means missing.

    Returns:
        The rule's truth value; ``None`` means Unknown.

    Raises:
        RuleEvaluationError: If a name is unbound, a value has the wrong type,
            or the tree contains a node outside ADR-0008.
    """
    return _Evaluator(bindings).truth(tree.body)


def evaluate_rule(text: str, bindings: Mapping[str, Any]) -> Truth:
    """Parse ``text`` over the names in ``bindings`` and evaluate it."""
    return evaluate(parse_rule(text, bindings.keys()), bindings)


class _Evaluator:
    """Evaluates nodes against one set of bindings."""

    def __init__(self, bindings: Mapping[str, Any]) -> None:
        """Store the variable bindings."""
        self.bindings = bindings

    def truth(self, node: ast.expr) -> Truth:
        """Evaluate ``node`` where a truth value is required."""
        return _as_truth(self.value(node), ast.unparse(node))

    def value(self, node: ast.expr) -> Any:
        """Evaluate ``node`` to a value; ``None`` means missing or Unknown."""
        if isinstance(node, ast.BoolOp):
            operands = [self.truth(item) for item in node.values]
            return kleene_and(operands) if isinstance(node.op, ast.And) else kleene_or(operands)
        if isinstance(node, ast.UnaryOp):
            return self.unary(node)
        if isinstance(node, ast.Compare):
            return self.compare(node)
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.Name):
            if node.id not in self.bindings:
                raise RuleEvaluationError(f"no value bound for {node.id!r}")
            return self.bindings[node.id]
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            return [self.value(item) for item in node.elts]
        raise RuleEvaluationError(f"{type(node).__name__} is not allowed (ADR-0008)")

    def unary(self, node: ast.UnaryOp) -> Any:
        """``not x`` (Kleene) or a negative number literal."""
        if isinstance(node.op, ast.Not):
            operand = self.truth(node.operand)
            return None if operand is None else not operand
        if isinstance(node.op, ast.USub):
            return -self.value(node.operand)
        raise RuleEvaluationError(f"{type(node.op).__name__} is not allowed (ADR-0008)")

    def compare(self, node: ast.Compare) -> Truth:
        """Evaluate each link of a (possibly chained) comparison and AND them."""
        operands = [self.value(node.left), *(self.value(item) for item in node.comparators)]
        links: list[Truth] = []
        for index, op in enumerate(node.ops):
            left, right = operands[index], operands[index + 1]
            links.append(_compare_link(op, left, right, ast.unparse(node)))
        return kleene_and(links)

    def call(self, node: ast.Call) -> Any:
        """Call a whitelisted helper with Unknown-propagating semantics."""
        name = node.func.id if isinstance(node.func, ast.Name) else type(node.func).__name__
        args = [self.value(item) for item in node.args]
        helper = _HELPERS.get(name)
        if helper is None:
            raise RuleEvaluationError(f"call to {name!r} is not allowed (ADR-0008)")
        try:
            return helper(*args)
        except TypeError as error:
            raise RuleEvaluationError(f"{name}() got invalid arguments {args!r}: {error}") from error


def _as_truth(value: Any, where: str) -> Truth:
    """Require a bool or Unknown where a condition is expected."""
    if value is None or isinstance(value, bool):
        return value
    raise RuleEvaluationError(f"expected a true/false value in {where!r}, got {value!r}")


def _compare_link(op: ast.cmpop, left: Any, right: Any, where: str) -> Truth:
    """One comparison; ``is`` is always definite, anything else with None is Unknown."""
    if isinstance(op, ast.Is):
        return left is right
    if isinstance(op, ast.IsNot):
        return left is not right
    if left is None or right is None:
        return None
    try:
        return bool(_COMPARE[type(op)](left, right))
    except TypeError as error:
        raise RuleEvaluationError(f"cannot compare {left!r} and {right!r} in {where!r}") from error


def _element_truth(item: Any) -> Truth:
    """Kleene value of a list element: bools and None as-is, other items by presence."""
    if item is None or isinstance(item, bool):
        return item
    return bool(item)


def _any(items: Any) -> Truth:
    if items is None:
        return None
    if not isinstance(items, list):
        raise TypeError("any() needs a list")
    return kleene_or([_element_truth(item) for item in items])


def _all(items: Any) -> Truth:
    if items is None:
        return None
    if not isinstance(items, list):
        raise TypeError("all() needs a list")
    return kleene_and([_element_truth(item) for item in items])


def _len(items: Any) -> int | None:
    if items is None:
        return None
    if not isinstance(items, (list, str)):
        raise TypeError("len() needs a list or text")
    return len(items)


def _check_dates(*values: Any) -> None:
    for value in values:
        if not isinstance(value, dt.date):
            raise TypeError(f"expected a date, got {value!r}")


def _days_between(first: Any, second: Any) -> int | None:
    """``(second - first).days``; Unknown if either date is missing."""
    if first is None or second is None:
        return None
    _check_dates(first, second)
    return int((second - first).days)


def _within_days(first: Any, second: Any, limit: Any) -> Truth:
    """True when ``second`` falls 0 to ``limit`` days after ``first`` (inclusive)."""
    gap = _days_between(first, second)
    if gap is None or limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError(f"day limit must be an integer, got {limit!r}")
    return 0 <= gap <= limit


_HELPERS: dict[str, Callable[..., Any]] = {
    "any": _any,
    "all": _all,
    "len": _len,
    "days_between": _days_between,
    "within_days": _within_days,
}
