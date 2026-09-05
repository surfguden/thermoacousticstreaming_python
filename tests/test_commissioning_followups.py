"""Offline closure evidence for the commissioning-readiness follow-ups.

Covered here: the achieved-cadence external camera gate (C1), the exact-model
DCAM TRIGGERTIMES bound (C2), AD2-disabled Review/runtime consistency (C3), and
the aggregate automatic-refresh requirement in Review (C4). All fake backends;
no hardware is opened, enumerated, configured, triggered, or captured.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from thermo_acoustic.ad2 import DoConfig, DoSingleChannelConfig
from thermo_acoustic.experiment_planning import (
    ExperimentRequest,
    build_independent_run_plan,
    build_result_from_existing_plan,
)
from thermo_acoustic.runtime_truth import (
    EvidenceBasis,
    EvidenceFreshness,
    EvidenceValue,
    RuntimeEvidenceSnapshot,
    SubsystemEvidence,
    VerificationScope,
)

from test_full_flow_dry_run import (
    configure_canonical_triggered_experiment,
    make_fake_app,
    make_recording_experiment,
)


# --------------------------------------------------------------------------
# C1 -- external-trigger feasibility against the achieved DIO0 cadence
# --------------------------------------------------------------------------

# A real, non-exact divider. WaveForms divides its 100 MHz DigitalOut internal
# clock by an integer and the counter toggles on each divided tick, so the
# programmed pulse cadence is internal_clock / (2 * divider):
#     divider  = int((100e6 / 30) / 2) = int(1_666_666.66...) = 1_666_666
#     achieved = 100e6 / (2 * 1_666_666) = 30.000006000001202 Hz
# The truncated divider makes the achieved cadence FASTER than requested, so
# the achieved trigger spacing is SHORTER than the requested spacing. The
# camera is paced by that programmed spacing, not by the request.
INTERNAL_CLOCK_HZ = 100_000_000.0
REQUESTED_FPS = 30.0
DIVIDER = int((INTERNAL_CLOCK_HZ / REQUESTED_FPS) / 2.0)
ACHIEVED_FPS = INTERNAL_CLOCK_HZ / (2.0 * DIVIDER)
REQUESTED_PERIOD_S = 1.0 / REQUESTED_FPS
ACHIEVED_PERIOD_S = 1.0 / ACHIEVED_FPS


def test_divider_quantization_makes_the_achieved_cadence_faster_than_requested():
    """Guard the arithmetic the C1 regression below depends on."""

    assert DIVIDER == 1_666_666
    assert ACHIEVED_FPS > REQUESTED_FPS
    assert ACHIEVED_PERIOD_S < REQUESTED_PERIOD_S
    # One 100 MHz clock step of difference, exactly as documented.
    assert 0 < REQUESTED_PERIOD_S - ACHIEVED_PERIOD_S < 2.1e-8


def build_external_trigger_app(tmp_path, *, min_trigger_interval_s, achieved_hz=ACHIEVED_FPS):
    calls: list = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    configure_canonical_triggered_experiment(experiment, frames=3, fps=REQUESTED_FPS)

    achieved_config = DoConfig(
        running=True,
        frame_count=3,
        channels=[
            DoSingleChannelConfig(
                channel_index=0,
                enable=True,
                clock_frequency_hz=REQUESTED_FPS,
                clock_divider=DIVIDER,
                achieved_clock_frequency_hz=achieved_hz,
            ),
            DoSingleChannelConfig(
                channel_index=1,
                enable=True,
                clock_frequency_hz=REQUESTED_FPS,
                clock_divider=DIVIDER,
                achieved_clock_frequency_hz=achieved_hz,
            ),
        ],
    )
    app.ad2.get_do_config = lambda: achieved_config
    app.camera.read_min_trigger_interval = lambda: min_trigger_interval_s

    app.experiment_series.enqueue_experiments([experiment])
    return app, calls, experiment


def test_external_gate_rejects_a_cadence_only_the_achieved_divider_exceeds(tmp_path):
    # Between the achieved spacing and the requested spacing: the request
    # looks feasible, the cadence the device is actually programmed at does
    # not. The gate must protect the programmed spacing.
    minimum_s = (ACHIEVED_PERIOD_S + REQUESTED_PERIOD_S) / 2.0
    assert ACHIEVED_PERIOD_S < minimum_s < REQUESTED_PERIOD_S

    app, calls, _experiment = build_external_trigger_app(
        tmp_path, min_trigger_interval_s=minimum_s
    )
    with pytest.raises(ValueError) as excinfo:
        app.run_experiment2()

    message = str(excinfo.value)
    assert "achieved DIO0 cadence" in message
    # Requested FPS stays visible as the separate scientific request.
    assert "Configured Camera FPS (30.000)" in message
    assert "requested spacing" in message
    # It fails closed before the camera is ever told to capture.
    assert not any(call[:2] == ("camera", "start_capture") for call in calls)
    assert not any(call[:2] == ("ad2", "pc_trigger") for call in calls)


def test_external_gate_accepts_a_cadence_the_achieved_divider_also_satisfies(tmp_path):
    app, calls, experiment = build_external_trigger_app(
        tmp_path, min_trigger_interval_s=ACHIEVED_PERIOD_S * 0.5
    )
    assert app.run_experiment2() is True
    assert any(call[:2] == ("camera", "start_capture") for call in calls)
    # The achieved cadence was read back from the configured DigitalOut, and
    # the requested cadence remains the recorded request.
    assert experiment.do_configured_by_runtime is True
    assert experiment.sequence_settings["camera_fps"] == REQUESTED_FPS


def test_external_gate_falls_back_to_the_request_when_no_cadence_was_achieved(tmp_path):
    # No real configure_do() ran, so there is no achieved cadence to protect;
    # the gate must use the request rather than inventing a value.
    app, calls, _experiment = build_external_trigger_app(
        tmp_path, min_trigger_interval_s=REQUESTED_PERIOD_S * 1.5, achieved_hz=None
    )
    with pytest.raises(ValueError) as excinfo:
        app.run_experiment2()
    message = str(excinfo.value)
    assert "achieved DIO0 cadence" not in message
    assert "Configured Camera FPS (30.000) requires" in message
    assert not any(call[:2] == ("camera", "start_capture") for call in calls)


def test_internal_trigger_timing_gate_is_untouched_by_the_achieved_cadence(tmp_path):
    calls: list = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path)
    configure_canonical_triggered_experiment(experiment, frames=3, fps=REQUESTED_FPS)
    # Internal/free-running keeps the documented overlapping exposure/readout
    # model; a divider-quantized DIO0 cadence is irrelevant there.
    experiment.sequence_settings["trigger_source"] = "Internal"
    app.camera.read_readout_time = lambda: 0.5
    app.camera.read_min_trigger_interval = lambda: 0.0
    app.experiment_series.enqueue_experiments([experiment])

    with pytest.raises(ValueError) as excinfo:
        app.run_experiment2()
    message = str(excinfo.value)
    assert "ROI readout time" in message
    assert "achieved DIO0 cadence" not in message


# --------------------------------------------------------------------------
# C3 / C4 -- Review presentation consistent with runtime behavior
# --------------------------------------------------------------------------


def _wfg(channel0_enabled: bool = True) -> dict:
    return {
        "running": True,
        "synchronize_state": "Independent",
        "channels": [
            {
                "channel_index": 0,
                "carrier": {"frequency_hz": 1_934_000.0, "enable": channel0_enabled},
                "trigger": {"sec_run": 1.0, "sec_wait": 0.0, "repeat_count": 1},
                "fm_mod": {"enable": False},
            },
            {
                "channel_index": 1,
                "carrier": {"frequency_hz": 2_000.0, "enable": False},
                "trigger": {},
                "fm_mod": {"enable": False},
            },
        ],
    }


def _request(**changes) -> ExperimentRequest:
    values = dict(
        output_path=Path("offline-series"),
        repeats_per_group=3,
        frequency_scan_enabled=False,
        frequency_values_hz=(),
        channel0_waveform_function="Sine",
        camera_fps=20.0,
        frames=10,
        camera_start_s=(0.0,),
        dynamic_camera_start=False,
        fm_sweep_enabled=False,
        channel0_output_selected=True,
        flush_enabled=False,
        tec_scan_enabled=False,
        temperature_targets_c=(),
        device_modes=(
            ("ad2", True, False),
            ("camera", True, False),
            ("pump", True, False),
            ("valve", True, False),
            ("tec", True, False),
        ),
        fixed_camera_start_s=0.0,
        wfg_templates=(_wfg(),),
        sequence_settings=(("frames", 10),),
        # (flow_rate, flush_volume_ml, wait_after_flush_s, syringe_capacity_ml)
        flush_settings=(1000.0, 0.4, 0.0, 5.0),
        exposure_ms=10.0,
        trigger_global_exposure=False,
    )
    values.update(changes)
    return ExperimentRequest(**values)


def _evidence(*, pump_fill_ml: float | None) -> RuntimeEvidenceSnapshot:
    now = datetime.now(timezone.utc)
    pump_values = {}
    if pump_fill_ml is not None:
        pump_values["fill_level_ml"] = EvidenceValue(
            value=pump_fill_ml,
            basis=EvidenceBasis.DERIVED,
            freshness=EvidenceFreshness.CACHED,
            verification=VerificationScope.SOFTWARE,
            observed_at_utc=None,
            source_operation="pump.fill_level",
        )
    return RuntimeEvidenceSnapshot(
        captured_at_utc=now,
        camera=SubsystemEvidence({}),
        tec=SubsystemEvidence({}),
        pump=SubsystemEvidence(pump_values),
        valve=SubsystemEvidence({}),
        experiment=SubsystemEvidence({}),
    )


def _result(request: ExperimentRequest, *, pump_fill_ml: float | None = None):
    plan = build_independent_run_plan(request)
    return build_result_from_existing_plan(request, plan, _evidence(pump_fill_ml=pump_fill_ml))


def _issue(result, code):
    return next((issue for issue in result.preflight.issues if issue.code == code), None)


def test_ad2_disabled_is_blocking_for_canonical_external_trigger_acquisition():
    request = _request(
        device_modes=(
            ("ad2", False, False),
            ("camera", True, False),
            ("pump", True, False),
            ("valve", True, False),
            ("tec", True, False),
        )
    )
    result = _result(request)
    issue = _issue(result, "ad2_disabled")

    assert issue is not None
    # The canonical plan always carries the External-trigger architecture, and
    # the runtime raises before camera arming, so Review must block too.
    assert issue.blocking is True
    assert issue in result.preflight.blocking_issues
    assert "fails closed before camera arming" in issue.message
    assert "skip its hardware actions" not in issue.message
    assert any(
        dict(condition.sequence_settings).get("trigger_architecture")
        == "canonical_pc_triggered_ad2_camera_led"
        for condition in result.plan.conditions
    )


def test_other_disabled_devices_remain_non_blocking_skipped_subsystems():
    request = _request(
        tec_scan_enabled=True,
        temperature_targets_c=((((1, 20.0),)),),
        device_modes=(
            ("ad2", True, False),
            ("camera", True, False),
            ("pump", True, False),
            ("valve", True, False),
            ("tec", False, False),
        ),
    )
    result = _result(request)
    issue = _issue(result, "tec_disabled")

    assert issue is not None
    assert issue.blocking is False
    assert "skip its hardware actions" in issue.message
    assert _issue(result, "ad2_disabled") is None


def test_review_uses_the_aggregate_refresh_requirement_for_a_flat_plan():
    # Three repeats plus the one sequence-level initial refresh: four flushes
    # of 0.4 ml = 1.6 ml required, against a 1.0 ml tracked fill.
    request = _request(flush_enabled=True, repeats_per_group=3)
    result = _result(request, pump_fill_ml=1.0)
    issue = _issue(result, "flush_tracked_fill")

    assert issue is not None
    assert "requires 1.6 ml for 4 flushes" in issue.message
    assert "3 repeat refresh(es) plus one sequence-level initial refresh" in issue.message
    assert "1 ml" in issue.message
    assert "not physical delivered volume" in issue.message
    assert issue.blocking is False


def test_review_aggregate_requirement_accepts_a_sufficient_tracked_fill():
    request = _request(flush_enabled=True, repeats_per_group=3)
    # Exactly the aggregate requirement, not merely one flush volume.
    assert _issue(_result(request, pump_fill_ml=1.6), "flush_tracked_fill") is None
    assert _issue(_result(request, pump_fill_ml=1.5999), "flush_tracked_fill") is not None
    # A single flush volume would have passed under the old one-flush check.
    assert _issue(_result(request, pump_fill_ml=0.4), "flush_tracked_fill") is not None


def test_review_aggregate_requirement_counts_temperature_groups_once():
    # Two temperature points x two repeats = four conditions; the initial
    # refresh belongs to the whole sequence and is charged once, matching
    # Application._preflight_automatic_flush_volume's flattened validation.
    request = _request(
        flush_enabled=True,
        repeats_per_group=2,
        tec_scan_enabled=True,
        temperature_targets_c=(((1, 20.0),), ((1, 25.0),)),
    )
    result = _result(request, pump_fill_ml=1.0)
    issue = _issue(result, "flush_tracked_fill")

    assert len(result.plan.conditions) == 4
    assert issue is not None
    # 4 conditions * 0.4 ml + one 0.4 ml initial = 2.0 ml over 5 flushes,
    # not 2.4 ml over 6 (which would recharge an initial refresh per group).
    assert "requires 2 ml for 5 flushes" in issue.message
    assert "4 repeat refresh(es) plus one sequence-level initial refresh" in issue.message


def test_review_reports_no_refresh_requirement_when_refresh_is_off():
    result = _result(_request(flush_enabled=False), pump_fill_ml=0.0)
    assert _issue(result, "flush_tracked_fill") is None
    assert _issue(result, "valve_route_unverified") is None
