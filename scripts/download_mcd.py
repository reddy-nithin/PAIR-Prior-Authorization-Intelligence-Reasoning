"""Download the CMS Medicare Coverage Database (MCD) NCD and current-LCD CSV exports.

Usage:
    uv run python scripts/download_mcd.py [--dest data/raw/mcd]

Writes ``<dest>/ncd_csv/*.csv``, ``<dest>/lcd_csv/*.csv``, the data dictionary
PDFs and ``<dest>/manifest.json`` (URLs, SHA-256, retrieval date). The large
Access ``.mdb`` files are not extracted. Data is never committed (gitignored).
"""

import argparse
import logging
import sys
from pathlib import Path

from pair.downloads import (
    DownloadError,
    DownloadRecord,
    download_file,
    extract_matching,
    write_manifest,
)

EXPORT_BASE = "https://downloads.cms.gov/medicare-coverage-database/downloads/exports/"
ARCHIVES: dict[str, str] = {"ncd.zip": "ncd_csv", "current_lcd.zip": "lcd_csv"}
DEFAULT_DEST = Path("data/raw/mcd")
NOTICE = (
    "CMS Medicare Coverage Database export. LCD text may reference CPT codes and "
    "descriptors, which are copyright of the American Medical Association (AMA) and "
    "subject to the AMA license accepted on the MCD downloads page. PAIR quotes "
    "coverage text only and never redistributes CPT descriptors or these files."
)

logger = logging.getLogger("download_mcd")


def fetch_export(archive_name: str, csv_folder: str, dest: Path) -> DownloadRecord:
    """Download one MCD archive and extract its CSVs and data dictionary into ``dest``."""
    archive_dir = dest / "archives"
    record = download_file(EXPORT_BASE + archive_name, archive_dir, archive_name)
    inner = extract_matching(archive_dir / archive_name, archive_dir, ["*_csv.zip", "*data dictionary.pdf"])
    for path in inner:
        if path.suffix == ".zip":
            csv_files = extract_matching(path, dest / csv_folder, ["*.csv"])
            logger.info("%s: extracted %d CSV files to %s", archive_name, len(csv_files), dest / csv_folder)
        else:
            path.replace(dest / path.name)
    return record


def main(argv: list[str] | None = None) -> int:
    """Download both exports and write the manifest. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="output folder")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(NOTICE)
    try:
        records = [fetch_export(name, folder, args.dest) for name, folder in ARCHIVES.items()]
    except DownloadError as error:
        logger.error("MCD download failed: %s", error)
        return 1
    manifest = write_manifest(records, args.dest / "manifest.json", NOTICE)
    logger.info("wrote %s", manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
