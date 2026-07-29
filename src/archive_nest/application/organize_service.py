from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from archive_nest.cancellation import CancellationToken, CancelledError
from archive_nest.copying import copy_and_verify
from archive_nest.domain.models import ScanResult
from archive_nest.persistence import SessionStore
from archive_nest.reports import write_archive_reports

ProgressCallback = Callable[[str, int, int, str], None]


class OrganizeService:
    def __init__(self, session_store: SessionStore | None = None) -> None:
        self.session_store = session_store

    def organize(
        self,
        scan: ScanResult,
        *,
        dry_run: bool = False,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> ScanResult:
        token = cancellation or CancellationToken()
        planned = [record for record in scan.records if record.status == "planned"]
        if dry_run:
            scan.finished_at = datetime.now(timezone.utc)
            write_archive_reports(scan)
            if self.session_store:
                self.session_store.save_scan(scan, "dry_run")
                self.session_store.finish(scan.session_id, "dry_run")
            return scan

        session_status = "completed"
        try:
            for index, record in enumerate(planned, 1):
                if token.cancelled:
                    record.status = "cancelled"
                    scan.summary.cancelled += 1
                    session_status = "cancelled"
                    break
                if progress:
                    progress("copy", index, len(planned), str(record.source_path))
                if not record.destination_relative_path:
                    record.status = "failed"
                    record.error_message = "Copy plan has no destination"
                    scan.summary.failed += 1
                    continue
                destination = scan.destination / record.destination_relative_path
                try:
                    copy_and_verify(
                        record.source_path,
                        destination,
                        record.sha256,
                        session_id=scan.session_id,
                        cancellation=token,
                    )
                    record.status = "verified"
                    scan.summary.copied += 1
                    scan.summary.verified += 1
                except CancelledError as exc:
                    record.status = "cancelled"
                    record.error_message = str(exc)
                    scan.summary.cancelled += 1
                    session_status = "cancelled"
                    if self.session_store:
                        self.session_store.update_record(scan.session_id, record)
                    break
                except (OSError, ValueError) as exc:
                    record.status = "failed"
                    record.error_message = str(exc)
                    scan.summary.failed += 1
                    session_status = "completed_with_errors"
                if self.session_store:
                    self.session_store.update_record(scan.session_id, record)
        finally:
            scan.finished_at = datetime.now(timezone.utc)
            write_archive_reports(scan)
            if self.session_store:
                self.session_store.save_scan(scan, session_status)
                self.session_store.finish(scan.session_id, session_status)
        return scan

