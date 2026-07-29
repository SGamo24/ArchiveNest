from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PHOTO_EXTENSIONS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".heic",
        ".heif",
        ".webp",
        ".tif",
        ".tiff",
        ".cr2",
        ".cr3",
        ".nef",
        ".arw",
        ".dng",
        ".rw2",
        ".orf",
        ".raf",
    }
)
VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp", ".mts", ".m2ts", ".webm"}
)
SIDECAR_EXTENSIONS = frozenset({".aae", ".xmp", ".thm"})


def user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "ArchiveNest"


@dataclass(slots=True)
class ArchiveConfig:
    last_source: str = ""
    last_destination: str = ""
    exiftool_path: str = ""
    include_subfolders: bool = True
    output_format: str = "%Y/%Y-%m"
    use_file_mtime: bool = False
    dry_run: bool = False
    include_unsupported: bool = False
    custom_date_fields: str = ""
    disc_capacity_bytes: int = 23_000_000_000
    window_width: int = 980
    window_height: int = 720
    log_level: str = "INFO"
    photo_extensions: tuple[str, ...] = tuple(sorted(PHOTO_EXTENSIONS))
    video_extensions: tuple[str, ...] = tuple(sorted(VIDEO_EXTENSIONS))
    sidecar_extensions: tuple[str, ...] = tuple(sorted(SIDECAR_EXTENSIONS))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("photo_extensions", "video_extensions", "sidecar_extensions"):
            data[key] = list(data[key])
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArchiveConfig:
        allowed = {item.name for item in fields(cls)}
        filtered = {key: value for key, value in data.items() if key in allowed}
        for key in ("photo_extensions", "video_extensions", "sidecar_extensions"):
            if key in filtered:
                filtered[key] = tuple(str(value).lower() for value in filtered[key])
        return cls(**filtered)


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or user_data_dir() / "settings.json"

    def load(self) -> ArchiveConfig:
        try:
            return ArchiveConfig.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return ArchiveConfig()
        except (OSError, ValueError, TypeError):
            logger.warning("Unable to read settings; defaults are being used", exc_info=True)
            return ArchiveConfig()

    def save(self, config: ArchiveConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.partial")
        temporary.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
