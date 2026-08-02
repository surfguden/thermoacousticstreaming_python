from __future__ import annotations

from thermo_acoustic import hw_logging
from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend
from thermo_acoustic.instruments import SerialTextCommandBackend
from thermo_acoustic.qmix_backend import QmixPumpBackend
from thermo_acoustic.thorlabs_piezo import PiezoStage
from thermo_acoustic.waveforms import WaveFormsBackend

from test_thorlabs_piezo import FakeBenchtopPrecisionPiezo, FakeChannel, FakeDevice, FakeDeviceManagerCLI


def _redirect(tmp_path):
    log_file = tmp_path / "hardware_transactions.log"
    hw_logging.configure(log_file)
    return log_file


def _read_log(log_file) -> str:
    return log_file.read_text(encoding="utf-8") if log_file.exists() else ""


# Spot-check, not exhaustive per-call-site testing (per Part A instruction):
# one real production call site per device, confirming it actually reaches
# the shared hw_logging module -- not re-testing hw_logging's own behavior
# (that's tests/test_hw_logging.py) or re-testing each backend's existing
# functional test coverage.


def test_piezo_connect_is_logged(tmp_path):
    log_file = _redirect(tmp_path)
    FakeDevice.instances = []
    FakeDeviceManagerCLI.build_device_list_calls = 0
    device = FakeDevice("44533854", channel=FakeChannel())
    FakeBenchtopPrecisionPiezo.next_device = device
    stage = PiezoStage(
        serial_number="44533854",
        device_manager_cli=FakeDeviceManagerCLI,
        benchtop_precision_piezo_cls=FakeBenchtopPrecisionPiezo,
        closed_loop_mode="CloseLoop",
        decimal_type=float,
    )

    stage.connect()

    log_text = _read_log(log_file)
    assert "piezo" in log_text
    assert "connect" in log_text
    assert "OK" in log_text


class _FakeDwfFunction:
    def __init__(self, name, owner):
        self.name = name
        self.owner = owner
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        def out_target(arg):
            return getattr(arg, "_obj", arg)

        if self.name == "FDwfDeviceOpen":
            out_target(args[-1]).value = 42
        elif self.name == "FDwfEnum":
            out_target(args[-1]).value = self.owner.device_count
        elif self.name == "FDwfEnumDeviceIsOpened":
            out_target(args[-1]).value = 1 if self.owner.device_opened else 0
        elif self.name == "FDwfEnumDeviceName":
            args[-1].value = self.owner.device_name
        elif self.name == "FDwfEnumSN":
            args[-1].value = self.owner.device_serial
        return 1


class _FakeDwf:
    def __init__(self):
        self.device_count = 1
        self.device_opened = True
        self.device_name = b"Analog Discovery 2"
        self.device_serial = b"SN:210321Axxxxx"

    def __getattr__(self, name):
        func = _FakeDwfFunction(name, self)
        setattr(self, name, func)
        return func


def test_ad2_open_device_is_logged(tmp_path):
    log_file = _redirect(tmp_path)
    backend = WaveFormsBackend(dwf=_FakeDwf())

    handle = backend.open_device(-1)

    assert handle == 42
    log_text = _read_log(log_file)
    assert "ad2" in log_text
    assert "open_device" in log_text
    assert "OK" in log_text


# Task 1 follow-up: the 9 methods confirmed reachable from real-hardware-
# touching code outside AD2Sdk's own 8 entry points (tools/release_ad2.py,
# hardware_tests/test_real_workflow_smoke.py) -- one spot-check test each,
# same pattern as every other device's spot-check above.


def test_ad2_close_all_is_logged(tmp_path):
    log_file = _redirect(tmp_path)
    backend = WaveFormsBackend(dwf=_FakeDwf())

    backend.close_all()

    log_text = _read_log(log_file)
    assert "ad2" in log_text
    assert "close_all" in log_text
    assert "OK" in log_text


def test_ad2_reset_device_is_logged(tmp_path):
    log_file = _redirect(tmp_path)
    backend = WaveFormsBackend(dwf=_FakeDwf())

    backend.reset_device(1)

    log_text = _read_log(log_file)
    assert "ad2" in log_text
    assert "reset_device" in log_text
    assert "OK" in log_text


def test_ad2_enum_devices_is_logged(tmp_path):
    log_file = _redirect(tmp_path)
    fake = _FakeDwf()
    fake.device_count = 3
    backend = WaveFormsBackend(dwf=fake)

    count = backend.enum_devices()

    assert count == 3
    log_text = _read_log(log_file)
    assert "ad2" in log_text
    assert "enum_devices" in log_text
    assert "resp=3" in log_text


def test_ad2_enum_device_is_opened_is_logged(tmp_path):
    log_file = _redirect(tmp_path)
    fake = _FakeDwf()
    fake.device_opened = True
    backend = WaveFormsBackend(dwf=fake)

    opened = backend.enum_device_is_opened(0)

    assert opened is True
    log_text = _read_log(log_file)
    assert "ad2" in log_text
    assert "enum_device_is_opened" in log_text
    assert "resp=True" in log_text


def test_ad2_enum_device_name_is_logged(tmp_path):
    log_file = _redirect(tmp_path)
    fake = _FakeDwf()
    fake.device_name = b"Analog Discovery 2"
    backend = WaveFormsBackend(dwf=fake)

    name = backend.enum_device_name(0)

    assert name == "Analog Discovery 2"
    log_text = _read_log(log_file)
    assert "ad2" in log_text
    assert "enum_device_name" in log_text
    assert "Analog Discovery 2" in log_text


def test_ad2_enum_device_serial_number_is_logged(tmp_path):
    log_file = _redirect(tmp_path)
    fake = _FakeDwf()
    fake.device_serial = b"SN:210321Axxxxx"
    backend = WaveFormsBackend(dwf=fake)

    serial = backend.enum_device_serial_number(0)

    assert serial == "SN:210321Axxxxx"
    log_text = _read_log(log_file)
    assert "ad2" in log_text
    assert "enum_device_serial_number" in log_text
    assert "SN:210321Axxxxx" in log_text


def test_ad2_analog_out_configure_is_logged(tmp_path):
    log_file = _redirect(tmp_path)
    backend = WaveFormsBackend(dwf=_FakeDwf())

    backend.analog_out_configure(1, 0, False)

    log_text = _read_log(log_file)
    assert "ad2" in log_text
    assert "analog_out_configure" in log_text
    assert "OK" in log_text


def test_ad2_analog_out_node_enable_set_is_logged(tmp_path):
    log_file = _redirect(tmp_path)
    backend = WaveFormsBackend(dwf=_FakeDwf())

    backend.analog_out_node_enable_set(1, 0, 0, False)

    log_text = _read_log(log_file)
    assert "ad2" in log_text
    assert "analog_out_node_enable_set" in log_text
    assert "OK" in log_text


def test_ad2_digital_out_configure_is_logged(tmp_path):
    log_file = _redirect(tmp_path)
    backend = WaveFormsBackend(dwf=_FakeDwf())

    backend.digital_out_configure(1, False)

    log_text = _read_log(log_file)
    assert "ad2" in log_text
    assert "digital_out_configure" in log_text
    assert "OK" in log_text


def test_camera_open_camera_is_logged(tmp_path):
    log_file = _redirect(tmp_path)

    class FakeDcam:
        def __init__(self, index):
            self.index = index
            self.opened = False

        def is_opened(self):
            return self.opened

        def dev_open(self):
            self.opened = True
            return True

    class FakeDcamModule:
        Dcam = FakeDcam

    class FakeDcamApi:
        @staticmethod
        def init():
            return True

    backend = HamamatsuDcamBackend()
    backend.dcam_module = FakeDcamModule
    backend.dcamapi = FakeDcamApi

    backend.open_camera()

    log_text = _read_log(log_file)
    assert "camera" in log_text
    assert "open_camera" in log_text
    assert "OK" in log_text


def test_pump_read_fill_level_is_logged(tmp_path):
    log_file = _redirect(tmp_path)

    class FakePump:
        def get_fill_level(self):
            return 0.42

    backend = QmixPumpBackend()
    backend.pump = FakePump()

    fill_level = backend.read_fill_level()

    assert fill_level == 0.42
    log_text = _read_log(log_file)
    assert "pump" in log_text
    assert "read_fill_level" in log_text
    assert "0.42" in log_text


def test_valve_query_is_logged_and_a_failed_query_is_logged_too(tmp_path):
    log_file = _redirect(tmp_path)

    class FakePort:
        def write(self, data):
            pass

        def read_until(self, expected):
            return b"01\r"

        def close(self):
            pass

    backend = SerialTextCommandBackend(device_name="valve", port=FakePort())

    response = backend.query("S")

    assert response == "01\r"
    log_text = _read_log(log_file)
    assert "valve" in log_text
    assert "query" in log_text
    assert "OK" in log_text

    # Failure path: no port open at all.
    backend_unopened = SerialTextCommandBackend(device_name="valve")
    try:
        backend_unopened.query("S")
        assert False, "expected RuntimeError for an unopened port"
    except RuntimeError:
        pass

    log_text = _read_log(log_file)
    assert "FAIL" in log_text
    assert "Serial port is not open" in log_text
