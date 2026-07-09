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

    def start_capture(self):
        self.capturing = True
        self.calls.append(("camera", "start_capture"))

    def image_sequence(self, frame_count=0):
        self.calls.append(("camera", "image_sequence", frame_count))
        return [f"fake-frame-{index}" for index in range(frame_count)]

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

    def set_fill_level(self, fill_level):
        self.fill_level = fill_level
        self.calls.append(("pump", "set_fill_level", fill_level))

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

    def save_settings(self):
        self.calls.append(("experiment", "save_settings"))
        super().save_settings()

    def save_image_data(self, image_data):
        self.saved_image_data = image_data
        self.calls.append(("experiment", "save_image_data", tuple(image_data)))
        super().save_image_data(image_data)

    def save_camera_settings(self, settings):
        self.saved_camera_settings = settings
        self.calls.append(("experiment", "save_camera_settings", settings))
        super().save_camera_settings(settings)

    def cleanup(self):
        self.calls.append(("experiment", "cleanup"))


def test_application_full_flow_dry_run_uses_fake_hardware_only(tmp_path):
    imported_before = {name for name in REAL_HARDWARE_MODULES if name in sys.modules}
    calls = []
    app = Application(
        ad2=FakeAD2(calls),
        camera=FakeCamera(calls),
        pump=FakePump(calls),
        valve=FakeValve(calls),
        z_motor=FakeZStage(calls),
        experiment_series=ExperimentSeries2(series_path=tmp_path),
    )
    experiment = RecordingExperiment(
        calls,
        experiment_folder=tmp_path / "repeat_001",
        flush_settings=FlushSettings(
            flush_flowrate=0.0,
            flush_volume_ml=0.0,
            wait_after_flush_s=0.0,
        ),
        global_exposure_ms=12.5,
        sequence_settings={"frames": 3},
        wfg_config={"running": False, "channels": []},
        do_clock_settings={"running": False, "channels": []},
    )
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
    assert ("ad2", "pc_trigger") in calls
    assert ("camera", "start_capture") in calls
    assert ("camera", "image_sequence", 3) in calls
    assert ("camera", "stop_capture") in calls
    assert ("valve", "set_position", 1) in calls
    assert ("pump", "set_fill_level", 1.0) in calls
    assert ("pump", "generate_flow", 0.0) in calls
    assert ("pump", "read_status") in calls
    assert ("valve", "set_position", 2) in calls
    assert calls[-5:] == [
        ("camera", "cleanup"),
        ("pump", "cleanup"),
        ("valve", "cleanup"),
        ("z_stage", "cleanup"),
        ("ad2", "cleanup"),
    ]

    assert isinstance(app.pump, FakePump)
    assert isinstance(app.valve, FakeValve)
