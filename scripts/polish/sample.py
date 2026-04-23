"""Deterministic sampling for the Auditor.

The Auditor agent cannot see every block in a 200-page document; we'd blow
its context budget. Instead we pick a representative sample with two
guarantees:

    1. Scale-aware page coverage — every Nth page (N shrinks for smaller
       docs). Finance staff reviewing Auditor output need enough coverage
       that systemic issues can't hide between the samples.

    2. Event-driven coverage — every heading, every table, every chart,
       every callout, every DS-extended block, every warning-tagged block
       is *always* included regardless of page N. These are the blocks
       most likely to need human review.

Sample order is sorted and deduped. For a 200-page, 1500-block doc the
expected sample size caps at ~150 blocks, which we chunk into ~30-block
Auditor calls in the orchestrator.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from . import state as state_mod


# ── Cadence by doc size ─────────────────────────────────────────────────────

def every_nth_page_for(page_count: int) -> int:
    """Nth-page cadence based on total page count.

    <50 pages → every 3rd page. 50-99 → every 5th. ≥100 → every 10th.
    """
    if page_count < 50:
        return 3
    if page_count < 100:
        return 5
    return 10


# ── Core sampler ────────────────────────────────────────────────────────────

SAMPLE_KINDS_ALWAYS = {"heading", "table", "chart", "callout", "kpi_strip"}


def select_sample(blocks: list[dict], *, page_count: int) -> list[int]:
    """Deterministic index selection. `blocks` is a list of canonical block
    dicts (as written to ``state_dir/blocks/``).

    The returned list is sorted ascending with no duplicates.
    """
    if not blocks:
        return []

    n = every_nth_page_for(page_count or 1)
    selected: set[int] = set()

    # Page-coverage: every Nth page, take the first block on that page.
    seen_pages: set[int] = set()
    for i, b in enumerate(blocks):
        p = _page_number(b)
        if p is None:
            continue
        if p in seen_pages:
            continue
        if p % n == 0 or p == 1:
            selected.add(i)
        seen_pages.add(p)

    # Event coverage: always-include kinds.
    for i, b in enumerate(blocks):
        kind = b.get("kind")
        if kind in SAMPLE_KINDS_ALWAYS:
            selected.add(i)
        if b.get("is_ds_extension"):
            selected.add(i)
        if b.get("warning_flags"):
            selected.add(i)

    return sorted(selected)


def _page_number(block: dict) -> int | None:
    """Extract page_number from a block payload if present.

    `parse` stage is responsible for stamping page_number onto every block
    dict. If it's missing we treat the block as page-agnostic.
    """
    v = block.get("page_number")
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


# ── Chunking for Auditor invocations ────────────────────────────────────────

def chunk_for_auditor(indices: list[int], *, chunk_size: int = 30) -> list[list[int]]:
    """Split the sample into Auditor-sized chunks.

    Each chunk becomes one Auditor invocation. 30 blocks per chunk keeps
    any single agent call ≤ ~50K tokens even with neighbor context.
    """
    if not indices:
        return []
    out: list[list[int]] = []
    for i in range(0, len(indices), chunk_size):
        out.append(indices[i:i + chunk_size])
    return out


# ── Persistence ─────────────────────────────────────────────────────────────

def save_sample(state_dir: Path, indices: list[int]) -> Path:
    d = state_mod.audit_dir(state_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "sample_indices.json"
    p.write_text(json.dumps({"sample": indices}, indent=2))
    return p


def load_sample(state_dir: Path) -> list[int]:
    p = state_mod.audit_dir(state_dir) / "sample_indices.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return list(data.get("sample") or [])


# ── Page-count estimator ────────────────────────────────────────────────────

def estimate_page_count(blocks: Iterable[dict]) -> int:
    """Best-effort page count: max page_number seen, or 1."""
    pages = [b.get("page_number") for b in blocks if b.get("page_number")]
    if not pages:
        return 1
    try:
        return max(int(p) for p in pages)
    except Exception:
        return 1
