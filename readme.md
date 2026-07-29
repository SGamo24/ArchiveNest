# ArchiveNest

ArchiveNest prepares a copy-only, individually accessible photo and video archive before long-term storage on M-DISC, external HDD, or SSD. It scans a source folder without writing to it, plans a deterministic `YYYY/YYYY-MM` layout, copies through identifiable partial files, verifies every copy with SHA-256, and produces offline reports.

ArchiveNest is an independent project based on [Phockup](https://github.com/ivandokov/phockup). It is not an official Phockup release and is not endorsed by the original Phockup author.

Phockup is licensed under the MIT License. The original copyright and license notice are retained in this repository and in distributed builds. The historical Phockup README is preserved at [docs/phockup-readme.md](docs/phockup-readme.md).

## 安全方針

ArchiveNest の GUI と `archivenest` CLI は元ファイルを削除、移動、変更、リネームせず、ハードリンクやシンボリックリンクも作りません。元フォルダ内に管理ファイルを作りません。同名ファイルを上書きせず、コピーは `.partial` ファイルを経由し、SHA-256 が一致した場合だけ完了とします。

元の Phockup 互換 CLI には移動・削除・リンク機能が残っていますが、新しい Windows 配布物の実行経路には含めていません。ArchiveNest の安全境界については [docs/safety.md](docs/safety.md) を参照してください。

## 対応形式

- 写真: `.jpg .jpeg .png .heic .heif .webp .tif .tiff`
- RAW: `.cr2 .cr3 .nef .arw .dng .rw2 .orf .raf`
- 動画: `.mp4 .mov .m4v .avi .mkv .3gp .mts .m2ts .webm`
- サイドカー: `.aae .xmp .thm`

対応外ファイルは既定でコピーせず、レポートへ記録します。

## Windows セットアップ

PowerShell で次を実行します。

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

`setup.ps1` は `.venv` を作成し、開発・GUI・ビルド依存関係を導入します。ExifTool は自動ダウンロードしません。

## ExifTool

ExifTool は、設定画面または `--exiftool` で指定したパス、PATH、開発用の `.tools/exiftool/`、アプリ領域の順で検出します。`.tools` は開発・テスト専用で Git 対象外です。製品は ExifTool を自動取得せず、Windows 配布物にも同梱しません。

GUI は ExifTool がなくても起動できます。その場合は、明確なファイル名日時を使用し、利用者が明示的に許可した場合だけ更新日時を低信頼度の代替値として使います。EXIF/XMP、HEIC、コンテナ固有の動画日時、共通アセット識別子には ExifTool が必要です。

## GUI

元フォルダと別の整理先を選択し、最初に「事前スキャン」を実行します。結果と容量を確認してから「コピー開始」を選びます。ドライランはメディアをコピーせず、走査、メタデータ解析、SHA-256、重複・衝突判定、容量計算、レポート生成を行います。

## CLI

```powershell
python -m archive_nest scan --source "D:\Photos" --destination "E:\PhotoArchive"
python -m archive_nest organize --source "D:\Photos" --destination "E:\PhotoArchive"
python -m archive_nest organize --source "D:\Photos" --destination "E:\PhotoArchive" --dry-run
python -m archive_nest resume --session-id "保存されたセッションID"
python -m archive_nest verify --archive "E:\PhotoArchive"
python -m archive_nest plan-disc --archive "E:\PhotoArchive" --capacity-bytes 23000000000
python -m archive_nest plan-disc --archive "E:\PhotoArchive" --capacity-bytes 23000000000 --staging "F:\BurnPrep"
```

終了コードは `0=成功`、`1=一部エラー`、`2=引数・設定エラー`、`3=キャンセル`、`4=検証不一致` です。

## 出力

整理先には年月別ファイル、`manifest.json`、`SHA256SUMS.txt` と次のレポートを生成します。

```text
reports/
├─ summary.html
├─ files.csv
├─ duplicates.csv
├─ unknown_dates.csv
├─ unsupported.csv
├─ errors.csv
└─ operations.csv
```

CSV は Excel で開きやすい UTF-8 BOM、HTML は外部リソース不要です。アーカイブ再検証は存在、サイズ、SHA-256、不足、追加、読み取りエラーを報告し、ファイルを変更しません。

## M-DISC

M-DISC 分割は計画だけを既定動作とし、ファイル自体を分割しません。Live Photo とサイドカーのグループを可能な限り同じディスクへ置きます。`--staging` を明示した場合だけ別の場所にコピーし、再度 SHA-256 を検証します。

ArchiveNest は M-DISC への書き込みを行いません。Power2Go などのライティングソフトを使用し、そのソフト側でも書き込み後ベリファイを有効にしてください。

## テストとビルド

```powershell
.\scripts\test.ps1
.\.venv\Scripts\python.exe -m pytest -ra -m exiftool
.\scripts\acceptance-test.ps1 -KeepArtifacts
.\scripts\build.ps1
```

受入試験は既定で合成 JPEG・MP4・サイドカー等を作り、スキャン、ドライラン、コピー後 SHA-256、重複・衝突、再実行、再検証、M-DISC 計画・ステージング、元データ不変性を確認します。成功時は生成物を削除し、`-KeepArtifacts` 指定時は表示された `.acceptance-artifacts` 配下へ保持します。利用者が明示的に準備した入力だけを試す場合は `-SourceFolder "D:\ArchiveNestAcceptanceInput"` を指定できます。

one-folder 形式の成果物は `dist\ArchiveNest\ArchiveNest.exe` です。ライセンス文書も同じ配布フォルダへ含まれます。

## 制限事項

- ExifTool を同梱していません。
- ベース名だけによる Live Photo 推定は低信頼度です。共通アセット識別子がある場合を優先します。
- 元 Phockup CLI は履歴と上流互換性のため隔離して保持しますが、ArchiveNest 配布物には含めません。
- 生成した exe はコード署名されません。この検証環境では Smart App Control の強制ポリシー `VerifiedAndReputableDesktop` が `ArchiveNest.exe` を WinError 4551 で拒否しました。一般的な署名を付けるだけで必ず許可されるとは断定できません。信頼された署名・評価または管理者が定める許可規則が必要な場合があります。セキュリティ機能を無効化せず、当面は `.\scripts\run.ps1` でソース版を実行してください。
- 光学ディスクの実書き込み、AI 判定、顔認識、類似写真選別、自動削除、クラウド送信、ZIP 化は行いません。

詳細は [ユーザーガイド](docs/user-guide.md)、[アーキテクチャ](docs/architecture.md)、[メタデータ方針](docs/metadata-policy.md)、[トラブルシューティング](docs/troubleshooting.md) を参照してください。
