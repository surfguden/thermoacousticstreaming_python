from __future__ import annotations

from thermo_acoustic.camera import SubRegion
from thermo_acoustic.experiment_planning import (
    CAMERA_FIELD_OWNERSHIP,
    CameraFieldOwnership,
    ExperimentCameraDefaults,
)


def test_experiment_camera_defaults_keep_defaults_separate_from_run_overrides():
    roi = SubRegion(horizontal_offset=10, vertical_offset=20, horizontal_size=100, vertical_size=80)
    defaults = ExperimentCameraDefaults(
        masterpulse_mode="Continuous",
        masterpulse_source="Internal",
        masterpulse_interval_s=0.05,
        masterpulse_burst_times=7,
        trigger_source="External",
        trigger_polarity="Negative",
        trigger_delay_s=0.002,
        roi=roi,
    )

    settings = defaults.sequence_settings(frames=42, trigger_source_override="Internal")

    assert settings == {
        "masterpulse_mode": "Continuous",
        "masterpulse_source": "Internal",
        "masterpulse_interval_s": 0.05,
        "masterpulse_burst_times": 7,
        "frames": 42,
        "trigger_source": "Internal",
        "trigger_polarity": "Negative",
        "trigger_delay_s": 0.002,
    }
    assert defaults.trigger_source == "External"
    assert defaults.roi is roi
    assert "roi" not in settings


def test_camera_field_ownership_classifies_defaults_overrides_applied_and_manual_state():
    assert CAMERA_FIELD_OWNERSHIP["masterpulse_mode"] is CameraFieldOwnership.EXPERIMENT_DEFAULT
    assert CAMERA_FIELD_OWNERSHIP["frames"] is CameraFieldOwnership.EXPERIMENT_OVERRIDE
    assert CAMERA_FIELD_OWNERSHIP["automated_trigger_source"] is CameraFieldOwnership.EXPERIMENT_OVERRIDE
    assert CAMERA_FIELD_OWNERSHIP["roi"] is CameraFieldOwnership.MANUAL_ONLY
    assert CAMERA_FIELD_OWNERSHIP["experiment_exposure_ms"] is CameraFieldOwnership.EXPERIMENT_OVERRIDE
    assert CAMERA_FIELD_OWNERSHIP["applied_exposure_ms"] is CameraFieldOwnership.APPLIED_DEVICE_STATE
    assert CAMERA_FIELD_OWNERSHIP["timing_feasibility_summary"] is CameraFieldOwnership.DISPLAY_ONLY
