"""Tests for document reading (T7): text directly, PDF/photo via the optional Docling extra."""

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from pair.ingest.documents import (
    MAX_UPLOAD_BYTES,
    DocumentError,
    read_document,
    read_upload,
)


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


def fake_docling(monkeypatch: pytest.MonkeyPatch, convert: Any) -> list[Any]:
    """Install fake Docling modules whose converter calls ``convert(source)``; returns the sources seen."""
    seen: list[Any] = []

    class Converter:
        def convert(self, source: Any) -> Any:
            seen.append(source)
            return convert(source)

    class DocumentStream:
        def __init__(self, name: str, stream: Any) -> None:
            self.name, self.stream = name, stream

    converter = ModuleType("docling.document_converter")
    converter.DocumentConverter = Converter  # type: ignore[attr-defined]
    models = ModuleType("docling.datamodel.base_models")
    models.DocumentStream = DocumentStream  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter)
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", models)
    return seen


def markdown(text: str) -> Any:
    """A fake Docling result exporting ``text``."""
    return SimpleNamespace(document=SimpleNamespace(export_to_markdown=lambda: text))


def test_text_upload_is_decoded_in_memory() -> None:
    """Text uploads are decoded from bytes; the name's folders are ignored."""
    assert read_upload("../../etc/denial.txt", "Denied – E0601".encode()) == "Denied – E0601"


def test_pdf_upload_goes_to_docling_as_a_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PDF upload reaches Docling as an in-memory stream with the bare file name, never a path."""
    seen = fake_docling(monkeypatch, lambda source: markdown("Denied: E0601"))
    assert read_upload("scans/denial.PDF", b"%PDF-1.4 bytes") == "Denied: E0601"
    (source,) = seen
    assert source.name == "denial.PDF"
    assert source.stream.read() == b"%PDF-1.4 bytes"


def test_upload_failures_name_the_file_but_not_its_contents(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Docling crash is wrapped with the file name; the error never echoes the bytes."""
    def crash(source: Any) -> Any:
        raise RuntimeError("bad pdf")

    fake_docling(monkeypatch, crash)
    with pytest.raises(DocumentError, match="denial.pdf") as error:
        read_upload("denial.pdf", b"%PDF secret-content")
    assert "secret-content" not in str(error.value)


@pytest.mark.parametrize(
    ("name", "data", "match"),
    [
        ("denial.txt", b"", "empty"),
        ("denial.docx", b"x", r"\.pdf"),
        ("denial.txt", b"\xff\xfe\x00bad", "UTF-8"),
        ("", b"x", "name"),
        ("denial.txt", b"x" * (MAX_UPLOAD_BYTES + 1), "MB"),
    ],
)
def test_bad_uploads_are_refused(name: str, data: bytes, match: str) -> None:
    """Empty, unknown, undecodable, unnamed or oversized uploads raise ``DocumentError``."""
    with pytest.raises(DocumentError, match=match):
        read_upload(name, data)


def test_reading_an_upload_writes_nothing_to_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    """No file is opened for writing and no temp file is made while reading uploads."""
    import builtins
    import tempfile

    fake_docling(monkeypatch, lambda source: markdown("Denied"))
    real_open = builtins.open

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"write attempted: {file}")
        return real_open(file, mode, *args, **kwargs)

    def no_temp(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("temp file attempted")

    monkeypatch.setattr(builtins, "open", guarded_open)
    for name in ("NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile", "mkstemp", "mkdtemp"):
        monkeypatch.setattr(tempfile, name, no_temp)
    assert read_upload("denial.txt", b"Denied") == "Denied"
    assert read_upload("denial.pdf", b"%PDF") == "Denied"


@pytest.mark.docling
def test_real_docling_reads_a_pdf_upload() -> None:
    """With the ``ocr`` extra installed, real PDF bytes convert from memory (slow; skipped otherwise)."""
    pytest.importorskip("docling")
    fixture = Path(__file__).resolve().parent.parent / "fixtures" / "documents" / "synthetic-denial.pdf"
    assert "E0601" in read_upload(fixture.name, fixture.read_bytes())
