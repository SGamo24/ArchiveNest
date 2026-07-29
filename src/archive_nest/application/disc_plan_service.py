from __future__ import annotations

from pathlib import Path

from archive_nest.cancellation import CancellationToken
from archive_nest.disc import create_staging, plan_discs, write_disc_plan
from archive_nest.disc.planner import load_archive_items
from archive_nest.domain.models import DiscVolume


class DiscPlanService:
    def plan(self, archive: Path, capacity_bytes: int) -> list[DiscVolume]:
        archive = archive.resolve()
        volumes = plan_discs(load_archive_items(archive), capacity_bytes)
        write_disc_plan(archive, volumes)
        return volumes

    def stage(
        self,
        archive: Path,
        staging_parent: Path,
        volumes: list[DiscVolume],
        *,
        cancellation: CancellationToken | None = None,
    ) -> Path:
        return create_staging(
            archive,
            staging_parent,
            volumes,
            cancellation=cancellation,
        )
