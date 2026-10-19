"""Generate the synthetic evaluation cases (spec §5.3, Phase 2 T9/T10).

Usage:
    uv run python scripts/generate_cases.py [--per-policy 10] [--seed 2026] [--backend gemini]

Steps: run Synthea once if its CSV output is missing (pinned jar, fixed seed,
ages 65 to 90, CSV only), plan each case, have the LLM write notes around the
planted phrases, check the spans, and write ``data/cases/<policy>/<id>.json``
plus ``data/cases/AUDIT.md``. Existing case files are kept. Everything is
synthetic and gitignored. Stop Ollama first if it runs locally (8 GB rule).
"""

import argparse
import datetime as dt
import logging
import os
import subprocess
import sys
from pathlib import Path

from pair.eval.synth.generate import generate_suite, suite
from pair.eval.synth.profiles import ProfileError, load_synthea_profiles
from pair.llm import LLMConfig, LLMConfigError, LLMError, make_client
from pair.policies.loader import load_all

SYNTHEA_DIR = Path("data/raw/synthea")
SYNTHEA_JAR = SYNTHEA_DIR / "synthea-with-dependencies.jar"
SYNTHEA_CSV = SYNTHEA_DIR / "output" / "csv"
SYNTHEA_SEED = 2026
SYNTHEA_REFERENCE = dt.date(2026, 10, 19)
SYNTHEA_PATIENTS = 40
OUT_DIR = Path("data/cases")
PRICE_PER_M = {"gemini-3.5-flash": (1.50, 9.00)}
"""USD per 1M input / output tokens on the Vertex global endpoint (checked 2026-10-19)."""

logger = logging.getLogger("generate_cases")


def run_synthea() -> None:
    """Run the pinned Synthea jar once with a fixed seed (CSV export only).

    Raises:
        FileNotFoundError: If the jar hasn't been downloaded.
        subprocess.CalledProcessError: If Synthea fails.
    """
    if not SYNTHEA_JAR.is_file():
        raise FileNotFoundError(f"{SYNTHEA_JAR} missing; run `uv run python scripts/download_synthea.py`")
    command = [
        "java", "-jar", SYNTHEA_JAR.name,
        "-s", str(SYNTHEA_SEED), "-cs", str(SYNTHEA_SEED), "-r", SYNTHEA_REFERENCE.strftime("%Y%m%d"),
        "-p", str(SYNTHEA_PATIENTS), "-a", "65-90",
        "--exporter.baseDirectory", "./output",
        "--exporter.fhir.export", "false", "--exporter.csv.export", "true",
        "--exporter.hospital.fhir.export", "false", "--exporter.practitioner.fhir.export", "false",
        "--generate.only_alive_patients", "true",
        "Missouri",
    ]  # fmt: skip
    logger.info("running Synthea: %s", " ".join(command))
    subprocess.run(command, cwd=SYNTHEA_DIR, check=True, capture_output=True)


def main(argv: list[str] | None = None) -> int:
    """Generate the case suite. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--per-policy", type=int, default=10)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--backend", default="gemini", help="LLM backend for writing notes (ADR-0010)")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if not (SYNTHEA_CSV / "patients.csv").is_file():
            run_synthea()
        profiles = load_synthea_profiles(SYNTHEA_CSV, SYNTHEA_REFERENCE)
        config = LLMConfig.from_env({**os.environ, "PAIR_LLM_BACKEND": args.backend})
    except (FileNotFoundError, subprocess.CalledProcessError, ProfileError, LLMConfigError) as error:
        logger.error("setup failed: %s", error)
        return 1
    checklists = load_all(Path("policies"))
    generator = {
        "backend": config.backend.value,
        "model": config.model,
        "config_hash": config.config_hash(),
        "generated": dt.date.today().isoformat(),
        "synthea": f"v4.0.0 seed {SYNTHEA_SEED}",
    }
    requests = suite(sorted(checklists), base_seed=args.seed, per_policy=args.per_policy)
    try:
        summary = generate_suite(requests, checklists, profiles, make_client(config), args.out, generator)
    except LLMError as error:
        logger.error("LLM unavailable: %s", error)
        return 1
    price_in, price_out = PRICE_PER_M.get(config.model, (0.0, 0.0))
    cost = summary.prompt_tokens * price_in / 1e6 + summary.output_tokens * price_out / 1e6
    print(
        f"written {summary.written}, skipped {summary.skipped}, failed {len(summary.failed)}; "
        f"tokens in {summary.prompt_tokens:,} out {summary.output_tokens:,}; est. cost ${cost:.3f}"
    )
    for case_id, reason in summary.failed:
        print(f"FAILED {case_id}: {reason}")
    return 1 if summary.failed else 0


if __name__ == "__main__":
    sys.exit(main())
