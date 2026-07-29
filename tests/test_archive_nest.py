from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from archive_nest.application.disc_plan_service import DiscPlanService
from archive_nest.application.organize_service import OrganizeService
from archive_nest.application.resume_service import ResumeService
from archive_nest.application.scan_service import ScanService
from archive_nest.application.verify_service import VerifyService
from archive_nest.cancellation import CancellationToken, CancelledError
from archive_nest.cli import EXIT_USAGE, build_parser, main
from archive_nest.config import ArchiveConfig, ConfigStore
from archive_nest.copying.safe_copy import (CopyVerificationError,
                                            copy_and_verify)
from archive_nest.disc import create_staging, plan_discs
from archive_nest.disc.planner import load_archive_items
from archive_nest.domain.models import DateDecision, DiscItem, FileRecord
from archive_nest.grouping import assign_groups
from archive_nest.hashing import sha256_file, sha256_stream
from archive_nest.metadata.dates import decide_capture_date
from archive_nest.metadata.exiftool import ExifTool
from archive_nest.persistence import SessionStore
from archive_nest.planning import build_copy_plan
from archive_nest.safety import PathSafetyError, normalize_path, validate_paths


class MetadataStub:
    available = True
    path = Path("stub-exiftool")

    def __init__(self, mapping=None, error=""):
        self.mapping = mapping or {}
        self.error = error

    def extract(self, path, **_kwargs):
        return self.mapping.get(path.name, {}), self.error

    def version(self):
        return "stub"


def make_config(**overrides):
    values = {
        "include_subfolders": True,
        "output_format": "%Y/%Y-%m",
        "use_file_mtime": False,
    }
    values.update(overrides)
    return ArchiveConfig(**values)


def test_streaming_sha256_uses_chunks(tmp_path):
    path = tmp_path / "large.bin"
    data = b"0123456789" * 100_000
    path.write_bytes(data)
    assert sha256_file(path, chunk_size=997) == hashlib.sha256(data).hexdigest()
    with path.open("rb") as stream:
        assert sha256_stream(stream, chunk_size=113) == hashlib.sha256(data).hexdigest()


def test_dates_metadata_filename_invalid_future_and_mtime(tmp_path):
    path = tmp_path / "IMG_20240203_040506.jpg"
    path.write_bytes(b"x")
    metadata = {"EXIF:DateTimeOriginal": "2020:01:02 03:04:05+09:00"}
    decision = decide_capture_date(path, "photo", metadata)
    assert decision.value == datetime.fromisoformat("2020-01-02T03:04:05+09:00")
    assert decision.confidence == "high"
    assert decision.timezone == "+0900"

    filename = decide_capture_date(path, "photo", {})
    assert filename.value == datetime(2024, 2, 3, 4, 5, 6)
    assert filename.source == "filename"

    invalid = tmp_path / "IMG_20240231_040506.jpg"
    invalid.write_bytes(b"x")
    assert decide_capture_date(invalid, "photo", {}).value is None

    future = tmp_path / "IMG_29990101_000000.jpg"
    future.write_bytes(b"x")
    assert decide_capture_date(future, "photo", {}).value is None

    unknown = tmp_path / "plain.jpg"
    unknown.write_bytes(b"x")
    assert decide_capture_date(unknown, "photo", {}).value is None
    assert decide_capture_date(unknown, "photo", {}, use_file_mtime=True).source == "filesystem"


def test_video_metadata_priority_and_naive_timezone(tmp_path):
    path = tmp_path / "clip.mov"
    path.write_bytes(b"x")
    decision = decide_capture_date(
        path,
        "video",
        {
            "XMP:CreateDate": "2019:01:01 00:00:00",
            "QuickTime:CreationDate": "2021:04:05 06:07:08",
        },
    )
    assert decision.value == datetime(2021, 4, 5, 6, 7, 8)
    assert decision.value.tzinfo is None
    assert decision.timezone == ""


def test_config_corruption_falls_back_and_round_trips(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    store = ConfigStore(path)
    assert store.load().output_format == "%Y/%Y-%m"
    config = ArchiveConfig(last_source="日本語", use_file_mtime=True)
    store.save(config)
    assert store.load().last_source == "日本語"
    assert store.load().use_file_mtime


def test_path_safety_rejects_equal_and_containment(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(PathSafetyError):
        validate_paths(source, source)
    with pytest.raises(PathSafetyError):
        validate_paths(source, source / "output")
    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(PathSafetyError):
        validate_paths(destination / "nested", destination)


def test_path_safety_normalizes_alternate_spelling(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    assert normalize_path(source / ".." / "source") == normalize_path(source)


def test_path_safety_rejects_known_capacity_shortage(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    monkeypatch.setattr(
        "archive_nest.safety.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=100, used=100, free=0),
    )
    with pytest.raises(PathSafetyError, match="insufficient"):
        validate_paths(source, destination, required_bytes=1)


def test_scan_classifies_hashes_groups_and_never_writes_source(tmp_path):
    source = tmp_path / "元 写真"
    destination = tmp_path / "整理先"
    source.mkdir()
    nested = source / "子"
    nested.mkdir()
    photo = nested / "IMG_20240102_030405.HEIC"
    video = nested / "IMG_20240102_030405.MOV"
    sidecar = nested / "IMG_20240102_030405.AAE"
    unsupported = nested / "notes.txt"
    duplicate = nested / "copy.jpg"
    photo.write_bytes(b"photo")
    video.write_bytes(b"video")
    sidecar.write_bytes(b"sidecar")
    unsupported.write_bytes(b"notes")
    duplicate.write_bytes(b"photo")
    before = {
        path.relative_to(source).as_posix(): (
            path.read_bytes(),
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
        for path in source.rglob("*")
        if path.is_file()
    }
    result = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config()
    )
    assert result.summary.total_files == 5
    assert result.summary.photos == 2
    assert result.summary.videos == 1
    assert result.summary.sidecars == 1
    assert result.summary.unsupported == 1
    assert result.summary.duplicate_candidates == 1
    grouped = [record for record in result.records if record.group_id]
    assert len(grouped) == 3
    assert len({record.group_id for record in grouped}) == 1
    assert not any(path.name not in {p.name for p in source.rglob("*")} for path in source.iterdir())
    after = {
        path.relative_to(source).as_posix(): (
            path.read_bytes(),
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
        for path in source.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_scan_no_subfolders(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "top.jpg").write_bytes(b"top")
    nested = source / "nested"
    nested.mkdir()
    (nested / "inside.jpg").write_bytes(b"inside")
    result = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config(include_subfolders=False)
    )
    assert [record.source_filename for record in result.records] == ["top.jpg"]


def test_reparse_point_not_followed_when_supported(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    outside = tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    (outside / "private.jpg").write_bytes(b"private")
    link = source / "junction"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating a symlink requires privileges on this Windows host")
    result = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config()
    )
    assert result.summary.reparse_points == 1
    assert all(record.source_filename != "private.jpg" for record in result.records)


def test_deterministic_duplicate_and_collision_planning(tmp_path):
    destination = tmp_path / "destination"
    destination.mkdir()
    records = []
    for relative, content in (
        ("b/IMG.jpg", b"same"),
        ("a/other.jpg", b"same"),
        ("a/IMG.jpg", b"different"),
        ("c/IMG.jpg", b"third"),
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        record = FileRecord(
            path,
            Path(relative),
            len(content),
            path.stat().st_mtime_ns,
            "photo",
            sha256_file(path),
        )
        record.date = decide_capture_date(
            Path("IMG_20240101_010101.jpg"), "photo", {}
        )
        records.append(record)
    build_copy_plan(records, destination)
    duplicate = next(record for record in records if record.source_relative_path.as_posix() == "b/IMG.jpg")
    assert duplicate.status == "skipped_duplicate"
    assert duplicate.duplicate_of == "a/other.jpg"
    planned = [record for record in records if record.status == "planned"]
    assert len({record.destination_relative_path.as_posix() for record in planned}) == 3
    assert any("__" in record.destination_relative_path.name for record in planned)


def test_copy_and_verify_success_preserves_source(tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "archive" / "source.bin"
    source.write_bytes(os.urandom(2_000_000))
    before = (source.read_bytes(), source.stat().st_size, source.stat().st_mtime_ns)
    digest = sha256_file(source)
    copy_and_verify(source, destination, digest, session_id="test", chunk_size=32_771)
    assert destination.read_bytes() == source.read_bytes()
    assert sha256_file(destination) == digest
    assert before == (source.read_bytes(), source.stat().st_size, source.stat().st_mtime_ns)
    assert not list(destination.parent.glob("*.partial"))


def test_copy_mismatch_retains_partial_and_does_not_publish(tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "out" / "source.bin"
    source.write_bytes(b"content")
    with pytest.raises(CopyVerificationError):
        copy_and_verify(source, destination, "0" * 64, session_id="mismatch")
    assert not destination.exists()
    assert (destination.parent / "source.bin.mismatch.partial").is_file()


def test_copy_cancellation_retains_partial(tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "out" / "source.bin"
    source.write_bytes(b"x" * 100)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError):
        copy_and_verify(
            source,
            destination,
            sha256_file(source),
            session_id="cancel",
            cancellation=token,
            chunk_size=10,
        )
    assert not destination.exists()
    assert (destination.parent / "source.bin.cancel.partial").exists()


def test_copy_never_overwrites_existing(tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "out" / "source.bin"
    source.write_bytes(b"new")
    destination.parent.mkdir()
    destination.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        copy_and_verify(source, destination, sha256_file(source), session_id="overwrite")
    assert destination.read_bytes() == b"old"


def test_copy_write_failure_never_publishes_destination(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    destination = tmp_path / "out" / "source.bin"
    source.write_bytes(b"new")
    monkeypatch.setattr(
        "archive_nest.copying.safe_copy.os.fsync",
        lambda _descriptor: (_ for _ in ()).throw(OSError("destination disconnected")),
    )
    with pytest.raises(OSError, match="disconnected"):
        copy_and_verify(
            source, destination, sha256_file(source), session_id="disconnect"
        )
    assert not destination.exists()
    assert (destination.parent / "source.bin.disconnect.partial").exists()


def test_organize_dry_run_reports_without_media(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "IMG_20240102_030405.jpg").write_bytes(b"photo")
    result = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config()
    )
    OrganizeService().organize(result, dry_run=True)
    assert not (destination / "2024" / "2024-01" / "IMG_20240102_030405.jpg").exists()
    assert (destination / "manifest.json").is_file()
    assert (destination / "reports" / "summary.html").is_file()
    assert (destination / "reports" / "files.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_organize_verify_rerun_and_reports(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    original = source / "日本語 IMG_20240102_030405.JPG"
    original.write_bytes(b"photo")
    before = (original.read_bytes(), original.stat().st_size, original.stat().st_mtime_ns)
    result = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config()
    )
    OrganizeService().organize(result)
    assert result.summary.verified == 1
    assert before == (original.read_bytes(), original.stat().st_size, original.stat().st_mtime_ns)
    sums = (destination / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert sha256_file(original) in sums
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"][0]["status"] == "verified"
    second = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config()
    )
    assert second.records[0].status == "already_verified"
    OrganizeService().organize(second)
    assert len(list((destination / "2024" / "2024-01").glob("*.JPG"))) == 1


def test_collision_is_already_verified_on_rerun(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    for directory, content in (("a", b"first"), ("b", b"second")):
        folder = source / directory
        folder.mkdir()
        (folder / "IMG_20240102_030405.jpg").write_bytes(content)

    first = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config()
    )
    OrganizeService().organize(first)
    assert sum(record.collision for record in first.records) == 1

    second = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config()
    )
    assert {record.status for record in second.records} == {"already_verified"}
    OrganizeService().organize(second)
    assert len(list((destination / "2024" / "2024-01").glob("*.jpg"))) == 2


def test_existing_unmanifested_file_is_not_treated_as_verified(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    media = source / "IMG_20240102_030405.jpg"
    media.write_bytes(b"same")
    existing = destination / "2024" / "2024-01" / media.name
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"same")
    result = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config()
    )
    assert result.records[0].status == "planned"
    assert result.records[0].collision
    assert "__" in result.records[0].destination_relative_path.name


def test_unknown_date_goes_to_unknown_directory(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "plain.jpg").write_bytes(b"photo")
    result = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config()
    )
    OrganizeService().organize(result)
    assert (destination / "_unknown_date" / "plain.jpg").is_file()


def test_reports_are_valid_and_external_resource_free(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "IMG_20240102_030405.jpg").write_bytes(b"photo")
    result = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config()
    )
    OrganizeService().organize(result)
    json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    html_text = (destination / "reports" / "summary.html").read_text(encoding="utf-8")
    assert "http://" not in html_text
    assert "https://" not in html_text
    with (destination / "reports" / "files.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        row = next(csv.DictReader(stream))
    assert row["status"] == "verified"
    assert row["date_source"] == "filename"


def test_copy_error_still_generates_error_report(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "IMG_20240102_030405.jpg").write_bytes(b"photo")
    result = ScanService(metadata_tool=MetadataStub()).scan(
        source, destination, make_config()
    )
    monkeypatch.setattr(
        "archive_nest.application.organize_service.copy_and_verify",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    OrganizeService().organize(result)
    assert result.summary.failed == 1
    errors = (destination / "reports" / "errors.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "disk full" in errors


def test_archive_verification_detects_hash_missing_and_added(tmp_path):
    source = tmp_path / "source"
    archive = tmp_path / "archive"
    source.mkdir()
    (source / "IMG_20240102_030405.jpg").write_bytes(b"photo")
    result = ScanService(metadata_tool=MetadataStub()).scan(
        source, archive, make_config()
    )
    OrganizeService().organize(result)
    verified = VerifyService().verify(archive)
    assert verified.ok
    copied = archive / result.records[0].destination_relative_path
    copied.write_bytes(b"changed")
    (archive / "added.bin").write_bytes(b"added")
    failed = VerifyService().verify(archive)
    assert not failed.ok
    assert failed.items[0].status == "size_mismatch"
    assert failed.added_files == ["added.bin"]
    copied.unlink()
    missing = VerifyService().verify(archive)
    assert missing.items[0].status == "missing"


def test_disc_plan_capacity_grouping_and_determinism():
    items = [
        DiscItem("2024/a.jpg", 6, "a", "live"),
        DiscItem("2024/a.mov", 3, "b", "live"),
        DiscItem("2024/b.jpg", 4, "c"),
        DiscItem("2024/c.jpg", 12, "d"),
    ]
    first = plan_discs(items, 10)
    second = plan_discs(list(reversed(items)), 10)
    assert [[item.relative_path for item in volume.items] for volume in first] == [
        [item.relative_path for item in volume.items] for volume in second
    ]
    assert {item.relative_path for item in first[0].items} == {"2024/a.jpg", "2024/a.mov"}
    assert any(volume.oversized for volume in first)
    assert all(volume.used_bytes <= 10 or volume.oversized for volume in first)


def test_disc_plan_and_staging_are_verified(tmp_path):
    source = tmp_path / "source"
    archive = tmp_path / "archive"
    staging_parent = tmp_path / "stage"
    source.mkdir()
    (source / "IMG_20240102_030405.jpg").write_bytes(b"photo")
    result = ScanService(metadata_tool=MetadataStub()).scan(
        source, archive, make_config()
    )
    OrganizeService().organize(result)
    service = DiscPlanService()
    volumes = service.plan(archive, 1_000_000)
    assert (archive / "reports" / "disc-plan.json").is_file()
    root = create_staging(archive, staging_parent, volumes)
    volume = root / "M_DISC_001"
    assert (volume / "README.txt").is_file()
    assert (volume / "FILES.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert (volume / "SHA256SUMS.txt").is_file()
    item = load_archive_items(archive)[0]
    assert sha256_file(volume / item.relative_path) == item.sha256


def test_grouping_does_not_force_unrelated_same_name_across_directories(tmp_path):
    records = []
    for directory, kind, extension in (
        ("a", "photo", ".jpg"),
        ("b", "video", ".mov"),
    ):
        path = tmp_path / directory / f"IMG_1{extension}"
        path.parent.mkdir()
        path.write_bytes(b"x")
        records.append(
            FileRecord(
                path,
                Path(directory) / path.name,
                1,
                path.stat().st_mtime_ns,
                kind,
            )
        )
    assign_groups(records)
    assert not any(record.group_id for record in records)


def test_common_asset_identifier_groups_heic_mov_and_aae(tmp_path):
    records = []
    for name, kind in (
        ("IMG_1.HEIC", "photo"),
        ("IMG_1.MOV", "video"),
        ("IMG_1.AAE", "sidecar"),
    ):
        path = tmp_path / name
        path.write_bytes(kind.encode())
        metadata = (
            {"Keys:ContentIdentifier": "synthetic-asset-id"}
            if kind in {"photo", "video"}
            else {}
        )
        records.append(
            FileRecord(
                path,
                Path(name),
                path.stat().st_size,
                path.stat().st_mtime_ns,
                kind,
                metadata=metadata,
            )
        )
    assign_groups(records)
    assert records[0].group_id == records[1].group_id
    assert {records[0].group_type, records[1].group_type} == {"live_photo"}
    assert records[2].group_type == "sidecar"
    assert records[2].group_id == records[0].group_id


def test_xmp_with_double_extension_groups_with_photo(tmp_path):
    records = []
    for name, kind in (("image.jpg", "photo"), ("image.jpg.xmp", "sidecar")):
        path = tmp_path / name
        path.write_bytes(kind.encode())
        records.append(
            FileRecord(
                path,
                Path(name),
                path.stat().st_size,
                path.stat().st_mtime_ns,
                kind,
            )
        )
    assign_groups(records)
    assert records[0].group_id == records[1].group_id
    assert {record.group_type for record in records} == {"sidecar"}


def test_long_collision_name_preserves_extension_and_hash_suffix(tmp_path):
    destination = tmp_path / "destination"
    destination.mkdir()
    records = []
    for directory, data in (("a", b"one"), ("b", b"two")):
        name = f"{'x' * 300}.JPG"
        path = tmp_path / directory / name
        digest = hashlib.sha256(data).hexdigest()
        record = FileRecord(
            path,
            Path(directory) / name,
            len(data),
            0,
            "photo",
            digest,
            DateDecision(datetime(2024, 1, 1), source="test"),
        )
        records.append(record)
    build_copy_plan(records, destination)
    assert all(len(record.destination_relative_path.name) <= 220 for record in records)
    assert all(record.destination_relative_path.suffix == ".JPG" for record in records)
    assert any(record.sha256[:8] in record.destination_relative_path.name for record in records)


def test_low_confidence_live_photo_candidate_is_not_forced_together(tmp_path):
    destination = tmp_path / "destination"
    destination.mkdir()
    records = []
    for extension, kind, captured in (
        (".jpg", "photo", datetime(2022, 1, 1, 1, 1, 1)),
        (".mov", "video", datetime(2023, 2, 2, 2, 2, 2)),
    ):
        path = tmp_path / f"IMG_1{extension}"
        path.write_bytes(kind.encode())
        records.append(
            FileRecord(
                path,
                Path(path.name),
                path.stat().st_size,
                path.stat().st_mtime_ns,
                kind,
                sha256_file(path),
                DateDecision(
                    captured,
                    captured.isoformat(),
                    "test",
                    "metadata",
                    "",
                    "high",
                    "stub",
                ),
            )
        )
    assign_groups(records)
    assert {record.group_type for record in records} == {"live_photo_candidate"}
    build_copy_plan(records, destination)
    assert {
        record.destination_relative_path.parent.as_posix() for record in records
    } == {"2022/2022-01", "2023/2023-02"}


def test_exiftool_uses_argument_list_without_shell(tmp_path, monkeypatch):
    executable = tmp_path / "exiftool.exe"
    executable.write_bytes(b"stub")
    media = tmp_path / "日本語 name.jpg"
    media.write_bytes(b"x")
    captured = {}

    class Process:
        returncode = 0

        def poll(self):
            return 0

        def communicate(self):
            return (
                '[{"EXIF:DateTimeOriginal":"2020:01:01 00:00:00"}]',
                "",
            )

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr("archive_nest.metadata.exiftool.subprocess.Popen", fake_popen)
    tool = ExifTool(str(executable))
    metadata, error = tool.extract(media)
    assert not error
    assert metadata["EXIF:DateTimeOriginal"]
    assert isinstance(captured["args"], list)
    assert captured["args"][-1] == str(media)
    assert captured["kwargs"]["shell"] is False


def test_session_store_records_unfinished_and_completion(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "file.jpg").write_bytes(b"x")
    store = SessionStore(tmp_path / "state" / "sessions.sqlite3")
    result = ScanService(
        metadata_tool=MetadataStub(), session_store=store
    ).scan(source, destination, make_config())
    assert store.unfinished_sessions()[0]["session_id"] == result.session_id
    OrganizeService(store).organize(result, dry_run=True)
    assert store.unfinished_sessions() == []


def test_cancelled_session_can_resume_and_replaces_only_its_partial(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    media = source / "IMG_20240102_030405.jpg"
    media.write_bytes(b"photo")
    store = SessionStore(tmp_path / "state" / "sessions.sqlite3")
    result = ScanService(
        metadata_tool=MetadataStub(), session_store=store
    ).scan(source, destination, make_config())
    record = result.records[0]
    record.status = "cancelled"
    partial = (
        destination
        / record.destination_relative_path.parent
        / f"{record.destination_relative_path.name}.{result.session_id}.partial"
    )
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"incomplete")
    store.save_scan(result, "cancelled")
    store.finish(result.session_id, "cancelled")
    prepared = ResumeService(store).prepare(result.session_id)
    assert prepared.records[0].status == "planned"
    OrganizeService(store).organize(prepared)
    final = destination / prepared.records[0].destination_relative_path
    assert final.read_bytes() == b"photo"
    assert not partial.exists()
    assert store.unfinished_sessions() == []


def test_cli_has_no_move_delete_or_link_options():
    help_text = build_parser().format_help()
    organize_help = build_parser()._subparsers._group_actions[0].choices[
        "organize"
    ].format_help()
    combined = f"{help_text}\n{organize_help}"
    assert "--move" not in combined
    assert "--delete" not in combined
    assert "--link" not in combined
    assert "--remove" not in combined
    assert "--unlink" not in combined
    assert "--hardlink" not in combined
    assert "--symlink" not in combined
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "organize",
                "--source",
                "a",
                "--destination",
                "b",
                "--move",
            ]
        )


def _source_snapshot(root):
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            sha256_file(path),
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def test_source_unchanged_after_failures_resume_rerun_and_staging(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    media = source / "IMG_20240102_030405.jpg"
    media.write_bytes(b"synthetic source")
    before = _source_snapshot(source)
    digest = sha256_file(media)

    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError):
        copy_and_verify(
            media,
            tmp_path / "cancel" / media.name,
            digest,
            session_id="cancel",
            cancellation=token,
        )
    assert _source_snapshot(source) == before

    with monkeypatch.context() as context:
        context.setattr(
            "archive_nest.copying.safe_copy.os.fsync",
            lambda _descriptor: (_ for _ in ()).throw(OSError("write failed")),
        )
        with pytest.raises(OSError, match="write failed"):
            copy_and_verify(
                media,
                tmp_path / "write-error" / media.name,
                digest,
                session_id="write-error",
            )
    assert _source_snapshot(source) == before

    with pytest.raises(CopyVerificationError):
        copy_and_verify(
            media,
            tmp_path / "mismatch" / media.name,
            "0" * 64,
            session_id="mismatch",
        )
    assert _source_snapshot(source) == before

    archive = tmp_path / "archive"
    store = SessionStore(tmp_path / "state" / "sessions.sqlite3")
    cancelled = ScanService(
        metadata_tool=MetadataStub(), session_store=store
    ).scan(source, archive, make_config())
    cancelled.records[0].status = "cancelled"
    store.save_scan(cancelled, "cancelled")
    store.finish(cancelled.session_id, "cancelled")
    resumed = ResumeService(store).prepare(cancelled.session_id)
    OrganizeService(store).organize(resumed)
    assert _source_snapshot(source) == before

    rerun = ScanService(metadata_tool=MetadataStub()).scan(
        source, archive, make_config()
    )
    assert rerun.records[0].status == "already_verified"
    OrganizeService().organize(rerun)
    assert _source_snapshot(source) == before

    volumes = DiscPlanService().plan(archive, 1_000_000)
    create_staging(archive, tmp_path / "staging", volumes)
    assert _source_snapshot(source) == before


def test_archive_nest_entrypoints_do_not_import_legacy_phockup():
    import inspect

    from archive_nest import cli
    from archive_nest.gui import main as gui

    isolated = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import archive_nest.cli; import archive_nest.gui.main; "
                "raise SystemExit('src.phockup' in sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
        shell=False,
        timeout=30,
    )
    assert isolated.returncode == 0, isolated.stderr
    for module in (cli, gui):
        source = inspect.getsource(module)
        assert "src.phockup" not in source
        assert "from src" not in source
    assert cli.ScanService.__module__ == "archive_nest.application.scan_service"
    assert gui.OrganizeService.__module__ == (
        "archive_nest.application.organize_service"
    )


def test_cli_rejects_nested_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))
    source = tmp_path / "source"
    source.mkdir()
    code = main(
        [
            "scan",
            "--source",
            str(source),
            "--destination",
            str(source / "archive"),
        ]
    )
    assert code == EXIT_USAGE


def test_cli_end_to_end_with_synthetic_unicode_data(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))
    source = tmp_path / "写真 source"
    destination = tmp_path / "archive"
    source.mkdir()
    media = source / "日本語_IMG_20240506_070809.JPG"
    media.write_bytes(b"synthetic photo bytes")
    before = (media.read_bytes(), media.stat().st_size, media.stat().st_mtime_ns)
    assert (
        main(
            [
                "organize",
                "--source",
                str(source),
                "--destination",
                str(destination),
            ]
        )
        == 0
    )
    assert main(["verify", "--archive", str(destination)]) == 0
    assert (
        main(
            [
                "plan-disc",
                "--archive",
                str(destination),
                "--capacity-bytes",
                "23000000000",
            ]
        )
        == 0
    )
    assert before == (media.read_bytes(), media.stat().st_size, media.stat().st_mtime_ns)
