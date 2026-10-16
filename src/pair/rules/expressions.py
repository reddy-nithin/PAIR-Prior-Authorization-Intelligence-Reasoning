"""Restricted expression language for policy rules and checklist logic (ADR-0008).

Rules are parsed with the standard-library ``ast`` module and then walked
against a whitelist. Nothing is ever executed here; Phase 2 adds an evaluator
that walks the same validated tree.
"""

import ast
from collections.abc import Collection

HELPERS: frozenset[str] = frozenset({"any", "all", "len", "days_between", "within_days"})
"""Functions a rule may call. Everything else is rejected."""

_CONSTANT_TYPES: tuple[type, ...] = (bool, int, float, str, type(None))


class RuleSyntaxError(ValueError):
    """A rule string is not valid under ADR-0008.

    Attributes:
        rule: The rule text that failed.
        col: Zero-based column of the offending node, if known.
    """

    def __init__(self, message: str, rule: str, col: int | None = None) -> None:
        """Build the error with the rule text and the offending column."""
        location = f" (col {col})" if col is not None else ""
        super().__init__(f"{message}{location} in rule: {rule!r}")
        self.rule = rule
        self.col = col


def parse_rule(text: str, allowed_names: Collection[str]) -> ast.Expression:
    """Parse and validate a rule or logic string.

    Args:
        text: The expression, e.g. ``"ahi >= 15 or any(symptoms)"``.
        allowed_names: Variable names the expression may read (declared
            variables for a rule, criterion ids plus context flags for logic).

    Returns:
        The validated expression tree.

    Raises:
        RuleSyntaxError: If the text is empty, isn't a single expression, uses a
            construct outside the whitelist, or reads an undeclared name.
    """
    shadowing = HELPERS.intersection(allowed_names)
    if shadowing:
        raise RuleSyntaxError(f"variable name shadows helper: {sorted(shadowing)}", text)
    if not text.strip():
        raise RuleSyntaxError("rule is empty", text)
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as error:
        raise RuleSyntaxError(f"not a valid expression: {error.msg}", text, error.offset) from error
    _Validator(text, frozenset(allowed_names)).check(tree.body)
    return tree


def referenced_names(tree: ast.Expression) -> set[str]:
    """Return the variable names an expression reads, excluding helper calls."""
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return names - (called & HELPERS)


class _Validator:
    """Walks an expression tree and rejects anything outside ADR-0008."""

    def __init__(self, rule: str, allowed_names: frozenset[str]) -> None:
        """Store the rule text (for messages) and the declared names."""
        self.rule = rule
        self.allowed_names = allowed_names

    def fail(self, message: str, node: ast.AST) -> RuleSyntaxError:
        """Build an error that points at ``node``'s column."""
        return RuleSyntaxError(message, self.rule, getattr(node, "col_offset", None))

    def check(self, node: ast.expr) -> None:
        """Validate one node and, recursively, its children."""
        if isinstance(node, ast.BoolOp):
            self.check_bool_op(node)
        elif isinstance(node, ast.UnaryOp):
            self.check_unary_op(node)
        elif isinstance(node, ast.Compare):
            self.check_compare(node)
        elif isinstance(node, ast.Call):
            self.check_call(node)
        elif isinstance(node, ast.Name):
            self.check_name(node)
        elif isinstance(node, ast.Constant):
            self.check_constant(node)
        elif isinstance(node, ast.List):
            for element in node.elts:
                self.check(element)
        else:
            raise self.fail(f"{type(node).__name__} is not allowed", node)

    def check_bool_op(self, node: ast.BoolOp) -> None:
        """``and`` / ``or`` (the only boolean operators Python has) over allowed operands."""
        for value in node.values:
            self.check(value)

    def check_unary_op(self, node: ast.UnaryOp) -> None:
        """``not x``, or a minus sign on a number literal."""
        is_negative_number = (
            isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, (int, float))
            and not isinstance(node.operand.value, bool)
        )
        if not (isinstance(node.op, ast.Not) or is_negative_number):
            raise self.fail(f"{type(node.op).__name__} is not allowed", node)
        self.check(node.operand)

    def check_compare(self, node: ast.Compare) -> None:
        """Comparisons, including chains; ``is`` / ``is not`` only against None.

        Every Python comparison operator is allowed, so only ``is`` needs a check.
        """
        self.check(node.left)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            is_none = isinstance(comparator, ast.Constant) and comparator.value is None
            if isinstance(op, (ast.Is, ast.IsNot)) and not is_none:
                raise self.fail("'is' / 'is not' may be used only with None", comparator)
            self.check(comparator)

    def check_call(self, node: ast.Call) -> None:
        """Positional calls to whitelisted helpers only."""
        name = node.func.id if isinstance(node.func, ast.Name) else type(node.func).__name__
        if name not in HELPERS:
            raise self.fail(f"call to {name!r} is not allowed", node)
        if node.keywords:
            raise self.fail(f"keyword arguments to {name!r} are not allowed", node)
        for argument in node.args:
            self.check(argument)

    def check_name(self, node: ast.Name) -> None:
        """Variables must be declared; helpers must be called, not read."""
        if node.id in HELPERS:
            raise self.fail(f"helper {node.id!r} used without calling it", node)
        if node.id not in self.allowed_names:
            raise self.fail(f"undeclared name {node.id!r}", node)

    def check_constant(self, node: ast.Constant) -> None:
        """Only bool, number, string and None literals."""
        if not isinstance(node.value, _CONSTANT_TYPES):
            raise self.fail(f"constant of type {type(node.value).__name__} is not allowed", node)
