"""Chart-data extraction — rule + OCR strategies, handoff for LLM inference.

Strategies (in order):

    1. Adjacent-data-table lookup — many reports include a data table next to
       the chart image. Most reliable signal, highest confidence.
    2. OCR-ish extraction of labels/numbers from the image itself (pymupdf
       words). Best-effort scaffold for better OCR to slot in later.
    3. *LLM inference* — deferred to the Classifier subagent (in chart-
       inference mode) via the handoff queue, not an in-process API call.

``extract_all`` returns ``(blocks, pending, warnings)``. Anything still below
``CONFIDENCE_FLOOR`` is emitted to the pending queue so the orchestrator can
dispatch the Classifier subagent (see handoff-protocol.md → "chart_infer").
The figure survives as a Figure block until the agent upgrades it.
"""
from __future__ import annotations

import re

from .model import Block, Chart, ChartKind, Figure, Series, Table


CONFIDENCE_FLOOR = 0.7


def extract_all(blocks: list[Block]) -> tuple[list[Block], list[dict], list[str]]:
    """Walk blocks, upgrade figures → charts where rules allow.

    Returns ``(new_blocks, pending, warnings)``. ``pending`` holds chart-
    inference items for the orchestrator; figures whose image bytes are
    too small to be a chart are left untouched with no pending entry.
    """
    warnings: list[str] = []
    pending: list[dict] = []
    if not blocks:
        return blocks, pending, warnings

    out: list[Block] = []
    for i, b in enumerate(blocks):
        if b.kind != "figure":
            out.append(b)
            continue
        fig: Figure = b.content
        if not _is_chart_candidate(fig):
            out.append(b)
            continue

        chart = _try_rules(blocks, i)
        if chart is not None and chart.extraction_confidence >= CONFIDENCE_FLOOR:
            out.append(Block(kind="chart", classification_source="rule",
                             content=chart, source_index=b.source_index))
            continue

        # Rules were inconclusive. Keep the Figure for render fallback AND
        # emit a pending item so the orchestrator can ask an agent. Index
        # refers to the block position in the new `out` list, which matches
        # `len(out)` right before we append.
        out.append(b)
        pending.append({
            "block_index": len(out) - 1,
            "payload": _pending_payload(blocks, i),
            "rule_suggestion": chart.kind if chart else None,
            "rule_confidence": chart.extraction_confidence if chart else 0.0,
            "reason": "chart-extraction confidence below floor",
        })
        if chart is not None:
            warnings.append(
                f"chart at block {i} extracted with low confidence "
                f"({chart.extraction_confidence:.2f} via {chart.extraction_strategy})"
            )
    return out, pending, warnings


def _is_chart_candidate(fig: Figure) -> bool:
    return bool(fig.image_bytes) and len(fig.image_bytes) >= 800


def _try_rules(blocks: list[Block], i: int) -> Chart | None:
    """Run the two non-LLM strategies; return the best Chart or None."""
    chart = _from_adjacent_table(blocks, i)
    if chart is not None and chart.extraction_confidence >= CONFIDENCE_FLOOR:
        return chart

    chart2 = _from_image_words(blocks[i].content)
    if chart2 is not None and (chart is None or chart2.extraction_confidence > chart.extraction_confidence):
        chart = chart2
    return chart


# ── Strategy 1: adjacent data table ─────────────────────────────────────────

def _from_adjacent_table(blocks: list[Block], i: int) -> Chart | None:
    neighbors: list[tuple[int, Block]] = []
    for j in (i - 1, i + 1, i - 2, i + 2):
        if 0 <= j < len(blocks) and blocks[j].kind == "table":
            neighbors.append((j, blocks[j]))
    for _, nb in neighbors:
        chart = _table_to_chart(nb.content)
        if chart is not None:
            chart.extraction_strategy = "adjacent_table"
            chart.extraction_confidence = 0.9
            return chart
    return None


_NUM_RE = re.compile(r'^-?[\$€£¥]?\s*-?\d[\d,]*(?:\.\d+)?\s*[KkMmBb]?\s*%?$')


def _to_float(s: str) -> float | None:
    if not s:
        return None
    s = s.strip().replace("$", "").replace("€", "").replace("£", "").replace("¥", "")
    mult = 1.0
    if s.endswith("%"):
        s = s[:-1].strip()
    if s.endswith(("K", "k")):
        mult, s = 1_000.0, s[:-1]
    elif s.endswith(("M", "m")):
        mult, s = 1_000_000.0, s[:-1]
    elif s.endswith(("B", "b")):
        mult, s = 1_000_000_000.0, s[:-1]
    try:
        return float(s.replace(",", "")) * mult
    except ValueError:
        return None


def _table_to_chart(tbl: Table) -> Chart | None:
    if not tbl.rows or not tbl.headers:
        return None
    header = tbl.headers[-1]
    if len(header) < 2:
        return None

    series_names = header[1:]
    categories: list[str] = []
    series_values: list[list[float]] = [[] for _ in series_names]

    for row in tbl.rows:
        if not row:
            continue
        cat = (row[0] or "").strip()
        if not cat:
            continue
        categories.append(cat)
        for col_idx, name in enumerate(series_names):
            cell_idx = col_idx + 1
            v = _to_float(row[cell_idx]) if cell_idx < len(row) else None
            if v is None:
                return None
            series_values[col_idx].append(v)

    if not categories:
        return None
    series = [Series(name=n.strip(), values=v)
              for n, v in zip(series_names, series_values)]
    kind: ChartKind = "bar" if len(categories) > 6 else "column"
    return Chart(
        kind=kind,
        title=(tbl.caption or None),
        categories=categories,
        series=series,
    )


# ── Strategy 2: image words (OCR-ish) ────────────────────────────────────────

def _from_image_words(fig: Figure) -> Chart | None:
    try:
        import fitz  # pymupdf
    except Exception:
        return None

    try:
        ext = (fig.image_format or "png").lower()
        if ext == "jpg":
            ext = "jpeg"
        doc = fitz.open(stream=fig.image_bytes, filetype=ext)
    except Exception:
        return None

    tokens: list[tuple[str, float, float]] = []
    try:
        for page in doc:
            for b in page.get_text("blocks"):
                if len(b) >= 5:
                    x0, y0, x1, y1, txt = b[:5]
                    for line in (txt or "").splitlines():
                        line = line.strip()
                        if line:
                            tokens.append((line, float(x0), float(y0)))
    finally:
        try:
            doc.close()
        except Exception:
            pass

    if not tokens:
        return None

    nums: list[tuple[str, float, float]] = []
    labs: list[tuple[str, float, float]] = []
    for t, x, y in tokens:
        (nums if _NUM_RE.match(t) else labs).append((t, x, y))
    if len(nums) < 2 or len(labs) < 2:
        return None

    pairs: list[tuple[str, float]] = []
    for lt, lx, ly in labs:
        if len(pairs) >= 16:
            break
        best = None
        best_d = float("inf")
        for nt, nx, ny in nums:
            d = (nx - lx) ** 2 + (ny - ly) ** 2
            if d < best_d:
                best_d = d
                best = (nt, nx, ny)
        if best is None:
            continue
        val = _to_float(best[0])
        if val is None:
            continue
        pairs.append((lt, val))

    if len(pairs) < 2:
        return None

    cats = [p[0] for p in pairs]
    vals = [p[1] for p in pairs]
    return Chart(
        kind="column",
        title=None,
        categories=cats,
        series=[Series(name="Series 1", values=vals)],
        extraction_strategy="ocr",
        extraction_confidence=0.6,
    )


# ── Pending payload + resolution application ────────────────────────────────

def _pending_payload(blocks: list[Block], i: int) -> dict:
    """Build the chart-infer payload for the orchestrator."""
    return {
        "nearby_narrative": _nearby_narrative(blocks, i),
        "block_kind": "chart_candidate",
        "image_size_bytes": len(blocks[i].content.image_bytes or b""),
    }


def _nearby_narrative(blocks: list[Block], i: int, radius: int = 3) -> str:
    out: list[str] = []
    for j in range(max(0, i - radius), min(len(blocks), i + radius + 1)):
        if j == i:
            continue
        b = blocks[j]
        if b.kind == "paragraph":
            out.append(b.content.text if hasattr(b.content, "text") else "")
        elif b.kind == "heading":
            out.append(f"# {b.content.text}")
        elif b.kind == "callout":
            body_text = " ".join(
                "".join(r.text for r in p.runs) for p in b.content.body
            )
            out.append(f"[{b.content.label}] {body_text}")
    return "\n".join(x for x in out if x).strip()


def apply_resolutions(blocks: list[Block], resolutions: dict[int, dict]) -> list[Block]:
    """Apply Classifier chart-inference resolutions to figure blocks.

    A resolution with ``kind`` in the valid chart set and
    ``confidence >= CONFIDENCE_FLOOR`` upgrades a Figure to a Chart block.
    Anything else is ignored; the original Figure survives.
    """
    if not resolutions:
        return blocks
    updated = list(blocks)
    for idx, res in resolutions.items():
        if idx < 0 or idx >= len(updated):
            continue
        if updated[idx].kind != "figure":
            continue
        kind = res.get("kind")
        if kind not in ("bar", "column", "line", "pie", "donut", "funnel", "stacked", "other"):
            continue
        conf = float(res.get("confidence") or 0.0)
        if conf < CONFIDENCE_FLOOR:
            continue
        cats = [str(c) for c in (res.get("categories") or [])]
        series = [
            Series(name=str(s.get("name") or ""), values=[float(v) for v in s.get("values") or []])
            for s in (res.get("series") or [])
        ]
        if not cats or not series:
            continue
        chart = Chart(
            kind=kind,
            title=res.get("title"),
            categories=cats,
            series=series,
            extraction_strategy="claude_infer",
            extraction_confidence=conf,
        )
        orig = updated[idx]
        updated[idx] = Block(
            kind="chart",
            classification_source="claude",
            content=chart,
            source_index=orig.source_index,
            notes=orig.notes,
        )
    return updated
