from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from archive_nest import __version__
from archive_nest.application.disc_plan_service import DiscPlanService
from archive_nest.application.organize_service import OrganizeService
from archive_nest.application.resume_service import ResumeService
from archive_nest.application.scan_service import ScanService
from archive_nest.application.verify_service import VerifyService
from archive_nest.cancellation import CancelledError
from archive_nest.config import ArchiveConfig
from archive_nest.persistence import SessionStore
from archive_nest.reports import write_archive_reports
from archive_nest.safety import PathSafetyError

EXIT_OK = 0
EXIT_PARTIAL_ERROR = 1
EXIT_USAGE = 2
EXIT_CANCELLED = 3
EXIT_VERIFY_FAILED = 4


def _add_source_destination(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument(
        "--no-subfolders",
        action="store_true",
        help="Do not recurse into source subfolders",
    )
    parser.add_argument(
        "--use-file-mtime",
        action="store_true",
        help="Allow file modification time as the lowest-priority date fallback",
    )
    parser.add_argument("--exiftool", default="", help="Path to ExifTool executable")
    parser.add_argument(
        "--output-format", default="%Y/%Y-%m", help="strftime output folder format"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archivenest",
        description="Copy-only photo and video archive preparation",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan", help="Scan and create a copy plan")
    _add_source_destination(scan)
    organize = subparsers.add_parser("organize", help="Scan, copy, and verify")
    _add_source_destination(organize)
    organize.add_argument("--dry-run", action="store_true")
    verify = subparsers.add_parser("verify", help="Verify an organized archive")
    verify.add_argument("--archive", required=True, type=Path)
    disc = subparsers.add_parser("plan-disc", help="Create an M-DISC split plan")
    disc.add_argument("--archive", required=True, type=Path)
    disc.add_argument("--capacity-bytes", required=True, type=int)
    disc.add_argument(
        "--staging",
        type=Path,
        help="After planning, copy and verify staging folders under this folder",
    )
    resume = subparsers.add_parser("resume", help="Resume a persisted session")
    resume.add_argument("--session-id", required=True)
    gui = subparsers.add_parser("gui", help="Start the PySide6 GUI")
    gui.set_defaults(command="gui")
    return parser


def _config(options: argparse.Namespace) -> ArchiveConfig:
    return ArchiveConfig(
        include_subfolders=not options.no_subfolders,
        output_format=options.output_format,
        use_file_mtime=options.use_file_mtime,
        exiftool_path=options.exiftool,
        dry_run=getattr(options, "dry_run", False),
    )


def _progress(phase: str, current: int, total: int, path: str) -> None:
    print(f"[{phase}] {current}/{total} {path}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if options.command == "gui":
            from archive_nest.gui.main import main as gui_main

            return gui_main()
        if options.command == "resume":
            store = SessionStore()
            result = ResumeService(store).prepare(options.session_id)
            OrganizeService(store).organize(result, progress=_progress)
            print(json.dumps(result.summary.to_dict(), ensure_ascii=False, indent=2))
            return EXIT_PARTIAL_ERROR if result.summary.failed else EXIT_OK
        if options.command in {"scan", "organize"}:
            store = SessionStore()
            scanner = ScanService(session_store=store)
            result = scanner.scan(
                options.source,
                options.destination,
                _config(options),
                progress=_progress,
            )
            if options.command == "scan":
                write_archive_reports(result)
            else:
                OrganizeService(store).organize(
                    result,
                    dry_run=options.dry_run,
                    progress=_progress,
                )
            print(json.dumps(result.summary.to_dict(), ensure_ascii=False, indent=2))
            return EXIT_PARTIAL_ERROR if result.summary.failed else EXIT_OK
        if options.command == "verify":
            result = VerifyService().verify(options.archive, progress=_progress)
            print(
                json.dumps(
                    {
                        "ok": result.ok,
                        "checked": len(result.items),
                        "added": len(result.added_files),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return EXIT_OK if result.ok else EXIT_VERIFY_FAILED
        if options.command == "plan-disc":
            service = DiscPlanService()
            volumes = service.plan(options.archive, options.capacity_bytes)
            if options.staging:
                service.stage(options.archive, options.staging, volumes)
            print(
                json.dumps(
                    [
                        {
                            "disc": volume.number,
                            "used_bytes": volume.used_bytes,
                            "remaining_bytes": volume.remaining_bytes,
                            "oversized": volume.oversized,
                        }
                        for volume in volumes
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return EXIT_PARTIAL_ERROR if any(v.oversized for v in volumes) else EXIT_OK
    except KeyboardInterrupt:
        return EXIT_CANCELLED
    except CancelledError:
        return EXIT_CANCELLED
    except (ValueError, PathSafetyError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PARTIAL_ERROR
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
