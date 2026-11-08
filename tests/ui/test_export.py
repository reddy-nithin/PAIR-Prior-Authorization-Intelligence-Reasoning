"""Tests for the letter export: DOCX and PDF (Phase 4 T6)."""

import io
import re

import pytest
from docx import Document
from pypdf import PdfReader

from pair.ui.export import ExportError, to_docx, to_pdf
from pair.ui.view import CaseView, Decision


def docx_text(data: bytes) -> str:
    """All paragraph text of a DOCX."""
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


def pdf_text(data: bytes) -> str:
    """All page text of a PDF, with whitespace collapsed (line wrapping splits sentences)."""
    text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
    return re.sub(r"\s+", " ", text)


def flat(text: str) -> str:
    """Whitespace collapsed, to compare with wrapped PDF text."""
    return re.sub(r"\s+", " ", text).strip()


@pytest.fixture(scope="module")
def docx_bytes(view: CaseView) -> bytes:
    """The fixture letter as DOCX."""
    return to_docx(view)


@pytest.fixture(scope="module")
def pdf_bytes(view: CaseView) -> bytes:
    """The fixture letter as PDF."""
    return to_pdf(view)


def test_docx_holds_the_letter_text_exactly(view: CaseView, docx_bytes: bytes) -> None:
    """Every paragraph of the letter is in the DOCX, word for word, including the safety notice."""
    assert view.letter is not None
    text = docx_text(docx_bytes)
    for paragraph in view.letter.text.split("\n\n"):
        assert paragraph in text
    assert view.safety_notice in text


def test_pdf_holds_the_letter_text_including_non_ascii(view: CaseView, pdf_bytes: bytes) -> None:
    """The PDF has the whole letter, and policy quotes keep characters like "≥" (a Unicode font)."""
    assert view.letter is not None
    text = pdf_text(pdf_bytes)
    assert "≥" in view.letter.text and "≥" in text
    for paragraph in view.letter.text.split("\n\n"):
        assert flat(paragraph) in text
    assert flat(view.safety_notice) in text


@pytest.mark.parametrize("render", [to_docx, to_pdf])
@pytest.mark.parametrize("which", ["view", "view_flagged"])
def test_only_shown_claims_are_exported(which: str, render: object, request: pytest.FixtureRequest) -> None:
    """Flagged sentences never reach the file; kept, quoted and not-evaluated ones do."""
    view: CaseView = request.getfixturevalue(which)
    assert view.letter is not None
    if which == "view_flagged":
        assert view.letter.unconfirmed
    data = render(view)  # type: ignore[operator]
    text = flat(docx_text(data) if render is to_docx else pdf_text(data))
    for sentence in view.letter.unconfirmed:
        assert flat(sentence.text) not in text
    for sentence in view.letter.sentences:
        assert sentence.decision in (Decision.KEPT, Decision.QUOTED, Decision.NOT_EVALUATED)
        assert flat(sentence.text) in text


def test_safety_notice_is_added_if_the_letter_lacks_it(view: CaseView) -> None:
    """A letter whose text doesn't end with the notice still gets it in both files."""
    assert view.letter is not None
    bare = view.letter.text.replace(view.safety_notice, "").strip()
    letter = view.letter.model_copy(update={"text": bare})
    other = view.model_copy(update={"letter": letter})
    assert view.safety_notice in docx_text(to_docx(other))
    assert flat(view.safety_notice) in pdf_text(to_pdf(other))


def test_requirement_headings_are_bold_in_the_docx(docx_bytes: bytes) -> None:
    """Each "Requirement:" line is a bold run, so the letter scans easily."""
    runs = [run for p in Document(io.BytesIO(docx_bytes)).paragraphs for run in p.runs if run.text.startswith("Requirement:")]
    assert runs and all(run.bold for run in runs)


def test_files_carry_no_personal_metadata(docx_bytes: bytes, pdf_bytes: bytes) -> None:
    """Author fields are empty: the files must not name the person who ran PAIR."""
    props = Document(io.BytesIO(docx_bytes)).core_properties
    assert props.author == "" and props.last_modified_by == ""
    meta = PdfReader(io.BytesIO(pdf_bytes)).metadata
    assert meta is not None and not meta.get("/Author")


def test_no_letter_is_an_error(view: CaseView) -> None:
    """An unsupported case has no letter to export."""
    empty = view.model_copy(update={"letter": None})
    with pytest.raises(ExportError, match="no letter"):
        to_docx(empty)
    with pytest.raises(ExportError, match="no letter"):
        to_pdf(empty)


def test_a_character_the_pdf_font_cant_draw_is_an_error_not_a_gap(view: CaseView) -> None:
    """An emoji has no DejaVu glyph: the PDF refuses (naming the code point) instead of dropping it; DOCX is fine."""
    assert view.letter is not None
    letter = view.letter.model_copy(update={"text": view.letter.text + "\n\nThanks 🙂"})
    other = view.model_copy(update={"letter": letter})
    with pytest.raises(ExportError, match="U\\+1F642"):
        to_pdf(other)
    assert "🙂" in docx_text(to_docx(other))
