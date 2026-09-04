from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import thermo_acoustic.experiment_planning as planning
from thermo_acoustic import qt_ui, qt_ui_v3
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
             "trigger": {"sec_run": 1.0, "sec_wait": 0.2, "repeat_count": 1},
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
        sequence_settings=(("frames", 10), ("trigger_source", "Internal"), (
            "roi", {"horizontal_offset": 0, "vertical_offset": 792,
                    "horizontal_size": 2304, "vertical_size": 740},
        )),
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
        pytest.param("DC", 2, True, False, True, (), False, _request().device_modes, id="dc-inactive-scan"),
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
        fm_sweep=(90_000.0, 110_000.0, 2.0, "Symmetric") if fm and function != "DC" else None,
    )
    plan = build_independent_run_plan(request)
    series = legacy_series_from_run_plan(plan)
    normalized = tuple(normalize_experiment(item) for group in series for item in group.experiments)

    assert len(plan.conditions) == request.repeats_per_group * (len(tec_targets) or 1)
    assert len(normalized) == len(plan.conditions)
    assert all(item["do_clock"]["running"] is False for item in normalized)
    assert all(item["do_channels"] == () for item in normalized)
    assert all(item["flush_enabled"] is flush for item in normalized)
    assert all(item["sequence_settings"]["camera_fps"] == request.camera_fps for item in normalized)
    assert all(item["requested_exposure_ms"] == request.exposure_ms for item in normalized)
    assert all(item["applied_exposure_ms"] is None for item in normalized)
    assert all(item["flush"][2] == request.flush_settings[2] for item in normalized)
    assert request.device_modes == device_modes  # simulation/enabled state is retained request semantics, not invented by the adapter
    if function == "DC":
        assert all(item["frequency_scan_selected_hz"] is None for item in normalized)
        assert all(item["fm_sweep"] is None for item in normalized)
    elif scan:
        assert [item["frequency_scan_selected_hz"] for item in normalized[:2]] == [90_000.0, 110_000.0]
    if tec_targets:
        assert {item["tec_targets_c"][1] for item in normalized} == {21.0, 25.0} if len(tec_targets) == 2 else {21.0}
    assert all(item["sequence_settings"]["roi"]["vertical_offset"] == 792 for item in normalized)


def test_pure_planner_does_not_construct_legacy_experiments(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("pure planner must not construct Experiment2")

    monkeypatch.setattr(planning, "Experiment2", forbidden)
    plan = build_independent_run_plan(_request())
    assert len(plan.conditions) == 2


def test_normal_plan_disables_dio_even_when_legacy_template_is_supplied():
    request = _request(
        do_template={
            "running": True,
            "channels": [{"channel_index": 1, "enable": True, "clock_frequency_hz": 20.0}],
        }
    )

    normalized = legacy_series_from_run_plan(build_independent_run_plan(request))[0].experiments

    assert all(experiment.do_clock_settings.running is False for experiment in normalized)
    assert all(experiment.do_clock_settings.channels == [] for experiment in normalized)


def test_invalid_static_combinations_fail_before_adapter():
    with pytest.raises(ValueError, match="Frequency-list"):
        build_independent_run_plan(_request(frequency_scan_enabled=True, frequency_values_hz=(1.0,)))
    with pytest.raises(ValueError, match="Camera FPS"):
        build_independent_run_plan(_request(camera_fps=0.0))
    with pytest.raises(ValueError, match="Camera Start"):
        build_independent_run_plan(_request(dynamic_camera_start=True, camera_start_s=(0.1,)))


def test_production_channel0_repeat_must_be_exactly_one():
    for repeat_count in (0, 2):
        config = _wfg()
        config["channels"][0]["trigger"]["repeat_count"] = repeat_count
        with pytest.raises(ValueError, match="Repeat must be exactly 1"):
            build_independent_run_plan(_request(wfg_templates=(config,)))

    plan = build_independent_run_plan(_request(wfg_templates=(_wfg(),)))
    assert plan.conditions


def test_production_rejects_laser_w2_output_until_input_semantics_are_confirmed():
    config = _wfg()
    config["channels"][1]["carrier"]["enable"] = True

    with pytest.raises(ValueError, match="W2 is connected to the laser Analog In"):
        build_independent_run_plan(_request(wfg_templates=(config,)))

    config["channels"][1]["carrier"]["enable"] = False
    config["channels"][1]["fm_mod"]["enable"] = True
    with pytest.raises(ValueError, match="W2 is connected to the laser Analog In"):
        build_independent_run_plan(_request(wfg_templates=(config,)))


def test_fm_sweep_rejects_frequency_scan_and_requires_explicit_channel0_enable():
    with pytest.raises(ValueError, match="FM Sweep and Frequency Scan"):
        build_independent_run_plan(_request(fm_sweep_enabled=True, frequency_scan_enabled=True))

    disabled = _wfg()
    disabled["channels"][0]["carrier"]["enable"] = False
    with pytest.raises(ValueError, match="explicitly enabled"):
        build_independent_run_plan(
            _request(fm_sweep_enabled=True, channel0_output_selected=False, wfg_templates=(disabled,))
        )

    not_running = _wfg()
    not_running["running"] = False
    with pytest.raises(ValueError, match="waveform generator to be running"):
        build_independent_run_plan(_request(fm_sweep_enabled=True, wfg_templates=(not_running,)))


def test_fm_sweep_endpoints_are_authoritative_through_plan_and_adapter():
    plan = build_independent_run_plan(
        _request(
            fm_sweep_enabled=True,
            fm_sweep=(1_909_000.0, 1_959_000.0, 1.0, "Symmetric"),
            wfg_templates=(_wfg(),),
        )
    )

    condition = plan.conditions[0]
    channel = condition.wfg_config.value_for("channels").values[0]
    experiment = legacy_series_from_run_plan(plan)[0].experiments[0]
    assert condition.fm_sweep == (1_909_000.0, 1_959_000.0, 1.0, "Symmetric")
    assert channel.value_for("carrier").value_for("frequency_hz") == 1_934_000.0
    assert channel.value_for("fm_mod").value_for("amplitude_v") == pytest.approx(1.2926577)
    assert experiment.fm_sweep.start_hz == 1_909_000.0
    assert experiment.fm_sweep.stop_hz == 1_959_000.0


def test_fm_sweep_plan_rejects_missing_or_zero_width_endpoint_request():
    with pytest.raises(ValueError, match="no start/stop"):
        build_independent_run_plan(_request(fm_sweep_enabled=True, fm_sweep=None))
    with pytest.raises(ValueError, match="stop must be greater than start"):
        build_independent_run_plan(
            _request(fm_sweep_enabled=True, fm_sweep=(1_934_000.0, 1_934_000.0, 1.0, "Symmetric"))
        )


def test_run_plan_contains_no_legacy_experiment_objects():
    plan = build_independent_run_plan(_request())
    assert not any(type(value).__name__ == "Experiment2" for value in plan.conditions)
    assert not hasattr(plan, "legacy_experiment_groups")
    assert all(type(condition.wfg_config) is FrozenMapping for condition in plan.conditions)
    with pytest.raises((AttributeError, TypeError)):
        plan.conditions[0].wfg_config.items += (("new", "value"),)


def test_request_and_run_condition_deep_freeze_nested_sequence_settings():
    mutable_values = [0.1, 0.2]
    request = _request(sequence_settings=(("frames", 10), ("nested", mutable_values)))
    mutable_values.append(9.9)

    plan = build_independent_run_plan(request)
    condition = plan.conditions[0]
    nested = dict(condition.sequence_settings)["nested"]
    assert nested.values == (0.1, 0.2)
    with pytest.raises((AttributeError, TypeError)):
        nested.values += (9.9,)

    adapted = legacy_series_from_run_plan(plan)[0].experiments[0]
    adapted.sequence_settings["nested"].append(7.7)
    assert dict(condition.sequence_settings)["nested"].values == (0.1, 0.2)


def test_normal_start_routes_through_shared_planner_and_adapter(monkeypatch, tmp_path):
    request = _request(output_path=tmp_path)
    calls = []
    real_planner = planning.build_independent_run_plan
    real_adapter = planning.legacy_series_from_run_plan

    def planner_spy(value):
        calls.append("planner")
        return real_planner(value)

    def adapter_spy(value):
        calls.append("adapter")
        return real_adapter(value)

    monkeypatch.setattr(qt_ui, "build_independent_run_plan", planner_spy)
    monkeypatch.setattr(qt_ui, "legacy_series_from_run_plan", adapter_spy)

    sink = SimpleNamespace(setText=lambda _value: None)
    window = SimpleNamespace(
        series_path=SimpleNamespace(text=lambda: str(tmp_path)),
        queue_count=sink,
        waveform_graph=SimpleNamespace(set_points=lambda _points: None),
        _series_path_has_existing_data=lambda _path: False,
        _start_experiment_legacy_authority=lambda _path: (_ for _ in ()).throw(
            AssertionError("normal Start must not invoke the rollback builder")
        ),
        _experiment_request=lambda: request,
        _preview_points=lambda _config: (),
        _run_action=lambda _action, _label: calls.append("runtime"),
    )

    qt_ui.MainWindow._start_experiment(window)
    assert calls == ["planner", "adapter", "runtime"]


def test_retained_ui_versions_inherit_one_request_extraction_seam():
    assert "_experiment_request" not in qt_ui_v3.MainWindowV3.__dict__
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
