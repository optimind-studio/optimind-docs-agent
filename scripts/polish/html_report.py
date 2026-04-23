"""Human-readable HTML report for every polish run.

The report renders alongside the output .docx and the classification.json
sidecar. Template lives at
``skills/polish/references/report-template.html`` so guideline and report
styling stay locked to the UI kit.

Data contract (keys the Jinja template consumes):

    title, client, period, run_id, started_at, duration_s
    degraded (bool), failed (bool)
    page_count, retries_total, block_counts (dict w/ .total), extensions
    block_breakdown: list of {kind, count, source}
    findings: list of {block_index, severity, issue, recommended_action, evidence}
    qa_runs: list of {attempt, passed, diagnosis}
    warnings: list[str]
    input_path, output_path, sidecar_path, figma_file_key
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError as e:  # pragma: no cover — requirements guarantee jinja2
    raise RuntimeError("jinja2 is required for polish report generation") from e


# Resolve the template folder at import so test harnesses can override.
_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "polish" / "references"
)


def render_report(context: dict, output_path: Path, template_dir: Path | None = None) -> Path:
    """Render the report template into `output_path`."""
    tmpl_dir = template_dir or _TEMPLATE_DIR
    env = Environment(
        loader=FileSystemLoader(str(tmpl_dir)),
        autoescape=select_autoescape(enabled_extensions=("html",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tmpl = env.get_template("report-template.html")
    html = tmpl.render(**context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    return output_path


# ── Context builder ─────────────────────────────────────────────────────────

def build_context(
    *,
    state: dict,
    blocks: list[dict],
    findings: list[dict],
    duration_s: float,
    input_path: Path,
    output_path: Path,
    sidecar_path: Path,
    figma_file_key: str | None = None,
) -> dict:
    """Assemble the template context from a state.json + blocks + findings."""
    counts: dict[str, int] = {}
    for b in blocks:
        k = b.get("kind", "unknown")
        counts[k] = counts.get(k, 0) + 1
    block_counts = {"total": len(blocks), **counts}

    # Block breakdown table
    breakdown = [
        {"kind": k, "count": v, "source": "canonical"}
        for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    ]

    # Retries total across all stages
    retries_total = sum(int(v) for v in (state.get("retry_counter") or {}).values())

    # Page count — best effort from block payloads
    from .sample import estimate_page_count
    page_count = estimate_page_count(blocks)

    return {
        "title": state.get("title", ""),
        "client": state.get("client", ""),
        "period": state.get("period", ""),
        "run_id": state.get("run_id", ""),
        "started_at": state.get("created_at", ""),
        "duration_s": round(duration_s, 2),
        "degraded": bool(state.get("degraded")),
        "failed": False,
        "page_count": page_count,
        "retries_total": retries_total,
        "block_counts": block_counts,
        "block_breakdown": breakdown,
        "extensions": state.get("extensions") or [],
        "findings": findings or [],
        "qa_runs": state.get("qa_runs") or [],
        "warnings": state.get("warnings") or [],
        "input_path": str(input_path),
        "output_path": str(output_path),
        "sidecar_path": str(sidecar_path),
        "figma_file_key": figma_file_key or "",
    }


def load_findings(state_dir: Path) -> list[dict]:
    """Load merged audit findings from `<state_dir>/audit/findings.json`."""
    p = state_dir / "audit" / "findings.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except Exception:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("findings") or [])
    return []
