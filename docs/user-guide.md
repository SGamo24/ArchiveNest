# User guide

1. Install with `scripts\setup.ps1` and start with `scripts\run.ps1`.
2. Select a source and a separate destination.
3. Leave modification-time fallback off unless its lower confidence is acceptable.
4. Run the mandatory pre-scan. Review planned count, bytes, duplicates, unknown dates, unsupported files, collisions, and errors.
5. Optionally enable dry-run. Start copying only after reviewing the confirmation.
6. Inspect `reports\summary.html`, `manifest.json`, `SHA256SUMS.txt`, and the organized files.
7. Use archive verification after copying to another device or reading an M-DISC.
8. Create an M-DISC plan using a conservative capacity. Staging is optional and always copy-and-verify.

Cancel stops at a safe chunk boundary. Verified files remain. Partial files are visibly suffixed and not included in successful checksums. On startup, the GUI presents the newest unfinished session as a resume candidate. The CLI can use `python -m archive_nest resume --session-id ID`. Resume revalidates source size and `mtime_ns`, keeps verified destinations, and restarts only pending copies; a changed source is reported instead of copied from stale state.

ArchiveNest does not burn discs. Use separate writing software and enable its post-write verification.
