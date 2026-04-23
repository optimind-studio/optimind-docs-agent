#!/usr/bin/env python3
"""
Cross-platform Poppins installer for the Optimind Docs plugin.

Checks whether Poppins (Regular, Bold, SemiBold) is already installed on the
machine. If any files are missing, copies them from the plugin's bundled
`assets/fonts/` directory into the user-scoped font folder for the current OS.

Supports macOS, Windows, and Linux. No admin/root required — installs per-user.

Usage:
    python install_fonts.py <path-to-bundled-fonts-dir>
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

FONT_FILES = (
    "Poppins-Regular.ttf",
    "Poppins-Bold.ttf",
    "Poppins-SemiBold.ttf",
)


def _user_fonts_dir() -> Path:
    """Per-user font directory for the current platform."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Fonts"
    if system == "Windows":
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            return Path(local_app) / "Microsoft" / "Windows" / "Fonts"
        return Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts"
    # Linux / BSD / anything else
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
    return base / "fonts"


def _system_font_dirs() -> list[Path]:
    """System-wide font directories to check for pre-existing installs."""
    system = platform.system()
    if system == "Darwin":
        return [Path("/Library/Fonts"), Path("/System/Library/Fonts")]
    if system == "Windows":
        win_root = os.environ.get("SystemRoot", r"C:\Windows")
        return [Path(win_root) / "Fonts"]
    return [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
    ]


def _font_already_installed(font_name: str) -> bool:
    """True if `font_name` exists in any user or system font directory."""
    candidates = [_user_fonts_dir(), *_system_font_dirs()]
    for directory in candidates:
        if not directory.exists():
            continue
        # Top-level quick check (covers macOS + Windows flat layouts).
        if (directory / font_name).exists():
            return True
        # Linux often nests fonts in subdirs — recurse one level deep.
        if platform.system() == "Linux":
            try:
                for match in directory.rglob(font_name):
                    if match.is_file():
                        return True
            except (PermissionError, OSError):
                continue
    return False


def install_bundled_fonts(src_dir: Path) -> tuple[int, int, list[str]]:
    """
    Copy any missing Poppins files from `src_dir` into the user font folder.

    Returns (installed_count, skipped_count, missing_source_files).
    """
    target = _user_fonts_dir()
    installed = 0
    skipped = 0
    missing: list[str] = []

    for fname in FONT_FILES:
        if _font_already_installed(fname):
            skipped += 1
            continue

        src = src_dir / fname
        if not src.exists():
            missing.append(fname)
            continue

        target.mkdir(parents=True, exist_ok=True)
        dest = target / fname
        shutil.copy2(src, dest)
        installed += 1
        print(f"[optimind-docs] Installed {fname} -> {dest}", file=sys.stderr)

    return installed, skipped, missing


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: install_fonts.py <bundled-fonts-dir>", file=sys.stderr)
        return 2

    src = Path(sys.argv[1])
    if not src.is_dir():
        print(f"[optimind-docs] Font source not found: {src}", file=sys.stderr)
        return 0  # non-fatal; plugin still works, just without auto-install

    installed, skipped, missing = install_bundled_fonts(src)

    if installed == 0 and skipped == len(FONT_FILES):
        # All good, already present — stay quiet to keep logs clean.
        return 0

    if missing:
        print(
            f"[optimind-docs] Note: bundled font(s) missing from plugin: {', '.join(missing)}",
            file=sys.stderr,
        )

    if installed > 0:
        print(
            f"[optimind-docs] Poppins setup: installed {installed}, already present {skipped}.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
