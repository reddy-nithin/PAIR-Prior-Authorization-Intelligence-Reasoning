"""Read NCD and LCD text from a Medicare Coverage Database (MCD) CSV export.

The export's text fields are HTML. They are converted to plain text with one
line per paragraph or list item, so policy clauses can be checked as verbatim
substrings (whitespace-insensitive) of the official text.
"""

import csv
import html
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LCD_SECTIONS: tuple[str, ...] = ("indication", "doc_reqs", "coding_guidelines")
NCD_SECTIONS: tuple[str, ...] = ("itm_srvc_desc", "indctn_lmtn")
LCD_URL = "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid={id}&ver={version}"
NCD_URL = "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid={id}&ncdver={version}"
ACTIVE_LCD_STATUS = "A"

_BLOCK_END = re.compile(r"<br\s*/?>|</(p|li|ol|ul|div|h[1-6]|tr|table)>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


class MCDDocumentNotFound(LookupError):
    """No active NCD or LCD matches the requested id."""


def normalize_whitespace(text: str) -> str:
    """Collapse every whitespace run (including newlines) into one space."""
    return " ".join(text.split())


def html_to_text(markup: str) -> str:
    """Convert MCD HTML to plain text, one line per paragraph or list item."""
    with_breaks = _BLOCK_END.sub("\n", markup)
    plain = html.unescape(_TAG.sub("", with_breaks))
    lines = (normalize_whitespace(line) for line in plain.splitlines())
    return "\n".join(line for line in lines if line)


@dataclass(frozen=True)
class MCDDocument:
    """One coverage document's metadata and plain-text sections."""

    kind: Literal["NCD", "LCD"]
    id: str
    version: str
    title: str
    url: str
    sections: Mapping[str, str]

    def contains(self, phrase: str) -> bool:
        """Return True if ``phrase`` appears verbatim, ignoring whitespace differences."""
        haystack = normalize_whitespace(" ".join(self.sections.values()))
        return normalize_whitespace(phrase) in haystack


class MCDExport:
    """Lookup over an extracted MCD export folder.

    Expects ``<root>/lcd_csv/lcd.csv`` and ``<root>/ncd_csv/ncd_trkg.csv``, as
    written by ``scripts/download_mcd.py``.
    """

    def __init__(self, root: Path) -> None:
        """Remember the export folder; each CSV is read once, on first use."""
        self.root = root
        self._row_cache: dict[str, list[dict[str, str]]] = {}

    def find_lcd(self, lcd_id: str) -> MCDDocument:
        """Return the newest active version of an LCD, e.g. ``L33718`` or ``33718``.

        Raises:
            MCDDocumentNotFound: If no active version exists.
            FileNotFoundError: If the export file is missing.
        """
        number = lcd_id.upper().removeprefix("L")
        rows = [
            row for row in self._rows("lcd_csv/lcd.csv")
            if row["lcd_id"] == number and row["status"] == ACTIVE_LCD_STATUS
        ]
        if not rows:
            raise MCDDocumentNotFound(f"no active LCD with id {number}")
        row = max(rows, key=lambda r: int(r["lcd_version"]))
        return MCDDocument(
            kind="LCD",
            id=f"L{number}",
            version=row["lcd_version"],
            title=row["title"],
            url=LCD_URL.format(id=number, version=row["lcd_version"]),
            sections=_sections(row, LCD_SECTIONS),
        )

    def find_ncd(self, manual_section: str) -> MCDDocument:
        """Return the current version of an NCD by manual section, e.g. ``240.4``.

        Raises:
            MCDDocumentNotFound: If no unterminated version exists.
            FileNotFoundError: If the export file is missing.
        """
        rows = [
            row for row in self._rows("ncd_csv/ncd_trkg.csv")
            if row["NCD_mnl_sect"] == manual_section and not row["NCD_trmntn_dt"]
        ]
        if not rows:
            raise MCDDocumentNotFound(f"no current NCD for manual section {manual_section}")
        row = max(rows, key=lambda r: int(r["NCD_vrsn_num"]))
        return MCDDocument(
            kind="NCD",
            id=manual_section,
            version=row["NCD_vrsn_num"],
            title=row["NCD_mnl_sect_title"],
            url=NCD_URL.format(id=row["NCD_id"], version=row["NCD_vrsn_num"]),
            sections=_sections(row, NCD_SECTIONS),
        )

    def _rows(self, relative_path: str) -> list[dict[str, str]]:
        """Return the rows of one export CSV as dicts, reading the file only once."""
        if relative_path not in self._row_cache:
            self._row_cache[relative_path] = _read_csv(self.root / relative_path)
        return self._row_cache[relative_path]


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read an MCD CSV (fields can be very large HTML) into a list of dicts."""
    if not path.exists():
        raise FileNotFoundError(f"MCD export file missing: {path} (run `make data`)")
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _sections(row: Mapping[str, str], names: tuple[str, ...]) -> dict[str, str]:
    """Convert the named HTML fields of a row to text, dropping empty ones."""
    converted = {name: html_to_text(row.get(name, "")) for name in names}
    return {name: text for name, text in converted.items() if text}
