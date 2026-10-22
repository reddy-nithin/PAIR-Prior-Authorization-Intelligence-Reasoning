"""``pair audit ...``: precheck, seeded-fault set, critic scoring (ADR-0013). No LLM is called here."""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from pair.eval.audit import (
    PrecheckFinding,
    Severity,
    check_policy_sources,
    precheck_paths,
)
from pair.eval.cases import load_case, save_case
from pair.eval.critic import (
    CriticOutputError,
    ValidatedOutput,
    case_documents,
    policy_text,
    score_seeded,
    validate_output,
)
from pair.eval.faults import DEFAULT_MIX, SeedingError, seed_suite
from pair.eval.metrics import update_results
from pair.policies.loader import load_all
from pair.policies.mcd import MCDDocumentNotFound, MCDExport

CASES_DIR = Path("data/cases")
AUDIT_DIR = Path("data/audit")
MCD_DIR = Path("data/raw/mcd")
EXIT_OK, EXIT_ERROR = 0, 1


def add_audit_parser(sub: Any) -> None:
    """Register ``pair audit`` and its subcommands on the top-level subparsers."""
    audit = sub.add_parser("audit", help="audit synthetic cases and policies (ADR-0013)")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    pre = audit_sub.add_parser("precheck", help="mechanical checks on every case and policy clause, logged as JSONL")
    pre.add_argument("--cases", type=Path, default=CASES_DIR)
    pre.add_argument("--out", type=Path, default=AUDIT_DIR)
    pre.add_argument("--mcd", type=Path, default=MCD_DIR, help="MCD export folder for the clause check")
    pre.add_argument("--no-mcd", action="store_true", help="skip the policy clause check")
    lcd = audit_sub.add_parser("policy-text", help="write each policy's MCD source text for the critic to quote")
    lcd.add_argument("--mcd", type=Path, default=MCD_DIR)
    lcd.add_argument("--out", type=Path, default=AUDIT_DIR / "lcd")
    seed = audit_sub.add_parser("seed", help="build the seeded-fault set and its hidden key")
    seed.add_argument("--cases", type=Path, default=CASES_DIR)
    seed.add_argument("--out", type=Path, default=AUDIT_DIR / "seeded")
    seed.add_argument("--key", type=Path, default=AUDIT_DIR / "seed-key" / "key.json")
    seed.add_argument("--seed", type=int, default=2026)
    score = audit_sub.add_parser("score", help="score critic verdicts on the seeded set against the key")
    score.add_argument("--seeded", type=Path, default=AUDIT_DIR / "seeded")
    score.add_argument("--critic", type=Path, default=AUDIT_DIR / "critic-seeded")
    score.add_argument("--key", type=Path, default=AUDIT_DIR / "seed-key" / "key.json")
    score.add_argument("--lcd", type=Path, default=AUDIT_DIR / "lcd")
    score.add_argument("--results", type=Path, default=Path("RESULTS.md"))


def run_audit(args: argparse.Namespace) -> int:
    """Dispatch ``pair audit <command>``. Returns an exit code."""
    handlers = {"precheck": _precheck, "policy-text": _policy_text, "seed": _seed, "score": _score}
    return handlers[args.audit_command](args)


def _precheck(args: argparse.Namespace) -> int:
    """Mechanical checks, one JSONL log, exit 1 if any blocker."""
    paths = sorted(args.cases.glob("*/*.json"))
    if not paths:
        print(f"error: no cases under {args.cases}", file=sys.stderr)
        return EXIT_ERROR
    checklists = load_all(args.policies)
    findings = precheck_paths(paths, checklists)
    if not args.no_mcd:
        try:
            findings += check_policy_sources(checklists, MCDExport(args.mcd))
        except FileNotFoundError as error:
            print(f"warning: clause check skipped, no MCD export ({error})", file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    log = args.out / f"precheck-{dt.datetime.now():%Y%m%d-%H%M%S}.jsonl"
    meta = {"kind": "meta", "cases": str(args.cases), "n_cases": len(paths), "date": dt.date.today().isoformat()}
    with log.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
        for finding in findings:
            handle.write(json.dumps({"kind": "finding", **finding.to_json()}) + "\n")
    counts = {s: sum(f.severity is s for f in findings) for s in Severity}
    print(
        f"{len(paths)} cases checked · {counts[Severity.BLOCKER]} blocker · {counts[Severity.MAJOR]} major · "
        f"{counts[Severity.MINOR]} minor · log {log}"
    )
    return EXIT_ERROR if counts[Severity.BLOCKER] else EXIT_OK


def _policy_text(args: argparse.Namespace) -> int:
    """Write ``<out>/<policy>.txt`` with the policy's source documents."""
    args.out.mkdir(parents=True, exist_ok=True)
    export = MCDExport(args.mcd)
    for policy_id, checklist in sorted(load_all(args.policies).items()):
        try:
            text = policy_text(checklist, export)
        except (FileNotFoundError, MCDDocumentNotFound) as error:
            print(f"error: {policy_id}: {error}", file=sys.stderr)
            return EXIT_ERROR
        (args.out / f"{policy_id}.txt").write_text(text, encoding="utf-8")
        print(f"{policy_id}: {len(text):,} chars → {args.out / f'{policy_id}.txt'}")
    return EXIT_OK


def _seed(args: argparse.Namespace) -> int:
    """Write the seeded cases (renamed ``seed-NN``) and the key, kept in a separate folder."""
    cases = [load_case(path) for path in sorted(args.cases.glob("*/*.json"))]
    try:
        seeded = seed_suite(cases, load_all(args.policies), args.seed)
    except SeedingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    for item in seeded:
        save_case(item.case, args.out / item.case.policy_id / f"{item.seed_id}.json")
    key = [
        {"seed_id": s.seed_id, "base_case": s.base_case, "fault": None if s.fault is None else vars(s.fault)}
        for s in seeded
    ]
    args.key.parent.mkdir(parents=True, exist_ok=True)
    meta = {"seed": args.seed, "mix": dict(DEFAULT_MIX), "cases": str(args.cases), "date": dt.date.today().isoformat()}
    args.key.write_text(json.dumps({"meta": meta, "key": key}, indent=2) + "\n", encoding="utf-8")
    n_clean = sum(s.fault is None for s in seeded)
    print(f"{len(seeded)} seeded cases ({len(seeded) - n_clean} faulted, {n_clean} clean) → {args.out}; key → {args.key}")
    return EXIT_OK


def _score(args: argparse.Namespace) -> int:
    """Validate critic outputs, score against the key, print and record in RESULTS.md."""
    data = json.loads(args.key.read_text(encoding="utf-8"))
    checklists = load_all(args.policies)
    paths = {p.stem: p for p in args.seeded.glob("*/*.json")}
    outputs: dict[str, ValidatedOutput] = {}
    missing: list[str] = []
    for entry in data["key"]:
        case = load_case(paths[entry["seed_id"]])
        lcd = (args.lcd / f"{case.policy_id}.txt").read_text(encoding="utf-8")
        docs = case_documents(case, checklists[case.policy_id], lcd)
        try:
            outputs[case.id] = validate_output(args.critic / f"{case.id}.jsonl", docs)
        except CriticOutputError:
            missing.append(case.id)
    precheck: list[PrecheckFinding] = precheck_paths(sorted(paths.values()), checklists)
    score = score_seeded(data["key"], outputs, precheck)
    lines = [
        "## Audit critic: seeded-fault test (ADR-0013)",
        "",
        f"Seed `{data['meta']['seed']}`, {score.n_faults} faults + {score.n_clean} clean twins, date `{dt.date.today()}`.",
        "",
        "| Metric | Target | Result | Pass |",
        "|---|---|---|---|",
        (
            f"| Blocker faults caught | ≥90% | {score.blocker_catch_rate:.0%} "
            f"({score.blocker_caught}/{score.n_blocker_faults}) | {'✅' if score.blocker_catch_rate >= 0.9 else '❌'} |"
        ),
        (
            f"| Clean twins with a blocker flag | ≤10% | {score.false_blocker_rate:.0%} "
            f"({score.clean_false_blockers}/{score.n_clean}) | {'✅' if score.false_blocker_rate <= 0.1 else '❌'} |"
        ),
        f"| All faults caught | report | {score.catch_rate:.0%} ({score.caught}/{score.n_faults}) | |",
        "",
        "- By kind: " + ", ".join(f"{k} {c}/{t}" for k, (c, t) in score.by_kind.items()) + ".",
        f"- Misses: {', '.join(score.misses) or 'none'}. False alarms: {', '.join(score.false_alarms) or 'none'}.",
        (
            f"- Critic lines rejected (bad JSON or non-verbatim quote): {score.rejected_lines}; quote-less passes "
            f"coerced to fail: {score.coerced}; outputs missing: {len(missing)}."
        ),
    ]
    section = "\n".join(lines)
    update_results(args.results, section, marker="audit-critic")
    print(section)
    return EXIT_OK if not missing else EXIT_ERROR
