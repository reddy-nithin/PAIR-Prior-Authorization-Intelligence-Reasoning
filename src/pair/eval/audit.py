"""Mechanical audit pre-check for synthetic cases and policy clauses (ADR-0013).

Runs the exact checks so the critic agent only spends judgment on what code
can't check. Check ids follow ``docs/audit/critic-rubric.md``: L labels,
K leaks, D denial, P policy, M0 for a case that can't be checked at all.
"""

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pair.contracts import Checklist
from pair.eval.cases import CaseBundle, CaseLoadError, load_case
from pair.eval.synth.denials import REASONS
from pair.eval.synth.planners import UNITS
from pair.policies.mcd import MCDDocument, MCDDocumentNotFound, MCDExport
from pair.policies.select import normalize_ref
from pair.rules.engine import RuleEngineError, run_rules

logger = logging.getLogger(__name__)

_NUMBER = r"(\d+(?:\.\d+)?)"
_LABEL_BEFORE = re.compile(r"^\s*([A-Za-z][A-Za-z%\- ]*?)\s*(?:of|is|was|=|:)?\s*" + _NUMBER)
_LABEL_AFTER = re.compile(r"^\s*" + _NUMBER + r"\s+([A-Za-z][A-Za-z\- ]*[A-Za-z])")
_FILLER = frozenset({"for", "of", "on", "at", "in", "with", "about", "since", "after", "over", "is", "was"})
"""Words too common to name a value ("for 8 months" has no label)."""


class Severity(StrEnum):
    """How bad a finding is (rubric severities)."""

    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"


@dataclass(frozen=True)
class PrecheckFinding:
    """One mechanical problem in a case or policy.

    Attributes:
        case_id: The case id, or ``policy:<id>`` for a policy finding.
        check_id: Rubric check id (L1, L2, K1, K2, D1, D2, P1, M0).
        target: The criterion, unit or field the finding is about.
        severity: Blocker, major or minor.
        message: What is wrong, for a person and the critic.
    """

    case_id: str
    check_id: str
    target: str
    severity: Severity
    message: str

    def to_json(self) -> dict[str, Any]:
        """A JSON-ready dict."""
        return {**asdict(self), "severity": self.severity.value}


def check_case(case: CaseBundle, checklists: Mapping[str, Checklist]) -> list[PrecheckFinding]:
    """Run every mechanical check on one loaded case.

    Span offsets are already checked by ``CaseBundle`` when it loads.

    Args:
        case: The case bundle.
        checklists: Loaded policies by id.

    Returns:
        Findings, empty when the case passes.
    """
    checklist = checklists.get(case.policy_id)
    if checklist is None:
        return [PrecheckFinding(case.id, "M0", case.policy_id, Severity.BLOCKER, "policy not loaded")]
    try:
        findings = _check_labels(case, checklist)
    except RuleEngineError as error:
        logger.error("%s: rule engine rejected the gold evidence: %s", case.id, error)
        return [PrecheckFinding(case.id, "M0", "gold_evidence", Severity.BLOCKER, f"rule engine error: {error}")]
    return findings + _check_absent_leaks(case) + _check_second_values(case) + _check_denial(case)


def precheck_paths(paths: Sequence[Path], checklists: Mapping[str, Checklist]) -> list[PrecheckFinding]:
    """Load and check each case file; a file that won't load is an M0 blocker."""
    findings: list[PrecheckFinding] = []
    for path in paths:
        try:
            case = load_case(path)
        except CaseLoadError as error:
            findings.append(PrecheckFinding(path.stem, "M0", "file", Severity.BLOCKER, str(error)))
            continue
        findings.extend(check_case(case, checklists))
    return findings


def check_policy_sources(checklists: Mapping[str, Checklist], export: MCDExport) -> list[PrecheckFinding]:
    """P1 (mechanical part): each criterion's clause appears verbatim in its MCD source."""
    findings: list[PrecheckFinding] = []
    for checklist in checklists.values():
        sources = {source.id: source for source in checklist.sources}
        docs: dict[str, MCDDocument | None] = {}
        for criterion in checklist.criteria:
            source = sources[criterion.source_id]
            if source.id not in docs:
                try:
                    docs[source.id] = export.find_ncd(source.id) if source.type == "NCD" else export.find_lcd(source.id)
                except MCDDocumentNotFound as error:
                    logger.error("policy %s: %s", checklist.id, error)
                    docs[source.id] = None
            doc = docs[source.id]
            if doc is None or not doc.contains(criterion.clause):
                where = "source not in the MCD export" if doc is None else f"not verbatim in {doc.id} v{doc.version}"
                findings.append(
                    PrecheckFinding(f"policy:{checklist.id}", "P1", criterion.id, Severity.BLOCKER, f"clause {where}")
                )
    return findings


def _check_labels(case: CaseBundle, checklist: Checklist) -> list[PrecheckFinding]:
    """L1/L2: the rule engine on the gold evidence reproduces the gold labels."""
    verdict = run_rules(checklist, case.gold_evidence, case.context, lambda _c, _s: "gap")
    findings = [
        PrecheckFinding(
            case.id, "L1", result.criterion_id, Severity.BLOCKER,
            f"gold says {case.gold_statuses.get(result.criterion_id)}, rules on gold evidence give {result.status}",
        )
        for result in verdict.results
        if case.gold_statuses.get(result.criterion_id) is not result.status
    ]  # fmt: skip
    if verdict.overall is not case.gold_overall:
        message = f"gold overall {case.gold_overall}, policy logic gives {verdict.overall}"
        findings.append(PrecheckFinding(case.id, "L2", "overall", Severity.BLOCKER, message))
    return findings


def _check_absent_leaks(case: CaseBundle) -> list[PrecheckFinding]:
    """K1: a unit meant to be missing has no matching value anywhere (the generator's leak regex)."""
    joined = "\n".join(note.text for note in case.notes)
    findings: list[PrecheckFinding] = []
    for unit in UNITS.get(case.policy_id, ()):
        if case.states.get(unit.name) != "absent" or not unit.forbidden:
            continue
        match = re.search(unit.forbidden, joined, flags=re.IGNORECASE)
        if match:
            message = f'"{match.group()}" appears but {unit.name} is meant to be missing'
            findings.append(PrecheckFinding(case.id, "K1", unit.name, Severity.BLOCKER, message))
    return findings


def _check_second_values(case: CaseBundle) -> list[PrecheckFinding]:
    """K2: numbers next to a planted value's label that aren't a gold value for that variable.

    A hint for the critic, not proof: "pain for 4 months" can sit next to "pain".
    """
    gold: dict[str, set[float]] = {}
    labels: dict[str, set[str]] = {}
    for item in case.gold_evidence:
        if isinstance(item.value, bool) or not isinstance(item.value, int | float):
            continue
        gold.setdefault(item.variable, set()).add(float(item.value))
        label = _label(item.span_text, float(item.value))
        if label:
            labels.setdefault(item.variable, set()).add(label)
    findings: list[PrecheckFinding] = []
    for variable, names in sorted(labels.items()):
        seen: set[str] = set()
        for note in case.notes:
            for name in sorted(names):
                for number in _numbers_near(note.text, name):
                    if float(number) not in gold[variable] and number not in seen:
                        seen.add(number)
                        message = f'{note.doc_id} has "{name}" with {number}, gold {variable} is {sorted(gold[variable])}'
                        findings.append(PrecheckFinding(case.id, "K2", variable, Severity.MAJOR, message))
    return findings


def _label(span: str, value: float) -> str:
    """The words naming ``value`` in a span: "AHI 22.4 ..." → "AHI", "131 total events" → "total events".

    Empty when the number next to the words isn't the value ("used 4 hours ... 78%").
    """
    before = _LABEL_BEFORE.match(span)
    after = _LABEL_AFTER.match(span)
    if before and float(before.group(2)) == value:
        label = before.group(1).strip()
    elif after and float(after.group(1)) == value:
        label = after.group(2).strip()
    else:
        return ""
    return "" if label.lower() in _FILLER else label


def _numbers_near(text: str, label: str) -> list[str]:
    """Numbers right before or right after ``label`` in ``text``."""
    name = re.escape(label)
    before = re.findall(rf"\b{name}\b[^\d\n.;]{{0,6}}{_NUMBER}", text, flags=re.IGNORECASE)
    after = re.findall(rf"{_NUMBER}\s+{name}\b", text, flags=re.IGNORECASE)
    return before + after


def _check_denial(case: CaseBundle) -> list[PrecheckFinding]:
    """D1: the letter shows every gold_denial field. D2: the reason category fits its template."""
    gold = case.gold_denial
    text = case.denial_text
    flat = " ".join(text.split())
    missing: list[str] = [f"code {code}" for code in gold.codes if code not in text]
    if gold.policy_ref and normalize_ref(gold.policy_ref) not in text.upper():
        missing.append(f"policy {gold.policy_ref}")
    if f"{gold.date:%B} {gold.date.day}, {gold.date.year}" not in text:
        missing.append(f"date {gold.date.isoformat()}")
    if " ".join(gold.reason_text.split()) not in flat:
        missing.append("reason text")
    if " ".join(gold.service.split()) not in flat:
        missing.append("service")
    findings = [
        PrecheckFinding(case.id, "D1", field, Severity.BLOCKER, f"gold_denial {field} is not in the letter")
        for field in missing
    ]
    categories = {category for category, reason in REASONS.values() if reason == gold.reason_text}
    if categories and gold.reason_category not in categories:
        message = f"reason_category {gold.reason_category} but the reason template is {sorted(categories)}"
        findings.append(PrecheckFinding(case.id, "D2", "reason_category", Severity.MAJOR, message))
    elif not categories:
        message = "reason text matches no denial template"
        findings.append(PrecheckFinding(case.id, "D2", "reason_text", Severity.MAJOR, message))
    return findings
