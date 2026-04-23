"""Handoff protocol — Python ↔ skill orchestrator.

When Python encounters a block it cannot resolve with rules, it writes the
block payload (plus neighbor context) to ``pending/<kind>/<index>.json`` and
emits a single ``<<HANDOFF>>`` sentinel on stderr followed by one JSON line
describing what the orchestrator should dispatch.

Exit codes (see state-machine.md for canonical table):
  0   stage done
  10  pending items emitted — orchestrator must resolve and re-invoke --resume
  20  soft failure (QA must diagnose) — pipeline continues
  2   hard failure / protocol violation — orchestrator surfaces stderr and stops

Resolution files live at ``resolutions/<kind>/<index>.json`` and carry a
single entry from the agent's ``resolutions[]`` array (or an ``extension``
object for DS-Extender). Python validates each resolution on load and skips
malformed ones so a single bad reply cannot corrupt the run.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from . import state as state_mod
from .model import HandoffProtocolError

HANDOFF_SENTINEL = "<<HANDOFF>>"

VALID_KINDS = ("classify", "chart_infer", "ds_extend")
VALID_BLOCK_KINDS = (
    "heading", "paragraph", "list", "table", "kpi_strip",
    "callout", "figure", "chart", "unknown",
)
VALID_CHART_KINDS = ("bar", "column", "line", "pie", "donut", "funnel", "stacked", "other")


# ── Content hashing (shared cache key) ──────────────────────────────────────

def content_hash(payload: dict) -> str:
    """Stable SHA-256 of the block payload's "signature" fields.

    Two blocks with the same signature share a cache entry, so re-running a
    near-identical doc reuses prior agent decisions at zero cost.
    """
    sig = {
        "shading_hex": payload.get("shading_hex"),
        "first_word": (payload.get("text") or "").split()[:1],
        "length_bucket": _length_bucket(payload.get("text") or ""),
        "kind_hint": payload.get("kind_hint"),
        "runs_digest": _runs_digest(payload.get("runs") or []),
    }
    s = json.dumps(sig, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()


def _length_bucket(text: str) -> str:
    n = len(text or "")
    if n == 0:
        return "empty"
    if n <= 30:
        return "short"
    if n <= 140:
        return "medium"
    return "long"


def _runs_digest(runs: list[dict]) -> str:
    parts = []
    for r in runs[:6]:
        parts.append(f"{bool(r.get('bold'))}:{bool(r.get('italic'))}:{_length_bucket(r.get('text') or '')}")
    return "|".join(parts)


# ── Pending queue ───────────────────────────────────────────────────────────

def write_pending(state_dir: Path, kind: str, index: int, payload: dict) -> Path:
    """Record one pending item. Returns the written path."""
    if kind not in VALID_KINDS:
        raise HandoffProtocolError(f"unknown pending kind: {kind!r}")
    d = state_mod.pending_dir(state_dir, kind)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{index:05d}.json"
    payload = {**payload, "content_hash": payload.get("content_hash") or content_hash(payload)}
    p.write_text(json.dumps(payload, indent=2, default=str))
    return p


def signature_groups(state_dir: Path, kind: str) -> dict[str, list[int]]:
    """Group pending block indices by their shape signature.

    The orchestrator batches one agent invocation per group so ~50 ambiguous
    blocks collapse to ~8 agent calls. DS-Extender does not batch (each
    unknown signature is one component).
    """
    d = state_mod.pending_dir(state_dir, kind)
    groups: dict[str, list[int]] = {}
    if not d.exists():
        return groups
    for p in sorted(d.glob("*.json")):
        try:
            idx = int(p.stem)
            payload = json.loads(p.read_text())
        except Exception:
            continue
        sig = _signature_key(payload)
        groups.setdefault(sig, []).append(idx)
    return groups


def _signature_key(payload: dict) -> str:
    """Human-readable batch signature (also used as the agent's
    ``batch_signature`` payload field)."""
    text = (payload.get("text") or "").strip()
    first = text.split()[:1]
    return (
        f"shading={payload.get('shading_hex') or 'none'}"
        f"|first_word={(first[0].upper() if first else '-')}"
        f"|length_bucket={_length_bucket(text)}"
    )


# ── Sentinel emission ───────────────────────────────────────────────────────

def emit_handoff(
    kind: str,
    run_id: str,
    pending_paths: list[Path],
    state_dir: Path,
) -> None:
    """Print the handoff sentinel + JSON to stderr.

    The skill captures the last two non-empty stderr lines to parse this.
    """
    if kind not in VALID_KINDS:
        raise HandoffProtocolError(f"unknown handoff kind: {kind!r}")
    sigs = signature_groups(state_dir, kind) if kind in ("classify", "chart_infer") else {}
    payload = {
        "stage": kind,
        "run_id": run_id,
        "pending": [str(p) for p in pending_paths],
        "resume_with": [f"resolutions/{kind}/"],
        "signature_groups": sigs,
    }
    print(HANDOFF_SENTINEL, file=sys.stderr)
    print(json.dumps(payload, default=str), file=sys.stderr)


# ── Resolution load + validation ────────────────────────────────────────────

def load_resolutions(state_dir: Path, kind: str) -> dict[int, dict]:
    """Load every resolution for `kind`, dropping malformed entries.

    Returns {block_index: validated_resolution_payload}. Malformed entries
    are skipped with a warning in state.json; the pending item survives so
    the stage re-emits it on the next --resume cycle.
    """
    out: dict[int, dict] = {}
    skipped: list[tuple[int, str]] = []
    for idx, raw in state_mod.iter_resolutions(state_dir, kind):
        ok, reason = validate_resolution(kind, raw)
        if not ok:
            skipped.append((idx, reason))
            continue
        out[idx] = raw
    if skipped:
        for idx, reason in skipped:
            state_mod.add_warning(
                state_dir,
                f"handoff: resolutions/{kind}/{idx:05d}.json rejected — {reason}",
            )
    return out


def validate_resolution(kind: str, payload: dict) -> tuple[bool, str]:
    """Return (ok, reason). `reason` is empty when ok=True."""
    if not isinstance(payload, dict):
        return False, "not a JSON object"

    if kind == "classify":
        bk = payload.get("kind")
        if bk not in VALID_BLOCK_KINDS:
            return False, f"kind must be one of {VALID_BLOCK_KINDS}"
        conf = payload.get("confidence")
        if conf is not None:
            try:
                conf = float(conf)
            except Exception:
                return False, "confidence must be numeric"
            if not 0.0 <= conf <= 1.0:
                return False, "confidence out of range"
        if bk == "heading":
            lv = payload.get("level")
            if lv not in (1, 2, 3):
                return False, "heading level must be 1-3"
        if bk == "callout":
            variant = payload.get("variant")
            if variant not in ("insight", "next_steps", "warning", "note"):
                return False, "unknown callout variant"
        return True, ""

    if kind == "chart_infer":
        ck = payload.get("kind")
        if ck not in VALID_CHART_KINDS:
            return False, f"chart kind must be one of {VALID_CHART_KINDS}"
        cats = payload.get("categories")
        series = payload.get("series")
        if not isinstance(cats, list) or not cats:
            return False, "categories must be a non-empty list"
        if not isinstance(series, list) or not series:
            return False, "series must be a non-empty list"
        for s in series:
            if not isinstance(s, dict):
                return False, "each series must be an object"
            vals = s.get("values")
            if not isinstance(vals, list):
                return False, "series.values must be a list"
        return True, ""

    if kind == "ds_extend":
        ext = payload.get("extension") or payload
        name = ext.get("name")
        if not name or not isinstance(name, str):
            return False, "extension.name missing"
        if not isinstance(ext.get("hex_tokens") or {}, dict):
            return False, "extension.hex_tokens must be an object"
        if not isinstance(ext.get("renderer_module") or "", str):
            return False, "extension.renderer_module must be a string"
        return True, ""

    return False, f"unknown kind: {kind!r}"


# ── Cache helpers ───────────────────────────────────────────────────────────

def cache_get(state_dir: Path, key: str) -> dict | None:
    """Return cached resolution for `key` or None."""
    p = state_mod.cache_dir(state_dir) / f"{_sanitize_hash(key)}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def cache_put(state_dir: Path, key: str, payload: dict) -> None:
    d = state_mod.cache_dir(state_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{_sanitize_hash(key)}.json").write_text(json.dumps(payload, default=str))


def _sanitize_hash(key: str) -> str:
    """Turn 'sha256:abcd…' into a filesystem-safe token."""
    return key.replace(":", "_").replace("/", "_")[:96]
