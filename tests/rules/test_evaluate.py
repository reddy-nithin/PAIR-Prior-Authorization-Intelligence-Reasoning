"""Tests for the three-valued rule evaluator (ADR-0008, ADR-0012)."""

import datetime as dt
from typing import Any

import pytest

from pair.rules.evaluate import RuleEvaluationError, evaluate, evaluate_rule
from pair.rules.expressions import parse_rule

T, F, U = True, False, None


def run(rule: str, **values: Any) -> bool | None:
    """Parse ``rule`` over the given names and evaluate it."""
    return evaluate_rule(rule, values)


@pytest.mark.parametrize(
    ("a", "b", "expected_and", "expected_or"),
    [
        (T, T, T, T),
        (T, F, F, T),
        (T, U, U, T),
        (F, F, F, F),
        (F, U, F, U),
        (U, U, U, U),
        (U, T, U, T),
        (U, F, F, U),
    ],
)
def test_kleene_and_or(a: bool | None, b: bool | None, expected_and: bool | None, expected_or: bool | None) -> None:
    """``and`` / ``or`` follow Kleene's strong three-valued tables."""
    assert run("a and b", a=a, b=b) is expected_and
    assert run("a or b", a=a, b=b) is expected_or


@pytest.mark.parametrize(("a", "expected"), [(T, F), (F, T), (U, U)])
def test_kleene_not(a: bool | None, expected: bool | None) -> None:
    """``not Unknown`` stays Unknown."""
    assert run("not a", a=a) is expected


@pytest.mark.parametrize(
    ("ahi", "expected"),
    [(4.9, F), (5, T), (10, T), (14, T), (14.1, F), (None, U)],
)
def test_chained_comparison(ahi: float | None, expected: bool | None) -> None:
    """``5 <= ahi <= 14`` holds on both boundaries and is Unknown for a missing value."""
    assert run("5 <= ahi <= 14", ahi=ahi) is expected


def test_chained_comparison_false_link_beats_unknown() -> None:
    """A definite False link makes the chain False even if another link is Unknown."""
    assert run("lo <= x <= hi", lo=None, x=20, hi=14) is False


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("x == 3", T),
        ("x != 3", F),
        ("x < 3", F),
        ("x > 2", T),
        ("x >= 3", T),
        ("x <= 2", F),
        ("x in [1, 2, 3]", T),
        ("x not in [1, 2, 3]", F),
        ("-1 < x", T),
    ],
)
def test_comparison_operators(rule: str, expected: bool) -> None:
    """Every comparison operator evaluates normally on known values."""
    assert run(rule, x=3) is expected


@pytest.mark.parametrize("rule", ["x == 3", "x in [1, 2]", "x not in [1, 2]", "'a' in x"])
def test_comparison_with_none_is_unknown(rule: str) -> None:
    """Any comparison or membership test with a missing operand is Unknown."""
    assert run(rule, x=None) is None


def test_membership_in_list_variable() -> None:
    """``in`` tests a string against a list variable."""
    assert run("'snoring' in symptoms", symptoms=["snoring", "insomnia"]) is True
    assert run("'snoring' in symptoms", symptoms=["insomnia"]) is False


@pytest.mark.parametrize(("x", "is_none", "is_not_none"), [(None, T, F), (0, F, T), (False, F, T)])
def test_is_none_is_always_definite(x: Any, is_none: bool, is_not_none: bool) -> None:
    """``is None`` / ``is not None`` never return Unknown."""
    assert run("x is None", x=x) is is_none
    assert run("x is not None", x=x) is is_not_none


@pytest.mark.parametrize(
    ("items", "expected_len", "expected_any", "expected_all"),
    [
        (["a", "b"], 2, T, T),
        ([], 0, F, T),
        (None, None, U, U),
    ],
)
def test_list_helpers(items: list[str] | None, expected_len: int | None, expected_any: bool | None, expected_all: bool | None) -> None:
    """``len`` / ``any`` / ``all`` on a list variable; a missing list is Unknown."""
    assert run("len(items) == 2", items=items) is (None if items is None else expected_len == 2)
    assert run("any(items)", items=items) is expected_any
    assert run("all(items)", items=items) is expected_all


@pytest.mark.parametrize(
    ("values", "expected_any", "expected_all"),
    [
        ([T, U], T, U),
        ([F, U], U, F),
        ([F, F], F, F),
        ([T, T], T, T),
    ],
)
def test_any_all_over_truth_values_are_kleene(values: list[bool | None], expected_any: bool | None, expected_all: bool | None) -> None:
    """``any([...])`` / ``all([...])`` over rule results use Kleene semantics."""
    a, b = values
    assert run("any([a, b])", a=a, b=b) is expected_any
    assert run("all([a, b])", a=a, b=b) is expected_all


def test_any_on_bare_unknown_operand() -> None:
    """``any`` over a list literal holding a missing value still applies Kleene rules."""
    assert run("any([a])", a=None) is None


START = dt.date(2026, 1, 1)


@pytest.mark.parametrize(
    ("later", "expected_days"),
    [(dt.date(2026, 1, 31), 30), (START, 0), (dt.date(2025, 12, 31), -1)],
)
def test_days_between_is_second_minus_first(later: dt.date, expected_days: int) -> None:
    """``days_between(a, b)`` is ``(b - a).days``: positive when ``b`` is later."""
    assert run(f"days_between(a, b) == {expected_days}", a=START, b=later) is True


@pytest.mark.parametrize(
    ("days", "expected"),
    [(-1, F), (0, T), (90, T), (91, F)],
)
def test_within_days_inclusive_window(days: int, expected: bool) -> None:
    """``within_days(a, b, n)`` holds for ``0 <= (b - a).days <= n``."""
    later = START + dt.timedelta(days=days)
    assert run("within_days(a, b, 90)", a=START, b=later) is expected


@pytest.mark.parametrize("rule", ["days_between(a, b) >= 0", "within_days(a, b, 90)"])
def test_date_helpers_with_missing_date_are_unknown(rule: str) -> None:
    """A missing date makes either helper Unknown, so the criterion is insufficient."""
    assert run(rule, a=START, b=None) is None
    assert run(rule, a=None, b=START) is None


def test_reevaluation_window_31st_to_91st_day() -> None:
    """The PAP re-evaluation rule accepts day index 30 to 90 after the start (31st to 91st day)."""
    rule = "days_between(s, r) >= 30 and within_days(s, r, 90)"
    for days, expected in [(29, False), (30, True), (90, True), (91, False)]:
        assert run(rule, s=START, r=START + dt.timedelta(days=days)) is expected, days


def test_bare_variable_must_be_bool_or_none() -> None:
    """A bare name used as a condition must hold a bool (or be missing)."""
    assert run("flag", flag=True) is True
    assert run("flag", flag=None) is None
    with pytest.raises(RuleEvaluationError, match="flag"):
        run("flag", flag=3)


def test_missing_binding_is_an_error() -> None:
    """Evaluating with a declared name absent from the bindings is a programming error."""
    tree = parse_rule("x > 1", {"x"})
    with pytest.raises(RuleEvaluationError, match="x"):
        evaluate(tree, {})


def test_type_mismatch_is_an_error() -> None:
    """Comparing incompatible types raises a clear error instead of a TypeError."""
    with pytest.raises(RuleEvaluationError, match="compare"):
        run("x > 1", x="high")


def test_helper_type_errors_are_wrapped() -> None:
    """Helpers given the wrong types raise ``RuleEvaluationError``."""
    with pytest.raises(RuleEvaluationError, match="days_between"):
        run("days_between(a, b) > 0", a=3, b=START)
    with pytest.raises(RuleEvaluationError, match="len"):
        run("len(x) > 0", x=3)


def test_real_ahi_rule() -> None:
    """The PAP AHI rule: 15+ with 30 events, or 5 to 14 with 10 events and a symptom."""
    rule = (
        "(ahi >= 15 and event_count >= 30) or "
        "(5 <= ahi <= 14 and event_count >= 10 and len(symptoms_or_conditions) > 0)"
    )
    assert run(rule, ahi=15, event_count=30, symptoms_or_conditions=None) is True
    assert run(rule, ahi=14, event_count=40, symptoms_or_conditions=["hypertension"]) is True
    assert run(rule, ahi=14, event_count=40, symptoms_or_conditions=None) is None
    assert run(rule, ahi=4, event_count=40, symptoms_or_conditions=None) is False
    assert run(rule, ahi=None, event_count=None, symptoms_or_conditions=None) is None
    assert run(rule, ahi=18, event_count=None, symptoms_or_conditions=None) is None


@pytest.mark.parametrize("source", ["x + 1 > 0", "+x > 0", "print(x)", "x.y", "{x}"])
def test_unvalidated_trees_are_refused(source: str) -> None:
    """Even a tree that skipped ``parse_rule`` can't run non-whitelisted code."""
    import ast

    tree = ast.parse(source, mode="eval")
    with pytest.raises(RuleEvaluationError):
        evaluate(tree, {"x": 1, "print": print})


def test_is_with_non_none_on_unvalidated_tree_is_definite() -> None:
    """``is`` stays an identity check; the validator is what restricts it to None."""
    import ast

    assert evaluate(ast.parse("x is x", mode="eval"), {"x": 1}) is True


@pytest.mark.parametrize(
    ("rule", "values"),
    [
        ("within_days(a, b, n)", {"a": START, "b": START, "n": "90"}),
        ("within_days(a, b, n)", {"a": START, "b": START, "n": True}),
        ("any(x)", {"x": "text"}),
        ("all(x)", {"x": 3}),
    ],
)
def test_helper_argument_types(rule: str, values: dict[str, Any]) -> None:
    """Helpers reject wrongly typed arguments with ``RuleEvaluationError``."""
    with pytest.raises(RuleEvaluationError):
        evaluate_rule(rule, values)


def test_within_days_unknown_limit() -> None:
    """A missing day limit is Unknown, like a missing date."""
    assert evaluate_rule("within_days(a, b, n)", {"a": START, "b": START, "n": None}) is None
