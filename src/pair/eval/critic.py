"""Critic agent I/O: policy text for the critic, verdict validation, and seeded-fault scoring (ADR-0013).

The critic (``.claude/agents/pair-critic.md``) writes JSONL verdicts in the
format of ``docs/audit/critic-rubric.md``. Nothing it says is trusted until
its quotes are checked against the documents here.
"""

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pair.contracts import Checklist
from pair.eval.audit import PrecheckFinding
from pair.eval.cases import CaseBundle
from pair.policies.mcd import MCDExport, normalize_whitespace

logger = logging.getLogger(__name__)

VERDICTS = frozenset({"pass", "fail", "uncertain"})
SEVERITIES = frozenset({"blocker", "major", "minor"})


class CriticOutputError(ValueError):
    """A critic output file is missing or not JSONL."""


@dataclass(frozen=True)
class Verdict:
    """One validated critic verdict.

    Attributes:
        case_id: Case (or ``policy:<id>``) the verdict is about.
        check_id: Rubric check id, or ``SUMMARY``.
        target: Criterion or field, if given.
        verdict: pass, fail or uncertain, after validation.
        severity: blocker, major or minor.
        reasoning: The critic's reasoning.
        quotes: The quotes, all verified verbatim.
        coerced: True if a quote-less pass was turned into a fail (rubric rule).
    """

    case_id: str
    check_id: str
    target: str
    verdict: str
    severity: str
    reasoning: str
    quotes: tuple[dict[str, str], ...] = ()
    coerced: bool = False


@dataclass
class ValidatedOutput:
    """A critic output file after validation."""

    verdicts: list[Verdict] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    """Why each dropped line was dropped (bad JSON, unknown field value, non-verbatim quote)."""


def policy_text(checklist: Checklist, export: MCDExport) -> str:
    """All source documents of a policy as plain text, for the critic to read and quote."""
    parts: list[str] = []
    for source in checklist.sources:
        doc = export.find_ncd(source.id) if source.type == "NCD" else export.find_lcd(source.id)
        parts.append(f"=== {doc.kind} {doc.id} v{doc.version}: {doc.title}\n{doc.url}\n")
        parts.extend(f"--- {name}\n{text}\n" for name, text in doc.sections.items())
    return "\n".join(parts)


def case_documents(case: CaseBundle, checklist: Checklist, lcd_text: str) -> dict[str, str]:
    """Every document a case-mode quote may cite, by the doc ids the agent file names."""
    docs = {note.doc_id: note.text for note in case.notes}
    docs["denial"] = case.denial_text
    docs["lcd"] = lcd_text
    docs.update({f"policy:{c.id}": c.clause for c in checklist.criteria})
    return docs


def validate_output(path: Path, documents: Mapping[str, str]) -> ValidatedOutput:
    """Read a critic JSONL file and keep only verdicts whose quotes are verbatim.

    A pass with no quote becomes a fail with ``coerced=True`` (rubric: a pass needs a quote).

    Raises:
        CriticOutputError: If the file doesn't exist.
    """
    if not path.exists():
        raise CriticOutputError(f"no critic output at {path}")
    normalized = {doc_id: normalize_whitespace(text) for doc_id, text in documents.items()}
    out = ValidatedOutput()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            out.rejected.append(f"line {number}: not JSON ({error})")
            continue
        problem = _row_problem(row, normalized)
        if problem:
            out.rejected.append(f"line {number}: {problem}")
            continue
        out.verdicts.append(_to_verdict(row))
    if out.rejected:
        logger.warning("%s: %d critic lines rejected", path, len(out.rejected))
    return out


def _row_problem(row: Any, documents: Mapping[str, str]) -> str:
    """Why a verdict row is invalid, or an empty string."""
    if not isinstance(row, dict):
        return "not an object"
    if row.get("verdict") not in VERDICTS or row.get("severity") not in SEVERITIES:
        return f"bad verdict/severity {row.get('verdict')!r}/{row.get('severity')!r}"
    if not isinstance(row.get("check_id"), str) or not isinstance(row.get("quotes", []), list):
        return "missing check_id or quotes list"
    for quote in row.get("quotes", []):
        if not isinstance(quote, dict):
            return "quote is not an object"
        doc = documents.get(str(quote.get("doc_id")))
        text = normalize_whitespace(str(quote.get("text", "")))
        if doc is None:
            return f"quote cites unknown doc {quote.get('doc_id')!r}"
        if not text or text not in doc:
            return f"quote not verbatim in {quote.get('doc_id')}: {text[:60]!r}"
    return ""


def _to_verdict(row: dict[str, Any]) -> Verdict:
    """A validated row as a ``Verdict``, applying the quote-less-pass rule."""
    quotes = tuple({"doc_id": str(q["doc_id"]), "text": str(q["text"])} for q in row.get("quotes", []))
    coerced = row["verdict"] == "pass" and not quotes and row["check_id"] != "SUMMARY"
    return Verdict(
        case_id=str(row.get("case_id", "")),
        check_id=row["check_id"],
        target=str(row.get("target", "")),
        verdict="fail" if coerced else row["verdict"],
        severity=row["severity"],
        reasoning=str(row.get("reasoning", "")),
        quotes=quotes,
        coerced=coerced,
    )


@dataclass(frozen=True)
class SeedScore:
    """Seeded-fault results (critic plan Step 6 targets: ≥90% blocker catch, ≤10% clean false blockers)."""

    n_faults: int
    caught: int
    n_blocker_faults: int
    blocker_caught: int
    n_clean: int
    clean_false_blockers: int
    by_kind: dict[str, tuple[int, int]]
    """Per fault kind: (caught, total)."""
    misses: list[str]
    false_alarms: list[str]
    coerced: int
    rejected_lines: int

    @property
    def blocker_catch_rate(self) -> float:
        """Share of blocker faults caught."""
        return self.blocker_caught / self.n_blocker_faults if self.n_blocker_faults else 0.0

    @property
    def catch_rate(self) -> float:
        """Share of all faults caught."""
        return self.caught / self.n_faults if self.n_faults else 0.0

    @property
    def false_blocker_rate(self) -> float:
        """Share of clean twins flagged with any blocker fail."""
        return self.clean_false_blockers / self.n_clean if self.n_clean else 0.0


def score_seeded(
    key: Sequence[Mapping[str, Any]],
    outputs: Mapping[str, ValidatedOutput],
    precheck: Sequence[PrecheckFinding],
) -> SeedScore:
    """Score critic + precheck against the hidden key.

    A fault is caught when a ``fail`` verdict (not coerced) or a precheck finding
    has one of the fault's expected check ids. ``uncertain`` doesn't count. A clean
    twin is a false alarm when it gets any blocker ``fail`` (critic or precheck).

    Args:
        key: Key entries: ``seed_id`` plus ``fault`` (None for a clean twin) with ``kind``, ``expected``, ``severity``.
        outputs: Validated critic output per seed id (a missing id counts as no flags).
        precheck: Precheck findings on the seeded cases.
    """
    pre_ids: dict[str, set[str]] = {}
    pre_block: set[str] = set()
    for finding in precheck:
        pre_ids.setdefault(finding.case_id, set()).add(finding.check_id)
        if finding.severity.value == "blocker":
            pre_block.add(finding.case_id)
    by_kind: dict[str, list[int]] = {}
    misses: list[str] = []
    false_alarms: list[str] = []
    n_faults = caught = n_block = block_caught = n_clean = clean_false = 0
    for entry in key:
        seed_id = entry["seed_id"]
        output = outputs.get(seed_id, ValidatedOutput())
        fails = [v for v in output.verdicts if v.verdict == "fail" and not v.coerced and v.check_id != "SUMMARY"]
        flagged = {v.check_id for v in fails} | pre_ids.get(seed_id, set())
        fault = entry.get("fault")
        if fault is None:
            n_clean += 1
            if seed_id in pre_block or any(v.severity == "blocker" for v in fails):
                clean_false += 1
                false_alarms.append(seed_id)
            continue
        hit = bool(flagged & set(fault["expected"]))
        n_faults += 1
        caught += hit
        tally = by_kind.setdefault(fault["kind"], [0, 0])
        tally[0] += hit
        tally[1] += 1
        if fault["severity"] == "blocker":
            n_block += 1
            block_caught += hit
        if not hit:
            misses.append(f"{seed_id} {fault['kind']} ({fault['target']})")
    return SeedScore(
        n_faults=n_faults,
        caught=caught,
        n_blocker_faults=n_block,
        blocker_caught=block_caught,
        n_clean=n_clean,
        clean_false_blockers=clean_false,
        by_kind={kind: (c, t) for kind, (c, t) in sorted(by_kind.items())},
        misses=misses,
        false_alarms=false_alarms,
        coerced=sum(v.coerced for o in outputs.values() for v in o.verdicts),
        rejected_lines=sum(len(o.rejected) for o in outputs.values()),
    )
