"""Table renderer — Classic (red header) + Minimal (rule-based) variants.

Builds the python-docx table from scratch using the canonical Table model.
Handles:
  - Multi-row headers (repeated for each row in table.headers)
  - Merged cells via MergeSpec (rowspan + colspan)
  - Numeric-column right alignment (auto-detected per column)
  - Zebra stripes in Classic; horizontal rules in Minimal

Port of pattern in scripts/polish_doc.py:431-598 — but operates on our typed model.
"""
from __future__ import annotations

import re

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from ..model import MergeSpec, Table
from . import tokens as T
from .xml_utils import (
    apply_text_style, set_cell_borders, set_cell_color, set_cell_grid_span,
    set_cell_padding, set_cell_vertical_merge, set_cell_width,
    set_paragraph_spacing,
)


_NUMERIC_RE = re.compile(r'^\s*[\$€£¥]?\s*[-+]?\d[\d,]*(\.\d+)?\s*%?\s*$')


def render(doc_docx, table: Table) -> None:
    if not table.rows and not table.headers:
        return

    # Build a single matrix of all rows including header rows for rendering.
    header_row_count = len(table.headers)
    total_rows = header_row_count + len(table.rows)
    n_cols = _infer_col_count(table)

    if total_rows == 0 or n_cols == 0:
        return

    t = doc_docx.add_table(rows=total_rows, cols=n_cols)
    t.autofit = False
    _set_table_frame(t)

    # Populate cells
    for row_idx in range(total_rows):
        if row_idx < header_row_count:
            source_row = table.headers[row_idx]
            is_header = True
        else:
            source_row = table.rows[row_idx - header_row_count]
            is_header = False
        _populate_row(t, row_idx, source_row, n_cols,
                      is_header=is_header,
                      is_last_body=row_idx == total_rows - 1 and not is_header,
                      variant=table.variant,
                      numeric_cols=_numeric_columns(table.rows, n_cols))

    # Apply merges. MergeSpec indexes into total_rows (0-based, headers first).
    for m in table.merges:
        _apply_merge(t, m, n_cols=n_cols, total_rows=total_rows)

    # Caption
    if table.caption:
        _add_caption(doc_docx, table.caption)


# ── frame ───────────────────────────────────────────────────────────────────

def _set_table_frame(tbl) -> None:
    """Set table-level borders (none at table level; per-cell controls) + width."""
    tblPr = tbl._tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl._tbl.insert(0, tblPr)
    for tag in ("w:tblStyle", "w:tblBorders", "w:tblCellMar"):
        old = tblPr.find(qn(tag))
        if old is not None:
            tblPr.remove(old)

    tblBorders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "none")
        tblBorders.append(el)
    tblPr.append(tblBorders)

    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW")
        tblPr.append(tblW)
    tblW.set(qn("w:w"), "5000")
    tblW.set(qn("w:type"), "pct")


# ── per-row population ──────────────────────────────────────────────────────

def _populate_row(tbl, row_idx: int, source_row, n_cols: int, *,
                  is_header: bool, is_last_body: bool,
                  variant: str, numeric_cols: set[int]) -> None:
    row = tbl.rows[row_idx]
    for col_idx in range(n_cols):
        cell = row.cells[col_idx]
        text = source_row[col_idx] if col_idx < len(source_row) else ""
        _style_cell(cell, text, col_idx=col_idx, row_idx=row_idx,
                    is_header=is_header, is_last_body=is_last_body,
                    variant=variant, is_numeric_col=col_idx in numeric_cols)


def _style_cell(cell, text: str, *, col_idx: int, row_idx: int,
                is_header: bool, is_last_body: bool,
                variant: str, is_numeric_col: bool) -> None:
    # Fill
    if variant == "classic":
        if is_header:
            set_cell_color(cell, T.RED)
        elif row_idx % 2 == 0:                      # zebra
            set_cell_color(cell, T.BG_SUBTLE)
        else:
            set_cell_color(cell, T.WHITE)
    else:  # minimal
        set_cell_color(cell, T.WHITE)

    # Borders
    if variant == "classic":
        set_cell_borders(
            cell,
            top=T.BORDER_STR if is_header else (T.BORDER_DEF if row_idx > 0 else None),
            bottom=T.BORDER_DEF if is_last_body else None,
            left=None, right=None,
        )
    else:  # minimal
        set_cell_borders(
            cell,
            top=T.BORDER_STR if is_header and row_idx == 0 else None,
            bottom=(T.BORDER_STR if (is_header or is_last_body) else T.BORDER_DEF),
            left=None, right=None,
        )

    set_cell_padding(cell, top=T.CELL_PAD_V_TWIPS, bottom=T.CELL_PAD_V_TWIPS,
                     left=T.CELL_PAD_H_TWIPS, right=T.CELL_PAD_H_TWIPS)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    # Remove default empty para, add our own
    for p in list(cell.paragraphs):
        cell._tc.remove(p._p)
    para = cell.add_paragraph()
    set_paragraph_spacing(para, before_twips=0, after_twips=0,
                          line_multiple=T.TEXT_TABLE.line_spacing)

    # Alignment
    if is_numeric_col and not is_header:
        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    elif is_header:
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT if col_idx == 0 else WD_ALIGN_PARAGRAPH.CENTER
    elif col_idx == 0:
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    else:
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    run = para.add_run(text)

    if is_header:
        if variant == "classic":
            apply_text_style(run, T.TITLES_TABLE)
        else:
            apply_text_style(run, T.LABELS_MAIN)
    elif col_idx == 0:
        apply_text_style(run, T.TEXT_TABLE)
    else:
        apply_text_style(run, T.TEXT_TABLE, override_color=T.TEXT_SEC)


# ── merges ──────────────────────────────────────────────────────────────────

def _apply_merge(tbl, m: MergeSpec, *, n_cols: int, total_rows: int) -> None:
    """Apply a rowspan/colspan to the (m.row, m.col) anchor cell."""
    if m.row >= total_rows or m.col >= n_cols:
        return

    # Column span
    if m.colspan > 1:
        anchor = tbl.rows[m.row].cells[m.col]
        right_bound = min(m.col + m.colspan - 1, n_cols - 1)
        # python-docx Cell.merge will combine — avoids manual gridSpan math.
        right_cell = tbl.rows[m.row].cells[right_bound]
        try:
            anchor.merge(right_cell)
        except Exception:
            # fall back to gridSpan write-through
            set_cell_grid_span(anchor, m.colspan)

    # Row span
    if m.rowspan > 1:
        anchor = tbl.rows[m.row].cells[m.col]
        set_cell_vertical_merge(anchor, restart=True)
        for r in range(m.row + 1, min(m.row + m.rowspan, total_rows)):
            try:
                set_cell_vertical_merge(tbl.rows[r].cells[m.col], restart=False)
            except IndexError:
                break


# ── helpers ─────────────────────────────────────────────────────────────────

def _infer_col_count(table: Table) -> int:
    candidates = []
    for hr in table.headers:
        candidates.append(len(hr))
    for r in table.rows:
        candidates.append(len(r))
    return max(candidates) if candidates else 0


def _numeric_columns(rows, n_cols: int) -> set[int]:
    cols: set[int] = set()
    if not rows:
        return cols
    for c in range(n_cols):
        total = numeric = 0
        for row in rows:
            if c >= len(row):
                continue
            t = (row[c] or "").strip()
            if not t:
                continue
            total += 1
            if _NUMERIC_RE.match(t):
                numeric += 1
        if total > 0 and numeric / total >= 0.5:
            cols.add(c)
    return cols


def _add_caption(doc_docx, caption: str) -> None:
    para = doc_docx.add_paragraph()
    set_paragraph_spacing(para, before_twips=60, after_twips=180, line_multiple=1.2)
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run(caption)
    apply_text_style(run, T.TEXT_DISCLAIMER, override_italic=True)
