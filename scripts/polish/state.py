"""Durable state bundle for the v0.5 stage machine.

Every stage of the polish pipeline reads/writes a `state.json` and a set of
sibling directories under `<state_dir>` (typically
`~/OptimindDocs/.polish-state/<run_id>/`). The skill orchestrates stage
invocations; Python writes pending items to disk, prints a handoff sentinel,
exits code 10, and resumes when the orchestrator has written resolutions.

The bundle is designed so any stage can be re-run from a clean checkout of
`state_dir` — nothing lives in process memory.

Layout (mirrors references/handoff-protocol.md):

    state_dir/
      state.json
      blocks/<index>.json              one canonical Block per file
      pending/{classify,chart_infer,ds_extend}/<index>.json
      resolutions/{classify,chart_infer,ds_extend}/<index>.json
      staged/{tokens_extensions.json, ui-kit.md.patch, dynamic/<kind>.py}
      audit/{sample_indices.json, findings.json}
      qa/verify-<attempt>.json
      cache/<content-hash>.json
      output/<basename>.docx

Schema version 1.0. Any forward-incompatible change must bump
STATE_SCHEMA_VERSION and add a migration.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

STATE_SCHEMA_VERSION = "1.0"

STAGES: tuple[str, ...] = (
    "intake_complete",
    "parse_complete",
    "classify_complete",
    "refine_complete",
    "chart_extract_complete",
    "ds_extend_complete",
    "render_complete",
    "audit_complete",
    "qa_complete",
    "promoted",
    "reported",
)

RETRYABLE_STAGES: tuple[str, ...] = ("classify", "chart_extract", "ds_extend", "render")


# ── Path helpers ────────────────────────────────────────────────────────────

def default_root() -> Path:
    """Root directory that holds all per-run state bundles.

    Can be overridden with ``OPTIMIND_POLISH_STATE_ROOT`` for tests or
    multi-user hosts.
    """
    override = os.environ.get("OPTIMIND_POLISH_STATE_ROOT")
    if override:
        return Path(override).expanduser()
    return Path.home() / "OptimindDocs" / ".polish-state"


def output_root() -> Path:
    override = os.environ.get("OPTIMIND_POLISH_OUTPUT_ROOT")
    if override:
        return Path(override).expanduser()
    return Path.home() / "OptimindDocs" / "output"


def new_run_dir(run_id: str | None = None) -> Path:
    """Allocate a fresh state-dir under the state root."""
    rid = run_id or uuid.uuid4().hex[:12]
    d = default_root() / rid
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Paths inside a state_dir ────────────────────────────────────────────────

def blocks_dir(state_dir: Path) -> Path:
    return state_dir / "blocks"


def pending_dir(state_dir: Path, kind: str) -> Path:
    return state_dir / "pending" / kind


def resolutions_dir(state_dir: Path, kind: str) -> Path:
    return state_dir / "resolutions" / kind


def staged_dir(state_dir: Path) -> Path:
    return state_dir / "staged"


def audit_dir(state_dir: Path) -> Path:
    return state_dir / "audit"


def qa_dir(state_dir: Path) -> Path:
    return state_dir / "qa"


def cache_dir(state_dir: Path) -> Path:
    return state_dir / "cache"


def output_dir(state_dir: Path) -> Path:
    return state_dir / "output"


def state_path(state_dir: Path) -> Path:
    return state_dir / "state.json"


# ── State.json load/save ────────────────────────────────────────────────────

def init_state(
    state_dir: Path,
    *,
    input_path: Path,
    title: str,
    client: str,
    period: str,
    fmt: str,
    output_basename: str,
    mode: str = "single",
    run_id: str | None = None,
) -> dict:
    """Create state.json for a fresh run."""
    state_dir.mkdir(parents=True, exist_ok=True)
    st: dict[str, Any] = {
        "schema_version": STATE_SCHEMA_VERSION,
        "run_id": run_id or state_dir.name,
        "mode": mode,
        "input_path": str(input_path),
        "format": fmt,
        "title": title,
        "client": client,
        "period": period,
        "output_basename": output_basename,
        "stage": "intake_complete",
        "retry_counter": {s: 0 for s in RETRYABLE_STAGES},
        "qa_runs": [],
        "extensions": [],
        "warnings": [],
        "degraded": False,
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
    }
    save_state(state_dir, st)
    for sub in (
        blocks_dir(state_dir),
        staged_dir(state_dir) / "dynamic",
        audit_dir(state_dir),
        qa_dir(state_dir),
        cache_dir(state_dir),
        output_dir(state_dir),
    ):
        sub.mkdir(parents=True, exist_ok=True)
    return st


def load_state(state_dir: Path) -> dict:
    p = state_path(state_dir)
    if not p.exists():
        raise FileNotFoundError(f"state.json missing at {p}")
    data = json.loads(p.read_text())
    if data.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(
            f"state.json schema_version {data.get('schema_version')!r} "
            f"does not match required {STATE_SCHEMA_VERSION!r}. "
            f"Delete {state_dir} and re-run to regenerate."
        )
    return data


def save_state(state_dir: Path, state: dict) -> None:
    """Atomically write state.json to avoid half-written files on crash."""
    state = {**state, "updated_at": _iso_now()}
    p = state_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, default=str)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def advance_stage(state_dir: Path, new_stage: str) -> dict:
    st = load_state(state_dir)
    st["stage"] = new_stage
    save_state(state_dir, st)
    return st


def add_warning(state_dir: Path, msg: str) -> None:
    st = load_state(state_dir)
    st.setdefault("warnings", []).append(msg)
    save_state(state_dir, st)


def set_degraded(state_dir: Path, reason: str) -> None:
    st = load_state(state_dir)
    st["degraded"] = True
    st.setdefault("warnings", []).append(f"degraded: {reason}")
    save_state(state_dir, st)


def record_qa_run(state_dir: Path, record: dict) -> None:
    st = load_state(state_dir)
    st.setdefault("qa_runs", []).append(record)
    save_state(state_dir, st)


def append_extension(state_dir: Path, ext: dict) -> None:
    st = load_state(state_dir)
    st.setdefault("extensions", []).append(ext)
    save_state(state_dir, st)


def increment_retry(state_dir: Path, stage: str) -> int:
    st = load_state(state_dir)
    ctr = st.setdefault("retry_counter", {})
    ctr[stage] = int(ctr.get(stage, 0)) + 1
    save_state(state_dir, st)
    return ctr[stage]


# ── Block file I/O ──────────────────────────────────────────────────────────

def write_block_file(state_dir: Path, index: int, payload: dict) -> Path:
    d = blocks_dir(state_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{index:05d}.json"
    p.write_text(json.dumps(payload, indent=2, default=_default_json))
    return p


def read_block_file(state_dir: Path, index: int) -> dict:
    p = blocks_dir(state_dir) / f"{index:05d}.json"
    return json.loads(p.read_text())


def iter_block_files(state_dir: Path):
    """Yield (index, path) for every block file in ascending order."""
    d = blocks_dir(state_dir)
    if not d.exists():
        return
    for p in sorted(d.glob("*.json")):
        stem = p.stem
        try:
            idx = int(stem)
        except ValueError:
            continue
        yield idx, p


def load_all_blocks(state_dir: Path) -> list[dict]:
    """Load every block file into memory as dicts. Caller re-hydrates to model."""
    return [json.loads(p.read_text()) for _, p in iter_block_files(state_dir)]


def write_resolution(state_dir: Path, kind: str, index: int, payload: dict) -> Path:
    d = resolutions_dir(state_dir, kind)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{index:05d}.json"
    p.write_text(json.dumps(payload, indent=2, default=_default_json))
    return p


def iter_resolutions(state_dir: Path, kind: str):
    d = resolutions_dir(state_dir, kind)
    if not d.exists():
        return
    for p in sorted(d.glob("*.json")):
        try:
            idx = int(p.stem)
        except ValueError:
            continue
        yield idx, json.loads(p.read_text())


# ── Helpers ─────────────────────────────────────────────────────────────────

def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _default_json(o):
    if hasattr(o, "__dataclass_fields__"):
        return asdict(o)
    if isinstance(o, (bytes, bytearray)):
        return f"<bytes:{len(o)}>"
    return str(o)
