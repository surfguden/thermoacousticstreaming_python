from __future__ import annotations

from ctypes import c_int

import pytest

from thermo_acoustic.drivers.ad2 import (
    AnalogDiscovery2,
    AnalogDiscoveryError,
    ScopeConfig,
    ScopeState,
    SimulatedAD2,
)
from thermo_acoustic.drivers.ad2.configuration import (
    AnalogOutputIdleState,
    ScopeTriggerCondition,
    ScopeTriggerFilter,
    ScopeTriggerLengthCondition,
    ScopeTriggerType,
    TriggerSource,
    coerce_scope_config,
    coerce_wfg_config,
)
from thermo_acoustic.drivers.camera import (
    CameraMode,
    HamamatsuDcamDriver,
    IntegerRange,
    SimulatedCamera,
    SubRegion,
    SubRegionLimits,
)
from thermo_acoustic.drivers.pump import CetoniPump, SimulatedPump
from thermo_acoustic.drivers.tec import MeerstetterTecDriver, SimulatedTec, TecController
from thermo_acoustic.drivers.valve import SerialTextCommandTransport, SimulatedValve, Valve
from thermo_acoustic.drivers.z_stage import PiezoStage, SimulatedZStage, ZStageLimits
from thermo_acoustic.hal import DeviceRegistry, DeviceWorker


def test_public_hal_and_driver_imports_are_available() -> None:
    assert DeviceRegistry is not None
    assert DeviceWorker is not None
    assert all(
        item is not None
        for item in (
            AnalogDiscovery2,
            SimulatedAD2,
            HamamatsuDcamDriver,
            SimulatedCamera,
            CetoniPump,
            SimulatedPump,
            SimulatedTec,
            SimulatedValve,
            SimulatedZStage,
            TecController,
            Valve,
            PiezoStage,
        )
    )


def test_retained_driver_construction_performs_no_hardware_io() -> None:
    dependency = object()
    assert AnalogDiscovery2(enabled=False).device_handle is None
    assert CetoniPump().pump is None
    assert TecController(driver=dependency, enabled=False).driver is dependency
    assert Valve(transport=dependency, enabled=False).transport is dependency
    assert AnalogDiscovery2.is_available() in (True, False)
    assert HamamatsuDcamDriver().dcam is None
    assert MeerstetterTecDriver().client is None
    assert SerialTextCommandTransport().port is None
    assert PiezoStage().connected is False


def test_simulated_devices_are_reusable_without_the_hal() -> None:
    pump = SimulatedPump()
    pump.initialize()
    pump.configure_syringe({"volume_ml": 5.0})
    pump.refill(100.0)
    assert pump.read_fill_level() == 5.0
    pump.generate_flow(25.0)
    assert pump.flow_ul_min == 25.0
    assert pump.read_status()
    with pytest.raises(ValueError, match="within"):
        pump.generate_flow(10001.0)
    pump.cleanup()
    assert pump.flow_ul_min == 0.0
    pump.clear_fault_and_reinitialize()
    assert pump.initialized
    pump.cleanup()

    z_stage = SimulatedZStage()
    z_stage.connect()
    z_stage.switch_to_closed_loop()
    assert z_stage.set_position(50.0) == 50.0
    assert z_stage.get_position() == 50.0
    assert z_stage.set_position(999.0) == z_stage.travel_limits.maximum_um
    z_stage.disconnect()

    assert ZStageLimits(maximum_um=100.0).clamp(-5.0) == 0.0

    valve = SimulatedValve()
    valve.initialize()
    valve.set_position(2)
    assert "pending" in valve.status_note
    with pytest.raises(RuntimeError, match="not confirmed"):
        valve.read_position()
    assert valve.wait_until_ready()
    assert valve.status_note == "confirmed"
    assert valve.read_position() == 2
    valve.cleanup()

    tec = SimulatedTec()
    tec.initialize()
    status = tec.apply_static_setpoint({1: 25.0, 2: 26.0})
    assert status[1].target_temperature_c == 25.0
    assert status[2].target_temperature_c == 26.0
    with pytest.raises(ValueError, match="outside the local safety range"):
        tec.apply_static_setpoint({1: -1.0, 2: 26.0})
    with pytest.raises(ValueError, match="must exactly match"):
        tec.apply_static_setpoint({1: 25.0}, channels=(1, 2))
    tec.set_output_stage_static_off()


def test_camera_roi_can_be_centered_with_integer_limits() -> None:
    limits = SubRegionLimits(
        horizontal_size=IntegerRange(minimum=4, maximum=2048, increment=4),
        vertical_size=IntegerRange(minimum=4, maximum=1024, increment=4),
    )
    assert SubRegion(horizontal_size=512, vertical_size=256).centered(limits) == SubRegion(
        horizontal_offset=768,
        vertical_offset=384,
        horizontal_size=512,
        vertical_size=256,
    )


def test_simulated_camera_rejects_invalid_roi_before_applying_it() -> None:
    camera = SimulatedCamera()
    camera.open_camera()
    with pytest.raises(ValueError, match="increment"):
        camera.configure_roi(SubRegion(1, 0, 512, 256))
    with pytest.raises(ValueError, match="exceeds sensor width"):
        camera.configure_roi(SubRegion(1800, 0, 512, 256))
    assert camera.roi is None


def test_simulated_camera_supports_snapshot_and_buffered_sequence_modes() -> None:
    camera = SimulatedCamera(buffer_frames=4)
    camera.open_camera()

    camera.configure_sequence({"frames": 3, "exposure_ms": 2.5})
    assert camera.mode is CameraMode.SEQUENCE
    camera.start_capture()
    frames = camera.image_sequence(3)
    assert len(frames) == 3
    assert all(frame.ndim == 2 for frame in frames)
    assert camera.frame_count == 3
    assert camera.capture_active
    camera.stop_capture()

    camera.configure_snapshot()
    assert camera.mode is CameraMode.SNAPSHOT
    assert camera.sequence_settings is None
    assert camera.capture_snapshot().ndim == 2
    assert camera.frame_count == 4


def test_hamamatsu_buffered_sequence_uses_finite_snap_mode() -> None:
    calls: list[object] = []

    class FakeDcam:
        def is_opened(self):
            return True

        def buf_release(self):
            calls.append("release")
            return True

        def buf_alloc(self, count):
            calls.append(("alloc", count))
            return True

        def cap_snapshot(self):
            calls.append("snapshot")
            return True

        def cap_start(self, sequence=True):
            calls.append(("sequence", sequence))
            return True

    driver = HamamatsuDcamDriver()
    driver.dcam_module = object()
    driver.dcamapi = object()
    driver.dcam = FakeDcam()
    driver.initialized = True

    driver.begin_buffered_sequence(12)

    assert ("alloc", 12) in calls
    assert "snapshot" in calls
    assert not any(isinstance(call, tuple) and call[0] == "sequence" for call in calls)


def test_simulated_camera_saves_individual_and_stacked_tiff_with_metadata(tmp_path) -> None:
    camera = SimulatedCamera()
    camera.open_camera()
    frames = camera.image_sequence(3)
    metadata = {"sequence": {"frame_count": 3}, "properties": [{"name": "test", "value": 1}]}

    frames_folder = tmp_path / "frames"
    camera.save_sequence(frames, frames_folder, image_format="frames", metadata=metadata)
    assert len(list(frames_folder.glob("frame_*.tiff"))) == 3
    assert (frames_folder / "camera_settings.json").is_file()

    stack_folder = tmp_path / "stack"
    camera.save_sequence(frames, stack_folder, image_format="stacked", metadata=metadata)
    assert (stack_folder / "sequence.tiff").is_file()
    assert (stack_folder / "camera_settings.json").is_file()


def test_analog_discovery_configures_directly_without_an_inner_driver() -> None:
    device = AnalogDiscovery2(enabled=False)
    configured: list[tuple[int, object]] = []
    device.enabled = True
    device._open_device = lambda _index: 7
    device._configure_wfg = lambda handle, config: configured.append((handle, config))

    device.wfg_configure(
        {
            "frequency_hz": 2500.0,
            "amplitude_v": 0.5,
            "trigger": {
                "source": "trigsrcPC",
                "sec_wait": 0.1,
                "sec_run": 0.2,
                "repeat_count": 3,
                "repeat_trigger": True,
            },
        }
    )

    assert device.device_handle == 7
    assert configured == [(7, device.wfg_config)]
    trigger = device.wfg_config.channels[0].trigger
    assert trigger.source is TriggerSource.PC
    assert (trigger.sec_wait, trigger.sec_run, trigger.repeat_count) == (0.1, 0.2, 3)
    assert trigger.repeat_trigger


def test_analog_discovery_do_config_keeps_custom_pattern_and_clock_settings() -> None:
    device = AnalogDiscovery2(enabled=False)
    configured: list[tuple[int, object]] = []
    device.enabled = True
    device._open_device = lambda _index: 11
    device._configure_do = lambda handle, config: configured.append((handle, config))

    device.do_configure(
        {
            "enabled": True,
            "output_type": "Custom",
            "clock_frequency_hz": 500.0,
            "bits": [1, 1, 0, 0],
            "trigger": {
                "source": "trigsrcDigitalIn",
                "sec_wait": 0.3,
                "sec_run": 0.4,
                "repeat_count": 2,
                "repeat_trigger": True,
            },
        }
    )

    channel = device.do_config.channels[0]
    assert configured == [(11, device.do_config)]
    assert channel.clock_frequency_hz == 500.0
    assert channel.custom_data.bits == [1, 1, 0, 0]
    assert channel.trigger.source is TriggerSource.DIGITAL_IN
    assert (channel.trigger.sec_wait, channel.trigger.sec_run) == (0.3, 0.4)
    assert channel.trigger.repeat_count == 2
    assert channel.trigger.repeat_trigger


def test_analog_discovery_applies_idle_and_reads_waveform_settings_from_sdk() -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeDwf:
        def __getattr__(self, name):
            def call(*args):
                calls.append((name, args))
                if name.endswith("FrequencyInfo"):
                    args[-2]._obj.value = 0.001
                    args[-1]._obj.value = 100_000_000.0
                elif name.endswith("AmplitudeInfo"):
                    args[-2]._obj.value = 0.0
                    args[-1]._obj.value = 5.0
                elif name.endswith("OffsetInfo"):
                    args[-2]._obj.value = -5.0
                    args[-1]._obj.value = 5.0
                elif name.endswith("SymmetryInfo"):
                    args[-2]._obj.value = 0.0
                    args[-1]._obj.value = 100.0
                elif name.endswith("PhaseInfo"):
                    args[-2]._obj.value = -360.0
                    args[-1]._obj.value = 360.0
                elif name == "FDwfAnalogOutIdleInfo":
                    args[-1]._obj.value = 0b111
                return 1

            return call

    device = AnalogDiscovery2(enabled=False, dwf=FakeDwf())
    config = coerce_wfg_config(
        {
            "channels": [
                {
                    "channel_index": 0,
                    "idle_state": "Offset",
                    "carrier": {"frequency_hz": 1234.0, "amplitude_v": 0.75},
                }
            ]
        }
    )
    device._configure_wfg(7, config)
    idle_call = next(args for name, args in calls if name == "FDwfAnalogOutIdleSet")
    assert idle_call[-1].value == 1

    class FakeReadDwf:
        def __getattr__(self, name):
            def call(*args):
                node = args[2].value if len(args) == 4 else None
                values = {
                    "FDwfAnalogOutNodeEnableGet": 1,
                    "FDwfAnalogOutNodeFunctionGet": 2 if node == 0 else 3,
                    "FDwfAnalogOutNodeFrequencyGet": 1234.0 if node == 0 else 500.0,
                    "FDwfAnalogOutNodeAmplitudeGet": 0.75 if node == 0 else 10.0,
                    "FDwfAnalogOutNodeOffsetGet": 0.1 if node == 0 else 0.0,
                    "FDwfAnalogOutNodeSymmetryGet": 50.0,
                    "FDwfAnalogOutNodePhaseGet": 0.0,
                    "FDwfAnalogOutWaitGet": 0.2,
                    "FDwfAnalogOutRunGet": 0.4,
                    "FDwfAnalogOutRepeatGet": 3,
                    "FDwfAnalogOutRepeatTriggerGet": 1,
                    "FDwfAnalogOutTriggerSourceGet": 5,
                    "FDwfAnalogOutIdleGet": 1,
                }
                args[-1]._obj.value = values[name]
                return 1

            return call

    device._dwf = FakeReadDwf()
    device.enabled = True
    device.device_handle = 7
    device.wfg_config = config
    channel = device.wfg_readback().channels[0]
    assert channel.carrier.frequency_hz == 1234.0
    assert channel.carrier.function.value == "Square"
    assert channel.fm_mod.frequency_hz == 500.0
    assert channel.fm_mod.amplitude_v == 10.0
    assert channel.idle_state is AnalogOutputIdleState.OFFSET
    assert channel.trigger.source is TriggerSource.DIGITAL_IN


def test_analog_discovery_reads_supported_node_functions_from_sdk() -> None:
    class FakeDwf:
        def FDwfAnalogOutNodeFunctionInfo(self, _handle, _channel, _node, value):
            value._obj.value = (1 << 1) | (1 << 3) | (1 << 5)
            return 1

    device = AnalogDiscovery2(enabled=False, dwf=FakeDwf())
    assert device._analog_out_node_functions(c_int(7), c_int(0), c_int(0)) == (
        "Sine",
        "Triangle",
        "RampDown",
    )


def test_analog_discovery_cleanup_stops_resets_and_closes_directly() -> None:
    device = AnalogDiscovery2(enabled=False)
    operations: list[tuple[object, ...]] = []
    device.device_handle = 13
    device.scope_state = ScopeState.ARMED
    device._stop_analog_output = lambda handle, channel: operations.append(
        ("stop", handle, channel)
    )
    device._reset_analog_output = lambda handle, channel: operations.append(
        ("reset", handle, channel)
    )
    device._stop_digital_output = lambda handle: operations.append(("stop-do", handle))
    device._reset_digital_output = lambda handle: operations.append(("reset-do", handle))
    device._reset_scope = lambda handle: operations.append(("reset-scope", handle))
    device._close = lambda handle: operations.append(("close", handle))

    device.cleanup()

    assert operations == [
        ("stop", 13, 0),
        ("reset", 13, 0),
        ("stop", 13, 1),
        ("reset", 13, 1),
        ("stop-do", 13),
        ("reset-do", 13),
        ("reset-scope", 13),
        ("close", 13),
    ]
    assert device.device_handle is None
    assert device.scope_state is ScopeState.IDLE


def test_analog_discovery_scope_can_arm_trigger_and_read_in_sequence() -> None:
    device = AnalogDiscovery2(enabled=False)
    operations: list[tuple[object, ...]] = []
    device.enabled = True
    device._open_device = lambda _index: 17
    device._configure_scope = lambda handle, config: operations.append(
        ("configure-scope", handle, config)
    )
    device._trigger_pc = lambda handle: operations.append(("trigger", handle))
    device._read_scope = lambda handle, config: (
        operations.append(("read-scope", handle, config)) or {0: [1.0, 2.0]}
    )

    configuration = ScopeConfig(
        sample_count=2,
        trigger_source=TriggerSource.DIGITAL_OUT,
    )
    device.scope_configure(configuration)
    assert device.scope_state is ScopeState.ARMED

    device.pc_trigger()
    samples = device.scope_read()

    assert samples == {0: [1.0, 2.0]}
    assert [operation[0] for operation in operations] == [
        "configure-scope",
        "trigger",
        "read-scope",
    ]
    assert device.scope_state is ScopeState.IDLE


def test_analog_discovery_scope_read_requires_an_armed_scope() -> None:
    with pytest.raises(AnalogDiscoveryError, match="requires an armed scope"):
        AnalogDiscovery2(enabled=False).scope_read()


def test_simulated_scope_uses_the_same_arm_and_read_lifecycle() -> None:
    device = SimulatedAD2()
    device.initialize()

    device.scope_configure({"channels": [0, 1], "sample_count": 3})
    device.pc_trigger()
    samples = device.scope_read()

    assert samples == {0: [0.0, 0.0, 0.0], 1: [0.0, 0.0, 0.0]}
    assert device.triggered
    assert not device.scope_armed


def test_scope_configuration_models_shared_timing_and_detector_trigger() -> None:
    config = coerce_scope_config(
        {
            "sample_count": 4000,
            "sample_frequency_hz": 2_000_000,
            "pretrigger_samples": 1000,
            "channels": [
                {"channel_index": 0, "range_v": 2.0, "offset_v": 0.1},
                {"channel_index": 1, "range_v": 5.0, "offset_v": -0.2},
            ],
            "trigger": {
                "source": "trigsrcDetectorAnalogIn",
                "channel_index": 1,
                "trigger_type": "Pulse",
                "condition": "Falling/Negative",
                "filter": "Average",
                "level_v": 0.4,
                "hysteresis_v": 0.05,
                "length_condition": "Less",
                "length_s": 0.001,
                "holdoff_s": 0.002,
                "auto_timeout_s": 1.0,
            },
        }
    )

    assert config.trigger_position_s == pytest.approx(0.0005)
    assert config.trigger.source is TriggerSource.DETECTOR_ANALOG_IN
    assert config.trigger.channel_index == 1
    assert config.trigger.trigger_type is ScopeTriggerType.PULSE
    assert config.trigger.condition is ScopeTriggerCondition.FALLING_NEGATIVE
    assert config.trigger.filter is ScopeTriggerFilter.AVERAGE
    assert config.trigger.length_condition is ScopeTriggerLengthCondition.LESS
    assert [channel.channel_index for channel in config.channels] == [0, 1]
    assert ScopeConfig(trigger_source=TriggerSource.PC).trigger.source is TriggerSource.PC


def test_scope_configuration_reaches_each_waveforms_trigger_setter() -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []

    class RecordingDwf:
        def __getattr__(self, name):
            def call(*arguments):
                calls.append(
                    (
                        name,
                        tuple(
                            argument.value if hasattr(argument, "value") else argument
                            for argument in arguments
                        ),
                    )
                )
                return 1

            return call

    device = AnalogDiscovery2(enabled=False)
    device._dwf = RecordingDwf()
    config = coerce_scope_config(
        {
            "sample_count": 4000,
            "sample_frequency_hz": 2_000_000,
            "pretrigger_samples": 1000,
            "channels": [0, 1],
            "trigger": {
                "source": "trigsrcDetectorAnalogIn",
                "channel_index": 1,
                "trigger_type": "Pulse",
                "condition": "Falling/Negative",
                "filter": "Average",
                "level_v": 0.4,
                "hysteresis_v": 0.05,
                "length_condition": "Less",
                "length_s": 0.001,
                "holdoff_s": 0.002,
                "auto_timeout_s": 1.0,
            },
        }
    )
    device._configure_scope(7, config)

    by_name = {name: arguments for name, arguments in calls}
    assert by_name["FDwfAnalogInFrequencySet"] == (7, 2_000_000.0)
    assert by_name["FDwfAnalogInBufferSizeSet"] == (7, 4000)
    assert by_name["FDwfAnalogInTriggerSourceSet"] == (7, 2)
    assert by_name["FDwfAnalogInTriggerPositionSet"] == (7, pytest.approx(0.0005))
    assert by_name["FDwfAnalogInTriggerChannelSet"] == (7, 1)
    assert by_name["FDwfAnalogInTriggerTypeSet"] == (7, 1)
    assert by_name["FDwfAnalogInTriggerConditionSet"] == (7, 1)
    assert by_name["FDwfAnalogInTriggerFilterSet"] == (7, 1)
    assert by_name["FDwfAnalogInTriggerLevelSet"] == (7, 0.4)
    assert by_name["FDwfAnalogInTriggerHysteresisSet"] == (7, 0.05)
    assert by_name["FDwfAnalogInTriggerLengthConditionSet"] == (7, 0)
    assert by_name["FDwfAnalogInTriggerLengthSet"] == (7, 0.001)
    assert by_name["FDwfAnalogInTriggerHoldOffSet"] == (7, 0.002)
    assert by_name["FDwfAnalogInTriggerAutoTimeoutSet"] == (7, 1.0)


def test_scope_sdk_readback_reports_actual_applied_values() -> None:
    scalar_values = {
        "FDwfAnalogInFrequencyGet": 1_999_999.0,
        "FDwfAnalogInBufferSizeGet": 3999,
        "FDwfAnalogInTriggerPositionGet": 0.0005,
        "FDwfAnalogInTriggerSourceGet": 2,
        "FDwfAnalogInTriggerChannelGet": 1,
        "FDwfAnalogInTriggerTypeGet": 1,
        "FDwfAnalogInTriggerConditionGet": 1,
        "FDwfAnalogInTriggerFilterGet": 1,
        "FDwfAnalogInTriggerLevelGet": 0.4,
        "FDwfAnalogInTriggerHysteresisGet": 0.05,
        "FDwfAnalogInTriggerLengthConditionGet": 0,
        "FDwfAnalogInTriggerLengthGet": 0.001,
        "FDwfAnalogInTriggerHoldOffGet": 0.002,
        "FDwfAnalogInTriggerAutoTimeoutGet": 1.0,
    }

    class ReadbackDwf:
        def __getattr__(self, name):
            def call(*arguments):
                pointer = arguments[-1]
                if name == "FDwfAnalogInChannelRangeGet":
                    pointer._obj.value = 2.0 if arguments[1].value == 0 else 5.0
                elif name == "FDwfAnalogInChannelOffsetGet":
                    pointer._obj.value = 0.1 if arguments[1].value == 0 else -0.2
                else:
                    pointer._obj.value = scalar_values[name]
                return 1

            return call

    device = AnalogDiscovery2(enabled=False)
    device._dwf = ReadbackDwf()
    requested = coerce_scope_config(
        {
            "sample_count": 4000,
            "sample_frequency_hz": 2_000_000,
            "pretrigger_samples": 1000,
            "channels": [0, 1],
            "trigger": {"source": "trigsrcDetectorAnalogIn"},
        }
    )
    applied = device._read_scope_configuration(7, requested)

    assert applied.sample_frequency_hz == 1_999_999.0
    assert applied.sample_count == 3999
    assert applied.pretrigger_samples == 1000
    assert [(item.range_v, item.offset_v) for item in applied.channels] == [
        (2.0, 0.1),
        (5.0, -0.2),
    ]
    assert applied.trigger.channel_index == 1
    assert applied.trigger.trigger_type is ScopeTriggerType.PULSE
    assert applied.trigger.condition is ScopeTriggerCondition.FALLING_NEGATIVE


def test_simulated_scope_supports_readback_poll_and_abort() -> None:
    device = SimulatedAD2()
    device.initialize()
    device.scope_configure(
        {
            "sample_count": 8,
            "sample_frequency_hz": 1000,
            "pretrigger_samples": 3,
            "trigger": {"source": "trigsrcPC"},
        }
    )
    readback = device.scope_readback()
    assert readback.sample_count == 8
    assert readback.pretrigger_samples == 3
    assert device.scope_poll() == {0: [0.0] * 8}
    assert not device.scope_armed

    device.scope_configure({"sample_count": 4})
    device.scope_abort()
    assert not device.scope_armed
