$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path ".venv")) {
  py -3 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PYTHONPATH = Join-Path (Get-Location) "backend"
& .\.venv\Scripts\python.exe scripts\start.py
