"""Deterministic rule engine: checklist + evidence → ``Verdict`` (step 4, spec §6.1).

No LLM is involved. Evidence is bound to rule variables (ADR-0012), each
criterion's rule is evaluated three-valued, and the checklist ``logic``
combines the outcomes. Every result carries a readable trace of the rule, the
values with their source spans, and the outcome.
"""

import datetime as dt
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pair.contracts import (
    Checklist,
    Criterion,
    CriterionResult,
    CriterionStatus,
    Evidence,
    EvidenceStatus,
    Gap,
    VariableType,
    Verdict,
)
from pair.rules.evaluate import Truth, evaluate
from pair.rules.expressions import parse_rule

logger = logging.getLogger(__name__)

GapMessage = Callable[[str, CriterionStatus], str]
"""Returns the plain-language gap text for a criterion id and its non-met status."""

_STATUS_BY_TRUTH: dict[Truth, CriterionStatus] = {
    True: CriterionStatus.MET,
    False: CriterionStatus.UNMET,
    None: CriterionStatus.INSUFFICIENT,
}

_TRUTH_BY_STATUS: dict[CriterionStatus, Truth] = {status: truth for truth, status in _STATUS_BY_TRUTH.items()}


class RuleEngineError(ValueError):
    """Evidence or context doesn't fit the checklist being applied."""


@dataclass(frozen=True)
class Binding:
    """The value bound to one rule variable, and why.

    Attributes:
        value: The bound value, or None when missing or conflicting.
        conflict: True when asserted evidence disagrees on the value.
        notes: Trace lines describing the evidence behind the value.
    """

    value: Any
    conflict: bool
    notes: tuple[str, ...]


def run_rules(
    checklist: Checklist,
    evidence: Sequence[Evidence],
    context: Mapping[str, bool | None],
    gap_message: GapMessage,
) -> Verdict:
    """Apply a checklist to a case's evidence.

    Args:
        checklist: The policy checklist to apply.
        evidence: Grounded evidence from the extractor, for this checklist.
        context: Case-level flags declared by the checklist (e.g. ``initial``);
            a missing flag is Unknown.
        gap_message: Gap text for each unmet or insufficient criterion.

    Returns:
        The verdict: one result per criterion in checklist order, the overall
        outcome of ``logic``, and one gap per non-met criterion.

    Raises:
        RuleEngineError: If evidence names an unknown criterion or variable, or
            a context flag is undeclared or not a bool.
    """
    _check_context(checklist, context)
    by_criterion = _group_evidence(checklist, evidence)
    results = [_evaluate_criterion(criterion, by_criterion[criterion.id]) for criterion in checklist.criteria]
    logic_bindings: dict[str, Any] = {result.criterion_id: _TRUTH_BY_STATUS[result.status] for result in results}
    logic_bindings.update({flag: context.get(flag) for flag in checklist.context})
    overall = _STATUS_BY_TRUTH[evaluate(parse_rule(checklist.logic, logic_bindings.keys()), logic_bindings)]
    gaps = [
        Gap(criterion_id=result.criterion_id, message=gap_message(result.criterion_id, result.status))
        for result in results
        if result.status is not CriterionStatus.MET
    ]
    logger.info("policy %s: overall %s, %d gaps", checklist.id, overall.value, len(gaps))
    return Verdict(policy_id=checklist.id, results=results, overall=overall, gaps=gaps)


def _check_context(checklist: Checklist, context: Mapping[str, bool | None]) -> None:
    """Context flags must be declared and hold True, False or None."""
    for flag, value in context.items():
        if flag not in checklist.context:
            raise RuleEngineError(f"context flag {flag!r} is not declared by policy {checklist.id}")
        if value is not None and not isinstance(value, bool):
            raise RuleEngineError(f"context flag {flag!r} must be true/false, got {value!r}")


def _group_evidence(checklist: Checklist, evidence: Sequence[Evidence]) -> dict[str, list[Evidence]]:
    """Group evidence by criterion, rejecting unknown criteria and variables."""
    criteria = {criterion.id: criterion for criterion in checklist.criteria}
    grouped: dict[str, list[Evidence]] = {criterion_id: [] for criterion_id in criteria}
    for item in evidence:
        criterion = criteria.get(item.criterion_id)
        if criterion is None:
            raise RuleEngineError(f"evidence names criterion {item.criterion_id!r}, not in policy {checklist.id}")
        if item.variable not in criterion.variables:
            raise RuleEngineError(f"criterion {criterion.id} has no variable {item.variable!r}")
        grouped[criterion.id].append(item)
    return grouped


def _evaluate_criterion(criterion: Criterion, evidence: list[Evidence]) -> CriterionResult:
    """Bind variables, evaluate the rule, and build the result with its trace."""
    bindings = {
        name: _bind(var_type, [item for item in evidence if item.variable == name])
        for name, var_type in criterion.variables.items()
    }
    conflicts = sorted(name for name, binding in bindings.items() if binding.conflict)
    if conflicts:
        status = CriterionStatus.INSUFFICIENT
        outcome = f"conflicting values for {', '.join(conflicts)} → insufficient"
    else:
        values = {name: binding.value for name, binding in bindings.items()}
        status = _STATUS_BY_TRUTH[evaluate(parse_rule(criterion.rule, values.keys()), values)]
        outcome = f"result: {status.value}"
    lines = [f"rule: {criterion.rule}"]
    for name, binding in bindings.items():
        lines.append(f"{name} = {_shown(binding)}")
        lines.extend(f"  {note}" for note in binding.notes)
    lines.append(outcome)
    return CriterionResult(criterion_id=criterion.id, status=status, evidence=evidence, trace="\n".join(lines))


def _shown(binding: Binding) -> str:
    """How a bound value appears in the trace: conflict, missing, or the value (dates as ISO)."""
    if binding.conflict:
        return "conflict"
    if binding.value is None:
        return "missing"
    if isinstance(binding.value, dt.date):
        return binding.value.isoformat()
    return repr(binding.value)


def _bind(var_type: VariableType, items: list[Evidence]) -> Binding:
    """Turn the evidence for one variable into its bound value (ADR-0012)."""
    notes: list[str] = []
    usable: list[Any] = []
    for item in items:
        source = f"[{item.doc_id} {item.char_start}-{item.char_end}] {item.span_text!r}"
        if item.status is not EvidenceStatus.ASSERTED:
            notes.append(f"{item.status.value}, not used: {source}")
        elif item.value is None:
            notes.append(f"mention without a value: {source}")
        elif not value_fits(var_type, item.value):
            notes.append(f"ignored ({type(item.value).__name__} is not {var_type.value}): {source}")
        else:
            notes.append(f"from {source}")
            usable.append(item.value)
    if var_type is VariableType.LIST:
        return Binding(value=_merge_items(usable), conflict=False, notes=tuple(notes))
    distinct: list[Any] = []
    for value in usable:
        if value not in distinct:
            distinct.append(value)
    if len(distinct) > 1:
        return Binding(value=None, conflict=True, notes=tuple(notes))
    return Binding(value=distinct[0] if distinct else None, conflict=False, notes=tuple(notes))


def _merge_items(values: list[Any]) -> list[str] | None:
    """Merge asserted list values (or single strings) into one ordered, de-duplicated list."""
    merged: list[str] = []
    for value in values:
        for item in value if isinstance(value, list) else [value]:
            if item not in merged:
                merged.append(item)
    return merged or None


def value_fits(var_type: VariableType, value: Any) -> bool:
    """Whether a normalized value has the type its variable declares."""
    if var_type is VariableType.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if var_type is VariableType.BOOL:
        return isinstance(value, bool)
    if var_type is VariableType.DATE:
        return isinstance(value, dt.date)
    if var_type is VariableType.TEXT:
        return isinstance(value, str)
    return isinstance(value, (list, str))
