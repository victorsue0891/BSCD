from __future__ import annotations

from math import exp, sin
from pathlib import Path

from PyQt6.QtCore import QIODevice, QObject, QTimer, pyqtSignal
from PyQt6.QtSerialPort import QSerialPort, QSerialPortInfo

from .domain import CAConfig, CVConfig, Well
from .protocol import LineFramer


class Transport(QObject):
    line = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()
    diagnostic = pyqtSignal(str, object)
    source = "unknown"
    connected = False

    def open(self):
        self.connected = True

    def close(self):
        self.connected = False

    def send(self, command: str):
        raise NotImplementedError


class SerialTransport(Transport):
    source = "serial"

    def __init__(self, port: str, ending: str = "LF", parent=None):
        super().__init__(parent)
        self.port = QSerialPort(self)
        self.port.setPortName(port)
        self.port.setBaudRate(115200)
        self.port.setDataBits(QSerialPort.DataBits.Data8)
        self.port.setParity(QSerialPort.Parity.NoParity)
        self.port.setStopBits(QSerialPort.StopBits.OneStop)
        self.port.setFlowControl(QSerialPort.FlowControl.NoFlowControl)
        self.port.readyRead.connect(self._read)
        self.port.errorOccurred.connect(self._error)
        self.port.bytesWritten.connect(lambda count: self.diagnostic.emit(
            "uart_tx_written", {"bytes": count, "port": self.port.portName()}))
        self.ending = "\r\n" if ending == "CRLF" else "\n"
        self.framer = LineFramer()

    @staticmethod
    def ports() -> list[str]:
        return [p.systemLocation() for p in QSerialPortInfo.availablePorts()]

    def open(self):
        self.diagnostic.emit("serial_open_attempt", {
            "port": self.port.portName(), "baud": self.port.baudRate(),
            "data_bits": self.port.dataBits().name, "parity": self.port.parity().name,
            "stop_bits": self.port.stopBits().name, "flow_control": self.port.flowControl().name,
            "line_ending": "CRLF" if self.ending == "\r\n" else "LF",
        })
        if not self.port.open(QIODevice.OpenModeFlag.ReadWrite):
            self.diagnostic.emit("serial_open_failed", {"error": self.port.errorString()})
            raise OSError(self.port.errorString())
        self.connected = True
        self.diagnostic.emit("serial_opened", {"port": self.port.portName()})

    def send(self, command: str):
        self.diagnostic.emit("uart_tx_attempt", {"command": command})
        if not self.connected:
            self.diagnostic.emit("uart_tx_failed", {"command": command, "error": "UART 未連線"})
            raise OSError("UART 未連線")
        payload = (command + self.ending).encode("ascii")
        accepted = self.port.write(payload)
        self.diagnostic.emit("uart_tx_queued", {
            "data_hex": payload.hex(), "bytes": len(payload), "accepted_bytes": accepted,
            "complete": accepted == len(payload),
        })
        if accepted != len(payload):
            raise OSError("UART 命令未完整排入傳送佇列")

    def _read(self):
        data = bytes(self.port.readAll())
        for offset in range(0, len(data), 4096):
            chunk = data[offset:offset + 4096]
            self.diagnostic.emit("uart_rx_bytes", {"data_hex": chunk.hex(), "bytes": len(chunk)})
        try:
            for line in self.framer.feed(data):
                self.line.emit(line)
        except ValueError as exc:
            self.diagnostic.emit("uart_framing_error", {"error": str(exc)})
            self.error.emit(str(exc))

    def _error(self, error):
        if error != QSerialPort.SerialPortError.NoError:
            self.diagnostic.emit("serial_error", {"code": error.name, "error": self.port.errorString()})
        if self.connected and error != QSerialPort.SerialPortError.NoError:
            if error in (QSerialPort.SerialPortError.ResourceError, QSerialPort.SerialPortError.DeviceNotFoundError):
                self.connected = False
            self.error.emit(self.port.errorString())

    def close(self):
        self.diagnostic.emit("serial_closed", {"port": self.port.portName()})
        self.connected = False
        self.port.close()
        self.framer = LineFramer()


class DemoTransport(Transport):
    source = "demo"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._tick)
        self.config = CVConfig()
        self.wells = []
        self.points = []
        self.index = 0
        self.tick = 0
        self.ca = False

    def open(self):
        super().open()
        self._defer(lambda: self.line.emit("FW_VERSION: DEMO"))

    def _defer(self, callback):
        # A parent-owned timer is cancelled when this transport is destroyed.
        timer = QTimer(self)
        timer.setSingleShot(True)

        def deliver():
            if self.connected:
                callback()
            timer.deleteLater()

        timer.timeout.connect(deliver)
        timer.start(0)

    def send(self, command: str):
        if not self.connected:
            raise OSError("模擬器未連線")
        if command.startswith("APPCFG_RST"):
            def reply():
                self.line.emit("APPCFG_RST OK")
                self.line.emit("REAL_STEP=1024 STEP_TIME=651")
                self.line.emit("APPVREF_RST=512 APPVBASE_RST=0")
            self._defer(reply)
        elif command.startswith("VRE_XSCAN_FUD") or command == "DEMO_CA_START":
            if command.startswith("VRE_XSCAN_FUD"):
                x = int(command.split()[1])
                self.wells = [w for w in self.all_wells if w.x == x]
                half = self.config.resolution // 2
                self.points = list(range(half + 1)) + list(range(half, -1, -1))
            else:
                self.points = list(range(int(self.config.duration_s / self.config.interval_s) + 1))
            self.index = 0
            self.line.emit("VRE_XSCAN_FUD OK")
            self.line.emit(f"XSCAN_FUD START T:{self.tick}")
            self.timer.start()
        elif command == "Q":
            self.timer.stop()
            # Demo alone defines its stop response; no invented real-device ACK.
            self._defer(self.finished.emit)

    @property
    def all_wells(self):
        return self._all_wells

    def prepare(self, config: CVConfig | CAConfig, wells: set[Well]):
        self.config = config
        self._all_wells = sorted(wells)
        self.wells = sorted(wells)
        self.ca = isinstance(config, CAConfig)

    def _tick(self):
        # Accelerated synthetic acquisition; 8 voltage points per timer tick.
        for _ in range(8):
            if self.index >= len(self.points):
                self.timer.stop()
                self.line.emit(f"XSCAN_FUD END T:{self.tick} ELAPSED:{self.tick}")
                return
            vre = self.points[self.index]
            for well in self.wells:
                amplitude = 0.006 + (well.x * 8 + well.y + 1) * 0.0003
                if self.ca:
                    t = vre * self.config.interval_s
                    value = amplitude * exp(-t / max(self.config.duration_s / 5, 0.1)) + 0.002
                    self.tick = round(t * 1000)
                    xvalue = self.config.target_v
                else:
                    half = self.config.resolution // 2
                    position = vre / half
                    downward = self.index > half
                    value = amplitude * exp(-((position - 0.65) / 0.15) ** 2)
                    if downward:
                        value = -amplitude * 0.7 * exp(-((position - 0.35) / 0.18) ** 2)
                    value += 0.00015 * sin(self.index + well.y)
                    self.tick += 80
                    xvalue = vre
                self.line.emit(
                    f"XS_FUD (1/1): {well.x},{well.y} VRE={xvalue} AVG={value:.8f} T:{self.tick}"
                )
            self.index += 1

    def close(self):
        self.timer.stop()
        super().close()


class ReplayTransport(Transport):
    source = "replay"

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.file = None
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._tick)

    def open(self):
        self.file = self.path.open(encoding="utf-8-sig", errors="replace")
        super().open()

    def play(self):
        self.timer.start()

    def send(self, command: str):
        raise OSError("紀錄重播不能傳送硬體命令")

    def _tick(self):
        try:
            for _ in range(160):
                line = self.file.readline()
                if not line:
                    self.timer.stop()
                    self.finished.emit()
                    return
                self.line.emit(line.rstrip("\r\n"))
                if not self.timer.isActive():
                    return
        except OSError as exc:
            self.timer.stop()
            self.error.emit(str(exc))

    def close(self):
        self.timer.stop()
        if self.file:
            self.file.close()
        super().close()
