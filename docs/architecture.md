# Architecture

ArchiveNest preserves the original Phockup implementation under the historical top-level CLI and `src/phockup.py`, `src/date.py`, and `src/exif.py`. New product code lives exclusively in `src/archive_nest`.

```text
PySide6 GUI / archivenest CLI
              ↓
        application services
              ↓
scan → metadata/date → grouping → hash/deduplicate → copy plan
                                      ↓
                         verified copy / reports / SQLite
                                      ↓
                         archive verify / disc plan
```

The interfaces never parse legacy CLI output. `ScanService`, `OrganizeService`, `VerifyService`, and `DiscPlanService` are called directly. The GUI runs those calls in `QThread` workers and receives progress through Qt signals.

The immutable source boundary is enforced by read-only scan and hash operations. Copying writes only under a separately validated destination. Session settings and SQLite data live in the platform user-data directory, not beside the executable or inside the source.

## Determinism

Source-relative paths are sorted case-insensitively. SHA-256 selects exact duplicates, with the lexically first path as canonical. Name collisions use the first eight SHA-256 characters. Disc grouping and ordering use stable relative paths and group identifiers.

