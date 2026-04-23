"""Sidecar writer — JSON classification dump + HTML report.

Writes two sibling files next to the polished .docx:

    <basename>.classification.json   machine-readable block breakdown (kept
                                     backwards-compatible with 0.3.x)
    <basename>.report.html           human-readable Optimind-branded report
                                     (new in 0.5 — see references/report-
                                     template.html)
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .model import Document


def write_sidecar(doc: Document, output_docx_path: Path) -> Path:
    """Write <output>.classification.json and return the path."""
    sidecar = output_docx_path.with_suffix(".classification.json")
    payload = {
        "title": doc.title,
        "client": doc.client,
        "period": doc.period,
        "counts": _counts(doc),
        "warnings": doc.warnings,
        "unclassified": doc.unclassified,
        "blocks": [_block_summary(i, b) for i, b in enumerate(doc.blocks)],
    }
    sidecar.write_text(json.dumps(payload, indent=2, default=str))
    return sidecar


def write_html_report(
    *,
    state: dict,
    blocks: list[dict],
    findings: list[dict],
    duration_s: float,
    input_path: Path,
    output_path: Path,
    sidecar_path: Path,
    figma_file_key: str | None = None,
) -> Path:
    """Render the HTML report next to the output .docx."""
    from . import html_report

    ctx = html_report.build_context(
        state=state,
        blocks=blocks,
        findings=findings,
        duration_s=duration_s,
        input_path=input_path,
        output_path=output_path,
        sidecar_path=sidecar_path,
        figma_file_key=figma_file_key,
    )
    report_path = output_path.with_suffix(".report.html")
    return html_report.render_report(ctx, report_path)


def _counts(doc: Document) -> dict[str, int]:
    counts: dict[str, int] = {}
    for b in doc.blocks:
        counts[b.kind] = counts.get(b.kind, 0) + 1
    return counts


def _block_summary(index: int, block) -> dict:
    out: dict = {
        "index": index,
        "kind": block.kind,
        "source": block.classification_source,
    }
    if block.notes:
        out["notes"] = list(block.notes)
    c = block.content
    if block.kind == "chart":
        out["chart"] = {
            "kind": c.kind,
            "title": c.title,
            "categories": len(c.categories),
            "series": len(c.series),
            "extraction_strategy": c.extraction_strategy,
            "extraction_confidence": round(c.extraction_confidence, 3),
        }
    elif block.kind == "table":
        out["table"] = {
            "headers": len(c.headers),
            "rows": len(c.rows),
            "variant": c.variant,
            "merges": len(c.merges),
        }
    elif block.kind == "kpi_strip":
        out["cards"] = len(c.cards)
    elif block.kind == "callout":
        out["variant"] = c.variant
    elif block.kind == "heading":
        out["level"] = c.level
        out["text"] = c.text
    return out
