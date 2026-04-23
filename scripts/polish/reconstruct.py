"""Reconstruct visual grids from positioned floating textboxes.

Design-tool exports (Canva, slide decks, Figma, dashboard exports) almost
never emit tables as actual `<w:tbl>` elements. They lay out a grid of
floating text boxes at absolute (x, y) page positions, and the reader
eyeballs the grid into columns and rows.

This stage walks the token stream *after* normalize and:

  1. Groups floating-lifted tokens by `spatial_group` (same host paragraph).
  2. Clusters each group into rows by Y, then columns by X.
  3. If a coherent grid emerges (≥3 rows, ≥2 cols, stable col count), the
     positioned paragraphs are removed and replaced with a single `table`
     token that canonicalizes the grid.
  4. If no grid emerges, the group passes through untouched.

Output preserves source order: the reconstructed table replaces the position
of the first positioned token in the group; remaining group tokens are
consumed.

Returns (tokens, warnings). Warnings name reconstructed table count + sizes.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


# 1 pt = 12700 EMU. 914400 EMU = 1 inch.
_Y_TOL_EMU = 101_600   # ~8pt — rows rarely overlap inside this
_X_TOL_EMU = 381_000   # ~30pt — column widths vary; wide tolerance groups
_MIN_ROWS = 3
_MIN_COLS = 2
_MIN_FILL_RATIO = 0.45   # fraction of cells filled to accept a grid
_MAX_GROUP_SIZE = 300    # absurdly huge groups are probably whole pages — still OK

# If a paragraph's text matches this, it's a standalone row of numbers and
# should be counted as one cell even though it might contain spaces.
_NUMERIC_CELL_RE = re.compile(r'^[\$€£¥]?\s*[-+]?\d[\d,\.]*\s*[KkMmBb]?\s*%?$')


def reconstruct(tokens: Iterable[dict]) -> tuple[list[dict], list[str]]:
    tokens = list(tokens)
    warnings: list[str] = []

    # Map group_id -> indices of positioned paragraph tokens
    groups: dict[int, list[int]] = {}
    for i, tok in enumerate(tokens):
        if tok.get("kind") != "paragraph":
            continue
        gid = tok.get("spatial_group")
        if gid is None:
            continue
        if tok.get("anchor_x") is None or tok.get("anchor_y") is None:
            continue
        groups.setdefault(gid, []).append(i)

    if not groups:
        return tokens, warnings

    reconstructed_count = 0
    reconstructed_details: list[str] = []
    consumed: set[int] = set()
    replacements: dict[int, dict] = {}   # first-index -> new table token

    for gid, idxs in groups.items():
        if len(idxs) < _MIN_ROWS * _MIN_COLS:
            continue
        if len(idxs) > _MAX_GROUP_SIZE:
            # Huge group — still try, but it likely spans an entire page
            pass

        rows = _cluster_to_grid(tokens, idxs)
        if rows is None:
            continue

        n_rows = len(rows)
        n_cols = max((len(r) for r in rows), default=0)
        fill = sum(1 for row in rows for c in row if c.strip())
        total = n_rows * n_cols
        fill_ratio = fill / total if total else 0

        if n_rows < _MIN_ROWS or n_cols < _MIN_COLS:
            continue
        if fill_ratio < _MIN_FILL_RATIO:
            continue

        # Build a synthetic table token that canonicalizes what we recovered.
        first_idx = min(idxs)
        first_tok = tokens[first_idx]
        table_tok = {
            "kind": "table",
            "source_index": first_tok.get("source_index", first_idx),
            "rows": [
                [{
                    "text": cell,
                    "runs": [{"text": cell, "bold": False, "italic": False}] if cell else [],
                    "shading_hex": None,
                    "colspan": 1,
                    "vmerge_continuation": False,
                    "nested_tables": [],
                } for cell in row]
                for row in rows
            ],
            "widths": None,
            "n_rows": n_rows,
            "n_cols": n_cols,
            "is_nested": False,
            "element": None,
            "reconstructed": True,
        }
        replacements[first_idx] = table_tok
        for i in idxs:
            consumed.add(i)
        # The replacement sits at first_idx; don't mark first_idx as consumed.
        consumed.discard(first_idx)
        reconstructed_count += 1
        reconstructed_details.append(f"{n_rows}×{n_cols}")

    if not replacements:
        return tokens, warnings

    out: list[dict] = []
    for i, tok in enumerate(tokens):
        if i in consumed:
            continue
        if i in replacements:
            out.append(replacements[i])
        else:
            out.append(tok)

    if reconstructed_count:
        warnings.append(
            f"reconstruct: rebuilt {reconstructed_count} grid(s) from positioned "
            f"textboxes [{', '.join(reconstructed_details)}]"
        )

    return out, warnings


def _cluster_to_grid(tokens: list[dict], idxs: list[int]) -> list[list[str]] | None:
    """Cluster positioned paragraphs (by token indices) into a 2D grid.

    Returns list-of-rows (each row is list-of-strings) or None if the points
    don't form a coherent grid.
    """
    points: list[tuple[int, int, str]] = []
    for i in idxs:
        t = tokens[i]
        x = t.get("anchor_x")
        y = t.get("anchor_y")
        text = (t.get("text") or "").strip()
        if x is None or y is None or not text:
            continue
        points.append((y, x, text))
    if len(points) < _MIN_ROWS * _MIN_COLS:
        return None

    # --- Cluster Y into rows
    points.sort(key=lambda p: (p[0], p[1]))
    rows_raw: list[list[tuple[int, str]]] = []   # row = [(x, text), ...]
    current: list[tuple[int, str]] = []
    current_y_anchor: int | None = None
    for y, x, text in points:
        if current_y_anchor is None or abs(y - current_y_anchor) <= _Y_TOL_EMU:
            current.append((x, text))
            if current_y_anchor is None:
                current_y_anchor = y
            else:
                # Update anchor to moving avg (stabilises long rows)
                current_y_anchor = (current_y_anchor + y) // 2
        else:
            rows_raw.append(current)
            current = [(x, text)]
            current_y_anchor = y
    if current:
        rows_raw.append(current)

    if len(rows_raw) < _MIN_ROWS:
        return None

    # --- Determine column anchors
    all_x = sorted(x for row in rows_raw for x, _ in row)
    col_anchors = _greedy_cluster(all_x, _X_TOL_EMU)
    if len(col_anchors) < _MIN_COLS:
        return None

    # --- Determine column count: median row width + anchor count
    row_widths = [len(row) for row in rows_raw]
    mode_width = Counter(row_widths).most_common(1)[0][0]
    n_cols = max(mode_width, len(col_anchors))
    # Cap n_cols to number of column anchors so we don't invent columns.
    n_cols = min(n_cols, len(col_anchors))
    if n_cols < _MIN_COLS:
        return None

    # --- Assign each cell to its column; merge same-column texts in a row
    rows: list[list[str]] = []
    for row in rows_raw:
        cells = [""] * n_cols
        row.sort(key=lambda p: p[0])
        for x, text in row:
            ci = _nearest_anchor_index(x, col_anchors)
            if ci >= n_cols:
                ci = n_cols - 1
            if cells[ci]:
                # Same column, same row — join with space
                cells[ci] = f"{cells[ci]} {text}".strip()
            else:
                cells[ci] = text
        rows.append(cells)

    # Drop rows that are completely empty
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < _MIN_ROWS:
        return None

    # Drop trailing single-cell rows that leaked in (chrome / annotations)
    while len(rows) > _MIN_ROWS:
        filled = sum(1 for c in rows[-1] if c.strip())
        if filled == 1 and _looks_chrome_row(rows[-1]):
            rows.pop()
        else:
            break

    return rows


def _greedy_cluster(values: list[int], tol: int) -> list[int]:
    """Return cluster centers. `values` must be sorted ascending."""
    if not values:
        return []
    anchors: list[int] = [values[0]]
    bucket: list[int] = [values[0]]
    for v in values[1:]:
        if v - bucket[-1] <= tol:
            bucket.append(v)
            anchors[-1] = sum(bucket) // len(bucket)
        else:
            bucket = [v]
            anchors.append(v)
    return anchors


def _nearest_anchor_index(x: int, anchors: list[int]) -> int:
    # Linear scan is fine — column counts are tiny.
    best_i = 0
    best_d = abs(x - anchors[0])
    for i in range(1, len(anchors)):
        d = abs(x - anchors[i])
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def _looks_chrome_row(row: list[str]) -> bool:
    """A one-cell row whose content looks like a caption/note rather than data."""
    joined = " ".join(c.strip() for c in row if c.strip()).lower()
    if len(joined) < 3:
        return True
    if len(joined) > 140:
        return True
    return False
