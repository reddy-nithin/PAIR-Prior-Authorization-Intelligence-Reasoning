"""Letter export: DOCX (python-docx) and PDF (fpdf2) from a ``CaseView`` (Phase 4 T6, ADR-0023).

Both files hold exactly the letter text the screen shows: kept and not-evaluated
sentences only (flagged ones are never in ``letter.text``), with the safety notice
at the end. "Requirement:" lines are bold. The PDF uses DejaVu Sans, which ships
with matplotlib, so policy quotes keep characters such as "≥" verbatim; a character
the font can't draw is an error, never silently dropped. Neither file carries an
author: they must not name the person who ran PAIR.
"""

import functools
import io
import logging
from pathlib import Path

import matplotlib
from docx import Document
from docx.shared import Pt
from fontTools.ttLib import TTFont
from fpdf import FPDF
from fpdf.enums import Align, XPos, YPos

from pair.ui.view import CaseView

logger = logging.getLogger(__name__)

TITLE = "Appeal letter"
HEADING_PREFIX = "Requirement:"
FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
FONT, FONT_BOLD = FONT_DIR / "DejaVuSans.ttf", FONT_DIR / "DejaVuSans-Bold.ttf"
FONT_SIZE, LINE_HEIGHT, MARGIN_MM = 11, 5.5, 22


class ExportError(ValueError):
    """The case can't be exported."""


def _paragraphs(view: CaseView) -> list[list[str]]:
    """The letter as paragraphs of lines, ending with the safety notice.

    Raises:
        ExportError: If the case has no letter.
    """
    if view.letter is None:
        raise ExportError(f"{view.case_id}: no letter to export")
    text = view.letter.text.strip()
    if not text.endswith(view.safety_notice):
        text = f"{text}\n\n{view.safety_notice}"
    return [block.split("\n") for block in text.split("\n\n") if block.strip()]


def to_docx(view: CaseView) -> bytes:
    """The letter as a Word document.

    Raises:
        ExportError: If the case has no letter.
    """
    paragraphs = _paragraphs(view)
    document = Document()
    document.styles["Normal"].font.size = Pt(FONT_SIZE)
    props = document.core_properties
    props.title, props.author, props.last_modified_by, props.comments = TITLE, "", "", ""
    for lines in paragraphs:
        paragraph = document.add_paragraph()
        for i, line in enumerate(lines):
            run = paragraph.add_run(line)
            run.bold = i == 0 and line.startswith(HEADING_PREFIX)
            if i < len(lines) - 1:
                run.add_break()
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@functools.cache
def _drawable() -> frozenset[int]:
    """Code points both DejaVu Sans faces can draw."""
    regular, bold = (set(TTFont(path).getBestCmap()) for path in (FONT, FONT_BOLD))
    return frozenset(regular & bold)


def _check_glyphs(paragraphs: list[list[str]], case_id: str) -> None:
    """Raise if any character has no glyph, so nothing is dropped from the PDF.

    Raises:
        ExportError: Naming the first such character by code point.
    """
    drawable = _drawable()
    for line in (line for lines in paragraphs for line in lines):
        if missing := sorted({ch for ch in line if ord(ch) not in drawable}):
            codes = ", ".join(f"U+{ord(ch):04X}" for ch in missing)
            logger.error("%s: PDF font can't draw %s", case_id, codes)
            raise ExportError(f"{case_id}: the PDF font can't draw {codes}; use the Word file instead")


def to_pdf(view: CaseView) -> bytes:
    """The letter as a PDF.

    Raises:
        ExportError: If the case has no letter or a character can't be drawn.
    """
    paragraphs = _paragraphs(view)
    _check_glyphs(paragraphs, view.case_id)
    pdf = FPDF(format="Letter")
    pdf.set_margins(MARGIN_MM, MARGIN_MM, MARGIN_MM)
    pdf.set_auto_page_break(auto=True, margin=MARGIN_MM)
    pdf.add_font("DejaVu", "", str(FONT))
    pdf.add_font("DejaVu", "B", str(FONT_BOLD))
    pdf.set_title(TITLE)
    pdf.set_creator("PAIR")
    pdf.add_page()
    for lines in paragraphs:
        for i, line in enumerate(lines):
            bold = i == 0 and line.startswith(HEADING_PREFIX)
            pdf.set_font("DejaVu", "B" if bold else "", FONT_SIZE)
            pdf.multi_cell(0, LINE_HEIGHT, line, align=Align.L, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(LINE_HEIGHT)
    return bytes(pdf.output())
