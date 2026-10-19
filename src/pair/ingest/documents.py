"""Read an uploaded document into text: text files directly, PDFs and photos via Docling.

Docling (ADR-0010) is the optional ``ocr`` extra: about 1.1 GB installed and a
~2 GB peak on the M2, so it's imported only when a PDF or photo arrives.
"""

import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TEXT_SUFFIXES: frozenset[str] = frozenset({".txt", ".md"})
DOCLING_SUFFIXES: frozenset[str] = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic"})


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
        return _docling_text(path)
    supported = ", ".join(sorted(TEXT_SUFFIXES | DOCLING_SUFFIXES))
    raise DocumentError(f"{path.name}: unsupported type {suffix!r}; supported: {supported}")


def _docling_text(path: Path) -> str:
    """Convert a PDF or image with Docling and export markdown text."""
    try:
        converter_module = importlib.import_module("docling.document_converter")
    except ImportError as exc:
        raise DocumentError(
            f"{path.name}: PDFs and photos need the optional OCR extra (`uv sync --extra ocr`)"
        ) from exc
    try:
        result = converter_module.DocumentConverter().convert(str(path))
        text: str = result.document.export_to_markdown()
    except Exception as exc:  # Docling raises many unrelated types; wrap them all with the file name
        logger.error("Docling failed on %s: %s", path, exc)
        raise DocumentError(f"{path.name}: conversion failed: {exc}") from exc
    return text
