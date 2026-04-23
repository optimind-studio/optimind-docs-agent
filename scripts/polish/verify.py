"""Verify step — structured QA diagnosis for the orchestrator retry loop.

Two checks:

    1. Content preservation: every source body word (≥3 chars) should appear
       in the rendered output. Cover/header/footer inject extras, so they can
       only ever add. Missing-word count drives severity.
    2. Layout smoke: no zero-size tables, no empty body, etc. Cheap
       structural sanity check.

Unlike the 0.3.x version, ``verify`` NEVER raises. It returns a structured
``QADiagnosis`` dict that Renderer-QA parses to decide ``should_retry`` and
``stage_to_retry``. The orchestrator owns the retry policy, not Python.

QADiagnosis schema (matches handoff-protocol.md → renderer-qa reply):

    {
      "passed": bool,
      "hard_fail": bool,
      "reason": str,
      "severity": "high" | "medium" | "low",
      "stage_to_retry": "render" | None,
      "affected_block_indices": list[int],
      "retry_instructions": str,
      "warnings": list[str]
    }
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from docx import Document as OpenDocx
from docx.oxml.ns import qn

from .model import Document


_WORD_RE = re.compile(r"[^A-Za-z0-9]+")
_DROP_RATIO_HARD_FAIL = 0.10
_UNIQUE_MISSING_SAMPLE = 10
_DROP_SAMPLE = 5


def verify(output_path: Path, doc: Document) -> dict:
    """Run content-preservation + layout-smoke checks.

    Always returns a QADiagnosis dict — never raises. Rendering callers
    that want old-style raising can check ``diagnosis["passed"]`` and
    ``diagnosis["hard_fail"]``.
    """
    diagnosis: dict = {
        "passed": True,
        "hard_fail": False,
        "reason": "",
        "severity": "low",
        "stage_to_retry": None,
        "affected_block_indices": [],
        "retry_instructions": "",
        "warnings": [],
    }

    # Layout smoke first — cheap structural checks detect catastrophic failures.
    smoke = _layout_smoke(output_path)
    if not smoke["ok"]:
        diagnosis.update({
            "passed": False,
            "hard_fail": smoke["hard_fail"],
            "reason": smoke["reason"],
            "severity": "high",
            "stage_to_retry": "render",
            "retry_instructions": "re-run render stage; investigate renderer contracts",
        })
        return diagnosis

    # Content preservation
    content = _content_preservation(doc, output_path)
    diagnosis["warnings"].extend(content["warnings"])
    if not content["ok"]:
        diagnosis.update({
            "passed": False,
            "hard_fail": False,
            "reason": content["reason"],
            "severity": content["severity"],
            "stage_to_retry": "render",
            "retry_instructions": content["retry_instructions"],
        })

    return diagnosis


# ── content preservation ────────────────────────────────────────────────────

def _content_preservation(doc: Document, output_path: Path) -> dict:
    warnings: list[str] = []
    src_text = _canonical_text(doc)
    if not src_text:
        return {"ok": True, "warnings": warnings}

    out_text = _docx_text(output_path)
    src_words = Counter(w for w in src_text.split() if len(w) >= 3)
    out_words = Counter(w for w in out_text.split() if len(w) >= 3)

    if not src_words:
        return {"ok": True, "warnings": warnings}

    unique_missing = [w for w, n in src_words.items() if out_words[w] == 0]
    if unique_missing:
        sample = unique_missing[:_UNIQUE_MISSING_SAMPLE]
        return {
            "ok": False,
            "severity": "high",
            "reason": (
                f"{len(unique_missing)} unique source word(s) missing from output "
                f"— a whole block likely rendered empty. Sample: {sample}"
            ),
            "retry_instructions": (
                "Re-render; inspect renderers for silent drops of any block "
                f"containing: {sample[:3]}"
            ),
            "warnings": warnings,
        }

    total_drops = sum(max(0, n - out_words[w]) for w, n in src_words.items())
    total_source = sum(src_words.values())
    drop_ratio = total_drops / total_source if total_source else 0.0

    if drop_ratio > _DROP_RATIO_HARD_FAIL:
        reductions = [(w, n, out_words[w]) for w, n in src_words.items() if out_words[w] < n]
        reductions.sort(key=lambda r: r[1] - r[2], reverse=True)
        return {
            "ok": False,
            "severity": "high",
            "reason": (
                f"content-preservation drop {drop_ratio:.1%} "
                f"({total_drops}/{total_source}). Top reductions: {reductions[:_DROP_SAMPLE]}"
            ),
            "retry_instructions": "Re-render with narrower optimizations off.",
            "warnings": warnings,
        }

    if total_drops > 0:
        warnings.append(
            f"content-preservation: {total_drops} word-occurrence(s) "
            f"({drop_ratio:.1%}) reduced — within tolerance"
        )
    return {"ok": True, "warnings": warnings}


def _canonical_text(doc: Document) -> str:
    parts: list[str] = []
    for b in doc.blocks:
        parts.extend(_block_text(b))
    raw = "\n".join(parts)
    return _WORD_RE.sub(" ", raw).strip().lower()


def _block_text(block) -> list[str]:
    c = block.content
    k = block.kind
    if k == "heading":
        return [c.text]
    if k == "paragraph":
        return [c.text] if hasattr(c, "text") else ["".join(r.text for r in c.runs)]
    if k == "list":
        return ["".join(r.text for r in it.runs) for it in c.items]
    if k == "callout":
        out = [c.label]
        for p in c.body:
            out.append("".join(r.text for r in p.runs))
        return out
    if k == "table":
        out: list[str] = []
        for hr in c.headers:
            out.extend(hr)
        for row in c.rows:
            out.extend(row)
        if c.caption:
            out.append(c.caption)
        return out
    if k == "kpi_strip":
        out = []
        for card in c.cards:
            out.append(card.label)
            out.append(card.value)
            if card.delta:
                out.append(card.delta)
        return out
    if k == "chart":
        return [c.title] if c.title else []
    if k == "figure":
        out = []
        if c.caption:
            out.append(c.caption)
        if c.alt:
            out.append(c.alt)
        return out
    return []


def _docx_text(path: Path) -> str:
    d = OpenDocx(str(path))
    paras: list[str] = []
    for p in d.element.body.iter(qn("w:p")):
        chunks = []
        for t in p.iter(qn("w:t")):
            if t.text:
                chunks.append(t.text)
        if chunks:
            paras.append("".join(chunks))
    for section in d.sections:
        for area in (section.header, section.footer):
            for p in area.paragraphs:
                if p.text:
                    paras.append(p.text)
    raw = "\n".join(paras)
    return _WORD_RE.sub(" ", raw).strip().lower()


# ── layout smoke ────────────────────────────────────────────────────────────

def _layout_smoke(output_path: Path) -> dict:
    try:
        d = OpenDocx(str(output_path))
    except Exception as e:
        return {
            "ok": False,
            "hard_fail": True,
            "reason": f"could not open rendered .docx: {e}",
        }
    body = d.element.body
    has_content = False
    for child in body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag in ("p", "tbl"):
            has_content = True
            break
    if not has_content:
        return {"ok": False, "hard_fail": False, "reason": "rendered output has no body content"}

    for i, tbl in enumerate(d.tables):
        n_rows = len(tbl.rows)
        if n_rows == 0:
            return {"ok": False, "hard_fail": False, "reason": f"table[{i}] has zero rows"}
        n_cols = max(len(r.cells) for r in tbl.rows)
        if n_cols == 0:
            return {"ok": False, "hard_fail": False, "reason": f"table[{i}] has zero columns"}
    return {"ok": True, "hard_fail": False, "reason": ""}
