"""Build, verify and publish the demo cache (Phase 4 T5). The scripts in ``scripts/`` call these.

The build runs steps 1 to 7 on a few synthetic cases with the real drafter and
verifier (the lab E4B + MiniCheck pair, through the tunnel), turns each run into a
``CaseView`` and writes ``data/demo-cache/``. Publishing copies a verified cache to
``web/public/demo/`` for the web app's cached mode. Both folders are gitignored.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from pair.eval.cases import CaseBundle, CaseLoadError, CaseType, load_case
from pair.extract.runner import ExtractFn
from pair.llm import LLMClient, LLMConfig, LLMConfigError, LLMError, make_client
from pair.trust_cli import IMR_MODEL, THRESHOLDS, case_flags
from pair.ui.cache import (
    CacheEntry,
    CacheError,
    input_digest,
    publish,
    verify_cache,
    write_cache,
)
from pair.ui.export import ExportError, to_docx, to_pdf
from pair.ui.runner import POLICIES, Runner
from pair.ui.view import CaseView
from pair.verify.nli import Verifier, VerifierConfig, VerifierConfigError, make_verifier

logger = logging.getLogger(__name__)

EXIT_OK, EXIT_ERROR = 0, 1
CASES = Path("data/cases-v3")
CACHE = Path("data/demo-cache")
WEB_DEMO = Path("web/public/demo")


def _abstains(entry: CacheEntry) -> bool:
    """True if the case shows the get-a-human card instead of a number."""
    strength = entry.view.strength
    return strength is not None and strength.abstain


def default_picks(cases: Path) -> list[Path]:
    """The first wrongly-denied (type A) case per policy, then the first fixable-gap (type B) case."""
    paths = sorted(cases.glob("*/*.json"))
    kinds = {path: json.loads(path.read_text()).get("case_type") for path in paths}
    firsts: dict[str, Path] = {}
    for path in paths:
        if kinds[path] == CaseType.WRONGLY_DENIED and path.parent.name not in firsts:
            firsts[path.parent.name] = path
    gap = next((path for path in paths if kinds[path] == CaseType.FIXABLE_GAP), None)
    return list(firsts.values()) + ([gap] if gap else [])


def _picked(cases: Path, ids: Sequence[str]) -> list[Path]:
    """Paths for the requested case ids, or the default picks.

    Raises:
        CaseLoadError: If a requested id has no case file.
    """
    if not ids:
        return default_picks(cases)
    by_id = {path.stem: path for path in cases.glob("*/*.json")}
    if missing := [case_id for case_id in ids if case_id not in by_id]:
        raise CaseLoadError(f"no case file for {', '.join(missing)} under {cases}")
    return [by_id[case_id] for case_id in ids]


def git_commit(repo: Path) -> str:
    """Short commit hash, with ``-dirty`` if the tree has uncommitted changes; ``unknown`` outside git."""
    try:
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                               capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("no git commit for the manifest: %s", type(exc).__name__)
        return "unknown"
    return head + ("-dirty" if dirty else "")


def _entry(runner: Runner, case: CaseBundle) -> CacheEntry:
    """Steps 1 to 7 on one case, with its DOCX and PDF, as a cache entry.

    Raises:
        LLMError: If the drafter or verifier backend fails.
        CacheError: If the case gets no verdict (unsupported or unparsed denial).
        ExportError: If the letter can't be written as DOCX or PDF.
    """
    notes = case.record_text()
    view = runner.view(case.id, case.denial_text, notes, {note.doc_id: note.title for note in case.notes},
                       case_flags(case), policy_override=case.policy_id)  # fmt: skip
    if view.letter is None:
        raise CacheError(f"{case.id}: no verdict, so no demo view")
    extras = {"docx": to_docx(view), "pdf": to_pdf(view)}
    return CacheEntry(view=view, input_sha256=input_digest(case.denial_text, notes, case.context), extras=extras)


def _summary(view: CaseView) -> str:
    """One line per built case."""
    strength = view.strength
    chance = "no strength" if strength is None else "get a human" if strength.abstain else "strength shown"
    sentences = view.letter.sentences if view.letter else []
    kept_out = len(view.letter.unconfirmed) if view.letter else 0
    quoted = sum(s.decision.value == "quoted" for s in sentences)
    overall = view.overall.label if view.overall else "unsupported"
    return f"  {view.case_id}: {overall} · {len(sentences)} sentence(s), {quoted} quoted, {kept_out} kept out · {chance} · {view.run.get('seconds', '?')} s"


def _build_parser() -> argparse.ArgumentParser:
    """Arguments for the build."""
    parser = argparse.ArgumentParser(description="Build the demo cache (steps 1 to 7 on a few synthetic cases).")
    parser.add_argument("--cases", type=Path, default=CASES, help="case folder (policy subfolders)")
    parser.add_argument("--case", action="append", default=[], help="case id to include (repeat); default picks if none")
    parser.add_argument("--out", type=Path, default=CACHE, help="cache folder (replaced)")
    parser.add_argument("--policies", type=Path, default=POLICIES)
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS)
    parser.add_argument("--imr-model", type=Path, default=IMR_MODEL)
    parser.add_argument("--require-get-a-human", action="store_true", help="fail unless one case abstains")
    return parser


def build_main(
    argv: Sequence[str] | None = None,
    client: LLMClient | None = None,
    extract_fn: ExtractFn | None = None,
    verifier: Verifier | None = None,
) -> int:
    """Build the demo cache. ``client``/``extract_fn``/``verifier`` are injectable for tests. Returns an exit code."""
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        paths = _picked(args.cases, args.case)
        config = LLMConfig.from_env(dict(os.environ))
        if extract_fn is None:
            import langextract as lx

            extract_fn = lx.extract
        runner = Runner(client or make_client(config), config, extract_fn,
                        verifier or make_verifier(VerifierConfig.from_env()), args.policies, args.thresholds,
                        args.imr_model)  # fmt: skip
        if runner.base_note:
            print(f"warning: {runner.base_note}; strength will show as not available", file=sys.stderr)
        if runner.threshold is None:
            print("warning: no fitted threshold for this drafter and verifier; letter claims are not evaluated",
                  file=sys.stderr)  # fmt: skip
        entries = [_entry(runner, load_case(path)) for path in paths]
        if args.require_get_a_human and not any(_abstains(entry) for entry in entries):
            print("error: no picked case shows get-a-human; add one with --case", file=sys.stderr)
            return EXIT_ERROR
        write_cache(args.out, entries, {**runner.meta(), "git_commit": git_commit(Path.cwd())})
    except (CaseLoadError, LLMConfigError, VerifierConfigError, LLMError, CacheError, ExportError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    print(f"demo cache: {len(entries)} case(s) at {args.out}")
    print("\n".join(_summary(entry.view) for entry in entries))
    return EXIT_OK


def _cache_command(argv: Sequence[str] | None, action: Callable[[argparse.Namespace], str], dest: bool) -> int:
    """Shared wrapper for verify and publish: parse, run, print, map errors to exit codes."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=CACHE)
    if dest:
        parser.add_argument("--dest", type=Path, default=WEB_DEMO)
    args = parser.parse_args(argv)
    try:
        print(action(args))
    except CacheError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _verify(args: argparse.Namespace) -> str:
    """Verify the cache; problems become a ``CacheError``."""
    if problems := verify_cache(args.cache):
        raise CacheError("\n".join(problems))
    return f"demo cache OK: {args.cache}"


def verify_main(argv: Sequence[str] | None = None) -> int:
    """Check every file's SHA-256 against the manifest. Returns an exit code."""
    return _cache_command(argv, _verify, dest=False)


def publish_main(argv: Sequence[str] | None = None) -> int:
    """Copy a verified cache to the web app's static folder. Returns an exit code."""
    return _cache_command(argv, lambda args: f"published to {publish(args.cache, args.dest)}", dest=True)
