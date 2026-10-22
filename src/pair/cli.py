"""Command line: ``pair run <case>``, ``pair eval-core`` (Phase 2 exit check) and ``pair audit precheck``."""

import argparse
import dataclasses
import datetime as dt
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import langextract as lx

from pair.audit_cli import add_audit_parser, run_audit
from pair.contracts import CriterionStatus
from pair.eval.cases import CaseBundle, CaseLoadError, load_case
from pair.eval.metrics import (
    CaseScore,
    denial_field_matches,
    results_markdown,
    span_hits,
    summarize,
    update_results,
)
from pair.extract.runner import ExtractFn
from pair.llm import (
    Backend,
    LLMClient,
    LLMConfig,
    LLMConfigError,
    LLMError,
    make_client,
)
from pair.pipeline import CoreRun, Resources, load_resources, run_core

logger = logging.getLogger("pair")

POLICIES_DIR = Path("policies")
CASES_DIR = Path("data/cases")
RUNS_DIR = Path("data/runs")
RESULTS_PATH = Path("RESULTS.md")
_BOOLS: dict[str, bool | None] = {"true": True, "false": False, "none": None}

EXIT_OK, EXIT_ERROR, EXIT_PARSE, EXIT_UNSUPPORTED = 0, 1, 2, 3


def _context_flag(text: str) -> tuple[str, bool | None]:
    """Parse ``name=true|false|none`` for ``--context``."""
    name, sep, value = text.partition("=")
    if not sep or value.lower() not in _BOOLS:
        raise argparse.ArgumentTypeError(f"expected name=true|false|none, got {text!r}")
    return name.strip(), _BOOLS[value.lower()]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pair", description="PAIR appeal copilot, core engine")
    parser.add_argument("--backend", choices=[b.value for b in Backend], help="override PAIR_LLM_BACKEND")
    parser.add_argument("--policies", type=Path, default=POLICIES_DIR)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="parse a case's denial, select the policy, extract evidence, print the verdict")
    run.add_argument("case", type=Path, help="case bundle JSON (only its denial text and notes are used)")
    run.add_argument("--context", type=_context_flag, action="append", default=[], help="flag=true|false|none")
    ev = sub.add_parser("eval-core", help="score steps 1 to 4 on every case and update RESULTS.md")
    ev.add_argument("--cases", type=Path, default=CASES_DIR)
    ev.add_argument("--results", type=Path, default=RESULTS_PATH)
    ev.add_argument("--runs", type=Path, default=RUNS_DIR)
    add_audit_parser(sub)
    return parser


def main(
    argv: Sequence[str] | None = None,
    client: LLMClient | None = None,
    extract_fn: ExtractFn | None = None,
) -> int:
    """Entry point. ``client``/``extract_fn`` are injectable for tests. Returns an exit code."""
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    if args.command == "audit":
        return run_audit(args)
    try:
        env = {**os.environ, **({"PAIR_LLM_BACKEND": args.backend} if args.backend else {})}
        config = LLMConfig.from_env(env)
    except LLMConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    resources = load_resources(args.policies)
    llm = client or make_client(config)
    extractor = extract_fn or lx.extract
    if args.command == "run":
        return _run(args, resources, llm, config, extractor)
    return _eval_core(args, resources, llm, config, extractor)


def _run(args: argparse.Namespace, resources: Resources, client: LLMClient, config: LLMConfig, extract_fn: ExtractFn) -> int:
    """``pair run``: steps 1 to 4 on one case, printed for a person."""
    try:
        case = load_case(args.case)
    except CaseLoadError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    context = {**case.context, **dict(args.context)}
    try:
        run = run_core(case.denial_text, case.record_text(), resources, client, config, context, extract_fn)
    except LLMError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    if run.denial is None:
        print(f"error: {run.denial_error}", file=sys.stderr)
        return EXIT_PARSE
    print(_render(case, run, context, config))
    return EXIT_OK if run.verdict is not None else EXIT_UNSUPPORTED


def _render(case: CaseBundle, run: CoreRun, context: dict[str, bool | None], config: LLMConfig) -> str:
    """Human-readable output for ``pair run``."""
    assert run.denial is not None
    d = run.denial.denial
    lines = [
        f"Case {case.id} (synthetic) · backend {config.backend.value} {config.model} · {run.seconds:.1f} s",
        (f"Denial: {d.service} | codes {', '.join(d.codes) or 'none'} | {d.reason_category.value} | "
        f"policy {d.policy_ref or 'not cited'} | {d.date.isoformat()} (parsed in {run.denial.attempts} attempt(s))"),
        f"  reason: {d.reason_text}",
    ]
    if run.verdict is None:
        lines.append(f"Policy: none, {run.selection.reason}")
        return "\n".join(lines)
    lines += [
        f"Policy: {run.verdict.policy_id} ({run.selection.reason})",
        f"  context: {', '.join(f'{k}={v}' for k, v in context.items()) or 'none'}",
        f"Overall: {run.verdict.overall.value.upper()}",
        "",
        f"{'Criterion':<34} Status",
    ]
    for result in run.verdict.results:
        lines.append(f"{result.criterion_id:<34} {_icon(result.status)} {result.status.value}")
        lines.extend(f"    {line}" for line in result.trace.splitlines())
    lines += ["", "Gaps (what's missing or not met):"]
    lines += [f"  - {gap.criterion_id}: {gap.message}" for gap in run.verdict.gaps] or ["  none"]
    total, dropped, empty = run.grounding
    lines.append(f"Grounding: {total - dropped}/{total} extractions grounded ({empty} blank placeholders ignored)")
    if run.failed_docs:
        lines.append(f"Warning: {run.failed_docs} document(s) could not be read by the extractor; their facts are missing")
    return "\n".join(lines)


def _icon(status: CriterionStatus) -> str:
    """Status shown by symbol and text, not color alone."""
    return {CriterionStatus.MET: "✓", CriterionStatus.UNMET: "✗", CriterionStatus.INSUFFICIENT: "?"}[status]


def _eval_core(
    args: argparse.Namespace, resources: Resources, client: LLMClient, config: LLMConfig, extract_fn: ExtractFn
) -> int:
    """``pair eval-core``: score every case, log JSONL, update RESULTS.md."""
    paths = sorted(args.cases.glob("*/*.json"))
    if not paths:
        print(f"error: no cases under {args.cases} (run `make cases`)", file=sys.stderr)
        return EXIT_ERROR
    host = config.ollama_url if config.backend is Backend.OLLAMA else f"vertex:{config.gcp_project}/{config.gcp_location}"
    meta = {
        "backend": config.backend.value,
        "model": config.model,
        "host": host,
        "config_hash": config.config_hash(),
        "date": dt.date.today().isoformat(),
    }
    scores = [_score(load_case(path), resources, client, config, extract_fn) for path in paths]
    args.runs.mkdir(parents=True, exist_ok=True)
    log = args.runs / f"eval-core-{dt.datetime.now():%Y%m%d-%H%M%S}-{meta['config_hash']}.jsonl"
    with log.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": "meta", **meta, "n_cases": len(scores)}) + "\n")
        for score in scores:
            handle.write(json.dumps({"kind": "case", **dataclasses.asdict(score)}, default=str) + "\n")
    good = [s for s in scores if s.error is None]
    summary = summarize(good)
    update_results(args.results, results_markdown(summary, {**meta, "log": str(log)}))
    print(
        f"{summary.n_cases} cases scored ({len(scores) - len(good)} errors) · denial accuracy "
        f"{_fmt(summary.denial_accuracy)} · macro-F1 {_fmt(summary.macro_f1, pct=False)} · grounding "
        f"{_fmt(summary.grounding)} · log {log}"
    )
    return EXIT_OK


def _fmt(value: float | None, pct: bool = True) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}" if pct else f"{value:.2f}"


def _score(case: CaseBundle, resources: Resources, client: LLMClient, config: LLMConfig, extract_fn: ExtractFn) -> CaseScore:
    """Run and score one case; an LLM failure becomes an error row."""
    base: dict[str, Any] = {
        "case_id": case.id,
        "policy_id": case.policy_id,
        "case_type": case.case_type.value,
        "overall_gold": case.gold_overall,
    }
    try:
        run = run_core(
            case.denial_text, case.record_text(), resources, client, config, case.context, extract_fn,
            policy_override=case.policy_id,
        )  # fmt: skip
    except LLMError as error:
        logger.error("%s: %s", case.id, error)
        return CaseScore(
            **base, denial_fields={}, selected_ok=False, statuses=[], overall_pred=None, n_total=0, n_dropped=0,
            n_empty=0, gold_spans=len(case.gold_evidence), gold_spans_hit=0, seconds=0.0, error=str(error),
        )  # fmt: skip
    assert run.verdict is not None
    predicted = {r.criterion_id: r.status for r in run.verdict.results}
    total, dropped, empty = run.grounding
    hit, n_gold = span_hits(case.gold_evidence, run.evidence)
    return CaseScore(
        **base,
        denial_fields=denial_field_matches(run.denial.denial if run.denial else None, case.gold_denial),
        selected_ok=run.selection.policy_id == case.policy_id,
        statuses=[(cid, gold, predicted[cid]) for cid, gold in case.gold_statuses.items()],
        overall_pred=run.verdict.overall,
        n_total=total,
        n_dropped=dropped,
        n_empty=empty,
        gold_spans=n_gold,
        gold_spans_hit=hit,
        seconds=run.seconds,
        error=None,
        n_failed_docs=run.failed_docs,
    )


def entry() -> None:
    """Console-script entry point."""
    sys.exit(main())
