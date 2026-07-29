$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$Targets = @(
    (Join-Path $RepoRoot "build"),
    (Join-Path $RepoRoot "dist")
)
foreach ($Target in $Targets) {
    $Full = [System.IO.Path]::GetFullPath($Target)
    if (-not $Full.StartsWith($RepoRoot + [System.IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing to clean outside repository: $Full"
    }
    if (Test-Path -LiteralPath $Full) {
        Remove-Item -LiteralPath $Full -Recurse -Force
        Write-Host "Removed $Full"
    }
}
