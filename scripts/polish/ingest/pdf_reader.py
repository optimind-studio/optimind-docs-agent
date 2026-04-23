"""PDF ingest — pdfplumber + pymupdf → token stream.

Replaces the old `pdf_to_docx.py` path. The goal is to emit the SAME token
schema as `docx_reader.read()` so downstream flatten → tokenize → classify
→ render keeps working unchanged.

Strategy per page:
  1. Use pdfplumber to find tables (fast, text-based). Each table becomes a
     `table` token.
  2. Use pdfplumber to extract text lines, grouped into paragraphs by
     vertical gap. Each paragraph emits a `paragraph` token with synthetic
     heading_level_hint / shading / ordered-list cues derived from font
     size and indentation.
  3. Use pymupdf to pull embedded images; those that don't intersect a
     pdfplumber table bbox become `image` tokens (likely charts).

We preserve source order by ordering tokens per page by the top-y of their
bounding box (or table bbox).

Caveats:
  - pdfplumber can't detect multi-row header table structure reliably; we
    rely on the classifier's header-detection heuristic.
  - OCR'd/scanned PDFs without text layer produce no paragraphs → caller
    sees an empty document and will need OCR out-of-band.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator


_HEADING_SIZE_H1 = 17.0
_HEADING_SIZE_H2 = 13.5
_HEADING_SIZE_H3 = 12.0
_BOLD_KEYWORDS = ("Bold", "Black", "Heavy", "Semibold", "SemiBold", "Demi")


def read(path: Path) -> Iterator[dict]:
    """Yield tokens in source order across all PDF pages."""
    import pdfplumber
    import fitz  # pymupdf

    source_index = [0]   # mutable holder for nested fns

    with pdfplumber.open(str(path)) as pdf, fitz.open(str(path)) as mupdf:
        for page_idx, page in enumerate(pdf.pages):
            mu_page = mupdf.load_page(page_idx)

            table_bboxes = _find_tables(page)

            # Collect per-page tokens with their (page, top-y) ordering key.
            per_page: list[tuple[float, dict]] = []

            # Tables
            for tb_bbox, tb_tok_rows in table_bboxes:
                per_page.append((tb_bbox[1], _make_table_token(tb_tok_rows, source_index)))

            # Paragraphs (lines → paragraph groups)
            for top_y, tok in _extract_paragraphs(page, table_bboxes, source_index):
                per_page.append((top_y, tok))

            # Images (pymupdf)
            for top_y, tok in _extract_images(mu_page, table_bboxes, source_index):
                per_page.append((top_y, tok))

            per_page.sort(key=lambda p: p[0])
            for _, tok in per_page:
                yield tok


# ── tables ─────────────────────────────────────────────────────────────────

def _find_tables(page) -> list[tuple[tuple[float, float, float, float], list[list[dict]]]]:
    """Return [((x0, top, x1, bottom), rows)] for each table on the page."""
    out: list[tuple[tuple[float, float, float, float], list[list[dict]]]] = []
    try:
        tables = page.find_tables()
    except Exception:
        return out
    for t in tables:
        try:
            rows_raw = t.extract() or []
            bbox = t.bbox  # (x0, top, x1, bottom)
        except Exception:
            continue
        rows: list[list[dict]] = []
        for r in rows_raw:
            row: list[dict] = []
            for cell in r:
                text = (cell or "").strip()
                row.append({
                    "text": text,
                    "runs": [{"text": text, "bold": False, "italic": False}],
                    "shading_hex": None,
                    "colspan": 1,
                    "vmerge_continuation": False,
                    "nested_tables": [],
                })
            rows.append(row)
        out.append((bbox, rows))
    return out


def _make_table_token(rows: list[list[dict]], source_index) -> dict:
    tok = {
        "kind": "table",
        "source_index": source_index[0],
        "rows": rows,
        "widths": None,
        "n_rows": len(rows),
        "n_cols": max((len(r) for r in rows), default=0),
        "is_nested": False,
        "element": None,
    }
    source_index[0] += 1
    return tok


# ── paragraphs ──────────────────────────────────────────────────────────────

def _extract_paragraphs(page, table_bboxes, source_index) -> list[tuple[float, dict]]:
    """Group page words into paragraph tokens. Heading level is inferred
    from font size; text inside any table bbox is skipped (it lives in the
    table token instead).
    """
    try:
        words = page.extract_words(
            keep_blank_chars=False,
            use_text_flow=True,
            extra_attrs=["fontname", "size"],
        )
    except Exception:
        return []

    # Drop words that fall inside any table bbox (avoid duplication).
    words = [w for w in words if not _inside_any(w, table_bboxes)]
    if not words:
        return []

    # Group into lines by nearly-equal 'top'
    lines: list[list[dict]] = []
    current: list[dict] = []
    prev_top: float | None = None
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if prev_top is not None and abs(w["top"] - prev_top) > 3:
            if current:
                lines.append(current)
                current = []
        current.append(w)
        prev_top = w["top"]
    if current:
        lines.append(current)

    # Now group lines into paragraphs — break when vertical gap is large
    # or when font size changes significantly (likely a new heading).
    paragraphs: list[list[list[dict]]] = []
    cur_para: list[list[dict]] = []
    last_bottom: float | None = None
    last_size: float | None = None
    for line in lines:
        avg_top = sum(w["top"] for w in line) / len(line)
        sizes = [w.get("size", 0) for w in line if w.get("size")]
        avg_size = sum(sizes) / len(sizes) if sizes else 0
        if cur_para:
            gap = avg_top - (last_bottom or avg_top)
            size_jump = abs(avg_size - (last_size or avg_size)) > 2
            if gap > 8 or size_jump:
                paragraphs.append(cur_para)
                cur_para = []
        cur_para.append(line)
        last_bottom = max(w["bottom"] for w in line)
        last_size = avg_size
    if cur_para:
        paragraphs.append(cur_para)

    tokens: list[tuple[float, dict]] = []
    for para in paragraphs:
        top_y = min(w["top"] for line in para for w in line)
        tok = _paragraph_from_lines(para, source_index)
        if tok is not None:
            tokens.append((top_y, tok))
    return tokens


def _inside_any(word, table_bboxes) -> bool:
    wx0, wy0 = word["x0"], word["top"]
    wx1, wy1 = word["x1"], word["bottom"]
    for (x0, y0, x1, y1), _ in table_bboxes:
        if wx0 >= x0 and wy0 >= y0 and wx1 <= x1 and wy1 <= y1:
            return True
    return False


def _paragraph_from_lines(para, source_index) -> dict | None:
    text_parts = []
    runs: list[dict] = []
    all_words = []
    for line in para:
        line_text = " ".join(w["text"] for w in line)
        text_parts.append(line_text)
        all_words.extend(line)
    text = "\n".join(text_parts).strip()
    if not text:
        return None

    sizes = [w.get("size", 0) for w in all_words if w.get("size")]
    avg_size = sum(sizes) / len(sizes) if sizes else 0
    fonts = [w.get("fontname", "") for w in all_words]
    is_bold = any(any(kw in (f or "") for kw in _BOLD_KEYWORDS) for f in fonts)

    hint = _size_to_heading(avg_size)
    if hint is None and is_bold and len(text) < 60 and "\n" not in text:
        hint = 3  # short bold → H3 ambiguity; classifier will decide

    runs.append({"text": text, "bold": is_bold, "italic": False})

    tok = {
        "kind": "paragraph",
        "source_index": source_index[0],
        "text": text,
        "runs": runs,
        "style_name": "",
        "heading_level_hint": hint,
        "shading_hex": None,
        "numbering": _infer_numbering(text),
        "has_page_break": False,
        "inline_images": [],
        "floating_shapes": [],
        "is_vml_hr": False,
        "element": None,
        "_pdf_font_size": avg_size,
    }
    source_index[0] += 1
    return tok


def _size_to_heading(size: float) -> int | None:
    if size >= _HEADING_SIZE_H1:
        return 1
    if size >= _HEADING_SIZE_H2:
        return 2
    if size >= _HEADING_SIZE_H3:
        return 3
    return None


def _infer_numbering(text: str) -> dict | None:
    """Infer list-ness from bullet glyph or N. prefix."""
    stripped = text.lstrip()
    if stripped[:2] in ("• ", "- ", "* "):
        return {"ilvl": 0, "numId": -1, "style_ordered": False}
    import re
    if re.match(r'^\d+[\.\)]\s', stripped):
        return {"ilvl": 0, "numId": -1, "style_ordered": True}
    return None


# ── images ─────────────────────────────────────────────────────────────────

def _extract_images(mu_page, table_bboxes, source_index) -> list[tuple[float, dict]]:
    out: list[tuple[float, dict]] = []
    try:
        imgs = mu_page.get_images(full=True)
    except Exception:
        return out
    page_h = mu_page.rect.height
    for img in imgs:
        xref = img[0]
        try:
            base = mu_page.parent.extract_image(xref)
        except Exception:
            continue
        if not base or not base.get("image"):
            continue
        # Best-effort bbox via image rectangles
        try:
            rects = mu_page.get_image_rects(xref)
        except Exception:
            rects = []
        if rects:
            r = rects[0]
            top_y = r.y0
            # Skip decorative images — tiny, or overlapping a table
            if r.width * r.height < 40_000:
                continue
            if any(_rect_overlaps(r, bbox) for bbox, _ in table_bboxes):
                continue
        else:
            top_y = page_h  # put at bottom if unknown

        ext = base.get("ext") or "png"
        tok = {
            "kind": "image",
            "source_index": source_index[0],
            "image_bytes": base["image"],
            "image_format": ext,
            "lifted_from": "pdf_image",
        }
        source_index[0] += 1
        out.append((top_y, tok))
    return out


def _rect_overlaps(rect, bbox) -> bool:
    x0, y0, x1, y1 = bbox
    return not (rect.x1 < x0 or rect.x0 > x1 or rect.y1 < y0 or rect.y0 > y1)
