# ShipMate setup script for Windows PowerShell
$ErrorActionPreference = "Stop"

Write-Host "Setting up ShipMate..." -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3.10+ is required. Install from https://python.org"
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

Write-Host "Installing dependencies..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements.txt

Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host "Activate:  .\.venv\Scripts\Activate.ps1"
Write-Host "Run app:   python start.py"
Write-Host "Run tests: python -m pytest tests/"
