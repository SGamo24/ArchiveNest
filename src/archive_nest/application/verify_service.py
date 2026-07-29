from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from archive_nest.cancellation import CancellationToken
from archive_nest.domain.models import VerificationItem, VerificationResult
from archive_nest.hashing import sha256_file
from archive_nest.reports import write_verification_reports

ProgressCallback = Callable[[str, int, int, str], None]
MANAGEMENT_NAMES = {"manifest.json", "SHA256SUMS.txt"}
MANAGEMENT_DIRECTORIES = {"reports", "mdisc_staging"}


def _load_manifest(archive: Path) -> dict[str, tuple[str, int | None]]:
    manifest_path = archive / "manifest.json"
    if manifest_path.is_file():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected: dict[str, tuple[str, int | None]] = {}
        for item in data.get("files", []):
            relative = str(item.get("destination_relative_path", ""))
            if (
                relative
                and item.get("status") in {"verified", "already_verified"}
                and item.get("sha256")
            ):
                expected[Path(relative).as_posix()] = (
                    str(item["sha256"]).lower(),
                    int(item["size_bytes"]) if item.get("size_bytes") is not None else None,
                )
        return expected
    sums = archive / "SHA256SUMS.txt"
    if not sums.is_file():
        raise ValueError("Neither manifest.json nor SHA256SUMS.txt was found")
    expected = {}
    for number, line in enumerate(sums.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            digest, relative = line.split(maxsplit=1)
        except ValueError as exc:
            raise ValueError(f"Invalid SHA256SUMS line {number}") from exc
        expected[Path(relative.lstrip("*")).as_posix()] = (digest.lower(), None)
    return expected


def _archive_files(archive: Path) -> set[str]:
    found: set[str] = set()
    for path in archive.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(archive)
        if relative.name in MANAGEMENT_NAMES or relative.parts[0] in MANAGEMENT_DIRECTORIES:
            continue
        if relative.name.endswith(".partial"):
            continue
        found.add(relative.as_posix())
    return found


class VerifyService:
    def verify(
        self,
        archive: Path,
        *,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> VerificationResult:
        archive = archive.resolve()
        if not archive.is_dir():
            raise ValueError(f"Archive folder does not exist: {archive}")
        expected = _load_manifest(archive)
        token = cancellation or CancellationToken()
        started = datetime.now(timezone.utc)
        items: list[VerificationItem] = []
        for index, (relative, (digest, expected_size)) in enumerate(
            sorted(expected.items()), 1
        ):
            token.raise_if_cancelled()
            path = archive / Path(relative)
            if progress:
                progress("verify", index, len(expected), str(path))
            if not path.is_file():
                items.append(
                    VerificationItem(
                        relative,
                        digest,
                        expected_size=expected_size,
                        status="missing",
                    )
                )
                continue
            try:
                actual_size = path.stat().st_size
                if expected_size is not None and actual_size != expected_size:
                    items.append(
                        VerificationItem(
                            relative,
                            digest,
                            expected_size=expected_size,
                            actual_size=actual_size,
                            status="size_mismatch",
                        )
                    )
                    continue
                actual = sha256_file(path, cancellation=token)
                items.append(
                    VerificationItem(
                        relative,
                        digest,
                        actual,
                        expected_size,
                        actual_size,
                        "verified" if actual == digest else "hash_mismatch",
                    )
                )
            except OSError as exc:
                items.append(
                    VerificationItem(
                        relative,
                        digest,
                        expected_size=expected_size,
                        status="unreadable",
                        error_message=str(exc),
                    )
                )
        added = sorted(_archive_files(archive) - set(expected))
        result = VerificationResult(
            archive,
            started,
            datetime.now(timezone.utc),
            items,
            added,
        )
        write_verification_reports(result)
        return result
