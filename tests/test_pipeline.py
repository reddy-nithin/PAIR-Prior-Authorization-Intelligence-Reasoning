"""The core pipeline (steps 1 to 4) on the fixture case with fake LLM + LangExtract (T11)."""

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
from langextract import data as lx_data

from pair.contracts import CriterionStatus
from pair.eval.cases import load_case
from pair.llm import LLMConfig
from pair.pipeline import load_resources, run_core
from tests.conftest import REPO_ROOT
from tests.fakes import FakeLLM

CASE = load_case(REPO_ROOT / "tests" / "fixtures" / "cases" / "pap-osa-fixture.json")
RESOURCES = load_resources(REPO_ROOT / "policies")


def gold_extract(**kwargs: Any) -> Any:
    """A fake LangExtract that returns the case's gold evidence for the document it is given."""
    text = kwargs["text_or_documents"]
    doc_id = next(note.doc_id for note in CASE.notes if note.text == text)
    seen: set[tuple[str, int]] = set()
    extractions = []
    for item in CASE.gold_evidence:
        if item.doc_id != doc_id or (item.variable, item.char_start) in seen:
            continue
        seen.add((item.variable, item.char_start))
        attributes: dict[str, str | list[str]] = {"status": item.status.value}
        if isinstance(item.value, dt.date):
            attributes["value"] = item.value.isoformat()
        elif isinstance(item.value, (str, list)):
            attributes["value"] = item.value
        elif item.value is not None:
            attributes["value"] = str(item.value)
        extractions.append(
            lx_data.Extraction(
                item.variable,
                item.span_text,
                char_interval=lx_data.CharInterval(start_pos=item.char_start, end_pos=item.char_end),
                attributes=attributes,
            )
        )
    extractions.append(lx_data.Extraction("ahi", "", char_interval=None))
    return SimpleNamespace(extractions=extractions)


def denial_reply() -> dict[str, Any]:
    """The gold denial as the LLM would return it."""
    return CASE.gold_denial.model_dump(mode="json")


def test_core_reproduces_gold_with_a_perfect_reader() -> None:
    """With perfect denial parsing and extraction, the verdict equals the gold labels."""
    run = run_core(
        CASE.denial_text, CASE.record_text(), RESOURCES, FakeLLM([denial_reply()]), LLMConfig.from_env({}),
        context=CASE.context, extract_fn=gold_extract,
    )  # fmt: skip
    assert run.denial is not None
    assert run.denial.denial == CASE.gold_denial
    assert run.selection.policy_id == "pap-osa"
    assert run.verdict is not None
    assert {r.criterion_id: r.status for r in run.verdict.results} == CASE.gold_statuses
    assert run.verdict.overall is CASE.gold_overall
    assert run.verdict.gaps
    assert run.grounding == (sum(len({(e.variable, e.char_start) for e in CASE.gold_evidence if e.doc_id == d})
                                 for d in ("clinic", "report")), 0, 2)


def test_unsupported_denial_stops_before_extraction() -> None:
    """A denial for an unmodeled service gives no verdict and makes no extraction call."""
    reply = {**denial_reply(), "codes": ["L1832"], "policy_ref": None, "service": "Knee brace"}
    calls: list[Any] = []
    run = run_core(
        "letter", CASE.record_text(), RESOURCES, FakeLLM([reply]), LLMConfig.from_env({}),
        extract_fn=lambda **k: calls.append(k),
    )  # fmt: skip
    assert run.selection.policy_id is None
    assert run.verdict is None
    assert calls == []


def test_policy_override_evaluates_even_when_parsing_fails() -> None:
    """The eval can force the gold policy so extraction is scored even if the denial parse fails."""
    run = run_core(
        CASE.denial_text, CASE.record_text(), RESOURCES, FakeLLM(["bad", "bad"]), LLMConfig.from_env({}),
        context=CASE.context, extract_fn=gold_extract, policy_override="pap-osa",
    )  # fmt: skip
    assert run.denial is None
    assert run.denial_error is not None
    assert run.selection.policy_id is None
    assert run.verdict is not None
    assert run.verdict.policy_id == "pap-osa"


def test_unknown_override_raises() -> None:
    """Overriding with a policy PAIR doesn't model is an error."""
    with pytest.raises(KeyError):
        run_core(
            "x", {}, RESOURCES, FakeLLM([denial_reply()]), LLMConfig.from_env({}),
            extract_fn=gold_extract, policy_override="knee-brace",
        )  # fmt: skip


def test_missing_overall_is_reported_per_status() -> None:
    """The overall outcome is one of the three statuses."""
    run = run_core(
        CASE.denial_text, CASE.record_text(), RESOURCES, FakeLLM([denial_reply()]), LLMConfig.from_env({}),
        context=CASE.context, extract_fn=gold_extract,
    )  # fmt: skip
    assert run.verdict is not None
    assert run.verdict.overall in set(CriterionStatus)
    assert run.seconds >= 0
