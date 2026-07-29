from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from archive_nest.config import user_data_dir
from archive_nest.domain.models import (DateDecision, FileRecord, ScanResult,
                                        ScanSummary)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    destination TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    settings_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    session_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_relative_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'unsupported',
    sha256 TEXT,
    metadata_json TEXT NOT NULL,
    date_json TEXT NOT NULL,
    destination_relative_path TEXT,
    copy_status TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    duplicate_of TEXT,
    group_id TEXT,
    group_type TEXT,
    group_confidence TEXT,
    error_message TEXT,
    PRIMARY KEY (session_id, source_path)
);
"""


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or user_data_dir() / "archive_nest.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(files)")
            }
            if "media_type" not in columns:
                connection.execute(
                    "ALTER TABLE files ADD COLUMN media_type TEXT NOT NULL DEFAULT 'unsupported'"
                )
            if "group_confidence" not in columns:
                connection.execute(
                    "ALTER TABLE files ADD COLUMN group_confidence TEXT"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def save_scan(self, result: ScanResult, status: str = "scanned") -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO sessions
                    (session_id, source, destination, started_at, finished_at, status, settings_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.session_id,
                    str(result.source),
                    str(result.destination),
                    result.started_at.isoformat(),
                    result.finished_at.isoformat() if result.finished_at else None,
                    status,
                    json.dumps(result.settings, ensure_ascii=False),
                ),
            )
            for record in result.records:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO files
                        (session_id, source_path, source_relative_path, size_bytes, mtime_ns,
                         media_type,
                         sha256, metadata_json, date_json, destination_relative_path,
                         copy_status, verification_status, duplicate_of, group_id, group_type,
                         group_confidence, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.session_id,
                        str(record.source_path),
                        record.source_relative_path.as_posix(),
                        record.size_bytes,
                        record.mtime_ns,
                        record.media_type,
                        record.sha256,
                        json.dumps(record.metadata, ensure_ascii=False, default=str),
                        json.dumps(record.date.to_dict(), ensure_ascii=False),
                        record.destination_relative_path.as_posix()
                        if record.destination_relative_path
                        else "",
                        record.status,
                        "verified"
                        if record.status in {"verified", "already_verified"}
                        else "pending",
                        record.duplicate_of,
                        record.group_id,
                        record.group_type,
                        record.group_confidence,
                        record.error_message,
                    ),
                )

    def update_record(self, session_id: str, record: FileRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE files
                SET copy_status = ?, verification_status = ?, error_message = ?,
                    destination_relative_path = ?
                WHERE session_id = ? AND source_path = ?
                """,
                (
                    record.status,
                    "verified"
                    if record.status in {"verified", "already_verified"}
                    else "pending",
                    record.error_message,
                    record.destination_relative_path.as_posix()
                    if record.destination_relative_path
                    else "",
                    session_id,
                    str(record.source_path),
                ),
            )

    def finish(self, session_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET status = ?, finished_at = ? WHERE session_id = ?",
                (status, datetime.now(timezone.utc).isoformat(), session_id),
            )

    def unfinished_sessions(self) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, source, destination, started_at, status
                FROM sessions
                WHERE status NOT IN ('completed', 'dry_run')
                ORDER BY started_at DESC
                """
            ).fetchall()
        return [
            {
                "session_id": row[0],
                "source": row[1],
                "destination": row[2],
                "started_at": row[3],
                "status": row[4],
            }
            for row in rows
        ]

    def load_session(self, session_id: str) -> ScanResult:
        with self._connect() as connection:
            session = connection.execute(
                """
                SELECT source, destination, started_at, finished_at, settings_json
                FROM sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if session is None:
                raise ValueError(f"Unknown session: {session_id}")
            rows = connection.execute(
                """
                SELECT source_path, source_relative_path, size_bytes, mtime_ns,
                       media_type, sha256, metadata_json, date_json,
                       destination_relative_path, copy_status, duplicate_of,
                       group_id, group_type, group_confidence, error_message
                FROM files WHERE session_id = ?
                ORDER BY source_relative_path COLLATE NOCASE
                """,
                (session_id,),
            ).fetchall()
        records: list[FileRecord] = []
        for row in rows:
            date_data = json.loads(row[7] or "{}")
            date_value = date_data.get("value")
            decision = DateDecision(
                value=datetime.fromisoformat(date_value) if date_value else None,
                raw=str(date_data.get("raw", "")),
                field=str(date_data.get("field", "")),
                source=str(date_data.get("source", "unknown")),
                timezone=str(date_data.get("timezone", "")),
                confidence=str(date_data.get("confidence", "none")),
                tool=str(date_data.get("tool", "fallback")),
            )
            records.append(
                FileRecord(
                    source_path=Path(row[0]),
                    source_relative_path=Path(row[1]),
                    size_bytes=int(row[2]),
                    mtime_ns=int(row[3]),
                    media_type=str(row[4]),
                    sha256=str(row[5] or ""),
                    date=decision,
                    metadata=json.loads(row[6] or "{}"),
                    destination_relative_path=Path(row[8]) if row[8] else None,
                    status=str(row[9]),
                    duplicate_of=str(row[10] or ""),
                    group_id=str(row[11] or ""),
                    group_type=str(row[12] or ""),
                    group_confidence=str(row[13] or ""),
                    error_message=str(row[14] or ""),
                )
            )
        return ScanResult(
            session_id=session_id,
            source=Path(session[0]),
            destination=Path(session[1]),
            started_at=datetime.fromisoformat(session[2]),
            finished_at=datetime.fromisoformat(session[3]) if session[3] else None,
            records=records,
            summary=ScanSummary(),
            settings=json.loads(session[4]),
            external_tools={"resumed_from_session": session_id},
        )
