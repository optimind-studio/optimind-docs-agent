"""Section-label renderer — "01 — OVERVIEW" dividers from PDF section markers."""
from __future__ import annotations

from docx.enum.text import WD_ALIGN_PARAGRAPH

from ..model import SectionLabel
from . import tokens as T
from .xml_utils import apply_text_style, set_paragraph_spacing


def render(doc_docx, label: SectionLabel) -> None:
    text = f"{label.number} — {label.text}" if label.number else label.text

    para = doc_docx.add_paragraph()
    set_paragraph_spacing(para, before_twips=480, after_twips=40, line_multiple=1.0)
    para.alignment = WD_ALIGN_PARAGRAPH.LEFT

    run = para.add_run(text)
    apply_text_style(run, T.LABELS_MAIN)
