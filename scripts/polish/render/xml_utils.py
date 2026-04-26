"""Low-level Word XML helpers, shared across renderers.

Ported from scripts/polish_doc.py XML helpers (lines 107-230) with cleanups.
"""
from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from .tokens import FONT_FAMILY, TextStyle, hex_color


# ── Cell-level ──────────────────────────────────────────────────────────────

def set_cell_color(cell, rgb: RGBColor) -> None:
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for existing in tcPr.findall(qn("w:shd")):
        tcPr.remove(existing)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color(rgb))
    tcPr.append(shd)


def set_cell_borders(cell, *, top=None, bottom=None, left=None, right=None,
                     size: int = 4) -> None:
    """Set individual borders. Pass RGBColor or None (None hides the border)."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = tcPr.find(qn("w:tcBorders"))
    if tcBorders is None:
        tcBorders = OxmlElement("w:tcBorders")
        tcPr.append(tcBorders)
    for side, color in [("top", top), ("bottom", bottom),
                        ("left", left), ("right", right)]:
        old = tcBorders.find(qn(f"w:{side}"))
        if old is not None:
            tcBorders.remove(old)
        el = OxmlElement(f"w:{side}")
        if color is None:
            el.set(qn("w:val"), "nil")
        else:
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), str(size))
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), hex_color(color))
        tcBorders.append(el)


def set_cell_padding(cell, top=100, bottom=100, left=120, right=120) -> None:
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    old = tcPr.find(qn("w:tcMar"))
    if old is not None:
        tcPr.remove(old)
    tcMar = OxmlElement("w:tcMar")
    for side, val in [("top", top), ("bottom", bottom),
                      ("left", left), ("right", right)]:
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:w"), str(val))
        el.set(qn("w:type"), "dxa")
        tcMar.append(el)
    tcPr.append(tcMar)


def set_cell_width(cell, value: int, width_type: str = "dxa") -> None:
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    old = tcPr.find(qn("w:tcW"))
    if old is not None:
        tcPr.remove(old)
    tcW = OxmlElement("w:tcW")
    tcW.set(qn("w:w"), str(value))
    tcW.set(qn("w:type"), width_type)
    tcPr.append(tcW)


def set_cell_vertical_merge(cell, restart: bool) -> None:
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    old = tcPr.find(qn("w:vMerge"))
    if old is not None:
        tcPr.remove(old)
    vm = OxmlElement("w:vMerge")
    if restart:
        vm.set(qn("w:val"), "restart")
    tcPr.append(vm)


def set_cell_grid_span(cell, span: int) -> None:
    if span <= 1:
        return
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    old = tcPr.find(qn("w:gridSpan"))
    if old is not None:
        tcPr.remove(old)
    gs = OxmlElement("w:gridSpan")
    gs.set(qn("w:val"), str(span))
    tcPr.append(gs)


# ── Run-level ───────────────────────────────────────────────────────────────

def apply_text_style(run, style: TextStyle, *, override_bold: bool | None = None,
                     override_italic: bool | None = None,
                     override_color: RGBColor | None = None) -> None:
    """Apply a TextStyle to a python-docx run, preserving text content."""
    bold = style.bold if override_bold is None else override_bold
    italic = False if override_italic is None else override_italic
    color = style.color if override_color is None else override_color

    # SemiBold uses the "Poppins SemiBold" face name — don't set w:b.
    font_face = f"{FONT_FAMILY} SemiBold" if style.semibold else FONT_FAMILY
    run.font.name = font_face
    run.font.size = style.size
    run.font.bold = None if style.semibold else bold
    run.font.italic = italic
    run.font.color.rgb = color

    rPr = run._r.get_or_add_rPr()
    # Lock the font across ascii / hAnsi / cs so Word doesn't substitute.
    for el in rPr.findall(qn("w:rFonts")):
        rPr.remove(el)
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), font_face)
    rFonts.set(qn("w:hAnsi"), font_face)
    rFonts.set(qn("w:cs"),    font_face)
    rPr.insert(0, rFonts)

    if style.letter_spacing_pt:
        for sp in rPr.findall(qn("w:spacing")):
            rPr.remove(sp)
        spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:val"), str(int(style.letter_spacing_pt * 20)))
        rPr.append(spacing)

    if style.titlecase and run.text:
        # Word has no native title-case property — apply at text level for labels only.
        run.text = run.text.title()

    # Strip RTL to prevent number/punctuation reordering in mixed-direction docs.
    for rtl in rPr.findall(qn("w:rtl")):
        rPr.remove(rtl)


# ── Paragraph-level ─────────────────────────────────────────────────────────

def set_paragraph_spacing(para, *, before_twips: int | None = None,
                          after_twips: int | None = None,
                          line_multiple: float | None = None) -> None:
    pPr = para._p.get_or_add_pPr()
    for old in pPr.findall(qn("w:spacing")):
        pPr.remove(old)
    sp = OxmlElement("w:spacing")
    if before_twips is not None:
        sp.set(qn("w:before"), str(before_twips))
    if after_twips is not None:
        sp.set(qn("w:after"), str(after_twips))
    if line_multiple is not None:
        sp.set(qn("w:line"), str(int(line_multiple * 240)))
        sp.set(qn("w:lineRule"), "auto")
    pPr.append(sp)


def set_paragraph_bottom_border(para, color: RGBColor, *, size: int = 4,
                                space: int = 6) -> None:
    pPr = para._p.get_or_add_pPr()
    pBdr = pPr.find(qn("w:pBdr"))
    if pBdr is None:
        pBdr = OxmlElement("w:pBdr")
        pPr.append(pBdr)
    for old in pBdr.findall(qn("w:bottom")):
        pBdr.remove(old)
    bot = OxmlElement("w:bottom")
    bot.set(qn("w:val"), "single")
    bot.set(qn("w:sz"), str(size))
    bot.set(qn("w:space"), str(space))
    bot.set(qn("w:color"), hex_color(color))
    pBdr.append(bot)


def set_paragraph_page_break_before(para) -> None:
    pPr = para._p.get_or_add_pPr()
    for old in pPr.findall(qn("w:pageBreakBefore")):
        pPr.remove(old)
    el = OxmlElement("w:pageBreakBefore")
    pPr.append(el)


def set_paragraph_indent(para, *, left_twips: int = 0,
                         hanging_twips: int = 0) -> None:
    pPr = para._p.get_or_add_pPr()
    for old in pPr.findall(qn("w:ind")):
        pPr.remove(old)
    ind = OxmlElement("w:ind")
    if left_twips:
        ind.set(qn("w:left"), str(left_twips))
    if hanging_twips:
        ind.set(qn("w:hanging"), str(hanging_twips))
    pPr.append(ind)


def strip_paragraph_shading(para) -> None:
    """Paragraphs we wrap in callout tables shouldn't keep their original fill."""
    pPr = para._p.find(qn("w:pPr"))
    if pPr is None:
        return
    for shd in pPr.findall(qn("w:shd")):
        pPr.remove(shd)
