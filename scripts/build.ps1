$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run scripts\setup.ps1 first."
}
Push-Location $RepoRoot
try {
    $BuildStarted = Get-Date
    $Exe = Join-Path $RepoRoot "dist\ArchiveNest\ArchiveNest.exe"
    $PreviousHash = if (Test-Path -LiteralPath $Exe -PathType Leaf) {
        (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash
    } else {
        ""
    }
    & $Python -m PyInstaller --noconfirm ArchiveNest.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $Exe)) {
        throw "Build completed without the expected executable: $Exe"
    }
    if ((Get-Item -LiteralPath $Exe).LastWriteTime -lt $BuildStarted.AddSeconds(-2)) {
        throw "Expected executable predates this build; refusing to report stale output."
    }
    foreach ($relative in @(
        "_internal\LICENSE", "_internal\THIRD_PARTY_NOTICES.md",
        "_internal\README.md",
        "_internal\PySide6\plugins\platforms\qwindows.dll"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path (Split-Path $Exe) $relative))) {
            throw "Build is missing required distribution file: $relative"
        }
    }
    if (Get-ChildItem -LiteralPath (Split-Path $Exe) -File -Recurse |
        Where-Object Name -Like "exiftool*") {
        throw "ExifTool must not be bundled in the ArchiveNest distribution."
    }
    $CurrentHash = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash
    Write-Host "ArchiveNest build: $Exe"
    Write-Host "SHA-256: $CurrentHash"
    if ($PreviousHash) {
        Write-Host "Previous SHA-256: $PreviousHash"
    }
} finally {
    Pop-Location
}
