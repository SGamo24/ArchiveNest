# ArchiveNest contributor rules

- Never delete, move, rename, modify, or write metadata to source files.
- Never create management files in the source folder.
- Do not add automatic deletion, a hard-link mode, or a symbolic-link substitute.
- Do not omit post-copy SHA-256 verification.
- Never overwrite an existing destination file.
- Keep the GUI and CLI dependent on shared application services; do not place archive logic in the GUI.
- Preserve the Phockup copyright, MIT license notice, upstream history, and provenance.
- Do not rewrite upstream history or change/remove the `upstream` remote.
- Preserve existing naming and design choices unless a scoped safety requirement requires otherwise.
- Run relevant tests before treating a change as complete; report anything that could not be run.
- Use only synthetic files and temporary directories in tests. Never search for or use a contributor's personal photos.
- Do not emit periodic progress messages; report only a blocker, a material safety conflict, a repository-assumption conflict, or completion.

