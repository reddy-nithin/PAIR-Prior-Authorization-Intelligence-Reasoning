"""Tests for the restricted rule expression validator (ADR-0008)."""

import pytest

from pair.rules.expressions import (
    HELPERS,
    RuleSyntaxError,
    parse_rule,
    referenced_names,
)

AHI_NAMES = {"ahi", "symptoms", "f2f_date", "test_date", "nights_4h_pct", "spo2"}


@pytest.mark.parametrize(
    "rule",
    [
        "ahi >= 15 or (5 <= ahi <= 14 and any(symptoms))",
        "f2f_date is not None and days_between(f2f_date, test_date) >= 0",
        "within_days(f2f_date, test_date, 180)",
        "nights_4h_pct >= 70",
        "not (spo2 > 88)",
        "'snoring' in symptoms or len(symptoms) >= 2",
        "ahi != -1 and spo2 in [86, 87, 88]",
        "all([ahi >= 5, spo2 <= 88])",
        "symptoms is None",
        "True",
    ],
)
def test_valid_rules_parse(rule: str) -> None:
    """Rules in the allowed subset parse without error."""
    parse_rule(rule, AHI_NAMES)


def test_logic_over_criterion_ids_parses() -> None:
    """Checklist logic is the same language over criterion ids and context flags."""
    parse_rule("f2f_visit and ahi_threshold and (initial or adherence)", {"f2f_visit", "ahi_threshold", "initial", "adherence"})


@pytest.mark.parametrize(
    ("rule", "fragment"),
    [
        ("__import__('os')", "call to '__import__'"),
        ("ahi.real > 1", "Attribute"),
        ("symptoms[0] == 'x'", "Subscript"),
        ("(lambda: 1)()", "Lambda"),
        ("any([s for s in symptoms])", "ListComp"),
        ("ahi + 1 > 15", "BinOp"),
        ("ahi > 15 if spo2 else False", "IfExp"),
        ("print(ahi)", "call to 'print'"),
        ("ahi(1)", "call to 'ahi'"),
        ("any(symptoms, key=1)", "keyword"),
        ("any(*symptoms)", "Starred"),
        ("rdi >= 15", "undeclared name 'rdi'"),
        ("ahi is 15", "only with None"),
        ("{'a': 1}", "Dict"),
        ("(x := 1)", "NamedExpr"),
        ("b'x' == ahi", "constant"),
        ("days_between", "helper 'days_between' used without calling it"),
        ("-ahi < 0", "USub is not allowed"),
        ("~ahi", "Invert is not allowed"),
        ("-True", "USub is not allowed"),
    ],
)
def test_disallowed_constructs_rejected(rule: str, fragment: str) -> None:
    """Anything outside ADR-0008's subset fails with a message naming the problem."""
    with pytest.raises(RuleSyntaxError, match=fragment):
        parse_rule(rule, AHI_NAMES)


@pytest.mark.parametrize("rule", ["", "   ", "ahi >=", "import os", "ahi = 15"])
def test_garbage_rejected(rule: str) -> None:
    """Empty strings, broken syntax and statements are rejected."""
    with pytest.raises(RuleSyntaxError):
        parse_rule(rule, AHI_NAMES)


def test_error_reports_column() -> None:
    """Errors point at the offending column so YAML authors can find it."""
    with pytest.raises(RuleSyntaxError) as info:
        parse_rule("ahi >= 15 and symptoms[0]", AHI_NAMES)
    assert info.value.col == 14
    assert "col 14" in str(info.value)


def test_referenced_names_excludes_helpers() -> None:
    """The loader can list which variables a rule reads."""
    tree = parse_rule("within_days(f2f_date, test_date, 180) and ahi >= 15", AHI_NAMES)
    assert referenced_names(tree) == {"f2f_date", "test_date", "ahi"}


def test_helper_names_cannot_be_declared_variables() -> None:
    """A variable named like a helper would be ambiguous."""
    with pytest.raises(RuleSyntaxError, match="shadows helper"):
        parse_rule("len > 1", {"len"})


def test_helpers_are_the_adr_set() -> None:
    """The helper whitelist matches ADR-0008 exactly."""
    assert HELPERS == frozenset({"any", "all", "len", "days_between", "within_days"})
