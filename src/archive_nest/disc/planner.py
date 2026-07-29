from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from archive_nest.domain.models import DiscItem, DiscVolume


def load_archive_items(archive: Path) -> list[DiscItem]:
    manifest_path = archive / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("manifest.json is required for M-DISC planning")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items: list[DiscItem] = []
    for record in manifest.get("files", []):
        if record.get("status") not in {"verified", "already_verified"}:
            continue
        relative = str(record.get("destination_relative_path", ""))
        if not relative:
            continue
        items.append(
            DiscItem(
                relative_path=Path(relative).as_posix(),
                size_bytes=int(record.get("size_bytes", 0)),
                sha256=str(record.get("sha256", "")),
                group_id=(
                    ""
                    if record.get("group_type") == "live_photo_candidate"
                    else str(record.get("group_id", ""))
                ),
            )
        )
    return sorted(items, key=lambda item: item.relative_path.casefold())


def plan_discs(items: list[DiscItem], capacity_bytes: int) -> list[DiscVolume]:
    if capacity_bytes <= 0:
        raise ValueError("Disc capacity must be greater than zero")
    grouped: dict[str, list[DiscItem]] = defaultdict(list)
    for item in items:
        key = item.group_id or f"file:{item.relative_path}"
        grouped[key].append(item)
    groups = sorted(
        (
            sorted(group, key=lambda item: item.relative_path.casefold())
            for group in grouped.values()
        ),
        key=lambda group: min(item.relative_path.casefold() for item in group),
    )
    volumes: list[DiscVolume] = []
    current = DiscVolume(number=1, capacity_bytes=capacity_bytes)
    for group in groups:
        group_size = sum(item.size_bytes for item in group)
        if group_size > capacity_bytes:
            if current.items:
                volumes.append(current)
                current = DiscVolume(len(volumes) + 1, capacity_bytes)
            current.items.extend(group)
            current.oversized = True
            volumes.append(current)
            current = DiscVolume(len(volumes) + 1, capacity_bytes)
            continue
        if current.items and current.used_bytes + group_size > capacity_bytes:
            volumes.append(current)
            current = DiscVolume(len(volumes) + 1, capacity_bytes)
        current.items.extend(group)
    if current.items:
        volumes.append(current)
    return volumes


def write_disc_plan(archive: Path, volumes: list[DiscVolume]) -> Path:
    reports = archive / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    data = {
        "volumes": [
            {
                "number": volume.number,
                "capacity_bytes": volume.capacity_bytes,
                "used_bytes": volume.used_bytes,
                "remaining_bytes": volume.remaining_bytes,
                "oversized": volume.oversized,
                "files": [
                    {
                        "relative_path": item.relative_path,
                        "size_bytes": item.size_bytes,
                        "sha256": item.sha256,
                        "group_id": item.group_id,
                    }
                    for item in volume.items
                ],
            }
            for volume in volumes
        ]
    }
    json_path = reports / "disc-plan.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = reports / "disc-plan.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "disc",
                "relative_path",
                "size_bytes",
                "sha256",
                "group_id",
                "oversized",
            )
        )
        for volume in volumes:
            for item in volume.items:
                writer.writerow(
                    (
                        volume.number,
                        item.relative_path,
                        item.size_bytes,
                        item.sha256,
                        item.group_id,
                        volume.oversized,
                    )
                )
    rows = "".join(
        f"<tr><td>M_DISC_{volume.number:03d}</td><td>{volume.used_bytes}</td>"
        f"<td>{volume.remaining_bytes}</td><td>{'要確認' if volume.oversized else ''}</td></tr>"
        for volume in volumes
    )
    html_path = reports / "disc-plan.html"
    html_path.write_text(
        f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>M-DISC plan</title>
<style>body{{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #999;padding:.4rem}}</style>
</head><body><h1>M-DISC 分割計画</h1><table><tr><th>ディスク</th><th>使用bytes</th><th>残りbytes</th><th>警告</th></tr>{rows}</table></body></html>""",
        encoding="utf-8",
    )
    return json_path
