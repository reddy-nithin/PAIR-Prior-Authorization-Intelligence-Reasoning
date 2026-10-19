"""Download the pinned Synthea release jar (synthetic patient generator, Apache 2.0).

Usage:
    uv run python scripts/download_synthea.py [--dest data/raw/synthea]

Writes ``<dest>/synthea-with-dependencies.jar`` and ``<dest>/manifest.json``.
The SHA-256 must match the pinned release digest (ADR-0010). Never committed.
"""

import argparse
import logging
import sys
from pathlib import Path

from pair.downloads import DownloadError, download_file, write_manifest

SYNTHEA_VERSION = "v4.0.0"
JAR_NAME = "synthea-with-dependencies.jar"
JAR_URL = f"https://github.com/synthetichealth/synthea/releases/download/{SYNTHEA_VERSION}/{JAR_NAME}"
JAR_SHA256 = "ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1"
"""Release asset digest from the GitHub releases API (2026-10-19)."""
DEFAULT_DEST = Path("data/raw/synthea")
NOTICE = "Synthea (https://github.com/synthetichealth/synthea), Apache License 2.0. Output is fully synthetic."

logger = logging.getLogger("download_synthea")


def main(argv: list[str] | None = None) -> int:
    """Download the jar, check its digest and write the manifest. Returns an exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="output folder")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        record = download_file(JAR_URL, args.dest, JAR_NAME)
    except DownloadError as error:
        logger.error("Synthea download failed: %s", error)
        return 1
    if record.sha256 != JAR_SHA256:
        logger.error("Synthea jar SHA-256 %s != pinned %s; deleting it", record.sha256, JAR_SHA256)
        (args.dest / JAR_NAME).unlink(missing_ok=True)
        return 1
    logger.info("wrote %s", write_manifest([record], args.dest / "manifest.json", NOTICE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
