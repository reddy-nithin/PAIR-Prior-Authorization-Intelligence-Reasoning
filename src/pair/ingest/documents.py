"""Read a denial letter or record into text: text directly, PDFs and photos via Docling.

``read_document`` reads a file on disk (CLI, eval). ``read_upload`` reads an
upload from bytes and never touches the disk (ADR-0023): Docling gets an
in-memory ``DocumentStream``. Errors name the file, never its contents.

Docling (ADR-0010) is the optional ``ocr`` extra: about 1.1 GB installed and a
~2 GB peak on the M2, so it's imported only when a PDF or photo arrives.
"""

import importlib
import io
import logging
from pathlib import Path, PurePath
from typing import Any

logger = logging.getLogger(__name__)

TEXT_SUFFIXES: frozenset[str] = frozenset({".txt", ".md"})
DOCLING_SUFFIXES: frozenset[str] = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic"})
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class DocumentError(ValueError):
    """The document can't be read."""


def read_document(path: Path) -> str:
    """Return the text of a denial letter or record.

    Raises:
        DocumentError: If the file is missing, of an unsupported type, needs the
            ``ocr`` extra that isn't installed, or fails to convert.
    """
    if not path.is_file():
        raise DocumentError(f"no such file: {path}")
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8")
    if suffix in DOCLING_SUFFIXES:
        return _docling_text(path.name, lambda: str(path))
    raise _unsupported(path.name, suffix)


def read_upload(name: str, data: bytes) -> str:
    """Return the text of an uploaded file, reading only from memory.

    Args:
        name: The file name the browser sent; any folders in it are ignored.
        data: The file bytes (at most ``MAX_UPLOAD_BYTES``).

    Raises:
        DocumentError: If the upload is unnamed, empty, too large, of an
            unsupported type, not UTF-8 text, needs the ``ocr`` extra, or fails
            to convert. The message names the file, never its contents.
    """
    base = PurePath(name.replace("\\", "/")).name
    if not base:
        raise DocumentError("upload has no file name")
    if not data:
        raise DocumentError(f"{base}: file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError(f"{base}: file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    suffix = PurePath(base).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentError(f"{base}: not UTF-8 text") from exc
    if suffix in DOCLING_SUFFIXES:
        return _docling_text(base, lambda: _stream(base, data))
    raise _unsupported(base, suffix)


def _stream(name: str, data: bytes) -> Any:
    """A Docling ``DocumentStream`` over the bytes (imported only when needed)."""
    models = importlib.import_module("docling.datamodel.base_models")
    return models.DocumentStream(name=name, stream=io.BytesIO(data))


def _unsupported(name: str, suffix: str) -> DocumentError:
    """The error for a file type PAIR can't read."""
    supported = ", ".join(sorted(TEXT_SUFFIXES | DOCLING_SUFFIXES))
    return DocumentError(f"{name}: unsupported type {suffix!r}; supported: {supported}")


def _docling_text(name: str, source: Any) -> str:
    """Convert a PDF or image with Docling and export markdown text.

    Args:
        name: File name for error messages.
        source: Zero-argument callable giving Docling's input (a path string or a stream).
    """
    try:
        converter_module = importlib.import_module("docling.document_converter")
        docling_input = source()
    except ImportError as exc:
        raise DocumentError(
            f"{name}: PDFs and photos need the optional OCR extra (`uv sync --extra ocr`)"
        ) from exc
    try:
        result = converter_module.DocumentConverter().convert(docling_input)
        text: str = result.document.export_to_markdown()
    except Exception as exc:  # Docling raises many unrelated types; wrap them all with the file name
        logger.error("Docling failed on %s: %s", name, type(exc).__name__)
        raise DocumentError(f"{name}: conversion failed ({type(exc).__name__})") from exc
    return text
