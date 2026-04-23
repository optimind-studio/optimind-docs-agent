#!/usr/bin/env bash
# Optimind Docs plugin launcher (macOS / Linux).
# On first run: creates a plugin-private venv, installs Python deps, and
# installs the Poppins font family if it's missing from the system.
# On subsequent runs: verifies fonts (skips if present) and execs the bundled
# venv's python with whatever args were passed.
#
# Windows users: use run.ps1 instead — it handles auto-install of Python.
#
# Usage:
#   run.sh <path-to-python-script.py> [args...]

set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$PLUGIN_ROOT/.venv"
REQS="$PLUGIN_ROOT/scripts/requirements.txt"
STAMP="$VENV/.deps-installed"
FONTS_SRC="$PLUGIN_ROOT/assets/fonts"
VENV_PY="$VENV/bin/python"

# Ensure user-facing drop folders exist (first-run convenience).
mkdir -p "$HOME/OptimindDocs/input" "$HOME/OptimindDocs/output"

# Returns 0 if the given command is a usable Python 3 (not the Windows
# "Microsoft Store" stub and not a Python 2), 1 otherwise.
is_real_python3() {
  local candidate="$1"
  [ -z "$candidate" ] && return 1
  command -v "$candidate" >/dev/null 2>&1 || return 1
  local version_output
  version_output="$("$candidate" --version 2>&1 || true)"
  # Real Python 3 prints "Python 3.X.Y". The MS Store stub prints
  # "Python was not found...". Python 2 prints "Python 2.X.Y".
  [[ "$version_output" =~ ^Python\ 3\.[0-9]+ ]]
}

PY_BIN=""
for candidate in "${OPTIMIND_DOCS_PYTHON:-}" python3 python; do
  if is_real_python3 "$candidate"; then
    PY_BIN="$candidate"
    break
  fi
done

if [ -z "$PY_BIN" ]; then
  cat >&2 <<ERR
{"error": "Python 3 was not found on this machine. Install it (macOS: 'brew install python'; Linux: use your package manager, e.g. 'sudo apt install python3 python3-venv'), then try again."}
ERR
  exit 127
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
