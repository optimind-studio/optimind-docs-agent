"""Refine — post-classify structural cleanup.

Runs AFTER `classify.py` has produced typed Blocks but BEFORE chart extraction
and rendering. Its job is to turn a technically-valid but structurally-messy
block stream into the one the renderer deserves.

This pass exists because classify operates strictly at the paragraph level; it
can't see that:

  * A list of 7 funnel names followed by a list of 7 dollar amounts is a
    two-column table.
  * A table with every cell empty except one is a decorative banner, not
    data.
  * A standalone `$61,974` paragraph is a fragment orphaned during
    design-tool flattening — not content.
  * A near-black full-bleed image is page chrome, not a real figure.
  * Three adjacent short headings like "Email" / "Marketing" / "Report" are
    one heading fragmented by per-word text frames.
  * A run of tiny trailing paragraphs ("Prepared by…", "Data Source:…") at
    the tail of a doc is source-chrome the new cover already covers.

Every refinement here is source-agnostic: it reacts to the *shape* of the
block stream, never to a specific string. Warnings are emitted so the
sidecar tells the full story.
"""
from __future__ import annotations

import io
import re
from typing import Iterable

from .model import (
    Block, Heading, KPICard, KPIStrip, List as ListBlock, ListItem,
    MergeSpec, Paragraph, Run, Table,
)


# ── Tunables ─────────────────────────────────────────────────────────────────

_DECOR_DARK_MEAN = 40           # RGB mean < this → probably a black backdrop
_DECOR_DARK_VARIANCE = 25       # low variance → flat fill / gradient, not content
_DECOR_MIN_BYTES = 4000         # tiny icons are dropped by chart_extract already
_MIN_IMAGE_AREA_PIXELS = 900    # anything smaller than 30×30 is chrome
_DECOR_PREBODY_INDEX = 3        # images this early (before first heading) = cover branding
_TRAILING_CLUTTER_MAX_CHARS = 200
_TRAILING_CLUTTER_WINDOW = 8
_HEADING_FRAGMENT_MAX_CHARS = 30
_HEADING_FRAGMENT_WINDOW = 4
# A paragraph where most non-space characters live in numeric atoms and no
# meaningful letter-run appears is design-tool KPI garbage.
_MASHED_NUMERIC_ATOMS_RE = re.compile(
    r'[\$€£¥]?\s*-?\d[\d,]*(?:\.\d+)?\s*[KkMmBb]?\s*%?'
)

_PURE_NUMERIC_RE = re.compile(
    r'^\s*[\$€£¥]?\s*[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*[KkMmBb]?\s*%?\s*$'
    r'|^\s*[\$€£¥]?\s*[-+]?\d+(?:\.\d+)?\s*[KkMmBb]?\s*%?\s*$'
)

# Labels that look like document tail chrome ("Prepared by", "Data Source",
# "Powered by", "Page N of M") — we still keep them if they're standalone
# paragraphs, but they contribute to "trailing clutter" detection.
#
# Note: the comparison is done on the lowercased text with all spaces stripped,
# so fragments like `DataSource:ExponeaCDP/Google` and `Powered by Ubono LTD`
# both match.
_CHROME_HINTS = (
    "preparedby", "datasource", "poweredby",
    "confidential", "allrightsreserved", "copyright",
    "generated:", "generatedon", "reportgenerated",
    "page1of", "page2of", "page3of",
)


# ── Entry point ─────────────────────────────────────────────────────────────

def refine(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Apply all refinements in a fixed order. Returns (new_blocks, warnings)."""
    warnings: list[str] = []
    blocks, w = _merge_fragmented_headings(blocks)
    warnings.extend(w)
    blocks, w = _defragment_source_tables(blocks)
    warnings.extend(w)
    blocks, w = _fuse_parallel_lists(blocks)
    warnings.extend(w)
    blocks, w = _form_metric_tables(blocks)
    warnings.extend(w)
    blocks, w = _fuse_label_value_runs(blocks)
    warnings.extend(w)
    blocks, w = _fuse_label_mashed_value_runs(blocks)
    warnings.extend(w)
    blocks, w = _drop_orphan_numeric_paragraphs(blocks)
    warnings.extend(w)
    blocks, w = _drop_mashed_numeric_paragraphs(blocks)
    warnings.extend(w)
    blocks, w = _drop_malformed_tables(blocks)
    warnings.extend(w)
    blocks, w = _drop_decorative_figures(blocks)
    warnings.extend(w)
    blocks, w = _trim_trailing_clutter(blocks)
    warnings.extend(w)
    return blocks, warnings


# ── Letter-spaced text reconstitution ───────────────────────────────────────

_SINGLE_CHAR_TOKEN_RE = re.compile(r'^[A-Za-z0-9]$')


def _reconstitute_letterspaced_text(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Fix strings where every letter has been separated by spaces.

    CSS-style `letter-spacing` rendered to Word often emits `M O N T H L Y`
    instead of `MONTHLY`. A reliable signature: most tokens (space-split) are
    single characters. We collapse runs of single-character tokens back into
    single words. Punctuation tokens like `—` pass through untouched.
    """
    if not blocks:
        return blocks, []
    fixed = 0
    out: list[Block] = []
    for b in blocks:
        if b.kind == "heading":
            orig = b.content.text
            new = _despace_letterspaced(orig)
            if new != orig:
                fixed += 1
                out.append(Block(kind="heading", classification_source=b.classification_source,
                                 content=Heading(level=b.content.level, text=new),
                                 source_index=b.source_index, notes=b.notes))
                continue
        elif b.kind == "paragraph":
            text = _paragraph_text(b.content)
            new = _despace_letterspaced(text)
            if new != text:
                fixed += 1
                out.append(Block(kind="paragraph", classification_source=b.classification_source,
                                 content=Paragraph(runs=[Run(text=new)]),
                                 source_index=b.source_index, notes=b.notes))
                continue
        out.append(b)
    warnings = [f"refine: reconstituted {fixed} letter-spaced heading/paragraph(s)"] if fixed else []
    return out, warnings


def _despace_letterspaced(text: str) -> str:
    """Collapse runs of single-character tokens back into words.

    "1 0 — M O N T H L Y" → "10 — MONTHLY"
    "Normal heading" → unchanged (too few single-char tokens)
    """
    if not text or len(text) < 5:
        return text
    tokens = text.split(" ")
    if len(tokens) < 3:
        return text

    # Count single-char alphanumeric tokens
    single = sum(1 for t in tokens if _SINGLE_CHAR_TOKEN_RE.match(t))
    if single < max(3, int(len(tokens) * 0.5)):
        return text

    # Walk tokens; collapse adjacent single-char runs into words.
    out_tokens: list[str] = []
    buf: list[str] = []
    for t in tokens:
        if _SINGLE_CHAR_TOKEN_RE.match(t):
            buf.append(t)
        else:
            if buf:
                out_tokens.append("".join(buf))
                buf = []
            out_tokens.append(t)
    if buf:
        out_tokens.append("".join(buf))
    return " ".join(out_tokens)


# ── Mashed-numeric paragraph drop ───────────────────────────────────────────

def _drop_mashed_numeric_paragraphs(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Drop paragraphs/headings that are several numeric atoms jammed together.

    Examples seen in the wild:
      * `7,729,22731.9%1.41%3,244$610,064` — 5 KPI values from a source
        textbox that fragment-merged into one paragraph.
      * `2,171,48537.7%1.58%1,046$202,714` — same.

    Also fires when docx_reader's "short-bold = H3" rule incorrectly promotes
    one of these to a heading.

    Rule: if stripping out numeric atoms leaves no letter-run of length ≥3,
    the block is pure number-debris. Keep sentences that mention numbers.
    """
    if not blocks:
        return blocks, []
    dropped = 0
    out: list[Block] = []
    for b in blocks:
        if b.kind == "paragraph":
            text = _paragraph_text(b.content).strip()
            if text and len(text) <= 80 and _looks_mashed_numeric(text):
                dropped += 1
                continue
        elif b.kind == "heading":
            text = (b.content.text or "").strip()
            if text and len(text) <= 80 and _looks_mashed_numeric(text):
                dropped += 1
                continue
        out.append(b)
    warnings = [f"refine: dropped {dropped} mashed-numeric block(s)"] if dropped else []
    return out, warnings


def _looks_mashed_numeric(text: str) -> bool:
    """True if `text` is multiple numeric atoms with no meaningful word."""
    if not text:
        return False
    # Count how many numeric atoms we can extract.
    atoms = _MASHED_NUMERIC_ATOMS_RE.findall(text)
    numeric_atoms = [a for a in atoms if any(ch.isdigit() for ch in a)]
    if len(numeric_atoms) < 2:
        return False
    # Strip every numeric atom out of the text and see what's left.
    residue = _MASHED_NUMERIC_ATOMS_RE.sub(" ", text)
    # Anything left that's a real word run (≥3 letters)?
    if re.search(r'[A-Za-z]{3,}', residue):
        return False
    return True


# ── Fragmented-heading merge ────────────────────────────────────────────────

def _merge_fragmented_headings(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Fuse runs of ≤3 adjacent same-level headings into one heading.

    Design-tool exports often break a single heading across multiple text
    frames ("Email" / "Marketing" / "Report"). Each frame comes through as
    its own heading-ambiguous paragraph that docx_reader fingerprints as H3.
    If we see 2–4 adjacent headings, all short and same level, combine them.
    """
    if not blocks:
        return blocks, []
    out: list[Block] = []
    merged = 0
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.kind != "heading":
            out.append(b)
            i += 1
            continue
        run = [b]
        j = i + 1
        while (j < len(blocks) and j - i < _HEADING_FRAGMENT_WINDOW
               and blocks[j].kind == "heading"
               and blocks[j].content.level == b.content.level
               and len(blocks[j].content.text) <= _HEADING_FRAGMENT_MAX_CHARS
               and len(b.content.text) <= _HEADING_FRAGMENT_MAX_CHARS):
            run.append(blocks[j])
            j += 1
        if len(run) >= 2 and sum(len(r.content.text) for r in run) <= 80:
            fused_text = " ".join(r.content.text.strip() for r in run)
            out.append(Block(kind="heading", classification_source=b.classification_source,
                             content=Heading(level=b.content.level, text=fused_text),
                             source_index=b.source_index))
            merged += len(run) - 1
            i = j
        else:
            out.append(b)
            i += 1
    warnings = [f"refine: merged {merged} fragmented heading fragment(s)"] if merged else []
    return out, warnings


# ── Parallel-list fusion ────────────────────────────────────────────────────

def _fuse_parallel_lists(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Two adjacent Lists of equal length where one is all-numeric → a Table.

    Also: a List of labels followed by a List of numeric values, optionally
    separated by a single heading/empty paragraph — the classic
    "funnel name / revenue $" layout in BI exports.

    Produces a 2-column Minimal table (no header row) so the numeric column
    is right-aligned and the labels are left-aligned per the variant rules.
    """
    if not blocks:
        return blocks, []
    out: list[Block] = []
    fused = 0
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.kind != "list":
            out.append(b)
            i += 1
            continue

        # Look at the next 1-2 blocks for a matching-length partner list.
        partner_idx = None
        for k in range(1, 3):
            j = i + k
            if j >= len(blocks):
                break
            nxt = blocks[j]
            if nxt.kind == "list":
                partner_idx = j
                break
            # Allow one short paragraph between (but not a heading — keep structure).
            if nxt.kind == "paragraph":
                continue
            break

        if partner_idx is None:
            out.append(b)
            i += 1
            continue

        partner = blocks[partner_idx]
        a_items = [_list_item_text(it) for it in b.content.items]
        p_items = [_list_item_text(it) for it in partner.content.items]
        if len(a_items) != len(p_items) or len(a_items) < 2:
            out.append(b)
            i += 1
            continue

        a_numeric_ratio = _numeric_ratio(a_items)
        p_numeric_ratio = _numeric_ratio(p_items)

        # Exactly one side is all-numeric, the other is labels.
        if a_numeric_ratio >= 0.9 and p_numeric_ratio <= 0.2:
            values, labels = a_items, p_items
            label_side = "right"  # (numeric list came first)
        elif p_numeric_ratio >= 0.9 and a_numeric_ratio <= 0.2:
            values, labels = p_items, a_items
            label_side = "left"
        else:
            out.append(b)
            i += 1
            continue

        rows = [[lbl, val] for lbl, val in zip(labels, values)] if label_side == "left" \
               else [[lbl, val] for lbl, val in zip(labels, values)]
        # Emit as a Minimal table with no header — numeric col auto-right-aligns.
        table = Table(
            headers=[],
            rows=rows,
            variant="minimal",
            merges=[],
            caption=None,
        )
        out.append(Block(kind="table", classification_source="rule",
                         content=table, source_index=b.source_index,
                         notes=["fused-from-parallel-lists"]))

        # Drop any paragraphs between the two lists we consumed.
        fused += 1
        i = partner_idx + 1

    warnings = [f"refine: fused {fused} parallel label/value list pair(s) into tables"] \
        if fused else []
    return out, warnings


def _list_item_text(item: ListItem) -> str:
    return "".join(r.text for r in item.runs).strip()


def _numeric_ratio(items: list[str]) -> float:
    if not items:
        return 0.0
    numeric = sum(1 for s in items if _PURE_NUMERIC_RE.match(s or ""))
    return numeric / len(items)


# ── Orphan numeric paragraph drop ───────────────────────────────────────────

def _drop_orphan_numeric_paragraphs(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Standalone paragraphs/headings that are *only* a number are fragmentation debris.

    Real body copy that quotes a KPI number embeds it in a sentence. A block
    whose entire text is `$61,974` or `24.9%` only appears when a floating
    text frame got lifted with its value and no surrounding context. Applies
    equally to headings in case the ingest heading heuristic mis-fired.
    """
    if not blocks:
        return blocks, []
    out: list[Block] = []
    dropped = 0
    for b in blocks:
        if b.kind == "paragraph":
            text = _paragraph_text(b.content).strip()
            if text and _PURE_NUMERIC_RE.match(text) and len(text) <= 20:
                dropped += 1
                continue
        elif b.kind == "heading":
            text = (b.content.text or "").strip()
            if text and _PURE_NUMERIC_RE.match(text) and len(text) <= 20:
                dropped += 1
                continue
        out.append(b)
    warnings = [f"refine: dropped {dropped} orphan numeric block(s)"] if dropped else []
    return out, warnings


def _paragraph_text(para: Paragraph) -> str:
    if hasattr(para, "text"):
        return para.text
    return "".join(r.text for r in para.runs)


# ── Malformed-table drop / degrade ──────────────────────────────────────────

def _drop_malformed_tables(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Tables with empty/single-cell bodies are decorative banners, not data.

    Degrade rules:
      * All cells empty → drop the table entirely.
      * Exactly one non-empty cell across the entire table → convert it
        into a plain paragraph carrying that text.
      * Body-cell density < 30% → drop (too sparse to be data; was likely
        used as a coloured band / divider).
    """
    if not blocks:
        return blocks, []
    out: list[Block] = []
    dropped = 0
    degraded = 0
    for b in blocks:
        if b.kind != "table":
            out.append(b)
            continue
        tbl: Table = b.content
        all_cells: list[str] = []
        for row in tbl.headers:
            all_cells.extend(row)
        for row in tbl.rows:
            all_cells.extend(row)
        total = len(all_cells)
        non_empty = [c for c in all_cells if (c or "").strip()]
        if total == 0 or not non_empty:
            dropped += 1
            continue

        # Single-text banner → paragraph
        if len(non_empty) == 1:
            text = non_empty[0].strip()
            if len(text) <= 80:
                degraded += 1
                out.append(Block(
                    kind="paragraph",
                    classification_source="rule",
                    content=Paragraph(runs=[Run(text=text)]),
                    source_index=b.source_index,
                    notes=["degraded-from-single-cell-table"],
                ))
                continue
            # Long content → keep as table still (rare, but preserve)

        # Density check (only on body rows, and only when we actually have rows)
        if tbl.rows:
            body_cells: list[str] = []
            for row in tbl.rows:
                body_cells.extend(row)
            body_non_empty = [c for c in body_cells if (c or "").strip()]
            density = len(body_non_empty) / max(1, len(body_cells))
            if density < 0.3 and len(body_cells) >= 4:
                dropped += 1
                continue

        out.append(b)

    warnings: list[str] = []
    if dropped:
        warnings.append(f"refine: dropped {dropped} malformed/decorative table(s)")
    if degraded:
        warnings.append(f"refine: degraded {degraded} single-cell table(s) to paragraphs")
    return out, warnings


# ── Decorative-figure drop ──────────────────────────────────────────────────

def _drop_decorative_figures(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Drop images that are clearly page chrome, not content.

    Heuristics (any one suffices):
      * Near-black full-bleed image (mean RGB < 40, variance < 25) — design
        background panels used as section dividers.
      * Tiny icon/glyph (total pixel area below threshold).
      * Image positioned before the first heading AND near-uniform colour
        (cover branding / watermark / "Powered by X" logo).
    """
    if not blocks:
        return blocks, []
    try:
        from PIL import Image, ImageStat   # optional — Pillow is in requirements
    except Exception:
        return blocks, []

    first_heading_idx = _first_heading_index(blocks)

    out: list[Block] = []
    dropped_dark = 0
    dropped_tiny = 0
    dropped_prebody = 0
    for idx, b in enumerate(blocks):
        if b.kind != "figure":
            out.append(b)
            continue
        fig = b.content
        blob = fig.image_bytes or b""
        if not blob or len(blob) < _DECOR_MIN_BYTES:
            dropped_tiny += 1
            continue
        try:
            im = Image.open(io.BytesIO(blob))
            im.load()
        except Exception:
            # Can't decode → let the renderer decide; don't drop silently.
            out.append(b)
            continue

        width, height = im.size
        if width * height < _MIN_IMAGE_AREA_PIXELS:
            dropped_tiny += 1
            continue

        try:
            stat_im = im.convert("RGB")
            stat = ImageStat.Stat(stat_im)
            mean = sum(stat.mean) / 3.0
            variance = sum(stat.stddev) / 3.0
        except Exception:
            mean, variance = 128.0, 128.0

        # Near-black flat backdrop
        if mean < _DECOR_DARK_MEAN and variance < _DECOR_DARK_VARIANCE:
            dropped_dark += 1
            continue

        # Pre-body branding / watermark (low-variance image before the first H1)
        if (first_heading_idx is not None and idx < first_heading_idx
                and (idx < _DECOR_PREBODY_INDEX or variance < 35)):
            dropped_prebody += 1
            continue

        out.append(b)

    warnings: list[str] = []
    if dropped_dark:
        warnings.append(f"refine: dropped {dropped_dark} dark/full-bleed decorative figure(s)")
    if dropped_tiny:
        warnings.append(f"refine: dropped {dropped_tiny} tiny/icon figure(s)")
    if dropped_prebody:
        warnings.append(f"refine: dropped {dropped_prebody} pre-body branding figure(s)")
    return out, warnings


def _first_heading_index(blocks: list[Block]) -> int | None:
    for i, b in enumerate(blocks):
        if b.kind == "heading":
            return i
    return None


# ── Trailing-clutter trim ───────────────────────────────────────────────────

def _trim_trailing_clutter(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Drop a trailing run of tiny/chrome paragraphs at the very end of the doc.

    We only look at the last N blocks. A block qualifies as clutter if it:
      * matches a chrome keyword (`prepared by`, `powered by`, `data source`,
        `generated:`, `page N of M`, `confidential`, `copyright`)
      * OR is a pure numeric marker ≤ 8 chars (standalone "2026" etc.)
      * OR is a squished concatenation — ≥30 chars with fewer than 3 spaces,
        which is the fingerprint of design-tool chrome that was lifted from
        a multi-line textbox

    We stop as soon as we hit a non-clutter block so real body content is
    never touched.
    """
    if not blocks:
        return blocks, []

    cutoff = len(blocks)
    for i in range(len(blocks) - 1, max(-1, len(blocks) - _TRAILING_CLUTTER_WINDOW - 1), -1):
        b = blocks[i]
        if b.kind != "paragraph":
            break
        text = _paragraph_text(b.content).strip()
        if not text:
            cutoff = i
            continue
        if len(text) > _TRAILING_CLUTTER_MAX_CHARS:
            break
        if not _looks_chrome(text):
            break
        cutoff = i

    dropped = len(blocks) - cutoff
    if dropped == 0:
        return blocks, []
    return blocks[:cutoff], [f"refine: trimmed {dropped} trailing chrome paragraph(s)"]


def _looks_chrome(text: str) -> bool:
    """True if `text` is a footer/chrome fragment, not real body copy."""
    if not text:
        return True
    # Chrome-keyword match — compare against lowercased, space-stripped form so
    # concatenated variants (e.g. "DataSource:ExponeaCDP") still match "datasource".
    squashed = re.sub(r'\s+', '', text).lower()
    if any(hint in squashed for hint in _CHROME_HINTS):
        return True
    # Pure-numeric / year marker
    if _PURE_NUMERIC_RE.match(text) and len(text) <= 8:
        return True
    # No-space concatenated fragment (design-tool chrome fingerprint)
    space_count = text.count(" ")
    if len(text) >= 30 and space_count < 3:
        return True
    return False


# ── Source-table defragment ─────────────────────────────────────────────────

def _defragment_source_tables(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Merge rows where col[0] is a fragment of the following data row.

    Design-tool "tables" often put one logical table row across several
    Word-table rows: col[0] of row N = "Landing", row N+1 = "Page",
    row N+2 = "MDC", row N+3 = "Interview", row N+4 = "9" — while
    cols[1..] in rows N..N+3 are all empty, and row N+4 finally has
    the numeric data on the right.

    Heuristic:
      * If row `i` has col[0] filled and cols[1..] empty, AND at least
        one upcoming row within the next 5 rows has cols[1..] filled,
        treat row i's col[0] as a fragment prefix.
      * Accumulate fragment prefixes until a "full" row (cols[1..] non-
        empty) is hit, then prepend them to that row's col[0].
      * Trailing fragments with no following full row are left in place
        (preserves data until other refinements handle them).
    """
    if not blocks:
        return blocks, []
    out: list[Block] = []
    defragmented = 0
    for b in blocks:
        if b.kind != "table":
            out.append(b)
            continue
        tbl: Table = b.content
        if not tbl.rows or max((len(r) for r in tbl.rows), default=0) < 2:
            out.append(b)
            continue

        new_rows: list[list[str]] = []
        fragments: list[str] = []
        for row in tbl.rows:
            n_cells = len(row)
            col0 = (row[0] or "").strip() if n_cells > 0 else ""
            rest = [(c or "").strip() for c in row[1:]]
            rest_filled = any(rest)
            if col0 and not rest_filled:
                fragments.append(col0)
                continue
            # Full row (or row with empty col0 but filled elsewhere)
            if fragments:
                new_col0 = " ".join(fragments + ([col0] if col0 else [])).strip()
                merged_row = list(row)
                merged_row[0] = new_col0
                new_rows.append(merged_row)
                fragments = []
                defragmented += 1
            else:
                new_rows.append(row)
        if fragments:
            # Trailing fragments — emit as their own single-col row so nothing
            # disappears; _drop_malformed_tables can still strip if useless.
            filler = [""] * max(1, max((len(r) for r in new_rows), default=1))
            filler[0] = " ".join(fragments)
            new_rows.append(filler)

        # Also defragment headers: if header has fragments stacked in col 0
        new_headers: list[list[str]] = []
        h_fragments: list[str] = []
        for hrow in tbl.headers:
            if not hrow:
                continue
            col0 = (hrow[0] or "").strip()
            rest_filled = any((c or "").strip() for c in hrow[1:])
            if col0 and not rest_filled and len(hrow) > 1:
                h_fragments.append(col0)
                continue
            if h_fragments:
                merged = list(hrow)
                merged[0] = " ".join(h_fragments + ([col0] if col0 else [])).strip()
                new_headers.append(merged)
                h_fragments = []
            else:
                new_headers.append(hrow)
        if h_fragments:
            # No full header row → inject a synthetic header spanning col 0
            new_headers.append([" ".join(h_fragments)])

        new_tbl = Table(
            headers=new_headers,
            rows=new_rows,
            variant=tbl.variant,
            merges=tbl.merges,
            caption=tbl.caption,
        )
        out.append(Block(kind="table", classification_source=b.classification_source,
                         content=new_tbl, source_index=b.source_index,
                         notes=b.notes + ["defragmented-col0"]))

    warnings = [f"refine: defragmented col-0 fragments in {defragmented} table row(s)"] \
        if defragmented else []
    return out, warnings


# ── Metric-table formation (LABEL VALUE NOTES paragraph runs) ──────────────

# Matches paragraphs shaped like:
#   "DELIVERY RATE 98.9% 33,373,555 delivered of 33,743,524 sent"
#   "TOTAL EMAIL REVENUE $350K March 2026"
#   "AVG EMAILS PER LEAD 12.4 Strong nurture cadence"
#   "33.8M +9.1% vs February"      (no label — just value + notes)
#
# We split into (label, value, notes) using this regex: capture everything up
# to the first numeric atom as LABEL, the numeric atom + optional unit as
# VALUE, and the remainder as NOTES.
_METRIC_SPLIT_RE = re.compile(
    r'^(?P<label>[A-Za-z][A-Za-z0-9&/\-\.\,\'\s·→]*?)\s+'
    r'(?P<value>[\$€£¥]?[-+]?\d[\d,]*(?:\.\d+)?[KkMmBb]?%?)'
    r'(?P<notes>(?:\s+.*)?)$'
)


def _form_metric_tables(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Fuse adjacent paragraphs that look like `LABEL VALUE [NOTES]` into tables.

    A run of ≥3 consecutive paragraphs where each matches the pattern
    becomes a 3-col table with headers ["Metric", "Value", "Notes"].

    Headings, callouts and other blocks break the run.
    """
    if not blocks:
        return blocks, []
    out: list[Block] = []
    i = 0
    formed = 0
    total_rows = 0
    while i < len(blocks):
        b = blocks[i]
        if b.kind != "paragraph":
            out.append(b)
            i += 1
            continue
        # Try to collect a run starting at i
        run_rows: list[tuple[str, str, str]] = []
        j = i
        while j < len(blocks) and blocks[j].kind == "paragraph":
            text = _paragraph_text(blocks[j].content).strip()
            parts = _parse_metric_paragraph(text)
            if parts is None:
                break
            run_rows.append(parts)
            j += 1
        if len(run_rows) >= 3:
            # Emit as a 3-col Classic table
            headers = [["Metric", "Value", "Notes"]]
            rows = [[lbl, val, notes] for lbl, val, notes in run_rows]
            tbl = Table(headers=headers, rows=rows, variant="classic",
                        merges=[], caption=None)
            out.append(Block(kind="table", classification_source="rule",
                             content=tbl, source_index=b.source_index,
                             notes=["fused-from-metric-paragraphs"]))
            formed += 1
            total_rows += len(run_rows)
            i = j
        else:
            out.append(b)
            i += 1

    warnings = [f"refine: formed {formed} metric table(s) from {total_rows} paragraph row(s)"] \
        if formed else []
    return out, warnings


def _parse_metric_paragraph(text: str) -> tuple[str, str, str] | None:
    """Return (label, value, notes) or None if the paragraph doesn't fit.

    Acceptance rules:
      * At least 3 characters and at most 200.
      * Matches _METRIC_SPLIT_RE.
      * Label must contain ≥2 letters (not empty / not garbage).
      * Value must be a recognizable numeric atom.
    """
    if not text or len(text) < 3 or len(text) > 200:
        return None
    m = _METRIC_SPLIT_RE.match(text)
    if m is None:
        return None
    label = (m.group("label") or "").strip()
    value = (m.group("value") or "").strip()
    notes = (m.group("notes") or "").strip()
    if not label or not value:
        return None
    # Label sanity: needs letters (≥3 letters), not too long.
    if not re.search(r'[A-Za-z]{3,}', label):
        return None
    if len(label) > 80:
        return None
    # Reject if label is mostly digits.
    digit_count = sum(ch.isdigit() for ch in label)
    if digit_count > max(1, len(label) // 3):
        return None
    return label, value, notes


# ── Label-run + value-run fusion (paragraph level) ─────────────────────────

def _fuse_label_value_runs(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Fuse N adjacent label paragraphs + N adjacent value-lead paragraphs.

    Pattern:
      label_1                                   (short, no leading numeric)
      label_2
      label_3
      label_4
      value_1 notes_1                           (leading numeric + optional notes)
      value_2 notes_2
      value_3 notes_3
      value_4 notes_4
    → 3-col Classic table [Metric, Value, Notes].

    Only fires when:
      * ≥3 consecutive label paragraphs (no value pattern)
      * followed by an equal count of consecutive value-lead paragraphs
      * labels are short (≤60 chars, no mashed numerics)
    """
    if not blocks:
        return blocks, []
    out: list[Block] = []
    i = 0
    fused = 0
    total_rows = 0
    while i < len(blocks):
        # Scan for a run of label paragraphs
        j = i
        labels: list[str] = []
        while j < len(blocks) and blocks[j].kind == "paragraph":
            text = _paragraph_text(blocks[j].content).strip()
            if not _looks_label(text):
                break
            labels.append(text)
            j += 1
        # Now scan for an equal run of value-lead paragraphs
        if len(labels) >= 3:
            values: list[tuple[str, str]] = []
            k = j
            while k < len(blocks) and blocks[k].kind == "paragraph" and len(values) < len(labels):
                text = _paragraph_text(blocks[k].content).strip()
                parts = _split_value_and_notes(text)
                if parts is None:
                    break
                values.append(parts)
                k += 1
            if len(values) == len(labels):
                # Emit 3-col table
                headers = [["Metric", "Value", "Notes"]]
                rows = [[lbl, val, notes] for lbl, (val, notes) in zip(labels, values)]
                # Emit preceding blocks (none, since we started at i), then table
                tbl = Table(headers=headers, rows=rows, variant="classic",
                            merges=[], caption=None)
                out.append(Block(kind="table", classification_source="rule",
                                 content=tbl, source_index=blocks[i].source_index,
                                 notes=["fused-from-label-value-runs"]))
                fused += 1
                total_rows += len(labels)
                i = k
                continue
        # No match — emit blocks[i] and advance
        out.append(blocks[i])
        i += 1

    warnings = [f"refine: fused {fused} label-run+value-run pair(s) into {total_rows} row table(s)"] \
        if fused else []
    return out, warnings


def _looks_label(text: str) -> bool:
    """Paragraph-level label: short, alphabetical, not leading with a number."""
    if not text:
        return False
    if len(text) > 60:
        return False
    # Must contain ≥3 letters and not match the metric split (would imply value inside)
    if not re.search(r'[A-Za-z]{3,}', text):
        return False
    # Starts with a letter (not a number / currency / bullet symbol)
    first = text.lstrip()
    if not first or not first[0].isalpha():
        return False
    # Reject lines that look like "label value" pairs already (metric paragraphs
    # are handled in _form_metric_tables)
    if _parse_metric_paragraph(text) is not None:
        return False
    # Reject mashed numerics
    if _looks_mashed_numeric(text):
        return False
    return True


def _split_value_and_notes(text: str) -> tuple[str, str] | None:
    """Paragraph-level value: starts with a numeric atom, optional trailing notes."""
    if not text:
        return None
    m = re.match(
        r'^(?P<value>[\$€£¥]?[-+]?\d[\d,]*(?:\.\d+)?[KkMmBb]?%?)'
        r'(?P<notes>(?:\s+.*)?)$',
        text,
    )
    if m is None:
        return None
    value = (m.group("value") or "").strip()
    notes = (m.group("notes") or "").strip()
    if not value:
        return None
    return value, notes


# ── Label + mashed-number fusion ────────────────────────────────────────────

# One numeric atom: optional currency prefix, digits (with thousand-sep
# commas), optional decimal, optional K/M/B suffix, optional trailing percent.
_NUMERIC_ATOM_RE = re.compile(
    r'[\$€£¥]?[-+]?'
    r'(?:\d{1,3}(?:,\d{3})+|\d+)'     # digits: either comma-grouped or plain
    r'(?:\.\d+)?'                      # optional decimal
    r'(?:[KkMmBb])?'                   # optional magnitude suffix
    r'%?'                              # optional percent
)


def _split_mashed_numbers(text: str) -> list[str]:
    """Split a jammed-together numeric paragraph into its component atoms.

    '2,806,5512,769,07430.0%0.94%' → ['2,806,551','2,769,074','30.0%','0.94%']
    '7,593,61934.7%1.43%3,736$628,448' → ['7,593,619','34.7%','1.43%','3,736','$628,448']
    Returns [] if any non-numeric content is encountered (string isn't purely
    concatenated numbers).
    """
    if not text:
        return []
    atoms: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        # Skip whitespace between atoms (tolerant of rare spacing)
        if text[i].isspace():
            i += 1
            continue
        m = _NUMERIC_ATOM_RE.match(text, i)
        if m is None or m.end() == i:
            return []   # non-numeric content → not purely mashed
        atom = m.group(0).strip()
        if not atom or atom in ('$', '%', '-', '+'):
            return []
        atoms.append(atom)
        i = m.end()
    return atoms


def _fuse_label_mashed_value_runs(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    """Fuse alternating `[label, mashed_values]` pairs into a multi-column table.

    Campaign-style sections in design-tool exports show:
       label_1
       mashed_values_1   (e.g. '2,806,5512,769,07430.0%0.94%')
       [optional 0–2 noise paragraphs — stray design fragments]
       label_2
       mashed_values_2
       ...

    When we see ≥2 (label, mashed) pairs whose mashed strings decompose into
    the SAME number of atoms N, separated by ≤2 non-matching blocks, emit a
    single (N+1)-column Classic table. Intervening noise is dropped (these
    are almost always fragments of another label/value that leaked in).
    """
    if not blocks:
        return blocks, []
    out: list[Block] = []
    i = 0
    fused = 0
    total_rows = 0
    while i < len(blocks):
        pairs, consumed = _collect_label_mashed_pairs(blocks, i)
        if len(pairs) >= 2:
            atom_count = len(pairs[0][1])
            headers = [["Metric"] + [f"Col {k + 1}" for k in range(atom_count)]]
            rows = [[label] + atoms for label, atoms in pairs]
            tbl = Table(headers=headers, rows=rows, variant="classic",
                        merges=[], caption=None)
            out.append(Block(kind="table", classification_source="rule",
                             content=tbl, source_index=blocks[i].source_index,
                             notes=["fused-from-label-mashed-pairs"]))
            fused += 1
            total_rows += len(pairs)
            i += consumed
            continue
        out.append(blocks[i])
        i += 1
    warnings = (
        [f"refine: fused {fused} label+mashed-value run(s) into {total_rows} row table(s)"]
        if fused else []
    )
    return out, warnings


def _try_label_mashed_pair_at(
    blocks: list[Block], i: int
) -> tuple[tuple[str, list[str]], int] | None:
    """Attempt to parse a (label, mashed_values) pair starting at block i.
    Returns (pair, blocks_consumed) or None. Both slots accept paragraph OR
    heading — design-tool exports frequently promote either to H3."""
    if i + 1 >= len(blocks):
        return None
    a = blocks[i]
    b = blocks[i + 1]
    if a.kind == "paragraph":
        label = _paragraph_text(a.content).strip()
    elif a.kind == "heading":
        label = a.content.text.strip()
    else:
        return None
    if b.kind == "paragraph":
        values_text = _paragraph_text(b.content).strip()
    elif b.kind == "heading":
        values_text = b.content.text.strip()
    else:
        return None
    if not _looks_label_for_mashed(label):
        return None
    atoms = _split_mashed_numbers(values_text)
    if len(atoms) < 2:
        return None
    return (label, atoms), 2


def _looks_label_for_mashed(text: str) -> bool:
    """Looser label check for the mashed-pair fusion path.

    Unlike `_looks_label`, this does NOT exclude text that matches the
    metric-paragraph pattern. 'Week 1 — Mar 2' is a perfectly good row
    label even though _parse_metric_paragraph would read it as
    label='Week'/value='1'. The companion mashed-numbers paragraph
    disambiguates intent.
    """
    if not text or len(text) > 80:
        return False
    if not re.search(r'[A-Za-z]{3,}', text):
        return False
    first = text.lstrip()
    if not first or not first[0].isalpha():
        return False
    if _looks_mashed_numeric(text):
        return False
    # Reject text that is itself a pure numeric-atom string (would mean the
    # "label" slot is actually a value).
    if _split_mashed_numbers(text):
        return False
    return True


def _collect_label_mashed_pairs(
    blocks: list[Block], start: int
) -> tuple[list[tuple[str, list[str]]], int]:
    """Greedy scan from `start` collecting [label, mashed] pairs with a
    consistent atom count. Allows up to 2 non-matching blocks between pairs.
    Returns (pairs, total_blocks_consumed).

    Labels may be paragraph OR heading blocks. Value block must be a paragraph
    of pure concatenated numeric atoms.
    """
    pairs: list[tuple[str, list[str]]] = []
    atom_count: int | None = None
    j = start
    gap_tolerance = 2
    last_pair_end = start
    while j < len(blocks):
        result = _try_label_mashed_pair_at(blocks, j)
        if result is not None:
            pair, consumed = result
            if atom_count is None:
                atom_count = len(pair[1])
                pairs.append(pair)
                j += consumed
                last_pair_end = j
            elif len(pair[1]) == atom_count:
                pairs.append(pair)
                j += consumed
                last_pair_end = j
            else:
                # Atom-count mismatch — stop the run.
                break
        else:
            # Noise block — skip up to gap_tolerance of them before giving up.
            if j - last_pair_end >= gap_tolerance:
                break
            j += 1
    return pairs, last_pair_end - start
