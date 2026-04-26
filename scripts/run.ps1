# Optimind Docs plugin launcher (Windows / PowerShell).
#
# First-run wizard (zero-config for non-technical users):
#   1. Locate a real Python 3 on this machine.
#   2. If none is found, silently download and install Python 3.12 from
#      python.org — per-user install, no admin required.
#   3. Create a plugin-private venv and install Python dependencies.
#   4. Install the Poppins font family if it's missing from the system.
#
# Subsequent runs skip setup and just exec the bundled venv python.
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

# Python version to auto-install if none is found on the system.
$PythonVersion = "3.12.7"

# Ensure user-facing drop folders exist.
$InputDir  = Join-Path $HOME "OptimindDocs\input"
$OutputDir = Join-Path $HOME "OptimindDocs\output"
New-Item -ItemType Directory -Force -Path $InputDir, $OutputDir | Out-Null

function Write-Info($msg) {
    [Console]::Error.WriteLine("[optimind-docs] $msg")
}

# Given a path to a claimed Python executable, verify it actually runs and
# isn't the Windows "Microsoft Store" stub (which lives under \WindowsApps\
# and prints "Python was not found; run without arguments to install from
# the Microsoft Store" when invoked).
function Test-RealPython($exePath) {
    if (-not $exePath) { return $false }
    if (-not (Test-Path $exePath)) { return $false }
    if ($exePath -like "*\WindowsApps\*") { return $false }
    try {
        $output = (& $exePath --version 2>&1 | Out-String)
        return ($output -match "^\s*Python 3\.\d+")
    } catch {
        return $false
    }
}

function Find-Python {
    if ($env:OPTIMIND_DOCS_PYTHON -and (Test-RealPython $env:OPTIMIND_DOCS_PYTHON)) {
        return $env:OPTIMIND_DOCS_PYTHON
    }
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd -and (Test-RealPython $cmd.Source)) { return $cmd.Source }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and (Test-RealPython $cmd.Source)) { return $cmd.Source }
    # Common install locations — useful right after a silent install, before
    # Windows has refreshed the session PATH.
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:PROGRAMFILES\Python312\python.exe",
        "$env:PROGRAMFILES\Python311\python.exe",
        "$env:PROGRAMFILES\Python310\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-RealPython $c) { return $c }
    }
    return $null
}

function Update-SessionPath {
    $userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
    $machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
    $env:PATH = @($machinePath, $userPath) -join ";"
}

function Get-PythonInstallerUrl {
    $archStr = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    switch ($archStr) {
        "Arm64" { $suffix = "arm64" }
        "X64"   { $suffix = "amd64" }
        default { $suffix = "amd64" }
    }
    return "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-$suffix.exe"
}

function Install-Python {
    $url = Get-PythonInstallerUrl
    Write-Info "Python 3 not found. Downloading Python $PythonVersion from python.org (per-user install, no admin needed)..."
    $installerPath = Join-Path $env:TEMP "optimind-docs-python-$PythonVersion.exe"

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $installerPath -UseBasicParsing
    } catch {
        throw "Failed to download Python installer from $url`n$_`nPlease install Python 3 manually from https://www.python.org/downloads/ and retry."
    }

    Write-Info "Installing Python $PythonVersion silently (this can take a minute)..."
    $installerArgs = @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_launcher=1",
        "Include_test=0",
        "Include_doc=0",
        "SimpleInstall=1"
    )
    $proc = Start-Process -FilePath $installerPath -ArgumentList $installerArgs -Wait -PassThru -NoNewWindow
    Remove-Item $installerPath -Force -ErrorAction SilentlyContinue

    if ($proc.ExitCode -ne 0) {
        throw "Python installer exited with code $($proc.ExitCode). Please install Python 3 manually from https://www.python.org/downloads/."
    }

    Update-SessionPath
    Write-Info "Python $PythonVersion installed."
}

$PyBin = Find-Python
if (-not $PyBin) {
    Install-Python
    $PyBin = Find-Python
    if (-not $PyBin) {
        [Console]::Error.WriteLine('{"error": "Python installation completed but python could not be located. Please restart your shell and try again, or install manually from https://www.python.org/downloads/."}')
        exit 127
    }
}

if (-not (Test-Path $VenvPy) -or -not (Test-Path $Stamp)) {
    Write-Info "First-run setup: creating Python environment and installing dependencies..."
    if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
    & $PyBin -m venv $Venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $VenvPy -m pip install --quiet --upgrade pip
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $VenvPy -m pip install --quiet -r $Reqs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    New-Item -ItemType File -Force -Path $Stamp | Out-Null
    Write-Info "Setup complete."
}

try {
    & $VenvPy $InstallFontsPy $FontsSrc
} catch {
    Write-Info "Font install step skipped: $_"
}

# --install-only: used by the SessionStart hook to bootstrap deps without
# running the pipeline. Exit here so the hook doesn't accidentally exec python
# with no meaningful args.
if ($args.Count -gt 0 -and $args[0] -eq "--install-only") {
    exit 0
}

# Put `scripts/` on the module search path so `python -m polish` resolves.
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$ScriptDir;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $ScriptDir
}

& $VenvPy @args
exit $LASTEXITCODE
