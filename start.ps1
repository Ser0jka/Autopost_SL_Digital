#Requires -Version 5.1
param(
    [switch]$NoRestart
)

Set-Location $PSScriptRoot
$Host.UI.RawUI.WindowTitle = "Dima Bot"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Step($message) { Write-Host "[INFO] $message" -ForegroundColor Cyan }
function Ok($message) { Write-Host "[OK]   $message" -ForegroundColor Green }
function Fail($message) { Write-Host "[ERR]  $message" -ForegroundColor Red }
function Warn($message) { Write-Host "[WARN] $message" -ForegroundColor Yellow }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Step "Virtual environment not found. Running setup..."
    & "$PSScriptRoot\setup.ps1"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not (Test-Path ".env")) {
    Fail ".env not found. Run setup.ps1 and fill environment variables."
    Read-Host "Press Enter to exit"
    exit 1
}

New-Item -ItemType Directory -Force "data\images" | Out-Null

Step "Starting bot..."
while ($true) {
    & .venv\Scripts\python.exe main.py
    $code = $LASTEXITCODE

    if ($code -eq 0 -or $NoRestart) {
        break
    }

    Warn "Bot exited with code $code. Restarting in 5 seconds. Press Ctrl+C to stop."
    Start-Sleep -Seconds 5
}

Ok "Bot stopped"
