from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from archive_nest.cancellation import CancellationToken, CancelledError


class ExifTool:
    def __init__(self, configured_path: str = "", bundled_dir: Path | None = None) -> None:
        self.path = self._find(configured_path, bundled_dir)

    @staticmethod
    def _find(configured_path: str, bundled_dir: Path | None) -> Path | None:
        candidates: list[Path] = []
        if configured_path:
            candidates.append(Path(configured_path).expanduser())
        repository = Path(__file__).resolve().parents[3]
        located = shutil.which("exiftool") or shutil.which("exiftool.exe")
        if located:
            candidates.append(Path(located))
        local_tool_root = repository / ".tools" / "exiftool"
        if local_tool_root.is_dir():
            candidates.extend(
                sorted(
                    (
                        *local_tool_root.glob("exiftool.exe"),
                        *local_tool_root.glob("*/exiftool.exe"),
                        *local_tool_root.glob("*/*/exiftool.exe"),
                    ),
                    reverse=True,
                )
            )
        application_dirs = [bundled_dir] if bundled_dir else []
        application_dirs.extend(
            [
                Path(sys.executable).resolve().parent,
                repository / "tools",
            ]
        )
        for directory in application_dirs:
            if directory:
                candidates.extend(
                    [
                        directory / "exiftool.exe",
                        directory / "exiftool(-k).exe",
                        directory / "tools" / "exiftool.exe",
                    ]
                )
        return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)

    @property
    def available(self) -> bool:
        return self.path is not None

    def version(self, timeout: float = 5.0) -> str:
        if not self.path:
            return ""
        try:
            result = subprocess.run(
                [str(self.path), "-ver"],
                capture_output=True,
                check=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    def extract(
        self,
        path: Path,
        *,
        timeout: float = 30.0,
        cancellation: CancellationToken | None = None,
    ) -> tuple[dict[str, Any], str]:
        if not self.path:
            return {}, "ExifTool is not available"
        if cancellation and cancellation.cancelled:
            raise CancelledError("Operation cancelled")
        arguments = [
            str(self.path),
            "-json",
            "-G1",
            "-a",
            "-s",
            "-time:all",
            "-MIMEType",
            "-ContentIdentifier",
            "-MediaGroupUUID",
            "-MotionPhoto",
            str(path),
        ]
        try:
            process = subprocess.Popen(
                arguments,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
        except OSError as exc:
            return {}, f"ExifTool could not be started: {exc}"
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancellation and cancellation.cancelled:
                process.terminate()
                process.communicate()
                raise CancelledError("Operation cancelled")
            if time.monotonic() >= deadline:
                process.kill()
                process.communicate()
                return {}, f"ExifTool timed out after {timeout:g} seconds"
            time.sleep(0.05)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            return {}, stderr.strip() or f"ExifTool exited with {process.returncode}"
        try:
            payload = json.loads(stdout)
            return (payload[0] if payload else {}), stderr.strip()
        except (json.JSONDecodeError, TypeError):
            return {}, "ExifTool returned invalid JSON"
