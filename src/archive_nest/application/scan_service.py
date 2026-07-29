from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from archive_nest.cancellation import CancellationToken
from archive_nest.config import ArchiveConfig
from archive_nest.domain.models import FileRecord, ScanResult, ScanSummary
from archive_nest.grouping import assign_groups
from archive_nest.hashing import sha256_file
from archive_nest.metadata import ExifTool, decide_capture_date
from archive_nest.persistence import SessionStore
from archive_nest.planning import build_copy_plan
from archive_nest.safety import is_reparse_point, validate_paths

ProgressCallback = Callable[[str, int, int, str], None]


def _classify(path: Path, config: ArchiveConfig) -> str:
    extension = path.suffix.lower()
    if extension in config.photo_extensions:
        return "photo"
    if extension in config.video_extensions:
        return "video"
    if extension in config.sidecar_extensions:
        return "sidecar"
    return "unsupported"


def _walk_source(
    source: Path, include_subfolders: bool
) -> Iterator[tuple[Path, bool]]:
    directories = [source]
    while directories:
        directory = directories.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            continue
        for entry in entries:
            if is_reparse_point(entry):
                yield entry, True
                continue
            if entry.is_dir():
                if include_subfolders:
                    directories.append(entry)
                continue
            if entry.is_file():
                yield entry, False


class ScanService:
    def __init__(
        self,
        *,
        metadata_tool: ExifTool | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self.metadata_tool = metadata_tool
        self.session_store = session_store

    def scan(
        self,
        source: Path,
        destination: Path,
        config: ArchiveConfig,
        *,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> ScanResult:
        token = cancellation or CancellationToken()
        source_normalized, destination_normalized, free_bytes = validate_paths(
            source, destination
        )
        started = datetime.now(timezone.utc)
        records: list[FileRecord] = []
        entries = list(_walk_source(source_normalized, config.include_subfolders))
        total = len(entries)
        tool = self.metadata_tool or ExifTool(config.exiftool_path)
        custom_fields = config.custom_date_fields.split()

        for index, (path, reparse) in enumerate(entries, 1):
            token.raise_if_cancelled()
            if progress:
                progress("scan", index, total, str(path))
            try:
                stat = path.lstat()
                relative = path.relative_to(source_normalized)
            except (OSError, ValueError) as exc:
                records.append(
                    FileRecord(
                        path,
                        Path(path.name),
                        0,
                        0,
                        "unsupported",
                        status="failed",
                        error_message=str(exc),
                    )
                )
                continue
            if reparse:
                records.append(
                    FileRecord(
                        path,
                        relative,
                        stat.st_size,
                        stat.st_mtime_ns,
                        "reparse_point",
                        status="reparse_point",
                        is_reparse_point=True,
                    )
                )
                continue
            media_type = _classify(path, config)
            status = "planned"
            if media_type == "unsupported" and not config.include_unsupported:
                status = "unsupported"
            record = FileRecord(
                path,
                relative,
                stat.st_size,
                stat.st_mtime_ns,
                media_type,
                status=status,
            )
            if status == "planned":
                try:
                    record.sha256 = sha256_file(path, cancellation=token)
                except OSError as exc:
                    record.status = "failed"
                    record.error_message = f"SHA-256 failed: {exc}"
                    records.append(record)
                    continue
            if media_type in {"photo", "video"}:
                metadata, error = tool.extract(path, cancellation=token)
                record.metadata = metadata
                if error and tool.available and not metadata:
                    record.error_message = error
                record.date = decide_capture_date(
                    path,
                    media_type,
                    metadata,
                    use_file_mtime=config.use_file_mtime,
                    custom_fields=custom_fields,
                )
            records.append(record)

        assign_groups(records)
        build_copy_plan(
            records,
            destination_normalized,
            output_format=config.output_format,
        )
        summary = self._summarize(records, free_bytes)
        result = ScanResult(
            session_id=str(uuid.uuid4()),
            source=source_normalized,
            destination=destination_normalized,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            records=records,
            summary=summary,
            settings=config.to_dict(),
            external_tools={
                "ExifTool": (
                    {"available": True, "path": str(tool.path), "version": tool.version()}
                    if tool.available
                    else {
                        "available": False,
                        "path": "",
                        "version": "",
                        "fallback": "filename dates; optional file mtime",
                    }
                )
            },
        )
        if summary.copy_bytes > summary.free_bytes:
            raise ValueError(
                f"Insufficient destination capacity: required {summary.copy_bytes}, "
                f"available {summary.free_bytes} bytes"
            )
        if self.session_store:
            self.session_store.save_scan(result)
        return result

    @staticmethod
    def _summarize(records: list[FileRecord], free_bytes: int) -> ScanSummary:
        summary = ScanSummary(total_files=len(records), free_bytes=free_bytes)
        live_photo_groups: set[str] = set()
        for record in records:
            if record.media_type == "photo":
                summary.photos += 1
            elif record.media_type == "video":
                summary.videos += 1
            elif record.media_type == "sidecar":
                summary.sidecars += 1
            elif record.media_type in {"unsupported", "reparse_point"}:
                summary.unsupported += 1
            if record.status == "skipped_duplicate":
                summary.duplicate_candidates += 1
            if record.status == "planned":
                summary.copy_planned += 1
                summary.copy_bytes += record.size_bytes
            elif record.status in {
                "unsupported",
                "reparse_point",
                "skipped_duplicate",
                "already_verified",
                "failed",
            }:
                summary.skip_planned += 1
            if record.media_type in {"photo", "video"} and not record.date.value:
                summary.unknown_dates += 1
            if record.date.confidence == "low":
                summary.low_confidence_dates += 1
            if record.collision:
                summary.collisions += 1
            if record.error_message and record.media_type in {"photo", "video"}:
                summary.metadata_errors += 1
            if record.group_type in {
                "live_photo",
                "live_photo_candidate",
            } and record.group_id:
                live_photo_groups.add(record.group_id)
            if record.is_reparse_point:
                summary.reparse_points += 1
        summary.live_photo_candidates = len(live_photo_groups)
        return summary
