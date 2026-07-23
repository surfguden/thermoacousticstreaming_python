from __future__ import annotations

import sys

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

    def initialize(self):
        self.calls.append(("ad2", "initialize"))

    def config_wfg(self, config):
        self.calls.append(("ad2", "config_wfg", config))

    def config_do_clock_special(self, settings):
        self.calls.append(("ad2", "config_do_clock_special", settings))

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

    def initialize(self):
        self.calls.append(("camera", "initialize"))

    def configure(self, exposure_ms=None):
        self.exposure_ms = exposure_ms
        self.calls.append(("camera", "configure", exposure_ms))

    def configure_sequence(self, settings):
        self.sequence_config = settings
        self.calls.append(("camera", "configure_sequence", settings))

    def configure_trigger_global_exposure(self, enabled):
        self.calls.append(("camera", "configure_trigger_global_exposure", enabled))

    def start_capture(self):
        self.capturing = True
        self.calls.append(("camera", "start_capture"))

    def image_sequence(self, frame_count=0):
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
        return {}

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

    def initialize(self):
        self.calls.append(("valve", "initialize"))

    def set_position(self, position):
        self.position = position
        self.calls.append(("valve", "set_position", position))

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
            flush_flowrate=0.0,
            flush_volume_ml=0.0,
            wait_after_flush_s=0.0,
        ),
        flush_enabled=flush_enabled,
        global_exposure_ms=12.5,
        trigger_global_exposure=True,
        sequence_settings={"frames": 3},
        wfg_config={"running": False, "channels": []},
        do_clock_settings={"running": False, "channels": []},
    )


def finite_wfg_config(*, sec_run=0.5, sec_wait=0.2, enabled=True):
    return {
        "running": True,
        "channels": [
            {
                "channel_index": 0,
                "carrier": {"enable": enabled},
                "trigger": {"secRun": sec_run, "secWait": sec_wait},
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
        "sub_region": {},
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
    assert ("ad2", "config_do_clock_special", {"running": False, "channels": []}) in calls
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


def test_application_full_flow_waits_only_for_remaining_ad2_time(tmp_path, monkeypatch):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    experiment.wfg_config = finite_wfg_config(sec_run=1.0, sec_wait=0.5)
    app.experiment_series.enqueue_experiments([experiment])

    clock = {"now": 100.0}
    monkeypatch.setattr("thermo_acoustic.application.time.monotonic", lambda: clock["now"])

    original_image_sequence = app.camera.image_sequence

    def image_sequence_with_elapsed_capture(frame_count=0):
        frames = original_image_sequence(frame_count)
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


def test_initialize_rolls_back_already_initialized_devices_when_later_device_fails(tmp_path):
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
        assert "valve initialize failed" in str(exc)
    else:
        raise AssertionError("partial initialization failure should be reported")

    assert calls[:4] == [
        ("ad2", "initialize"),
        ("camera", "initialize"),
        ("pump", "initialize"),
        ("valve", "initialize"),
    ]
    assert ("z_stage", "initialize") not in calls
    assert calls[-3:] == [
        ("ad2", "cleanup"),
        ("camera", "cleanup"),
        ("pump", "cleanup"),
    ]


def test_run_experiment2_stops_capture_when_image_sequence_raises(tmp_path):
    calls = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    app.experiment_series.enqueue_experiments([experiment])

    def failing_image_sequence(frame_count=0):
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
    assert ("pump", "set_fill_level", 1.0, 0.0) in calls
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

    monkeypatch.setattr(Application, "flush", lambda self, settings: False)

    with caplog.at_level("ERROR", logger="thermo_acoustic.application"):
        ok = app.run_experiment2()

    assert ok is False
    assert app.status == "ExperimentFlushFailed"
    assert any("Flush failed for experiment repeat" in str(error) for error in app.errors)
    assert any("Flush failed for experiment repeat" in record.message for record in caplog.records)
    assert not any(call[:2] == ("camera", "save_sequence") for call in calls)
    assert ("experiment", "cleanup") in calls
