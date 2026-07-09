from __future__ import annotations

import importlib
import sys

from thermo_acoustic.experiment_presets import (
    LABVIEW_SCREENSHOT_PRESET_NAME,
    labview_screenshot_working_preset,
)


HARDWARE_SDK_MODULE_NAMES = ("pylablib", "qmixsdk", "serial", "dcam", "dwf")


def test_labview_screenshot_working_preset_values():
    preset = labview_screenshot_working_preset()

    assert preset.name == LABVIEW_SCREENSHOT_PRESET_NAME
    assert preset.camera.roi_dict() == {
        "horizontal_offset": 0,
        "vertical_offset": 792,
        "horizontal_size": 2304,
        "vertical_size": 740,
    }
    assert preset.camera.exposure_ms == 40.0
    assert preset.camera.camera_fps == 20.0
    assert preset.camera.experiment_frames == 1000
    assert preset.camera.dcam_trigger_source_camera_only == "internal"
    assert preset.camera.capture_mode == "Snap"
    assert preset.camera.sequence_mode == "Continuous"
    assert preset.camera.sequence_source == "External"
    assert preset.camera.external_polarity == "Negative"

    assert preset.experiment.repeats == 1
    assert preset.experiment.frames == 1000
    assert preset.experiment.exposure_ms == 40.0
    assert preset.experiment.ch1_frequency_hz == 1.975e6
    assert preset.experiment.ch1_amplitude_v == 2.0
    assert preset.experiment.ch1_run_s == 60.0
    assert preset.experiment.ch2_run_s == 60.0
    assert preset.experiment.dynamic_frequency is False
    assert preset.experiment.dynamic_camera_start_time is False
    assert preset.experiment.global_exposure is False
    assert preset.experiment.average_fps_observed == 20.099

    assert preset.ad2.ch1.index == 0
    assert preset.ad2.ch1.frequency_hz == 1.975e6
    assert preset.ad2.ch1.amplitude_v == 2.0
    assert preset.ad2.ch2.index == 1
    assert preset.ad2.ch2.frequency_hz == 1000.0
    assert preset.ad2.ch2.amplitude_v == 1.0
    assert preset.ad2.trigger_source == "trigsrcNone"
    assert preset.ad2.wfg_sec_run_s == 0.0
    assert preset.ad2.wfg_sec_wait_s == 0.0
    assert preset.ad2.wfg_repeat_count == 0

    assert preset.flush.syringe == "BD 5 ml"
    assert preset.flush.manual_flow_rate == -5000.0
    assert preset.flush.experiment_flush_flowrate_ul == 1000.0
    assert preset.flush.experiment_flush_volume_ml == 0.01
    assert preset.flush.experiment_wait_after_flush_s == 2.0
    assert preset.flush.pump_tab_wait_after_flush_s == 5.0
    assert preset.flush.number_of_flushes == 2


def test_initialization_candidate_values_do_not_replace_validated_defaults():
    preset = labview_screenshot_working_preset()

    assert preset.initialization.analog_discovery_on is True
    assert preset.initialization.hamamatsu_on is True
    assert preset.initialization.cetoni_pump_on is True
    assert preset.initialization.mx_valve_on is True
    assert preset.initialization.z_stage_on is False
    assert preset.initialization.simulate_camera is False
    assert preset.initialization.simulate_pump is False
    assert preset.initialization.simulate_valve is False
    assert preset.initialization.prior_resource_candidate == "COM7"
    assert preset.initialization.valve_resource_candidate == "COM5"
    assert str(preset.initialization.qmix_config_path_candidate) == r"C:\Users\Lab user\Desktop\Franzi\Cetoni_1pump_config_FM"
    assert "candidates only" in preset.initialization.candidate_note


def test_preset_module_does_not_import_hardware_sdks():
    before = {name for name in HARDWARE_SDK_MODULE_NAMES if name in sys.modules}

    module = importlib.import_module("thermo_acoustic.experiment_presets")
    importlib.reload(module)

    after = {name for name in HARDWARE_SDK_MODULE_NAMES if name in sys.modules}
    assert after == before
