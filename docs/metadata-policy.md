# Metadata and date policy

ArchiveNest uses ExifTool JSON output when available. Arguments are passed as a list with `shell=False`; Unicode paths are not interpolated into a shell command. The tool path may come from user settings or `--exiftool`, PATH, the ignored repository-local `.tools/exiftool` development area, or an application area. Calls have a timeout and errors are recorded. ArchiveNest does not download or bundle ExifTool.

Photo fields prioritize `DateTimeOriginal`, subsecond original time, and appropriate EXIF/XMP creation fields. Video fields prioritize QuickTime or media creation time. A user-provided field list is tried before defaults. A clear filename date is the next fallback. File modification time is disabled by default and is used only when enabled.

Each decision records the normalized value, raw value, field, source, timezone text, confidence, and tool. Naive timestamps remain naive; ArchiveNest does not invent a UTC offset. Dates before 1900, invalid dates, and dates more than two days in the future are rejected.

Without ExifTool, the GUI and CLI continue with filename parsing and the optional modification-time fallback. HEIC, RAW, and container-specific video dates generally require ExifTool.

The real-tool integration tests create copies of synthetic repository fixtures in pytest temporary folders and use ExifTool to write and read JPEG `DateTimeOriginal`, offset-aware composite time, XMP `CreateDate`, MP4 `QuickTime:CreateDate`, and MOV `Keys:CreationDate`. Run them with:

```powershell
.\.venv\Scripts\python.exe -m pytest -ra -m exiftool
```

The test environment does not synthesize a fully valid HEIC container. HEIC classification, HEIC/MOV/AAE grouping, common asset identifiers, weak-pair rejection, invalid dates, filename fallback, and modification-time fallback remain synthetic or mocked tests; MOV and MP4 metadata extraction uses real ExifTool.
