"""Walk flattened tokens into primitive blocks ready for classification.

A primitive block is a semantic unit the classifier can label with one call.
Grouping rules:
  - Consecutive list-item paragraphs → `list_group` (homogeneous by numId/indent)
  - Consecutive shaded paragraphs with the same fill → `shaded_group` (callout candidate)
  - Table tokens pass through as `table_primitive`
  - Image tokens pass through as `figure_primitive`
  - Everything else becomes a `text_primitive` (paragraph-at-a-time)

Downstream the classifier may regroup further (e.g. a `text_primitive` that is
really a KPI strip + its label pair).
"""
from __future__ import annotations

from typing import Iterable, Iterator


def build_blocks(tokens: Iterable[dict]) -> Iterator[dict]:
    buf: list[dict] = []
    current_mode: str | None = None   # "list" | "shaded" | None

    def flush():
        nonlocal buf, current_mode
        if not buf:
            return
        if current_mode == "list":
            yield_kind = "list_group"
        elif current_mode == "shaded":
            yield_kind = "shaded_group"
        else:
            yield_kind = "text_primitive"
        yield {
            "kind": yield_kind,
            "source_indices": [t["source_index"] for t in buf],
            "tokens": list(buf),
        }
        buf = []
        current_mode = None

    # Collect into a list to support flush-yield pattern cleanly.
    out: list[dict] = []

    def flush_out():
        nonlocal buf, current_mode
        if not buf:
            return
        if current_mode == "list":
            yield_kind = "list_group"
        elif current_mode == "shaded":
            yield_kind = "shaded_group"
        else:
            yield_kind = "text_primitive"
        out.append({
            "kind": yield_kind,
            "source_indices": [t["source_index"] for t in buf],
            "tokens": list(buf),
        })
        buf = []
        current_mode = None

    for tok in tokens:
        kind = tok.get("kind")
        if kind == "table":
            flush_out()
            out.append({"kind": "table_primitive", "source_indices": [tok["source_index"]], "tokens": [tok]})
            continue
        if kind == "image":
            flush_out()
            out.append({"kind": "figure_primitive", "source_indices": [tok["source_index"]], "tokens": [tok]})
            continue
        # paragraph
        is_list = tok.get("numbering") is not None
        is_shaded = tok.get("shading_hex") is not None

        if is_list:
            target = "list"
        elif is_shaded:
            target = "shaded"
        else:
            target = "text"

        if target != (current_mode or "text"):
            flush_out()
            current_mode = target if target != "text" else None

        buf.append(tok)

    flush_out()
    yield from out
