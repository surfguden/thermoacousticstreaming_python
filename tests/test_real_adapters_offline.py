from __future__ import annotations

import unittest

from thermo_acoustic.domain import ScopeCaptureRequest
from thermo_acoustic.infrastructure.real import AD2Adapter, NemesysPumpAdapter, PiezoZStageAdapter, TecAdapter


class FakeTecDriver:
    initialized = False

    def __init__(self) -> None:
        self.read_calls = 0

    def initialize(self) -> None:
        self.initialized = True

    def read_status(self):
        self.read_calls += 1
        raise AssertionError("passive status must not access the driver")

    def cleanup(self) -> None:
        self.initialized = False


class FakePiezoDriver:
    connected = False
    max_travel_um = 300.0
    min_output_voltage_v = 0.0
    max_output_voltage_v = 75.0

    def __init__(self) -> None:
        self.position_reads = 0

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def needs_closed_loop_confirmation(self) -> bool:
        return True

    def get_position(self) -> float:
        self.position_reads += 1
        raise AssertionError("passive status must not read position")


class FakeAD2Driver:
    def initialize(self) -> None:
        pass

    def get_phdwf(self) -> int:
        return 1

    def capture_scope_channels(self, **kwargs):
        self.capture_arguments = kwargs
        return {channel: [0.0] for channel in kwargs["channel_indices"]}


class FakeNemesysDriver:
    is_connected = True
    is_pumping = False
    current_volume_ul = 12.0
    current_flow_ul_min = 3.0
    maximum_volume_ul = 100.0

    def connect(self) -> None:
        pass


class RealAdapterOfflineTests(unittest.TestCase):
    def test_ad2_scope_adapter_uses_keyword_only_driver_contract(self) -> None:
        driver = FakeAD2Driver()
        adapter = AD2Adapter(driver)
        adapter.connect()

        capture = adapter.capture_scope(ScopeCaptureRequest(channels=(0, 1), sample_count=1))

        self.assertEqual(set(capture.samples_by_channel), {0, 1})
        self.assertEqual(driver.capture_arguments["channel_indices"], [0, 1])

    def test_nemesys_adapter_uses_property_based_driver_status(self) -> None:
        adapter = NemesysPumpAdapter(FakeNemesysDriver())
        adapter.connect()

        status = adapter.read_pump_status()

        self.assertEqual(status.fill_volume_ul, 12.0)
        self.assertEqual(status.maximum_volume_ul, 100.0)

    def test_tec_status_is_cached_and_passive(self) -> None:
        driver = FakeTecDriver()
        adapter = TecAdapter(driver)
        adapter.connect()

        status = adapter.read_status()

        self.assertEqual(status.connection.value, "connected")
        self.assertEqual(driver.read_calls, 0)

    def test_z_stage_status_is_cached_and_passive(self) -> None:
        driver = FakePiezoDriver()
        adapter = PiezoZStageAdapter(driver)
        adapter.connect()

        status = adapter.read_status()

        self.assertIsNone(status.readings["position_um"])
        self.assertEqual(driver.position_reads, 0)
