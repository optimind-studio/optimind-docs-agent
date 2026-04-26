"""Polish stage-machine CLI (v0.5).

The `/polish` skill orchestrator in the user's Claude Code session invokes
this module one stage at a time:

    python -m polish --stage parse           --state-dir <dir>
    python -m polish --stage classify        --state-dir <dir>
    python -m polish --stage classify --resume --state-dir <dir>
    python -m polish --stage refine          --state-dir <dir>
    python -m polish --stage chart_extract   --state-dir <dir>
    python -m polish --stage chart_extract --resume --state-dir <dir>
    python -m polish --stage render          --state-dir <dir>
    python -m polish --stage verify          --state-dir <dir>
    python -m polish --stage promote         --state-dir <dir>
    python -m polish --stage report          --state-dir <dir>

Exit codes (see references/state-machine.md):

    0   stage complete
    10  pending items — orchestrator must resolve and re-invoke --resume
    20  soft failure — continue to QA for diagnosis
    2   hard failure — orchestrator surfaces stderr verbatim and stops

A supplementary ``init`` stage takes ``--input``, ``--title``, ``--client``,
``--period`` and creates a fresh state bundle. It prints the new run_id and
state_dir on stdout so the orchestrator (or Intake subagent) can pick them up.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path

from . import audit_parse as audit_parse_mod
from . import chart_extract as chart_mod
from . import classify as classify_mod
from . import flatten as flatten_mod
from . import handoff as handoff_mod
from . import html_report as html_mod
from . import normalize as normalize_mod
from . import reconstruct as reconstruct_mod
from . import refine as refine_mod
from . import report as report_mod
from . import sample as sample_mod
from . import state as state_mod
from . import tokenize_blocks
from . import verify as verify_mod
from .ingest import docx_reader, pdf_reader
from .model import Block, Document, PolishError
from .render import docx_writer


# ── Top-level entry ─────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.stage == "init":
        return _stage_init(args)

    state_dir = Path(args.state_dir).expanduser().resolve()
    if not state_dir.exists():
        _hard_fail(f"state_dir not found: {state_dir}")
        return 2

    try:
        return _dispatch_stage(args.stage, state_dir, resume=bool(args.resume))
    except PolishError as e:
        _hard_fail(f"{type(e).__name__}: {e}")
        return 2
    except Exception as e:  # noqa: BLE001 — last line of defence
        _hard_fail(f"unhandled {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return 2


def _dispatch_stage(stage: str, state_dir: Path, *, resume: bool) -> int:
    if stage == "parse":
        return _stage_parse(state_dir)
    if stage == "audit_parse":
        return _stage_audit_parse(state_dir)
    if stage == "classify":
        return _stage_classify(state_dir, resume=resume)
    if stage == "refine":
        return _stage_refine(state_dir)
    if stage == "chart_extract":
        return _stage_chart_extract(state_dir, resume=resume)
    if stage == "ds_extend":
        return _stage_ds_extend(state_dir, resume=resume)
    if stage == "render":
        return _stage_render(state_dir)
    if stage == "verify":
        return _stage_verify(state_dir)
    if stage == "promote":
        return _stage_promote(state_dir)
    if stage == "report":
        return _stage_report(state_dir)
    _hard_fail(f"unknown stage: {stage!r}")
    return 2


# ── Arg parsing ─────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="polish", description="Optimind Docs polisher — stage machine")
    p.add_argument("--stage", required=True, choices=(
        "init", "parse", "audit_parse", "classify", "refine", "chart_extract",
        "ds_extend", "render", "verify", "promote", "report",
    ))
    p.add_argument("--state-dir", default=None, help="State bundle dir (required for every stage except init)")
    p.add_argument("--resume", action="store_true", help="Load resolutions from disk before re-running")
    # init-only
    p.add_argument("--input", default=None)
    p.add_argument("--title", default="")
    p.add_argument("--client", default="")
    p.add_argument("--period", default="")
    p.add_argument("--mode", choices=("single", "batch"), default="single")
    p.add_argument("--run-id", default=None)
    return p.parse_args(argv)


# ── init ────────────────────────────────────────────────────────────────────

def _stage_init(args: argparse.Namespace) -> int:
    if not args.input:
        _hard_fail("init stage requires --input")
        return 2
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        _hard_fail(f"input not found: {input_path}")
        return 2
    suffix = input_path.suffix.lower().lstrip(".")
    if suffix not in ("docx", "pdf"):
        _hard_fail(f"unsupported input extension: {suffix!r}")
        return 2

    state_dir = state_mod.new_run_dir(args.run_id)
    from datetime import date
    output_basename = f"{input_path.stem}-polished-{date.today().isoformat()}"
    state_mod.init_state(
        state_dir,
        input_path=input_path,
        title=args.title or input_path.stem,
        client=args.client,
        period=args.period,
        fmt=suffix,
        output_basename=output_basename,
        mode=args.mode,
    )
    print(json.dumps({
        "run_id": state_dir.name,
        "state_dir": str(state_dir),
        "input_path": str(input_path),
        "output_basename": output_basename,
    }, indent=2))
    return 0


# ── parse ───────────────────────────────────────────────────────────────────

def _stage_parse(state_dir: Path) -> int:
    st = state_mod.load_state(state_dir)
    input_path = Path(st["input_path"])
    fmt = st["format"]

    if fmt == "docx":
        tokens = list(docx_reader.read(input_path))
    elif fmt == "pdf":
        tokens = list(pdf_reader.read(input_path))
    else:
        _hard_fail(f"unknown format: {fmt!r}")
        return 2

    tokens = list(flatten_mod.flatten(tokens))
    tokens, normalize_warnings = normalize_mod.normalize(tokens)
    tokens, reconstruct_warnings = reconstruct_mod.reconstruct(tokens)
    primitives = list(tokenize_blocks.build_blocks(tokens))

    # Stash primitives on disk so later stages can resume from them.
    (_parse_out(state_dir)).write_bytes(pickle.dumps(primitives))

    warnings = list(normalize_warnings) + list(reconstruct_warnings)
    for w in warnings:
        state_mod.add_warning(state_dir, w)
    state_mod.advance_stage(state_dir, "parse_complete")
    return 0


# ── audit_parse ─────────────────────────────────────────────────────────────

def _stage_audit_parse(state_dir: Path) -> int:
    st = state_mod.load_state(state_dir)
    input_path = Path(st["input_path"])
    manifest_path = audit_parse_mod.produce_manifest(input_path, state_dir)
    state_mod.advance_stage(state_dir, "audit_parse_complete")
    print(json.dumps({"stage": "audit_parse_complete", "manifest": str(manifest_path)}))
    return 0


def _parse_out(state_dir: Path) -> Path:
    return state_dir / "primitives.pkl"


# ── classify ────────────────────────────────────────────────────────────────

def _stage_classify(state_dir: Path, *, resume: bool) -> int:
    st = state_mod.load_state(state_dir)

    if resume:
        blocks = _load_blocks_from_disk(state_dir)
        resolutions = handoff_mod.load_resolutions(state_dir, "classify")
        blocks = classify_mod.apply_resolutions(blocks, resolutions)
        _persist_blocks(state_dir, blocks)
        # Check if any pending remain unresolved (rare — if an agent chose
        # kind="unknown" with low confidence, drop the pending entry).
        remaining = _remaining_pending(state_dir, "classify", resolutions)
        for p in remaining:
            pass  # still pending — we'll re-emit a handoff below
        if remaining:
            handoff_mod.emit_handoff(
                "classify", st["run_id"], remaining, state_dir
            )
            return 10
        _clear_pending(state_dir, "classify")
        state_mod.advance_stage(state_dir, "classify_complete")
        return 0

    # Fresh classify
    primitives_path = _parse_out(state_dir)
    if not primitives_path.exists():
        _hard_fail("classify: primitives.pkl missing — run --stage parse first")
        return 2
    primitives = pickle.loads(primitives_path.read_bytes())

    blocks, pending, warnings = classify_mod.classify(primitives)
    _persist_blocks(state_dir, blocks)
    for w in warnings:
        state_mod.add_warning(state_dir, w)

    pending_paths: list[Path] = []
    for item in pending:
        idx = item.get("block_index", -1)
        if idx < 0:
            continue
        payload = {
            "text": item["payload"].get("text", ""),
            "runs": item["payload"].get("runs", []),
            "shading_hex": item["payload"].get("shading_hex"),
            "heading_level_hint": item["payload"].get("heading_level_hint"),
            "rule_suggestion": item.get("rule_suggestion"),
            "reason": item.get("reason"),
            "neighbors_before": item.get("neighbors_before", []),
            "neighbors_after": item.get("neighbors_after", []),
        }
        p = handoff_mod.write_pending(state_dir, "classify", idx, payload)
        pending_paths.append(p)

    if pending_paths:
        handoff_mod.emit_handoff("classify", st["run_id"], pending_paths, state_dir)
        return 10

    state_mod.advance_stage(state_dir, "classify_complete")
    return 0


# ── refine ──────────────────────────────────────────────────────────────────

def _stage_refine(state_dir: Path) -> int:
    st = state_mod.load_state(state_dir)
    blocks = _load_blocks_from_disk(state_dir)
    blocks, warnings = refine_mod.refine(
        blocks,
        title=st.get("title", ""),
        client=st.get("client", ""),
        period=st.get("period", ""),
    )
    _persist_blocks(state_dir, blocks)
    for w in warnings:
        state_mod.add_warning(state_dir, w)
    state_mod.advance_stage(state_dir, "refine_complete")
    return 0


# ── chart_extract ───────────────────────────────────────────────────────────

def _stage_chart_extract(state_dir: Path, *, resume: bool) -> int:
    st = state_mod.load_state(state_dir)

    if resume:
        blocks = _load_blocks_from_disk(state_dir)
        resolutions = handoff_mod.load_resolutions(state_dir, "chart_infer")
        blocks = chart_mod.apply_resolutions(blocks, resolutions)
        _persist_blocks(state_dir, blocks)
        remaining = _remaining_pending(state_dir, "chart_infer", resolutions)
        if remaining:
            handoff_mod.emit_handoff("chart_infer", st["run_id"], remaining, state_dir)
            return 10
        _clear_pending(state_dir, "chart_infer")
        state_mod.advance_stage(state_dir, "chart_extract_complete")
        return 0

    blocks = _load_blocks_from_disk(state_dir)
    blocks, pending, warnings = chart_mod.extract_all(blocks)
    _persist_blocks(state_dir, blocks)
    for w in warnings:
        state_mod.add_warning(state_dir, w)

    pending_paths: list[Path] = []
    for item in pending:
        idx = item.get("block_index", -1)
        if idx < 0:
            continue
        payload = {
            "nearby_narrative": item["payload"].get("nearby_narrative", ""),
            "image_size_bytes": item["payload"].get("image_size_bytes"),
            "rule_suggestion": item.get("rule_suggestion"),
            "rule_confidence": item.get("rule_confidence"),
            "reason": item.get("reason"),
        }
        p = handoff_mod.write_pending(state_dir, "chart_infer", idx, payload)
        pending_paths.append(p)

    if pending_paths:
        # chart-inference is a soft requirement — figures survive as fallback.
        # We still emit a handoff, but the orchestrator may choose to skip it
        # when the retry budget is exhausted.
        handoff_mod.emit_handoff("chart_infer", st["run_id"], pending_paths, state_dir)
        return 10

    state_mod.advance_stage(state_dir, "chart_extract_complete")
    return 0


# ── ds_extend ───────────────────────────────────────────────────────────────
#
# ds_extend is entirely orchestrator-driven — the subagent writes resolutions
# and staged artefacts directly; Python only verifies the staged files exist
# and advances the stage. Resume is the normal path.

def _stage_ds_extend(state_dir: Path, *, resume: bool) -> int:
    resolutions = handoff_mod.load_resolutions(state_dir, "ds_extend")
    # Verify each extension's staged artefacts exist before advancing.
    staged_root = state_mod.staged_dir(state_dir)
    for idx, res in resolutions.items():
        ext = res.get("extension") or res
        renderer_mod = ext.get("renderer_module") or ""
        kind = renderer_mod.split(".")[-1] if renderer_mod else ""
        if kind and not (staged_root / "dynamic" / f"{kind}.py").exists():
            state_mod.add_warning(
                state_dir,
                f"ds_extend: extension {idx} missing staged dynamic/{kind}.py"
            )
    state_mod.advance_stage(state_dir, "ds_extend_complete")
    return 0


# ── render ──────────────────────────────────────────────────────────────────

def _stage_render(state_dir: Path) -> int:
    st = state_mod.load_state(state_dir)
    blocks = _load_blocks_from_disk(state_dir)
    doc = Document(
        title=st["title"], client=st["client"], period=st["period"],
        blocks=blocks, warnings=list(st.get("warnings") or []),
    )
    out_path = state_mod.output_dir(state_dir) / f"{st['output_basename']}.docx"
    docx_writer.write(doc, out_path)

    # Write the sample index used by the Auditor now — blocks are final.
    block_dicts = _blocks_to_dicts(blocks)
    page_count = sample_mod.estimate_page_count(block_dicts)
    indices = sample_mod.select_sample(block_dicts, page_count=page_count)
    sample_mod.save_sample(state_dir, indices)

    state_mod.advance_stage(state_dir, "render_complete")
    return 0


# ── verify ──────────────────────────────────────────────────────────────────

def _stage_verify(state_dir: Path) -> int:
    st = state_mod.load_state(state_dir)
    blocks = _load_blocks_from_disk(state_dir)
    doc = Document(
        title=st["title"], client=st["client"], period=st["period"],
        blocks=blocks, warnings=list(st.get("warnings") or []),
    )
    out_path = state_mod.output_dir(state_dir) / f"{st['output_basename']}.docx"
    diagnosis = verify_mod.verify(out_path, doc)

    # Stash QA diagnosis for Renderer-QA to consume.
    qa_file = state_mod.qa_dir(state_dir) / f"verify-{len(st.get('qa_runs') or []) + 1}.json"
    qa_file.parent.mkdir(parents=True, exist_ok=True)
    qa_file.write_text(json.dumps(diagnosis, indent=2, default=str))

    for w in diagnosis.get("warnings") or []:
        state_mod.add_warning(state_dir, w)

    if diagnosis.get("hard_fail"):
        _hard_fail(f"verify: {diagnosis.get('reason')}")
        return 2
    if not diagnosis.get("passed"):
        # Soft failure — orchestrator consults Renderer-QA to decide retry.
        return 20
    return 0


# ── promote ─────────────────────────────────────────────────────────────────

def _stage_promote(state_dir: Path) -> int:
    """Atomically promote staged DS extensions into the committed tree.

    Promotion rules (belt-and-braces — DS-Extender already staged):

        staged/tokens_extensions.json  →  render/tokens_extensions.json (merged)
        staged/dynamic/<kind>.py       →  render/dynamic/<kind>.py
        staged/ui-kit.md.patch         →  applied to references/ui-kit.md

    Conflict handling: if a promotion would overwrite an existing file with
    different content, we log a warning and skip — the committed file wins.
    """
    st = state_mod.load_state(state_dir)
    staged = state_mod.staged_dir(state_dir)
    if not staged.exists():
        state_mod.advance_stage(state_dir, "promoted")
        return 0

    render_dir = Path(__file__).resolve().parent / "render"
    dynamic_dst = render_dir / "dynamic"
    dynamic_dst.mkdir(parents=True, exist_ok=True)

    # Merge tokens_extensions.json
    staged_tokens = staged / "tokens_extensions.json"
    dst_tokens = render_dir / "tokens_extensions.json"
    if staged_tokens.exists():
        try:
            staged_data = json.loads(staged_tokens.read_text())
            dst_data = json.loads(dst_tokens.read_text()) if dst_tokens.exists() else {
                "hex_tokens": {}, "text_styles": {}
            }
            dst_data.setdefault("hex_tokens", {}).update(staged_data.get("hex_tokens") or {})
            dst_data.setdefault("text_styles", {}).update(staged_data.get("text_styles") or {})
            dst_tokens.write_text(json.dumps(dst_data, indent=2))
        except Exception as e:
            state_mod.add_warning(state_dir, f"promote: tokens merge failed: {e}")

    # Copy staged dynamic renderers (refuse to overwrite existing files).
    staged_dynamic = staged / "dynamic"
    if staged_dynamic.exists():
        for py in staged_dynamic.glob("*.py"):
            dst = dynamic_dst / py.name
            if dst.exists() and dst.read_text() != py.read_text():
                state_mod.add_warning(
                    state_dir, f"promote: refusing to overwrite {dst} (content differs)"
                )
                continue
            dst.write_text(py.read_text())

    # Record extensions on state.json
    resolutions = handoff_mod.load_resolutions(state_dir, "ds_extend")
    for res in resolutions.values():
        ext = res.get("extension") or res
        state_mod.append_extension(state_dir, ext)

    state_mod.advance_stage(state_dir, "promoted")
    return 0


# ── report ──────────────────────────────────────────────────────────────────

def _stage_report(state_dir: Path) -> int:
    st = state_mod.load_state(state_dir)
    blocks = _load_blocks_from_disk(state_dir)
    doc = Document(
        title=st["title"], client=st["client"], period=st["period"],
        blocks=blocks, warnings=list(st.get("warnings") or []),
    )
    out_path = state_mod.output_dir(state_dir) / f"{st['output_basename']}.docx"
    sidecar = report_mod.write_sidecar(doc, out_path)

    findings = html_mod.load_findings(state_dir)
    duration = _compute_duration(st)
    report_path = report_mod.write_html_report(
        state=st,
        blocks=_blocks_to_dicts(blocks),
        findings=findings,
        duration_s=duration,
        input_path=Path(st["input_path"]),
        output_path=out_path,
        sidecar_path=sidecar,
        figma_file_key="iYE9CtCoxRESvSGtTrfBhs",
    )

    # Copy artefacts to the final output folder so the user can find them.
    final_dir = state_mod.output_root()
    final_dir.mkdir(parents=True, exist_ok=True)
    final_docx = final_dir / out_path.name
    final_json = final_dir / sidecar.name
    final_html = final_dir / report_path.name
    final_docx.write_bytes(out_path.read_bytes())
    final_json.write_text(sidecar.read_text())
    final_html.write_text(report_path.read_text())

    state_mod.advance_stage(state_dir, "reported")

    print(json.dumps({
        "stage": "reported",
        "run_id": st["run_id"],
        "output_docx": str(final_docx),
        "sidecar": str(final_json),
        "report_html": str(final_html),
        "degraded": bool(st.get("degraded")),
        "block_counts": report_mod._counts(doc),
        "warnings_count": len(st.get("warnings") or []),
    }, indent=2))
    return 0


# ── helpers ─────────────────────────────────────────────────────────────────

def _persist_blocks(state_dir: Path, blocks: list[Block]) -> None:
    """Write every block as one JSON file per index.

    Blocks contain non-JSON values (bytes, dataclasses) — we use the state
    module's default JSON encoder to normalize before writing. Figures keep
    a byte-reference marker; the raw bytes live in a sibling pickle so later
    stages can rehydrate them. This pattern keeps each per-block file small
    enough for subagent context budgets.
    """
    # Clear existing block files first so deletions (refine drops) persist.
    d = state_mod.blocks_dir(state_dir)
    d.mkdir(parents=True, exist_ok=True)
    for p in d.glob("*.json"):
        p.unlink()

    # Bytes payload stored alongside the state dir (not under blocks/ so it
    # doesn't pollute Auditor file listings).
    blobs: dict[int, bytes] = {}
    for i, b in enumerate(blocks):
        payload = _block_to_dict(b)
        if b.kind == "figure" and getattr(b.content, "image_bytes", None):
            blobs[i] = b.content.image_bytes
            payload["content"]["image_bytes"] = f"<blob:{i}>"
        state_mod.write_block_file(state_dir, i, payload)

    (state_dir / "figure_blobs.pkl").write_bytes(pickle.dumps(blobs))


def _load_blocks_from_disk(state_dir: Path) -> list[Block]:
    """Rehydrate canonical Block instances from blocks/<index>.json + blobs."""
    from .model import (
        ActionCard, Block, Callout, Chart, ComparisonPanel, Figure, Heading,
        KPICard, KPIStrip, List as ListBlock, ListItem, MergeSpec, Paragraph,
        Run, SectionLabel, Series, Table,
    )

    blobs: dict[int, bytes] = {}
    blobs_path = state_dir / "figure_blobs.pkl"
    if blobs_path.exists():
        try:
            blobs = pickle.loads(blobs_path.read_bytes())
        except Exception:
            blobs = {}

    out: list[Block] = []
    for idx, raw in state_mod.iter_block_files(state_dir):
        data = json.loads(raw.read_text())
        kind = data["kind"]
        c = data.get("content") or {}
        if kind == "heading":
            content = Heading(level=c.get("level", 1), text=c.get("text", ""))
        elif kind == "paragraph":
            content = Paragraph(runs=[_run_from_dict(r) for r in c.get("runs") or []])
        elif kind == "list":
            content = ListBlock(items=[
                ListItem(
                    runs=[_run_from_dict(r) for r in it.get("runs") or []],
                    level=it.get("level", 0),
                    ordered=it.get("ordered", False),
                ) for it in c.get("items") or []
            ])
        elif kind == "callout":
            content = Callout(
                variant=c.get("variant", "note"),
                label=c.get("label", ""),
                body=[Paragraph(runs=[_run_from_dict(r) for r in (p.get("runs") or [])])
                      for p in c.get("body") or []],
            )
        elif kind == "table":
            content = Table(
                headers=list(c.get("headers") or []),
                rows=list(c.get("rows") or []),
                variant=c.get("variant", "classic"),
                merges=[MergeSpec(**m) for m in (c.get("merges") or [])],
                caption=c.get("caption"),
            )
        elif kind == "kpi_strip":
            content = KPIStrip(cards=[
                KPICard(value=k.get("value", ""), label=k.get("label", ""),
                        delta=k.get("delta"))
                for k in (c.get("cards") or [])
            ])
        elif kind == "chart":
            content = Chart(
                kind=c.get("kind", "column"),
                title=c.get("title"),
                categories=list(c.get("categories") or []),
                series=[Series(name=s.get("name", ""),
                               values=[float(v) for v in (s.get("values") or [])])
                        for s in (c.get("series") or [])],
                extraction_strategy=c.get("extraction_strategy", "unknown"),
                extraction_confidence=float(c.get("extraction_confidence") or 0.0),
            )
        elif kind == "figure":
            img = blobs.get(idx) or b""
            content = Figure(
                image_bytes=img,
                image_format=c.get("image_format", "png"),
                caption=c.get("caption"),
                alt=c.get("alt"),
            )
        elif kind == "section_label":
            content = SectionLabel(
                text=c.get("text", ""),
                number=c.get("number"),
            )
        elif kind == "action_card":
            content = ActionCard(
                number=c.get("number", ""),
                title=c.get("title", ""),
                body=c.get("body", ""),
            )
        elif kind == "comparison_panel":
            content = ComparisonPanel(
                left_title=c.get("left_title", ""),
                left_items=list(c.get("left_items") or []),
                right_title=c.get("right_title", ""),
                right_items=list(c.get("right_items") or []),
            )
        else:
            # Unknown → treat as paragraph fallback.
            content = Paragraph(runs=[Run(text=c.get("text", ""))])
            kind = "paragraph"

        out.append(Block(
            kind=kind,
            content=content,
            source_index=data.get("source_index", -1),
            classification_source=data.get("classification_source", "unknown"),
            notes=list(data.get("notes") or []),
        ))
    return out


def _run_from_dict(r: dict):
    from .model import Run
    return Run(text=r.get("text", ""), bold=bool(r.get("bold")), italic=bool(r.get("italic")))


def _block_to_dict(b: Block) -> dict:
    d = {
        "kind": b.kind,
        "source_index": b.source_index,
        "classification_source": b.classification_source,
        "notes": list(b.notes),
        "content": asdict(b.content),
    }
    # Figures carry bytes — serialize as marker; caller stores blobs separately.
    if b.kind == "figure":
        d["content"]["image_bytes"] = f"<blob>"
    return d


def _blocks_to_dicts(blocks: list[Block]) -> list[dict]:
    return [_block_to_dict(b) for b in blocks]


def _remaining_pending(state_dir: Path, kind: str, resolutions: dict[int, dict]) -> list[Path]:
    """Return pending file paths that still have no valid resolution."""
    d = state_mod.pending_dir(state_dir, kind)
    if not d.exists():
        return []
    out: list[Path] = []
    for p in sorted(d.glob("*.json")):
        try:
            idx = int(p.stem)
        except ValueError:
            continue
        if idx not in resolutions:
            out.append(p)
    return out


def _clear_pending(state_dir: Path, kind: str) -> None:
    d = state_mod.pending_dir(state_dir, kind)
    if not d.exists():
        return
    for p in d.glob("*.json"):
        p.unlink()


def _compute_duration(state: dict) -> float:
    try:
        from datetime import datetime
        start = datetime.strptime(state["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        now = datetime.strptime(state["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
        return (now - start).total_seconds()
    except Exception:
        return 0.0


def _hard_fail(msg: str) -> None:
    print(json.dumps({"error": "hard_fail", "message": msg}), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
