from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DateDecision:
    value: datetime | None = None
    raw: str = ""
    field: str = ""
    source: str = "unknown"
    timezone: str = ""
    confidence: str = "none"
    tool: str = "fallback"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["value"] = self.value.isoformat() if self.value else None
        return data


@dataclass(slots=True)
class FileRecord:
    source_path: Path
    source_relative_path: Path
    size_bytes: int
    mtime_ns: int
    media_type: str
    sha256: str = ""
    date: DateDecision = field(default_factory=DateDecision)
    metadata: dict[str, Any] = field(default_factory=dict)
    destination_relative_path: Path | None = None
    status: str = "planned"
    duplicate_of: str = ""
    group_id: str = ""
    group_type: str = ""
    group_confidence: str = ""
    error_message: str = ""
    collision: bool = False
    is_reparse_point: bool = False

    @property
    def source_filename(self) -> str:
        return self.source_path.name

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "media_type": self.media_type,
            "source_path": str(self.source_path),
            "source_relative_path": self.source_relative_path.as_posix(),
            "source_filename": self.source_filename,
            "destination_relative_path": (
                self.destination_relative_path.as_posix()
                if self.destination_relative_path
                else ""
            ),
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
            "sha256": self.sha256,
            "date": self.date.to_dict(),
            "group_id": self.group_id,
            "group_type": self.group_type,
            "group_confidence": self.group_confidence,
            "duplicate_of": self.duplicate_of,
            "error_message": self.error_message,
        }


@dataclass(slots=True)
class ScanSummary:
    total_files: int = 0
    photos: int = 0
    videos: int = 0
    sidecars: int = 0
    unsupported: int = 0
    duplicate_candidates: int = 0
    unknown_dates: int = 0
    copy_planned: int = 0
    skip_planned: int = 0
    copy_bytes: int = 0
    free_bytes: int = 0
    collisions: int = 0
    metadata_errors: int = 0
    low_confidence_dates: int = 0
    live_photo_candidates: int = 0
    reparse_points: int = 0
    copied: int = 0
    verified: int = 0
    failed: int = 0
    cancelled: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(slots=True)
class ScanResult:
    session_id: str
    source: Path
    destination: Path
    started_at: datetime
    finished_at: datetime | None
    records: list[FileRecord]
    summary: ScanSummary
    settings: dict[str, Any]
    external_tools: dict[str, Any]


@dataclass(slots=True)
class VerificationItem:
    relative_path: str
    expected_sha256: str = ""
    actual_sha256: str = ""
    expected_size: int | None = None
    actual_size: int | None = None
    status: str = "verified"
    error_message: str = ""


@dataclass(slots=True)
class VerificationResult:
    archive: Path
    started_at: datetime
    finished_at: datetime
    items: list[VerificationItem]
    added_files: list[str]

    @property
    def ok(self) -> bool:
        return not self.added_files and all(item.status == "verified" for item in self.items)


@dataclass(slots=True)
class DiscItem:
    relative_path: str
    size_bytes: int
    sha256: str
    group_id: str = ""


@dataclass(slots=True)
class DiscVolume:
    number: int
    capacity_bytes: int
    items: list[DiscItem] = field(default_factory=list)
    oversized: bool = False

    @property
    def used_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.capacity_bytes - self.used_bytes)
