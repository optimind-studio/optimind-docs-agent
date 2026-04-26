"""Canonical document model — the only thing the renderer sees.

Blocks are immutable-ish dataclasses; a Document is an ordered list of Blocks.
Anything that cannot be expressed in this schema fails classification and the
pipeline hard-fails with a report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union


# ── Primitives ───────────────────────────────────────────────────────────────

@dataclass
class Run:
    """Styled text span within a paragraph."""
    text: str
    bold: bool = False
    italic: bool = False


@dataclass
class Paragraph:
    runs: list[Run]

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class Heading:
    level: Literal[1, 2, 3]
    text: str


@dataclass
class ListItem:
    runs: list[Run]
    level: int = 0          # 0-based indentation depth
    ordered: bool = False


@dataclass
class List:
    items: list[ListItem]


# ── Tables ───────────────────────────────────────────────────────────────────

@dataclass
class MergeSpec:
    """Cell merge hint. 0-indexed."""
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1


@dataclass
class Table:
    headers: list[list[str]]            # list of header rows (supports multi-row headers)
    rows: list[list[str]]
    variant: str = "classic"  # reserved — always renders as classic
    merges: list[MergeSpec] = field(default_factory=list)
    caption: str | None = None


# ── KPI strip ────────────────────────────────────────────────────────────────

@dataclass
class KPICard:
    value: str              # display string; e.g. "$350K", "33.8M"
    label: str              # short descriptor; e.g. "Total Revenue"
    delta: str | None = None


@dataclass
class KPIStrip:
    cards: list[KPICard]    # 2–5 side-by-side


# ── Callouts ─────────────────────────────────────────────────────────────────

CalloutVariant = Literal["insight", "next_steps", "warning", "note"]


@dataclass
class Callout:
    variant: CalloutVariant
    label: str              # displayed uppercase, e.g. "KEY INSIGHT"
    body: list[Paragraph]


# ── Charts ───────────────────────────────────────────────────────────────────

ChartKind = Literal[
    "bar", "column", "funnel", "line", "pie", "donut", "stacked", "other"
]


@dataclass
class Series:
    name: str
    values: list[float]


@dataclass
class Chart:
    kind: ChartKind
    title: str | None
    categories: list[str]
    series: list[Series]
    # Extraction metadata
    extraction_strategy: Literal["ocr", "adjacent_table", "claude_infer", "unknown"] = "unknown"
    extraction_confidence: float = 0.0


# ── Figures (non-chart images) ───────────────────────────────────────────────

@dataclass
class Figure:
    image_bytes: bytes
    image_format: Literal["png", "jpeg", "svg"] = "png"
    caption: str | None = None
    alt: str | None = None


# ── Top-level block ──────────────────────────────────────────────────────────

# ── PDF-specific layout blocks ───────────────────────────────────────────────

@dataclass
class SectionLabel:
    """Numbered section marker, e.g. "01 — OVERVIEW"."""
    text: str
    number: str | None = None   # "01" or None


@dataclass
class ActionCard:
    """Numbered recommendation card with a bold title and body."""
    number: str          # "1", "2", "🎯", etc.
    title: str
    body: str


@dataclass
class ComparisonPanel:
    """Two-column panel comparing positives vs. negatives."""
    left_title: str
    left_items: list[str]
    right_title: str
    right_items: list[str]


# ── Top-level block ──────────────────────────────────────────────────────────

BlockContent = Union[
    Heading, Paragraph, List, Table, KPIStrip, Callout, Chart, Figure,
    SectionLabel, ActionCard, ComparisonPanel,
]

BlockKind = Literal[
    "heading", "paragraph", "list",
    "table", "kpi_strip",
    "callout", "chart", "figure",
    "section_label", "action_card", "comparison_panel",
]


@dataclass
class Block:
    kind: BlockKind
    content: BlockContent
    # Provenance hints — preserved for debugging and sidecar JSON
    source_index: int = -1
    classification_source: Literal["rule", "claude", "unknown"] = "unknown"
    notes: list[str] = field(default_factory=list)


# ── Document ─────────────────────────────────────────────────────────────────

@dataclass
class Document:
    title: str
    client: str
    period: str
    blocks: list[Block] = field(default_factory=list)

    # Populated by the review/report step
    warnings: list[str] = field(default_factory=list)
    unclassified: list[dict] = field(default_factory=list)


# ── v0.5 orchestrator records ────────────────────────────────────────────────

@dataclass
class DSExtension:
    """Record of a design-system extension materialized by DS-Extender.

    Written by the orchestrator into state.json.extensions[] after QA pass.
    """
    name: str                              # slug, e.g. "timeline_row"
    content_hash: str                      # sha256:... keyed by block signature
    added_at: str                          # ISO date
    added_by_run: str                      # run_id that first staged it
    hex_tokens: dict[str, str] = field(default_factory=dict)      # TOKEN → #HEX
    text_styles: dict[str, dict] = field(default_factory=dict)    # name → style spec
    renderer_module: str = ""              # e.g. "dynamic.timeline_row"
    figma_node_id: str | None = None       # pushed via use_figma, nullable
    rationale: str = ""                    # ≤140 chars


@dataclass
class RetryRecord:
    """One QA retry attempt."""
    attempt: int
    stage_retried: str | None              # "render" | "classify" | "ds_extend" | "chart_extract"
    reason: str
    severity: Literal["high", "medium", "low"]
    affected_block_indices: list[int] = field(default_factory=list)


@dataclass
class StageCheckpoint:
    """Snapshot of stage progress — lets `--resume` skip completed work."""
    stage: str
    completed_at: str
    pending_count: int = 0
    resolved_count: int = 0


# ── Exceptions ───────────────────────────────────────────────────────────────

class PolishError(Exception):
    """Base for pipeline errors."""


class UnclassifiedContentError(PolishError):
    """Raised when a block cannot be confidently classified. Pipeline hard-fails."""

    def __init__(self, blocks: list[dict]):
        self.blocks = blocks
        super().__init__(
            f"{len(blocks)} block(s) could not be classified. "
            "See sidecar JSON for details."
        )


class ContentPreservationError(PolishError):
    """Raised when the verify step detects word-level content drift."""


class ChartExtractionError(PolishError):
    """Raised when all three chart-data extraction strategies fail."""


class HandoffProtocolError(PolishError):
    """Raised when a subagent reply violates the handoff schema.

    Orchestrator surfaces stderr verbatim and stops — never retry a protocol
    violation, since retrying a broken producer does not produce valid output.
    """
