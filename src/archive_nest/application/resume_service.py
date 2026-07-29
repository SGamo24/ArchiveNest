from __future__ import annotations

import shutil

from archive_nest.application.scan_service import ScanService
from archive_nest.cancellation import CancellationToken
from archive_nest.config import ArchiveConfig
from archive_nest.hashing import sha256_file
from archive_nest.persistence import SessionStore
from archive_nest.planning import build_copy_plan
from archive_nest.safety import validate_paths


class ResumeService:
    def __init__(self, session_store: SessionStore) -> None:
        self.session_store = session_store

    def prepare(
        self,
        session_id: str,
        *,
        cancellation: CancellationToken | None = None,
    ):
        token = cancellation or CancellationToken()
        result = self.session_store.load_session(session_id)
        _, destination, free_bytes = validate_paths(
            result.source, result.destination
        )
        config = ArchiveConfig.from_dict(result.settings)
        for record in result.records:
            token.raise_if_cancelled()
            if record.status in {
                "unsupported",
                "reparse_point",
                "skipped_duplicate",
            }:
                continue
            try:
                stat = record.source_path.stat()
            except OSError as exc:
                record.status = "failed"
                record.error_message = f"Source is no longer readable: {exc}"
                continue
            if stat.st_size != record.size_bytes or stat.st_mtime_ns != record.mtime_ns:
                record.status = "failed"
                record.error_message = "Source changed since the original scan"
                continue
            if record.status in {"verified", "already_verified"}:
                target = (
                    destination / record.destination_relative_path
                    if record.destination_relative_path
                    else None
                )
                if (
                    target
                    and target.is_file()
                    and target.stat().st_size == record.size_bytes
                    and sha256_file(target, cancellation=token) == record.sha256
                ):
                    continue
            record.status = "planned"
            record.error_message = ""

        build_copy_plan(
            result.records,
            destination,
            output_format=config.output_format,
        )
        result.summary = ScanService._summarize(result.records, free_bytes)
        if result.summary.copy_bytes > shutil.disk_usage(destination).free:
            raise ValueError("Insufficient destination capacity to resume")
        result.finished_at = None
        self.session_store.save_scan(result, "resuming")
        return result
