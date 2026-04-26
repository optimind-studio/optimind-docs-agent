"""audit_parse.py — produce a structured content manifest from any input format.

For PDF: uses pdfplumber page-by-page extraction with column detection,
KPI strip fusion, action card detection, and cross-page table merging.

For docx: uses python-docx paragraph/table iteration (already reliable;
manifest is a consistency pass).

Output: <state_dir>/manifest.md
"""
from __future__ import annotations

import re
import logging
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── constants ──────────────────────────────────────────────────────────────────

_HEADING_SIZE_H1 = 17.0
_HEADING_SIZE_H2 = 13.5
_HEADING_SIZE_H3 = 12.0
_BOLD_KEYWORDS = ("Bold", "Black", "Heavy", "Semibold", "SemiBold", "Demi")

_SECTION_LABEL_RE = re.compile(r'^\d{1,2}\s*[—–\-]\s*[A-Z][A-Z\s]+$')
_NUMERIC_VALUE_RE = re.compile(r'^\$?[\d,.]+[KMB%]?$')

_COMPARISON_KEYWORDS = (
    "worked", "positive", "strength", "improvement",
    "needs", "weakness", "challenge",
)


# ── public entry point ─────────────────────────────────────────────────────────

def produce_manifest(input_path: Path, state_dir: Path) -> Path:
    """Read *input_path* (PDF or docx) and write ``state_dir/manifest.md``.

    Returns the path to the written manifest file.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    suffix = input_path.suffix.lower()

    if suffix == ".pdf":
        lines = _extract_pdf(input_path)
    elif suffix in (".docx", ".doc"):
        lines = _extract_docx(input_path)
    else:
        raise ValueError(f"audit_parse: unsupported format '{suffix}'")

    manifest_path = state_dir / "manifest.md"
    manifest_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("audit_parse: manifest written → %s", manifest_path)
    return manifest_path


# ── PDF extraction ─────────────────────────────────────────────────────────────

def _extract_pdf(path: Path) -> list[str]:
    import pdfplumber  # type: ignore

    out: list[str] = []

    with pdfplumber.open(str(path)) as pdf:
        total_pages = len(pdf.pages)

        # Manifest header
        out += [
            "# Document Manifest",
            f"Source: {path.name}",
            f"Pages: {total_pages}",
            f"Extracted: {date.today().isoformat()}",
            "",
            "---",
            "",
        ]

        # State for cross-page table merging
        prev_table_block_idx: int | None = None   # index into `out` of last table header line
        prev_table_col_count: int | None = None
        prev_table_rows_idx: int | None = None    # line index where rows start

        for page_idx, page in enumerate(pdf.pages):
            page_num = page_idx + 1
            try:
                page_lines, table_col_count = _process_pdf_page(
                    page, page_num, prev_table_col_count
                )
                # Cross-page table merging: detect if this page starts with a
                # continued table (first block is a [TABLE — continued] marker).
                if (
                    table_col_count is not None
                    and prev_table_col_count is not None
                    and table_col_count == prev_table_col_count
                    and prev_table_rows_idx is not None
                    and page_lines
                    and page_lines[0].startswith("[TABLE — continued]")
                ):
                    # Strip the continued marker from this page's lines and
                    # insert the extra rows after the previous table's rows.
                    continued_rows = page_lines[1:]  # rows after the marker
                    insert_pos = prev_table_rows_idx
                    for i, row_line in enumerate(continued_rows):
                        out.insert(insert_pos + i, row_line)
                    # Remove pages that were already written; adjust prev pointer
                    prev_table_rows_idx = None
                    prev_table_col_count = None
                else:
                    out += page_lines
                    # Track the last table col count for next page
                    prev_table_col_count = table_col_count
                    # Record where the table rows are so we can insert into them
                    if table_col_count is not None:
                        # Find the last [TABLE …] block's first row in out
                        for rev_i in range(len(out) - 1, -1, -1):
                            if out[rev_i].startswith("| "):
                                prev_table_rows_idx = rev_i
                                break
                        else:
                            prev_table_rows_idx = None
                    else:
                        prev_table_rows_idx = None

            except Exception as exc:  # noqa: BLE001
                log.exception("audit_parse: page %d failed", page_num)
                out.append(f"<!-- Page {page_num} extraction failed: {exc} -->")
                out.append("")
                prev_table_col_count = None
                prev_table_rows_idx = None

    return out


def _process_pdf_page(page, page_num: int, prev_table_col_count: int | None) -> tuple[list[str], int | None]:
    """Extract blocks from one PDF page.

    Returns ``(lines, last_table_col_count)`` where *last_table_col_count* is
    ``None`` if the page does not end with a table.
    """
    page_width = float(page.width)

    # ── 1. Find tables ──────────────────────────────────────────────────────
    raw_tables = _pdf_find_tables(page)  # [(bbox, rows_2d)]
    table_bboxes = [t[0] for t in raw_tables]

    # ── 2. Extract words outside tables ────────────────────────────────────
    try:
        all_words = page.extract_words(
            keep_blank_chars=False,
            use_text_flow=True,
            extra_attrs=["size", "fontname", "stroking_color", "non_stroking_color"],
        )
    except Exception:
        all_words = []

    non_table_words = [w for w in all_words if not _word_inside_any(w, table_bboxes)]

    # ── 3. Column detection ─────────────────────────────────────────────────
    is_two_col, col_split_x = _detect_columns(non_table_words, page_width)
    layout = "two-column" if is_two_col else "single-column"

    # ── 4. Split words into column groups, then extract paragraphs ──────────
    if is_two_col and col_split_x is not None:
        left_words = [w for w in non_table_words if w["x0"] < col_split_x]
        right_words = [w for w in non_table_words if w["x0"] >= col_split_x]
        col_paras = [
            ("LEFT", _words_to_paras(left_words)),
            ("RIGHT", _words_to_paras(right_words)),
        ]
    else:
        col_paras = [("FULL", _words_to_paras(non_table_words))]

    # ── 5. Classify paragraphs ──────────────────────────────────────────────
    classified_cols: list[tuple[str, list[dict[str, Any]]]] = []
    for col_label, paras in col_paras:
        classified = [_classify_para(p) for p in paras]
        classified_cols.append((col_label, classified))

    # ── 6. Detect comparison panel (two-column specific) ───────────────────
    is_comparison = False
    if is_two_col and len(classified_cols) == 2:
        is_comparison = _detect_comparison_panel(classified_cols)

    # ── 7. KPI strip & action card fusion ─────────────────────────────────
    fused_cols: list[tuple[str, list[dict[str, Any]]]] = []
    for col_label, classified in classified_cols:
        fused = _fuse_kpi_strips(classified)
        fused = _fuse_action_cards(fused)
        fused_cols.append((col_label, fused))

    # ── 8. Build page lines ────────────────────────────────────────────────
    lines: list[str] = []
    lines.append(f"## Page {page_num}")
    lines.append(f"Layout: {layout}")
    lines.append("")

    if is_comparison:
        left_blocks = fused_cols[0][1] if fused_cols else []
        right_blocks = fused_cols[1][1] if len(fused_cols) > 1 else []
        lines += _render_comparison_panel(left_blocks, right_blocks)
    else:
        # Interleave tables with paragraph blocks by top-y position
        # Build a unified list of (top_y, kind, payload) entries
        entries: list[tuple[float, str, Any]] = []

        for _, (col_label, blocks) in enumerate(fused_cols):
            for blk in blocks:
                entries.append((blk["top_y"], "block", blk))

        for bbox, rows in raw_tables:
            entries.append((bbox[1], "table", (bbox, rows)))

        entries.sort(key=lambda e: e[0])

        last_was_table = False
        last_table_col_count_local: int | None = None

        for _, kind, payload in entries:
            if kind == "block":
                last_was_table = False
                lines += _render_block(payload)
            else:
                bbox, rows = payload
                tbl_lines, col_count = _render_table(
                    rows, prev_table_col_count, is_first_page_table=not last_was_table
                )
                lines += tbl_lines
                last_table_col_count_local = col_count
                last_was_table = True

        last_table_col_count_out = last_table_col_count_local

    lines.append("")
    lines.append("---")
    lines.append("")

    if is_comparison:
        last_table_col_count_out = None
    elif not any(k == "table" for _, k, _ in entries if True):
        last_table_col_count_out = None

    # Resolve scoping issue for is_comparison path
    if is_comparison:
        last_table_col_count_out = None

    return lines, last_table_col_count_out


def _pdf_find_tables(page) -> list[tuple[tuple[float, float, float, float], list[list[str]]]]:
    """Return [(bbox, rows_2d)] using pdfplumber's table finder."""
    out = []
    try:
        tables = page.find_tables(table_settings={"snap_tolerance": 3, "join_tolerance": 3})
    except Exception:
        return out
    for t in tables:
        try:
            bbox = t.bbox  # (x0, top, x1, bottom)
            rows_raw = t.extract() or []
        except Exception:
            continue
        rows_2d: list[list[str]] = []
        for r in rows_raw:
            rows_2d.append([(cell or "").strip() for cell in r])
        out.append((bbox, rows_2d))
    return out


def _word_inside_any(word: dict, table_bboxes: list[tuple]) -> bool:
    wx0, wy0 = word["x0"], word["top"]
    wx1, wy1 = word["x1"], word["bottom"]
    for x0, y0, x1, y1 in table_bboxes:
        if wx0 >= x0 and wy0 >= y0 and wx1 <= x1 and wy1 <= y1:
            return True
    return False


# ── column detection ──────────────────────────────────────────────────────────

def _detect_columns(words: list[dict], page_width: float) -> tuple[bool, float | None]:
    """Return (is_two_column, split_x).

    Build a histogram of word x0 values in 20px buckets.  If a gap of ≥ 20%
    of the page width exists with no word left-edges → two columns.
    """
    if not words or page_width <= 0:
        return False, None

    bucket_size = 20.0
    gap_threshold = page_width * 0.20
    counts: Counter[int] = Counter()
    for w in words:
        bucket = int(w["x0"] / bucket_size)
        counts[bucket] += 1

    # Find contiguous empty bucket runs
    max_bucket = max(counts.keys())
    best_gap_start: float | None = None
    best_gap_width = 0.0
    run_start: int | None = None
    for b in range(max_bucket + 1):
        if counts[b] == 0:
            if run_start is None:
                run_start = b
        else:
            if run_start is not None:
                gap_w = (b - run_start) * bucket_size
                if gap_w > best_gap_width:
                    best_gap_width = gap_w
                    best_gap_start = run_start * bucket_size
                run_start = None
    if run_start is not None:
        gap_w = (max_bucket + 1 - run_start) * bucket_size
        if gap_w > best_gap_width:
            best_gap_width = gap_w
            best_gap_start = run_start * bucket_size

    if best_gap_width >= gap_threshold and best_gap_start is not None:
        split_x = best_gap_start + best_gap_width / 2.0
        return True, split_x

    return False, None


# ── words → paragraphs ────────────────────────────────────────────────────────

def _words_to_paras(words: list[dict]) -> list[dict]:
    """Group words into lines then into paragraphs. Returns list of para dicts."""
    if not words:
        return []

    # Sort by (top, x0)
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))

    # Group into lines (within 3px of each other vertically)
    lines: list[list[dict]] = []
    current: list[dict] = []
    prev_top: float | None = None
    for w in sorted_words:
        if prev_top is not None and abs(w["top"] - prev_top) > 3:
            if current:
                lines.append(current)
            current = []
        current.append(w)
        prev_top = w["top"]
    if current:
        lines.append(current)

    if not lines:
        return []

    # Group lines into paragraphs (gap > 1.5× avg line height → new para)
    def _line_height(line: list[dict]) -> float:
        tops = [w["top"] for w in line]
        bots = [w["bottom"] for w in line]
        return (max(bots) - min(tops)) if bots else 12.0

    paras: list[list[list[dict]]] = []
    cur_para: list[list[dict]] = [lines[0]]
    for line in lines[1:]:
        prev_line = cur_para[-1]
        prev_bottom = max(w["bottom"] for w in prev_line)
        cur_top = min(w["top"] for w in line)
        lh = _line_height(prev_line)
        gap = cur_top - prev_bottom
        if gap > 1.5 * lh:
            paras.append(cur_para)
            cur_para = []
        cur_para.append(line)
    paras.append(cur_para)

    result: list[dict] = []
    for para_lines in paras:
        all_words_in_para = [w for line in para_lines for w in line]
        text_lines = [" ".join(w["text"] for w in line) for line in para_lines]
        text = "\n".join(text_lines).strip()
        if not text:
            continue

        sizes = [w.get("size", 0) for w in all_words_in_para if w.get("size")]
        avg_size = sum(sizes) / len(sizes) if sizes else 0
        top_y = min(w["top"] for w in all_words_in_para)

        fontnames = [w.get("fontname", "") or "" for w in all_words_in_para]
        is_bold = any(any(kw in fn for kw in _BOLD_KEYWORDS) for fn in fontnames)
        word_count = len(text.split())

        result.append({
            "text": text,
            "avg_size": avg_size,
            "is_bold": is_bold,
            "word_count": word_count,
            "top_y": top_y,
            "all_words": all_words_in_para,
        })
    return result


# ── paragraph classifier ───────────────────────────────────────────────────────

def _classify_para(para: dict) -> dict:
    """Add 'kind' to a paragraph dict based on font size and text patterns."""
    size = para["avg_size"]
    text = para["text"]

    if size >= _HEADING_SIZE_H1:
        kind = "HEADING-1"
    elif size >= _HEADING_SIZE_H2:
        kind = "HEADING-2"
    elif size >= _HEADING_SIZE_H3:
        kind = "HEADING-3"
    elif _SECTION_LABEL_RE.match(text.strip()):
        kind = "SECTION-LABEL"
    else:
        kind = "PARAGRAPH"

    return {**para, "kind": kind}


# ── KPI strip fusion ──────────────────────────────────────────────────────────

def _is_numeric_value(text: str) -> bool:
    """Return True if *text* looks like a KPI metric value."""
    return bool(_NUMERIC_VALUE_RE.match(text.strip()))


def _fuse_kpi_strips(blocks: list[dict]) -> list[dict]:
    """Detect (value, label, optional-delta) triplets and fuse into KPI-STRIP blocks."""
    if not blocks:
        return blocks

    # A KPI card is a short paragraph (≤6 words) where at least one adjacent
    # pair has value + label characteristics.
    # Strategy: scan windows of 2-3 consecutive short paragraphs.

    out: list[dict] = []
    i = 0
    while i < len(blocks):
        blk = blocks[i]
        if blk.get("kind") != "PARAGRAPH" or blk["word_count"] > 6:
            out.append(blk)
            i += 1
            continue

        # Collect a run of short paragraphs
        run: list[dict] = []
        j = i
        while j < len(blocks) and blocks[j].get("kind") == "PARAGRAPH" and blocks[j]["word_count"] <= 6:
            run.append(blocks[j])
            j += 1

        if len(run) < 2:
            out.extend(run)
            i = j
            continue

        # Try to parse KPI cards out of the run
        kpi_cards: list[dict] = []
        k = 0
        while k < len(run):
            text_k = run[k]["text"].strip()
            if _is_numeric_value(text_k):
                value = text_k
                label = run[k + 1]["text"].strip() if k + 1 < len(run) else ""
                delta = ""
                if k + 2 < len(run) and run[k + 2]["word_count"] <= 6:
                    candidate_delta = run[k + 2]["text"].strip()
                    if any(c in candidate_delta for c in ["+", "-", "vs", "▲", "▼"]):
                        delta = candidate_delta
                        k += 3
                    else:
                        k += 2
                else:
                    k += 2
                kpi_cards.append({"value": value, "label": label, "delta": delta})
            else:
                # Not a KPI pattern — emit as-is later
                kpi_cards = []
                break

        if len(kpi_cards) >= 2:
            card_lines = [f"[KPI-STRIP — {len(kpi_cards)} cards]"]
            for card in kpi_cards:
                parts = [f"Value: {card['value']}", f"Label: {card['label']}"]
                if card["delta"]:
                    parts.append(f"Delta: {card['delta']}")
                card_lines.append(" | ".join(parts))
            out.append({
                "kind": "KPI-STRIP",
                "text": "\n".join(card_lines),
                "top_y": run[0]["top_y"],
                "word_count": 0,
                "avg_size": 0,
                "is_bold": False,
            })
        else:
            out.extend(run)

        i = j

    return out


# ── action card fusion ────────────────────────────────────────────────────────

def _fuse_action_cards(blocks: list[dict]) -> list[dict]:
    """Detect lone number/digit + bold short title + body → ACTION-CARD."""
    if len(blocks) < 3:
        return blocks

    out: list[dict] = []
    i = 0
    while i < len(blocks):
        blk = blocks[i]
        text = blk["text"].strip()

        # Lone digit / emoji acting as card number
        if (
            blk.get("kind") == "PARAGRAPH"
            and len(text) <= 3
            and i + 2 < len(blocks)
            and blocks[i + 1].get("is_bold")
            and len(blocks[i + 1]["text"]) <= 80
            and blocks[i + 2].get("kind") == "PARAGRAPH"
        ):
            card_num = text
            title = blocks[i + 1]["text"].strip()
            body = blocks[i + 2]["text"].strip()
            out.append({
                "kind": "ACTION-CARD",
                "text": (
                    f"[ACTION-CARD — numbered]\n"
                    f"Number: {card_num}\n"
                    f"Title: {title}\n"
                    f"Body: {body}"
                ),
                "top_y": blk["top_y"],
                "word_count": 0,
                "avg_size": 0,
                "is_bold": False,
            })
            i += 3
        else:
            out.append(blk)
            i += 1
    return out


# ── comparison panel ──────────────────────────────────────────────────────────

def _detect_comparison_panel(classified_cols: list[tuple[str, list[dict]]]) -> bool:
    """Return True if both columns start with a bold heading matching comparison keywords."""
    for _, blocks in classified_cols:
        if not blocks:
            return False
        first = blocks[0]
        text_lower = first["text"].lower()
        if not first.get("is_bold"):
            return False
        if not any(kw in text_lower for kw in _COMPARISON_KEYWORDS):
            return False
    return True


def _render_comparison_panel(
    left_blocks: list[dict], right_blocks: list[dict]
) -> list[str]:
    lines = ["[COMPARISON-PANEL]"]
    left_heading = left_blocks[0]["text"].strip() if left_blocks else ""
    right_heading = right_blocks[0]["text"].strip() if right_blocks else ""
    lines.append(f'LEFT: "{left_heading}"')
    for blk in left_blocks[1:]:
        for ln in blk["text"].splitlines():
            lines.append(f"- {ln.strip()}" if ln.strip() else "")
    lines.append(f'RIGHT: "{right_heading}"')
    for blk in right_blocks[1:]:
        for ln in blk["text"].splitlines():
            lines.append(f"- {ln.strip()}" if ln.strip() else "")
    lines.append("")
    return lines


# ── table rendering ───────────────────────────────────────────────────────────

def _detect_header_row(rows: list[list[str]]) -> bool:
    """Return True if the first row looks like a header (distinct from body rows)."""
    if not rows or len(rows) < 2:
        return bool(rows)
    first = rows[0]
    rest = rows[1:]
    # Header heuristic: first row has significantly shorter cell texts (labels)
    # vs body rows, or cells look like column names (title-cased / all-caps).
    first_texts = [c.strip() for c in first]
    if any(c.isupper() and len(c) > 1 for c in first_texts):
        return True
    if all(c == c.title() or c == c.upper() for c in first_texts if c):
        body_avg = (
            sum(len(c) for row in rest for c in row) / max(sum(len(row) for row in rest), 1)
        )
        header_avg = sum(len(c) for c in first_texts) / max(len(first_texts), 1)
        if header_avg < body_avg * 0.8:
            return True
    return False


def _row_has_no_header_signals(rows: list[list[str]], first_row: list[str]) -> bool:
    """Return True if first_row has no typical header signals (for cross-page merge)."""
    if not first_row:
        return True
    texts = [c.strip() for c in first_row]
    # All cells numeric → probably a data row, not a header
    all_numeric = all(_is_numeric_value(t) or t == "" for t in texts)
    if all_numeric:
        return True
    # Starts with a number → data row
    if texts and texts[0] and texts[0][0].isdigit():
        return True
    return False


def _detect_table_variant(rows: list[list[str]]) -> str:
    """Return "Classic" or "Minimal" based on header row characteristics.

    In a pdfplumber context we can't easily read cell fill colours, so we
    use text-only heuristics as a proxy: if all header cells are non-empty
    and all-caps we assume a shaded (Classic) header row.
    """
    if not rows:
        return "Classic"
    header = [c.strip() for c in rows[0]]
    non_empty = [c for c in header if c]
    if non_empty and all(c == c.upper() for c in non_empty):
        return "Classic"
    return "Minimal"


def _render_table(
    rows: list[list[str]],
    prev_col_count: int | None,
    is_first_page_table: bool = True,
) -> tuple[list[str], int]:
    """Render a table as manifest lines.  Returns (lines, col_count)."""
    if not rows:
        return [], 0

    col_count = max(len(r) for r in rows)
    has_header = _detect_header_row(rows)
    variant = _detect_table_variant(rows)

    # Cross-page continuation detection
    is_continuation = (
        prev_col_count is not None
        and col_count == prev_col_count
        and not has_header
        and _row_has_no_header_signals(rows, rows[0])
    )

    lines: list[str] = []

    if is_continuation:
        lines.append("[TABLE — continued]")
    else:
        header_note = "row 0" if has_header else "none"
        lines.append(f"[TABLE — {col_count} columns, {variant}, header: {header_note}]")

    # Emit as markdown table
    for row_i, row in enumerate(rows):
        # Pad to col_count
        padded = list(row) + [""] * (col_count - len(row))
        cells = [c.replace("|", "\\|").replace("\n", " ") for c in padded]
        lines.append("| " + " | ".join(cells) + " |")
        if row_i == 0 and has_header:
            lines.append("| " + " | ".join(["---"] * col_count) + " |")

    lines.append("")
    return lines, col_count


# ── block renderer ────────────────────────────────────────────────────────────

def _render_block(blk: dict) -> list[str]:
    kind = blk.get("kind", "PARAGRAPH")
    text = blk["text"].strip()

    if kind in ("KPI-STRIP", "ACTION-CARD"):
        return text.splitlines() + [""]

    lines = [f"[{kind}]", text, ""]
    return lines


# ── docx extraction ────────────────────────────────────────────────────────────

def _extract_docx(path: Path) -> list[str]:
    from docx import Document  # type: ignore
    from docx.oxml.ns import qn  # type: ignore

    doc = Document(str(path))

    out: list[str] = [
        "# Document Manifest",
        f"Source: {path.name}",
        "Pages: —",
        f"Extracted: {date.today().isoformat()}",
        "",
        "---",
        "",
        "## Content",
        "",
    ]

    # Iterate document body elements in order (paragraphs and tables interleaved)
    body = doc.element.body
    blk_i = 0  # running block index for grouping
    list_buffer: list[str] = []
    list_style: str | None = None

    def flush_list() -> list[str]:
        nonlocal list_buffer, list_style
        if not list_buffer:
            return []
        result = [f"[LIST — {list_style or 'bulleted'}]"]
        result += list_buffer
        result.append("")
        list_buffer = []
        list_style = None
        return result

    for child in body:
        tag = child.tag.split("}")[-1]  # strip namespace

        if tag == "p":
            from docx.text.paragraph import Paragraph  # type: ignore

            para = Paragraph(child, doc)
            style_name = (para.style.name or "") if para.style else ""
            text = para.text.strip()
            if not text:
                out += flush_list()
                continue

            # Determine numbering / list style
            num_pr = child.find(f".//{{{child.nsmap.get('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')}}}numPr")
            is_list = num_pr is not None

            if is_list:
                # Detect ordered vs unordered heuristically
                numfmt_el = child.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numFmt")
                if numfmt_el is not None:
                    fmt_val = numfmt_el.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "")
                    cur_style = "numbered" if fmt_val in ("decimal", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman") else "bulleted"
                else:
                    cur_style = "bulleted"

                if list_style and list_style != cur_style:
                    out += flush_list()

                list_style = cur_style
                list_buffer.append(f"  - {text}")
                continue
            else:
                out += flush_list()

            # Heading levels
            if "Heading 1" in style_name:
                out += ["[HEADING-1]", text, ""]
            elif "Heading 2" in style_name:
                out += ["[HEADING-2]", text, ""]
            elif "Heading 3" in style_name:
                out += ["[HEADING-3]", text, ""]
            else:
                # Check for shading (callout)
                shading_el = child.find(
                    ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd"
                )
                if shading_el is not None:
                    fill = shading_el.get(
                        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fill", ""
                    )
                    if fill and fill.upper() not in ("FFFFFF", "AUTO", ""):
                        variant = _docx_callout_variant(text, style_name)
                        out += ["[CALLOUT]", f"Variant: {variant}", f"Body: {text}", ""]
                        continue

                # KPI strip heuristic: short bold text followed by short normal
                runs = para.runs
                is_bold_para = any(r.bold for r in runs)
                word_count = len(text.split())
                if is_bold_para and word_count <= 6:
                    out += ["[KPI-STRIP]", f"Value/Label: {text}", ""]
                else:
                    out += ["[PARAGRAPH]", text, ""]

        elif tag == "tbl":
            from docx.table import Table  # type: ignore

            out += flush_list()
            table = Table(child, doc)
            n_cols = max((len(row.cells) for row in table.rows), default=0)
            variant = _docx_table_variant(table)
            out.append(f"[TABLE — {n_cols} columns, {variant}]")

            for row_i, row in enumerate(table.rows):
                cells = [c.text.strip().replace("|", "\\|").replace("\n", " ") for c in row.cells]
                out.append("| " + " | ".join(cells) + " |")
                if row_i == 0:
                    out.append("| " + " | ".join(["---"] * n_cols) + " |")

            out.append("")

    out += flush_list()

    out += ["---", ""]
    return out


def _docx_callout_variant(text: str, style_name: str) -> str:
    """Heuristically determine callout variant from text/style."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ("insight", "key")):
        return "insight"
    if any(kw in text_lower for kw in ("note", "important")):
        return "note"
    if any(kw in text_lower for kw in ("warning", "caution")):
        return "warning"
    return "callout"


def _docx_table_variant(table) -> str:
    """Return "Classic" or "Minimal" based on first-row cell shading in docx."""
    try:
        first_row = table.rows[0]
        for cell in first_row.cells:
            shd = cell._tc.find(
                ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd"
            )
            if shd is not None:
                fill = shd.get(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fill",
                    "",
                )
                if fill and fill.upper() not in ("FFFFFF", "AUTO", ""):
                    return "Classic"
    except Exception:
        pass
    return "Minimal"
