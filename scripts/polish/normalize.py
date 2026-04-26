"""Aggressive pre-classify cleanup for design-tool exports.

Many source documents arrive as a dump from a layout/design tool (Canva,
slide decks saved as .docx, Figma exports, dashboards exported to PDF).
The characteristic pathologies are:

  - Every word is its own floating text frame, so paragraph `.text` arrives
    as `"Redesign\n \nMDC\n \nEmail\n \nContent"` instead of
    `"Redesign MDC Email Content"`.
  - Overlapping decorative layers duplicate the same visible text, so the
    same paragraph shows up 2–3 times back-to-back.
  - Huge runs of empty "spacer" paragraphs sit between real content, each
    with a `BodyText` style and Times New Roman 8pt — pure padding.

This pass runs between flatten and tokenize_blocks. It operates on the
flat token stream (same dict schema as ingest / flatten) and:

  1. Collapses all-whitespace inside a paragraph's `.text` and each run
     into single spaces. Preserves order; preserves bold/italic flags.
  2. Drops paragraph tokens whose normalized text is empty.
  3. Deduplicates paragraph tokens whose normalized text matches any of
     the last N paragraph tokens' text (window catches back-to-back
     duplicate design layers).
  4. Deduplicates image tokens with identical bytes inside a rolling window
     (design-tool pages often stamp the same icon/logo on every page).

Returns (cleaned_tokens, warnings). Warnings name the collapse/dedup
counts so the sidecar tells the full story.
"""
from __future__ import annotations

import re
from typing import Iterable


_WS_RE = re.compile(r"\s+")
_DEDUP_WINDOW = 8            # look back this many paragraphs for exact-text dupes
_IMAGE_DEDUP_WINDOW = 12     # rolling window for identical image bytes

# Letter-spaced source pattern — e.g. `M O N T H L Y  R E P O R T` where the
# CSS letter-spacing was rendered as literal spaces. We detect and fix this
# BEFORE collapsing whitespace so the double-space word boundaries survive.
#
# A token is single-char-alnum if it's exactly one alphanumeric character.
# We only fire if a paragraph is dominated by such tokens AND word-boundary
# signals (multi-space runs) exist — otherwise we'd mangle prose.
_SINGLE_CHAR_ALNUM_RE = re.compile(r'^[A-Za-z0-9]$')
_LETTERSPACED_RUN_RE = re.compile(
    r'(?:[A-Za-z0-9] ){1,}[A-Za-z0-9](?=(?:\s|$))'
)


def normalize(tokens: Iterable[dict]) -> tuple[list[dict], list[str]]:
    out: list[dict] = []
    warnings: list[str] = []

    collapsed = 0      # paragraphs whose text we normalized
    emptied = 0        # paragraphs dropped because normalized text is empty
    dup_paras = 0      # paragraphs dropped as duplicates
    dup_images = 0     # images dropped as duplicates

    # Rolling window of recent paragraph normalized text (left = oldest).
    recent_text: list[str] = []
    # Rolling window of recent image-byte identities.
    recent_imgs: list[int] = []

    for tok in tokens:
        kind = tok.get("kind")
        if kind == "paragraph":
            new_text, new_runs, changed = _normalize_paragraph(tok)
            if changed:
                collapsed += 1

            if not new_text:
                emptied += 1
                # If the paragraph had inline images or page-break markers,
                # still keep it so flatten's image-lift invariant holds.
                # (In practice normalize runs AFTER flatten, so inline_images
                # are already lifted to standalone tokens — safe to drop.)
                continue

            if new_text in recent_text:
                dup_paras += 1
                continue

            tok["text"] = new_text
            tok["runs"] = new_runs
            out.append(tok)
            recent_text.append(new_text)
            if len(recent_text) > _DEDUP_WINDOW:
                recent_text.pop(0)
            continue

        if kind == "image":
            blob = tok.get("image_bytes") or b""
            # Hash only first 256 bytes + length — stable, O(1), avoids copying.
            sig = hash((len(blob), bytes(blob[:256])))
            if sig in recent_imgs:
                dup_images += 1
                continue
            out.append(tok)
            recent_imgs.append(sig)
            if len(recent_imgs) > _IMAGE_DEDUP_WINDOW:
                recent_imgs.pop(0)
            continue

        # Tables and any other kinds pass through untouched — but the text
        # window resets so a paragraph with identical body text to a previous
        # one on the other side of a table is NOT treated as a dupe.
        out.append(tok)
        recent_text.clear()

    if collapsed:
        warnings.append(
            f"normalize: collapsed fragmented whitespace in {collapsed} paragraph(s)"
        )
    if emptied:
        warnings.append(
            f"normalize: dropped {emptied} empty/whitespace-only paragraph(s)"
        )
    if dup_paras:
        warnings.append(
            f"normalize: dropped {dup_paras} duplicate paragraph(s) "
            f"(overlapping design-tool layers)"
        )
    if dup_images:
        warnings.append(
            f"normalize: dropped {dup_images} duplicate inline image(s)"
        )

    return out, warnings


def _normalize_paragraph(tok: dict) -> tuple[str, list[dict], bool]:
    """Collapse whitespace inside text + each run. Returns (new_text, new_runs, changed)."""
    old_text = tok.get("text") or ""
    old_runs = tok.get("runs") or []

    # First, fix letter-spaced text while multi-space word-boundaries are intact.
    despaced_text = _reconstitute_letterspaced(old_text)
    new_text = _collapse_ws(despaced_text)

    new_runs: list[dict] = []
    for r in old_runs:
        # Collapse internal whitespace but preserve boundary spaces — they are
        # word separators between adjacent runs and must not be stripped away.
        rt = _WS_RE.sub(" ", _reconstitute_letterspaced(r.get("text") or ""))
        if not rt:
            continue
        new_runs.append({
            "text": rt,
            "bold": bool(r.get("bold")),
            "italic": bool(r.get("italic")),
        })

    # If we dropped all runs but we still have text, rebuild a single run so
    # downstream code that expects runs keeps working.
    if new_text and not new_runs:
        new_runs = [{"text": new_text, "bold": False, "italic": False}]

    changed = (new_text != old_text.strip()) or (len(new_runs) != len(old_runs))
    return new_text, new_runs, changed


def _collapse_ws(s: str) -> str:
    """Normalize whitespace: every run of whitespace (including \\n) → single space."""
    if not s:
        return ""
    return _WS_RE.sub(" ", s).strip()


def _reconstitute_letterspaced(s: str) -> str:
    """If a string looks letter-spaced (e.g. `M O N T H L Y  R E P O R T`),
    collapse single-space gaps inside each word while preserving multi-space
    gaps as actual word boundaries.

    We only fire when the pattern is unambiguous — at least one run of ≥3
    single-char tokens separated by single spaces — so we don't mangle
    prose. Inputs without that signature pass through unchanged.
    """
    if not s or len(s) < 5:
        return s
    if not _LETTERSPACED_RUN_RE.search(s):
        return s

    # Walk character-by-character, identifying "single-char tokens separated
    # by single spaces" and collapsing them into unspaced words. Double-space
    # (and larger) runs act as word boundaries — we emit one space per such run.
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == " ":
            # Count the space run.
            j = i
            while j < n and s[j] == " ":
                j += 1
            space_run = j - i
            # Single-space between two alnum runs may be interior letter spacing
            # — handled in the alnum branch below. Multi-space is word break.
            if space_run >= 2:
                out.append(" ")
            else:
                # Only reachable if we're starting the string with a single space
                # or there was no preceding alnum; treat as single space.
                out.append(" ")
            i = j
            continue

        # Non-space: try to grab a "letter-spaced run" starting here.
        # Pattern: char, space, char, space, char, ... ending when we see
        # double-space or non-alphanum-followed or end.
        if _SINGLE_CHAR_ALNUM_RE.match(ch):
            run_chars: list[str] = [ch]
            j = i + 1
            while j + 1 < n:
                if s[j] == " " and s[j + 1] != " " and _SINGLE_CHAR_ALNUM_RE.match(s[j + 1]):
                    run_chars.append(s[j + 1])
                    j += 2
                else:
                    break
            # If run_chars has 3+ chars, it's a reconstituted letter-spaced word.
            # If it's 2 chars, only collapse if both are digits (so "0 8" becomes
            # "08" but random "A B" prose is preserved).
            if (len(run_chars) >= 3
                    or (len(run_chars) == 2 and all(c.isdigit() for c in run_chars))):
                out.append("".join(run_chars))
                i = j
                continue
        # Otherwise pass the character through unchanged.
        out.append(ch)
        i += 1
    return "".join(out)
