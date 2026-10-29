"""Phase 3 commands: draft and score claims, fit the threshold, fit and test the IMR model, report.

- ``pair draft-claims``: steps 1 to 6 on every case from predicted evidence, one
  record per claim (T6, T7b).
- ``pair fit-threshold``: q̂ from labeled dev claims; refuses with fewer than 11
  strict-unsupported claims (ADR-0020).
- ``pair imr-fit`` / ``pair imr-test``: choose and calibrate the base model on
  2023, then score 2024 and later once (ADR-0019).
- ``pair eval-trust``: claim funnel, conformal rates and the exit verdict into
  ``RESULTS.md`` (T10, T11).
"""

import argparse
import dataclasses
import datetime as dt
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pair.contracts import ClaimDecision, CriterionStatus
from pair.draft.template import load_letter_template
from pair.eval.cases import CaseBundle, load_case
from pair.eval.claims import (
    ClaimRecord,
    agreement,
    blind_batches,
    build_gate_set,
    disagreement_queue,
    import_labels,
    load_human_jsonl,
    load_label_file,
    overlaps_gold,
    pick_human_naturals,
    read_records,
    score_gate,
    spot_check_sample,
    unblind,
    write_records,
)
from pair.eval.trust_metrics import (
    claim_funnel,
    claim_records,
    exchangeability,
    letter_outcomes,
    trust_markdown,
    write_trust_results,
)
from pair.eval.trust_stats import (
    empty_letter_rate,
    exit_verdict,
    leak_rate,
    precision_of_kept,
    support_among_nonempty,
    worst_case_leak_rate,
)
from pair.extract.runner import ExtractFn
from pair.llm import LLMClient, LLMConfig, LLMError
from pair.pipeline import Resources, run_core, run_trust
from pair.rules.active import ContextFlag
from pair.score.base_model import (
    BaseModelError,
    fit_base_model,
    load_base_model,
    save_base_model,
    split_years,
)
from pair.score.imr_data import IMRSchemaError, load_imr_features
from pair.score.imr_mapping import ImrMappingError, load_imr_mapping
from pair.verify.conformal import ConformalError, ThresholdBook, fit_threshold
from pair.verify.nli import PREMISE_RULE, Verifier

logger = logging.getLogger(__name__)

THRESHOLDS = Path("data/models/thresholds.json")
IMR_MODEL = Path("data/models/imr-base.pkl")
IMR_CSV = Path("data/raw/imr/imr_determinations.csv")
IMR_REPORT = Path("data/runs/imr-test-2024plus.json")
TEMPLATE = Path("policies/_letter.yaml")
TRUST_COMMANDS = frozenset({"draft-claims", "gate-export", "gate-score", "label-export", "label-import", "spot-check", "fit-threshold", "imr-fit", "imr-test", "eval-trust"})
GATE_SEED, BLIND_SEED, HUMAN_SEED, HUMAN_N = 0, 1, 2, 20
EXIT_OK, EXIT_ERROR = 0, 1


def add_trust_parsers(sub: Any, runs_dir: Path, results_path: Path) -> None:
    """Register the Phase 3 subcommands."""
    draft = sub.add_parser("draft-claims", help="draft and score claims for every case (predicted evidence)")
    draft.add_argument("--cases", type=Path, action="append", required=True, help="cases folder (repeatable)")
    draft.add_argument("--out", type=Path, required=True)
    draft.add_argument("--thresholds", type=Path, default=THRESHOLDS)
    gate = sub.add_parser("gate-export", help="seeded-claim gate: blind critic batches, key, and Nithin's natural set")
    gate.add_argument("--claims", type=Path, required=True, help="natural dev claim records")
    gate.add_argument("--out-dir", type=Path, default=Path("data/audit/claims-gate-v1"))
    gate.add_argument("--key-dir", type=Path, default=Path("data/audit/seed-key/claims-gate-v1"))
    gate.add_argument("--batches", type=Path, default=Path(".agent/critic/batches"))
    gate.add_argument("--batch-size", type=int, default=20)
    score = sub.add_parser("gate-score", help="import the critic's gate labels and Nithin's, score the gate")
    score.add_argument("--out-dir", type=Path, default=Path("data/audit/claims-gate-v1"))
    score.add_argument("--key-dir", type=Path, default=Path("data/audit/seed-key/claims-gate-v1"))
    lex = sub.add_parser("label-export", help="blind S1 batches for every natural claim that passed the citation checks")
    lex.add_argument("--claims", type=Path, required=True)
    lex.add_argument("--out-dir", type=Path, default=Path("data/audit/claims-s1-dev-v1"))
    lex.add_argument("--key-dir", type=Path, default=Path("data/audit/seed-key/claims-s1-dev-v1"))
    lex.add_argument("--batches", type=Path, default=Path(".agent/critic/batches"))
    lex.add_argument("--batch-size", type=int, default=20)
    lim = sub.add_parser("label-import", help="import S1 verdicts, queue one re-run for gaps, write labels.json")
    lim.add_argument("--out-dir", type=Path, default=Path("data/audit/claims-s1-dev-v1"))
    lim.add_argument("--key-dir", type=Path, default=Path("data/audit/seed-key/claims-s1-dev-v1"))
    lim.add_argument("--batches", type=Path, default=Path(".agent/critic/batches"))
    spot = sub.add_parser("spot-check", help="Nithin's S1 spot check: export the sheet, then score agreement")
    spot.add_argument("action", choices=["export", "score"])
    spot.add_argument("--claims", type=Path, required=True)
    spot.add_argument("--cases", type=Path, action="append", required=True, help="cases folder with gold evidence")
    spot.add_argument("--out-dir", type=Path, default=Path("data/audit/claims-s1-dev-v1"))
    spot.add_argument("--key-dir", type=Path, default=Path("data/audit/seed-key/claims-s1-dev-v1"))
    fit = sub.add_parser("fit-threshold", help="fit the conformal threshold on labeled dev claims")
    fit.add_argument("--claims", type=Path, action="append", required=True)
    fit.add_argument("--labels", type=Path, required=True)
    fit.add_argument("--thresholds", type=Path, default=THRESHOLDS)
    imr_fit = sub.add_parser("imr-fit", help="choose and calibrate the IMR base model on 2023 (no 2024+ rows)")
    imr_fit.add_argument("--imr", type=Path, default=IMR_CSV)
    imr_fit.add_argument("--model", type=Path, default=IMR_MODEL)
    imr_fit.add_argument("--mapping", type=Path, default=Path("policies/_imr-mapping.yaml"))
    imr_test = sub.add_parser("imr-test", help="score the frozen IMR model on 2024 and later, once")
    imr_test.add_argument("--imr", type=Path, default=IMR_CSV)
    imr_test.add_argument("--model", type=Path, default=IMR_MODEL)
    imr_test.add_argument("--out", type=Path, default=IMR_REPORT)
    ev = sub.add_parser("eval-trust", help="claim funnel, conformal rates and exit verdict into RESULTS.md")
    ev.add_argument("--claims", type=Path, action="append", required=True, help="test claim records (repeatable)")
    ev.add_argument("--labels", type=Path, required=True)
    ev.add_argument("--cases", type=Path, action="append", required=True, help="test cases folder (repeatable)")
    ev.add_argument("--thresholds", type=Path, default=THRESHOLDS)
    ev.add_argument("--imr-report", type=Path, default=IMR_REPORT)
    ev.add_argument("--results", type=Path, default=results_path)
    ev.add_argument("--runs", type=Path, default=runs_dir)
    ev.add_argument("--calib-claims", type=Path, action="append", help="dev claim records for the exchangeability check")
    ev.add_argument("--calib-labels", type=Path, help="dev S1 labels for the exchangeability check")
    ev.add_argument("--spot-check-result", type=Path, help="spot-check agreement JSON shown next to the leak rate")


def run_trust_command(
    args: argparse.Namespace,
    resources: Resources,
    client: LLMClient,
    config: LLMConfig,
    extract_fn: ExtractFn,
    verifier: Verifier | None,
) -> int:
    """Dispatch one Phase 3 command; returns an exit code."""
    try:
        if args.command == "draft-claims":
            assert verifier is not None
            return _draft_claims(args, resources, client, config, extract_fn, verifier)
        if args.command == "gate-export":
            return _gate_export(args)
        if args.command == "gate-score":
            return _gate_score(args)
        if args.command == "label-export":
            return _label_export(args)
        if args.command == "label-import":
            return _label_import(args)
        if args.command == "spot-check":
            return _spot_check(args)
        if args.command == "fit-threshold":
            return _fit_threshold(args)
        if args.command == "imr-fit":
            return _imr_fit(args)
        if args.command == "imr-test":
            return _imr_test(args)
        return _eval_trust(args)
    except (LLMError, ConformalError, BaseModelError, IMRSchemaError, ImrMappingError, ValueError, OSError) as error:
        logger.error("%s failed: %s", args.command, error)
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR


def case_flags(case: CaseBundle, overrides: Mapping[str, bool | None] | None = None) -> dict[str, ContextFlag]:
    """Context flags with sources: the case bundle's flags, then ``--context`` user input."""
    flags = {name: ContextFlag(value, "case bundle (synthetic)") for name, value in case.context.items()}
    flags.update({name: ContextFlag(value, "user input") for name, value in (overrides or {}).items()})
    return flags


def _case_paths(folders: list[Path]) -> list[Path]:
    """Every case JSON under the folders (one level of policy subfolders)."""
    return sorted(path for folder in folders for path in folder.glob("*/*.json"))


def _draft_claims(
    args: argparse.Namespace,
    resources: Resources,
    client: LLMClient,
    config: LLMConfig,
    extract_fn: ExtractFn,
    verifier: Verifier,
) -> int:
    """Steps 1 to 6 per case, from predicted evidence; one record per claim."""
    info = verifier.describe()
    threshold = ThresholdBook.load(args.thresholds).lookup(config.model, info["verifier_backend"], info["verifier_model"])
    template = load_letter_template(TEMPLATE)
    records: list[ClaimRecord] = []
    fallbacks = 0
    paths = _case_paths(args.cases)
    for path in paths:
        case = load_case(path)
        core = run_core(case.denial_text, case.record_text(), resources, client, config, case.context, extract_fn,
                        policy_override=case.policy_id)
        if core.verdict is None or core.denial is None:
            logger.warning("%s: no verdict or denial, no claims", case.id)
            continue
        trust = run_trust(core, case.record_text(), resources.checklists[case.policy_id], client, verifier,
                          threshold, config.model, template, case_flags(case))
        fallbacks += trust.wording.fallbacks
        records += claim_records(case.id, case.profile.synthea_id, trust.verified)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_records(records, args.out)
    meta = {"drafter": config.model, **info, "premise_rule": PREMISE_RULE, "threshold": "fitted" if threshold else "none",
            "config_hash": config.config_hash(), "date": dt.date.today().isoformat(), "cases": len(paths),
            "claims": len(records), "wording_fallbacks": fallbacks}
    args.out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    dropped = sum(r.decision is ClaimDecision.DROP for r in records)
    print(f"{len(records)} claims from {len(paths)} cases ({dropped} dropped, {fallbacks} wording fallbacks) "
          f"· threshold {meta['threshold']} · {args.out}")
    return EXIT_OK


def _check_no_open_batches(batches: Path) -> None:
    """Refuse to add batches while unclaimed ones are waiting.

    Raises:
        ValueError: If an unclaimed ``batch-*.md`` exists.
    """
    open_batches = sorted(p.name for p in batches.glob("batch-*.md") if not p.with_suffix(".claimed").exists())
    if open_batches:
        raise ValueError(f"unclaimed batches already in {batches}: {', '.join(open_batches)}; archive them first")


def _write_batches(
    batches: Sequence[Sequence[dict[str, str]]], out_dir: Path, batch_dir: Path, stem: str = "batch"
) -> int:
    """Write critic inputs under ``out_dir/input`` and one spec per batch; returns the first batch number."""
    (out_dir / "input").mkdir(parents=True, exist_ok=True)
    (out_dir / "critic").mkdir(parents=True, exist_ok=True)
    batch_dir.mkdir(parents=True, exist_ok=True)
    start = 1 + max((int(p.stem.split("-")[1]) for p in batch_dir.glob("batch-*.md")), default=0)
    first_input = 1 + len(list((out_dir / "input").glob(f"{stem}-*.jsonl")))
    for offset, rows in enumerate(batches):
        name = f"{stem}-{first_input + offset:02d}"
        source = out_dir / "input" / f"{name}.jsonl"
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        (batch_dir / f"batch-{start + offset:02d}.md").write_text(
            f"mode: claims\ninput: {source}\noutput: {out_dir / 'critic' / f'{name}.jsonl'}\nclaims: {len(rows)}\n"
            + ("rerun: true (each claim gets one second try; still unlabeled after this means excluded)\n"
               if stem == "rerun" else "")
        )
    return start


def _label_export(args: argparse.Namespace) -> int:
    """Blind S1 batches for every natural claim that passed the citation checks."""
    _check_no_open_batches(args.batches)
    records = [r for r in read_records(args.claims) if r.kind == "natural" and r.decision is not ClaimDecision.DROP]
    blind = blind_batches(records, seed=BLIND_SEED, batch_size=args.batch_size, prefix="d")
    args.key_dir.mkdir(parents=True, exist_ok=True)
    (args.key_dir / "key.json").write_text(json.dumps(blind.key, indent=2) + "\n")
    start = _write_batches(blind.batches, args.out_dir, args.batches)
    print(f"{len(records)} claims in {len(blind.batches)} S1 batches from batch-{start:02d} in {args.batches} · "
          f"key in {args.key_dir}")
    return EXIT_OK


def _read_inputs(out_dir: Path, stem: str) -> dict[str, dict[str, str]]:
    """Premises per input file stem, e.g. ``{"batch-01": {claim_id: premise}}``."""
    return {
        path.stem: {row["claim_id"]: row["premise"] for row in map(json.loads, path.read_text().splitlines())}
        for path in sorted((out_dir / "input").glob(f"{stem}-*.jsonl"))
    }


def _label_import(args: argparse.Namespace) -> int:
    """Import every S1 output, queue one re-run batch for claims with no valid verdict, write ``labels.json``."""
    key: dict[str, str] = json.loads((args.key_dir / "key.json").read_text())
    first, second = _read_inputs(args.out_dir, "batch"), _read_inputs(args.out_dir, "rerun")
    labels: dict[str, Any] = {}
    missing, rejected = [], 0
    for name, premises in {**first, **second}.items():
        output = args.out_dir / "critic" / f"{name}.jsonl"
        if not output.exists():
            missing.append(name)
            continue
        imported = import_labels(output, premises)
        labels.update(imported.labels)
        rejected += len(imported.rejected)
    rerun_done = {cid for name, premises in second.items() if name not in missing for cid in premises}
    rerun_pending = {cid for name, premises in second.items() if name in missing for cid in premises}
    gaps = [cid for name, premises in first.items() if name not in missing for cid in premises if cid not in labels]
    excluded = [cid for cid in gaps if cid in rerun_done]
    to_rerun = [cid for cid in gaps if cid not in rerun_done and cid not in rerun_pending]
    if to_rerun:
        rows = {row["claim_id"]: row for name in first for row in map(
            json.loads, (args.out_dir / "input" / f"{name}.jsonl").read_text().splitlines())}
        _write_batches([[rows[cid] for cid in to_rerun]], args.out_dir, args.batches, stem="rerun")
    real = unblind(labels, key)
    (args.out_dir / "labels.json").write_text(json.dumps(dict(sorted(real.items())), indent=2) + "\n")
    (args.out_dir / "excluded.json").write_text(json.dumps(sorted(key[c] for c in excluded), indent=2) + "\n")
    counts = {label: sum(v == label for v in real.values()) for label in ("supported", "partly", "unsupported")}
    print(f"{len(real)} labeled ({', '.join(f'{k} {v}' for k, v in counts.items())}) · {rejected} lines rejected · "
          f"{len(to_rerun)} to re-run · {len(excluded)} excluded after a re-run · labels {args.out_dir / 'labels.json'}")
    if missing:
        print(f"  critic output not written yet: {', '.join(missing)}")
    return EXIT_OK


SPOT_HEADER = [
    "# S1 spot check", "",
    "Same question as the gate: does the CLAIM say anything the PREMISE doesn't?", "",
    "- supported: everything in the claim is in the premise (rewording is fine; the premise may have more).",
    "- partly: the claim's main fact is there, but the claim adds or changes something.",
    "- unsupported: the premise doesn't say the claim's main fact, or says the opposite.", "",
    "Use only the premise. One word on each LABEL line (a note after it is fine). Save with Cmd+S.",
    "Don't open {critic_dir} or labels.json until you're done.", "",
]


def _spot_check(args: argparse.Namespace) -> int:
    """Export Nithin's spot-check sheet (ADR-0020 sample), or score it against the critic's labels."""
    key: dict[str, str] = json.loads((args.key_dir / "key.json").read_text())
    blind_of = {real: blind for blind, real in key.items()}
    critic: dict[str, Any] = json.loads((args.out_dir / "labels.json").read_text())
    sheet = args.out_dir / "human" / "spot-check.jsonl"
    if args.action == "export":
        records = {r.claim_id: r for r in read_records(args.claims)}
        gold = {c.id: c.gold_evidence for c in map(load_case, _case_paths(args.cases))}
        overlap = {cid: overlaps_gold(records[cid], gold.get(records[cid].case_id, [])) for cid in critic}
        queue = disagreement_queue(critic, overlap)
        sample = sorted(spot_check_sample(critic, queue, seed=0), key=lambda cid: blind_of[cid])
        sheet.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"claim_id": blind_of[cid], "claim": records[cid].text, "premise": records[cid].premise, "label": ""}
                for cid in sample]
        sheet.write_text("".join(json.dumps(row) + "\n" for row in rows))
        lines = [line.format(critic_dir=f"{args.out_dir / 'critic'}/") for line in SPOT_HEADER]
        for number, row in enumerate(rows, start=1):
            lines += ["---", "", f"## {number} of {len(rows)} ({row['claim_id']})", "", f"CLAIM: {row['claim']}", "",
                      f"PREMISE: {row['premise']}", "", "LABEL: ", ""]
        sheet.with_name("spot-check-checklist.md").write_text("\n".join(lines))
        print(f"spot check: {len(rows)} claims ({len(queue)} from the disagreement queue) · {sheet.with_name('spot-check-checklist.md')}")
        return EXIT_OK
    human_blind, blank = load_human_jsonl(sheet)
    human = unblind(human_blind, key)
    report = agreement(critic, human, seed=0)
    (args.out_dir / "spot-check-result.json").write_text(
        json.dumps({**dataclasses.asdict(report), "blank": len(blank)}, indent=2, default=float) + "\n")
    verdict = "labels count" if report.labels_count else "labels DON'T count (binary kappa < 0.7)"
    print(f"spot check: n {report.n} · agreement {report.percent:.0%} · binary kappa {report.kappa_binary:.2f} "
          f"[{report.kappa_binary_low:.2f}, {report.kappa_binary_high:.2f}], AC1 {report.ac1_binary:.2f} · 3-class "
          f"kappa {report.kappa:.2f} [{report.kappa_low:.2f}, {report.kappa_high:.2f}], AC1 {report.ac1:.2f} · {verdict}"
          + (f" · {len(blank)} blank" if blank else ""))
    return EXIT_OK


def _gate_export(args: argparse.Namespace) -> int:
    """Build the seeded gate plus Nithin's 20 naturals, blind them together, write batches and the key."""
    _check_no_open_batches(args.batches)
    records = read_records(args.claims)
    gate = build_gate_set(records, seed=GATE_SEED)
    human = pick_human_naturals(records, gate, n=HUMAN_N, seed=HUMAN_SEED)
    blind = blind_batches([*gate, *human], seed=BLIND_SEED, batch_size=args.batch_size, prefix="g")
    args.key_dir.mkdir(parents=True, exist_ok=True)
    write_records(gate, args.key_dir / "gate.jsonl")
    write_records(human, args.key_dir / "human-naturals.jsonl")
    (args.key_dir / "key.json").write_text(json.dumps(blind.key, indent=2) + "\n")
    start = _write_batches(blind.batches, args.out_dir, args.batches)
    by_real = {real: blind_id for blind_id, real in blind.key.items()}
    (args.out_dir / "human").mkdir(parents=True, exist_ok=True)
    (args.out_dir / "human" / f"natural-{HUMAN_N}.jsonl").write_text("".join(
        json.dumps({"claim_id": by_real[r.claim_id], "claim": r.text, "premise": r.premise, "label": ""}) + "\n"
        for r in sorted(human, key=lambda r: by_real[r.claim_id])
    ))
    print(f"gate: {sum(g.kind == 'fault' for g in gate)} faults, {sum(g.kind == 'clean' for g in gate)} clean twins, "
          f"{len(human)} naturals for Nithin · {len(blind.batches)} critic batches from batch-{start:02d} in "
          f"{args.batches} · key in {args.key_dir}")
    return EXIT_OK


def _gate_score(args: argparse.Namespace) -> int:
    """Import every critic batch, unblind, and score the gate against the seeded key and Nithin's labels."""
    key: dict[str, str] = json.loads((args.key_dir / "key.json").read_text())
    gate = read_records(args.key_dir / "gate.jsonl")
    human_real = {r.claim_id for r in read_records(args.key_dir / "human-naturals.jsonl")}
    blind_labels: dict[str, Any] = {}
    missing, rejected, rerun = [], [], []
    for source in sorted((args.out_dir / "input").glob("batch-*.jsonl")):
        premises = {row["claim_id"]: row["premise"] for row in map(json.loads, source.read_text().splitlines())}
        output = args.out_dir / "critic" / source.name
        if not output.exists():
            missing.append(source.stem)
            continue
        imported = import_labels(output, premises)
        blind_labels.update(imported.labels)
        rejected += [f"{source.stem} {line}" for line in imported.rejected]
        rerun += list(imported.rerun)
    labels = unblind(blind_labels, key)
    human_blind, blank = load_human_jsonl(args.out_dir / "human" / "natural-20.jsonl")
    human = unblind(human_blind, key)
    critic_natural = {cid: label for cid, label in labels.items() if cid in human_real}
    result = score_gate(gate, labels, critic_natural, human)
    by_fault: dict[str, dict[str, int]] = {}
    for record in gate:
        if record.kind == "fault" and record.fault_type:
            row = by_fault.setdefault(record.fault_type, {"n": 0, "caught": 0})
            row["n"] += 1
            row["caught"] += labels.get(record.claim_id) in ("partly", "unsupported")
    report: dict[str, Any] = {**dataclasses.asdict(result), "by_fault": by_fault, "missing_batches": missing,
                              "rejected": rejected, "rerun": rerun, "human_blank": len(blank)}
    if len(human) >= 2 and critic_natural:
        report["agreement"] = dataclasses.asdict(agreement(critic_natural, human, seed=0))
    (args.out_dir / "gate-result.json").write_text(json.dumps(report, indent=2, default=float) + "\n")
    print(f"Gate {'PASS' if result.passed else 'NOT PASSED'} · faults caught {result.caught}/{result.n_faults} · "
          f"clean flagged {result.clean_flagged}/{result.n_clean} · agreement with Nithin "
          f"{result.natural_agree}/{result.n_natural}")
    print("  by fault: " + ", ".join(f"{k} {v['caught']}/{v['n']}" for k, v in sorted(by_fault.items())))
    if missing:
        print(f"  critic output not written yet: {', '.join(missing)}")
    if rejected or rerun:
        print(f"  {len(rejected)} critic lines rejected, {len(rerun)} claims to re-run once")
    if blank:
        print(f"  Nithin's file: {len(blank)} blank labels")
    print("  " + "; ".join(result.reasons) if result.reasons else "  all three bars met")
    return EXIT_OK


def _labeled(paths: list[Path], labels_path: Path) -> tuple[list[ClaimRecord], dict[str, Any]]:
    """Records from every file and the final S1 labels."""
    return [r for path in paths for r in read_records(path)], dict(load_label_file(labels_path))


def _fit_threshold(args: argparse.Namespace) -> int:
    """Fit q̂ on strict-unsupported natural dev claims that passed the citation checks."""
    records, labels = _labeled(args.claims, args.labels)
    negatives = [r for r in records if r.kind == "natural" and r.decision is not ClaimDecision.DROP
                 and r.score is not None and labels.get(r.claim_id) in ("partly", "unsupported")]
    rules = {r.premise_rule for r in records if r.kind == "natural"}
    if len(rules) != 1 or None in rules:
        raise ConformalError(f"calibration claims need one premise rule, found {sorted(map(str, rules))} (ADR-0022)")
    pairs = {(r.drafter, r.verifier_backend, r.verifier_model) for r in negatives}
    if len(pairs) > 1:
        raise ValueError(f"claims come from several (drafter, verifier) pairs: {sorted(pairs)}")
    if not negatives:
        raise ConformalError("0 unsupported calibration claims; at least 11 are needed (ADR-0020)")
    drafter, backend, model = pairs.pop()
    threshold = fit_threshold([r.score for r in negatives if r.score is not None], drafter, backend, model,
                              premise_rule=rules.pop() or "")
    args.thresholds.parent.mkdir(parents=True, exist_ok=True)
    ThresholdBook.load(args.thresholds).with_threshold(threshold).save(args.thresholds)
    print(f"q_hat {threshold.q_hat:.4f} from n={threshold.n} (k={threshold.k}) for {threshold.key} · "
          f"P(leak > 0.2) = {threshold.leak_bound:.3f} · {args.thresholds}")
    return EXIT_OK


def _imr_fit(args: argparse.Namespace) -> int:
    """Choose model and window on 2023, fit calibrators, print the width rule, save. 2024+ is never scored."""
    frame = load_imr_features(args.imr)
    model = fit_base_model(frame, load_imr_mapping(args.mapping), seed=0, log=print)
    for policy_id, row in model.width_check(max_width=0.20).items():
        estimate = model.estimate(policy_id)
        print(f"{policy_id}: p {estimate.p:.3f} range [{estimate.low:.3f}, {estimate.high:.3f}] width {row.width:.3f} "
              f"n_similar {row.n_similar} abstain_on_width {row.abstain}")
    print(f"saved {save_base_model(model, args.model)}")
    return EXIT_OK


def _imr_test(args: argparse.Namespace) -> int:
    """Score the frozen model on 2024 and later and save the report."""
    model = load_base_model(args.model)
    _, _, test = split_years(load_imr_features(args.imr))
    report = model.evaluate(test)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dataclasses.asdict(report), indent=2, default=float) + "\n")
    c = report.coverage
    print(f"2024+: n {report.n} · AUROC {report.auroc:.3f} · Brier {report.brier:.4f} · Mondrian coverage "
          f"{c.coverage:.3f} [{c.low:.3f}, {c.high:.3f}] · sets both {c.share_both:.2f} single {c.share_single:.2f}")
    for policy_id, group in report.per_group.items():
        print(f"  {policy_id} (descriptive): n {group.n} coverage {group.coverage.coverage:.3f} "
              f"[{group.coverage.low:.3f}, {group.coverage.high:.3f}]")
    print(f"saved {args.out}")
    return EXIT_OK


def _config_hash(claims: Path) -> str | None:
    """The config hash from a claims file's ``.meta.json``, if it has one."""
    meta = claims.with_suffix(".meta.json")
    if not meta.exists():
        return None
    value = json.loads(meta.read_text()).get("config_hash")
    return str(value) if value else None


def _eval_trust(args: argparse.Namespace) -> int:
    """Funnel, conformal rates and exit verdict for the test side, into RESULTS.md and a JSONL log."""
    records, labels = _labeled(args.claims, args.labels)
    cases = [load_case(path) for path in _case_paths(args.cases)]
    gold = {c.id: frozenset(cid for cid, s in c.gold_statuses.items() if s is CriterionStatus.MET) for c in cases}
    letters = letter_outcomes(records, labels, gold)
    rates = {"leak": leak_rate(letters), "empty": empty_letter_rate(letters),
             "support": support_among_nonempty(letters), "precision": precision_of_kept(letters),
             "worst_leak": worst_case_leak_rate(letters)}
    verdict = exit_verdict(rates["leak"])
    natural = [r for r in records if r.kind == "natural"]
    pair = (natural[0].drafter, natural[0].verifier_backend, natural[0].verifier_model) if natural else ("", "", "")
    threshold = ThresholdBook.load(args.thresholds).lookup(*pair)
    imr: dict[str, Any] | None = None
    if args.imr_report.exists():
        raw = json.loads(args.imr_report.read_text())
        cov = raw["coverage"]
        imr = {"n": raw["n"], "auroc": raw["auroc"], "brier": raw["brier"], "coverage": cov["coverage"],
               "coverage_low": cov["low"], "coverage_high": cov["high"], "share_both": cov["share_both"]}
        imr["reliability"] = raw.get("reliability", [])
    meta = {"drafter": pair[0], "verifier_backend": pair[1], "verifier_model": pair[2],
            "date": dt.date.today().isoformat(), "claims": str(len(natural)), "cases": str(len(cases))}
    hashes = sorted({h for path in args.claims if (h := _config_hash(path))})
    if hashes:
        meta["config_hash"] = ",".join(hashes)
    shift = None
    if args.calib_claims and args.calib_labels:
        calib, calib_labels = _labeled(args.calib_claims, args.calib_labels)
        shift = exchangeability(calib, calib_labels, records, labels)
    agreement = json.loads(args.spot_check_result.read_text()) if args.spot_check_result else None
    funnel = claim_funnel(records, labels, gold)
    section = trust_markdown(funnel, rates, verdict, threshold.leak_bound if threshold else None, imr, meta,
                             agreement=agreement, shift=shift)
    write_trust_results(args.results, section)
    args.runs.mkdir(parents=True, exist_ok=True)
    log = args.runs / f"eval-trust-{dt.datetime.now():%Y%m%d-%H%M%S}.jsonl"
    with log.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": "meta", **meta, "verdict": verdict}) + "\n")
        handle.write(json.dumps({"kind": "funnel", **dataclasses.asdict(funnel)}) + "\n")
        for name, rate in rates.items():
            handle.write(json.dumps({"kind": "rate", "name": name, **dataclasses.asdict(rate)}) + "\n")
    leak = rates["leak"]
    print(f"leak {leak.k}/{leak.n} = {leak.point:.3f} (bootstrap [{leak.boot_low:.3f}, {leak.boot_high:.3f}]) · "
          f"CCR after verifier {funnel.ccr_after.rate:.1%} · verdict {verdict} (relative to critic labels) · {log}")
    return EXIT_OK
