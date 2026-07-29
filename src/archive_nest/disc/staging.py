from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable

from archive_nest.cancellation import CancellationToken
from archive_nest.copying import copy_and_verify
from archive_nest.domain.models import DiscVolume
from archive_nest.safety import validate_paths

ProgressCallback = Callable[[str, int, int, str], None]


def create_staging(
    archive: Path,
    staging_parent: Path,
    volumes: list[DiscVolume],
    *,
    cancellation: CancellationToken | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    total_bytes = sum(volume.used_bytes for volume in volumes)
    archive_normalized, staging_normalized, _ = validate_paths(
        archive,
        staging_parent,
        required_bytes=total_bytes,
    )
    root = staging_normalized / "mdisc_staging"
    if root.exists():
        raise FileExistsError(f"Staging folder already exists: {root}")
    token = cancellation or CancellationToken()
    all_items = [item for volume in volumes for item in volume.items]
    completed = 0
    for volume in volumes:
        volume_root = root / f"M_DISC_{volume.number:03d}"
        volume_root.mkdir(parents=True, exist_ok=False)
        file_rows: list[tuple[str, int, str, str]] = []
        checksum_lines: list[str] = []
        for item in volume.items:
            token.raise_if_cancelled()
            completed += 1
            source = archive_normalized / Path(item.relative_path)
            destination = volume_root / Path(item.relative_path)
            if progress:
                progress("staging", completed, len(all_items), str(source))
            copy_and_verify(
                source,
                destination,
                item.sha256,
                session_id=f"staging-{volume.number:03d}",
                cancellation=token,
            )
            file_rows.append(
                (item.relative_path, item.size_bytes, item.sha256, item.group_id)
            )
            checksum_lines.append(f"{item.sha256} *{item.relative_path}")
        (volume_root / "README.txt").write_text(
            "ArchiveNest M-DISC staging folder.\n"
            "Burn all contents and enable the writing software's verify option.\n"
            f"Planned bytes: {volume.used_bytes}\n",
            encoding="utf-8",
        )
        with (volume_root / "FILES.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as stream:
            writer = csv.writer(stream)
            writer.writerow(("relative_path", "size_bytes", "sha256", "group_id"))
            writer.writerows(file_rows)
        (volume_root / "SHA256SUMS.txt").write_text(
            "\n".join(checksum_lines) + "\n", encoding="utf-8"
        )
    return root

