"""Qt export UI. USB media must already be mounted by the desktop/system."""
from pathlib import Path

from PyQt6.QtCore import QStorageInfo, QThread, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QVBoxLayout,
)

from .diagnostics import export_diagnostics


class ExportWorker(QThread):
    progress = pyqtSignal(int)
    result = pyqtSignal(str, str)

    def __init__(self, recorder, session_id, destination, parent=None):
        super().__init__(parent)
        self.recorder = recorder
        self.session_id = session_id
        self.destination = Path(destination).resolve()
        volume = QStorageInfo(str(self.destination))
        self.identity = (bytes(volume.device()), volume.rootPath())

    def check_destination(self):
        volume = QStorageInfo(str(self.destination))
        volume.refresh()
        if (not self.destination.is_dir() or not volume.isValid() or not volume.isReady()
                or volume.isReadOnly() or (bytes(volume.device()), volume.rootPath()) != self.identity):
            raise OSError("儲存裝置已移除、無法寫入或掛載狀態改變，請重新選擇")

    def run(self):
        try:
            path = export_diagnostics(self.recorder, self.session_id, self.destination,
                                      progress=self.progress.emit,
                                      check_destination=self.check_destination,
                                      cancelled=self.isInterruptionRequested)
            self.result.emit(str(path), "")
        except Exception as exc:
            self.result.emit("", str(exc))


class DiagnosticsDialog(QDialog):
    def __init__(self, recorder, log_view, parent=None):
        super().__init__(parent)
        self.recorder = recorder
        self.worker = None
        self.setWindowTitle("通訊紀錄與 USB 匯出")
        self.resize(760, min(560, parent.height() - 20) if parent else 560)
        layout = QVBoxLayout(self)
        self.health = QLabel()
        self.health.setWordWrap(True)
        health_row = QHBoxLayout()
        health_row.addWidget(self.health, 1)
        self.controller = getattr(parent, "controller", None)
        self.stop_button = QPushButton("停止量測")
        self.stop_button.setObjectName("stop")
        if self.controller:
            self.stop_button.clicked.connect(self.controller.stop)
            self.controller.changed.connect(self.update_health)
        health_row.addWidget(self.stop_button)
        layout.addLayout(health_row)
        layout.addWidget(log_view, 1)
        row = QHBoxLayout()
        self.sessions = QComboBox()
        self.sessions.setMinimumContentsLength(15)
        self.sessions.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(QLabel("紀錄"))
        row.addWidget(self.sessions, 1)
        self.reload_button = QPushButton("重新整理")
        self.reload_button.clicked.connect(self.reload)
        row.addWidget(self.reload_button)
        layout.addLayout(row)
        self.volumes = QComboBox()
        self.volumes.setMinimumContentsLength(20)
        self.volumes.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.volumes.activated.connect(self.choose_volume)
        layout.addWidget(self.volumes)
        row = QHBoxLayout()
        self.destination = QLineEdit()
        self.destination.setReadOnly(True)
        self.destination.setPlaceholderText("選擇已掛載的 USB／SD 卡或其他資料夾")
        row.addWidget(self.destination, 1)
        self.browse_button = QPushButton("選擇資料夾")
        self.browse_button.clicked.connect(self.browse)
        row.addWidget(self.browse_button)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.result = QLabel("Pi 保留原始紀錄；匯出完成後，請從桌面檔案管理員卸載裝置再拔除。")
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        row = QHBoxLayout()
        self.export_button = QPushButton("匯出診斷 ZIP")
        self.export_button.clicked.connect(self.export)
        row.addWidget(self.export_button)
        self.cancel_button = QPushButton("取消匯出")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        self.folder_button = QPushButton("開啟匯出資料夾")
        self.folder_button.setEnabled(False)
        self.folder_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.destination.text())))
        row.addWidget(self.folder_button)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.reject)
        row.addWidget(close_button)
        layout.addLayout(row)
        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self.update_health)
        self.health_timer.start(500)
        self.reload()
        self.update_health()

    @pyqtSlot()
    def update_health(self):
        self.health.setText(self.recorder.warning or "完整診斷持續記錄中；下方顯示最近 500 行狀態訊息。")
        self.stop_button.setEnabled(bool(self.controller and self.controller.busy
                                        and self.controller.batch.state != "stopping"))

    def reload(self):
        self.sessions.clear()
        self.sessions.addItem("本次執行（包含開機及連線紀錄）", self.recorder.session_id)
        for item in self.recorder.sessions():
            if item["session_id"] != self.recorder.session_id:
                suffix = " · 非正常結束／狀態未知" if not item.get("clean_shutdown") else ""
                self.sessions.addItem(item["started_at"] + suffix, item["session_id"])
        self.volumes.clear()
        self.volumes.addItem("選擇已掛載的儲存裝置（未出現時可重新整理）", None)
        for volume in QStorageInfo.mountedVolumes():
            if volume.isValid() and volume.isReady():
                root = volume.rootPath()
                if root == "/" or root.startswith(("/media/", "/run/media/", "/mnt/")) or ":/" in root:
                    state = "唯讀" if volume.isReadOnly() else f"可用 {volume.bytesAvailable() / 1024**3:.2f} GB"
                    self.volumes.addItem(f"{volume.displayName()} · {root} · {state}", root)

    def choose_volume(self, index):
        path = self.volumes.itemData(index)
        if path:
            self.destination.setText(path)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "選擇 USB／SD 卡上的匯出資料夾",
                                                self.destination.text() or str(Path.home()))
        if path:
            self.destination.setText(path)

    def export(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.destination.text():
            self.result.setText("請先選擇已掛載的儲存裝置或資料夾。")
            return
        self.progress.setValue(0)
        self.result.setText("正在建立診斷快照並匯出，請勿拔除裝置。")
        self.folder_button.setEnabled(False)
        self.set_exporting(True)
        if self.worker:
            self.worker.deleteLater()
        self.worker = ExportWorker(self.recorder, self.sessions.currentData(), self.destination.text(), self)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.result.connect(self.export_result)
        self.worker.finished.connect(self.export_finished)
        self.worker.start()

    @pyqtSlot()
    def export_finished(self):
        self.set_exporting(False)

    def set_exporting(self, active):
        for widget in (self.sessions, self.volumes, self.browse_button, self.reload_button, self.export_button):
            widget.setEnabled(not active)
        self.cancel_button.setEnabled(active)

    @pyqtSlot(str, str)
    def export_result(self, path, error):
        if error:
            self.result.setText(f"匯出未完成：{error}。Pi 上的原始紀錄仍保留。")
            self.recorder.record("export_failed", error=error)
        else:
            self.result.setText(f"已完成並檢查：{path}\n請從檔案管理員卸載裝置後再拔除。")
            self.folder_button.setEnabled(True)
            self.recorder.record("export_complete", path=path)

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.result.setText("正在取消匯出，請等待目前磁碟操作結束。")

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.result.setText("匯出尚未結束；請先取消匯出並等待完成，再關閉。")
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
            self.reject()
        else:
            event.accept()
