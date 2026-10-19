"""Metric math on toy inputs (T11)."""

import datetime as dt
from pathlib import Path

import pytest

from pair.contracts import CriterionStatus, Denial, Evidence, EvidenceStatus
from pair.eval.metrics import (
    DENIAL_FIELDS,
    CaseScore,
    denial_field_matches,
    macro_f1,
    per_class_f1,
    results_markdown,
    span_hits,
    summarize,
    update_results,
)
from tests.contracts.factories import valid_denial

M, U, I = CriterionStatus.MET, CriterionStatus.UNMET, CriterionStatus.INSUFFICIENT


def test_denial_fields_exact_and_lenient() -> None:
    """Service matches leniently; refs are normalized; other fields are exact."""
    gold = Denial(**valid_denial())
    pred = gold.model_copy(update={"service": "cpap device.", "policy_ref": "LCD L33718", "codes": ["E0601"]})
    matches = denial_field_matches(pred, gold)
    assert matches == {
        "service": True, "codes": True, "reason_category": True, "policy_ref": True, "plan_type": True, "date": True,
    }  # fmt: skip
    wrong = gold.model_copy(update={"date": dt.date(2020, 1, 1), "service": "wheelchair", "policy_ref": None})
    assert denial_field_matches(wrong, gold) == {
        "service": False, "codes": True, "reason_category": True, "policy_ref": False, "plan_type": True, "date": False,
    }  # fmt: skip
    assert set(denial_field_matches(None, gold).values()) == {False}


def test_none_refs_match() -> None:
    """A letter with no citation parsed as None is correct."""
    gold = Denial(**{**valid_denial(), "policy_ref": None})
    assert denial_field_matches(gold, gold)["policy_ref"] is True


def test_macro_f1_hand_computed() -> None:
    """F1 per class, averaged over classes present in gold or predictions."""
    pairs = [(M, M), (M, M), (M, I), (U, U), (I, I), (I, M)]
    per = per_class_f1(pairs)
    assert per[M] == pytest.approx(2 / 3)  # tp 2, fp 1, fn 1
    assert per[U] == pytest.approx(1.0)
    assert per[I] == pytest.approx(0.5)  # tp 1, fp 1, fn 1
    assert macro_f1(pairs) == pytest.approx((2 / 3 + 1.0 + 0.5) / 3)


def test_macro_f1_skips_absent_classes_and_handles_empty() -> None:
    """A class in neither gold nor predictions doesn't count; no pairs gives None."""
    assert macro_f1([(M, M)]) == 1.0
    assert macro_f1([]) is None


def ev(doc: str, start: int, end: int, criterion: str = "ahi_threshold", variable: str = "ahi") -> Evidence:
    """Toy evidence."""
    return Evidence(criterion_id=criterion, variable=variable, value=1, span_text="x" * (end - start),
                    char_start=start, char_end=end, doc_id=doc, status=EvidenceStatus.ASSERTED)  # fmt: skip


def test_span_hits_need_overlap_on_the_same_doc_criterion_and_variable() -> None:
    """A gold span is found if any prediction overlaps it for the same doc, criterion and variable."""
    gold = [ev("n", 10, 20), ev("n", 30, 40), ev("m", 0, 5), ev("n", 50, 60, variable="event_count")]
    pred = [ev("n", 15, 25), ev("m", 5, 9), ev("n", 50, 60)]
    assert span_hits(gold, pred) == (1, 4)


def score(case_id: str, pairs: list[tuple[CriterionStatus, CriterionStatus]], **kw: object) -> CaseScore:
    """A toy case score."""
    base = {
        "case_id": case_id, "policy_id": "pap-osa", "case_type": "A",
        "denial_fields": dict.fromkeys(DENIAL_FIELDS, True), "selected_ok": True,
        "statuses": [(f"c{i}", g, p) for i, (g, p) in enumerate(pairs)],
        "overall_gold": M, "overall_pred": M, "n_total": 4, "n_dropped": 1, "n_empty": 2,
        "gold_spans": 3, "gold_spans_hit": 2, "seconds": 2.0, "error": None,
    }  # fmt: skip
    base.update(kw)
    return CaseScore(**base)  # type: ignore[arg-type]


def test_summarize_pools_cases() -> None:
    """Denial accuracy counts fields plus selection; grounding pools extraction counts."""
    scores = [
        score("a", [(M, M), (U, U)]),
        score("b", [(I, M)], denial_fields={**dict.fromkeys(DENIAL_FIELDS, True), "service": False}, selected_ok=False,
              overall_pred=U, n_total=6, n_dropped=0),
    ]  # fmt: skip
    summary = summarize(scores)
    assert summary.n_cases == 2
    assert summary.denial_accuracy == pytest.approx(12 / 14)
    assert summary.field_accuracy["selected_policy"] == 0.5
    assert summary.field_accuracy["service"] == 0.5
    assert summary.grounding == pytest.approx(9 / 10)
    assert summary.overall_accuracy == 0.5
    assert summary.span_recall == pytest.approx(4 / 6)
    assert summary.macro_f1 == pytest.approx(macro_f1([(M, M), (U, U), (I, M)]))
    assert set(summary.f1_by_type) == {"A"}
    assert summary.mean_seconds == 2.0
    assert summary.errors == 0


def test_summarize_empty_and_no_extractions() -> None:
    """No cases or no extractions give None metrics, not a crash."""
    empty = summarize([])
    assert empty.denial_accuracy is None
    assert empty.grounding is None
    none = summarize([score("a", [], n_total=0, n_dropped=0, gold_spans=0, gold_spans_hit=0)])
    assert none.grounding is None
    assert none.span_recall is None


def test_results_markdown_shows_targets_and_pass_marks() -> None:
    """The RESULTS section lists each headline metric with its target and pass/fail."""
    summary = summarize([score("a", [(M, M), (U, U)])])
    text = results_markdown(summary, {"backend": "ollama", "model": "gemma4:e4b", "config_hash": "abc"})
    assert "Denial-field accuracy" in text and "≥90%" in text
    assert "Checklist macro-F1" in text and "≥0.85" in text
    assert "Grounding" in text and "≥95%" in text
    assert "gemma4:e4b" in text
    assert "✅" in text or "❌" in text


def test_update_results_replaces_only_its_section(tmp_path: Path) -> None:
    """The phase-2 section is replaced in place; other content is kept."""
    path = tmp_path / "RESULTS.md"
    update_results(path, "first")
    assert "first" in path.read_text()
    path.write_text(path.read_text() + "\n## Later section\nkeep me\n")
    update_results(path, "second")
    text = path.read_text()
    assert "second" in text and "first" not in text and "keep me" in text


def test_failed_documents_are_counted_and_reported() -> None:
    """Documents whose model output couldn't be parsed show up in the summary and RESULTS."""
    summary = summarize([score("a", [(M, M)], n_failed_docs=2), score("b", [(M, M)])])
    assert summary.n_failed_docs == 2
    assert "2 documents failed to parse" in results_markdown(summary, {"model": "m"})
