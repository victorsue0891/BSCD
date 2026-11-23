from pathlib import Path

import pytest
from PyQt6.QtTest import QTest

from instrument_ui.controller import Controller
from instrument_ui.domain import CAConfig, CVConfig, RGB, Well
from instrument_ui.transports import DemoTransport, Transport


class FakeSerial(Transport):
    source = "serial"

    def __init__(self):
        super().__init__()
        self.commands = []

    def open(self):
        super().open()
        self.line.emit("FW_VERSION: 028")

    def send(self, command):
        self.commands.append(command)


@pytest.fixture
def rig(qapp, tmp_path):
    controller = Controller(tmp_path)
    transport = FakeSerial()
    controller.connect_transport(transport)
    yield controller, transport
    controller.close()


def configure(controller, transport, columns=(0,)):
    controller.start("CV", CVConfig(), RGB(1, 2, 3), {Well(x, y) for x in columns for y in range(8)})
    transport.line.emit("APPCFG_RST OK")
    transport.line.emit("REAL_STEP=1024 STEP_TIME=651")
    transport.line.emit("APPVREF_RST=512 APPVBASE_RST=0")


def test_configuration_barrier(rig):
    controller, transport = rig
    controller.start("CV", CVConfig(), RGB(), {Well(0, y) for y in range(8)})
    transport.line.emit("APPCFG_RST OK")
    assert len(transport.commands) == 1
    transport.line.emit("REAL_STEP=1024 STEP_TIME=651")
    assert len(transport.commands) == 1
    transport.line.emit("APPVREF_RST=512 APPVBASE_RST=0")
    assert transport.commands[-1] == "VRE_XSCAN_FUD 0 0 0 0 1"
    transport.line.emit("APPCFG_RST OK")
    assert len(transport.commands) == 2


def test_partial_column_and_ca_do_not_send_live_commands(rig):
    c, t = rig
    with pytest.raises(ValueError, match="完整欄"):
        c.start("CV", CVConfig(), RGB(), {Well(0, 0)})
    with pytest.raises(ValueError, match="CA"):
        c.start("CA", CAConfig(), RGB(), {Well(0, y) for y in range(8)})
    assert t.commands == []


def test_column_finishes_only_on_end_and_next_column_is_sequential(rig):
    c, t = rig
    configure(c, t, (0, 1))
    t.line.emit("XSCAN_FUD START T:10")
    for y in range(8):
        t.line.emit(f"XS_FUD (1/1): 0,{y} VRE=0 AVG=0.1 T:{11+y}")
    assert c.batch.well_states[Well(0, 0)] == "running"
    assert len(t.commands) == 2
    t.line.emit("XSCAN_FUD END T:30 ELAPSED:20")
    t.line.emit("XSCAN_FUD END T:30 ELAPSED:20")
    QTest.qWait(1)
    assert t.commands == ["APPCFG_RST 15 2500 -2500 1024", "VRE_XSCAN_FUD 0 1 2 3 1", "VRE_XSCAN_FUD 1 1 2 3 1"]
    assert all(c.batch.well_states[Well(0, y)] == "complete" for y in range(8))
    assert c.batch.state == "await_start"


@pytest.mark.parametrize("fault_line", [
    "ESP-ROM:esp32s3-20210327",
    "XS_FUD (1/1): 1,0 VRE=0 AVG=0.1 T:11",
    "ERROR invalid configuration",
])
def test_fault_stops_without_retry_and_keeps_data(rig, fault_line):
    c, t = rig
    configure(c, t)
    t.line.emit("XSCAN_FUD START T:10")
    t.line.emit("XS_FUD (1/1): 0,0 VRE=0 AVG=0.1 T:11")
    t.line.emit(fault_line)
    assert c.batch.state == "fault"
    assert c.hardware_uncertain
    assert t.commands[-1] == "Q"
    assert len(c.batch.samples[Well(0, 0)]) == 1
    assert list(c.store.path.glob("*_export_*/*.csv"))
    with pytest.raises(ValueError):
        c.start("CV", CVConfig(), RGB(), {Well(0, y) for y in range(8)})


def test_stop_timeout_preserves_partial_data_and_latches(rig):
    c, t = rig
    configure(c, t)
    t.line.emit("XSCAN_FUD START T:10")
    t.line.emit("XS_FUD (1/1): 0,0 VRE=0 AVG=1 T:11")
    c.stop()
    assert c.batch.state == "stopping"
    c._timed_out()
    assert c.hardware_uncertain
    assert c.batch.state == "fault"
    assert c.batch.well_states[Well(0, 0)] == "interrupted"
    assert sum(cmd.startswith("VRE_XSCAN") for cmd in t.commands) == 1
    c.acknowledge_stopped()
    assert not c.hardware_uncertain
    assert c.transport is None


def test_recording_replay(qapp, tmp_path):
    c = Controller(tmp_path)
    c.replay(Path(__file__).resolve().parents[1] / "RefTxt1006.txt")
    for _ in range(150):
        QTest.qWait(20)
        if not c.busy:
            break
    assert c.batch.state == "complete"
    assert c.batch.firmware == "028"
    assert sum(map(len, c.batch.samples.values())) == 8208
    assert all(state == "complete" for state in c.batch.well_states.values())
    assert len(list(c.store.path.glob("*_export_*/*.csv"))) == 8
    c.close()


def test_replay_truncated_after_previous_column_end(qapp, tmp_path):
    path = tmp_path / "partial.txt"
    path.write_text("\n".join([
        "XSCAN_FUD START T:0", "XS_FUD (1/1): 0,0 VRE=0 AVG=1 T:1",
        "XSCAN_FUD END T:2 ELAPSED:2", "XSCAN_FUD START T:3",
        "XS_FUD (1/1): 1,0 VRE=0 AVG=1 T:4",
    ]), encoding="utf-8")
    c = Controller(tmp_path / "data")
    c.replay(path)
    QTest.qWait(80)
    assert c.batch.state == "interrupted"
    assert c.batch.well_states[Well(0, 0)] == "complete"
    assert c.batch.well_states[Well(1, 0)] == "interrupted"
    c.close()


def test_demo_arbitrary_wells_and_ca(qapp, tmp_path):
    c = Controller(tmp_path)
    c.connect_transport(DemoTransport(c))
    c.start("CA", CAConfig(duration_s=0.2, interval_s=0.1), RGB(), {Well(2, 4), Well(8, 1)})
    QTest.qWait(100)
    assert c.batch.state == "complete"
    assert set(c.batch.samples) == {Well(2, 4), Well(8, 1)}
    assert all(len(s) == 3 for s in c.batch.samples.values())
    c.close()


def test_journal_failure_sends_stop_and_keeps_memory(rig):
    c, t = rig
    configure(c, t)
    t.line.emit("XSCAN_FUD START T:10")
    t.line.emit("XS_FUD (1/1): 0,0 VRE=0 AVG=1 T:11")
    def disk_full(*args):
        raise OSError("disk full")
    c.store.record = disk_full
    t.line.emit("XS_FUD (1/1): 0,1 VRE=0 AVG=1 T:12")
    assert c.batch.state == "fault"
    assert c.storage_failed
    assert c.hardware_uncertain
    assert t.commands[-1] == "Q"
    assert c.batch.samples[Well(0, 0)][0].avg == 1
