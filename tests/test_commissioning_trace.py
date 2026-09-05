"""Offline proof that commissioning-trace recording is passive evidence.

Every test here runs against the same fake backends the rest of the offline
suite uses. Nothing in this file opens, enumerates, configures, triggers, or
captures from real hardware.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from conftest import build_with_retry
from thermo_acoustic import hw_logging, qt_ui
from thermo_acoustic.workflows import Experiment2, ExperimentSeries2
from thermo_acoustic.application import Application
from thermo_acoustic.commissioning_trace import (
    CommissioningTraceRecorder,
    TraceState,
    read_trace_events,
)

from test_full_flow_dry_run import (
    configure_canonical_triggered_experiment,
    make_fake_app,
    make_recording_experiment,
)


def normalized_calls(calls: list, root: Path) -> list:
    """Backend conversation with series-local paths made comparable.

    Two runs under different series directories must be compared on what was
    asked of each device, not on the absolute output path each one used.
    """

    def norm(value):
        if isinstance(value, Path):
            try:
                return Path(value).relative_to(root).as_posix()
            except ValueError:
                return str(value)
        if isinstance(value, tuple):
            return tuple(norm(item) for item in value)
        return value

    return [tuple(norm(part) for part in call) for call in calls]


def run_once(tmp_path: Path, *, trace: bool, canonical: bool = True, flush: bool = False):
    """Run exactly one canonical repeat and return (app, backend calls)."""

    calls: list = []
    app = make_fake_app(calls, tmp_path)
    experiment = make_recording_experiment(calls, tmp_path, flush_enabled=flush)
    if canonical:
        configure_canonical_triggered_experiment(experiment)
    app.experiment_series.enqueue_experiments([experiment])
    app.commissioning_trace_enabled = trace
    app.start_commissioning_trace(tmp_path)
    try:
        completed = app.run_experiment2()
    finally:
        app.stop_commissioning_trace()
    return app, calls, completed


def test_trace_off_writes_nothing_and_reports_off_state(tmp_path):
    app, _calls, completed = run_once(tmp_path, trace=False)

    assert completed is True
    assert app.commissioning_trace_state() is TraceState.OFF
    assert not (tmp_path / "commissioning_trace.jsonl").exists()
    assert not (tmp_path / "commissioning_trace_summary.json").exists()
    # The canonical action stream is untouched by the recording option.
    assert (tmp_path / "action_log.jsonl").exists()


def test_trace_records_the_canonical_repeat_timeline_in_order(tmp_path):
    app, _calls, completed = run_once(tmp_path, trace=True)

    assert completed is True
    assert app.commissioning_trace_state() is TraceState.RECORDING
    events = read_trace_events(tmp_path)
    assert events, "recording was armed but produced no trace events"

    # Sequence numbers are dense and strictly increasing, and the file order
    # matches them -- the concurrent refresh worker shares this writer.
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    # Software chronology is monotonic; wall time is provenance only.
    monotonic = [event["monotonic_ns"] for event in events]
    assert all(isinstance(value, int) for value in monotonic)
    assert monotonic == sorted(monotonic)
    assert all(event["wall_time_utc"].endswith("+00:00") for event in events)
    assert all(event["schema_version"] == 1 for event in events)

    # Condition/repeat identity is carried on every event.
    assert {event["condition"] for event in events} == {"default"}
    assert {event["condition_index"] for event in events} == {1}
    assert {event["repeat"] for event in events} == {1}
    assert {event["run_id"] for event in events} == {tmp_path.name}

    ordered = [(event["event"], event["status"]) for event in events]
    assert ordered[0] == ("condition_planned", "READY")
    assert ordered[-1] == ("repeat_outcome", "COMPLETED")

    def index_of(name: str, status: str) -> int:
        return ordered.index((name, status))

    # The canonical software order the operator is told about must be the
    # order the trace reconstructs.
    assert (
        index_of("InitializeExperiment", "STARTED")
        < index_of("ConfigureWfg", "STARTED")
        < index_of("ConfigureCamera", "STARTED")
        < index_of("CaptureFrames", "STARTED")
        < index_of("pc_trigger_command_sent", "SENT")
        < index_of("CaptureFrames", "COMPLETED")
        < index_of("SaveResults", "STARTED")
        < index_of("results_saved", "COMPLETED")
        < index_of("save_flush_rendezvous", "COMPLETED")
        < index_of("repeat_outcome", "COMPLETED")
    )


def test_trace_uses_truthful_evidence_stages_and_never_claims_physical_verification(tmp_path):
    run_once(tmp_path, trace=True)
    events = read_trace_events(tmp_path)

    stages = {event["evidence_stage"] for event in events}
    assert stages <= {
        "REQUESTED",
        "PLANNED",
        "EFFECTIVE",
        "COMMAND_SENT",
        "PROTOCOL_ACKNOWLEDGED",
        "OBSERVED",
    }
    assert "PHYSICAL_VERIFIED" not in stages

    trigger = next(event for event in events if event["event"] == "pc_trigger_command_sent")
    # The single FDwfDeviceTriggerPC call may only be claimed as a command.
    assert trigger["evidence_stage"] == "COMMAND_SENT"
    assert trigger["status"] == "SENT"
    assert trigger["result"]["physical_onset_verified"] is False
    assert trigger["subsystem"] == "acoustic_laser_control"

    planned = next(event for event in events if event["event"] == "condition_planned")
    assert planned["evidence_stage"] == "PLANNED"
    assert "requested" in planned

    summary = json.loads((tmp_path / "commissioning_trace_summary.json").read_text(encoding="utf-8"))
    assert summary["physical_verified_event_count"] == 0
    assert "does not establish physical timing" in summary["evidence_boundary"]


def test_trace_summary_is_derived_from_the_recorded_event_stream(tmp_path):
    run_once(tmp_path, trace=True)
    events = read_trace_events(tmp_path)
    summary = json.loads((tmp_path / "commissioning_trace_summary.json").read_text(encoding="utf-8"))

    assert summary["recording_state"] == "RECORDING"
    assert summary["degraded_reason"] is None
    assert summary["dropped_event_count"] == 0
    assert summary["event_count"] == len(events)
    assert summary["first_wall_time_utc"] == events[0]["wall_time_utc"]
    assert summary["last_wall_time_utc"] == events[-1]["wall_time_utc"]
    assert summary["monotonic_span_ns"] == events[-1]["monotonic_ns"] - events[0]["monotonic_ns"]
    assert summary["conditions_observed"] == {"default": 1}
    assert summary["trace_file"] == "commissioning_trace.jsonl"
    assert summary["action_log_file"] == "action_log.jsonl"

    expected_status_counts: dict[str, int] = {}
    for event in events:
        expected_status_counts[event["status"]] = expected_status_counts.get(event["status"], 0) + 1
    assert summary["status_counts"] == expected_status_counts


def test_recording_adds_no_backend_calls_and_does_not_change_execution(tmp_path):
    off_path = tmp_path / "off"
    on_path = tmp_path / "on"
    off_path.mkdir()
    on_path.mkdir()

    app_off, calls_off, completed_off = run_once(off_path, trace=False)
    app_on, calls_on, completed_on = run_once(on_path, trace=True)

    assert completed_off is completed_on is True
    assert app_off.status == app_on.status
    # Identical hardware conversation, in identical order: recording reads
    # facts the canonical path already produced, it never asks a device
    # anything and never reorders a hardware call.
    assert normalized_calls(calls_off, off_path) == normalized_calls(calls_on, on_path)
    assert app_on.commissioning_trace_state() is TraceState.RECORDING

    off_actions = [
        json.loads(line)
        for line in (off_path / "action_log.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    on_actions = [
        json.loads(line)
        for line in (on_path / "action_log.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["operation"] for record in off_actions] == [
        record["operation"] for record in on_actions
    ]
    # The persisted action-log schema is unchanged by the observer hook.
    assert "monotonic_ns" not in off_actions[0]
    assert "monotonic_ns" not in on_actions[0]


def test_recording_adds_no_backend_calls_with_the_concurrent_refresh_worker(tmp_path):
    """Same proof with save and refresh overlapping.

    The save branch and the hardware-only refresh worker interleave by design,
    so only the multiset of device calls is comparable here; the ordered
    equality above covers the fully sequential path.
    """

    off_path = tmp_path / "off"
    on_path = tmp_path / "on"
    off_path.mkdir()
    on_path.mkdir()

    _app_off, calls_off, completed_off = run_once(off_path, trace=False, flush=True)
    app_on, calls_on, completed_on = run_once(on_path, trace=True, flush=True)

    assert completed_off is completed_on is True
    assert sorted(map(repr, normalized_calls(calls_off, off_path))) == sorted(
        map(repr, normalized_calls(calls_on, on_path))
    )
    assert any(call[:2] == ("valve", "set_position") for call in calls_on)
    assert app_on.commissioning_trace_state() is TraceState.RECORDING

    events = read_trace_events(on_path)
    ordered = [(event["event"], event["status"]) for event in events]
    assert ("Flush", "STARTED") in ordered
    assert ("Flush", "COMPLETED") in ordered
    assert ("save_flush_rendezvous", "COMPLETED") in ordered
    rendezvous = next(event for event in events if event["event"] == "save_flush_rendezvous")
    assert rendezvous["result"]["refresh_requested"] is True
    assert rendezvous["result"]["refresh_completed"] is True
    assert rendezvous["result"]["physical_fluid_refresh_verified"] is False
    # The rendezvous is the last thing before the repeat outcome: both
    # branches have rejoined and the main thread has finalized the result.
    assert ordered.index(("save_flush_rendezvous", "COMPLETED")) > ordered.index(
        ("Flush", "COMPLETED")
    )
    assert ordered.index(("save_flush_rendezvous", "COMPLETED")) > ordered.index(
        ("SaveResults", "COMPLETED")
    )


def test_trace_start_failure_degrades_without_blocking_the_run(tmp_path):
    series = tmp_path / "series"
    series.mkdir()
    # A directory where the trace file belongs makes the initial open fail.
    (series / "commissioning_trace.jsonl").mkdir()

    calls: list = []
    app = make_fake_app(calls, series)
    experiment = make_recording_experiment(calls, series)
    configure_canonical_triggered_experiment(experiment)
    app.experiment_series.enqueue_experiments([experiment])
    app.commissioning_trace_enabled = True

    assert app.start_commissioning_trace(series) is TraceState.DEGRADED
    completed = app.run_experiment2()
    app.stop_commissioning_trace()

    assert completed is True, "a trace that cannot be created must not stop the experiment"
    assert app.commissioning_trace_state() is TraceState.DEGRADED
    assert app.commissioning_trace.degraded_reason
    baseline = tmp_path / "baseline"
    baseline_app, baseline_calls, _ = run_once(baseline, trace=False)
    assert normalized_calls(calls, series) == normalized_calls(baseline_calls, baseline)
    assert app.status == baseline_app.status


def test_trace_write_failure_marks_degraded_without_changing_execution(tmp_path):
    series = tmp_path / "series"
    series.mkdir()
    calls: list = []
    app = make_fake_app(calls, series)
    experiment = make_recording_experiment(calls, series)
    configure_canonical_triggered_experiment(experiment)
    app.experiment_series.enqueue_experiments([experiment])
    app.commissioning_trace_enabled = True

    assert app.start_commissioning_trace(series) is TraceState.RECORDING
    # Break the destination after recording started: every later append fails.
    trace_file = series / "commissioning_trace.jsonl"
    trace_file.unlink()
    trace_file.mkdir()

    completed = app.run_experiment2()
    app.stop_commissioning_trace()

    assert completed is True, "a failed trace append must not stop the experiment"
    assert app.commissioning_trace_state() is TraceState.DEGRADED
    assert "trace write failed" in (app.commissioning_trace.degraded_reason or "")
    assert app.commissioning_trace.dropped_event_count > 0
    assert app.commissioning_trace.event_count == 0

    baseline = tmp_path / "baseline"
    baseline_app, baseline_calls, _ = run_once(baseline, trace=False)
    assert normalized_calls(calls, series) == normalized_calls(baseline_calls, baseline)
    assert app.status == baseline_app.status
    # Degraded recording must not be reported as a complete trace.
    summary_path = series / "commissioning_trace_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["recording_state"] == "DEGRADED"
        assert summary["dropped_event_count"] > 0


def test_trace_records_failure_and_cleanup_events(tmp_path):
    series = tmp_path / "series"
    series.mkdir()
    calls: list = []
    app = make_fake_app(calls, series)
    experiment = make_recording_experiment(calls, series)
    configure_canonical_triggered_experiment(experiment)

    def failing_image_sequence(frame_count=0, partial_capture_folder=None):
        calls.append(("camera", "image_sequence", frame_count))
        raise RuntimeError("simulated capture failure")

    app.camera.image_sequence = failing_image_sequence
    app.experiment_series.enqueue_experiments([experiment])
    app.commissioning_trace_enabled = True
    app.start_commissioning_trace(series)
    with pytest.raises(RuntimeError, match="simulated capture failure"):
        app.run_experiment2()
    app.stop_commissioning_trace()

    events = read_trace_events(series)
    ordered = [(event["event"], event["status"]) for event in events]
    assert ("CaptureFrames", "FAILED") in ordered
    assert ("primary_failure", "FAILED") in ordered
    failure = next(event for event in events if event["event"] == "primary_failure")
    assert "simulated capture failure" in failure["error"]
    assert failure["software_phase"] == "RUN"

    summary = json.loads((series / "commissioning_trace_summary.json").read_text(encoding="utf-8"))
    assert summary["errors"], "a failed run must retain its error in the summary"
    assert any("simulated capture failure" in entry["error"] for entry in summary["errors"])


def test_observer_registration_is_removed_when_recording_stops(tmp_path):
    series = tmp_path / "series"
    series.mkdir()
    recorder = CommissioningTraceRecorder(series_path=series)
    before = len(hw_logging._action_observers)
    recorder.start()
    assert len(hw_logging._action_observers) == before + 1
    recorder.stop()
    assert len(hw_logging._action_observers) == before

    # A stopped recorder never appends again, even if an action still fires.
    with hw_logging.action_scope(
        series / "action_log.jsonl", run_id="r", condition="default", repeat=1
    ):
        hw_logging.log_action("run", "after_stop", evidence_stage="OBSERVED", status="COMPLETED")
    assert all(event["event"] != "after_stop" for event in read_trace_events(series))


def test_action_observer_exception_cannot_reach_the_caller(tmp_path):
    def exploding(_record):
        raise RuntimeError("observer defect")

    token = hw_logging.register_action_observer(exploding)
    try:
        with hw_logging.action_scope(
            tmp_path / "action_log.jsonl", run_id="r", condition="default", repeat=1
        ):
            hw_logging.log_action(
                "run", "guarded", evidence_stage="OBSERVED", status="COMPLETED"
            )
    finally:
        hw_logging.unregister_action_observer(token)

    records = [
        json.loads(line)
        for line in (tmp_path / "action_log.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["operation"] for record in records] == ["guarded"]


def test_sequence_boundary_brackets_the_trace_and_records_start_and_finish(monkeypatch, tmp_path):
    class CompletingApplication(qt_ui.Application):
        def run_experiment2(self, progress=None) -> bool:
            self.experiment_series.dequeue_experiment()
            self.status = "ExperimentComplete"
            return True

    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", tmp_path / "settings.json")
    QApplication.instance() or QApplication([])
    app = CompletingApplication()
    app.commissioning_trace_enabled = True
    window = build_with_retry(lambda: qt_ui.MainWindow(app=app))
    try:
        series = ExperimentSeries2(
            series_path=tmp_path, experiments=[Experiment2(), Experiment2()]
        )
        result = window._run_experiment_series(series, 1, window._experiment_wfg_config())
    finally:
        window.close()

    assert result == "ExperimentComplete"
    # Recording is armed for exactly one sequence and released afterwards.
    assert app.commissioning_trace_state() is TraceState.RECORDING
    assert app.commissioning_trace._token is None

    events = read_trace_events(tmp_path)
    ordered = [(event["event"], event["status"]) for event in events]
    assert ordered[0] == ("sequence_started", "STARTED")
    assert ordered[-1] == ("sequence_completed", "COMPLETED")
    start = events[0]
    assert start["software_phase"] == "SEQUENCE"
    assert start["evidence_stage"] == "PLANNED"
    assert start["requested"]["requested_repeats"] == 2
    assert start["requested"]["commissioning_trace"] == "RECORDING"
    assert events[-1]["result"]["series_result"] == "ExperimentComplete"

    summary = json.loads((tmp_path / "commissioning_trace_summary.json").read_text(encoding="utf-8"))
    assert summary["event_count"] == len(events)
    assert summary["software_phase_counts"]["SEQUENCE"] == 2


def test_sequence_boundary_records_a_graceful_abort_truthfully(monkeypatch, tmp_path):
    class AbortingApplication(qt_ui.Application):
        def run_experiment2(self, progress=None) -> bool:
            self.experiment_series.dequeue_experiment()
            self.status = "ExperimentComplete"
            self.fire_stop_event()
            return True

    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", tmp_path / "settings.json")
    QApplication.instance() or QApplication([])
    app = AbortingApplication()
    app.commissioning_trace_enabled = True
    window = build_with_retry(lambda: qt_ui.MainWindow(app=app))
    try:
        series = ExperimentSeries2(
            series_path=tmp_path, experiments=[Experiment2(), Experiment2()]
        )
        result = window._run_experiment_series(series, 1, window._experiment_wfg_config())
    finally:
        window.close()

    assert result == "ExperimentSeriesAborted"
    events = read_trace_events(tmp_path)
    final = events[-1]
    assert (final["event"], final["status"]) == ("sequence_completed", "GRACEFULLY_ABORTED")
    assert final["result"]["series_result"] == "ExperimentSeriesAborted"


def test_action_records_outside_a_run_scope_are_not_traced(tmp_path):
    series = tmp_path / "series"
    series.mkdir()
    recorder = CommissioningTraceRecorder(series_path=series)
    recorder.start()
    try:
        hw_logging.log_action("run", "unscoped", evidence_stage="OBSERVED", status="COMPLETED")
    finally:
        recorder.stop()
    assert read_trace_events(series) == []
