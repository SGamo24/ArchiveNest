$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run scripts\setup.ps1 first."
}
$BaseTemp = Join-Path $RepoRoot ".pytest-tmp"
& $Python -m pytest --basetemp $BaseTemp
exit $LASTEXITCODE
