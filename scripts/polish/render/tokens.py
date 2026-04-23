"""Brand tokens — single source of truth.

Mirrors ``skills/polish/references/ui-kit.md`` and the Figma design system
(file iYE9CtCoxRESvSGtTrfBhs, Docx Demo frame 2550:17). If any built-in token
changes, update the ui-kit.md reference in lockstep.

Runtime extensions (v0.5): the DS-Extender subagent can add new tokens for
novel components it designs. Extension tokens are stored in
``tokens_extensions.json`` (committed to git for reproducibility) and merged
into this module's namespace at import time. A dynamic renderer at
``render/dynamic/<kind>.py`` can then reference them as ``T.<TOKEN_NAME>``
alongside any built-in.

Collisions are resolved with a warning: extensions never override built-in
tokens (built-ins win). This prevents a bad extension push from silently
changing brand colors.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from docx.shared import Pt, RGBColor


log = logging.getLogger(__name__)


# ── Semantic colors ──────────────────────────────────────────────────────────
RED        = RGBColor(0xF5, 0x2C, 0x39)  # brand
TEXT_PRI   = RGBColor(0x00, 0x00, 0x00)  # text/primary
TEXT_SEC   = RGBColor(0x62, 0x65, 0x67)  # text/secondary
BG_SUBTLE  = RGBColor(0xF2, 0xF3, 0xF4)  # bg/subtle
BG_BRAND   = RGBColor(0xFE, 0xEC, 0xEE)  # bg/brand-subtle
BORDER_DEF = RGBColor(0xE5, 0xE7, 0xE9)  # border/default
BORDER_STR = RGBColor(0xD7, 0xDB, 0xDD)  # border/strong
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)  # text/on-brand, bg/page


# ── Text styles ──────────────────────────────────────────────────────────────
FONT_FAMILY = "Poppins"


@dataclass(frozen=True)
class TextStyle:
    size: Pt
    bold: bool
    color: RGBColor
    uppercase: bool = False
    letter_spacing_pt: float = 0.0
    line_spacing: float = 1.5   # multiplier


TITLES_COVER     = TextStyle(size=Pt(40), bold=True,  color=TEXT_PRI, line_spacing=1.1)
TITLES_MAIN      = TextStyle(size=Pt(16), bold=True,  color=TEXT_PRI, line_spacing=1.25)
TITLES_SUB       = TextStyle(size=Pt(12), bold=True,  color=TEXT_PRI, line_spacing=1.3)
TITLES_TABLE     = TextStyle(size=Pt(10), bold=True,  color=WHITE,    line_spacing=1.25)
TEXT_COVER       = TextStyle(size=Pt(12), bold=False, color=TEXT_PRI, line_spacing=1.4)
TEXT_MAIN        = TextStyle(size=Pt(11), bold=False, color=TEXT_PRI, line_spacing=1.5)
TEXT_TABLE       = TextStyle(size=Pt(10), bold=False, color=TEXT_PRI, line_spacing=1.25)
TEXT_DISCLAIMER  = TextStyle(size=Pt(9),  bold=False, color=TEXT_SEC, line_spacing=1.3)
LABELS_COVER     = TextStyle(size=Pt(11), bold=True,  color=TEXT_PRI,
                             uppercase=True, letter_spacing_pt=1.32)
LABELS_MAIN      = TextStyle(size=Pt(10), bold=True,  color=TEXT_SEC,
                             uppercase=True, letter_spacing_pt=1.2)


HEADING_STYLES = {
    1: TITLES_MAIN,
    2: TITLES_SUB,
    3: TextStyle(size=Pt(11), bold=True, color=TEXT_PRI, line_spacing=1.35),
}


# ── Layout tokens (twips = 1/1440 inch) ──────────────────────────────────────
PAGE_MARGIN_TOP_TWIPS    = 1080
PAGE_MARGIN_BOTTOM_TWIPS = 1080
PAGE_MARGIN_LEFT_TWIPS   = 1080
PAGE_MARGIN_RIGHT_TWIPS  = 1080

CELL_PAD_V_TWIPS = 100
CELL_PAD_H_TWIPS = 120

H1_DIVIDER_SIZE_TWIPS   = 4
BORDER_DEFAULT_SZ       = 4
BORDER_STRONG_SZ        = 8

PARA_SPACE_AFTER_TWIPS  = 120
HEADING_SPACE_BEFORE_TWIPS = 360
HEADING_SPACE_AFTER_TWIPS  = 120


# ── Callout palette ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CalloutPalette:
    fill: RGBColor
    label_color: RGBColor
    body_color: RGBColor


CALLOUT_PALETTES = {
    "insight":    CalloutPalette(fill=BG_BRAND,  label_color=RED,      body_color=TEXT_PRI),
    "next_steps": CalloutPalette(fill=BG_SUBTLE, label_color=TEXT_PRI, body_color=TEXT_SEC),
    "warning":    CalloutPalette(fill=BG_BRAND,  label_color=RED,      body_color=TEXT_PRI),
    "note":       CalloutPalette(fill=BG_SUBTLE, label_color=TEXT_SEC, body_color=TEXT_PRI),
}


# ── Chart palette ────────────────────────────────────────────────────────────
CHART_SERIES_COLORS = [
    RGBColor(0xF5, 0x2C, 0x39),  # brand red
    RGBColor(0x62, 0x65, 0x67),  # text/secondary
    RGBColor(0xF2, 0x72, 0x7B),  # red/300
    RGBColor(0x9B, 0x9E, 0xA0),  # neutral/400
    RGBColor(0xFD, 0xAE, 0xB3),  # red/200
    RGBColor(0xD7, 0xDB, 0xDD),  # border/strong
]


def hex_color(rgb: RGBColor) -> str:
    return f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


# ── Runtime extensions ──────────────────────────────────────────────────────
#
# Loaded once at import from tokens_extensions.json. The schema is:
#
#   {
#     "hex_tokens": {"TIMELINE_DOT": "#2E7D32", ...},
#     "text_styles": {
#        "TIMELINE_DATE": {
#           "size_pt": 9, "bold": false, "color_token": "TEXT_SEC",
#           "letter_spacing_px": 1.2, "uppercase": true
#        }
#     }
#   }
#
# Built-in token names are the single protected namespace — extensions that
# collide are skipped with a warning. Order: hex tokens first (so text styles
# can reference newly-added color tokens), then text styles.

_BUILTIN_NAMES = {
    "RED", "TEXT_PRI", "TEXT_SEC", "BG_SUBTLE", "BG_BRAND",
    "BORDER_DEF", "BORDER_STR", "WHITE",
    "TITLES_COVER", "TITLES_MAIN", "TITLES_SUB", "TITLES_TABLE",
    "TEXT_COVER", "TEXT_MAIN", "TEXT_TABLE", "TEXT_DISCLAIMER",
    "LABELS_COVER", "LABELS_MAIN",
    "HEADING_STYLES", "CALLOUT_PALETTES", "CHART_SERIES_COLORS",
    "FONT_FAMILY",
}


def _extensions_path() -> Path:
    return Path(__file__).resolve().parent / "tokens_extensions.json"


def _load_extensions() -> dict:
    p = _extensions_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except Exception as e:
        log.warning("tokens_extensions.json unreadable (%s) — ignoring", e)
        return {}
    if not isinstance(data, dict):
        log.warning("tokens_extensions.json not an object — ignoring")
        return {}
    return data


def _hex_to_rgb(hex_str: str) -> RGBColor | None:
    s = (hex_str or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        return RGBColor(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _apply_extensions(ext: dict) -> list[str]:
    """Merge extension tokens into this module's namespace.

    Returns a list of skipped-name warnings for the caller to surface.
    """
    warnings: list[str] = []
    mod = sys.modules[__name__]

    for name, hex_str in (ext.get("hex_tokens") or {}).items():
        if not isinstance(name, str) or not name.isidentifier() or not name.isupper():
            warnings.append(f"tokens_extensions: invalid token name {name!r}")
            continue
        if name in _BUILTIN_NAMES:
            warnings.append(f"tokens_extensions: skipped {name!r} — shadows built-in token")
            continue
        rgb = _hex_to_rgb(hex_str)
        if rgb is None:
            warnings.append(f"tokens_extensions: bad hex {hex_str!r} for {name!r}")
            continue
        setattr(mod, name, rgb)

    for name, spec in (ext.get("text_styles") or {}).items():
        if not isinstance(name, str) or not name.isidentifier() or not name.isupper():
            warnings.append(f"tokens_extensions: invalid text-style name {name!r}")
            continue
        if name in _BUILTIN_NAMES:
            warnings.append(f"tokens_extensions: skipped text-style {name!r} — shadows built-in")
            continue
        color_token = spec.get("color_token") or "TEXT_PRI"
        color = getattr(mod, color_token, TEXT_PRI)
        try:
            style = TextStyle(
                size=Pt(float(spec.get("size_pt", 11))),
                bold=bool(spec.get("bold", False)),
                color=color,
                uppercase=bool(spec.get("uppercase", False)),
                letter_spacing_pt=float(spec.get("letter_spacing_px", 0.0)),
                line_spacing=float(spec.get("line_spacing", 1.4)),
            )
        except Exception as e:
            warnings.append(f"tokens_extensions: invalid text-style {name!r}: {e}")
            continue
        setattr(mod, name, style)
    return warnings


# Apply at import. Extension warnings are logged and also stored on the
# module so the skill/report can surface them.
EXTENSION_WARNINGS = _apply_extensions(_load_extensions())
for _w in EXTENSION_WARNINGS:
    log.warning(_w)
