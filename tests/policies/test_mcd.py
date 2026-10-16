"""Tests for reading NCD/LCD text from an MCD CSV export (fake fixture rows)."""

from pathlib import Path

import pytest

from pair.policies.mcd import (
    MCDDocumentNotFound,
    MCDExport,
    html_to_text,
    normalize_whitespace,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "mcd"


def test_html_to_text_strips_tags_and_entities() -> None:
    """Tags go, entities decode, list items and paragraphs become lines."""
    text = html_to_text("<p>A <b>bold</b> claim&#8217;s</p><ol><li>one</li><li>AHI &#8805; 15</li></ol>")
    assert text.splitlines() == ["A bold claim’s", "one", "AHI ≥ 15"]


def test_normalize_whitespace_collapses_runs() -> None:
    """Whitespace runs, including newlines, become single spaces."""
    assert normalize_whitespace("  a \n\n b\tc ") == "a b c"


def test_find_lcd_returns_latest_active_version() -> None:
    """The newest active version wins, with sections as plain text and an MCD URL."""
    doc = MCDExport(FIXTURE).find_lcd("L99001")
    assert doc.version == "3"
    assert doc.title == "Fake Device Policy"
    assert doc.url == "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid=99001&ver=3"
    assert "AHI ≥ 15 events per hour" in doc.sections["indication"]
    assert doc.contains("A device is covered when ALL of these are met:")
    assert doc.contains("Keep the usage report.")
    assert not doc.contains("old text")


def test_find_lcd_accepts_bare_number() -> None:
    """``99001`` and ``L99001`` name the same LCD."""
    assert MCDExport(FIXTURE).find_lcd("99001").id == "L99001"


def test_find_ncd_by_manual_section_skips_retired() -> None:
    """NCDs are found by manual section; terminated versions are ignored."""
    doc = MCDExport(FIXTURE).find_ncd("999.1")
    assert doc.version == "2"
    assert doc.url == "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=500&ncdver=2"
    assert doc.contains("Covered if the test is positive.")


@pytest.mark.parametrize(("kind", "doc_id"), [("lcd", "L99002"), ("lcd", "L12345"), ("ncd", "1.1")])
def test_missing_or_inactive_documents_raise(kind: str, doc_id: str) -> None:
    """Proposed-only or absent documents are an error, never a silent empty string."""
    export = MCDExport(FIXTURE)
    finder = export.find_lcd if kind == "lcd" else export.find_ncd
    with pytest.raises(MCDDocumentNotFound, match=doc_id.lstrip("L")):
        finder(doc_id)


def test_missing_export_dir_raises(tmp_path: Path) -> None:
    """Pointing at a folder with no CSVs fails loudly."""
    with pytest.raises(FileNotFoundError, match="lcd.csv"):
        MCDExport(tmp_path).find_lcd("L1")
