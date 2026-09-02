from __future__ import annotations

import sys

import pytest

from thermo_acoustic.application import Application
from thermo_acoustic.workflows import Experiment2, ExperimentSeries2, FlushSettings


REAL_HARDWARE_MODULES = (
    "dcam",
    "dcamapi",
    "pylablib",
    "qmixsdk",
    "serial",
)


class FakeAD2:
    def __init__(self, calls):
        self.calls = calls
        self.enabled = True
        self._wfg_config = None
        self._do_config = None

    def initialize(self):
        self.calls.append(("ad2", "initialize"))

    def config_wfg(self, config):
        self.calls.append(("ad2", "config_wfg", config))
        self._wfg_config = config

    def config_do_clock_special(self, settings):
        self.calls.append(("ad2", "config_do_clock_special", settings))
        self._do_config = settings

    def get_wfg_config(self):
        return self._wfg_config

    def get_do_config(self):
        return self._do_config

    def pc_trigger(self):
        self.calls.append(("ad2", "pc_trigger"))

    def cleanup(self):
        self.calls.append(("ad2", "cleanup"))


class FakeCamera:
    def __init__(self, calls):
        self.calls = calls
        self.sequence_config = None
        self.exposure_ms = None
        self.capturing = False
        self.simulate = True
        self.enabled = True
        self.roi = {
            "horizontal_offset": 999,
            "vertical_offset": 999,
            "horizontal_size": 16,
            "vertical_size": 16,
        }
        self.applied_roi = {
            "horizontal_offset": 0,
            "vertical_offset": 792,
            "horizontal_size": 2304,
            "vertical_size": 736,
        }

    def initialize(self):
        self.calls.append(("camera", "initialize"))

    def configure(self, exposure_ms=None):
        self.exposure_ms = exposure_ms
        self.calls.append(("camera", "configure", exposure_ms))

    def configure_exposure_time(self, exposure_ms):
        self.exposure_ms = exposure_ms
        self.calls.append(("camera", "configure_exposure_time", exposure_ms))
        return exposure_ms

    def configure_roi(self, roi):
        self.calls.append(("camera", "configure_roi", roi))

    def read_subregion_limits_and_value(self):
        self.roi = dict(self.applied_roi)
        self.calls.append(("camera", "read_subregion_limits_and_value", self.roi))
        return None, self.roi

    def configure_sequence(self, settings):
        self.sequence_config = settings
        self.calls.append(("camera", "configure_sequence", settings))

    def configure_trigger_global_exposure(self, enabled):
        self.calls.append(("camera", "configure_trigger_global_exposure", enabled))

    def start_capture(self):
        self.capturing = True
        self.calls.append(("camera", "start_capture"))

    def image_sequence(self, frame_count=0, partial_capture_folder=None):
        self.calls.append(("camera", "image_sequence", frame_count))
        return [f"fake-frame-{index}" for index in range(frame_count)]

    def read_frame_timestamps(self):
        self.calls.append(("camera", "read_frame_timestamps"))
        return []

    def stop_capture(self):
        self.capturing = False
        self.calls.append(("camera", "stop_capture"))

    def save_sequence(self, image_data, folder):
        self.calls.append(("camera", "save_sequence", tuple(image_data), folder))
        folder.mkdir(parents=True, exist_ok=True)

    def get_camera_buffer_size(self):
        self.calls.append(("camera", "get_camera_buffer_size"))
        return 0

    def get_sub_region(self):
        self.calls.append(("camera", "get_sub_region"))
        return self.roi

    def read_readout_time(self):
        self.calls.append(("camera", "read_readout_time"))
        return 0.0

    def cleanup(self):
        self.calls.append(("camera", "cleanup"))


class FakePump:
    def __init__(self, calls):
        self.calls = calls
        self.fill_level = 1.0
        self.dosing = False
        self.simulate = True
        self.enabled = True

    def initialize(self):
        self.calls.append(("pump", "initialize"))

    def set_fill_level(self, fill_level, flow_rate=None):
        self.fill_level = fill_level
        if flow_rate is None:
            self.calls.append(("pump", "set_fill_level", fill_level))
        else:
            self.calls.append(("pump", "set_fill_level", fill_level, flow_rate))

    def generate_flow(self, flow_rate):
        self.dosing = False
        self.calls.append(("pump", "generate_flow", flow_rate))

    def read_status(self):
        self.calls.append(("pump", "read_status"))
        return self.dosing

    def cleanup(self):
        self.calls.append(("pump", "cleanup"))


class FakeValve:
    def __init__(self, calls):
        self.calls = calls
        self.position = None
        self.simulate = True
        self.enabled = True

    def initialize(self):
        self.calls.append(("valve", "initialize"))

    def set_position(self, position):
        self.position = position
        self.calls.append(("valve", "set_position", position))

    def wait_until_ready(self, timeout_s=1.0):
        self.calls.append(("valve", "wait_until_ready", timeout_s))
        return True

    def cleanup(self):
        self.calls.append(("valve", "cleanup"))


class FakeZStage:
    def __init__(self, calls):
        self.calls = calls

    def initialize(self):
        self.calls.append(("z_stage", "initialize"))

    def cleanup(self):
        self.calls.append(("z_stage", "cleanup"))


class RecordingExperiment(Experiment2):
    def __init__(self, calls, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = calls
        self.saved_image_data = None
        self.saved_camera_settings = None

    def create_folder_and_tdms(self):
        self.calls.append(("experiment", "create_folder_and_tdms", self.experiment_folder))
        return super().create_folder_and_tdms()

    def _write_tdms(self):
        self.experiment_folder.mkdir(parents=True, exist_ok=True)

    def save_settings(self):
        self.calls.append(("experiment", "save_settings"))
        super().save_settings()

    def save_image_data(self, image_data, frame_timestamps=None):
        self.saved_image_data = image_data
        self.calls.append(("experiment", "save_image_data", tuple(image_data)))
        super().save_image_data(image_data, frame_timestamps=frame_timestamps)

    def save_camera_settings(self, settings):
        self.saved_camera_settings = settings
        self.calls.append(("experiment", "save_camera_settings", settings))
        super().save_camera_settings(settings)

    def cleanup(self):
        self.calls.append(("experiment", "cleanup"))


def make_fake_app(calls, tmp_path):
    return Application(
        ad2=FakeAD2(calls),
        camera=FakeCamera(calls),
        pump=FakePump(calls),
        valve=FakeValve(calls),
        z_motor=FakeZStage(calls),
        experiment_series=ExperimentSeries2(series_path=tmp_path),
    )


def make_recording_experiment(calls, tmp_path, *, flush_enabled=False):
    return RecordingExperiment(
        calls,
        experiment_folder=tmp_path / "repeat_001",
        flush_settings=FlushSettings(
            # Match LabviewFlushPreset's retained experiment default. Unlike
            # the former 0.0 placeholder, this is a valid positive Qmix
            # uL/min request and lets flush-enabled tests reach the fake pump.
            flush_flowrate=1000.0,
            flush_volume_ml=0.0,
            wait_after_flush_s=0.0,
        ),
        flush_enabled=flush_enabled,
        global_exposure_ms=12.5,
        trigger_global_exposure=True,
        sequence_settings={
            "frames": 3,
            "roi": {
                "horizontal_offset": 0,
                "vertical_offset": 792,
                "horizontal_size": 2304,
                "vertical_size": 740,
            },
        },
        wfg_config={"running": False, "channels": []},
        do_clock_settings={"running": False, "channels": []},
    )


def finite_wfg_config(*, sec_run=0.5, sec_wait=0.2, enabled=True, repeat_count=1):
    return {
        "running": True,
        "channels": [
            {
                "channel_index": 0,
                "carrier": {"enable": enabled},
                "trigger": {"secRun": sec_run, "secWait": sec_wait, "repeatCount": repeat_count},
            }
        ],
    }


def test_application_full_flow_dry_run_skips_flush_by_default(tmp_path):
    imported_before = {name for name in REAL_HARDWARE_MODULES if name in sys.modules}
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    app.experiment_series.enqueue_experiments([experiment])

    app.initialize()
    ok = app.run_experiment2()
    app.cleanup()

    imported_after = {name for name in REAL_HARDWARE_MODULES if name in sys.modules}
    assert imported_after == imported_before
    assert ok is True
    assert app.status == "System Not Initialized"
    assert (tmp_path / "repeat_001").exists()
    assert experiment.saved_image_data == ["fake-frame-0", "fake-frame-1", "fake-frame-2"]
    assert experiment.saved_camera_settings == {
        "buffer_size": 0,
        "sub_region": app.camera.applied_roi,
        "readout_time": 0.0,
    }

    assert calls[:5] == [
        ("ad2", "initialize"),
        ("camera", "initialize"),
        ("pump", "initialize"),
        ("valve", "initialize"),
        ("z_stage", "initialize"),
    ]
    assert ("ad2", "config_wfg", {"running": False, "channels": []}) in calls
    assert not any(call[:2] == ("ad2", "config_do_clock_special") for call in calls)
    assert ("camera", "configure_trigger_global_exposure", True) in calls
    assert ("ad2", "pc_trigger") in calls
    assert ("camera", "start_capture") in calls
    assert ("camera", "image_sequence", 3) in calls
    assert ("camera", "stop_capture") in calls
    assert not any(call[:2] == ("valve", "set_position") for call in calls)
    assert not any(call[:2] == ("pump", "set_fill_level") for call in calls)
    assert not any(call[:2] == ("pump", "generate_flow") for call in calls)
    assert not any(call[:2] == ("pump", "read_status") for call in calls)
    assert calls[-5:] == [
        ("camera", "cleanup"),
        ("pump", "cleanup"),
        ("valve", "cleanup"),
        ("z_stage", "cleanup"),
        ("ad2", "cleanup"),
    ]

    assert isinstance(app.pump, FakePump)
    assert isinstance(app.valve, FakeValve)


def test_camera_roi_is_applied_read_back_and_saved_before_capture(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    requested_roi = experiment.sequence_settings["roi"]
    stale_roi = dict(app.camera.roi)
    app.experiment_series.enqueue_experiments([experiment])

    assert app.run_experiment2() is True

    configure_call = ("camera", "configure_roi", requested_roi)
    readback_call = ("camera", "read_subregion_limits_and_value", app.camera.applied_roi)
    assert calls.index(configure_call) < calls.index(readback_call)
    assert calls.index(readback_call) < calls.index(("camera", "configure_sequence", {"frames": 3}))
    assert calls.index(readback_call) < calls.index(("camera", "start_capture"))
    assert experiment.saved_camera_settings["sub_region"] == app.camera.applied_roi
    assert experiment.saved_camera_settings["sub_region"] != requested_roi
    assert experiment.saved_camera_settings["sub_region"] != stale_roi


def test_camera_roi_failure_prevents_acquisition(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    app.experiment_series.enqueue_experiments([experiment])

    def fail_roi(_roi):
        calls.append(("camera", "configure_roi_failed"))
        raise RuntimeError("ROI apply failed")

    app.camera.configure_roi = fail_roi
    with pytest.raises(RuntimeError, match="ROI apply failed"):
        app.run_experiment2()

    assert ("camera", "start_capture") not in calls


def test_run_experiment2_applies_experiment_tab_exposure_to_real_dcam_call(tmp_path):
    # Regression test for the Session 19 finding: run_experiment2() previously called
    # camera.configure(exposure_ms=...), which only updates a Python-side bookkeeping
    # field and never writes DCAM_IDPROP.EXPOSURETIME to real hardware -- only the
    # manual Camera tab's configure_exposure_time() call does that. Simulate a manual
    # tab session having left the camera at a different exposure, then confirm
    # run_experiment2() overwrites it with the Experiment tab's own distinctive value
    # via the same real hardware-writing call the manual tab uses.
    calls = []
    app = make_fake_app(calls, tmp_path)
    app.camera.configure_exposure_time(9.999)  # simulates a prior manual-tab session
    calls.clear()

    experiment = make_recording_experiment(calls, tmp_path)
    experiment.global_exposure_ms = 33.7  # distinctive Experiment-tab value
    app.experiment_series.enqueue_experiments([experiment])

    ok = app.run_experiment2()

    assert ok is True
    assert ("camera", "configure_exposure_time", 33.7) in calls
    assert not any(call[:2] == ("camera", "configure") for call in calls)
    assert app.camera.exposure_ms == 33.7


def test_application_full_flow_waits_only_for_remaining_ad2_time(tmp_path, monkeypatch):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    experiment.wfg_config = finite_wfg_config(sec_run=1.0, sec_wait=0.5)
    app.experiment_series.enqueue_experiments([experiment])

    clock = {"now": 100.0}
    monkeypatch.setattr("thermo_acoustic.application.time.monotonic", lambda: clock["now"])

    original_image_sequence = app.camera.image_sequence

    def image_sequence_with_elapsed_capture(frame_count=0, partial_capture_folder=None):
        frames = original_image_sequence(frame_count, partial_capture_folder)
        clock["now"] += 1.2
        return frames

    app.camera.image_sequence = image_sequence_with_elapsed_capture

    def record_wait(self, seconds):
        calls.append(("app", "wait", seconds))
        return None

    monkeypatch.setattr(Application, "wait", record_wait)

    ok = app.run_experiment2()

    assert ok is True
    wait_calls = [call for call in calls if call[:2] == ("app", "wait")]
    assert len(wait_calls) == 1
    assert abs(wait_calls[0][2] - 0.3) < 1e-9
    assert calls.index(("camera", "image_sequence", 3)) < calls.index(wait_calls[0])
    assert calls.index(wait_calls[0]) < calls.index(
        ("camera", "save_sequence", ("fake-frame-0", "fake-frame-1", "fake-frame-2"), tmp_path / "repeat_001")
    )


def test_application_full_flow_rejects_continuous_ad2_before_hardware_start(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    experiment.wfg_config = finite_wfg_config(sec_run=0.0, sec_wait=0.5)
    app.experiment_series.enqueue_experiments([experiment])

    try:
        app.run_experiment2()
    except ValueError as exc:
        assert "configured for continuous output" in str(exc)
        assert "finite Run Duration" in str(exc)
    else:
        raise AssertionError("continuous AD2 output should be rejected")

    assert not any(call[:2] == ("ad2", "config_wfg") for call in calls)
    assert ("camera", "start_capture") not in calls


@pytest.mark.parametrize("repeat_count", [0, 2])
def test_application_rejects_unsupported_channel0_repeat_before_hardware(tmp_path, repeat_count):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    experiment.wfg_config = finite_wfg_config(repeat_count=repeat_count)
    app.experiment_series.enqueue_experiments([experiment])

    with pytest.raises(ValueError, match="Repeat must be exactly 1"):
        app.run_experiment2()

    assert not any(call[:2] == ("ad2", "config_wfg") for call in calls)
    assert ("camera", "start_capture") not in calls


def test_application_rejects_fm_scan_conflict_before_hardware(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    experiment.wfg_config = finite_wfg_config()
    experiment.fm_sweep = object()
    experiment.frequency_scan_selected_hz = 1_934_000.0
    app.experiment_series.enqueue_experiments([experiment])

    with pytest.raises(ValueError, match="FM Sweep and Frequency Scan"):
        app.run_experiment2()

    assert not any(call[:2] == ("ad2", "config_wfg") for call in calls)
    assert ("camera", "start_capture") not in calls


def test_application_rejects_fm_sweep_without_enabled_channel0_before_hardware(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    experiment.wfg_config = finite_wfg_config(enabled=False)
    experiment.fm_sweep = object()
    app.experiment_series.enqueue_experiments([experiment])

    with pytest.raises(ValueError, match="explicitly enabled"):
        app.run_experiment2()

    assert not any(call[:2] == ("ad2", "config_wfg") for call in calls)
    assert ("camera", "start_capture") not in calls


def test_application_rejects_laser_w2_output_before_hardware(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    config = finite_wfg_config()
    config["channels"].append(
        {
            "channel_index": 1,
            "carrier": {"enable": True, "frequency_hz": 1000.0, "amplitude_v": 1.0},
            "fm_mod": {"enable": False},
            "trigger": {"secRun": 0.5, "secWait": 0.0, "repeatCount": 1},
        }
    )
    experiment.wfg_config = config
    app.experiment_series.enqueue_experiments([experiment])

    with pytest.raises(ValueError, match="W2 is connected to the laser Analog In"):
        app.run_experiment2()

    assert not any(call[:2] == ("ad2", "config_wfg") for call in calls)
    assert ("camera", "start_capture") not in calls


def finite_do_clock_config(*, camera_fps=10.0, enabled=True):
    return {
        "running": True,
        "channels": [
            {
                "channel_index": 1,
                "enable": enabled,
                "clock_frequency_hz": camera_fps,
                "trigger": {"secRun": 0.5, "secWait": 0.0},
            }
        ],
    }


def test_camera_timing_budget_rejects_legacy_do_fps_exceeding_readout_budget(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    app.camera.read_readout_time = lambda: 0.05  # 50 ms readout for the configured ROI
    experiment = make_recording_experiment(calls, tmp_path)
    experiment.global_exposure_ms = 20.0  # 20 ms exposure -> 70 ms frame period -> ~14.3 fps max
    experiment.do_clock_settings = finite_do_clock_config(camera_fps=100.0)
    app.camera.configure_exposure_time(experiment.global_exposure_ms)
    with pytest.raises(ValueError) as exc_info:
        app._check_camera_timing_budget(experiment)

    assert "exceeds what the current exposure" in str(exc_info.value)
    assert "Reduce Camera FPS" in str(exc_info.value)
    assert ("camera", "start_capture") not in calls


def test_camera_timing_budget_allows_legacy_do_fps_within_readout_budget(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    app.camera.read_readout_time = lambda: 0.005  # 5 ms readout for the configured ROI
    experiment = make_recording_experiment(calls, tmp_path)
    experiment.global_exposure_ms = 5.0  # 5 ms exposure -> 10 ms frame period -> 100 fps max
    experiment.do_clock_settings = finite_do_clock_config(camera_fps=50.0)
    app.camera.configure_exposure_time(experiment.global_exposure_ms)
    app._check_camera_timing_budget(experiment)

    assert ("camera", "start_capture") not in calls


def test_run_experiment2_ignores_legacy_enabled_do_clock_for_fps_budget(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    app.camera.read_readout_time = lambda: 0.05
    experiment = make_recording_experiment(calls, tmp_path)
    experiment.global_exposure_ms = 20.0
    experiment.do_clock_settings = finite_do_clock_config(camera_fps=1000.0, enabled=True)
    app.experiment_series.enqueue_experiments([experiment])

    ok = app.run_experiment2()

    assert ok is True
    assert ("camera", "start_capture") in calls
    assert not any(call[:2] == ("ad2", "config_do_clock_special") for call in calls)


def test_initialize_lets_every_device_attempt_independently_when_one_fails(tmp_path):
    # Architecture fix (2026-08-13): devices are confirmed functionally
    # independent (no device's initialize() reads another's state), so one
    # device failing must not stop the others from getting their own
    # attempt, and devices that succeed must not be torn back down just
    # because a later, unrelated device failed. Replaces the old
    # "stop at the first failure and roll back everything already-
    # succeeded" behavior this same test used to assert -- see
    # docs/hardware_repair_plan.md's "Initialization And Failure Recovery".
    calls = []

    class FailingValve(FakeValve):
        def initialize(self):
            super().initialize()
            raise RuntimeError("valve init failed")

    app = Application(
        ad2=FakeAD2(calls),
        camera=FakeCamera(calls),
        pump=FakePump(calls),
        valve=FailingValve(calls),
        z_motor=FakeZStage(calls),
        experiment_series=ExperimentSeries2(series_path=tmp_path),
    )

    try:
        app.initialize()
    except RuntimeError as exc:
        assert "Valve initialize failed" in str(exc)
    else:
        raise AssertionError("partial initialization failure should be reported")

    # Every device gets its own attempt, in the existing reporting order --
    # Z-stage (after Valve in that order) is NOT skipped just because Valve
    # failed.
    assert calls == [
        ("ad2", "initialize"),
        ("camera", "initialize"),
        ("pump", "initialize"),
        ("valve", "initialize"),
        ("z_stage", "initialize"),
    ]
    # No cleanup() call anywhere: AD2/Camera/Pump succeeded and must stay
    # connected/usable, not be rolled back because Valve (a later, unrelated
    # device) failed.
    assert not any(call[1] == "cleanup" for call in calls)


def test_initialize_pump_failure_does_not_block_ad2_camera_valve_z_stage(tmp_path):
    # Directly covers the user-reported scenario: a pump fault must not
    # prevent AD2/Camera/Valve/Z-stage from each getting their own real
    # initialize() attempt, and must not roll back the ones that already
    # succeeded before Pump's turn in the reporting order.
    calls = []

    class FailingPump(FakePump):
        def initialize(self):
            self.calls.append(("pump", "initialize"))
            raise RuntimeError("pump is in a fault state")

    app = Application(
        ad2=FakeAD2(calls),
        camera=FakeCamera(calls),
        pump=FailingPump(calls),
        valve=FakeValve(calls),
        z_motor=FakeZStage(calls),
        experiment_series=ExperimentSeries2(series_path=tmp_path),
    )

    with pytest.raises(RuntimeError, match="Pump initialize failed"):
        app.initialize()

    assert calls == [
        ("ad2", "initialize"),
        ("camera", "initialize"),
        ("pump", "initialize"),
        ("valve", "initialize"),
        ("z_stage", "initialize"),
    ]
    assert not any(call[1] == "cleanup" for call in calls)


def test_initialize_reports_every_independent_failure_not_just_the_first(tmp_path):
    calls = []

    class FailingPump(FakePump):
        def initialize(self):
            self.calls.append(("pump", "initialize"))
            raise RuntimeError("pump is in a fault state")

    class FailingValve(FakeValve):
        def initialize(self):
            self.calls.append(("valve", "initialize"))
            raise RuntimeError("valve did not respond")

    app = Application(
        ad2=FakeAD2(calls),
        camera=FakeCamera(calls),
        pump=FailingPump(calls),
        valve=FailingValve(calls),
        z_motor=FakeZStage(calls),
        experiment_series=ExperimentSeries2(series_path=tmp_path),
    )

    with pytest.raises(RuntimeError) as excinfo:
        app.initialize()

    # Both independent failures are named, not just the first one hit --
    # a caller inspecting the exception can tell which devices need
    # attention without re-running initialize() device by device.
    assert "Pump initialize failed" in str(excinfo.value)
    assert "Valve initialize failed" in str(excinfo.value)
    # AD2/Camera still got attempted and are not rolled back; Z-stage
    # (last in the order) still got its own attempt too.
    assert calls == [
        ("ad2", "initialize"),
        ("camera", "initialize"),
        ("pump", "initialize"),
        ("valve", "initialize"),
        ("z_stage", "initialize"),
    ]
    assert not any(call[1] == "cleanup" for call in calls)


def test_initialize_reports_per_device_progress_independently_on_partial_failure(tmp_path):
    calls = []
    events = []

    class FailingPump(FakePump):
        def initialize(self):
            self.calls.append(("pump", "initialize"))
            raise RuntimeError("pump is in a fault state")

    app = Application(
        ad2=FakeAD2(calls),
        camera=FakeCamera(calls),
        pump=FailingPump(calls),
        valve=FakeValve(calls),
        z_motor=FakeZStage(calls),
        experiment_series=ExperimentSeries2(series_path=tmp_path),
    )

    with pytest.raises(RuntimeError):
        app.initialize(progress=lambda kind, value: events.append((kind, value)))

    final_status = {}
    for kind, value in events:
        if kind == "init_device":
            name, status = value
            final_status[name] = status

    # Each device's own genuine outcome is reported -- no "Rolled back"
    # placeholder text for devices that actually succeeded.
    assert final_status["AD2"] == "Complete"
    assert final_status["Camera"] == "Complete"
    assert final_status["Pump"] == "Failed"
    assert final_status["Valve"] == "Complete"
    assert final_status["Z-stage"] == "Complete"
    for status in final_status.values():
        assert "Rolled back" not in status


def test_run_experiment2_stops_capture_when_image_sequence_raises(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    app.experiment_series.enqueue_experiments([experiment])

    def failing_image_sequence(frame_count=0, partial_capture_folder=None):
        calls.append(("camera", "image_sequence", frame_count))
        raise RuntimeError("camera read failed")

    app.camera.image_sequence = failing_image_sequence

    try:
        app.run_experiment2()
    except RuntimeError as exc:
        assert "camera read failed" in str(exc)
    else:
        raise AssertionError("camera read failure should propagate")

    assert ("camera", "start_capture") in calls
    assert ("camera", "image_sequence", 3) in calls
    assert ("camera", "stop_capture") in calls
    assert calls.index(("camera", "image_sequence", 3)) < calls.index(("camera", "stop_capture"))
    assert not any(call[:2] == ("camera", "save_sequence") for call in calls)


def test_run_experiment2_attempts_capture_cleanup_when_start_capture_raises(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    app.experiment_series.enqueue_experiments([experiment])

    def failing_start_capture():
        calls.append(("camera", "start_capture"))
        raise RuntimeError("camera start failed")

    app.camera.start_capture = failing_start_capture

    with pytest.raises(RuntimeError, match="camera start failed"):
        app.run_experiment2()

    assert calls.count(("camera", "start_capture")) == 1
    assert calls.count(("camera", "stop_capture")) == 1
    assert calls.index(("camera", "start_capture")) < calls.index(("camera", "stop_capture"))
    assert not any(call[:2] == ("ad2", "pc_trigger") for call in calls)


def test_application_full_flow_dry_run_can_opt_into_fake_flush(tmp_path):
    imported_before = {name for name in REAL_HARDWARE_MODULES if name in sys.modules}
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path, flush_enabled=True)
    app.experiment_series.enqueue_experiments([experiment])

    ok = app.run_experiment2()

    imported_after = {name for name in REAL_HARDWARE_MODULES if name in sys.modules}
    assert imported_after == imported_before
    assert ok is True
    assert experiment.saved_image_data == ["fake-frame-0", "fake-frame-1", "fake-frame-2"]
    assert ("camera", "start_capture") in calls
    assert ("camera", "image_sequence", 3) in calls
    assert ("camera", "stop_capture") in calls
    assert ("camera", "save_sequence", ("fake-frame-0", "fake-frame-1", "fake-frame-2"), tmp_path / "repeat_001") in calls
    assert ("valve", "set_position", 1) in calls
    assert ("pump", "set_fill_level", 1.0, 1000.0) in calls
    assert sum(call[:2] == ("pump", "set_fill_level") for call in calls) == 1
    assert ("pump", "generate_flow", 0.0) not in calls
    assert ("pump", "read_status") in calls
    assert ("valve", "set_position", 2) in calls
    assert isinstance(app.pump, FakePump)
    assert isinstance(app.valve, FakeValve)


def test_run_experiment2_reports_flush_failure_instead_of_completing(tmp_path, monkeypatch, caplog):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path, flush_enabled=True)
    app.experiment_series.enqueue_experiments([experiment])

    monkeypatch.setattr(Application, "flush", lambda self, settings, progress=None: False)

    with caplog.at_level("ERROR", logger="thermo_acoustic.application"):
        ok = app.run_experiment2()

    assert ok is False
    assert app.status == "ExperimentFlushFailed"
    assert any("Flush failed for experiment repeat" in str(error) for error in app.errors)
    assert any("Flush failed for experiment repeat" in record.message for record in caplog.records)
    assert not any(call[:2] == ("camera", "save_sequence") for call in calls)
    assert ("experiment", "cleanup") in calls


# -- Phase 1 of the v2 sequence-visualization feature: run_experiment2()/
# flush()/run_temperature_series() now accept an optional `progress`
# callable and fire step_started/step_completed/step_failed around named
# steps (see application.py's STEP_* constants and _report_step()). These
# tests confirm the exact event sequence for each real branch and that a
# failure at one step is attributed to that step specifically, with no
# step_started for anything after it.


def record_progress():
    calls: list[tuple[str, object]] = []

    def progress(kind: str, value: object) -> None:
        calls.append((kind, value))

    return progress, calls


def step_names(calls: list[tuple[str, object]], kind: str) -> list[str]:
    return [value for k, value in calls if k == kind]


def test_run_experiment2_step_sequence_without_flush_or_ad2_wait(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)  # flush_enabled=False by default
    app.experiment_series.enqueue_experiments([experiment])
    progress, progress_calls = record_progress()

    ok = app.run_experiment2(progress=progress)

    assert ok is True
    started = step_names(progress_calls, "step_started")
    completed = step_names(progress_calls, "step_completed")
    assert started == [
        "InitializeExperiment",
        "ConfigureWfg",
        "ConfigureCamera",
        "CaptureFrames",
        "SaveResults",
    ]
    # Every started step also completed, in the same order -- no step left
    # started-but-unresolved on the happy path.
    assert completed == started
    assert step_names(progress_calls, "step_failed") == []
    # Conditional steps genuinely did not fire at all (not just "completed
    # instantly") -- default config has no AD2 wait and flush_enabled=False.
    assert "WaitForAd2Completion" not in started
    assert "Flush" not in started


def test_run_experiment2_step_sequence_with_flush_enabled(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path, flush_enabled=True)
    app.experiment_series.enqueue_experiments([experiment])
    progress, progress_calls = record_progress()

    ok = app.run_experiment2(progress=progress)

    assert ok is True
    started = step_names(progress_calls, "step_started")
    assert started == [
        "InitializeExperiment",
        "ConfigureWfg",
        "ConfigureCamera",
        "CaptureFrames",
        "Flush",
        "SaveResults",
    ]
    assert step_names(progress_calls, "step_completed") == started
    assert step_names(progress_calls, "step_failed") == []


def test_run_experiment2_step_sequence_with_ad2_completion_wait(tmp_path, monkeypatch):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    experiment.wfg_config = finite_wfg_config(sec_run=1.0, sec_wait=0.5)
    app.experiment_series.enqueue_experiments([experiment])
    progress, progress_calls = record_progress()

    # Same deterministic-clock technique as
    # test_application_full_flow_waits_only_for_remaining_ad2_time -- no
    # real sleeping, so this stays fast.
    clock = {"now": 100.0}
    monkeypatch.setattr("thermo_acoustic.application.time.monotonic", lambda: clock["now"])
    original_image_sequence = app.camera.image_sequence

    def image_sequence_with_elapsed_capture(frame_count=0, partial_capture_folder=None):
        frames = original_image_sequence(frame_count, partial_capture_folder)
        clock["now"] += 1.2
        return frames

    app.camera.image_sequence = image_sequence_with_elapsed_capture
    monkeypatch.setattr(Application, "wait", lambda self, seconds: None)

    ok = app.run_experiment2(progress=progress)

    assert ok is True
    started = step_names(progress_calls, "step_started")
    assert started == [
        "InitializeExperiment",
        "ConfigureWfg",
        "ConfigureCamera",
        "CaptureFrames",
        "WaitForAd2Completion",
        "SaveResults",
    ]
    assert step_names(progress_calls, "step_completed") == started
    assert step_names(progress_calls, "step_failed") == []


def test_run_experiment2_step_failure_in_initialize_experiment(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)

    def raise_boom():
        raise RuntimeError("boom: create_folder_and_tdms")

    experiment.create_folder_and_tdms = raise_boom
    app.experiment_series.enqueue_experiments([experiment])
    progress, progress_calls = record_progress()

    with pytest.raises(RuntimeError, match="boom: create_folder_and_tdms"):
        app.run_experiment2(progress=progress)

    assert step_names(progress_calls, "step_started") == ["InitializeExperiment"]
    assert step_names(progress_calls, "step_completed") == []
    assert progress_calls[-1] == ("step_failed", ("InitializeExperiment", "boom: create_folder_and_tdms"))


def test_run_experiment2_step_failure_in_configure_wfg(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)

    def raise_boom(config):
        raise RuntimeError("boom: config_wfg")

    app.ad2.config_wfg = raise_boom
    experiment = make_recording_experiment(calls, tmp_path)
    app.experiment_series.enqueue_experiments([experiment])
    progress, progress_calls = record_progress()

    with pytest.raises(RuntimeError, match="boom: config_wfg"):
        app.run_experiment2(progress=progress)

    assert step_names(progress_calls, "step_started") == ["InitializeExperiment", "ConfigureWfg"]
    assert step_names(progress_calls, "step_completed") == ["InitializeExperiment"]
    assert progress_calls[-1] == ("step_failed", ("ConfigureWfg", "boom: config_wfg"))


def test_run_experiment2_step_failure_in_configure_camera(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)

    def raise_boom(exposure_ms):
        raise RuntimeError("boom: configure_exposure_time")

    app.camera.configure_exposure_time = raise_boom
    experiment = make_recording_experiment(calls, tmp_path)
    app.experiment_series.enqueue_experiments([experiment])
    progress, progress_calls = record_progress()

    with pytest.raises(RuntimeError, match="boom: configure_exposure_time"):
        app.run_experiment2(progress=progress)

    assert step_names(progress_calls, "step_started") == ["InitializeExperiment", "ConfigureWfg", "ConfigureCamera"]
    assert step_names(progress_calls, "step_completed") == ["InitializeExperiment", "ConfigureWfg"]
    assert progress_calls[-1] == ("step_failed", ("ConfigureCamera", "boom: configure_exposure_time"))


def test_run_experiment2_step_failure_in_capture_frames(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)

    def raise_boom(frame_count=0, partial_capture_folder=None):
        raise RuntimeError("boom: image_sequence")

    app.camera.image_sequence = raise_boom
    experiment = make_recording_experiment(calls, tmp_path)
    app.experiment_series.enqueue_experiments([experiment])
    progress, progress_calls = record_progress()

    with pytest.raises(RuntimeError, match="boom: image_sequence"):
        app.run_experiment2(progress=progress)

    assert step_names(progress_calls, "step_started") == [
        "InitializeExperiment",
        "ConfigureWfg",
        "ConfigureCamera",
        "CaptureFrames",
    ]
    assert step_names(progress_calls, "step_completed") == ["InitializeExperiment", "ConfigureWfg", "ConfigureCamera"]
    assert progress_calls[-1] == ("step_failed", ("CaptureFrames", "boom: image_sequence"))
    # stop_capture() still runs in image_sequence()'s enclosing finally,
    # even though the step itself failed -- existing cleanup behavior is
    # unchanged by the new step wrapping.
    assert ("camera", "stop_capture") in calls


def test_run_experiment2_step_failure_in_wait_for_ad2_completion(tmp_path, monkeypatch):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    experiment.wfg_config = finite_wfg_config(sec_run=1.0, sec_wait=0.5)
    app.experiment_series.enqueue_experiments([experiment])
    progress, progress_calls = record_progress()

    def raise_boom(self, seconds):
        raise RuntimeError("boom: wait")

    monkeypatch.setattr(Application, "wait", raise_boom)

    with pytest.raises(RuntimeError, match="boom: wait"):
        app.run_experiment2(progress=progress)

    assert step_names(progress_calls, "step_started") == [
        "InitializeExperiment",
        "ConfigureWfg",
        "ConfigureCamera",
        "CaptureFrames",
        "WaitForAd2Completion",
    ]
    assert step_names(progress_calls, "step_completed") == [
        "InitializeExperiment",
        "ConfigureWfg",
        "ConfigureCamera",
        "CaptureFrames",
    ]
    assert progress_calls[-1] == ("step_failed", ("WaitForAd2Completion", "boom: wait"))


def test_run_experiment2_step_failure_in_flush(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path, flush_enabled=True)
    app.experiment_series.enqueue_experiments([experiment])
    progress, progress_calls = record_progress()

    def raise_boom(position):
        raise RuntimeError("boom: valve.set_position")

    app.valve.set_position = raise_boom

    with pytest.raises(RuntimeError, match="boom: valve.set_position"):
        app.run_experiment2(progress=progress)

    assert step_names(progress_calls, "step_started") == [
        "InitializeExperiment",
        "ConfigureWfg",
        "ConfigureCamera",
        "CaptureFrames",
        "Flush",
    ]
    assert step_names(progress_calls, "step_completed") == [
        "InitializeExperiment",
        "ConfigureWfg",
        "ConfigureCamera",
        "CaptureFrames",
    ]
    assert progress_calls[-1] == ("step_failed", ("Flush", "boom: valve.set_position"))


def test_run_experiment2_step_failure_in_save_results(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)

    def raise_boom(image_data, folder):
        raise RuntimeError("boom: save_sequence")

    app.camera.save_sequence = raise_boom
    experiment = make_recording_experiment(calls, tmp_path)
    app.experiment_series.enqueue_experiments([experiment])
    progress, progress_calls = record_progress()

    with pytest.raises(RuntimeError, match="boom: save_sequence"):
        app.run_experiment2(progress=progress)

    assert step_names(progress_calls, "step_started") == [
        "InitializeExperiment",
        "ConfigureWfg",
        "ConfigureCamera",
        "CaptureFrames",
        "SaveResults",
    ]
    assert step_names(progress_calls, "step_completed") == [
        "InitializeExperiment",
        "ConfigureWfg",
        "ConfigureCamera",
        "CaptureFrames",
    ]
    assert progress_calls[-1] == ("step_failed", ("SaveResults", "boom: save_sequence"))


def test_run_experiment2_step_completed_fires_even_when_flush_returns_false(tmp_path, monkeypatch):
    # flush() returning False (e.g. a pump-wait timeout) is not an
    # exception -- per _report_step()'s own documented design, that's
    # still a step_completed, not a step_failed. This is the deliberate
    # behavior confirmed for Phase 1 (see application.py's _report_step
    # docstring); the caller distinguishes "step ran but the overall
    # experiment still stopped" via the existing ExperimentFlushFailed
    # status event, not a second failure channel.
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path, flush_enabled=True)
    app.experiment_series.enqueue_experiments([experiment])
    progress, progress_calls = record_progress()

    monkeypatch.setattr(Application, "flush", lambda self, settings, progress=None: False)

    ok = app.run_experiment2(progress=progress)

    assert ok is False
    assert app.status == "ExperimentFlushFailed"
    assert step_names(progress_calls, "step_failed") == []
