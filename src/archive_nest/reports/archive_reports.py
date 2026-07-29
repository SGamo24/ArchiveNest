from __future__ import annotations

import csv
import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from archive_nest import __version__
from archive_nest.domain.models import FileRecord, ScanResult

FILE_FIELDS = (
    "status",
    "media_type",
    "source_path",
    "source_relative_path",
    "source_filename",
    "destination_path",
    "destination_relative_path",
    "size_bytes",
    "sha256",
    "captured_at",
    "captured_at_raw",
    "timezone",
    "date_source",
    "date_field",
    "date_confidence",
    "metadata_tool",
    "group_id",
    "group_type",
    "duplicate_of",
    "error_message",
)


def _atomic_write(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    temporary = path.with_name(f"{path.name}.partial")
    temporary.write_text(content, encoding=encoding, newline="")
    temporary.replace(path)


def _write_csv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    temporary = path.with_name(f"{path.name}.partial")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _file_row(record: FileRecord, destination: Path) -> dict[str, Any]:
    relative = record.destination_relative_path
    return {
        "status": record.status,
        "media_type": record.media_type,
        "source_path": str(record.source_path),
        "source_relative_path": record.source_relative_path.as_posix(),
        "source_filename": record.source_filename,
        "destination_path": str(destination / relative) if relative else "",
        "destination_relative_path": relative.as_posix() if relative else "",
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "captured_at": record.date.value.isoformat() if record.date.value else "",
        "captured_at_raw": record.date.raw,
        "timezone": record.date.timezone,
        "date_source": record.date.source,
        "date_field": record.date.field,
        "date_confidence": record.date.confidence,
        "metadata_tool": record.date.tool,
        "group_id": record.group_id,
        "group_type": record.group_type,
        "duplicate_of": record.duplicate_of,
        "error_message": record.error_message,
    }


def _summary_html(result: ScanResult) -> str:
    monthly_count: Counter[str] = Counter()
    monthly_bytes: Counter[str] = Counter()
    source_count: Counter[str] = Counter()
    confidence_count: Counter[str] = Counter()
    status_count: Counter[str] = Counter(record.status for record in result.records)
    for record in result.records:
        month = (
            record.date.value.strftime("%Y-%m")
            if record.date.value
            else "_unknown_date"
        )
        monthly_count[month] += 1
        monthly_bytes[month] += record.size_bytes
        source_count[record.date.source] += 1
        confidence_count[record.date.confidence] += 1

    def table(mapping: dict[str, Any], second_heading: str) -> str:
        body = "".join(
            f"<tr><td>{html.escape(str(key))}</td><td>{html.escape(str(value))}</td></tr>"
            for key, value in sorted(mapping.items())
        )
        return f"<table><thead><tr><th>項目</th><th>{second_heading}</th></tr></thead><tbody>{body}</tbody></table>"

    settings = {
        key: value
        for key, value in result.settings.items()
        if "password" not in key.lower() and "token" not in key.lower()
    }
    summary_values = result.summary.to_dict()
    summary_values["source"] = str(result.source)
    summary_values["destination"] = str(result.destination)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>ArchiveNest report</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}}
table{{border-collapse:collapse;margin:1rem 0;width:100%}}th,td{{border:1px solid #aaa;padding:.4rem;text-align:left}}
@media(prefers-color-scheme:dark){{body{{color:#eee;background:#181818}}th,td{{border-color:#666}}}}
</style></head><body>
<h1>ArchiveNest 実行結果</h1>
<p>セッション: {html.escape(result.session_id)}</p>
<p>開始: {html.escape(result.started_at.isoformat())}<br>終了: {html.escape(result.finished_at.isoformat() if result.finished_at else "")}</p>
<h2>概要</h2>{table(summary_values, "値")}
<h2>設定</h2>{table(settings, "値")}
<h2>年月別件数</h2>{table(dict(monthly_count), "件数")}
<h2>年月別容量</h2>{table(dict(monthly_bytes), "bytes")}
<h2>日時情報源</h2>{table(dict(source_count), "件数")}
<h2>信頼度</h2>{table(dict(confidence_count), "件数")}
<h2>処理状態</h2>{table(dict(status_count), "件数")}
<h2>外部ツール</h2>{table(result.external_tools, "状態")}
</body></html>"""


def write_archive_reports(result: ScanResult) -> None:
    destination = result.destination
    reports = destination / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    rows = [_file_row(record, destination) for record in result.records]
    by_relative_source = {
        record.source_relative_path.as_posix(): record for record in result.records
    }
    _write_csv(reports / "files.csv", FILE_FIELDS, rows)
    _write_csv(
        reports / "duplicates.csv",
        (
            "sha256",
            "size_bytes",
            "canonical_source_path",
            "canonical_destination_path",
            "duplicate_source_path",
            "status",
        ),
        (
            {
                "sha256": record.sha256,
                "size_bytes": record.size_bytes,
                "canonical_source_path": (
                    str(by_relative_source[record.duplicate_of].source_path)
                    if record.duplicate_of in by_relative_source
                    else record.duplicate_of
                ),
                "canonical_destination_path": (
                    str(
                        destination
                        / by_relative_source[
                            record.duplicate_of
                        ].destination_relative_path
                    )
                    if record.duplicate_of in by_relative_source
                    and by_relative_source[
                        record.duplicate_of
                    ].destination_relative_path
                    else ""
                ),
                "duplicate_source_path": str(record.source_path),
                "status": record.status,
            }
            for record in result.records
            if record.duplicate_of
        ),
    )
    _write_csv(
        reports / "unknown_dates.csv",
        FILE_FIELDS,
        (
            row
            for row, record in zip(rows, result.records)
            if record.media_type in {"photo", "video"} and not record.date.value
        ),
    )
    _write_csv(
        reports / "unsupported.csv",
        FILE_FIELDS,
        (
            row
            for row, record in zip(rows, result.records)
            if record.status in {"unsupported", "reparse_point"}
        ),
    )
    _write_csv(
        reports / "errors.csv",
        FILE_FIELDS,
        (row for row, record in zip(rows, result.records) if record.error_message),
    )
    _write_csv(
        reports / "operations.csv",
        ("status", "source_path", "destination_path", "sha256", "error_message"),
        (
            {
                "status": row["status"],
                "source_path": row["source_path"],
                "destination_path": row["destination_path"],
                "sha256": row["sha256"],
                "error_message": row["error_message"],
            }
            for row in rows
        ),
    )

    verified = [
        record
        for record in result.records
        if record.status in {"verified", "already_verified"}
        and record.destination_relative_path
    ]
    checksum_lines = [
        f"{record.sha256} *{record.destination_relative_path.as_posix()}"
        for record in sorted(
            verified, key=lambda item: item.destination_relative_path.as_posix()
        )
    ]
    _atomic_write(
        destination / "SHA256SUMS.txt",
        "\n".join(checksum_lines) + ("\n" if checksum_lines else ""),
    )
    manifest = {
        "schema_version": 1,
        "archive_nest_version": __version__,
        "session_id": result.session_id,
        "started_at": result.started_at.isoformat(),
        "finished_at": (
            result.finished_at or datetime.now(timezone.utc)
        ).isoformat(),
        "source": str(result.source),
        "destination": str(result.destination),
        "settings": result.settings,
        "external_tools": result.external_tools,
        "summary": result.summary.to_dict(),
        "files": [record.to_manifest_dict() for record in result.records],
    }
    _atomic_write(
        destination / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )
    _atomic_write(reports / "summary.html", _summary_html(result))
