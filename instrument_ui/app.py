from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QMainWindow, QMessageBox, QPlainTextEdit, QVBoxLayout,
)

from .controller import Controller
from .diagnostics import Diagnostics
from .diagnostics_ui import DiagnosticsDialog
from .domain import ALL_WELLS, CAConfig, CVConfig, RGB, Well
from .transports import DemoTransport, SerialTransport
from .screens import STYLE, ReferenceScreens, button, label


class MainWindow(ReferenceScreens, QMainWindow):
    def __init__(self, data_root: Path, diagnostics_root: Path | None = None, startup=None):
        super().__init__()
        self.setWindowTitle("PIMEX · 光電磁電化學轉換裝置")
        self.resize(800, 600)
        self.setMinimumSize(800, 480)
        self.diagnostics = Diagnostics(diagnostics_root or data_root.parent / "diagnostics", startup=startup)
        self.controller = Controller(data_root, self, diagnostics=self.diagnostics)
        self.controller.changed.connect(self.refresh)
        self.controller.message.connect(self.show_message)
        self.controller.log_line.connect(self.log)
        self.controller.finished.connect(self.on_finished)
        self.mode = "CV"
        self.display_batch = None
        self.last_export = None
        self.recovery_saved = False
        self.controls = []
        self._last_log = None
        self._repeat_logs = 0
        self._diagnostic_warning = ""
        self._last_connection = ""
        self.diagnostics_dialog = None
        self.startup_serial_timer = QTimer(self)
        self.startup_serial_timer.setInterval(2000)
        self.startup_serial_timer.timeout.connect(self._try_startup_serial)
        self.startup_serial_target = None
        self.startup_serial_error = None
        self.construct_shell()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(200)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()
        self.refresh()

    def choose_mode(self, mode):
        if self.controller.busy:
            return
        self.mode = mode
        self.show_page(1 if mode == "CV" else 2)
        self.refresh()

    def show_page(self, index):
        if self.controller.busy and index != 4:
            return
        self.pages.setCurrentIndex(index)

    def cv_config(self):
        return CVConfig(self.slope.currentData(), round(self.upper.value() * 1000),
                        round(self.lower.value() * 1000), int(self.resolution.currentText()))

    def ca_config(self):
        return CAConfig(self.duration.value(), self.interval.value(), self.ca_initial.value(), self.ca_target.value())

    def rgb(self):
        return RGB(*(self.rgb_spins[c].value() for c in "RGB"))

    def settings_next(self):
        try:
            (self.cv_config() if self.mode == "CV" else self.ca_config()).validate()
            self.show_page(3)
        except ValueError as exc:
            self.show_message(str(exc))

    def reset_cv(self):
        self.slope.setCurrentIndex(self.slope.findData(15))
        self.upper.setValue(2.5)
        self.lower.setValue(-2.5)
        self.resolution.setCurrentText("1024")

    def reset_rgb(self):
        for spin in self.rgb_spins.values():
            spin.setValue(0)

    def update_rgb_preview(self):
        rgb = self.rgb()
        light = (rgb.r * 299 + rgb.g * 587 + rgb.b * 114) / 1000 > 140
        self.rgb_preview.setStyleSheet(
            f"background:rgb({rgb.r},{rgb.g},{rgb.b});color:{'#253246' if light else 'white'};border-radius:8px;"
        )
        self.rgb_preview.setText(f"RGB {rgb.r} · {rgb.g} · {rgb.b}")

    def connect_demo(self):
        self.cancel_startup_serial()
        try:
            self.controller.connect_transport(DemoTransport(self.controller))
            self.status_text.setText("模擬模式 · 加速展示，曲線與分色不代表實際量測")
        except (ValueError, OSError) as exc:
            self.show_message(str(exc))

    def cancel_startup_serial(self):
        self.startup_serial_timer.stop()
        self.startup_serial_target = None

    def connect_startup_serial(self, port, ending="LF"):
        """Wait for a late USB device; never resume acquisition or reconnect after loss."""
        self.startup_serial_target = (port, ending)
        self.startup_serial_error = None
        self.startup_serial_timer.start()
        self._try_startup_serial()

    def _try_startup_serial(self):
        if self.startup_serial_target is None:
            return
        if self.controller.transport or self.controller.busy or self.controller.hardware_uncertain:
            self.cancel_startup_serial()
            return
        port, ending = self.startup_serial_target
        transport = SerialTransport(port, ending, self.controller)
        try:
            self.controller.connect_transport(transport)
        except (OSError, ValueError) as exc:
            transport.deleteLater()
            message = f"等待 UART {port}：{exc}（每 2 秒重試，可由連線設定切換）"
            self.status_text.setText(message)
            if message != self.startup_serial_error:
                self.log(message)
                self.startup_serial_error = message
            return
        self.cancel_startup_serial()
        message = f"串口已開啟：{port} · 115200 / 8N1 / {ending} · 等待主板版本 FW_VERSION: 028"
        self.status_text.setText(message)
        self.log(message)

    def connection_dialog(self):
        self.cancel_startup_serial()
        dialog = QDialog(self)
        dialog.setWindowTitle("連線設定")
        dialog.setMinimumWidth(450)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("ESP32 UART · 115200 / 8N1 / 無流量控制", "pageTitle"))
        ports = QComboBox()
        ports.setEditable(True)
        ports.addItems(SerialTransport.ports() or ["/dev/serial0", "/dev/ttyUSB0", "/dev/ttyACM0"])
        form = QFormLayout()
        form.addRow("連接埠", ports)
        ending = QComboBox()
        ending.addItems(["LF", "CRLF"])
        form.addRow("送出換行", ending)
        layout.addLayout(form)
        layout.addWidget(label("連線後請等待 FW_VERSION: 028。換行格式需依實機確認。", "muted"))
        def connect_serial():
            try:
                port = ports.currentText().strip()
                if not port:
                    raise ValueError("請輸入連接埠")
                self.controller.connect_transport(SerialTransport(port, ending.currentText(), self.controller))
                dialog.accept()
            except (OSError, ValueError) as exc:
                self.show_message(str(exc))
        layout.addWidget(button("連接 UART", connect_serial, "primary"))
        layout.addWidget(button("切換模擬器", lambda: (self.connect_demo(), dialog.accept())))
        if self.controller.hardware_uncertain:
            layout.addWidget(label("停止狀態未確認；請在實機確認量測停止後再恢復連線。", "notice"))
            layout.addWidget(button("我已確認設備停止 · 清除連線", lambda: (self.controller.acknowledge_stopped(), dialog.accept())))
        layout.addWidget(button("關閉", dialog.reject))
        dialog.exec()

    def start_measurement(self):
        try:
            if self.display_batch:
                raise ValueError("請先按 CLR all 開始新批次；先前資料已自動保留")
            config = self.cv_config() if self.mode == "CV" else self.ca_config()
            self.controller.start(self.mode, config, self.rgb(), set(self.plate.selected))
            self.recovery_saved = False
            self.display_batch = self.controller.batch
            self.plate.batch = self.display_batch
            self.refresh()
        except (OSError, ValueError) as exc:
            self.show_message(str(exc))

    def select_all(self):
        if not self.controller.busy and not self.display_batch:
            self.plate.selected = set(ALL_WELLS)
            self.plate.update()
            self.refresh()

    def clear_plate(self):
        if self.controller.busy:
            return
        if self.display_batch and self.controller.storage_failed and not self.recovery_saved:
            self.show_message("資料尚未成功存檔；請先 Save data 至可寫入位置")
            return
        self.display_batch = None
        self.plate.batch = None
        self.plate.selected.clear()
        self.refresh()

    def inspect_well(self, well):
        if self.controller.busy:
            return
        if self.display_batch and self.display_batch.samples.get(well):
            self.mode = self.display_batch.mode
            self.result_page.set_batch(self.display_batch, well)
            self.show_page(5)

    def export_data(self, wells=None):
        if not self.display_batch or not self.display_batch.samples or not self.controller.store:
            return
        destination = QFileDialog.getExistingDirectory(self, "選擇資料儲存位置", str(self.controller.data_root))
        if not destination:
            return
        try:
            self.last_export = self.controller.store.export(Path(destination), wells)
            if wells is None:
                self.recovery_saved = True
                self.controller.recovery_exported = True
            self.status_text.setText(f"已儲存：{self.last_export}")
        except OSError as exc:
            self.show_message(f"儲存失敗，資料仍保留在記憶體：{exc}")

    def open_replay(self):
        self.cancel_startup_serial()
        path, _ = QFileDialog.getOpenFileName(self, "選擇 FW 028 通訊紀錄", str(Path.cwd()), "Text logs (*.txt *.log);;All files (*)")
        if not path:
            return
        try:
            self.controller.replay(Path(path))
            self.recovery_saved = False
            self.mode = "CV"
            self.display_batch = self.controller.batch
            self.plate.batch = self.display_batch
            self.plate.selected = set(self.display_batch.selected)
            self.show_page(4)
            self.refresh()
        except (OSError, ValueError) as exc:
            self.show_message(str(exc))

    def save_profile(self):
        import json
        from dataclasses import asdict
        try:
            config = self.cv_config()
            config.validate()
            path, _ = QFileDialog.getSaveFileName(self, "儲存 CV 參數", "cv-profile.json", "JSON (*.json)")
            if path:
                Path(path).write_text(json.dumps({"cv": asdict(config), "rgb": asdict(self.rgb())}, indent=2), encoding="utf-8")
                self.status_text.setText("參數已儲存")
        except (OSError, ValueError) as exc:
            self.show_message(str(exc))

    def load_profile(self):
        import json
        try:
            path, _ = QFileDialog.getOpenFileName(self, "載入 CV 參數", "", "JSON (*.json)")
            if not path:
                return
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            config, rgb = CVConfig(**data["cv"]), RGB(**data["rgb"])
            config.validate()
            self.slope.setCurrentIndex(self.slope.findData(config.slope))
            self.upper.setValue(config.upper_mv / 1000)
            self.lower.setValue(config.lower_mv / 1000)
            self.resolution.setCurrentText(str(config.resolution))
            for name in "RGB":
                self.rgb_spins[name].setValue(getattr(rgb, name.lower()))
            self.status_text.setText("參數已載入")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.show_message(f"參數檔格式錯誤：{exc}")

    def log(self, text):
        if text == self._last_log:
            self._repeat_logs += 1
            return
        if self._repeat_logs:
            self.log_view.appendPlainText(f"上一訊息另重複 {self._repeat_logs} 次（原始診斷紀錄逐筆保留）")
        self._last_log = text
        self._repeat_logs = 0
        self.log_view.appendPlainText(text)
        logging.getLogger(__name__).info(text)

    def log_dialog(self):
        dialog = DiagnosticsDialog(self.diagnostics, self.log_view, self)
        self.diagnostics_dialog = dialog
        try:
            dialog.exec()
        finally:
            self.log_view.setParent(None)
            self.diagnostics_dialog = None
            dialog.deleteLater()

    def show_message(self, message):
        self.diagnostics.record("ui_message", message=message)
        self.status_text.setText(message)
        # Non-modal status reporting keeps acquisition and Stop responsive.
        box = QMessageBox(QMessageBox.Icon.Warning, "操作訊息", message, parent=self)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.open()

    def on_finished(self):
        if self.controller.store:
            self.status_text.setText(f"批次 {self.controller.batch.state} · 資料目錄：{self.controller.store.path}")
        self.refresh()

    def refresh(self):
        if not hasattr(self, "plate"):
            return
        controller = self.controller
        busy = controller.busy
        transport = controller.transport
        source = transport.source.upper() if transport and transport.connected else "未連線"
        connection = controller.connection_text
        if self.startup_serial_target and not controller.transport:
            connection = "等待串口裝置 · 每 2 秒重試"
        self.connection_status.setText(connection)
        self.connection_status.setToolTip(connection)
        self.status_text.setToolTip(connection)
        if connection != self._last_connection:
            self._last_connection = connection
            if source == "SERIAL" and not busy:
                self.status_text.setText(connection)
        warning = self.diagnostics.warning
        if warning:
            self.connection_status.setText(connection + " · 診斷紀錄異常")
            self.connection_status.setToolTip(connection + "\n" + warning)
            if warning != self._diagnostic_warning:
                self._diagnostic_warning = warning
                self.status_text.setText(warning)
        self.pages.widget(0).connection_label.setText(connection + (" · 診斷紀錄異常，請開啟通訊紀錄" if warning else ""))
        self.pages.widget(0).connection_label.setToolTip(warning or connection)
        self.plate.locked = busy
        self.plate_title.setText(f"{self.mode} · 96 孔" + (" · 模擬／重播" if source in ("DEMO", "REPLAY") else ""))
        self.selection_label.setText(f"已選 {len(self.plate.selected)} / 96 孔")
        rgb = self.rgb()
        self.rgb_summary.setText(f"RGB {rgb.r} / {rgb.g} / {rgb.b}")
        for name, block in self.plate_rgb.items():
            block.setText(str(getattr(rgb, name.lower())))
        self.update_chrome(self.pages.currentIndex())
        for widget in [self.home_btn, self.connect_btn, self.demo_btn, self.replay_btn, self.back_btn, *self.controls]:
            widget.setEnabled(not busy)
        self.select_btn.setEnabled(not busy and self.display_batch is None)
        self.clear_btn.setEnabled(not busy)
        self.start_btn.setEnabled(not busy and controller.ready and self.display_batch is None
                                  and bool(self.plate.selected)
                                  and not (source == "SERIAL" and self.mode == "CA"))
        self.stop_btn.setEnabled(busy and controller.batch.state != "stopping")
        self.save_btn.setEnabled(not busy and bool(self.display_batch and self.display_batch.samples))
        batch = self.display_batch
        if batch:
            done = sum(state == "complete" for state in batch.well_states.values())
            count = sum(len(samples) for samples in batch.samples.values())
            self.progress.setRange(0, len(batch.selected))
            self.progress.setValue(done)
            states = {"configuring": "傳送設定", "await_start": "等待開始", "running": "量測中", "replaying": "重播中",
                      "stopping": "等待停止回覆", "complete": "已收到結束", "interrupted": "已中止", "fault": "異常"}
            self.measure_status.setText(f"{states.get(batch.state, batch.state)} · {done}/{len(batch.selected)} 孔結束 · {count:,} 筆" +
                                        (" · 展示分色" if batch.source == "demo" and batch.mode == "CV" else " · 原始值未校正"))
        else:
            self.progress.setRange(0, 96)
            self.progress.setValue(0)
            self.measure_status.setText("點欄號可選取整欄；完成後點孔位檢視曲線。")
        self.plate.update()

    def closeEvent(self, event):
        if self.diagnostics_dialog and self.diagnostics_dialog.worker and self.diagnostics_dialog.worker.isRunning():
            self.status_text.setText("請先等待診斷匯出完成或取消匯出，再關閉程式")
            event.ignore()
            return
        if self.controller.busy:
            self.controller.stop()
            self.status_text.setText("已要求停止；待回覆或逾時後再關閉視窗")
            event.ignore()
            return
        if self.controller.storage_failed and self.display_batch and not self.recovery_saved:
            self.show_message("資料存檔失敗；請先 Save data 至可寫入位置再關閉")
            event.ignore()
            return
        self.controller.close()
        self.cancel_startup_serial()
        self.diagnostics.close()
        event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Raspberry Pi PyQt6 instrument UI")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="Start with accelerated synthetic measurements")
    source.add_argument("--port", help="Connect to this UART on startup (e.g. /dev/ttyACM0)")
    source.add_argument("--replay", type=Path)
    parser.add_argument("--line-ending", choices=("LF", "CRLF"), default="LF")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "PIMEX" / "data")
    parser.add_argument("--diagnostics-dir", type=Path, help="Diagnostic log directory (default: data-dir sibling diagnostics)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Noto Sans CJK TC", 10))
    window = MainWindow(args.data_dir.expanduser(),
                        args.diagnostics_dir.expanduser() if args.diagnostics_dir else None,
                        startup={"port": args.port, "line_ending": args.line_ending,
                                 "demo": args.demo, "fullscreen": args.fullscreen,
                                 "replay": bool(args.replay), "data_dir": str(args.data_dir.expanduser())})
    app.aboutToQuit.connect(window.diagnostics.close)
    if args.demo:
        window.connect_demo()
    if args.fullscreen:
        window.showFullScreen()
    else:
        window.show()
    if args.port:
        QTimer.singleShot(0, lambda: window.connect_startup_serial(args.port, args.line_ending))
    if args.replay:
        def replay():
            try:
                window.controller.replay(args.replay)
                window.display_batch = window.controller.batch
                window.plate.batch = window.display_batch
                window.plate.selected = set(window.display_batch.selected)
                window.show_page(4)
            except (OSError, ValueError) as exc:
                window.show_message(str(exc))
        QTimer.singleShot(0, replay)
    return app.exec()
