from __future__ import annotations

import json
import os
from pathlib import Path

from archive_nest.domain.models import FileRecord
from archive_nest.hashing import sha256_file

MAX_FILENAME_LENGTH = 220


def _safe_filename(
    filename: str, suffix: str = "", maximum_length: int = MAX_FILENAME_LENGTH
) -> str:
    path = Path(filename)
    extension = path.suffix
    stem = path.stem
    maximum = max(1, maximum_length - len(extension) - len(suffix))
    if len(stem) > maximum:
        stem = stem[:maximum]
    return f"{stem}{suffix}{extension}"


def _month_path(record: FileRecord, output_format: str) -> Path:
    if not record.date.value:
        return Path("_unknown_date")
    formatted = record.date.value.strftime(output_format)
    return Path(*formatted.replace("\\", "/").split("/"))


def _case_key(path: Path) -> str:
    return os.path.normcase(str(path)).casefold()


def _verified_manifest_entries(destination: Path) -> dict[str, tuple[int, str]]:
    manifest = destination / "manifest.json"
    if not manifest.is_file():
        return {}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    entries: dict[str, tuple[int, str]] = {}
    for item in data.get("files", []):
        relative = str(item.get("destination_relative_path", ""))
        if (
            relative
            and item.get("status") in {"verified", "already_verified"}
            and item.get("sha256")
        ):
            entries[_case_key(Path(relative))] = (
                int(item.get("size_bytes", -1)),
                str(item["sha256"]).lower(),
            )
    return entries


def build_copy_plan(
    records: list[FileRecord],
    destination: Path,
    *,
    output_format: str = "%Y/%Y-%m",
) -> None:
    verified_manifest = _verified_manifest_entries(destination)

    def is_already_verified(record: FileRecord, relative: Path) -> bool:
        final_path = destination / relative
        if (
            verified_manifest.get(_case_key(relative))
            != (record.size_bytes, record.sha256)
            or not final_path.is_file()
        ):
            return False
        try:
            return (
                final_path.stat().st_size == record.size_bytes
                and sha256_file(final_path) == record.sha256
            )
        except OSError:
            return False

    canonical_by_digest: dict[tuple[int, str], FileRecord] = {}
    for record in sorted(records, key=lambda item: item.source_relative_path.as_posix().casefold()):
        if record.status in {"unsupported", "failed", "reparse_point"}:
            continue
        duplicate_key = (record.size_bytes, record.sha256)
        canonical = canonical_by_digest.get(duplicate_key)
        if canonical:
            record.status = "skipped_duplicate"
            record.duplicate_of = canonical.source_relative_path.as_posix()
            continue
        canonical_by_digest[duplicate_key] = record

    confidence_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
    group_dates: dict[str, FileRecord] = {}
    for record in records:
        if (
            record.group_id
            and record.group_type in {"live_photo", "sidecar"}
            and record.date.value
        ):
            existing = group_dates.get(record.group_id)
            if existing is None or (
                confidence_rank.get(record.date.confidence, 0),
                record.source_relative_path.as_posix().casefold(),
            ) > (
                confidence_rank.get(existing.date.confidence, 0),
                existing.source_relative_path.as_posix().casefold(),
            ):
                group_dates[record.group_id] = record

    used: dict[str, FileRecord] = {}
    for record in sorted(records, key=lambda item: item.source_relative_path.as_posix().casefold()):
        if record.status != "planned":
            continue
        date_record = (
            group_dates.get(record.group_id, record)
            if record.group_type in {"live_photo", "sidecar"}
            else record
        )
        directory = _month_path(date_record, output_format)
        path_budget = max(
            32,
            min(MAX_FILENAME_LENGTH, 240 - len(str(destination / directory)) - 1),
        )
        filename = _safe_filename(
            record.source_filename, maximum_length=path_budget
        )
        relative = directory / filename
        key = _case_key(relative)
        existing_planned = used.get(key)
        final_path = destination / relative

        if existing_planned or final_path.exists():
            if not existing_planned and is_already_verified(record, relative):
                record.destination_relative_path = relative
                record.status = "already_verified"
                continue
            suffix = f"__{record.sha256[:8]}"
            relative = directory / _safe_filename(
                record.source_filename, suffix, path_budget
            )
            record.collision = True
            key = _case_key(relative)
            counter = 2
            while key in used or (destination / relative).exists():
                if key not in used and is_already_verified(record, relative):
                    record.destination_relative_path = relative
                    record.status = "already_verified"
                    break
                suffix = f"__{record.sha256[:8]}_{counter}"
                relative = directory / _safe_filename(
                    record.source_filename, suffix, path_budget
                )
                key = _case_key(relative)
                counter += 1
            if record.status == "already_verified":
                continue
        record.destination_relative_path = relative
        used[key] = record
