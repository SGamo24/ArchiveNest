# Safety model

ArchiveNest prioritizes source-data protection over performance.

Before scanning it resolves and case-normalizes source and destination paths, rejects equality and either-direction containment, checks destination writability, and checks free capacity before copying. Symbolic links, junctions, and other Windows reparse points are recorded but not traversed.

Each source is opened only for reading. Copying writes to a destination-side `<name>.<session>.partial`, flushes it, verifies that source size and `mtime_ns` did not change, calculates the partial file's SHA-256, and renames it only after a match. Existing final files are never overwritten. A failed or cancelled partial remains identifiable and is never reported as successful.

SQLite session state is stored below `%LOCALAPPDATA%\ArchiveNest` on Windows. Reports and manifests are written only below the destination. Archive verification is read-only except for its result reports.

The legacy Phockup implementation still contains move, delete, directory-removal, and hard-link options for historical/upstream compatibility. They remain in `src/phockup.py` and the historical CLI only.

The ArchiveNest command parser defines only `scan`, `organize`, `verify`, `plan-disc`, `resume`, and `gui`; its tests reject move, delete, remove, unlink, hard-link, and symbolic-link options. GUI signals invoke `ScanService`, `OrganizeService`, `ResumeService`, `VerifyService`, and `DiscPlanService` directly. Those services import only `archive_nest` modules. The PyInstaller specification starts at `src/archive_nest/gui/main.py` and explicitly excludes `src.phockup`, `src.exif`, and `src.date`.

The copy implementation opens the source with `rb`, writes only a destination-side session `.partial`, verifies source size, inode and `mtime_ns`, verifies the destination SHA-256, and renames only that destination partial. Its only unlink operation removes a destination partial belonging to the same resumed session. Regression tests exercise command reachability and compare source relative paths, names, sizes, SHA-256 and `mtime_ns` after cancellation, destination-write failure, SHA mismatch, resume, rerun, and M-DISC staging.
