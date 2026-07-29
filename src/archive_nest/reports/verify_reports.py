from __future__ import annotations

import csv
import html
from pathlib import Path

from archive_nest.domain.models import VerificationResult


def write_verification_reports(result: VerificationResult) -> Path:
    directory = result.archive / "reports" / "verification"
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / "verification.csv"
    temporary = csv_path.with_suffix(".csv.partial")
    fields = (
        "status",
        "relative_path",
        "expected_size",
        "actual_size",
        "expected_sha256",
        "actual_sha256",
        "error_message",
    )
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in result.items:
            writer.writerow(
                {
                    "status": item.status,
                    "relative_path": item.relative_path,
                    "expected_size": item.expected_size,
                    "actual_size": item.actual_size,
                    "expected_sha256": item.expected_sha256,
                    "actual_sha256": item.actual_sha256,
                    "error_message": item.error_message,
                }
            )
        for relative in result.added_files:
            writer.writerow({"status": "added", "relative_path": relative})
    temporary.replace(csv_path)

    counts: dict[str, int] = {}
    for item in result.items:
        counts[item.status] = counts.get(item.status, 0) + 1
    counts["added"] = len(result.added_files)
    rows = "".join(
        f"<tr><td>{html.escape(key)}</td><td>{value}</td></tr>"
        for key, value in sorted(counts.items())
    )
    item_rows = "".join(
        f"<tr><td>{html.escape(item.status)}</td><td>{html.escape(item.relative_path)}</td>"
        f"<td>{html.escape(item.error_message)}</td></tr>"
        for item in result.items
    )
    output = directory / "verification.html"
    output.write_text(
        f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>ArchiveNest verification</title><style>
body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;color:#222;background:#fff}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #999;padding:.4rem}}
@media(prefers-color-scheme:dark){{body{{color:#eee;background:#181818}}}}
</style></head><body><h1>アーカイブ再検証</h1>
<p>結果: {"成功" if result.ok else "不一致あり"}</p>
<table>{rows}</table><h2>ファイル</h2><table><tr><th>状態</th><th>パス</th><th>エラー</th></tr>{item_rows}</table>
</body></html>""",
        encoding="utf-8",
    )
    return output

