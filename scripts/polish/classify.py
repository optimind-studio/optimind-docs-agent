"""Classify primitive blocks into typed canonical Blocks (v0.5).

Rule-based classifier — covers ~90% of common cases. Anything the rules cannot
confidently label is emitted to the *pending queue* so the orchestrator can
hand it off to the Classifier subagent. This module no longer imports the
Anthropic SDK; all LLM reasoning happens in the user's Claude Code session.

Outputs:

    blocks:   list[Block]           — the canonical stream (rule-tagged)
    pending:  list[dict]            — items needing agent resolution
    warnings: list[str]

Each pending item carries enough context (payload + ≤8 neighbors) that the
Classifier agent can decide without re-parsing the source document. The
``block_index`` field aligns with the index into ``blocks`` so the orchestrator
can splice resolutions back in on ``--resume``.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable

from .model import (
    Block, Callout, Document, Figure, Heading, KPICard, KPIStrip,
    List as ListBlock, ListItem, MergeSpec, Paragraph, Run, Table,
)


NEIGHBOR_RADIUS = 4


# ── Main entrypoint ─────────────────────────────────────────────────────────

def classify(primitives: Iterable[dict]) -> tuple[list[Block], list[dict], list[str]]:
    """Classify primitive blocks.

    Returns ``(blocks, pending, warnings)``.

    * ``blocks`` is the typed stream. Ambiguous paragraphs are labeled with
      ``classification_source="rule"`` and ``kind="paragraph"`` as a safe
      default; the matching pending entry lets an agent upgrade the kind.
    * ``pending`` contains {block_index, payload, neighbors_before,
      neighbors_after} dicts for items that benefit from agent review. The
      orchestrator writes these to ``state_dir/pending/classify/`` and
      dispatches the Classifier subagent.
    """
    primitives = list(primitives)
    blocks: list[Block] = []
    pending: list[dict] = []
    warnings: list[str] = []
    running_source_idx = 0

    for prim in primitives:
        produced = _classify_primitive(prim, pending=pending, warnings=warnings)
        for b in produced:
            b.source_index = running_source_idx
            running_source_idx += 1
            blocks.append(b)

    # Rewrite pending block_index values to match the final block list.
    # _classify_primitive appends pending entries with the *in-progress* index
    # of the block they describe. Because blocks are appended in order, that
    # equals the final index — no remapping needed.
    _attach_neighbors(blocks, pending)
    return blocks, pending, warnings


def _attach_neighbors(blocks: list[Block], pending: list[dict]) -> None:
    """Fill in ``neighbors_before`` / ``neighbors_after`` for each pending item.

    Neighbor previews are stable snippets the agent uses to judge context
    without loading every block file from disk.
    """
    for item in pending:
        idx = item.get("block_index", -1)
        if idx < 0 or idx >= len(blocks):
            continue
        before = blocks[max(0, idx - NEIGHBOR_RADIUS):idx]
        after = blocks[idx + 1:idx + 1 + NEIGHBOR_RADIUS]
        item["neighbors_before"] = [_neighbor_summary(j, b) for j, b in
                                    enumerate(before, start=max(0, idx - NEIGHBOR_RADIUS))]
        item["neighbors_after"] = [_neighbor_summary(j, b) for j, b in
                                   enumerate(after, start=idx + 1)]


def _neighbor_summary(block_index: int, block: Block) -> dict:
    kind = block.kind
    text_preview = ""
    c = block.content
    if kind == "heading":
        text_preview = c.text[:120]
    elif kind == "paragraph":
        text_preview = ("".join(r.text for r in c.runs))[:120]
    elif kind == "callout":
        text_preview = f"[{c.label}] " + " ".join(
            "".join(r.text for r in p.runs) for p in c.body
        )[:100]
    elif kind == "list":
        text_preview = " · ".join(
            ("".join(r.text for r in it.runs))[:40] for it in c.items[:3]
        )
    elif kind == "table":
        text_preview = f"[table {len(c.rows)}r × {len(c.headers[0]) if c.headers else 0}c]"
    return {"block_index": block_index, "kind": kind, "text_preview": text_preview}


# ── Dispatch ────────────────────────────────────────────────────────────────

def _classify_primitive(
    prim: dict, *, pending: list[dict], warnings: list[str]
) -> list[Block]:
    kind = prim.get("kind")

    if kind == "table_primitive":
        return [_to_table_block(prim["tokens"][0])]

    if kind == "figure_primitive":
        return [_to_figure_block(prim["tokens"][0])]

    if kind == "list_group":
        return [_to_list_block(prim["tokens"])]

    if kind == "shaded_group":
        return [_to_callout_block(prim["tokens"])]

    if kind == "text_primitive":
        return _classify_text(prim["tokens"], pending=pending, warnings=warnings)

    # Unknown primitive kind → queue for agent review as an "unknown" block.
    placeholder = Block(
        kind="paragraph",
        classification_source="unknown",
        content=Paragraph(runs=[Run(text=(prim.get("text") or "").strip())]),
        notes=[f"unclassified-primitive:{kind}"],
    )
    pending.append({
        "block_index": -1,  # patched after the block is appended
        "payload": _pending_payload_from_primitive(prim),
        "rule_suggestion": "unknown",
        "reason": f"unknown primitive kind: {kind!r}",
    })
    return [placeholder]


# ── Table ───────────────────────────────────────────────────────────────────

def _to_table_block(tok: dict) -> Block:
    raw_rows = tok.get("rows") or []
    if not raw_rows:
        return Block(kind="table", classification_source="rule",
                     content=Table(headers=[], rows=[]))

    header_rows_guess = _detect_header_rows(raw_rows)
    headers: list[list[str]] = []
    body: list[list[str]] = []
    merges: list[MergeSpec] = []

    for row_idx, row in enumerate(raw_rows):
        flat_cells: list[str] = []
        col_cursor = 0
        for cell in row:
            text = (cell.get("text") or "").strip()
            colspan = int(cell.get("colspan") or 1)
            flat_cells.append(text)
            if colspan > 1:
                merges.append(MergeSpec(row=row_idx, col=col_cursor, colspan=colspan))
            if cell.get("vmerge_continuation"):
                _extend_vmerge(merges, row_idx=row_idx, col=col_cursor)
            col_cursor += colspan
        if row_idx < header_rows_guess:
            headers.append(flat_cells)
        else:
            body.append(flat_cells)

    variant = _pick_variant(body)
    return Block(
        kind="table",
        classification_source="rule",
        content=Table(headers=headers, rows=body, variant=variant, merges=merges),
    )


def _detect_header_rows(raw_rows: list[list[dict]]) -> int:
    """Heuristic: a top row is a header if its cells are mostly non-numeric
    AND short. Cap at 3 header rows."""
    header_count = 0
    for row in raw_rows[:3]:
        texts = [(c.get("text") or "").strip() for c in row]
        non_empty = [t for t in texts if t]
        if not non_empty:
            break
        numeric = sum(1 for t in non_empty if _is_numeric(t))
        if numeric > len(non_empty) * 0.3:
            break
        avg_len = sum(len(t) for t in non_empty) / len(non_empty)
        if avg_len > 40:
            break
        header_count += 1
    return max(1, header_count) if raw_rows else 0


def _pick_variant(body_rows: list[list[str]]) -> str:
    if not body_rows:
        return "classic"
    total = numeric = 0
    for row in body_rows:
        for cell in row:
            text = (cell or "").strip()
            if not text:
                continue
            total += 1
            if _is_numeric(text):
                numeric += 1
    if total == 0:
        return "classic"
    return "minimal" if numeric / total >= 0.6 else "classic"


def _extend_vmerge(merges: list[MergeSpec], row_idx: int, col: int) -> None:
    for m in reversed(merges):
        if m.col == col and m.row + m.rowspan == row_idx:
            merges.remove(m)
            merges.append(replace(m, rowspan=m.rowspan + 1))
            return


_NUMERIC_RE = re.compile(r'^\s*[\$€£¥]?\s*[-+]?\d[\d,]*(\.\d+)?\s*%?\s*$')


def _is_numeric(text: str) -> bool:
    return bool(_NUMERIC_RE.match(text))


# ── Figure ──────────────────────────────────────────────────────────────────

def _to_figure_block(tok: dict) -> Block:
    return Block(
        kind="figure",
        classification_source="rule",
        content=Figure(
            image_bytes=tok.get("image_bytes") or b"",
            image_format=tok.get("image_format") or "png",
            caption=None, alt=None,
        ),
    )


# ── List ────────────────────────────────────────────────────────────────────

def _to_list_block(tokens: list[dict]) -> Block:
    items: list[ListItem] = []
    for t in tokens:
        runs = [Run(text=r.get("text", ""), bold=r.get("bold", False),
                    italic=r.get("italic", False))
                for r in (t.get("runs") or [])]
        numbering = t.get("numbering") or {}
        ilvl = int(numbering.get("ilvl", 0))
        items.append(ListItem(runs=runs, level=ilvl, ordered=_looks_ordered(t)))
    return Block(kind="list", classification_source="rule",
                 content=ListBlock(items=items))


def _looks_ordered(tok: dict) -> bool:
    numbering = tok.get("numbering") or {}
    if numbering.get("style_ordered"):
        return True
    text = (tok.get("text") or "").strip()
    return bool(re.match(r'^\d+[\.\)]\s', text))


# ── Callout ─────────────────────────────────────────────────────────────────

_PINK_FILLS = {"FEECEE", "FEE", "FFE5E5", "FDDDE0", "FFE0E0", "FFEAEA", "FFEBEE"}
_WARN_TRIGGERS = ("warning", "caution", "alert")
_NEXT_STEPS_TRIGGERS = ("next steps", "action items", "action plan", "to do")


def _to_callout_block(tokens: list[dict]) -> Block:
    fills = [t.get("shading_hex") for t in tokens if t.get("shading_hex")]
    fill = fills[0] if fills else None
    first_text = (tokens[0].get("text") or "").strip().lower() if tokens else ""

    variant = "note"
    if fill and fill.upper() in _PINK_FILLS:
        variant = "insight"
    if any(k in first_text for k in _WARN_TRIGGERS):
        variant = "warning"
    elif any(k in first_text for k in _NEXT_STEPS_TRIGGERS):
        variant = "next_steps"
    elif "insight" in first_text or "key" in first_text:
        variant = "insight"

    if tokens:
        label = (tokens[0].get("text") or "").strip() or variant.replace("_", " ").upper()
        body_paras = []
        for t in tokens[1:]:
            runs = [Run(text=r.get("text", ""), bold=r.get("bold", False),
                        italic=r.get("italic", False))
                    for r in (t.get("runs") or []) if r.get("text")]
            if runs:
                body_paras.append(Paragraph(runs=runs))
    else:
        label = variant.replace("_", " ").upper()
        body_paras = []

    label = label.rstrip(":")

    return Block(
        kind="callout",
        classification_source="rule",
        content=Callout(variant=variant, label=label.upper(), body=body_paras),
    )


# ── Text primitive ──────────────────────────────────────────────────────────

def _classify_text(
    tokens: list[dict], *, pending: list[dict], warnings: list[str]
) -> list[Block]:
    out: list[Block] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        text = (tok.get("text") or "").strip()
        if not text and not tok.get("inline_images"):
            i += 1
            continue

        hint = tok.get("heading_level_hint")
        if hint is not None and _looks_like_heading(text):
            out.append(Block(
                kind="heading",
                classification_source="rule",
                content=Heading(level=min(3, max(1, int(hint))), text=text),
            ))
            i += 1
            continue

        strip, skip = _try_extract_kpi_strip(tokens, start=i)
        if strip is not None:
            out.append(Block(
                kind="kpi_strip",
                classification_source="rule",
                content=strip,
            ))
            i += skip
            continue

        runs = [Run(text=r.get("text", ""), bold=r.get("bold", False),
                    italic=r.get("italic", False))
                for r in (tok.get("runs") or []) if r.get("text")]
        if not runs:
            runs = [Run(text=text)]

        # Default: paragraph. If the paragraph is ambiguous, queue it for
        # agent review — the rule-based result is kept as a safe fallback so
        # the pipeline can continue even if the agent declines to resolve.
        block = Block(
            kind="paragraph",
            classification_source="rule",
            content=Paragraph(runs=runs),
        )
        out.append(block)

        if _is_ambiguous_paragraph(tok, text):
            pending.append({
                "block_index": -1,  # patched by caller
                "payload": _pending_payload_from_text_token(tok, text),
                "rule_suggestion": "paragraph",
                "reason": "ambiguous text primitive",
            })
            # Patch the pending block_index to the index of the block we just
            # appended, relative to the calling context's running index.
            # The outer `classify()` pass realigns these on completion.
            pending[-1]["_local_index_within_text_primitive"] = len(out) - 1

        i += 1
    return out


def _looks_like_heading(text: str) -> bool:
    if len(text) > 120:
        return False
    if text.endswith(".") and len(text.split()) > 12:
        return False
    return True


# ── KPI strip detection ─────────────────────────────────────────────────────

_KPI_VALUE_RE = re.compile(
    r'^\s*[\$€£¥]?\s*[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*[KkMmBb]?\s*%?\s*$'
    r'|^\s*[\$€£¥]?\s*[-+]?\d+(?:\.\d+)?\s*[KkMmBb]?\s*%?\s*$'
)
_MASHED_VALUE_RE = re.compile(r'%\s*\d|\d\s*[\$€£¥]\s*\d')
_KPI_LABEL_MAX_LEN = 40
_KPI_LABEL_MIN_LEN = 2
_LABEL_LETTER_RUN_RE = re.compile(r'[A-Za-z]{2,}')
_SECTION_HEADING_RES = [
    re.compile(r'^\d{1,2}\s*[—–-]\s+[A-Za-z]'),
    re.compile(r'^\d{1,3}\.\s+[A-Za-z]'),
    re.compile(r'^\d{1,3}\.\d+\s+[A-Za-z]'),
    re.compile(r'^\d{1,3}\.\d+\.\d+\s+[A-Za-z]'),
    re.compile(r'^Section\s+\d+', re.IGNORECASE),
    re.compile(r'^Chapter\s+\d+', re.IGNORECASE),
]


def _is_kpi_value(text: str) -> bool:
    if not text:
        return False
    if _MASHED_VALUE_RE.search(text):
        return False
    if text.count("%") > 1 or text.count("$") > 1:
        return False
    return bool(_KPI_VALUE_RE.match(text))


def _is_kpi_label(text: str) -> bool:
    if not text:
        return False
    n = len(text)
    if n < _KPI_LABEL_MIN_LEN or n > _KPI_LABEL_MAX_LEN:
        return False
    if _is_kpi_value(text):
        return False
    if _MASHED_VALUE_RE.search(text):
        return False
    digit_count = sum(ch.isdigit() for ch in text)
    if digit_count > max(2, n // 3):
        return False
    if not _LABEL_LETTER_RUN_RE.search(text):
        return False
    for rx in _SECTION_HEADING_RES:
        if rx.match(text):
            return False
    return True


def _try_extract_kpi_strip(tokens: list[dict], start: int) -> tuple[KPIStrip | None, int]:
    window = tokens[start:start + 12]
    if len(window) < 4:
        return None, 0
    texts = [(t.get("text") or "").strip() for t in window]

    # Pattern A: v, l, v, l, …
    pairs: list[KPICard] = []
    j = 0
    while j + 1 < len(window):
        v, l = texts[j], texts[j + 1]
        if _is_kpi_value(v) and _is_kpi_label(l):
            pairs.append(KPICard(value=v, label=l, delta=None))
            j += 2
            if len(pairs) >= 5:
                break
        else:
            break
    if len(pairs) >= 2:
        return KPIStrip(cards=pairs), j

    # Pattern B: values-run then labels-run.
    values: list[str] = []
    k = 0
    while k < len(window) and _is_kpi_value(texts[k]):
        values.append(texts[k])
        k += 1
        if len(values) >= 5:
            break
    if 2 <= len(values) <= 5:
        labels: list[str] = []
        while k < len(window) and len(labels) < len(values):
            if _is_kpi_label(texts[k]):
                labels.append(texts[k])
                k += 1
            else:
                break
        if len(labels) == len(values):
            cards = [KPICard(value=v, label=l) for v, l in zip(values, labels)]
            return KPIStrip(cards=cards), k
    return None, 0


# ── Ambiguity detection + pending payload ──────────────────────────────────

_AMBIGUOUS_MAX_LEN = 140
_AMBIGUOUS_PREFIXES = ("▶", "→", "•", "★", "⚡", "✱", "🔑")


def _is_ambiguous_paragraph(tok: dict, text: str) -> bool:
    """Paragraphs that might actually be a heading / callout header."""
    if not text or len(text) > _AMBIGUOUS_MAX_LEN:
        return False
    if text.isupper() and 3 < len(text) < 80:
        return True
    stripped = text.lstrip()
    if stripped and stripped[0] in _AMBIGUOUS_PREFIXES:
        return True
    return False


def _pending_payload_from_text_token(tok: dict, text: str) -> dict:
    """Shape matches handoff-protocol.md for Classifier payloads."""
    return {
        "text": text,
        "runs": [
            {
                "text": r.get("text") or "",
                "bold": bool(r.get("bold")),
                "italic": bool(r.get("italic")),
            }
            for r in (tok.get("runs") or [])
        ],
        "shading_hex": tok.get("shading_hex"),
        "heading_level_hint": tok.get("heading_level_hint"),
        "kind_hint": "text",
    }


def _pending_payload_from_primitive(prim: dict) -> dict:
    """Fallback payload for unknown primitive kinds — richer debug context."""
    tokens = prim.get("tokens") or []
    first = tokens[0] if tokens else {}
    return {
        "text": (first.get("text") or "")[:400],
        "shading_hex": first.get("shading_hex"),
        "primitive_kind": prim.get("kind"),
        "n_tokens": len(tokens),
        "kind_hint": prim.get("kind"),
    }


# ── Apply agent resolutions on --resume ─────────────────────────────────────

def apply_resolutions(blocks: list[Block], resolutions: dict[int, dict]) -> list[Block]:
    """Splice agent-returned classifications into the rule-based block stream.

    ``resolutions`` is keyed by block_index (as written to resolutions/classify/).
    Any resolution with ``confidence < 0.6`` or ``kind == "unknown"`` is
    ignored — the safe rule-based fallback stands.
    """
    updated = list(blocks)
    for idx, res in resolutions.items():
        if idx < 0 or idx >= len(updated):
            continue
        conf = float(res.get("confidence") or 0.0)
        kind = res.get("kind")
        if not kind or kind == "unknown" or conf < 0.6:
            continue
        new_block = _block_from_resolution(kind, res, existing=updated[idx])
        if new_block is not None:
            updated[idx] = new_block
    return updated


def _block_from_resolution(kind: str, res: dict, *, existing: Block) -> Block | None:
    text = _existing_text(existing)
    if kind == "heading":
        level = int(res.get("level") or 2)
        level = max(1, min(3, level))
        return Block(kind="heading", classification_source="claude",
                     content=Heading(level=level, text=text),
                     source_index=existing.source_index, notes=existing.notes)
    if kind == "callout":
        variant = res.get("variant") or "note"
        if variant not in ("insight", "next_steps", "warning", "note"):
            variant = "note"
        label = (res.get("label") or variant.replace("_", " ").upper()).upper()
        return Block(kind="callout", classification_source="claude",
                     content=Callout(variant=variant, label=label,
                                     body=[Paragraph(runs=[Run(text=text)])]),
                     source_index=existing.source_index, notes=existing.notes)
    if kind == "paragraph":
        # Resolution confirms the rule — no change needed.
        return None
    return None


def _existing_text(block: Block) -> str:
    c = block.content
    if block.kind == "paragraph":
        return "".join(r.text for r in c.runs)
    if block.kind == "heading":
        return c.text
    if block.kind == "callout":
        return " ".join("".join(r.text for r in p.runs) for p in c.body)
    return ""
