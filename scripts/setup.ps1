param(
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    if ($PythonExecutable) {
        & $PythonExecutable -m venv $VenvPath
    } else {
        $Launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($Launcher) {
        & $Launcher.Source -3 -m venv $VenvPath
        } else {
            $Python = Get-Command python -ErrorAction Stop
            & $Python.Source -m venv $VenvPath
        }
    }
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed with exit code $LASTEXITCODE"
}
& $VenvPython -m pip install -e "$RepoRoot[dev,gui,build]"
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed with exit code $LASTEXITCODE"
}

$ExifTool = Get-Command exiftool -ErrorAction SilentlyContinue
if ($ExifTool) {
    $ExifVersion = & $ExifTool.Source -ver
    Write-Host "ExifTool: $($ExifTool.Source) (version $ExifVersion)"
} else {
    Write-Warning "ExifTool was not found. Setup is complete; filename-date fallback remains available."
}

Write-Host "ArchiveNest environment ready: $VenvPython"
