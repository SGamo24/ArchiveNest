from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


class PathSafetyError(ValueError):
    """Raised when source/destination safety invariants are not met."""


def normalize_path(path: Path) -> Path:
    return Path(os.path.normcase(os.path.abspath(os.path.realpath(path))))


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def is_reparse_point(path: Path) -> bool:
    try:
        stat = path.lstat()
    except OSError:
        return False
    attributes = getattr(stat, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & 0x400)


def validate_paths(
    source: Path,
    destination: Path,
    *,
    required_bytes: int = 0,
    create_destination: bool = True,
) -> tuple[Path, Path, int]:
    if not source.exists():
        raise PathSafetyError(f"Source folder does not exist: {source}")
    if not source.is_dir():
        raise PathSafetyError(f"Source is not a folder: {source}")

    source_normalized = normalize_path(source)
    destination_normalized = normalize_path(destination)
    if source_normalized == destination_normalized:
        raise PathSafetyError("Source and destination must be different folders")
    if is_relative_to(destination_normalized, source_normalized):
        raise PathSafetyError("Destination must not be inside the source folder")
    if is_relative_to(source_normalized, destination_normalized):
        raise PathSafetyError("Source must not be inside the destination folder")

    if destination.exists() and not destination.is_dir():
        raise PathSafetyError(f"Destination is not a folder: {destination}")
    if create_destination:
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PathSafetyError(f"Destination cannot be created: {exc}") from exc

    probe_parent = destination if destination.exists() else destination.parent
    if not probe_parent.exists():
        raise PathSafetyError(f"Destination parent does not exist: {probe_parent}")
    try:
        with tempfile.NamedTemporaryFile(prefix=".archivenest-write-", dir=probe_parent):
            pass
    except OSError as exc:
        raise PathSafetyError(f"Destination is not writable: {exc}") from exc

    free_bytes = shutil.disk_usage(probe_parent).free
    if required_bytes > free_bytes:
        raise PathSafetyError(
            f"Destination has insufficient free space: required {required_bytes}, "
            f"available {free_bytes} bytes"
        )
    return source_normalized, destination_normalized, free_bytes

