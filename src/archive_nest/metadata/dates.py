from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from archive_nest.domain.models import DateDecision

PHOTO_FIELDS = (
    "Composite:SubSecDateTimeOriginal",
    "EXIF:DateTimeOriginal",
    "EXIF:CreateDate",
    "XMP:CreateDate",
    "QuickTime:CreateDate",
)
VIDEO_FIELDS = (
    "QuickTime:CreationDate",
    "QuickTime:CreateDate",
    "Keys:CreationDate",
    "Track1:MediaCreateDate",
    "Track1:TrackCreateDate",
    "XMP:CreateDate",
)
FILENAME_PATTERNS = (
    re.compile(
        r"(?<!\d)(?P<year>19\d{2}|20\d{2})[-_]?(?P<month>\d{2})[-_]?(?P<day>\d{2})"
        r"(?:[-_ T]?(?P<hour>\d{2})[-_.:]?(?P<minute>\d{2})[-_.:]?(?P<second>\d{2}))?(?!\d)"
    ),
)


def _parse_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip() or raw.startswith("0000"):
        return None
    value = raw.strip()
    value = re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", value)
    value = value.replace("Z", "+00:00")
    for parser in (
        datetime.fromisoformat,
        lambda text: datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S"),
    ):
        try:
            return parser(value)
        except (ValueError, TypeError):
            continue
    return None


def _valid(value: datetime | None, now: datetime) -> bool:
    if value is None or value.year < 1900:
        return False
    comparable = value
    if comparable.tzinfo:
        comparable = comparable.astimezone(timezone.utc).replace(tzinfo=None)
    return comparable <= now + timedelta(days=2)


def _metadata_candidates(
    metadata: dict[str, Any],
    media_type: str,
    custom_fields: Iterable[str],
) -> Iterable[tuple[str, Any]]:
    fields = list(custom_fields)
    fields.extend(VIDEO_FIELDS if media_type == "video" else PHOTO_FIELDS)
    seen: set[str] = set()
    for field in fields:
        if not field or field in seen:
            continue
        seen.add(field)
        if field in metadata:
            yield field, metadata[field]
            continue
        short = field.split(":", 1)[-1]
        for key, value in metadata.items():
            if key.split(":", 1)[-1] == short:
                yield key, value
                break


def decide_capture_date(
    path: Path,
    media_type: str,
    metadata: dict[str, Any],
    *,
    use_file_mtime: bool = False,
    custom_fields: Iterable[str] = (),
    now: datetime | None = None,
) -> DateDecision:
    current = now or datetime.now()
    for field, raw in _metadata_candidates(metadata, media_type, custom_fields):
        parsed = _parse_datetime(raw)
        if _valid(parsed, current):
            timezone_text = ""
            if parsed and parsed.tzinfo:
                timezone_text = parsed.strftime("%z")
            confidence = "high" if "DateTimeOriginal" in field or "CreationDate" in field else "medium"
            return DateDecision(
                parsed,
                str(raw),
                field,
                "metadata",
                timezone_text,
                confidence,
                "ExifTool",
            )

    for pattern in FILENAME_PATTERNS:
        match = pattern.search(path.stem)
        if not match:
            continue
        parts = {key: int(value or 0) for key, value in match.groupdict().items()}
        try:
            parsed = datetime(
                parts["year"],
                parts["month"],
                parts["day"],
                parts["hour"],
                parts["minute"],
                parts["second"],
            )
        except ValueError:
            continue
        if _valid(parsed, current):
            return DateDecision(
                parsed,
                match.group(0),
                "filename",
                "filename",
                "",
                "medium",
                "ArchiveNest",
            )

    if use_file_mtime:
        try:
            parsed = datetime.fromtimestamp(path.stat().st_mtime)
            if _valid(parsed, current):
                return DateDecision(
                    parsed,
                    str(path.stat().st_mtime_ns),
                    "FileModifyDate",
                    "filesystem",
                    "",
                    "low",
                    "ArchiveNest",
                )
        except OSError:
            pass
    return DateDecision()
