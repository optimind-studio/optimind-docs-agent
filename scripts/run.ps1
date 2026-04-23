# Optimind Docs plugin launcher (Windows / PowerShell).
# On first run: creates a plugin-private venv, installs Python deps, and
# installs Poppins if missing. On subsequent runs: verifies fonts then
# execs the bundled venv's python with whatever args were passed.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File run.ps1 <path-to-python-script.py> [args...]

$ErrorActionPreference = "Stop"

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$PluginRoot = Split-Path -Parent $ScriptDir
$Venv       = Join-Path $PluginRoot ".venv"
$VenvPy     = Join-Path $Venv "Scripts\python.exe"
$Reqs       = Join-Path $PluginRoot "scripts\requirements.txt"
$Stamp      = Join-Path $Venv ".deps-installed"
$FontsSrc   = Join-Path $PluginRoot "assets\fonts"
$InstallFontsPy = Join-Path $PluginRoot "scripts\install_fonts.py"

# Ensure user-facing drop folders exist.
$InputDir  = Join-Path $HOME "OptimindDocs\input"
$OutputDir = Join-Path $HOME "OptimindDocs\output"
New-Item -ItemType Directory -Force -Path $InputDir, $OutputDir | Out-Null

# Locate a Python 3 interpreter.
$PyBin = $env:OPTIMIND_DOCS_PYTHON
if (-not $PyBin) {
    $candidate = Get-Command python -ErrorAction SilentlyContinue
    if ($candidate) { $PyBin = $candidate.Source }
}
if (-not $PyBin) {
    $candidate = Get-Command py -ErrorAction SilentlyContinue
    if ($candidate) { $PyBin = $candidate.Source }
}
if (-not $PyBin) {
    [Console]::Error.WriteLine('{"error": "Python 3 was not found on this machine. Install it from python.org (check ''Add Python to PATH'' during install), then try again."}')
    exit 127
}

# First-run: create venv + install deps.
if (-not (Test-Path $VenvPy) -or -not (Test-Path $Stamp)) {
    [Console]::Error.WriteLine("[optimind-docs] First-run setup: creating Python environment and installing dependencies...")
    if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
    & $PyBin -m venv $Venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $VenvPy -m pip install --quiet --upgrade pip
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $VenvPy -m pip install --quiet -r $Reqs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    New-Item -ItemType File -Force -Path $Stamp | Out-Null
    [Console]::Error.WriteLine("[optimind-docs] Setup complete.")
}

# Install Poppins if missing (skip-if-exists). Non-fatal.
try {
    & $VenvPy $InstallFontsPy $FontsSrc
} catch {
    [Console]::Error.WriteLine("[optimind-docs] Font install step skipped: $_")
}

# Exec the requested script with remaining args.
& $VenvPy @args
exit $LASTEXITCODE
