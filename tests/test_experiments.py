"""Passive experiment tests use simulated workers only."""

from __future__ import annotations

from copy import deepcopy
import json
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application.controller import ApplicationController
from thermo_acoustic.application.commands import Ad2AnalogOutputIdle, Ad2WaveformFunction, CameraConfigureRoiArgs, CameraSequenceResult, DeviceCommand, DeviceOperation, PumpMoveArgs
from thermo_acoustic.application.experiments import default_definition, validate_definition
from thermo_acoustic.application.experiment_storage import SeriesStorage
from thermo_acoustic.application.experiment_runner import ExperimentManager
from thermo_acoustic.console.parser import ExperimentConsoleCommand, parse_command
from thermo_acoustic.domain.models import DeviceId, FloatRange, OperatingMode
from thermo_acoustic.drivers.ad2 import AnalogDiscovery2
from thermo_acoustic.hal.registry import DeviceRegistry


def until(app, predicate, timeout=10):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        sleep(0.01)
    assert predicate(), "Timed out waiting for simulated experiment"


def described_default_definition():
    definition = deepcopy(default_definition())
    definition["description"] = "Offline test series"
    return definition


def test_sweep_cartesian_order_and_parameter_refs():
    definition = default_definition()
    sweep = definition["steps"][1]
    sweep["parameters"] = {"frequency_hz": [1e6, 2e6],
                           "amplitude_v": {"start": 1, "stop": 2, "step": 1}}
    sweep["steps"][0]["count"] = 2
    expanded = validate_definition(definition)
    assert len(expanded.experiments) == 8
    assert [item.parameters for item in expanded.experiments[::2]] == [
        {"frequency_hz": 1e6, "amplitude_v": 1.0},
        {"frequency_hz": 1e6, "amplitude_v": 2.0},
        {"frequency_hz": 2e6, "amplitude_v": 1.0},
        {"frequency_hz": 2e6, "amplitude_v": 2.0},
    ]
    assert expanded.experiments[0].relative_path.endswith("repeat_0001")
    assert expanded.experiments[1].relative_path.endswith("repeat_0002")
    assert isinstance(parse_command("experiment status"), ExperimentConsoleCommand)
    parsed = parse_command(r"experiment queue C:\runs\plan.json --output-root C:\data --format stacked")
    assert parsed.path == r"C:\runs\plan.json"
    assert parsed.output_root == r"C:\data"


def test_rejects_conflicting_parallel_resources_and_bad_order():
    definition = default_definition()
    experiment = definition["steps"][1]["steps"][0]["steps"][0]["steps"]
    experiment[-1]["branches"].append([{"type": "flush", "args": {
        "unit_index": 0, "volume_ml": 0.1, "flow_ul_min": 100}}])
    with pytest.raises(ValueError, match="parallel resource conflict"):
        validate_definition(definition)
    definition = default_definition()
    experiment = definition["steps"][1]["steps"][0]["steps"][0]["steps"]
    experiment[4], experiment[5] = experiment[5], experiment[4]
    with pytest.raises(ValueError, match="Configure and arm"):
        validate_definition(definition)
    definition = default_definition()
    definition["steps"].insert(0, {"type": "shell", "args": {"command": "echo unsafe"}})
    with pytest.raises(ValueError, match="Unsupported experiment action"):
        validate_definition(definition)


def test_stacked_tiff_page_mapping_and_missing_stamp(tmp_path):
    expansion = validate_definition(default_definition())
    storage = SeriesStorage(tmp_path, expansion, "stacked")
    experiment = expansion.experiments[0]
    frames = tuple(np.full((4, 4), value, dtype=np.uint16) for value in range(10))
    missing = CameraSequenceResult(frames, (), tuple("2026-09-24T00:00:00+00:00" for _ in frames))
    with pytest.raises(ValueError, match="Incomplete camera acquisition"):
        storage.save_frames(experiment, missing, {})
    complete = CameraSequenceResult(frames, tuple(f"dcam_clock:{i}" for i in range(10)),
                                    missing.host_received_utc, {"sensor": "simulation"})
    record = storage.save_frames(experiment, complete, {})
    assert [entry["page_index"] for entry in record["frames"]] == list(range(10))
    with Image.open(storage.folder / experiment.relative_path / "sequence.tif") as image:
        assert image.n_frames == 10
    assert record["timestamp_clock_domains"]["host_received_utc"].startswith("Host UTC")


def test_dio_experiment_configuration_calculates_divider_and_initial_delay_without_hardware():
    class FakeDwf:
        def FDwfDigitalOutCounterInfo(self, _handle, _channel, minimum, maximum):
            minimum._obj.value = 0
            maximum._obj.value = 65535
            return 1
        def FDwfDigitalOutRunInfo(self, _handle, minimum, maximum):
            minimum._obj.value = 0
            maximum._obj.value = 100
            return 1
    driver = AnalogDiscovery2(enabled=False, dwf=FakeDwf())
    driver.enabled = True  # exercise the method against a fake, not a DLL
    driver.device_handle = 1  # synthetic handle, never passed to an SDK DLL
    driver._digital_out_internal_clock_info = lambda _handle: 100_000_000.0
    driver._digital_out_divider_info = lambda _handle, _channel: (1, 100_000_000)
    applied = []
    driver._configure_do = lambda _handle, config: applied.append(config)
    result = driver.experiment_digital_configure(10, 10.0, 0.1, led_enabled=False)
    assert result["achieved_frame_rate_hz"] == 10.0
    assert result["global_run_s"] == 1.1
    channel0, channel1 = applied[0].channels
    assert channel0.clock_divider == 5_000_000
    assert channel0.counter_initial_bits == 2  # 0.1 s * 2 * 10 pulse/s
    assert not channel0.start_high and channel0.counter_low_bits == channel0.counter_high_bits == 1
    assert not channel1.enable  # count preflight never illuminates the LED


def test_tec_json_channel_keys_are_normalized_for_worker_arguments():
    args = ExperimentManager._tec_args({"target_temperature_c": {"1": 37.0, "2": 38.0},
                                        "channels": [1, 2]})
    assert args == {"target_temperature_c": {1: 37.0, 2: 38.0}, "channels": (1, 2)}


def test_experiment_laser_uses_live_wfg2_minimum_and_safe_offset_idle():
    expanded = validate_definition(default_definition())
    settings = next(step["args"] for step in expanded.experiments[0].steps
                    if step["type"] == "ad2_configure")
    settings["laser"]["enabled"] = True
    settings["laser"]["on_voltage_v"] = 0.5
    capability = SimpleNamespace(channel_index=1, carrier=SimpleNamespace(
        functions=("Square",), frequency_hz=FloatRange(1e-6, 1e8)))
    controller = SimpleNamespace(statuses=lambda: {DeviceId.AD2: SimpleNamespace(
        readback=SimpleNamespace(capabilities=SimpleNamespace(waveform_channels=(capability,))))})
    frequency = ExperimentManager._read_laser_min_frequency(SimpleNamespace(controller=controller))
    channels = ExperimentManager._waveform_args(settings, frequency).resolved_channels()
    ultrasound, laser = channels
    assert ultrasound.function is Ad2WaveformFunction.SINE
    assert ultrasound.idle_state is Ad2AnalogOutputIdle.OFFSET
    assert laser.function is Ad2WaveformFunction.SQUARE
    assert laser.frequency_hz == 1e-6
    assert laser.amplitude_v == 0.5
    assert laser.offset_v == laser.phase_deg == 0
    assert laser.idle_state is Ad2AnalogOutputIdle.OFFSET
    ExperimentManager._validate_laser_window(settings, frequency)
    with pytest.raises(ValueError, match="low half"):
        ExperimentManager._validate_laser_window(settings, 1.0)
    with pytest.raises(RuntimeError, match="capabilities are unavailable"):
        ExperimentManager._read_laser_min_frequency(SimpleNamespace(
            controller=SimpleNamespace(statuses=lambda: {DeviceId.AD2: SimpleNamespace(readback=None)})))


def test_experiment_rejects_nonzero_ultrasound_idle_offset_and_negative_laser_voltage():
    definition = default_definition()
    steps = definition["steps"][1]["steps"][0]["steps"][0]["steps"]
    ad2 = next(step["args"] for step in steps if step["type"] == "ad2_configure")
    ad2["ultrasound"]["offset_v"] = 0.1
    with pytest.raises(ValueError, match="ultrasound.offset_v must be 0"):
        validate_definition(definition)
    ad2["ultrasound"]["offset_v"] = 0
    ad2["laser"]["on_voltage_v"] = -0.1
    with pytest.raises(ValueError, match="laser.on_voltage_v"):
        validate_definition(definition)


def test_simulated_series_writes_timestamped_images_and_metadata(tmp_path):
    app = QApplication.instance() or QApplication(["test-experiments"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        until(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok
                               for result in results) == 2)
        controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_ROI_CONFIGURE,
                                        CameraConfigureRoiArgs(0, 0, 16, 16)))
        until(app, lambda: any(result.operation is DeviceOperation.CAMERA_ROI_CONFIGURE for result in results))
        definition = described_default_definition()
        definition["steps"] = [definition["steps"][1]]
        experiment = definition["steps"][0]["steps"][0]["steps"][0]["steps"]
        experiment[-1]["branches"][1] = [{"type": "wait_outputs", "args": {}}]
        experiment[0]["args"]["frame_count"] = 2
        experiment[1]["args"]["dio"]["frame_count"] = 2
        experiment[1]["args"]["laser"]["enabled"] = True
        experiment[1]["args"]["laser"]["on_voltage_v"] = 0.5
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        until(app, lambda: controller.experiments.status()["state"] in {"completed", "failed"})
        assert controller.experiments.status()["state"] == "completed"
        progress = controller.experiments.status()
        assert progress["planned_experiments"] == progress["batch_completed_experiments"] == 1
        assert progress["series"][0]["state"] == "completed"
        assert progress["series"][0]["description"] == "Offline test series"
        manifest = json.loads((folder / "metadata" / "manifest.json").read_text())
        leaf = folder / manifest["experiments"][0]["relative_path"]
        record = json.loads((leaf / "experiment.json").read_text())
        assert record["frame_count"] == 2
        assert len(record["frames"]) == 2
        assert all(item["camera_sdk_timestamp"] for item in record["frames"])
        assert record["physical_dio0_edges_verified"] is False
        assert all((leaf / item["filename"]).exists() for item in record["frames"])
        assert record["applied_settings"]["ad2_digital"]["achieved_frame_rate_hz"] == 10
        operations = [event.operation for event in events if event.source == "experiment" and event.state == "completed"]
        assert operations.index(DeviceOperation.CAMERA_SEQUENCE_ARM) < operations.index(DeviceOperation.AD2_SOFTWARE_TRIGGER)
        assert operations.index(DeviceOperation.AD2_WAVEFORM_START) < operations.index(DeviceOperation.AD2_SOFTWARE_TRIGGER)
        assert operations.index(DeviceOperation.AD2_DIGITAL_OUTPUT_START) < operations.index(DeviceOperation.AD2_SOFTWARE_TRIGGER)
        assert operations.index(DeviceOperation.AD2_SOFTWARE_TRIGGER) < operations.index(DeviceOperation.CAMERA_SEQUENCE_COLLECT)
        assert operations.count(DeviceOperation.AD2_SOFTWARE_TRIGGER) == 1
        assert operations.count(DeviceOperation.CAMERA_CONTINUOUS_CAPTURE) >= 2
    finally:
        controller.shutdown()


def test_count_preflight_uses_fake_workers_and_discards_test_images(tmp_path):
    app = QApplication.instance() or QApplication(["test-experiments"])
    # Deliberately supply simulation factories while exercising the real-mode
    # approval/preflight path. No hardware or SDK handle is opened by this test.
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.REAL)
    controller.experiments.confirm_batch = lambda _summary: True
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        until(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok
                               for result in results) == 2)
        controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_ROI_CONFIGURE,
                                        CameraConfigureRoiArgs(0, 0, 16, 16)))
        until(app, lambda: any(result.operation is DeviceOperation.CAMERA_ROI_CONFIGURE for result in results))
        definition = described_default_definition()
        definition["preflight"] = True
        definition["steps"] = [definition["steps"][1]]
        experiment = definition["steps"][0]["steps"][0]["steps"][0]["steps"]
        experiment[-1]["branches"][1] = [{"type": "wait_outputs", "args": {}}]
        experiment[0]["args"]["frame_count"] = 2
        experiment[1]["args"]["dio"]["frame_count"] = 2
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        until(app, lambda: controller.experiments.status()["state"] in {"completed", "failed"})
        assert controller.experiments.status()["state"] == "completed"
        events = (folder / "metadata" / "events.jsonl").read_text()
        assert "count_preflight" in events
        assert '"physical_dio0_edges_verified": false' in events
        assert '"applied_dio"' in events
        assert len(list(folder.rglob("*.tif"))) == 2  # experiment only; preflight images discarded
        triggers = [result for result in results if result.operation is DeviceOperation.AD2_SOFTWARE_TRIGGER]
        assert len(triggers) == 2  # one count check plus one experiment
    finally:
        controller.shutdown()


def test_save_failure_stops_later_queued_series_without_overwriting(tmp_path):
    app = QApplication.instance() or QApplication(["test-experiments"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        until(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok
                               for result in results) == 2)
        controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_ROI_CONFIGURE,
                                        CameraConfigureRoiArgs(0, 0, 16, 16)))
        until(app, lambda: any(result.operation is DeviceOperation.CAMERA_ROI_CONFIGURE for result in results))
        definition = described_default_definition()
        definition["steps"] = [definition["steps"][1]]
        experiment = definition["steps"][0]["steps"][0]["steps"][0]["steps"]
        experiment[-1]["branches"][1] = [{"type": "wait_outputs", "args": {}}]
        experiment[0]["args"]["frame_count"] = 2
        experiment[1]["args"]["dio"]["frame_count"] = 2
        first = controller.experiments.queue(definition, tmp_path)
        second = controller.experiments.queue(definition, tmp_path)
        assert first != second
        storage = controller.experiments._queued[0][1]
        def fail_save(*_args, **_kwargs):
            raise OSError("simulated disk failure")
        storage.save_frames = fail_save
        assert controller.experiments.start()
        until(app, lambda: controller.experiments.status()["state"] in {"failed", "aborted"})
        assert controller.experiments.status()["state"] == "failed"
        assert "simulated disk failure" in (first / "metadata" / "status.json").read_text()
        assert '"state": "cancelled"' in (second / "metadata" / "status.json").read_text()
        assert not list(second.rglob("*.tif"))
    finally:
        controller.shutdown()


def test_missing_sdk_timestamp_fails_acquisition_and_retains_partial_frames(tmp_path):
    app = QApplication.instance() or QApplication(["test-experiments"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        until(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok
                               for result in results) == 2)
        controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_ROI_CONFIGURE,
                                        CameraConfigureRoiArgs(0, 0, 16, 16)))
        until(app, lambda: any(result.operation is DeviceOperation.CAMERA_ROI_CONFIGURE for result in results))
        camera = controller.registry.by_id(DeviceId.CAMERA).device
        camera.finish_buffered_sequence = lambda: (camera.stop_capture(), ())[1]
        definition = described_default_definition()
        definition["steps"] = [definition["steps"][1]]
        experiment = definition["steps"][0]["steps"][0]["steps"][0]["steps"]
        experiment[-1]["branches"][1] = [{"type": "wait_outputs", "args": {}}]
        experiment[0]["args"]["frame_count"] = 2
        experiment[1]["args"]["dio"]["frame_count"] = 2
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        until(app, lambda: controller.experiments.status()["state"] == "failed")
        manifest = json.loads((folder / "metadata" / "manifest.json").read_text())
        partial = folder / manifest["experiments"][0]["relative_path"] / "partial_capture"
        record = json.loads((partial / "partial.json").read_text())
        assert record["acquisition_status"] == "partial_failed"
        assert record["captured_frames"] == 2
        assert len(list(partial.glob("*.tif"))) == 2
    finally:
        controller.shutdown()


def test_capability_failure_is_detected_before_initial_flush(tmp_path):
    app = QApplication.instance() or QApplication(["test-experiments"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    results = []
    events = []
    controller.command_result.connect(results.append)
    controller.command_event.connect(events.append)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        until(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok
                               for result in results) == 4)
        controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_REFILL,
                                        PumpMoveArgs(flow_rate_ul_min=1000)))
        until(app, lambda: any(result.operation is DeviceOperation.PUMP_REFILL for result in results))
        camera = controller.registry.by_id(DeviceId.CAMERA).device
        camera.configure_sequence = lambda _settings: (_ for _ in ()).throw(
            ValueError("fake unsupported exposure"))
        definition = described_default_definition()
        definition["steps"][0]["args"]["volume_ml"] = 0.001
        experiment = definition["steps"][1]["steps"][0]["steps"][0]["steps"]
        experiment[-1]["branches"][1][1]["args"]["volume_ml"] = 0.001
        controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        until(app, lambda: controller.experiments.status()["state"] == "failed")
        assert not any(event.operation.value == "workflow.flush" and event.source == "experiment"
                       for event in events)
    finally:
        controller.shutdown()


def test_file_save_and_post_output_flush_overlap_without_blocking_preview(tmp_path):
    app = QApplication.instance() or QApplication(["test-experiments"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        until(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok
                               for result in results) == 4)
        controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_ROI_CONFIGURE,
                                        CameraConfigureRoiArgs(0, 0, 16, 16)))
        controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_REFILL,
                                        PumpMoveArgs(flow_rate_ul_min=1000)))
        until(app, lambda: any(result.operation is DeviceOperation.PUMP_REFILL for result in results))
        definition = described_default_definition()
        definition["steps"] = [definition["steps"][1]]
        experiment = definition["steps"][0]["steps"][0]["steps"][0]["steps"]
        experiment[0]["args"]["frame_count"] = 2
        experiment[1]["args"]["dio"]["frame_count"] = 2
        flush = experiment[-1]["branches"][1][1]["args"]
        flush["volume_ml"] = 0.001
        flush["flow_ul_min"] = 1000
        folder = controller.experiments.queue(definition, tmp_path)
        storage = controller.experiments._queued[0][1]
        original = storage.save_frames
        def slow_save(*args, **kwargs):
            sleep(1.0)
            return original(*args, **kwargs)
        storage.save_frames = slow_save
        assert controller.experiments.start()
        until(app, lambda: controller.experiments.status()["state"] in {"completed", "failed"}, timeout=10)
        assert controller.experiments.status()["state"] == "completed"
        events = [json.loads(line) for line in (folder / "metadata" / "events.jsonl").read_text().splitlines()]
        saved = next(event for event in events if event["event"] == "frames_saved")
        finished = next(event for event in events if event["event"] == "experiment_completed")
        assert saved["timestamp_utc"] < finished["timestamp_utc"]
        assert controller.statuses()[DeviceId.CAMERA].readback.mode == "continuous"
    finally:
        controller.shutdown()


def test_save_failure_waits_for_already_started_flush_cleanup(tmp_path):
    app = QApplication.instance() or QApplication(["test-experiments"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        until(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok
                               for result in results) == 4)
        controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_ROI_CONFIGURE,
                                        CameraConfigureRoiArgs(0, 0, 16, 16)))
        controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_REFILL,
                                        PumpMoveArgs(flow_rate_ul_min=1000)))
        until(app, lambda: any(result.operation is DeviceOperation.PUMP_REFILL for result in results))
        definition = described_default_definition()
        definition["steps"] = [definition["steps"][1]]
        experiment = definition["steps"][0]["steps"][0]["steps"][0]["steps"]
        experiment[0]["args"]["frame_count"] = 2
        experiment[1]["args"]["dio"]["frame_count"] = 2
        experiment[-1]["branches"][1][1]["args"]["volume_ml"] = 0.001
        controller.experiments.queue(definition, tmp_path)
        storage = controller.experiments._queued[0][1]
        def delayed_failure(*_args, **_kwargs):
            sleep(1.0)
            raise OSError("simulated save failure during flush")
        storage.save_frames = delayed_failure
        assert controller.experiments.start()
        until(app, lambda: controller._flush is not None)
        until(app, lambda: controller.experiments.status()["state"] == "stopping")
        assert controller._flush is not None  # failure did not abort the active flush
        until(app, lambda: controller.experiments.status()["state"] == "failed", timeout=10)
        assert controller._flush is None
        assert controller.statuses()[DeviceId.VALVE].readback.confirmed_position == 2
    finally:
        controller.shutdown()
