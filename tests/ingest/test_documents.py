"""Tests for document reading (T7): text directly, PDF/photo via the optional Docling extra."""

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from pair.ingest.documents import DocumentError, read_document


def test_text_file_is_read_as_utf8(tmp_path: Path) -> None:
    """Plain text and markdown are read as-is."""
    path = tmp_path / "denial.txt"
    path.write_text("Notice of Denial – E0601", encoding="utf-8")
    assert read_document(path) == "Notice of Denial – E0601"


def test_missing_file_raises(tmp_path: Path) -> None:
    """A missing file is a DocumentError naming the path."""
    with pytest.raises(DocumentError, match="nope.txt"):
        read_document(tmp_path / "nope.txt")


def test_unsupported_suffix_raises(tmp_path: Path) -> None:
    """Unknown formats are refused, listing what is supported."""
    path = tmp_path / "denial.docx"
    path.write_bytes(b"x")
    with pytest.raises(DocumentError, match=r"\.pdf"):
        read_document(path)


def test_pdf_without_the_extra_says_how_to_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without Docling installed, a PDF gives a clear install hint."""
    path = tmp_path / "denial.pdf"
    path.write_bytes(b"%PDF-1.4")
    real_import = importlib.import_module

    def no_docling(name: str, *args: Any) -> ModuleType:
        if name.startswith("docling"):
            raise ImportError(name)
        return real_import(name, *args)

    monkeypatch.setattr("importlib.import_module", no_docling)
    with pytest.raises(DocumentError, match="--extra ocr"):
        read_document(path)


def test_pdf_goes_through_docling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A PDF or photo is converted by Docling and exported as markdown text."""
    path = tmp_path / "denial.png"
    path.write_bytes(b"\x89PNG")
    seen: list[str] = []

    class Converter:
        def convert(self, source: str) -> Any:
            seen.append(source)
            return SimpleNamespace(document=SimpleNamespace(export_to_markdown=lambda: "Denied: E0601"))

    fake = ModuleType("docling.document_converter")
    fake.DocumentConverter = Converter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake)
    assert read_document(path) == "Denied: E0601"
    assert seen == [str(path)]


def test_docling_failure_becomes_document_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A conversion crash is wrapped with the file name."""
    path = tmp_path / "denial.pdf"
    path.write_bytes(b"%PDF-1.4")

    class Converter:
        def convert(self, source: str) -> Any:
            raise RuntimeError("bad pdf")

    fake = ModuleType("docling.document_converter")
    fake.DocumentConverter = Converter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake)
    with pytest.raises(DocumentError, match="denial.pdf"):
        read_document(path)


@pytest.mark.docling
def test_real_docling_reads_a_pdf(tmp_path: Path) -> None:
    """With the ``ocr`` extra installed, a real PDF converts (slow; skipped otherwise)."""
    pytest.importorskip("docling")
    fixture = Path(__file__).resolve().parent.parent / "fixtures" / "documents" / "synthetic-denial.pdf"
    assert "E0601" in read_document(fixture)
