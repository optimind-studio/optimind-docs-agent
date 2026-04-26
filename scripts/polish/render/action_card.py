"""Action-card renderer — numbered recommendation card with red left border."""
from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from ..model import ActionCard
from . import tokens as T
from .xml_utils import apply_text_style, set_paragraph_spacing


def render(doc_docx, card: ActionCard) -> None:
    # Title paragraph: "N. Bold title text"
    title_para = doc_docx.add_paragraph()
    set_paragraph_spacing(title_para, before_twips=240, after_twips=60, line_multiple=1.3)
    _set_left_border(title_para)

    num_run = title_para.add_run(f"{card.number}. ")
    apply_text_style(num_run, T.LABELS_MAIN, override_color=T.RED)

    title_run = title_para.add_run(card.title)
    apply_text_style(title_run, T.TEXT_MAIN, override_bold=True)

    # Body paragraph
    if card.body:
        body_para = doc_docx.add_paragraph()
        set_paragraph_spacing(body_para, before_twips=0, after_twips=160, line_multiple=1.3)
        _set_left_border(body_para)
        _set_left_indent(body_para, twips=360)
        body_run = body_para.add_run(card.body)
        apply_text_style(body_run, T.TEXT_MAIN, override_color=T.TEXT_SEC)


def _set_left_border(para) -> None:
    """3pt solid brand-red left border on the paragraph."""
    pPr = para._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "18")   # 18 eighths-of-a-point = ~2.25pt
    left.set(qn("w:space"), "12")
    left.set(qn("w:color"), f"{T.RED.red:02X}{T.RED.green:02X}{T.RED.blue:02X}")
    pBdr.append(left)
    pPr.append(pBdr)


def _set_left_indent(para, twips: int) -> None:
    pPr = para._p.get_or_add_pPr()
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), str(twips))
    pPr.append(ind)
