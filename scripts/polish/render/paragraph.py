"""Paragraph renderer — Text/Main style, Poppins 11pt, 1.5 line height."""
from __future__ import annotations

from ..model import Paragraph
from . import tokens as T
from .xml_utils import apply_text_style, set_paragraph_spacing


def render(doc_docx, paragraph: Paragraph) -> None:
    para = doc_docx.add_paragraph()
    set_paragraph_spacing(
        para,
        after_twips=T.PARA_SPACE_AFTER_TWIPS,
        line_multiple=T.TEXT_MAIN.line_spacing,
    )
    for r in paragraph.runs:
        if not r.text:
            continue
        run = para.add_run(r.text)
        apply_text_style(
            run, T.TEXT_MAIN,
            override_bold=r.bold,
            override_italic=r.italic,
        )
