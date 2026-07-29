from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from archive_nest.domain.models import FileRecord


def _asset_identifier(metadata: dict[str, Any]) -> str:
    for key, value in metadata.items():
        short = key.split(":", 1)[-1].lower()
        if short in {"contentidentifier", "mediagroupuuid", "assetidentifier"} and value:
            return str(value)
    return ""


def _group_id(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def assign_groups(records: list[FileRecord]) -> None:
    by_asset: dict[str, list[FileRecord]] = defaultdict(list)
    by_directory_stem: dict[tuple[str, str], list[FileRecord]] = defaultdict(list)
    for record in records:
        asset_id = _asset_identifier(record.metadata)
        if asset_id:
            by_asset[asset_id].append(record)
        stem = record.source_path.stem
        if record.media_type == "sidecar" and record.source_path.suffix.lower() == ".xmp":
            nested = Path(stem).suffix
            if nested:
                stem = Path(stem).stem
        key = (record.source_relative_path.parent.as_posix().casefold(), stem.casefold())
        by_directory_stem[key].append(record)

    assigned: set[Path] = set()
    for asset_id, members in sorted(by_asset.items()):
        if len(members) < 2:
            continue
        identifier = _group_id(f"asset:{asset_id}")
        for member in members:
            member.group_id = identifier
            member.group_type = "live_photo"
            member.group_confidence = "high"
            assigned.add(member.source_path)

    for key, members in sorted(by_directory_stem.items()):
        media_types = {member.media_type for member in members}
        is_pair = "photo" in media_types and "video" in media_types
        has_sidecar = "sidecar" in media_types and bool(media_types & {"photo", "video"})
        if not is_pair and not has_sidecar:
            continue
        identifier = _group_id(f"name:{key[0]}:{key[1]}")
        unassigned = [member for member in members if member.source_path not in assigned]
        assigned_group_ids = {
            member.group_id
            for member in members
            if member.source_path in assigned and member.group_id
        }
        if has_sidecar and len(assigned_group_ids) == 1:
            existing_group = next(iter(assigned_group_ids))
            for member in unassigned:
                if member.media_type == "sidecar":
                    member.group_id = existing_group
                    member.group_type = "sidecar"
                    member.group_confidence = "medium"
                    assigned.add(member.source_path)
            unassigned = [
                member for member in members if member.source_path not in assigned
            ]
        dated_photos = [
            member.date.value
            for member in unassigned
            if member.media_type == "photo" and member.date.value
        ]
        dated_videos = [
            member.date.value
            for member in unassigned
            if member.media_type == "video" and member.date.value
        ]
        close_dates = any(
            abs((photo.replace(tzinfo=None) - video.replace(tzinfo=None)).total_seconds())
            <= 10
            for photo in dated_photos
            for video in dated_videos
        )
        if is_pair and close_dates:
            for member in unassigned:
                member.group_id = identifier
                member.group_type = "live_photo"
                member.group_confidence = "medium"
            continue
        if is_pair:
            for member in unassigned:
                if member.media_type in {"photo", "video"}:
                    member.group_id = identifier
                    member.group_type = "live_photo_candidate"
                    member.group_confidence = "low"
            if has_sidecar:
                sidecar_identifier = _group_id(f"sidecar:{key[0]}:{key[1]}")
                for member in unassigned:
                    if member.media_type in {"photo", "sidecar"}:
                        member.group_id = sidecar_identifier
                        member.group_type = "sidecar"
                        member.group_confidence = "medium"
            continue
        for member in unassigned:
            member.group_id = identifier
            member.group_type = "sidecar"
            member.group_confidence = "medium"
