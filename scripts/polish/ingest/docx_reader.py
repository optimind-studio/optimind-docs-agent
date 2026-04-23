"""DOCX ingest — walk the body tree once, yield low-level tokens in source order.

Token schema (see model-level docstring). Each token carries a back-reference
to the source XML element for downstream flatten / debug steps.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from docx import Document as _OpenDocx
from docx.oxml.ns import qn

VML_NS = "urn:schemas-microsoft-com:vml"
O_NS   = "urn:schemas-microsoft-com:office:office"
WP_NS  = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
A_NS   = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS   = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC_NS  = "http://schemas.openxmlformats.org/markup-compatibility/2006"


_HEADING_NUMERIC = [
    (re.compile(r'^\d+\.\d+\.\d+\s+\S'), 3),
    (re.compile(r'^\d+\.\d+\s+\S'),      2),
    (re.compile(r'^\d+\.\s+\S'),         1),
]

_HEADING_STYLE_RE = re.compile(r'^Heading\s?(\d+)$', re.IGNORECASE)

_LIST_STYLES = (
    "ListBullet", "ListBullet2", "ListBullet3",
    "ListNumber", "ListNumber2", "ListNumber3",
    "ListParagraph",
)


def read(path: Path) -> Iterator[dict]:
    """Yield low-level tokens from a .docx source in body order."""
    doc = _OpenDocx(str(path))
    body = doc.element.body
    rels = doc.part.rels

    source_index = 0
    for child in list(body):
        tag = _local(child.tag)
        if tag == "p":
            token = _paragraph_token(child, rels, source_index)
            if token is not None:
                yield token
                source_index += 1
        elif tag == "tbl":
            yield _table_token(child, rels, source_index)
            source_index += 1
        elif tag == "sectPr":
            continue                   # section properties are preserved elsewhere
        else:                          # w:bookmarkStart etc — rare; skip silently
            continue


# ── paragraph ───────────────────────────────────────────────────────────────

def _paragraph_token(p_el, rels, source_index: int) -> dict | None:
    """Build a token dict for a <w:p> element."""
    runs = _extract_runs(p_el)
    text = "".join(r["text"] for r in runs)

    style_name = _paragraph_style_name(p_el)
    heading_level_hint = _infer_heading_level(p_el, text, style_name)
    shading_hex = _paragraph_shading(p_el)
    numbering = _paragraph_numbering(p_el)
    if numbering is None and style_name in _LIST_STYLES:
        ordered = style_name.startswith("ListNumber")
        numbering = {"ilvl": 0, "numId": -1, "style_ordered": ordered}
    has_page_break = _has_page_break(p_el)

    inline_images, floating_shapes = _extract_drawings(p_el, rels)
    is_vml_hr = _is_vml_horizontal_rule(p_el, has_text=bool(text.strip()))

    return {
        "kind": "paragraph",
        "source_index": source_index,
        "text": text,
        "runs": runs,
        "style_name": style_name,
        "heading_level_hint": heading_level_hint,
        "shading_hex": shading_hex,
        "numbering": numbering,
        "has_page_break": has_page_break,
        "inline_images": inline_images,
        "floating_shapes": floating_shapes,
        "is_vml_hr": is_vml_hr,
        "element": p_el,
    }


def _extract_runs(p_el) -> list[dict]:
    """Flatten all <w:r> children into a list of run dicts."""
    out: list[dict] = []
    for r in p_el.iter(qn("w:r")):
        # Skip runs inside drawings — those are shape contents, captured separately.
        if _run_is_inside_drawing(r, p_el):
            continue
        chunks = [(t.text or "") for t in r.findall(qn("w:t"))]
        text = "".join(chunks)
        if not text:
            continue
        rPr = r.find(qn("w:rPr"))
        bold = _has_toggle(rPr, "w:b")
        italic = _has_toggle(rPr, "w:i")
        out.append({"text": text, "bold": bold, "italic": italic})
    return out


def _run_is_inside_drawing(r_el, p_el) -> bool:
    """True if r_el has any ancestor drawing element before reaching p_el."""
    cur = r_el.getparent()
    while cur is not None and cur is not p_el:
        lt = _local(cur.tag)
        if lt in ("drawing", "pict", "txbxContent"):
            return True
        cur = cur.getparent()
    return False


def _has_toggle(rPr, tag_qn: str) -> bool:
    if rPr is None:
        return False
    el = rPr.find(qn(tag_qn))
    if el is None:
        return False
    val = el.get(qn("w:val"))
    # absent or "1"/"true" means on
    return val is None or val in ("1", "true", "on")


def _paragraph_style_name(p_el) -> str:
    pPr = p_el.find(qn("w:pPr"))
    if pPr is None:
        return ""
    pStyle = pPr.find(qn("w:pStyle"))
    if pStyle is None:
        return ""
    return pStyle.get(qn("w:val")) or ""


def _paragraph_shading(p_el) -> str | None:
    """Return the paragraph-level shading fill hex (uppercase, no '#') or None."""
    pPr = p_el.find(qn("w:pPr"))
    if pPr is None:
        return None
    shd = pPr.find(qn("w:shd"))
    if shd is None:
        return None
    fill = shd.get(qn("w:fill"))
    if not fill or fill.lower() == "auto":
        return None
    return fill.upper()


def _paragraph_numbering(p_el) -> dict | None:
    pPr = p_el.find(qn("w:pPr"))
    if pPr is None:
        return None
    numPr = pPr.find(qn("w:numPr"))
    if numPr is None:
        return None
    ilvl_el = numPr.find(qn("w:ilvl"))
    numId_el = numPr.find(qn("w:numId"))
    return {
        "ilvl":  int(ilvl_el.get(qn("w:val")))  if ilvl_el is not None else 0,
        "numId": int(numId_el.get(qn("w:val"))) if numId_el is not None else 0,
    }


def _has_page_break(p_el) -> bool:
    for br in p_el.iter(qn("w:br")):
        if br.get(qn("w:type")) == "page":
            return True
    pPr = p_el.find(qn("w:pPr"))
    if pPr is not None and pPr.find(qn("w:pageBreakBefore")) is not None:
        return True
    return False


def _infer_heading_level(p_el, text: str, style_name: str) -> int | None:
    """Return 1/2/3 if this paragraph looks like a heading, else None."""
    if not text.strip():
        return None

    m = _HEADING_STYLE_RE.match(style_name or "")
    if m:
        lvl = int(m.group(1))
        if lvl in (1, 2, 3):
            return lvl
        if lvl == 4:
            return 3  # collapse H4 to H3
        if lvl >= 5:
            return 3

    for rx, lvl in _HEADING_NUMERIC:
        if rx.match(text):
            return lvl

    # Short bold paragraph → ambiguous heading candidate (classifier decides).
    # But: skip if the text is pure numeric / currency / percent — those are
    # KPI values orphaned from their labels by design-tool fragmentation and
    # must NOT become headings.
    stripped = text.strip()
    if _looks_pure_numeric(stripped):
        return None

    has_bold = any((r.find(qn("w:rPr")) is not None and
                    r.find(qn("w:rPr")).find(qn("w:b")) is not None)
                   for r in p_el.iter(qn("w:r")))
    pPr = p_el.find(qn("w:pPr"))
    has_num = pPr is not None and pPr.find(qn("w:numPr")) is not None
    if has_bold and not has_num and 0 < len(text) < 60 and "\n" not in text:
        return 3
    return None


_PURE_NUMERIC_RE_INGEST = re.compile(
    r'^\s*[\$€£¥]?\s*[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*[KkMmBb]?\s*%?\s*$'
    r'|^\s*[\$€£¥]?\s*[-+]?\d+(?:\.\d+)?\s*[KkMmBb]?\s*%?\s*$'
)


def _looks_pure_numeric(text: str) -> bool:
    """Matches '$61,974' / '24.9%' / '15,081' / '$350K' — no prose."""
    if not text:
        return False
    return bool(_PURE_NUMERIC_RE_INGEST.match(text))


# ── drawings / floating shapes ──────────────────────────────────────────────

def _extract_drawings(p_el, rels) -> tuple[list[dict], list[dict]]:
    """Return (inline_images, floating_shapes).

    inline_images: simple picture drawings anchored inline with text.
    floating_shapes: text boxes, drawings anchored to page — these will be
        flattened (de-anchored) in the flatten step. Each floating shape
        carries its anchor position (x, y in EMUs) and extent when available
        so that downstream `reconstruct` can rebuild visual grids.

    Handles `<mc:AlternateContent>` correctly: prefers the `<mc:Choice>`
    branch (modern DrawingML), ignores the `<mc:Fallback>` VML duplicate so
    content isn't emitted twice. Standalone VML shapes (not inside an
    AlternateContent block) are still processed as first-class floats.
    """
    inlines: list[dict] = []
    floats: list[dict] = []

    # Walk every <w:drawing> that is NOT inside an mc:Fallback branch.
    for drawing in p_el.iter(qn("w:drawing")):
        if _inside_fallback(drawing, p_el):
            continue
        is_inline = drawing.find(f"{{{WP_NS}}}inline") is not None
        anchor_info = _drawing_anchor_info(drawing)

        # Pictures (images) — one drawing can contain one pic
        for blip in drawing.iter(f"{{{A_NS}}}blip"):
            rid = blip.get(f"{{{R_NS}}}embed") or blip.get(f"{{{R_NS}}}link")
            image_info = _resolve_image_rel(rels, rid)
            if image_info is None:
                continue
            if is_inline:
                inlines.append(image_info)
            else:
                floats.append({"kind": "image", **image_info, **anchor_info})

        # Text boxes — prefer the a:txBody chain (modern); only if none found,
        # fall back to w:txbxContent. Many drawings nest BOTH (a:txBody wraps
        # w:txbxContent), so double-iterating the same tree doubled content.
        tb_text = _extract_text_from_txbody(drawing)
        if tb_text:
            floats.append({"kind": "textbox", "text": tb_text, **anchor_info})

    # Legacy VML shapes — skip any inside a w:drawing (already processed) or
    # mc:Fallback (dupe of mc:Choice).
    for vshape in p_el.iter(f"{{{VML_NS}}}shape"):
        if _inside_fallback(vshape, p_el):
            continue
        if _inside_drawing(vshape, p_el):
            continue
        vml_anchor = _vml_anchor_info(vshape)
        tb_text = _extract_text_from_txbody(vshape)
        if tb_text:
            floats.append({"kind": "textbox", "text": tb_text, **vml_anchor})
    return inlines, floats


def _inside_fallback(el, stop_at) -> bool:
    cur = el.getparent()
    while cur is not None and cur is not stop_at:
        if cur.tag == f"{{{MC_NS}}}Fallback":
            return True
        cur = cur.getparent()
    return False


def _inside_drawing(el, stop_at) -> bool:
    cur = el.getparent()
    while cur is not None and cur is not stop_at:
        if cur.tag == qn("w:drawing"):
            return True
        cur = cur.getparent()
    return False


def _extract_text_from_txbody(root_el) -> str:
    """Gather textbox text from a single shape/drawing root.

    Modern: <a:txBody>/<w:txbxContent>/<w:p>/<w:r>/<w:t>.
    We iterate text runs once; dedupe by text-run identity to avoid
    double-counting when a:txBody wraps w:txbxContent.
    """
    seen_ids: set[int] = set()
    chunks: list[str] = []
    # Collect w:t elements whose nearest ancestor in {a:txBody, w:txbxContent}
    # is the first such ancestor inside root_el — i.e. the text content.
    for t_el in root_el.iter(qn("w:t")):
        # Skip if no ancestor textbox/body wrapper up to root_el.
        cur = t_el.getparent()
        inside_body = False
        while cur is not None and cur is not root_el:
            if cur.tag in (f"{{{A_NS}}}txBody", qn("w:txbxContent")):
                inside_body = True
                break
            cur = cur.getparent()
        if not inside_body:
            continue
        if id(t_el) in seen_ids:
            continue
        seen_ids.add(id(t_el))
        if t_el.text:
            chunks.append(t_el.text)
    return "\n".join(chunks).strip()


def _drawing_anchor_info(drawing) -> dict:
    """Return {anchor_x, anchor_y, anchor_cx, anchor_cy, anchor_relH, anchor_relV}
    in EMUs for a <w:drawing>. Missing values → None. Inline drawings have no
    position but still carry an extent.
    """
    out = {
        "anchor_x": None,
        "anchor_y": None,
        "anchor_cx": None,
        "anchor_cy": None,
        "anchor_relH": None,
        "anchor_relV": None,
    }
    anchor_el = drawing.find(f"{{{WP_NS}}}anchor")
    if anchor_el is not None:
        posH = anchor_el.find(f"{{{WP_NS}}}positionH")
        posV = anchor_el.find(f"{{{WP_NS}}}positionV")
        extent = anchor_el.find(f"{{{WP_NS}}}extent")
        if posH is not None:
            out["anchor_relH"] = posH.get("relativeFrom")
            off = posH.find(f"{{{WP_NS}}}posOffset")
            if off is not None and off.text is not None:
                try:
                    out["anchor_x"] = int(off.text)
                except ValueError:
                    pass
        if posV is not None:
            out["anchor_relV"] = posV.get("relativeFrom")
            off = posV.find(f"{{{WP_NS}}}posOffset")
            if off is not None and off.text is not None:
                try:
                    out["anchor_y"] = int(off.text)
                except ValueError:
                    pass
        if extent is not None:
            try:
                out["anchor_cx"] = int(extent.get("cx") or 0) or None
                out["anchor_cy"] = int(extent.get("cy") or 0) or None
            except ValueError:
                pass
    else:
        # Inline drawing — only extent, no position
        inline_el = drawing.find(f"{{{WP_NS}}}inline")
        if inline_el is not None:
            extent = inline_el.find(f"{{{WP_NS}}}extent")
            if extent is not None:
                try:
                    out["anchor_cx"] = int(extent.get("cx") or 0) or None
                    out["anchor_cy"] = int(extent.get("cy") or 0) or None
                except ValueError:
                    pass
    return out


def _vml_anchor_info(vshape) -> dict:
    """Pull a rough (x, y) for VML <v:shape> via its `style="..."` attribute.
    Style values are in pt; convert to EMU (1 pt = 12700 EMU).
    """
    out = {
        "anchor_x": None,
        "anchor_y": None,
        "anchor_cx": None,
        "anchor_cy": None,
        "anchor_relH": None,
        "anchor_relV": None,
    }
    style = vshape.get("style") or ""
    if not style:
        return out
    parts = [p.strip() for p in style.split(";") if p.strip()]
    kv = {}
    for p in parts:
        if ":" in p:
            k, v = p.split(":", 1)
            kv[k.strip().lower()] = v.strip()
    def _pt_to_emu(v: str) -> int | None:
        if not v:
            return None
        v = v.replace(",", ".")
        try:
            if v.endswith("pt"):
                return int(float(v[:-2]) * 12700)
            if v.endswith("in"):
                return int(float(v[:-2]) * 914400)
            if v.endswith("px"):
                return int(float(v[:-2]) * 9525)
        except ValueError:
            return None
        return None
    for k, emu_key in (("margin-left", "anchor_x"), ("margin-top", "anchor_y"),
                       ("left", "anchor_x"), ("top", "anchor_y"),
                       ("width", "anchor_cx"), ("height", "anchor_cy")):
        if k in kv:
            v = _pt_to_emu(kv[k])
            if v is not None and out[emu_key] is None:
                out[emu_key] = v
    return out


def _resolve_image_rel(rels, rid: str | None) -> dict | None:
    if not rid:
        return None
    rel = rels.get(rid)
    if rel is None:
        return None
    try:
        blob = rel.target_part.blob
        ext = Path(rel.target_ref).suffix.lower().lstrip(".") or "bin"
        return {"bytes": blob, "format": ext}
    except Exception:
        return None


def _is_vml_horizontal_rule(p_el, has_text: bool) -> bool:
    """VML decorative hr: empty paragraph containing v:rect with o:hr='t'."""
    if has_text:
        return False
    for rect in p_el.iter(f"{{{VML_NS}}}rect"):
        if rect.get(f"{{{O_NS}}}hr") == "t":
            return True
    return False


# ── table ───────────────────────────────────────────────────────────────────

def _table_token(tbl_el, rels, source_index: int) -> dict:
    rows: list[list[dict]] = []
    for tr in tbl_el.findall(qn("w:tr")):
        row: list[dict] = []
        for tc in tr.findall(qn("w:tc")):
            row.append(_cell_dict(tc, rels))
        rows.append(row)

    n_rows = len(rows)
    n_cols = max((len(r) for r in rows), default=0)
    widths = _table_widths(tbl_el)

    return {
        "kind": "table",
        "source_index": source_index,
        "rows": rows,
        "widths": widths,
        "n_rows": n_rows,
        "n_cols": n_cols,
        "is_nested": False,
        "element": tbl_el,
    }


def _cell_dict(tc_el, rels) -> dict:
    """Build a cell dict. Nested tables are captured as `nested` list."""
    tcPr = tc_el.find(qn("w:tcPr"))
    # merge hints
    gridSpan = _int_attr(tcPr, "w:gridSpan", default=1) if tcPr is not None else 1
    vMerge_el = tcPr.find(qn("w:vMerge")) if tcPr is not None else None
    vmerge_val = vMerge_el.get(qn("w:val")) if vMerge_el is not None else None
    # vMerge without val = continuation of merge above; with val="restart" = starts merge
    is_vmerge_continuation = vMerge_el is not None and vmerge_val != "restart"
    # shading
    shading_hex = None
    if tcPr is not None:
        shd = tcPr.find(qn("w:shd"))
        if shd is not None:
            fill = shd.get(qn("w:fill"))
            if fill and fill.lower() != "auto":
                shading_hex = fill.upper()

    runs: list[dict] = []
    nested: list[dict] = []
    for p_el in tc_el.findall(qn("w:p")):
        runs.extend(_extract_runs(p_el))
    for inner_tbl in tc_el.findall(qn("w:tbl")):
        nt = _table_token(inner_tbl, rels, -1)
        nt["is_nested"] = True
        nested.append(nt)

    text = "".join(r["text"] for r in runs).strip()
    return {
        "text": text,
        "runs": runs,
        "shading_hex": shading_hex,
        "colspan": max(1, gridSpan),
        "vmerge_continuation": is_vmerge_continuation,
        "nested_tables": nested,
    }


def _table_widths(tbl_el) -> list[int] | None:
    grid = tbl_el.find(qn("w:tblGrid"))
    if grid is None:
        return None
    widths: list[int] = []
    for gc in grid.findall(qn("w:gridCol")):
        w = gc.get(qn("w:w"))
        if w is None:
            continue
        try:
            widths.append(int(w))
        except ValueError:
            continue
    return widths or None


# ── helpers ─────────────────────────────────────────────────────────────────

def _int_attr(el, tag: str, default: int = 0) -> int:
    if el is None:
        return default
    child = el.find(qn(tag))
    if child is None:
        return default
    v = child.get(qn("w:val"))
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag
