from __future__ import annotations

from pathlib import Path

import pytest

import thermo_acoustic.experiment_planning as planning
from thermo_acoustic import qt_ui, qt_ui_v2, qt_ui_v3
from thermo_acoustic.ad2 import WaveformFunction
from thermo_acoustic.experiment_planning import (
    ExperimentRequest,
    FrozenMapping,
    build_independent_run_plan,
    legacy_series_from_run_plan,
    normalize_experiment,
    temperature_series_from_request,
)


def _wfg(function: str = "Sine") -> dict:
    return {
        "running": True,
        "synchronize_state": "Independent",
        "channels": [
            {"channel_index": 0, "carrier": {"frequency_hz": 100_000.0,
             "amplitude_v": 2.0, "offset_v": 0.1, "symmetry_percent": 40.0,
             "phase_deg": 10.0, "function": function, "enable": True},
             "trigger": {"sec_run": 1.0, "sec_wait": 0.2},
             "fm_mod": {"enable": False}},
            {"channel_index": 1, "carrier": {"frequency_hz": 2_000.0,
             "function": "Square", "enable": False}, "trigger": {}, "fm_mod": {"enable": False}},
        ],
    }


def _request(**changes) -> ExperimentRequest:
    values = dict(
        output_path=Path("offline-series"), repeats_per_group=2,
        frequency_scan_enabled=False, frequency_values_hz=(90_000.0, 110_000.0),
        channel0_waveform_function="Sine", camera_fps=20.0, frames=10,
        camera_start_s=(0.1, 0.2), dynamic_camera_start=False,
        fm_sweep_enabled=False, channel0_output_selected=True, flush_enabled=False,
        tec_scan_enabled=False, temperature_targets_c=(),
        device_modes=(("ad2", True, True), ("camera", True, True), ("pump", True, True),
                      ("valve", True, True), ("tec", False, True)),
        fixed_camera_start_s=0.3, wfg_templates=(_wfg(),),
        sequence_settings=(("frames", 10), ("trigger_source", "Internal")),
        flush_settings=(1.0, 0.2, 0.5, 5.0), exposure_ms=3.5,
        trigger_global_exposure=True,
    )
    values.update(changes)
    return ExperimentRequest(**values)


@pytest.mark.parametrize(
    "function, repeats, scan, fm, dynamic, tec_targets, flush, device_modes",
    [
        pytest.param("Sine", 1, False, False, False, (), False, _request().device_modes, id="sine-single-fixed"),
        pytest.param("Sine", 2, False, False, False, (), False, _request().device_modes, id="sine-multiple-fixed"),
        pytest.param("Square", 2, True, False, False, (), True, _request().device_modes, id="square-scan-flush"),
        pytest.param("DC", 2, True, True, True, (), False, _request().device_modes, id="dc-inactive-scan-fm"),
        pytest.param("Sine", 2, False, True, True, (((1, 21.0), (2, 21.0)),), True, _request().device_modes, id="fm-dynamic-locked-tec"),
        pytest.param("Sine", 2, True, False, True, (((1, 21.0), (2, 18.0)), ((1, 25.0), (2, 22.0))), False, _request().device_modes, id="scan-dynamic-unlocked-tec"),
        pytest.param("Sine", 2, False, False, False, (), False,
                     (("ad2", False, True), ("camera", False, True), ("pump", True, False), ("valve", True, True), ("tec", False, True)),
                     id="disabled-and-simulated-subsystems"),
    ],
)
def test_independent_plan_adapter_preserves_static_execution_semantics(
    function, repeats, scan, fm, dynamic, tec_targets, flush, device_modes
):
    request = _request(
        channel0_waveform_function=function, repeats_per_group=repeats,
        frequency_scan_enabled=scan, frequency_values_hz=(90_000.0,) if repeats == 1 else (90_000.0, 110_000.0),
        fm_sweep_enabled=fm, dynamic_camera_start=dynamic,
        tec_scan_enabled=bool(tec_targets), temperature_targets_c=tec_targets,
        flush_enabled=flush, device_modes=device_modes, wfg_templates=(_wfg(function),),
        fm_sweep=(100_000.0, 20_000.0, 2.0, "Symmetric") if fm and function != "DC" else None,
    )
    plan = build_independent_run_plan(request)
    series = legacy_series_from_run_plan(plan)
    normalized = tuple(normalize_experiment(item) for group in series for item in group.experiments)

    assert len(plan.conditions) == request.repeats_per_group * (len(tec_targets) or 1)
    assert len(normalized) == len(plan.conditions)
    assert all(item["do_channels"][0][2] == request.camera_fps for item in normalized)
    assert all(item["flush_enabled"] is flush for item in normalized)
    assert request.device_modes == device_modes  # simulation/enabled state is retained request semantics, not invented by the adapter
    if function == "DC":
        assert all(item["frequency_scan_selected_hz"] is None for item in normalized)
        assert all(item["fm_sweep"] is None for item in normalized)
    elif scan:
        assert [item["frequency_scan_selected_hz"] for item in normalized[:2]] == [90_000.0, 110_000.0]
    if tec_targets:
        assert {item["tec_targets_c"][1] for item in normalized} == {21.0, 25.0} if len(tec_targets) == 2 else {21.0}


def test_pure_planner_does_not_construct_legacy_experiments(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("pure planner must not construct Experiment2")

    monkeypatch.setattr(planning, "Experiment2", forbidden)
    plan = build_independent_run_plan(_request())
    assert len(plan.conditions) == 2


def test_invalid_static_combinations_fail_before_adapter():
    with pytest.raises(ValueError, match="Frequency-list"):
        build_independent_run_plan(_request(frequency_scan_enabled=True, frequency_values_hz=(1.0,)))
    with pytest.raises(ValueError, match="Camera FPS"):
        build_independent_run_plan(_request(camera_fps=0.0))
    with pytest.raises(ValueError, match="Camera Start"):
        build_independent_run_plan(_request(dynamic_camera_start=True, camera_start_s=(0.1,)))


def test_run_plan_contains_no_legacy_experiment_objects():
    plan = build_independent_run_plan(_request())
    assert not any(type(value).__name__ == "Experiment2" for value in plan.conditions)
    assert not hasattr(plan, "legacy_experiment_groups")
    assert all(type(condition.wfg_config) is FrozenMapping for condition in plan.conditions)
    with pytest.raises((AttributeError, TypeError)):
        plan.conditions[0].wfg_config.items += (("new", "value"),)


def test_all_ui_versions_inherit_one_request_extraction_seam():
    assert "_experiment_request" not in qt_ui_v2.MainWindowV2.__dict__
    assert "_experiment_request" not in qt_ui_v3.MainWindowV3.__dict__
    assert qt_ui_v2.MainWindowV2._experiment_request is qt_ui.MainWindow._experiment_request
    assert qt_ui_v3.MainWindowV3._experiment_request is qt_ui.MainWindow._experiment_request


def test_temperature_adapter_preserves_locked_unlocked_targets_and_settling_policy():
    locked = temperature_series_from_request(_request(
        tec_scan_enabled=True, temperature_targets_c=(((1, 20.0), (2, 20.0)),),
        tec_settle_settings=(0.2, 2.0, 30.0, 0.5, 1.0),
    ))
    assert locked.target_at(0) == 20.0
    assert (locked.tolerance_c, locked.min_settle_s, locked.max_wait_s, locked.poll_interval_s, locked.post_stable_hold_s) == (0.2, 2.0, 30.0, 0.5, 1.0)
    unlocked = temperature_series_from_request(_request(
        tec_scan_enabled=True, temperature_targets_c=(((1, 20.0), (2, 18.0)),),
    ))
    assert unlocked.target_at(0) == {1: 20.0, 2: 18.0}
