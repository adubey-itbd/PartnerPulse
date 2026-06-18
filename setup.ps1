<#
.SYNOPSIS
    PartnerPulse one-shot bootstrap — fresh Windows machine -> live local dashboard.

.DESCRIPTION
    Run this after downloading/extracting the repo zip on a new machine. It will:
      1. Ensure Python 3 is installed (installs via winget if missing).
      2. Create an isolated virtual environment (.venv) and install dependencies.
      3. (Optionally) write a .env so you can override the baked-in API keys.
      4. Build every partner's data cache + Claude churn analysis (data\*.json).
      5. Start the local web server and open the portfolio dashboard in your browser.

    Halo / TeamGPS API keys are already baked into extract\config.py, so no key entry is
    required. The Claude churn analysis bills your Claude subscription via the local
    Claude Agent SDK login — run 'claude setup-token' (or 'claude login') once and keep
    the 'claude' CLI on PATH; do NOT set ANTHROPIC_API_KEY. To override keys, create a
    .env (see .env.example) or pass -Rebuild after editing config.

.PARAMETER Rebuild
    Force a full data rebuild even if data\_index.json already exists.

.PARAMETER Port
    Port for the local dashboard (default 8000).

.PARAMETER NoBrowser
    Don't auto-open the browser.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup.ps1
    powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Rebuild -Port 8080
#>
[CmdletBinding()]
param(
    [switch]$Rebuild,
    [int]$Port = 8000,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Info($msg) { Write-Host "  $msg" -ForegroundColor Gray }

Write-Host "PartnerPulse setup" -ForegroundColor Magenta
Write-Host "Working dir: $PSScriptRoot"

# ---------------------------------------------------------------------------
# 1. Ensure Python 3
# ---------------------------------------------------------------------------
Write-Step "Checking for Python 3"

function Resolve-Python {
    foreach ($cmd in @("python", "py -3")) {
        try {
            $parts = $cmd.Split(" ")
            $ver = & $parts[0] $parts[1..($parts.Length-1)] --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $ver -match "Python 3") { return $cmd }
        } catch { }
    }
    return $null
}

$py = Resolve-Python
if (-not $py) {
    Write-Info "Python 3 not found. Installing via winget…"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is not available. Please install Python 3.11+ from https://www.python.org/downloads/ and re-run this script."
    }
    winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements --silent
    # Refresh PATH for the current session from the registry.
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
    $py = Resolve-Python
    if (-not $py) {
        throw "Python installed but not on PATH yet. Close this window, open a NEW PowerShell, and re-run setup.ps1."
    }
}
$pyParts = $py.Split(" ")
Write-Ok ((& $pyParts[0] $pyParts[1..($pyParts.Length-1)] --version 2>&1) -join "")

# ---------------------------------------------------------------------------
# 2. Virtual environment + dependencies
# ---------------------------------------------------------------------------
Write-Step "Setting up virtual environment (.venv)"
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    & $pyParts[0] $pyParts[1..($pyParts.Length-1)] -m venv .venv
    Write-Ok "Created .venv"
} else {
    Write-Ok ".venv already exists"
}
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Step "Installing dependencies (this can take a few minutes)"
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
Write-Ok "Dependencies installed"

# ---------------------------------------------------------------------------
# 3. Optional .env scaffold (keys are already baked into config.py)
# ---------------------------------------------------------------------------
if (-not (Test-Path ".\.env") -and (Test-Path ".\.env.example")) {
    Write-Info "No .env found — using the API keys baked into extract\config.py."
    Write-Info "To override, copy .env.example to .env and edit it."
}

# ---------------------------------------------------------------------------
# 3b. Git hooks — enforce the docs-update SOP (docs/LLM-SOP.md) on every commit
# ---------------------------------------------------------------------------
if (Test-Path ".\.git") {
    git config core.hooksPath hooks
    Write-Ok "Git hooks enabled (core.hooksPath=hooks — pre-commit docs check)"
}

# ---------------------------------------------------------------------------
# 4. Build partner data + AI analysis
# ---------------------------------------------------------------------------
Write-Step "Building partner data + Claude churn analysis"
Write-Info "Claude churn analysis bills your Claude subscription — authenticate once with 'claude setup-token' (or 'claude login'); the 'claude' CLI must be on PATH. Do NOT set ANTHROPIC_API_KEY."
if ($Rebuild -or -not (Test-Path ".\data\_index.json")) {
    Write-Info "Running full build for all partners (live API calls + Claude — ~5 min)…"
    & $venvPy -m extract.build_all
    if ($LASTEXITCODE -ne 0) { throw "Data build failed. Check API keys / connectivity." }
    Write-Ok "All partner caches + portfolio index built"
} else {
    Write-Ok "data\_index.json already present — skipping rebuild (use -Rebuild to force)"
}

# ---------------------------------------------------------------------------
# 5. Launch dashboard
# ---------------------------------------------------------------------------
Write-Step "Starting local dashboard"
$url = "http://localhost:$Port/"
Write-Host "  Portfolio overview : $url" -ForegroundColor Yellow
Write-Host "  Press Ctrl+C to stop the server." -ForegroundColor Gray
if (-not $NoBrowser) { Start-Process $url }
& $venvPy server.py $Port
