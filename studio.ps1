# Launcher for Windows (PowerShell): installs `uv` if needed, then runs studio.py with Python 3.11.
#   .\studio.ps1 setup | run | doctor | generate ... | benchmark | eval | vendor | test
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv (Python package manager)..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
uv run --python 3.11 studio.py @args
