"""List renderer — bulleted with a clean indent hierarchy.

We render lists as simple indented paragraphs with a leading glyph (•, ‣, ·) to
avoid the complexity of Word's numbering definitions. For numbered lists we emit
`1.`, `1.1`, etc. as text.

Why: rebuilding Word's `w:numId` machinery reliably across arbitrary source
documents is brittle; the canonical rule is "every list looks the same". A
visual glyph + indent gives us that without touching numPr.
"""
from __future__ import annotations

from ..model import List, ListItem
from . import tokens as T
from .xml_utils import apply_text_style, set_paragraph_indent, set_paragraph_spacing


_BULLET_GLYPHS = ["•", "‣", "·"]


def render(doc_docx, list_block: List) -> None:
    counters: dict[int, int] = {}
    for item in list_block.items:
        _render_item(doc_docx, item, counters)


def _render_item(doc_docx, item: ListItem, counters: dict[int, int]) -> None:
    para = doc_docx.add_paragraph()
    level = max(0, min(item.level, 2))
    set_paragraph_spacing(para, after_twips=60, line_multiple=T.TEXT_MAIN.line_spacing)
    set_paragraph_indent(para, left_twips=360 + level * 360, hanging_twips=180)

    if item.ordered:
        counters[level] = counters.get(level, 0) + 1
        # reset deeper levels on outer increment
        for deeper in list(counters):
            if deeper > level:
                counters.pop(deeper, None)
        glyph = f"{counters[level]}."
    else:
        glyph = _BULLET_GLYPHS[level % len(_BULLET_GLYPHS)]

    # Glyph run — same Poppins, slight right margin via tab-ish space.
    glyph_run = para.add_run(f"{glyph}\t")
    apply_text_style(glyph_run, T.TEXT_MAIN)

    for r in item.runs:
        if not r.text:
            continue
        run = para.add_run(r.text)
        apply_text_style(run, T.TEXT_MAIN, override_bold=r.bold, override_italic=r.italic)
