# Third-party notices

ArchiveNest is an independent derivative of **Phockup**.

- Project: Phockup
- Upstream: <https://github.com/ivandokov/phockup>
- Copyright: Copyright © 2017 Ivan Dokov
- License: MIT License; the complete text is retained in `LICENSE` and `license`.
- Relationship: ArchiveNest is not an official Phockup release and is not endorsed by the original author.

Runtime and build dependencies are not relicensed by ArchiveNest:

| Component | Purpose | License |
|---|---|---|
| Python | Runtime | Python Software Foundation License |
| PySide6 / Qt for Python | GUI | LGPLv3/GPLv3/commercial; distribution must comply with the selected terms |
| PyInstaller | Windows packaging | GPLv2-or-later with the PyInstaller bootloader exception |
| pytest and pytest plugins | Development tests only | MIT-compatible licenses; see each package |
| tqdm | Historical Phockup CLI dependency | MPL-2.0/MIT |
| ExifTool | Optional external metadata tool, not bundled | Perl Artistic License or GPL |

`scripts/build.ps1` copies this notice, `LICENSE`, and `license` into the one-folder distribution. Before a public release, regenerate and review a complete dependency inventory for the exact locked dependency versions.

