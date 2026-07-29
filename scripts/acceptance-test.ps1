[CmdletBinding()]
param(
    [string]$SourceFolder = "",
    [switch]$KeepArtifacts,
    [string]$ExifToolPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$AcceptanceRoot = Join-Path $RepoRoot ".acceptance-artifacts"
$WorkRoot = Join-Path $AcceptanceRoot ([guid]::NewGuid().ToString("N"))
$Succeeded = $false
$GeneratedSource = -not $SourceFolder

function Assert-Condition {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-ArchiveNest {
    param([string[]]$Arguments)
    & $Python -m archive_nest @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "ArchiveNest exited with code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

function Invoke-ExifTool {
    param([string]$Target, [string[]]$Metadata)
    & $script:ExifTool -overwrite_original @Metadata $Target
    if ($LASTEXITCODE -ne 0) {
        throw "ExifTool failed for synthetic file: $Target"
    }
}

function Get-SourceSnapshot {
    param([string]$Root)
    $epochTicks = [DateTime]::UnixEpoch.Ticks
    return @(
        Get-ChildItem -LiteralPath $Root -File -Recurse |
            Sort-Object FullName |
            ForEach-Object {
                [pscustomobject]@{
                    relative_path = [IO.Path]::GetRelativePath($Root, $_.FullName)
                    size_bytes = $_.Length
                    sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
                    mtime_ns = ($_.LastWriteTimeUtc.Ticks - $epochTicks) * 100
                }
            }
    )
}

function Assert-SourceUnchanged {
    param([string]$Stage)
    $after = Get-SourceSnapshot $script:Source
    $afterJson = $after | ConvertTo-Json -Depth 3 -Compress
    if ($afterJson -cne $script:BeforeJson) {
        throw "Source changed after $Stage"
    }
    Write-Host "[source unchanged] $Stage"
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Virtual environment not found. Run scripts\setup.ps1 first."
}

New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null
try {
    if ($SourceFolder) {
        $Source = (Resolve-Path -LiteralPath $SourceFolder).Path
        Assert-Condition (Test-Path -LiteralPath $Source -PathType Container) `
            "SourceFolder must be an existing directory."
    } else {
        $Source = Join-Path $WorkRoot "synthetic-source"
        New-Item -ItemType Directory -Path $Source | Out-Null
    }
    $script:Source = $Source

    if ($ExifToolPath) {
        $ExifTool = (Resolve-Path -LiteralPath $ExifToolPath).Path
    } else {
        $ExifTool = Get-ChildItem `
            -LiteralPath (Join-Path $RepoRoot ".tools\exiftool") `
            -Filter "exiftool.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1 -ExpandProperty FullName
        if (-not $ExifTool) {
            $command = Get-Command exiftool.exe -ErrorAction SilentlyContinue
            if ($command) {
                $ExifTool = $command.Source
            }
        }
    }
    Assert-Condition ([bool]$ExifTool) `
        "ExifTool was not found. Pass -ExifToolPath or place it under .tools\exiftool."
    $script:ExifTool = $ExifTool
    $ExifVersion = & $ExifTool -ver
    if ($LASTEXITCODE -ne 0 -or -not $ExifVersion) {
        throw "ExifTool could not be executed: $ExifTool"
    }
    Write-Host "ExifTool ${ExifVersion}: $ExifTool"

    if ($GeneratedSource) {
        $jpegFixture = Join-Path $RepoRoot "tests\input\exif.jpg"
        $videoFixture = Join-Path $RepoRoot "tests\input\exif.mp4"
        foreach ($directory in @(
            "month-a", "month-b", "collision-a", "collision-b",
            "duplicates", "unknown", "video", "live"
        )) {
            New-Item -ItemType Directory -Path (Join-Path $Source $directory) |
                Out-Null
        }

        $january = Join-Path $Source "month-a\EXIF photo.jpg"
        Copy-Item -LiteralPath $jpegFixture -Destination $january
        Invoke-ExifTool $january @(
            "-EXIF:DateTimeOriginal=2024:01:02 03:04:05",
            "-EXIF:OffsetTimeOriginal=+09:00"
        )

        $february = Join-Path $Source "month-b\日本語 写真.jpg"
        $februaryTemplate = Join-Path $WorkRoot "japanese-name-template.jpg"
        Copy-Item -LiteralPath $jpegFixture -Destination $februaryTemplate
        Invoke-ExifTool $februaryTemplate @(
            "-EXIF:DateTimeOriginal=2024:02:03 04:05:06"
        )
        Copy-Item -LiteralPath $februaryTemplate -Destination $february

        $collisionOne = Join-Path $Source "collision-a\same-name.jpg"
        $collisionTwo = Join-Path $Source "collision-b\same-name.jpg"
        Copy-Item -LiteralPath $jpegFixture -Destination $collisionOne
        Copy-Item -LiteralPath $jpegFixture -Destination $collisionTwo
        Invoke-ExifTool $collisionOne @(
            "-EXIF:DateTimeOriginal=2024:03:01 01:02:03",
            "-Comment=first collision"
        )
        Invoke-ExifTool $collisionTwo @(
            "-EXIF:DateTimeOriginal=2024:03:02 01:02:03",
            "-Comment=second collision"
        )

        $duplicateOriginal = Join-Path $Source "duplicates\original.jpg"
        Copy-Item -LiteralPath $jpegFixture -Destination $duplicateOriginal
        Invoke-ExifTool $duplicateOriginal @(
            "-EXIF:DateTimeOriginal=2024:04:05 06:07:08"
        )
        Copy-Item -LiteralPath $duplicateOriginal `
            -Destination (Join-Path $Source "duplicates\別名 duplicate.jpg")

        Set-Content -LiteralPath (Join-Path $Source "unknown\unknown.jpg") `
            -Value "synthetic invalid JPEG without a date" -Encoding UTF8
        Copy-Item -LiteralPath (Join-Path $RepoRoot "tests\input\xmp.jpg.xmp") `
            -Destination "$january.xmp"

        $video = Join-Path $Source "video\metadata video.mp4"
        Copy-Item -LiteralPath $videoFixture -Destination $video
        Invoke-ExifTool $video @("-QuickTime:CreateDate=2024:05:06 07:08:09")

        $livePhoto = Join-Path $Source "live\IMG_20240607_080910.HEIC"
        $liveVideo = Join-Path $Source "live\IMG_20240607_080910.MOV"
        Set-Content -LiteralPath $livePhoto `
            -Value "synthetic HEIC placeholder for filename-date grouping" `
            -Encoding UTF8
        Copy-Item -LiteralPath $videoFixture -Destination $liveVideo
        Invoke-ExifTool $liveVideo @(
            "-Keys:CreationDate=2024:06:07 08:09:10+09:00"
        )
        Set-Content -LiteralPath `
            (Join-Path $Source "live\IMG_20240607_080910.AAE") `
            -Value "<synthetic-adjustment />" -Encoding UTF8
    }

    $Before = Get-SourceSnapshot $Source
    Assert-Condition ($Before.Count -gt 0) "Acceptance source contains no files."
    $BeforePath = Join-Path $WorkRoot "source-before.json"
    $Before | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $BeforePath `
        -Encoding UTF8
    $script:BeforeJson = $Before | ConvertTo-Json -Depth 3 -Compress

    $env:LOCALAPPDATA = Join-Path $WorkRoot "local-app-data"
    $ExifArguments = @("--exiftool", $ExifTool)
    $ScanDestination = Join-Path $WorkRoot "scan-output"
    $DryRunDestination = Join-Path $WorkRoot "dry-run-output"
    $Archive = Join-Path $WorkRoot "archive"
    $Staging = Join-Path $WorkRoot "staging"

    Invoke-ArchiveNest (@(
        "scan", "--source", $Source, "--destination", $ScanDestination
    ) + $ExifArguments)
    Assert-SourceUnchanged "pre-scan"

    Invoke-ArchiveNest (@(
        "organize", "--source", $Source, "--destination", $DryRunDestination,
        "--dry-run"
    ) + $ExifArguments)
    Assert-Condition (
        (Test-Path -LiteralPath (Join-Path $DryRunDestination "manifest.json"))
    ) "Dry-run manifest is missing."
    Assert-SourceUnchanged "dry-run"

    Invoke-ArchiveNest (@(
        "organize", "--source", $Source, "--destination", $Archive
    ) + $ExifArguments)
    Assert-SourceUnchanged "copy and post-copy SHA-256 verification"

    foreach ($relative in @(
        "manifest.json", "SHA256SUMS.txt", "reports\files.csv",
        "reports\summary.html", "reports\duplicates.csv",
        "reports\unknown_dates.csv"
    )) {
        Assert-Condition (Test-Path -LiteralPath (Join-Path $Archive $relative)) `
            "Required acceptance artifact is missing: $relative"
    }
    $FirstManifest = Get-Content -LiteralPath (Join-Path $Archive "manifest.json") `
        -Raw | ConvertFrom-Json
    if ($GeneratedSource) {
        Assert-Condition (
            @($FirstManifest.files | Where-Object status -eq "skipped_duplicate").Count -ge 1
        ) "A complete duplicate was not skipped."
        Assert-Condition (
            @($FirstManifest.files | Where-Object {
                $_.destination_relative_path -match "__[0-9a-f]{8}"
            }).Count -ge 1
        ) "A same-name collision was not safely renamed."
        Assert-Condition (
            @($FirstManifest.files | Where-Object {
                $_.destination_relative_path -like "_unknown_date/*"
            }).Count -ge 1
        ) "An unknown-date file was not placed under _unknown_date."
    }

    Invoke-ArchiveNest @("verify", "--archive", $Archive)
    Assert-SourceUnchanged "archive verification"

    Invoke-ArchiveNest (@(
        "organize", "--source", $Source, "--destination", $Archive
    ) + $ExifArguments)
    $SecondManifest = Get-Content -LiteralPath (Join-Path $Archive "manifest.json") `
        -Raw | ConvertFrom-Json
    Assert-Condition (
        @($SecondManifest.files | Where-Object status -eq "already_verified").Count -ge 1
    ) "Rerun did not report already_verified."
    Assert-SourceUnchanged "rerun"

    Invoke-ArchiveNest @(
        "plan-disc", "--archive", $Archive, "--capacity-bytes", "5000",
        "--staging", $Staging
    )
    Assert-Condition (
        Test-Path -LiteralPath (Join-Path $Archive "reports\disc-plan.json")
    ) "M-DISC plan is missing."
    $StageRoot = Join-Path $Staging "mdisc_staging"
    $StageSums = Get-ChildItem -LiteralPath $StageRoot `
        -Filter "SHA256SUMS.txt" -File -Recurse
    Assert-Condition ($StageSums.Count -gt 0) "Staging checksum files are missing."
    foreach ($sumFile in $StageSums) {
        foreach ($line in Get-Content -LiteralPath $sumFile.FullName) {
            if ($line -notmatch "^([0-9a-fA-F]{64}) \*(.+)$") {
                throw "Invalid staging checksum line: $line"
            }
            $stagedFile = Join-Path $sumFile.Directory.FullName $Matches[2]
            Assert-Condition (Test-Path -LiteralPath $stagedFile -PathType Leaf) `
                "Staged file is missing: $stagedFile"
            $actual = (Get-FileHash -LiteralPath $stagedFile -Algorithm SHA256).Hash
            Assert-Condition ($actual -eq $Matches[1]) `
                "Staging SHA-256 mismatch: $stagedFile"
        }
    }
    Assert-SourceUnchanged "M-DISC staging"

    & $Python -m pytest -q --basetemp (Join-Path $WorkRoot "pytest-faults") `
        "tests/test_archive_nest.py::test_source_unchanged_after_failures_resume_rerun_and_staging" `
        "tests/test_archive_nest.py::test_path_safety_rejects_equal_and_containment"
    if ($LASTEXITCODE -ne 0) {
        throw "Fault-injection or nested-path acceptance tests failed."
    }

    $After = Get-SourceSnapshot $Source
    $After | ConvertTo-Json -Depth 3 | Set-Content `
        -LiteralPath (Join-Path $WorkRoot "source-after.json") -Encoding UTF8
    Assert-SourceUnchanged "all acceptance operations"
    $Succeeded = $true
    Write-Host "ACCEPTANCE PASSED"
    Write-Host "Artifacts: $WorkRoot"
} finally {
    if ($Succeeded -and -not $KeepArtifacts) {
        $resolvedAcceptance = [IO.Path]::GetFullPath($AcceptanceRoot)
        $resolvedWork = [IO.Path]::GetFullPath($WorkRoot)
        if (-not $resolvedWork.StartsWith(
            $resolvedAcceptance + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Refusing to remove an unexpected path: $resolvedWork"
        }
        Remove-Item -LiteralPath $resolvedWork -Recurse -Force
        Write-Host "Generated acceptance artifacts removed."
    } elseif (-not $Succeeded) {
        Write-Host "Acceptance failed; artifacts retained for diagnosis: $WorkRoot"
    }
}
