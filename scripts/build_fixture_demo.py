"""Build and publish a demo cache from the synthetic test fixture case, with fake models (no Ollama, no lab).

Usage:
    PYTHONPATH=. uv run python scripts/build_fixture_demo.py   (or `make demo-fixture`)

For web development and the Playwright tests before the real lab cache exists (T9).
The manifest names the drafter ``fixture-fake`` so it can't pass for a real run. The local IMR
base model (gitignored) is used when present, so the strength screen has data.
Writes data/demo-cache-fixture/ and web/public/demo/ (both gitignored); a later
`make demo-cache && make demo-publish` replaces the published copy.
"""

import os
import sys
import tempfile
from pathlib import Path

from pair.trust_cli import IMR_MODEL
from pair.ui.demo_build import EXIT_OK, WEB_DEMO, build_main, publish_main
from pair.verify.conformal import Threshold, ThresholdBook
from tests.test_pipeline import CASE, gold_extract
from tests.ui.conftest import FirstLowVerifier
from tests.ui.test_demo_build import DemoLLM

DRAFTER = "fixture-fake"
OUT = Path("data/demo-cache-fixture")


def main() -> int:
    """Build the one-case fixture cache and publish it to the web app. Returns an exit code."""
    os.environ["PAIR_LLM_MODEL"] = DRAFTER
    with tempfile.TemporaryDirectory() as tmp:
        thresholds = Path(tmp) / "thresholds.json"
        ThresholdBook([Threshold(q_hat=0.5, n=54, k=1, alpha=0.1, drafter=DRAFTER, verifier_backend="minicheck",
                                 verifier_model="bespoke-minicheck")]).save(thresholds)  # fmt: skip
        argv = ["--cases", "tests/fixtures", "--case", CASE.id, "--out", str(OUT), "--thresholds", str(thresholds),
                "--imr-model", str(IMR_MODEL if IMR_MODEL.exists() else Path(tmp) / "none.pkl")]  # fmt: skip
        code = build_main(argv, client=DemoLLM(), extract_fn=gold_extract, verifier=FirstLowVerifier())
    if code != EXIT_OK:
        return code
    return publish_main(["--cache", str(OUT), "--dest", str(WEB_DEMO)])


if __name__ == "__main__":
    sys.exit(main())
