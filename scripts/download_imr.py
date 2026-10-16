"""Download the California DMHC Independent Medical Review (IMR) determinations dataset.

Usage:
    uv run python scripts/download_imr.py [--dest data/raw/imr]

Writes the CSV, the data dictionary PDF and ``<dest>/manifest.json``. The data is
gitignored and never committed or redistributed.
"""

import argparse
import logging
import sys
from pathlib import Path

from pair.downloads import DownloadError, download_file, write_manifest

DATASET = "https://data.chhs.ca.gov/dataset/b79b3447-4c10-4ae6-84e2-1076f83bb24e/resource/"
FILES: dict[str, str] = {
    "imr_determinations.csv": DATASET
    + "3340c5d7-4054-4d03-90e0-5f44290ed095/download/independent-medical-review-imr-determinations-trends.csv",
    "imr_data_dictionary.pdf": DATASET + "2c5c2144-138f-4feb-b2af-a1176995e1b1/download/imrdatadictionary.pdf",
}
DEFAULT_DEST = Path("data/raw/imr")
NOTICE = (
    "California Department of Managed Health Care (DMHC) Independent Medical Review "
    "determinations, via the CHHS Open Data Portal. Used for noncommercial research; "
    "PAIR does not redistribute the data or altered copies of it."
)

logger = logging.getLogger("download_imr")


def main(argv: list[str] | None = None) -> int:
    """Download the IMR CSV and data dictionary. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="output folder")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(NOTICE)
    try:
        records = [download_file(url, args.dest, name) for name, url in FILES.items()]
    except DownloadError as error:
        logger.error("IMR download failed: %s", error)
        return 1
    manifest = write_manifest(records, args.dest / "manifest.json", NOTICE)
    logger.info("wrote %s", manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
