"""Heading renderer — H1 with page break + divider rule, H2/H3 with spacing."""
from __future__ import annotations

from ..model import Heading
from . import tokens as T
from .xml_utils import (
    apply_text_style, set_paragraph_bottom_border,
    set_paragraph_page_break_before, set_paragraph_spacing,
)


def render(doc_docx, heading: Heading) -> None:
    """Append a heading paragraph to a python-docx Document."""
    style = T.HEADING_STYLES[heading.level]
    para = doc_docx.add_paragraph()

    # H1 starts on a new page with a bottom-border divider on the prior paragraph.
    # We paint the divider on the prior paragraph so it sits above the heading
    # regardless of page breaks — matches the Figma `2550:17` layout.
    if heading.level == 1:
        set_paragraph_page_break_before(para)
        prev = _last_paragraph_before(doc_docx, para)
        if prev is not None:
            set_paragraph_bottom_border(prev, T.BORDER_STR, size=T.BORDER_DEFAULT_SZ, space=6)

    set_paragraph_spacing(
        para,
        before_twips=T.HEADING_SPACE_BEFORE_TWIPS if heading.level == 1 else (280 if heading.level == 2 else 200),
        after_twips=T.HEADING_SPACE_AFTER_TWIPS,
        line_multiple=style.line_spacing,
    )

    run = para.add_run(heading.text)
    apply_text_style(run, style)


def _last_paragraph_before(doc_docx, current_para):
    """Return the paragraph immediately before `current_para`, if any."""
    paras = doc_docx.paragraphs
    # python-docx .paragraphs rebuilds on each access; find by identity of _p.
    for i, p in enumerate(paras):
        if p._p is current_para._p and i > 0:
            return paras[i - 1]
    return None
