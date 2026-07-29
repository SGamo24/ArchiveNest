from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from archive_nest import __version__
from archive_nest.application.disc_plan_service import DiscPlanService
from archive_nest.application.organize_service import OrganizeService
from archive_nest.application.resume_service import ResumeService
from archive_nest.application.scan_service import ScanService
from archive_nest.application.verify_service import VerifyService
from archive_nest.cancellation import CancellationToken, CancelledError
from archive_nest.config import ArchiveConfig, ConfigStore, user_data_dir
from archive_nest.metadata import ExifTool
from archive_nest.persistence import SessionStore

try:
    from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal, Slot
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - exercised when optional dependency is absent
    raise RuntimeError(
        "PySide6 is required for the GUI. Run scripts/setup.ps1 first."
    ) from exc

logger = logging.getLogger(__name__)


class Worker(QObject):
    progress = Signal(str, int, int, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, operation: Callable[[Callable[..., None]], Any]) -> None:
        super().__init__()
        self.operation = operation

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(self.operation(self.progress.emit))
        except CancelledError:
            self.cancelled.emit()
        except Exception:
            logger.exception("Background operation failed")
            self.failed.emit(traceback.format_exc())


class SettingsDialog(QDialog):
    def __init__(self, config: ArchiveConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ArchiveNest 設定")
        layout = QFormLayout(self)
        self.exiftool = QLineEdit(config.exiftool_path)
        browse = QPushButton("参照…")
        browse.clicked.connect(self._browse_exiftool)
        exif_layout = QHBoxLayout()
        exif_layout.addWidget(self.exiftool)
        exif_layout.addWidget(browse)
        layout.addRow("ExifTool:", exif_layout)
        tool = ExifTool(config.exiftool_path)
        layout.addRow(
            "検出状態:",
            QLabel(
                f"{tool.path} (version {tool.version() or 'unknown'})"
                if tool.available
                else "未検出（ファイル名日時のみ利用可能）"
            ),
        )
        self.include_unsupported = QCheckBox("対応外ファイルもコピー対象にする")
        self.include_unsupported.setChecked(config.include_unsupported)
        layout.addRow(self.include_unsupported)
        self.date_fields = QLineEdit(config.custom_date_fields)
        self.date_fields.setPlaceholderText("例: DateTimeOriginal CreateDate")
        layout.addRow("優先日時フィールド:", self.date_fields)
        self.photo_extensions = QLineEdit(" ".join(config.photo_extensions))
        self.video_extensions = QLineEdit(" ".join(config.video_extensions))
        self.sidecar_extensions = QLineEdit(" ".join(config.sidecar_extensions))
        layout.addRow("写真・RAW拡張子:", self.photo_extensions)
        layout.addRow("動画拡張子:", self.video_extensions)
        layout.addRow("サイドカー拡張子:", self.sidecar_extensions)
        self.log_level = QComboBox()
        self.log_level.addItems(["INFO", "DEBUG", "WARNING"])
        self.log_level.setCurrentText(config.log_level)
        layout.addRow("ログレベル:", self.log_level)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _browse_exiftool(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "ExifTool を選択", self.exiftool.text(), "Executable (*.exe);;All files (*)"
        )
        if selected:
            self.exiftool.setText(selected)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config_store = ConfigStore()
        self.config = self.config_store.load()
        logging.getLogger().setLevel(
            getattr(logging, self.config.log_level.upper(), logging.INFO)
        )
        self.session_store = SessionStore()
        self.scan_result = None
        self.token: CancellationToken | None = None
        self.thread: QThread | None = None
        self.worker: Worker | None = None
        self.elapsed_seconds = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._build_ui()
        self.resize(self.config.window_width, self.config.window_height)
        unfinished = self.session_store.unfinished_sessions()
        if unfinished:
            self.status_label.setText(
                f"未完了または再開確認が必要なセッション: {len(unfinished)} 件"
            )
            QTimer.singleShot(0, self._offer_resume)

    def _build_ui(self) -> None:
        self.setWindowTitle(f"ArchiveNest {__version__}")
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        paths = QGroupBox("フォルダ")
        grid = QGridLayout(paths)
        self.source_edit = QLineEdit(self.config.last_source)
        self.destination_edit = QLineEdit(self.config.last_destination)
        source_button = QPushButton("元フォルダを選択…")
        destination_button = QPushButton("整理先を選択…")
        source_button.clicked.connect(lambda: self._choose_folder(self.source_edit))
        destination_button.clicked.connect(
            lambda: self._choose_folder(self.destination_edit)
        )
        self.source_edit.textChanged.connect(self._invalidate_scan)
        self.destination_edit.textChanged.connect(self._invalidate_scan)
        grid.addWidget(QLabel("元フォルダ"), 0, 0)
        grid.addWidget(self.source_edit, 0, 1)
        grid.addWidget(source_button, 0, 2)
        grid.addWidget(QLabel("整理先フォルダ"), 1, 0)
        grid.addWidget(self.destination_edit, 1, 1)
        grid.addWidget(destination_button, 1, 2)
        root.addWidget(paths)

        options = QGroupBox("整理設定")
        options_layout = QGridLayout(options)
        self.subfolders = QCheckBox("サブフォルダを含める")
        self.subfolders.setChecked(self.config.include_subfolders)
        self.output_format = QComboBox()
        self.output_format.setEditable(True)
        self.output_format.addItems(["%Y/%Y-%m", "%Y/%m", "%Y/%m/%d"])
        self.output_format.setCurrentText(self.config.output_format)
        self.use_mtime = QCheckBox("更新日時を代替日時として使用")
        self.use_mtime.setChecked(self.config.use_file_mtime)
        self.dry_run = QCheckBox("ドライラン（メディアをコピーしない）")
        self.dry_run.setChecked(self.config.dry_run)
        for widget in (self.subfolders, self.output_format, self.use_mtime):
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self._invalidate_scan)
            else:
                widget.toggled.connect(self._invalidate_scan)
        options_layout.addWidget(self.subfolders, 0, 0)
        options_layout.addWidget(QLabel("出力フォルダ形式"), 0, 1)
        options_layout.addWidget(self.output_format, 0, 2)
        options_layout.addWidget(self.use_mtime, 1, 0, 1, 2)
        options_layout.addWidget(self.dry_run, 1, 2)
        root.addWidget(options)

        actions = QHBoxLayout()
        self.scan_button = QPushButton("事前スキャン")
        self.copy_button = QPushButton("コピー開始")
        self.resume_button = QPushButton("前回処理を再開")
        self.cancel_button = QPushButton("キャンセル")
        self.verify_button = QPushButton("アーカイブ再検証")
        self.disc_button = QPushButton("M-DISC分割計画")
        self.settings_button = QPushButton("設定")
        self.logs_button = QPushButton("ログを開く")
        self.about_button = QPushButton("バージョン情報")
        self.copy_button.setEnabled(False)
        self.resume_button.setEnabled(bool(self.session_store.unfinished_sessions()))
        self.cancel_button.setEnabled(False)
        self.scan_button.clicked.connect(self._scan)
        self.copy_button.clicked.connect(self._organize)
        self.resume_button.clicked.connect(self._offer_resume)
        self.cancel_button.clicked.connect(self._cancel)
        self.verify_button.clicked.connect(self._verify)
        self.disc_button.clicked.connect(self._disc_plan)
        self.settings_button.clicked.connect(self._settings)
        self.logs_button.clicked.connect(self._open_logs)
        self.about_button.clicked.connect(self._about)
        for button in (
            self.scan_button,
            self.copy_button,
            self.resume_button,
            self.cancel_button,
            self.verify_button,
            self.disc_button,
            self.settings_button,
            self.logs_button,
            self.about_button,
        ):
            actions.addWidget(button)
        root.addLayout(actions)

        progress_group = QGroupBox("処理状況")
        progress_layout = QFormLayout(progress_group)
        self.phase_label = QLabel("待機中")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.current_label = QLabel("")
        self.current_label.setWordWrap(False)
        self.status_label = QLabel("事前スキャンを実行してください")
        self.counters_label = QLabel("処理済み 0 / 0")
        self.elapsed_label = QLabel("0 秒")
        progress_layout.addRow("フェーズ:", self.phase_label)
        progress_layout.addRow("全体進捗:", self.progress_bar)
        progress_layout.addRow("現在:", self.current_label)
        progress_layout.addRow("経過時間:", self.elapsed_label)
        progress_layout.addRow("件数:", self.counters_label)
        progress_layout.addRow("結果:", self.status_label)
        root.addWidget(progress_group)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        root.addWidget(self.log_view, 1)

    def _config_from_ui(self) -> ArchiveConfig:
        self.config.last_source = self.source_edit.text().strip()
        self.config.last_destination = self.destination_edit.text().strip()
        self.config.include_subfolders = self.subfolders.isChecked()
        self.config.output_format = self.output_format.currentText().strip()
        self.config.use_file_mtime = self.use_mtime.isChecked()
        self.config.dry_run = self.dry_run.isChecked()
        return self.config

    def _choose_folder(self, target: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "フォルダを選択", target.text() or str(Path.home())
        )
        if selected:
            target.setText(selected)

    def _invalidate_scan(self) -> None:
        self.scan_result = None
        self.copy_button.setEnabled(False)

    def _set_busy(self, busy: bool) -> None:
        self.scan_button.setEnabled(not busy)
        self.copy_button.setEnabled(not busy and self.scan_result is not None)
        self.resume_button.setEnabled(
            not busy and bool(self.session_store.unfinished_sessions())
        )
        self.verify_button.setEnabled(not busy)
        self.disc_button.setEnabled(not busy)
        self.settings_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        if busy:
            self.elapsed_seconds = 0
            self.timer.start(1000)
        else:
            self.timer.stop()

    def _run(
        self,
        operation: Callable[[Callable[..., None]], Any],
        on_completed: Callable[[Any], None],
    ) -> None:
        if self.token is None:
            self.token = CancellationToken()
        self.thread = QThread(self)
        self.worker = Worker(operation)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(on_completed)
        self.worker.completed.connect(self.thread.quit)
        self.worker.failed.connect(self._failed)
        self.worker.failed.connect(self.thread.quit)
        self.worker.cancelled.connect(self._cancelled)
        self.worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(lambda: self._set_busy(False))
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self._set_busy(True)
        self.thread.start()

    def _scan(self) -> None:
        config = self._config_from_ui()
        self.config_store.save(config)
        source = Path(config.last_source)
        destination = Path(config.last_destination)
        token = self.token = CancellationToken()
        service = ScanService(session_store=self.session_store)
        self._run(
            lambda progress: service.scan(
                source,
                destination,
                config,
                cancellation=token,
                progress=progress,
            ),
            self._scan_completed,
        )

    def _scan_completed(self, result: Any) -> None:
        self.scan_result = result
        self.copy_button.setEnabled(True)
        summary = result.summary
        text = (
            f"総数 {summary.total_files} / コピー予定 {summary.copy_planned} / "
            f"重複 {summary.duplicate_candidates} / 日付不明 {summary.unknown_dates} / "
            f"対応外 {summary.unsupported} / エラー {summary.metadata_errors}\n"
            f"予定容量 {summary.copy_bytes:,} bytes / 空き {summary.free_bytes:,} bytes"
        )
        self.status_label.setText(text)
        self.counters_label.setText(
            f"コピー予定 {summary.copy_planned} / 重複 {summary.duplicate_candidates} / "
            f"日付不明 {summary.unknown_dates} / 対応外 {summary.unsupported}"
        )
        QMessageBox.information(
            self,
            "事前スキャン完了",
            text + "\n\n内容を確認してから「コピー開始」を押してください。",
        )

    def _organize(self) -> None:
        if self.scan_result is None:
            QMessageBox.warning(self, "事前スキャンが必要です", "先に事前スキャンを実行してください。")
            return
        action = "レポートを生成" if self.dry_run.isChecked() else "コピーを開始"
        if (
            QMessageBox.question(
                self,
                "実行確認",
                f"事前スキャン結果に基づいて{action}します。よろしいですか？",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        token = self.token = CancellationToken()
        service = OrganizeService(self.session_store)
        self._run(
            lambda progress: service.organize(
                self.scan_result,
                dry_run=self.dry_run.isChecked(),
                cancellation=token,
                progress=progress,
            ),
            self._organize_completed,
        )

    def _organize_completed(self, result: Any) -> None:
        self.scan_result = result
        self.status_label.setText(
            f"コピー {result.summary.copied} / 検証成功 {result.summary.verified} / "
            f"失敗 {result.summary.failed} / キャンセル {result.summary.cancelled}"
        )
        QMessageBox.information(self, "処理完了", self.status_label.text())

    def _offer_resume(self) -> None:
        sessions = self.session_store.unfinished_sessions()
        if not sessions or (self.thread and self.thread.isRunning()):
            return
        session = sessions[0]
        if (
            QMessageBox.question(
                self,
                "未完了セッション",
                "前回の処理を再開できます。\n"
                f"元: {session['source']}\n"
                f"先: {session['destination']}\n"
                f"状態: {session['status']}\n\n再開候補を読み込みますか？",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        token = self.token = CancellationToken()
        service = ResumeService(self.session_store)
        self._run(
            lambda _progress: service.prepare(
                session["session_id"], cancellation=token
            ),
            self._resume_ready,
        )

    def _resume_ready(self, result: Any) -> None:
        self.scan_result = result
        self.source_edit.setText(str(result.source))
        self.destination_edit.setText(str(result.destination))
        self.scan_result = result
        self.copy_button.setEnabled(True)
        self.status_label.setText(
            f"再開準備完了: コピー予定 {result.summary.copy_planned} / "
            f"既存検証済み {sum(r.status in {'verified', 'already_verified'} for r in result.records)}"
        )

    def _verify(self) -> None:
        archive = self.destination_edit.text().strip()
        if not archive:
            archive = QFileDialog.getExistingDirectory(self, "検証するアーカイブを選択")
        if not archive:
            return
        token = self.token = CancellationToken()
        self._run(
            lambda progress: VerifyService().verify(
                Path(archive), cancellation=token, progress=progress
            ),
            lambda result: QMessageBox.information(
                self,
                "再検証完了",
                f"確認 {len(result.items)} 件 / 追加 {len(result.added_files)} 件\n"
                f"結果: {'成功' if result.ok else '不一致あり'}",
            ),
        )

    def _disc_plan(self) -> None:
        archive = self.destination_edit.text().strip()
        if not archive:
            archive = QFileDialog.getExistingDirectory(self, "アーカイブを選択")
        if not archive:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("M-DISC 容量")
        layout = QFormLayout(dialog)
        preset = QComboBox()
        preset.addItems(["25 GB", "50 GB", "100 GB", "カスタム容量"])
        capacity = QSpinBox()
        capacity.setRange(1, 2_000_000)
        capacity.setSuffix(" MB")
        capacity.setValue(self.config.disc_capacity_bytes // 1_000_000)
        values = {"25 GB": 23_000, "50 GB": 46_000, "100 GB": 92_000}
        preset.currentTextChanged.connect(
            lambda text: capacity.setValue(values[text]) if text in values else None
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow("プリセット:", preset)
        layout.addRow("最大使用容量:", capacity)
        layout.addRow(buttons)
        if not dialog.exec():
            return
        self.config.disc_capacity_bytes = capacity.value() * 1_000_000
        self.config_store.save(self.config)
        service = DiscPlanService()
        self.token = CancellationToken()
        self._run(
            lambda _progress: service.plan(
                Path(archive), self.config.disc_capacity_bytes
            ),
            lambda volumes: QMessageBox.information(
                self,
                "分割計画完了",
                f"{len(volumes)} 枚の計画を reports フォルダへ保存しました。\n"
                "ステージングは CLI の plan-disc --staging で明示的に作成できます。",
            ),
        )

    def _settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            self.config.exiftool_path = dialog.exiftool.text().strip()
            self.config.include_unsupported = dialog.include_unsupported.isChecked()
            self.config.custom_date_fields = dialog.date_fields.text().strip()
            self.config.photo_extensions = self._parse_extensions(
                dialog.photo_extensions.text()
            )
            self.config.video_extensions = self._parse_extensions(
                dialog.video_extensions.text()
            )
            self.config.sidecar_extensions = self._parse_extensions(
                dialog.sidecar_extensions.text()
            )
            self.config.log_level = dialog.log_level.currentText()
            self.config_store.save(self.config)
            self._invalidate_scan()

    @staticmethod
    def _parse_extensions(value: str) -> tuple[str, ...]:
        extensions = []
        for item in value.replace(",", " ").split():
            normalized = item.lower()
            extensions.append(
                normalized if normalized.startswith(".") else f".{normalized}"
            )
        return tuple(sorted(set(extensions)))

    def _open_logs(self) -> None:
        log_dir = user_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "ArchiveNest について",
            f"<h2>ArchiveNest {__version__}</h2>"
            "<p>写真・動画の長期保存準備を行う、コピー専用の独立プロジェクトです。</p>"
            "<p>ArchiveNest is independently based on Phockup. It is not an official "
            "Phockup release and is not endorsed by its original author.</p>"
            "<p>Phockup: Copyright © 2017 Ivan Dokov, MIT License.</p>",
        )

    def _cancel(self) -> None:
        if self.token:
            self.token.cancel()
            self.status_label.setText("キャンセルを要求しました。安全な位置で停止します。")

    @Slot(str, int, int, str)
    def _progress(self, phase: str, current: int, total: int, path: str) -> None:
        self.phase_label.setText(phase)
        self.progress_bar.setValue(int(current * 100 / total) if total else 0)
        self.current_label.setText(path)
        self.current_label.setToolTip(path)
        self.counters_label.setText(f"処理済み {current} / {total}")
        self.log_view.append(f"[{phase}] {current}/{total} {path}")

    def _failed(self, details: str) -> None:
        self.status_label.setText("エラーが発生しました")
        QMessageBox.critical(self, "エラー", details)

    def _cancelled(self) -> None:
        self.status_label.setText("キャンセルされました。完了済みファイルは保持されています。")

    def _tick(self) -> None:
        self.elapsed_seconds += 1
        self.elapsed_label.setText(f"{self.elapsed_seconds} 秒")

    def closeEvent(self, event: Any) -> None:
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(self, "処理中", "先にキャンセルし、安全に停止するまでお待ちください。")
            event.ignore()
            return
        self.config.window_width = self.width()
        self.config.window_height = self.height()
        self._config_from_ui()
        self.config_store.save(self.config)
        event.accept()


def main() -> int:
    log_dir = user_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "ArchiveNest.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("ArchiveNest")
    application.setOrganizationName("ArchiveNest")
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
