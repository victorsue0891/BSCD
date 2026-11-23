from __future__ import annotations

from pathlib import Path
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .domain import Batch, CAConfig, CVConfig, RGB, Well
from .protocol import parse_line, scan_command
from .storage import SessionStore
from .transports import DemoTransport, ReplayTransport, Transport


ACTIVE = {"configuring", "await_start", "running", "stopping", "replaying", "between_columns"}


class Controller(QObject):
    changed = pyqtSignal()
    message = pyqtSignal(str)
    log_line = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, data_root: Path, parent=None, diagnostics=None):
        super().__init__(parent)
        self.data_root = data_root
        self.diagnostics = diagnostics
        self.transport: Transport | None = None
        self.batch: Batch | None = None
        self.store: SessionStore | None = None
        self.firmware = "unknown"
        self.columns = []
        self.current_wells = set()
        self.config_ok = False
        self.hardware_uncertain = False
        self.storage_failed = False
        self.recovery_exported = False
        self.replay_segment = set()
        self.replay_unfinished = False
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._timed_out)

    @property
    def busy(self):
        return self.batch is not None and self.batch.state in ACTIVE

    def diagnostic(self, kind, **fields):
        if self.diagnostics:
            self.diagnostics.record(kind, **fields)

    def _transport_diagnostic(self, kind, fields):
        self.diagnostic(kind, source=self.transport.source if self.transport else "serial", **fields)

    @property
    def connection_text(self):
        if self.hardware_uncertain:
            return "連線異常／停止狀態待確認"
        if not self.transport or not self.transport.connected:
            return "未連線"
        if self.transport.source != "serial":
            return f"{self.transport.source.upper()} · FW {self.firmware}"
        if self.firmware == "unknown":
            return "串口已開啟 · 等待主板版本"
        if self.firmware != "028":
            return f"版本不支援 · FW {self.firmware}"
        return "已收到主板版本 · FW 028"

    @property
    def ready(self):
        return bool(self.transport and self.transport.connected and not self.hardware_uncertain
                    and (self.transport.source == "demo" or
                         (self.transport.source == "serial" and self.firmware == "028")))

    def connect_transport(self, transport: Transport):
        if self.busy or self.hardware_uncertain:
            raise ValueError("請先停止量測並確認設備已停止")
        self.disconnect()
        self.transport = transport
        self.firmware = "unknown"
        self.diagnostic("connection_attempt", source=transport.source)
        transport.diagnostic.connect(self._transport_diagnostic)
        transport.line.connect(self.receive)
        transport.error.connect(self.fault)
        transport.finished.connect(self._transport_finished)
        try:
            transport.open()
        except Exception:
            transport.close()
            transport.diagnostic.disconnect(self._transport_diagnostic)
            self.transport = None
            raise
        self.diagnostic("connection_open", source=transport.source, firmware=self.firmware)
        self.changed.emit()

    def disconnect(self):
        if self.busy:
            raise ValueError("量測中不能切換連線")
        if self.transport:
            self.transport.close()
            self.transport.line.disconnect(self.receive)
            self.transport.error.disconnect(self.fault)
            self.transport.finished.disconnect(self._transport_finished)
            self.transport.diagnostic.disconnect(self._transport_diagnostic)
            self.transport.deleteLater()
            self.transport = None
        self.firmware = "unknown"
        self.changed.emit()

    def start(self, mode: str, config, rgb: RGB, selected: set[Well]):
        if self.busy or self.hardware_uncertain:
            raise ValueError("設備仍忙碌或停止狀態未確認")
        if not self.transport or not self.transport.connected:
            raise ValueError("請先連線或使用模擬模式")
        if self.transport.source == "replay":
            raise ValueError("重播連線不能開始新的量測，請切換模擬或 UART")
        if not selected:
            raise ValueError("請至少選擇一個孔位")
        if mode not in ("CV", "CA") or (mode == "CV") != isinstance(config, CVConfig):
            raise ValueError("模式與參數不一致")
        config.validate()
        if self.transport.source == "serial":
            if mode == "CA":
                raise ValueError("CA 實機命令、電壓及資料格式待確認；目前提供模擬操作")
            if self.firmware != "028":
                raise ValueError("尚未收到 FW_VERSION: 028；請等待設備開機回覆或重新連線")
            for x in {w.x for w in selected}:
                if {w.y for w in selected if w.x == x} != set(range(8)):
                    raise ValueError("FW 028 尚無部分選孔契約；實機請選完整欄（8 孔）")
        self._new_batch(Batch(mode, self.transport.source, set(selected), config, rgb, firmware=self.firmware))
        self.columns = sorted({w.x for w in selected})
        self.config_ok = False
        if isinstance(self.transport, DemoTransport):
            self.transport.prepare(config, selected)
        if mode == "CA":
            self.current_wells = set(selected)
            self._state("await_start")
            self._send("DEMO_CA_START")
        else:
            self._state("configuring")
            self._send(config.command)

    def replay(self, path: Path):
        if self.busy:
            raise ValueError("量測中不能開啟重播")
        if self.hardware_uncertain:
            raise ValueError("請先確認設備已停止")
        if self.storage_failed and not self.recovery_exported:
            raise ValueError("前一批資料存檔失敗，請先 Save data 至其他位置")
        # Infer wells from evidence; never assign the source coordinates as YX.
        wells = set()
        with path.open(encoding="utf-8-sig", errors="replace") as f:
            for raw in f:
                event = parse_line(raw.rstrip("\r\n"))
                if event.kind == "sample":
                    wells.add(event.value.well)
        if not wells:
            raise ValueError("檔案中沒有 FW 028 XS_FUD 量測資料")
        transport = ReplayTransport(path, self)
        self.connect_transport(transport)
        self._new_batch(Batch("CV", "replay", wells, CVConfig(), RGB()))
        # The original settings reply and raw log are authoritative for replay.
        self.batch.settings_reply["replay_file"] = str(path.resolve())
        self.batch.settings_reply["config_is_placeholder"] = True
        self.current_wells = wells
        self.replay_segment = set()
        self.replay_unfinished = False
        self._state("replaying")
        transport.play()

    def _new_batch(self, batch):
        # Create the journal before any command is sent.
        if self.storage_failed and not self.recovery_exported:
            raise ValueError("前一批資料存檔失敗，請先 Save data 至其他位置")
        if self.store:
            self.store.close()
        self.batch = batch
        if self.diagnostics:
            batch.settings_reply["diagnostics_session"] = self.diagnostics.session_id
        batch.well_states = {w: "queued" for w in batch.selected}
        self.storage_failed = False
        self.recovery_exported = False
        self.store = None
        try:
            self.store = SessionStore(self.data_root, batch)
            self.diagnostic("batch_start", batch_id=batch.id, metadata=batch.metadata())
        except OSError as exc:
            batch.state = "fault"
            batch.reason = f"無法建立資料目錄：{exc}"
            raise ValueError(batch.reason) from exc

    def _state(self, state: str):
        self.batch.state = state
        self.diagnostic("measurement_state", batch_id=self.batch.id, state=state)
        self.timeout.stop()
        if state in ("configuring", "await_start", "stopping"):
            self.timeout.start(8000)
        elif state == "running":
            self.timeout.start(30000)
        self.changed.emit()

    def _send(self, command):
        self.diagnostic("command_requested", command=command,
                        source=self.transport.source if self.transport else "unknown")
        try:
            if self.store and not self.storage_failed:
                self.store.record("TX", command)
            self.log_line.emit(f"> {command}")
            self.transport.send(command)
        except (OSError, ValueError) as exc:
            self.fault(str(exc))

    def receive(self, raw: str):
        self.diagnostic("uart_rx_line", line=raw,
                        source=self.transport.source if self.transport else "unknown")
        event = parse_line(raw)
        if event.kind in ("invalid", "error"):
            self.diagnostic("protocol_error", line=raw, category=event.kind)
        if self.store and not self.storage_failed:
            try:
                self.store.record("RX", raw)
            except OSError as exc:
                # Preserve the triggering sample in RAM even if the disk fails.
                if self.busy and event.kind == "sample" and event.value.well in self.current_wells:
                    self.batch.samples.setdefault(event.value.well, []).append(event.value)
                self.storage_failed = True
                self.fault(f"資料寫入失敗：{exc}")
                return
        if event.kind not in ("sample", "log"):
            self.log_line.emit(raw)
        if event.kind == "firmware":
            version_changed = self.firmware != event.value
            self.firmware = event.value
            self.diagnostic("firmware_received", firmware=self.firmware,
                            supported=self.firmware == "028")
            if self.batch and self.busy:
                self.batch.firmware = self.firmware
            if version_changed:
                self.changed.emit()
            return
        if event.kind == "boot" and self.transport and self.transport.source == "serial":
            self.firmware = "unknown"
            self.diagnostic("board_boot", line=raw)
            self.changed.emit()
        if not self.busy:
            return
        state = self.batch.state
        if event.kind == "boot" and self.batch.source != "replay":
            self.fault("量測期間 ESP32 重新開機；部分資料已保留")
        elif event.kind in ("error", "invalid"):
            self.fault(f"設備或資料錯誤：{event.value}")
        elif event.kind == "settings":
            self.batch.settings_reply.update(event.value)
            self._config_ready()
        elif event.kind == "config_ok" and state == "configuring":
            self.config_ok = True
            self._config_ready()
        elif event.kind == "start" and state == "await_start":
            for well in self.current_wells:
                self.batch.well_states[well] = "running"
            self._state("running")
        elif event.kind == "start" and state == "replaying":
            self.replay_segment = set()
            self.replay_unfinished = True
        elif event.kind == "sample":
            sample = event.value
            if state not in ("running", "stopping", "replaying"):
                self.fault("未收到 START 就收到量測資料")
                return
            if sample.well not in self.current_wells:
                self.fault(f"收到未排程孔位 {sample.well.label}；原始訊息已保留")
                return
            points = self.batch.samples.setdefault(sample.well, [])
            points.append(sample)
            if state == "replaying":
                self.replay_segment.add(sample.well)
                self.replay_unfinished = True
            self.batch.well_states[sample.well] = "running" if state != "stopping" else "interrupted"
            if state == "running":
                self.timeout.start(30000)
        elif event.kind == "end":
            if state == "running":
                self.batch.settings_reply[f"column_{min(w.x for w in self.current_wells)}_end"] = event.value
                if any(not self.batch.samples.get(w) for w in self.current_wells):
                    self.fault("收到 END，但本欄有孔位沒有資料")
                    return
                for well in self.current_wells:
                    self.batch.well_states[well] = "complete"
                self.timeout.stop()
                # Leave running immediately to reject duplicate END events.
                self._state("between_columns")
                if self.batch.mode == "CA":
                    self._finish("complete")
                else:
                    QTimer.singleShot(0, self._next_column)
            elif state == "stopping":
                self._finish("interrupted", "使用者停止；部分資料保留")
            elif state == "replaying":
                # A log may contain multiple columns; EOF completes the replay.
                for well in self.replay_segment:
                    self.batch.well_states[well] = "complete"
                self.batch.settings_reply["observed_end"] = event.value
                self.replay_segment = set()
                self.replay_unfinished = False

    def _config_ready(self):
        if self.batch.state != "configuring":
            return
        required = {"REAL_STEP", "STEP_TIME", "APPVREF_RST", "APPVBASE_RST"}
        if self.config_ok and required.issubset(self.batch.settings_reply):
            self._next_column()

    def _next_column(self):
        if not self.batch or self.batch.state not in ("configuring", "between_columns"):
            return
        if not self.columns:
            self._finish("complete")
            return
        x = self.columns.pop(0)
        self.current_wells = {w for w in self.batch.selected if w.x == x}
        self._state("await_start")
        self._send(scan_command(x, self.batch.rgb))

    def stop(self):
        if not self.busy:
            return
        if self.batch.source == "replay":
            self.transport.close()
            self._finish("interrupted", "停止重播")
        else:
            self._state("stopping")
            self._send("Q")

    def _transport_finished(self):
        if not self.busy:
            return
        if self.batch.state == "stopping" and self.batch.source == "demo":
            self._finish("interrupted", "模擬量測已停止")
        elif self.batch.source == "replay":
            if "observed_end" not in self.batch.settings_reply or self.replay_unfinished:
                self._finish("interrupted", "紀錄未包含 END；保留已讀取資料")
            else:
                self._finish("complete")

    def _timed_out(self):
        self.diagnostic("response_timeout", state=self.batch.state if self.batch else "idle")
        self.fault("等待設備回覆逾時；未自動重送掃描命令")

    def fault(self, reason: str):
        self.diagnostic("fault", reason=reason, busy=self.busy)
        if not self.busy:
            if self.transport and self.transport.source == "serial":
                self.hardware_uncertain = True
            self.message.emit(reason)
            self.changed.emit()
            return
        self.hardware_uncertain = self.batch.source == "serial"
        self.timeout.stop()
        self.batch.state = "fault"
        self.batch.reason = reason
        for well, state in list(self.batch.well_states.items()):
            if state == "running":
                self.batch.well_states[well] = "interrupted"
        if self.transport.source == "serial":
            try:
                self.transport.send("Q")
                if self.store and not self.storage_failed:
                    self.store.record("TX", "Q")
            except (OSError, ValueError):
                pass
        else:
            self.transport.close()
        self._persist()
        self.message.emit(reason)
        self.changed.emit()
        self.finished.emit()

    def _finish(self, state, reason=""):
        self.timeout.stop()
        self.batch.state = state
        self.batch.reason = reason
        if state != "complete":
            for well, status in list(self.batch.well_states.items()):
                if status == "running":
                    self.batch.well_states[well] = "interrupted"
        self._persist()
        self.changed.emit()
        self.finished.emit()

    def _persist(self):
        if self.store and not self.storage_failed:
            try:
                self.store.checkpoint()
                if self.batch.samples:
                    self.store.export()
            except OSError as exc:
                self.storage_failed = True
                self.message.emit(f"自動存檔失敗，資料仍在記憶體，請另存至其他位置：{exc}")

        if self.batch:
            self.diagnostic("batch_end", batch_id=self.batch.id, metadata=self.batch.metadata())

    def acknowledge_stopped(self):
        if self.busy:
            raise ValueError("請先等待停止回覆或逾時")
        self.hardware_uncertain = False
        self.disconnect()

    def close(self):
        self.timeout.stop()
        if self.transport:
            self.transport.close()
        if self.store:
            self.store.close()
