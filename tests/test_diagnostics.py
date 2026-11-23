import json
from pathlib import Path
import threading
import zipfile

import pytest
from PyQt6.QtTest import QTest

from instrument_ui.app import MainWindow
from instrument_ui.controller import Controller
from instrument_ui.diagnostics import Diagnostics, export_diagnostics
from instrument_ui.diagnostics_ui import DiagnosticsDialog
from instrument_ui.domain import CVConfig, RGB, Well
from instrument_ui.screens import STYLE
from instrument_ui.transports import SerialTransport, Transport


def rows(snapshot):
    return [json.loads(line) for path in snapshot.files for line in path.read_text(encoding="utf-8").splitlines()]


def test_raw_uart_fragments_and_tx_are_captured_before_any_batch(qapp, tmp_path):
    recorder = Diagnostics(tmp_path / "diagnostics")
    transport = SerialTransport("test")
    transport.diagnostic.connect(lambda kind, fields: recorder.record(kind, **fields))
    transport.line.connect(lambda line: recorder.record("uart_rx_line", line=line))

    class Port:
        data = b""
        sent = []

        def readAll(self):
            return self.data

        def write(self, payload):
            self.sent.append(payload)
            return len(payload)

        def close(self):
            pass

        def portName(self):
            return "test"

    transport.port = Port()
    transport.connected = True
    chunks = [b"FW_VER", b"SION: 028\r", b"\nunknown \xff\npartial"]
    for chunk in chunks:
        transport.port.data = chunk
        transport._read()
    transport.send("Q")
    transport.close()
    recorder.close()
    snap = recorder.snapshot(recorder.session_id)
    try:
        events = rows(snap)
        assert b"".join(bytes.fromhex(e["data_hex"]) for e in events if e["kind"] == "uart_rx_bytes") == b"".join(chunks)
        assert [e["line"] for e in events if e["kind"] == "uart_rx_line"] == ["FW_VERSION: 028", "unknown \ufffd"]
        tx = next(e for e in events if e["kind"] == "uart_tx_queued")
        assert bytes.fromhex(tx["data_hex"]) == b"Q\n"
        assert tx["accepted_bytes"] == 2
        assert not any(e["kind"] == "batch_start" for e in events)
        assert all("host_time" in e and "elapsed_s" in e for e in events)
    finally:
        recorder.release(snap)


class Board(Transport):
    source = "serial"

    def __init__(self):
        super().__init__()
        self.commands = []

    def send(self, command):
        self.commands.append(command)


def test_version_status_sends_no_new_commands_and_boot_clears_ready(qapp, tmp_path):
    recorder = Diagnostics(tmp_path / "diagnostics")
    controller = Controller(tmp_path / "data", diagnostics=recorder)
    board = Board()
    controller.connect_transport(board)
    assert not controller.ready
    assert "等待主板版本" in controller.connection_text
    board.line.emit("FW_VERSION: 029")
    assert not controller.ready and "不支援" in controller.connection_text
    for _ in range(100):
        board.line.emit("FW_VERSION: 028")
    assert controller.ready
    assert board.commands == []  # No invented ACK, READY, query or measurement command.
    board.line.emit("ESP-ROM:esp32s3-20210327")
    assert not controller.ready
    board.line.emit("FW_VERSION: 028")
    controller.start("CV", CVConfig(), RGB(), {Well(0, y) for y in range(8)})
    assert board.commands == ["APPCFG_RST 15 2500 -2500 1024"]
    assert controller.batch.settings_reply["diagnostics_session"] == recorder.session_id
    controller.close()
    recorder.close()
    snap = recorder.snapshot(recorder.session_id)
    assert sum(e["kind"] == "firmware_received" for e in rows(snap)) == 102
    recorder.release(snap)


def test_export_snapshot_keeps_later_records_out_and_history_is_exportable(tmp_path):
    recorder = Diagnostics(tmp_path / "diagnostics")
    recorder.record("uart_rx_line", line="before snapshot")
    destination = tmp_path / "USB"
    destination.mkdir()
    calls = []

    def check():
        calls.append(1)
        recorder.record("uart_rx_line", line="after snapshot")

    output = export_diagnostics(recorder, recorder.session_id, destination, check_destination=check)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        content = archive.read("uart.jsonl").decode()
        assert "before snapshot" in content and "after snapshot" not in content
        assert {"summary.txt", "manifest.json", "events.log", "uart.txt", "batch_metadata.json"}.issubset(archive.namelist())
    recorder.close()
    later = Diagnostics(tmp_path / "diagnostics")
    try:
        historical = export_diagnostics(later, recorder.session_id, destination)
        with zipfile.ZipFile(historical) as archive:
            assert "after snapshot" in archive.read("uart.jsonl").decode()
            assert json.loads(archive.read("manifest.json"))["clean_shutdown"]
        assert output != historical
        assert not list(destination.glob("*.partial"))
    finally:
        later.close()


@pytest.mark.parametrize("failure", ["removed", "cancelled", "full"])
def test_export_failure_keeps_local_logs_without_success_zip(tmp_path, monkeypatch, failure):
    recorder = Diagnostics(tmp_path / "diagnostics")
    recorder.record("uart_rx_line", line="keep me")
    destination = tmp_path / "USB"
    destination.mkdir()
    checks = []

    def check():
        checks.append(1)
        if failure == "removed" and len(checks) == 2:
            raise OSError("device removed")

    if failure == "full":
        from collections import namedtuple
        monkeypatch.setattr("instrument_ui.diagnostics.shutil.disk_usage", lambda p: namedtuple("Usage", "free")(0))
    try:
        with pytest.raises(OSError):
            export_diagnostics(recorder, recorder.session_id, destination, check_destination=check,
                               cancelled=lambda: failure == "cancelled")
        assert not list(destination.iterdir())
        snap = recorder.snapshot(recorder.session_id)
        assert any(e.get("line") == "keep me" for e in rows(snap))
        recorder.release(snap)
    finally:
        recorder.close()


def test_rotation_bounds_storage_without_touching_measurements_and_marks_gaps(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    sentinel = data / "measurements.csv"
    sentinel.write_text("irreplaceable", encoding="utf-8")
    recorder = Diagnostics(tmp_path / "diagnostics", segment_bytes=700, budget_bytes=2100)
    for i in range(50):
        recorder.record("uart_rx_line", line=f"{i}:" + "x" * 200)
    recorder.close()
    snap = recorder.snapshot(recorder.session_id)
    try:
        assert snap.manifest["pruned_segments"] > 0
        assert sum(p.stat().st_size for p in snap.files) <= 2100
        assert any(e["kind"] == "application_stop" for e in rows(snap))
        assert sentinel.read_text() == "irreplaceable"
    finally:
        recorder.release(snap)


def test_queue_overflow_is_visible_and_exported(tmp_path, monkeypatch):
    gate = threading.Event()
    rotate = Diagnostics._rotate

    def blocked_rotate(self):
        gate.wait(5)
        rotate(self)

    monkeypatch.setattr(Diagnostics, "_rotate", blocked_rotate)
    recorder = Diagnostics(tmp_path / "diagnostics", queue_size=2)
    try:
        for i in range(100):
            recorder.record("uart_rx_line", line=str(i))
        assert "不完整" in recorder.warning
    finally:
        gate.set()
        recorder.close()
    snap = recorder.snapshot(recorder.session_id)
    assert snap.manifest["dropped_records"] > 0
    recorder.release(snap)


def test_diagnostic_disk_failure_does_not_block_controller(qapp, tmp_path):
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("file")
    recorder = Diagnostics(invalid_root)
    board = Board()
    controller = Controller(tmp_path / "data", diagnostics=recorder)
    controller.connect_transport(board)
    board.line.emit("FW_VERSION: 028")
    controller.start("CV", CVConfig(), RGB(), {Well(0, y) for y in range(8)})
    assert board.commands == ["APPCFG_RST 15 2500 -2500 1024"]
    assert not controller.storage_failed
    assert not controller.hardware_uncertain
    controller.close()
    recorder.close()
    assert "寫入失敗" in recorder.warning


def test_diagnostics_dialog_export_keeps_event_loop_running(qapp, tmp_path):
    qapp.setStyleSheet(STYLE)
    window = MainWindow(tmp_path / "data")
    window.resize(800, 480)
    window.show()
    window.connect_demo()
    dialog = DiagnosticsDialog(window.diagnostics, window.log_view, window)
    dialog.show()
    output = tmp_path / "USB"
    output.mkdir()
    dialog.destination.setText(str(output))
    window.resolution.setCurrentText("256")
    window.plate.selected = {Well(0, y) for y in range(8)}
    window.start_measurement()
    dialog.export()
    try:
        for _ in range(300):
            QTest.qWait(20)
            if not dialog.worker.isRunning() and not window.controller.busy:
                break
        assert not dialog.worker.isRunning()
        assert dialog.progress.value() == 100, dialog.result.text()
        assert window.controller.batch.state == "complete"
        assert sum(map(len, window.controller.batch.samples.values())) == 2064
        assert dialog.width() <= 800 and dialog.height() <= 480
        assert len(list(output.glob("*.zip"))) == 1
    finally:
        if dialog.worker.isRunning():
            dialog.worker.requestInterruption()
            dialog.worker.wait()
        window.log_view.setParent(None)
        dialog.close()
        window.close()


def test_stop_measurement_remains_available_during_export(qapp, tmp_path, monkeypatch):
    gate = threading.Event()

    def slow_export(*args, **kwargs):
        gate.wait(5)
        raise OSError("cancelled")

    monkeypatch.setattr("instrument_ui.diagnostics_ui.export_diagnostics", slow_export)
    window = MainWindow(tmp_path / "data")
    window.connect_demo()
    window.plate.selected = {Well(0, y) for y in range(8)}
    window.start_measurement()
    dialog = DiagnosticsDialog(window.diagnostics, window.log_view, window)
    dialog.destination.setText(str(tmp_path))
    dialog.export()
    try:
        assert dialog.worker.isRunning()
        assert dialog.stop_button.isEnabled()
        dialog.stop_button.click()
        for _ in range(50):
            QTest.qWait(10)
            if not window.controller.busy:
                break
        assert window.controller.batch.state == "interrupted"
        assert not dialog.stop_button.isEnabled()
    finally:
        gate.set()
        dialog.worker.wait()
        window.log_view.setParent(None)
        dialog.close()
        window.close()
