"""Phase 2 core metrics: denial-field accuracy, checklist macro-F1, grounding rate (plan §Phase 2).

Definitions (also printed in RESULTS.md):
- Denial-field accuracy: share of correct fields over all cases, counting six
  ``Denial`` fields plus whether the selected policy is the case's policy.
- Checklist macro-F1: F1 per status (met / unmet / insufficient) over every
  criterion of every case, averaged over the statuses that occur.
- Grounding: share of non-empty extractions that LangExtract aligned to exact
  characters. Blank placeholders for facts the model didn't find are excluded.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pair.contracts import CriterionStatus, Denial, Evidence
from pair.policies.select import normalize_ref

DENIAL_FIELDS: tuple[str, ...] = ("service", "codes", "reason_category", "policy_ref", "plan_type", "date")
TARGETS: dict[str, float] = {"denial_accuracy": 0.90, "macro_f1": 0.85, "grounding": 0.95}
START, END = "<!-- phase2-core:start -->", "<!-- phase2-core:end -->"

StatusPair = tuple[CriterionStatus, CriterionStatus]
"""(gold, predicted)."""


def _plain(text: str) -> str:
    """Lowercase, punctuation stripped, spaces collapsed."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def denial_field_matches(pred: Denial | None, gold: Denial) -> dict[str, bool]:
    """Per-field correctness of a parsed denial; a failed parse gets every field wrong.

    Service matches if either normalized string contains the other; codes as sets;
    policy refs after ``normalize_ref``; the rest exactly.
    """
    if pred is None:
        return dict.fromkeys(DENIAL_FIELDS, False)
    p_service, g_service = _plain(pred.service), _plain(gold.service)
    p_ref = normalize_ref(pred.policy_ref) if pred.policy_ref else None
    g_ref = normalize_ref(gold.policy_ref) if gold.policy_ref else None
    return {
        "service": bool(p_service) and (p_service in g_service or g_service in p_service),
        "codes": {c.upper() for c in pred.codes} == {c.upper() for c in gold.codes},
        "reason_category": pred.reason_category is gold.reason_category,
        "policy_ref": p_ref == g_ref,
        "plan_type": pred.plan_type is gold.plan_type,
        "date": pred.date == gold.date,
    }


def per_class_f1(pairs: Sequence[StatusPair]) -> dict[CriterionStatus, float]:
    """F1 for each status that occurs in gold or predictions."""
    scores: dict[CriterionStatus, float] = {}
    for status in CriterionStatus:
        tp = sum(g is status and p is status for g, p in pairs)
        fp = sum(g is not status and p is status for g, p in pairs)
        fn = sum(g is status and p is not status for g, p in pairs)
        if tp + fp + fn == 0:
            continue
        scores[status] = 2 * tp / (2 * tp + fp + fn)
    return scores


def macro_f1(pairs: Sequence[StatusPair]) -> float | None:
    """Mean of per-status F1, or None with no pairs."""
    scores = per_class_f1(pairs)
    return sum(scores.values()) / len(scores) if scores else None


def span_hits(gold: Sequence[Evidence], pred: Sequence[Evidence]) -> tuple[int, int]:
    """(gold spans overlapped by a prediction for the same doc, criterion and variable, gold spans)."""
    hit = 0
    for g in gold:
        if any(
            p.doc_id == g.doc_id
            and p.criterion_id == g.criterion_id
            and p.variable == g.variable
            and p.char_start < g.char_end
            and g.char_start < p.char_end
            for p in pred
        ):
            hit += 1
    return hit, len(gold)


@dataclass(frozen=True)
class CaseScore:
    """Everything scored for one case (one JSONL row)."""

    case_id: str
    policy_id: str
    case_type: str
    denial_fields: dict[str, bool]
    selected_ok: bool
    statuses: list[tuple[str, CriterionStatus, CriterionStatus]]
    overall_gold: CriterionStatus
    overall_pred: CriterionStatus | None
    n_total: int
    n_dropped: int
    n_empty: int
    gold_spans: int
    gold_spans_hit: int
    seconds: float
    error: str | None
    n_failed_docs: int = 0


@dataclass(frozen=True)
class Summary:
    """Pooled metrics over a set of cases."""

    n_cases: int
    errors: int
    denial_accuracy: float | None
    field_accuracy: dict[str, float]
    macro_f1: float | None
    f1_per_status: dict[CriterionStatus, float]
    f1_by_type: dict[str, float | None]
    grounding: float | None
    span_recall: float | None
    overall_accuracy: float | None
    mean_seconds: float | None
    n_extractions: int
    n_dropped: int
    n_empty: int
    n_failed_docs: int = 0


def summarize(scores: Sequence[CaseScore]) -> Summary:
    """Pool case scores into the headline metrics."""
    fields = [*DENIAL_FIELDS, "selected_policy"]
    field_accuracy: dict[str, float] = {}
    if scores:
        for name in fields:
            values = [s.selected_ok if name == "selected_policy" else s.denial_fields.get(name, False) for s in scores]
            field_accuracy[name] = sum(values) / len(values)
    pairs = [(g, p) for s in scores for _, g, p in s.statuses]
    types = sorted({s.case_type for s in scores})
    total = sum(s.n_total for s in scores)
    dropped = sum(s.n_dropped for s in scores)
    gold_spans = sum(s.gold_spans for s in scores)
    return Summary(
        n_cases=len(scores),
        errors=sum(s.error is not None for s in scores),
        denial_accuracy=_mean(list(field_accuracy.values())),
        field_accuracy=field_accuracy,
        macro_f1=macro_f1(pairs),
        f1_per_status=per_class_f1(pairs),
        f1_by_type={t: macro_f1([(g, p) for s in scores if s.case_type == t for _, g, p in s.statuses]) for t in types},
        grounding=(total - dropped) / total if total else None,
        span_recall=sum(s.gold_spans_hit for s in scores) / gold_spans if gold_spans else None,
        overall_accuracy=_mean([float(s.overall_pred is s.overall_gold) for s in scores]),
        mean_seconds=_mean([s.seconds for s in scores]),
        n_extractions=total,
        n_dropped=dropped,
        n_empty=sum(s.n_empty for s in scores),
        n_failed_docs=sum(s.n_failed_docs for s in scores),
    )


def _mean(values: Sequence[float]) -> float | None:
    """Mean, or None for no values."""
    return sum(values) / len(values) if values else None


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _mark(value: float | None, target: float) -> str:
    return "n/a" if value is None else ("✅" if value >= target else "❌")


def results_markdown(summary: Summary, meta: dict[str, str]) -> str:
    """The RESULTS.md section for a Phase 2 core eval run."""
    t = TARGETS
    rows = [
        f"| Denial-field accuracy | ≥90% | {_pct(summary.denial_accuracy)} | {_mark(summary.denial_accuracy, t['denial_accuracy'])} |",
        f"| Checklist macro-F1 | ≥0.85 | {_num(summary.macro_f1)} | {_mark(summary.macro_f1, t['macro_f1'])} |",
        f"| Grounding (valid char interval) | ≥95% | {_pct(summary.grounding)} | {_mark(summary.grounding, t['grounding'])} |",
    ]  # fmt: skip
    fields = ", ".join(f"{name} {_pct(value)}" for name, value in summary.field_accuracy.items())
    per_status = ", ".join(f"{s.value} {_num(v)}" for s, v in summary.f1_per_status.items())
    by_type = ", ".join(f"{t_} {_num(v)}" for t_, v in summary.f1_by_type.items())
    meta_line = ", ".join(f"{k} `{v}`" for k, v in meta.items())
    return "\n".join(
        [
            "## Phase 2: core engine (steps 1 to 4)",
            "",
            f"Run: {meta_line}. Cases: {summary.n_cases} synthetic ({summary.errors} with errors).",
            "",
            "| Metric | Target | Result | Pass |",
            "|---|---|---|---|",
            *rows,
            "",
            f"- Per field: {fields}.",
            f"- F1 per status: {per_status}. Macro-F1 by case type: {by_type}.",
            f"- Overall verdict accuracy {_pct(summary.overall_accuracy)}; gold-span recall {_pct(summary.span_recall)}.",
            (f"- Extractions: {summary.n_extractions} non-empty, {summary.n_dropped} ungrounded (dropped), "
            f"{summary.n_empty} blank placeholders (excluded); {summary.n_failed_docs} documents failed to parse. "
                f"Mean time per case {_num(summary.mean_seconds)} s."),
            ("- Definitions: denial accuracy pools 6 `Denial` fields + selected policy over all cases; macro-F1 is over "
            "met/unmet/insufficient for every criterion, scored on the case's own checklist; grounding excludes blank "
            "placeholders the model emits for facts it didn't find."),
        ]
    )


def update_results(path: Path, section: str) -> Path:
    """Write ``section`` between the phase-2 markers in RESULTS.md, keeping everything else."""
    block = f"{START}\n{section}\n{END}"
    text = path.read_text(encoding="utf-8") if path.exists() else "# PAIR results\n\nAll numbers come from logged runs.\n"
    if START in text and END in text:
        before, rest = text.split(START, 1)
        after = rest.split(END, 1)[1]
        text = before + block + after
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")
    return path
