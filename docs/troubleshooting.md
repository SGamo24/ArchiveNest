# Troubleshooting

## ExifTool not found

The app remains usable with filename dates. Install ExifTool yourself, then select `exiftool.exe` in Settings or pass `--exiftool`. Detection order is the configured path, PATH, repository-local `.tools/exiftool` for development, and known application locations. ArchiveNest never downloads it without consent and never bundles the development copy.

For a repository-local development setup, download the current 64-bit Windows ZIP through the link on the official ExifTool home page, verify it against that release's official checksum file, extract it below `.tools\exiftool`, keep `exiftool_files` beside the executable, and rename `exiftool(-k).exe` to `exiftool.exe`. Do not add `.tools` to Git or permanently change the system PATH.

## Source/destination rejected

Choose two independent folders. Source and destination cannot be the same, nested, aliases of the same physical path, or related through a junction. The destination must be writable.

## Not enough free space

The pre-scan uses planned copy bytes and current free bytes. Remove unrelated data or choose another destination; ArchiveNest will not partially begin a known-over-capacity plan.

## `.partial` files remain

They indicate a failed or cancelled unverified copy. They are excluded from manifests and verification success. Review the error report and retry; ArchiveNest never promotes an unverified partial.

## Verification reports added files

Files not present in the successful manifest are reported as additions. Management files under `reports`, the manifest, and checksum list are excluded.

## Long or Unicode paths

ArchiveNest uses Python path APIs and list-form ExifTool arguments. On Windows, enable long-path support if the operating system or target filesystem rejects a path. Collision names retain the extension and SHA identifier while shortening the stem.

## Windows blocks `ArchiveNest.exe`

On the verified host, WinError 4551 means `An Application Control policy has blocked this file`. The exception occurred while Windows was creating the `ArchiveNest.exe` process, before Python, Qt plug-ins, or ExifTool could be loaded.

Code Integrity `Operational` events at 2026-07-29 22:06:37 and 22:06:55 identified:

- event 3077: enforcement block of `dist\ArchiveNest\ArchiveNest.exe`;
- status `0xc0e90002`;
- policy `VerifiedAndReputableDesktop`, ID `27555.1000.240208`, GUID `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`;
- requested signing level 2 and validated level 1;
- correlated event 3089: `TotalSignatureCount=0`, `PublisherName=Unknown`, and `ValidatedSigningLevel=0`;
- flat SHA-256 `E165503F0CBD80395054367DE4EBA12B8D385604562055BEBF9A8DD2776EB99B`.

Microsoft documents `VerifiedAndReputableDesktop` as Smart App Control enforcement mode and event 3077 as an enforced App Control block. The executable had no `Zone.Identifier`, so Mark of the Web was not the cause. The unsigned ExifTool executable ran successfully on the same host, so “all unsigned files are blocked” and “an ExifTool child process was blocked” are both contradicted by the evidence. The available evidence does not prove that PyInstaller itself is the rule criterion; it proves that this generated executable lacked a signature or reputation accepted by the active policy.

Do not disable Smart App Control, WDAC/App Control, or Defender. A trusted production signature and reputation may allow a public build, but an arbitrary or self-signed certificate is not guaranteed to satisfy this policy, and an organization-managed device may require an explicit publisher, hash, or managed-installer rule. Ask the administrator for the required trust path. Until then, use the source version:

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```
