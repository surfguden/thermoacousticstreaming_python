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
from thermo_acoustic.application.commands import Ad2AnalogOutputIdle, Ad2WaveformFunction, CameraConfigureRoiArgs, CameraSequenceResult, DeviceCommand, DeviceOperation, PumpMoveArgs, PumpSetFillLevelArgs
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
    bad_root = tmp_path / "bad"
    bad_root.mkdir()
    bad_storage = SeriesStorage(bad_root, expansion, "stacked")
    bad_experiment = expansion.experiments[0]
    bad_frames = (np.zeros((4, 4, 3), dtype=np.uint16),) + frames[1:]
    invalid = CameraSequenceResult(bad_frames, complete.timestamps,
                                   complete.host_received_utc, complete.settings)
    with pytest.raises(ValueError, match="non-grayscale"):
        bad_storage.save_frames(bad_experiment, invalid, {})
    assert not (bad_storage.folder / bad_experiment.relative_path).exists()
    assert not list(bad_storage.folder.rglob(".capture_*"))


def test_experiment_base_must_be_empty_and_uses_numbered_batch_folders(tmp_path):
    expansion = validate_definition(default_definition())
    first = SeriesStorage(tmp_path, expansion, "frames")
    assert first.folder.name == "experiment_batch_0001"
    with pytest.raises(ValueError, match="must be empty"):
        SeriesStorage(tmp_path, expansion, "frames")
    second = SeriesStorage(tmp_path, expansion, "frames", continuing_batch=True)
    assert second.folder.name == "experiment_batch_0002"


def test_duplicate_parameter_path_is_rejected_before_storage(tmp_path):
    definition = default_definition()
    definition["steps"][1]["parameters"]["frequency_hz"] = [2e6, 2e6]
    with pytest.raises(ValueError, match="Duplicate experiment parameter path"):
        validate_definition(definition)
    assert not list(tmp_path.iterdir())


def test_failure_discards_only_unfinished_experiment(tmp_path):
    QApplication.instance() or QApplication(["test-experiments"])
    definition = default_definition()
    definition["steps"][1]["steps"][0]["count"] = 2
    expansion = validate_definition(definition)
    storage = SeriesStorage(tmp_path, expansion, "frames")
    frames = tuple(np.zeros((4, 4), dtype=np.uint16) for _ in range(10))
    capture = CameraSequenceResult(frames, tuple(f"sdk:{i}" for i in range(10)),
                                   tuple("2026-09-25T00:00:00+00:00" for _ in frames))
    for experiment in expansion.experiments:
        storage.save_frames(experiment, capture, {})
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    manager = controller.experiments
    manager._current = (expansion, storage)
    manager._experiment = expansion.experiments[1]
    manager._failure_reason = "simulated later failure"
    manager._state = "stopping"
    manager._completed = 1
    manager._finish_failure_when_safe()
    assert (storage.folder / expansion.experiments[0].relative_path / "experiment.json").exists()
    assert not (storage.folder / expansion.experiments[1].relative_path).exists()
    assert manager.status()["state"] == "failed"


def test_series_lifecycle_marks_in_progress_experiment_failed_and_finalizes_once(tmp_path):
    # Mirrors the setup of test_failure_discards_only_unfinished_experiment
    # but asserts the lifecycle record itself: the completed repeat counts
    # once, the interrupted one counts as failed (even though its own folder
    # never existed to discard), and the first terminal outcome sticks even
    # if status() is called again afterward.
    QApplication.instance() or QApplication(["test-experiments"])
    definition = default_definition()
    definition["steps"][1]["steps"][0]["count"] = 2
    expansion = validate_definition(definition)
    storage = SeriesStorage(tmp_path, expansion, "frames")
    storage.record_experiment_started()
    storage.record_experiment_completed()
    storage.record_experiment_started()
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    manager = controller.experiments
    manager._current = (expansion, storage)
    manager._experiment = expansion.experiments[1]
    manager._failure_reason = "simulated later failure"
    manager._state = "stopping"
    manager._completed = 1
    manager._finish_failure_when_safe()
    recorded = json.loads((storage.folder / "metadata" / "status.json").read_text())
    assert recorded["requested_experiments"] == 2
    assert recorded["experiments_started"] == 2
    assert recorded["experiments_completed"] == 1
    assert recorded["experiments_failed"] == 1
    assert recorded["finalized_outcome"] == "failed"
    first_finalized_utc = recorded["finalized_utc"]
    assert first_finalized_utc
    storage.status("completed", {})
    recorded = json.loads((storage.folder / "metadata" / "status.json").read_text())
    assert recorded["finalized_outcome"] == "failed"
    assert recorded["finalized_utc"] == first_finalized_utc


def test_series_lifecycle_counts_and_outcome_on_completion(tmp_path):
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
        definition = described_default_definition()
        definition["steps"] = [definition["steps"][1]]
        experiment = definition["steps"][0]["steps"][0]["steps"][0]["steps"]
        experiment[-1]["branches"][1] = [{"type": "wait_outputs", "args": {}}]
        experiment[0]["args"]["frame_count"] = 2
        experiment[1]["args"]["dio"]["frame_count"] = 2
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        until(app, lambda: controller.experiments.status()["state"] in {"completed", "failed"})
        assert controller.experiments.status()["state"] == "completed"
        recorded = json.loads((folder / "metadata" / "status.json").read_text())
        assert recorded["requested_experiments"] == 1
        assert recorded["experiments_started"] == 1
        assert recorded["experiments_completed"] == 1
        assert recorded["experiments_failed"] == 0
        assert recorded["finalized_outcome"] == "completed"
        assert recorded["finalized_utc"]
    finally:
        controller.shutdown()


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


def test_missing_sdk_timestamp_fails_acquisition_without_saving_frames(tmp_path):
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
        leaf = folder / manifest["experiments"][0]["relative_path"]
        assert not leaf.exists()
        assert not list(folder.rglob("*.tif"))
        assert not list(folder.rglob("partial_capture"))
        assert '"state": "failed"' in (folder / "metadata" / "status.json").read_text()
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


def _minimal_experiment_steps(frame_count: int = 2) -> list[dict]:
    return [
        {"type": "camera_configure", "args": {"frame_count": frame_count, "exposure_ms": 1, "global_exposure": False}},
        {"type": "ad2_configure", "args": {
            "ultrasound": {"enabled": True, "start_s": 0, "run_s": 1, "frequency_hz": 2000000, "amplitude_v": 1.0, "offset_v": 0},
            "laser": {"enabled": False, "start_s": 0, "run_s": 1, "on_voltage_v": 0},
            "dio": {"frame_rate_hz": 10, "camera_delay_s": 0.1, "frame_count": frame_count},
            "output_timeout_s": 10}},
        {"type": "camera_arm", "args": {}}, {"type": "ad2_arm", "args": {}},
        {"type": "pc_trigger", "args": {}}, {"type": "await_frames", "args": {}},
        {"type": "parallel", "branches": [
            [{"type": "save_frames", "args": {}}],
            [{"type": "wait_outputs", "args": {}}],
        ]},
    ]


def test_temperature_point_series_runs_each_point_in_order(tmp_path):
    # A TEC multi-point temperature series (set -> wait for stability -> hold
    # -> run an experiment group, repeated per point) needs no new execution
    # machinery: it composes entirely from tec_set/tec_wait_stable/wait/
    # experiment nodes already supported by the sweep mechanism. This is the
    # common "locked" case (both channels follow the same point list).
    app = QApplication.instance() or QApplication(["test-experiments"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.TEC):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        until(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok
                               for result in results) == 3)
        definition = {
            "version": 1, "name": "temperature_series", "description": "Temperature series test",
            "preflight": False, "tiff_format": "frames",
            "steps": [{
                "type": "sweep", "parameters": {"temperature_c": [20.0, 25.0]},
                "steps": [
                    {"type": "tec_set", "args": {"target_temperature_c":
                        {"1": {"$param": "temperature_c"}, "2": {"$param": "temperature_c"}}}},
                    {"type": "tec_wait_stable", "args": {"target_temperature_c":
                        {"1": {"$param": "temperature_c"}, "2": {"$param": "temperature_c"}},
                        "tolerance_c": 0.5, "min_settle_s": 0, "max_wait_s": 5}},
                    {"type": "wait", "args": {"seconds": 0}},
                    {"type": "repeat", "count": 1, "steps": [
                        {"type": "experiment", "steps": _minimal_experiment_steps()},
                    ]},
                ],
            }],
        }
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        until(app, lambda: controller.experiments.status()["state"] in {"completed", "failed"}, timeout=15)
        status = controller.experiments.status()
        assert status["state"] == "completed", status
        assert status["planned_experiments"] == 2
        manifest = json.loads((folder / "metadata" / "manifest.json").read_text())
        assert [item["parameters"]["temperature_c"] for item in manifest["experiments"]] == [20.0, 25.0]
        tec_set_values = [event.arguments.target_temperature_c for event in events
                          if event.operation is DeviceOperation.TEC_SETPOINTS_APPLY and event.state == "completed"]
        assert tec_set_values == [{1: 20.0, 2: 20.0}, {1: 25.0, 2: 25.0}]
        tec_set_index = [i for i, e in enumerate(events) if e.operation is DeviceOperation.TEC_SETPOINTS_APPLY
                         and e.state == "completed"]
        arm_index = [i for i, e in enumerate(events) if e.operation is DeviceOperation.CAMERA_SEQUENCE_ARM
                    and e.state == "completed"]
        assert tec_set_index[0] < arm_index[0] < tec_set_index[1] < arm_index[1]
        for item in manifest["experiments"]:
            leaf = folder / item["relative_path"]
            record = json.loads((leaf / "experiment.json").read_text())
            assert record["frame_count"] == 2
    finally:
        controller.shutdown()


def test_tec_wait_stable_argument_construction_failure_reports_cleanly(tmp_path):
    # validate_definition() only checks max_wait_s > 0 -- it has no way to
    # know TecWaitStableArgs' own poll_interval_s default (1.0 s, a software
    # polling choice, not part of the declarative JSON schema), so a
    # definition with max_wait_s below that passes validation and used to
    # reach TecWaitStableArgs(**args) inside _run_action as an uncaught
    # exception in the middle of a Qt callback chain. Confirms it now fails
    # as an ordinary, reported series failure instead.
    app = QApplication.instance() or QApplication(["test-experiments"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.TEC):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        results = []
        controller.command_result.connect(results.append)
        until(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok
                               for result in results) == 3)
        definition = {
            "version": 1, "name": "bad_poll_interval", "description": "Bad poll interval test",
            "preflight": False, "tiff_format": "frames",
            "steps": [
                {"type": "tec_set", "args": {"target_temperature_c": 20.0}},
                {"type": "tec_wait_stable", "args": {"target_temperature_c": 20.0,
                    "tolerance_c": 0.5, "min_settle_s": 0, "max_wait_s": 0.1}},  # below the 1.0s poll interval
                {"type": "repeat", "count": 1, "steps": [
                    {"type": "experiment", "steps": _minimal_experiment_steps()},
                ]},
            ],
        }
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        until(app, lambda: controller.experiments.status()["state"] == "failed", timeout=10)
        status_doc = json.loads((folder / "metadata" / "status.json").read_text())
        assert "rejected its own arguments" in status_doc["error"]
        assert "poll_interval_s" in status_doc["error"]
    finally:
        controller.shutdown()


def test_temperature_point_series_supports_independent_per_channel_targets(tmp_path):
    # The "unlocked" case: channels 1 and 2 follow different point lists in
    # lockstep, expressed as one sweep parameter whose values are themselves
    # per-channel target objects (not a cartesian cross-product of two
    # separate parameters, which would wrongly combine every ch1 value with
    # every ch2 value).
    app = QApplication.instance() or QApplication(["test-experiments"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.TEC):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        until(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok
                               for result in results) == 3)
        points = [{"1": 20.0, "2": 24.0}, {"1": 21.0, "2": 23.0}]
        definition = {
            "version": 1, "name": "temperature_series_unlocked", "description": "Unlocked temperature series test",
            "preflight": False, "tiff_format": "frames",
            "steps": [{
                "type": "sweep", "parameters": {"temperature_point": points},
                "steps": [
                    {"type": "tec_set", "args": {"target_temperature_c": {"$param": "temperature_point"}}},
                    {"type": "tec_wait_stable", "args": {"target_temperature_c": {"$param": "temperature_point"},
                        "tolerance_c": 0.5, "min_settle_s": 0, "max_wait_s": 5}},
                    {"type": "wait", "args": {"seconds": 0}},
                    {"type": "repeat", "count": 1, "steps": [
                        {"type": "experiment", "steps": _minimal_experiment_steps()},
                    ]},
                ],
            }],
        }
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        until(app, lambda: controller.experiments.status()["state"] in {"completed", "failed"}, timeout=15)
        assert controller.experiments.status()["state"] == "completed", controller.experiments.status()
        tec_set_values = [event.arguments.target_temperature_c for event in events
                          if event.operation is DeviceOperation.TEC_SETPOINTS_APPLY and event.state == "completed"]
        assert tec_set_values == [{1: 20.0, 2: 24.0}, {1: 21.0, 2: 23.0}]
    finally:
        controller.shutdown()


def _capacity_check_rejects_below_whole_series_total(app, tmp_path, definition, expected_total_ml):
    # Shared body for the three placement scenarios below: connects the
    # devices _check_capacity needs, sets the pump's fill level to just
    # under the EXPECTED whole-series total (not the test author's own
    # arithmetic alone -- the assertion on the rejection message is what
    # actually proves the engine computed the same total), and confirms
    # the series is rejected before any flush runs, citing that exact
    # number.
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
        controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_ROI_CONFIGURE,
                                        CameraConfigureRoiArgs(0, 0, 16, 16)))
        controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_SET,
                                        PumpSetFillLevelArgs(expected_total_ml - 0.03)))
        until(app, lambda: any(result.operation is DeviceOperation.PUMP_FILL_LEVEL_SET and result.ok
                               for result in results))
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        until(app, lambda: controller.experiments.status()["state"] == "failed", timeout=10)
        status_doc = json.loads((folder / "metadata" / "status.json").read_text())
        assert f"{expected_total_ml:g} mL total flush volume" in status_doc["error"], status_doc["error"]
        assert not any(event.operation.value == "workflow.flush" and event.source == "experiment"
                       for event in events)  # rejected before any flush ran, regardless of placement
    finally:
        controller.shutdown()


def test_flush_budget_sums_a_series_level_only_flush(tmp_path):
    # Placement 1: one flush outside any sweep/repeat -- associated with
    # the whole series by construction, not just by the capacity check.
    app = QApplication.instance() or QApplication(["test-experiments"])
    definition = described_default_definition()
    experiment = definition["steps"][1]["steps"][0]["steps"][0]["steps"]
    experiment[-1]["branches"][1] = [{"type": "wait_outputs", "args": {}}]  # remove the per-experiment flush
    _capacity_check_rejects_below_whole_series_total(app, tmp_path, definition, expected_total_ml=0.1)


def test_flush_budget_sums_a_per_repeat_only_flush_across_two_repeats(tmp_path):
    # Placement 2: no series-level flush; two repeats, each with its own
    # flush inside its experiment's parallel branch -- the capacity check
    # must sum both repeats' flushes, not count the per-repeat flush once.
    app = QApplication.instance() or QApplication(["test-experiments"])
    definition = described_default_definition()
    definition["steps"] = [definition["steps"][1]]  # drop the series-level flush entirely
    definition["steps"][0]["steps"][0]["count"] = 2  # two repeats
    _capacity_check_rejects_below_whole_series_total(app, tmp_path, definition, expected_total_ml=0.2)


def test_flush_budget_sums_a_mixed_series_and_per_repeat_placement(tmp_path):
    # Placement 3: a series-level flush AND two repeats each with their own
    # per-experiment flush -- the capacity check must add all three
    # together regardless of where in the tree each one sits.
    app = QApplication.instance() or QApplication(["test-experiments"])
    definition = described_default_definition()
    definition["steps"][1]["steps"][0]["count"] = 2  # two repeats, keep the series-level flush
    _capacity_check_rejects_below_whole_series_total(app, tmp_path, definition, expected_total_ml=0.3)
