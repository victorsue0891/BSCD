from instrument_ui.app import MainWindow
from instrument_ui.transports import Transport


def test_startup_retries_late_device_without_sending_commands(qapp, tmp_path, monkeypatch):
    attempts, sent = [], []

    class LateSerial(Transport):
        source = "serial"

        def __init__(self, port, ending, parent):
            super().__init__(parent)
            attempts.append((port, ending))

        def open(self):
            if len(attempts) == 1:
                raise OSError("device not present")
            super().open()

        def send(self, command):
            sent.append(command)

    monkeypatch.setattr("instrument_ui.app.SerialTransport", LateSerial)
    window = MainWindow(tmp_path)
    window.connect_startup_serial("/dev/ttyUSB0", "CRLF")
    assert window.startup_serial_timer.isActive()
    assert window.controller.transport is None
    window._try_startup_serial()
    assert attempts == [("/dev/ttyUSB0", "CRLF")] * 2
    assert window.controller.transport.connected
    assert not window.startup_serial_timer.isActive()
    assert window.controller.firmware == "unknown"
    assert not sent
    # Loss after the first successful connection must not restart a measurement.
    window.controller.transport.close()
    window._try_startup_serial()
    assert len(attempts) == 2
    window.close()


def test_switch_to_demo_cancels_pending_serial(qapp, tmp_path, monkeypatch):
    class MissingSerial(Transport):
        def __init__(self, port, ending, parent):
            super().__init__(parent)

        def open(self):
            raise OSError("device not present")

    monkeypatch.setattr("instrument_ui.app.SerialTransport", MissingSerial)
    window = MainWindow(tmp_path)
    window.connect_startup_serial("/dev/ttyUSB0")
    assert window.startup_serial_timer.isActive()
    window.connect_demo()
    window._try_startup_serial()
    assert window.controller.transport.source == "demo"
    assert not window.startup_serial_timer.isActive()
    window.close()
