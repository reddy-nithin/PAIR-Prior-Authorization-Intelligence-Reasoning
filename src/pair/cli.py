"""Command line: ``pair run <case>``, ``pair eval-core`` (Phase 2 exit check), ``pair audit precheck`` and the Phase 3 commands (``trust_cli``)."""

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
from pair.draft.template import load_letter_template
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
from pair.pipeline import (
    CoreRun,
    Resources,
    TrustRun,
    load_resources,
    run_core,
    run_trust,
)
from pair.score.base_model import BaseModelError, load_base_model
from pair.score.strength import IMR_NOTE, load_adjustments, load_ship_links
from pair.trust_cli import (
    IMR_MODEL,
    TEMPLATE,
    THRESHOLDS,
    TRUST_COMMANDS,
    add_trust_parsers,
    case_flags,
    run_trust_command,
)
from pair.verify.conformal import ThresholdBook
from pair.verify.nli import Verifier, VerifierConfig, VerifierConfigError, make_verifier

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
    run.add_argument("--trust", action="store_true", help="also draft, verify and score the letter (steps 5 to 7)")
    run.add_argument("--imr-model", type=Path, default=IMR_MODEL)
    run.add_argument("--thresholds", type=Path, default=THRESHOLDS)
    ev = sub.add_parser("eval-core", help="score steps 1 to 4 on every case and update RESULTS.md")
    ev.add_argument("--cases", type=Path, default=CASES_DIR)
    ev.add_argument("--results", type=Path, default=RESULTS_PATH)
    ev.add_argument("--runs", type=Path, default=RUNS_DIR)
    add_audit_parser(sub)
    add_trust_parsers(sub, RUNS_DIR, RESULTS_PATH)
    return parser


def main(
    argv: Sequence[str] | None = None,
    client: LLMClient | None = None,
    extract_fn: ExtractFn | None = None,
    verifier: Verifier | None = None,
) -> int:
    """Entry point. ``client``/``extract_fn``/``verifier`` are injectable for tests. Returns an exit code."""
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
    if verifier is None and (args.command == "draft-claims" or getattr(args, "trust", False)):
        try:
            verifier = make_verifier(VerifierConfig.from_env())
        except VerifierConfigError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_ERROR
    if args.command in TRUST_COMMANDS:
        return run_trust_command(args, resources, llm, config, extractor, verifier)
    if args.command == "run":
        return _run(args, resources, llm, config, extractor, verifier)
    return _eval_core(args, resources, llm, config, extractor)


def _run(
    args: argparse.Namespace,
    resources: Resources,
    client: LLMClient,
    config: LLMConfig,
    extract_fn: ExtractFn,
    verifier: Verifier | None = None,
) -> int:
    """``pair run``: steps 1 to 4 on one case (and 5 to 7 with ``--trust``), printed for a person."""
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
    if args.trust and run.verdict is not None:
        assert verifier is not None
        try:
            print(_trust_section(args, case, run, resources, client, config, verifier))
        except LLMError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_ERROR
    return EXIT_OK if run.verdict is not None else EXIT_UNSUPPORTED


def _trust_section(
    args: argparse.Namespace,
    case: CaseBundle,
    run: CoreRun,
    resources: Resources,
    client: LLMClient,
    config: LLMConfig,
    verifier: Verifier,
) -> str:
    """Steps 5 to 7 for ``pair run --trust``: the letter, what was kept out of it, and the strength."""
    assert run.verdict is not None
    checklist = resources.checklists[run.verdict.policy_id]
    info = verifier.describe()
    threshold = ThresholdBook.load(args.thresholds).lookup(config.model, info["verifier_backend"], info["verifier_model"])
    note = None
    base = None
    try:
        base = load_base_model(args.imr_model).estimate(checklist.id)
    except (BaseModelError, KeyError) as error:
        note = str(error)
    trust = run_trust(
        run, case.record_text(), checklist, client, verifier, threshold, config.model,
        load_letter_template(TEMPLATE), case_flags(case, dict(args.context)), base,
        load_adjustments(Path(__file__).parent / "score" / "adjustments.yaml"),
    )  # fmt: skip
    return _render_trust(trust, note, args.policies)


def _render_trust(trust: TrustRun, note: str | None, policies: Path) -> str:
    """The letter, the claims kept out of it, and the strength or "get a human"."""
    meta = trust.verified.metadata
    lines = ["", (f"Letter (drafter {meta['drafter']}, verifier {meta['verifier_backend']} {meta['verifier_model']}, "
             f"threshold {meta['threshold']})"), "", trust.rendered.text, ""]
    if trust.rendered.unconfirmed:
        lines.append("Statements PAIR couldn't confirm (removed from the letter; check them against your records):")
        lines += [f"  ⚑ {claim.text}" for claim in trust.rendered.unconfirmed]
    if trust.rendered.not_evaluated:
        lines.append(f"{len(trust.rendered.not_evaluated)} statement(s) in the letter are not evaluated: no "
                     "calibrated threshold exists for this drafter and verifier.")
    lines += [f"Not argued: {s.criterion_id} ({s.status.value}): {s.message}" for s in trust.plan.skipped]
    strength = trust.strength
    if strength is None:
        lines.append(f"Strength: not available ({note})")
    elif strength.abstain:
        lines.append(f"Get a human: {strength.abstain_reason}")
        lines += [f"  {link.name}: {link.url}" for link in load_ship_links(policies / "_ship.yaml")]
    else:
        lines.append(f"Strength: {strength.p:.0%} (range {strength.interval.low:.0%} to {strength.interval.high:.0%}), "
                     f"from a base rate of {strength.explanation.base_rate:.0%} over "
                     f"{strength.explanation.n_similar} similar reviews")
        lines += [f"  {s.criterion_id}: {s.status.value} (odds x{s.shift})" for s in strength.explanation.steps]
        lines += [f"  What helps: {i.action} (to about {i.p_if_fixed:.0%})" for i in strength.explanation.improve]
    lines.append(IMR_NOTE)
    return "\n".join(lines)


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
