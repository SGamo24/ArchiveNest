from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from archive_nest.metadata.dates import decide_capture_date
from archive_nest.metadata.exiftool import ExifTool

pytestmark = pytest.mark.exiftool

FIXTURES = Path(__file__).parent / "input"


@pytest.fixture
def real_exiftool() -> ExifTool:
    tool = ExifTool()
    if not tool.available:
        pytest.skip("real ExifTool executable is not available")
    assert tool.version()
    return tool


def _write_metadata(tool: ExifTool, path: Path, *arguments: str) -> None:
    result = subprocess.run(
        [
            str(tool.path),
            "-overwrite_original",
            *arguments,
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_real_exiftool_reads_jpeg_original_date_with_timezone(
    tmp_path: Path, real_exiftool: ExifTool
) -> None:
    photo = tmp_path / "日本語 photo.jpg"
    shutil.copy2(FIXTURES / "exif.jpg", photo)
    _write_metadata(
        real_exiftool,
        photo,
        "-EXIF:DateTimeOriginal=2024:03:04 05:06:07",
        "-EXIF:CreateDate=2023:02:03 04:05:06",
        "-EXIF:OffsetTimeOriginal=+09:00",
        "-XMP:CreateDate=2022:01:02 03:04:05Z",
    )

    metadata, error = real_exiftool.extract(photo)
    assert not error
    decision = decide_capture_date(photo, "photo", metadata)
    assert decision.value == datetime.fromisoformat("2024-03-04T05:06:07+09:00")
    assert decision.field == "Composite:SubSecDateTimeOriginal"
    assert decision.timezone == "+0900"


def test_real_exiftool_reads_xmp_sidecar_date(
    tmp_path: Path, real_exiftool: ExifTool
) -> None:
    source = tmp_path / "source.jpg"
    sidecar = tmp_path / "source.jpg.xmp"
    shutil.copy2(FIXTURES / "exif.jpg", source)
    result = subprocess.run(
        [
            str(real_exiftool.path),
            "-o",
            str(sidecar),
            "-XMP:CreateDate=2020:11:12 13:14:15+01:00",
            str(source),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    _write_metadata(
        real_exiftool,
        sidecar,
        "-XMP:CreateDate=2020:11:12 13:14:15+01:00",
    )

    metadata, error = real_exiftool.extract(sidecar)
    assert not error
    decision = decide_capture_date(sidecar, "photo", metadata)
    assert decision.value == datetime.fromisoformat("2020-11-12T13:14:15+01:00")
    assert decision.field.endswith(":CreateDate")
    assert decision.timezone == "+0100"


@pytest.mark.parametrize(
    ("extension", "arguments", "expected"),
    [
        (
            ".mp4",
            (
                "-QuickTime:CreateDate=2021:04:05 06:07:08",
                "-XMP:CreateDate=2019:01:01 00:00:00+01:00",
            ),
            datetime(2021, 4, 5, 6, 7, 8),
        ),
        (
            ".mov",
            (
                "-Keys:CreationDate=2024:07:08 09:10:11+09:00",
                "-QuickTime:CreateDate=2022:01:02 03:04:05",
            ),
            datetime.fromisoformat("2024-07-08T09:10:11+09:00"),
        ),
    ],
)
def test_real_exiftool_reads_quicktime_dates_and_priority(
    tmp_path: Path,
    real_exiftool: ExifTool,
    extension: str,
    arguments: tuple[str, ...],
    expected: datetime,
) -> None:
    video = tmp_path / f"synthetic video{extension}"
    shutil.copy2(FIXTURES / "exif.mp4", video)
    _write_metadata(real_exiftool, video, *arguments)

    metadata, error = real_exiftool.extract(video)
    assert not error
    decision = decide_capture_date(video, "video", metadata)
    assert decision.value == expected
    assert decision.source == "metadata"
    assert decision.timezone == (
        expected.strftime("%z") if expected.tzinfo else ""
    )
