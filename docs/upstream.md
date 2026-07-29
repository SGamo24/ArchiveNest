# Upstream relationship

The upstream project is <https://github.com/ivandokov/phockup>. This repository retains its Git history.

Expected remotes:

```text
origin   ArchiveNest independent repository
upstream https://github.com/ivandokov/phockup.git
```

Use `git fetch upstream` and compare `upstream/master` without rewriting history. Merge or cherry-pick reviewed upstream fixes only after checking ArchiveNest's copy-only safety boundary and tests. Do not remove or repoint `upstream`.

The original implementation remains in the historical `src` modules and Phockup CLI. ArchiveNest-specific work lives under `src/archive_nest`, its scripts, documentation, tests, and packaging. A generally useful fix that does not depend on ArchiveNest policy may be proposed upstream separately; do not imply that ArchiveNest itself is endorsed upstream.
