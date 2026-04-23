#!/usr/bin/env bash
# Optimind Docs plugin launcher (macOS / Linux / Git Bash on Windows).
# On first run: creates a plugin-private venv, installs Python deps, and
# installs the Poppins font family if it's missing from the system.
# On subsequent runs: verifies fonts (skips if present) and execs the bundled
# venv's python with whatever args were passed.
#
# Usage:
#   run.sh <path-to-python-script.py> [args...]

set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$PLUGIN_ROOT/.venv"
REQS="$PLUGIN_ROOT/scripts/requirements.txt"
STAMP="$VENV/.deps-installed"
FONTS_SRC="$PLUGIN_ROOT/assets/fonts"

# Windows (Git Bash / MSYS / Cygwin) puts the venv python under Scripts/, not bin/.
case "${OSTYPE:-}" in
  msys*|cygwin*|win32*)
    VENV_PY="$VENV/Scripts/python.exe"
    ;;
  *)
    VENV_PY="$VENV/bin/python"
    ;;
esac

# Ensure user-facing drop folders exist (first-run convenience).
mkdir -p "$HOME/OptimindDocs/input" "$HOME/OptimindDocs/output"

# Pick a python3 interpreter (macOS 12+ ships python3; Windows users install from python.org).
PY_BIN="${OPTIMIND_DOCS_PYTHON:-}"
if [ -z "$PY_BIN" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PY_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PY_BIN="python"
  else
    cat >&2 <<ERR
{"error": "Python 3 was not found on this machine. Install it (macOS: 'brew install python'; Windows: download from python.org and check 'Add Python to PATH'), then try again."}
ERR
    exit 127
  fi
fi

# First-run: create venv + install deps.
if [ ! -x "$VENV_PY" ] || [ ! -f "$STAMP" ]; then
  echo "[optimind-docs] First-run setup: creating Python environment and installing dependencies..." >&2
  rm -rf "$VENV"
  "$PY_BIN" -m venv "$VENV" >&2
  "$VENV_PY" -m pip install --quiet --upgrade pip >&2
  "$VENV_PY" -m pip install --quiet -r "$REQS" >&2
  touch "$STAMP"
  echo "[optimind-docs] Setup complete." >&2
fi

# Install Poppins on this machine if missing (skip-if-exists, cross-platform).
# Non-fatal: if this step fails the polisher still runs, output just won't
# render in Poppins on this machine.
"$VENV_PY" "$PLUGIN_ROOT/scripts/install_fonts.py" "$FONTS_SRC" || true

exec "$VENV_PY" "$@"
