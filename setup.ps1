#Requires -Version 5.1
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Step($message) { Write-Host "[INFO] $message" -ForegroundColor Cyan }
function Ok($message) { Write-Host "[OK]   $message" -ForegroundColor Green }
function Fail($message) { Write-Host "[ERR]  $message" -ForegroundColor Red }
function Warn($message) { Write-Host "[WARN] $message" -ForegroundColor Yellow }
function Find-Python {
    $commands = @("python", "py")
    foreach ($command in $commands) {
        $found = Get-Command $command -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }

    $codexPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path $codexPython) { return $codexPython }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    Fail "Python 3.10+ is required. Install it from https://python.org"
    Read-Host "Press Enter to exit"
    exit 1
}
$pythonVersion = & $Python --version 2>&1
Ok "Python found: $pythonVersion ($Python)"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Step "Creating virtual environment..."
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not create virtual environment"
        Read-Host "Press Enter to exit"
        exit 1
    }
}
Ok "Virtual environment is ready"

Step "Installing dependencies..."
& .venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Fail "Dependency installation failed"
    Read-Host "Press Enter to exit"
    exit 1
}
Ok "Dependencies installed"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Warn ".env was created from .env.example. Fill it with real tokens before starting the bot."
}

New-Item -ItemType Directory -Force "data\images" | Out-Null
Ok "Data directories are ready"

Write-Host ""
Ok "Setup complete"
Write-Host "Next steps:"
Write-Host "1. Fill .env if needed"
Write-Host "2. Run: .venv\Scripts\python.exe scripts\login_telethon.py"
Write-Host "3. Run: .\start.ps1"
