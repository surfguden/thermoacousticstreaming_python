"""Offline proof for V3's persistent read-only Execution indicator.

The indicator is a projection of the canonical progress/event stream the
Monitor already consumes. These tests drive it only through those events, so a
regression that reintroduced a local timer, an elapsed-time guess, or a
physical claim would fail here. Nothing in this file touches hardware.
"""

from __future__ import annotations

import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QGroupBox, QLabel

from conftest import build_with_retry
from thermo_acoustic import qt_ui, qt_ui_v3
from thermo_acoustic.application import (
    Application,
    STEP_CAPTURE_FRAMES,
    STEP_CONFIGURE_CAMERA,
    STEP_CONFIGURE_WFG,
    STEP_FLUSH,
    STEP_INITIALIZE_EXPERIMENT,
    STEP_SAVE_RESULTS,
    STEP_WAIT_FOR_AD2_COMPLETION,
)
from thermo_acoustic.commissioning_trace import CommissioningTraceRecorder, TraceState


# Wording that would assert a physical, electrical, optical, acoustic or
# fluid effect the software never observes. None of it may reach the operator
# through this indicator, in any state.
FORBIDDEN_PHRASES = (
    "w1 triggered",
    "acoustic output",
    "led is illuminated",
    "led on",
    "laser on",
    "emitting",
    "exposure started",
    "exposure has started",
    "sample refreshed",
    "fluid delivered",
    "pressure",
    "physically",
    "verified",
)

RUNNING_CONTEXT = {
    "condition": "default",
    "repeat": 3,
    "repeat_total": 5,
    "temperature_point": None,
    "subsystems": {
        "ad2": True,
        "camera": True,
        "sample_refresh": True,
        "tec": False,
        "record": True,
    },
    "ad2_wait_required": True,
    "tec_condition_ready": False,
}


def make_window(monkeypatch, tmp_path, app: Application | None = None) -> qt_ui_v3.MainWindowV3:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    return build_with_retry(lambda: qt_ui_v3.MainWindowV3(app=app))


def indicator(window) -> dict[str, str]:
    return {
        "state": window.findChild(QLabel, "v3PersistentExecutionState").text(),
        "last": window.findChild(QLabel, "v3PersistentExecutionLast").text(),
        "current": window.findChild(QLabel, "v3PersistentExecutionAction").text(),
        "next": window.findChild(QLabel, "v3PersistentExecutionNext").text(),
        "trace": window.findChild(QLabel, "v3PersistentExecutionTrace").text(),
    }


def indicator_styles(window) -> dict[str, str]:
    return {
        "state": window.findChild(QLabel, "v3PersistentExecutionState").styleSheet(),
        "trace": window.findChild(QLabel, "v3PersistentExecutionTrace").styleSheet(),
    }


def colour_of(style: str) -> str | None:
    """The colour token a stylesheet actually applies, or None if it is quiet."""

    for part in style.split(";"):
        name, _, value = part.partition(":")
        if name.strip() == "color":
            return value.strip()
    return None


def enter_running_repeat(window, context: dict | None = None) -> None:
    window._handle_worker_progress("experiment_series_active", True)
    window._handle_worker_progress("execution_context", dict(context or RUNNING_CONTEXT))
    window._handle_worker_progress("step_reset", None)


def test_execution_indicator_lives_in_the_persistent_strip_and_starts_idle(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        bar = window.findChild(QGroupBox, "v3InstrumentBar")
        assert bar is not None
        # Visible on the ordinary operator journey, not only in Diagnostics.
        for name in (
            "v3PersistentExecutionState",
            "v3PersistentExecutionAction",
            "v3PersistentExecutionNext",
            "v3PersistentExecutionTrace",
        ):
            label = window.findChild(QLabel, name)
            assert label is not None, name
            assert bar.isAncestorOf(label), f"{name} must live in the persistent instrument strip"
        # The strip stays compact after the extra line: it is a status strip,
        # not a panel that pushes the workspace off screen.
        window.resize(1440, 900)
        window.show()
        QApplication.processEvents()
        assert bar.height() <= 120

        shown = indicator(window)
        assert shown["state"].startswith("IDLE")
        assert shown["current"] == "Current: No run in progress"
        assert shown["next"] == "Next: No queued software action"
        assert shown["trace"] == "Trace: OFF"
    finally:
        window.close()


def test_execution_indicator_projects_canonical_progress_events(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        enter_running_repeat(window)
        window._handle_worker_progress("step_started", STEP_INITIALIZE_EXPERIMENT)
        shown = indicator(window)
        assert shown["state"] == "PREPARING | default | repeat 3/5"
        assert shown["current"] == "Current: Creating the repeat record and settings snapshot"
        assert shown["next"] == (
            "Next: Configuring and arming W1 and the shared DigitalOut program"
        )

        window._handle_worker_progress("step_completed", STEP_INITIALIZE_EXPERIMENT)
        window._handle_worker_progress("step_started", STEP_CONFIGURE_WFG)
        window._handle_worker_progress("step_completed", STEP_CONFIGURE_WFG)
        window._handle_worker_progress("step_started", STEP_CONFIGURE_CAMERA)
        assert indicator(window)["current"] == (
            "Current: Configuring and arming camera acquisition properties"
        )

        window._handle_worker_progress("step_completed", STEP_CONFIGURE_CAMERA)
        window._handle_worker_progress("step_started", STEP_CAPTURE_FRAMES)
        shown = indicator(window)
        assert shown["state"] == "RUNNING | default | repeat 3/5"
        assert shown["current"] == (
            "Current: PC trigger command sent; waiting for requested camera frames"
        )
        assert shown["next"] == "Next: Waiting for the software output-completion barrier"

        window._handle_worker_progress("step_completed", STEP_CAPTURE_FRAMES)
        window._handle_worker_progress("step_started", STEP_WAIT_FOR_AD2_COMPLETION)
        shown = indicator(window)
        assert shown["state"] == "WAITING | default | repeat 3/5"
        assert shown["current"] == "Current: Waiting for the software output-completion barrier"

        window._handle_worker_progress("step_completed", STEP_WAIT_FOR_AD2_COMPLETION)
        window._handle_worker_progress("step_started", STEP_FLUSH)
        window._handle_worker_progress("step_started", STEP_SAVE_RESULTS)
        shown = indicator(window)
        # Refresh and save deliberately overlap; both are reported, neither is
        # hidden behind the other.
        assert shown["state"] == "FLUSHING | default | repeat 3/5"
        assert "Automatic sample-refresh commands in progress" in shown["current"]
        assert "Saving acquired frames, metadata and settings" in shown["current"]
        assert shown["next"] == "Next: Complete the current run unit"
    finally:
        window.close()


def test_capture_wording_does_not_claim_a_trigger_when_ad2_is_disabled(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        context = dict(RUNNING_CONTEXT)
        context["subsystems"] = dict(RUNNING_CONTEXT["subsystems"], ad2=False)
        context["ad2_wait_required"] = False
        enter_running_repeat(window, context)
        window._handle_worker_progress("step_started", STEP_CAPTURE_FRAMES)
        assert indicator(window)["current"] == (
            "Current: Waiting for requested camera frames; AD2 disabled, no PC trigger command sent"
        )
    finally:
        window.close()


def test_execution_indicator_never_uses_physical_claim_wording(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        collected: list[str] = []
        enter_running_repeat(window)
        for step in (
            STEP_INITIALIZE_EXPERIMENT,
            STEP_CONFIGURE_WFG,
            STEP_CONFIGURE_CAMERA,
            STEP_CAPTURE_FRAMES,
            STEP_WAIT_FOR_AD2_COMPLETION,
            STEP_FLUSH,
            STEP_SAVE_RESULTS,
        ):
            window._handle_worker_progress("step_started", step)
            collected.extend(indicator(window).values())
            window._handle_worker_progress("step_completed", step)
            collected.extend(indicator(window).values())
        window._handle_worker_progress("step_failed", (STEP_CAPTURE_FRAMES, "boom"))
        collected.extend(indicator(window).values())

        haystack = " || ".join(collected).lower()
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in haystack, f"indicator must not claim {phrase!r}"
        # The one command claim that is legitimate must still be present.
        assert "pc trigger command sent" in haystack
    finally:
        window.close()


def test_execution_indicator_keeps_a_fault_visible_after_the_series_stops(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        enter_running_repeat(window)
        window._handle_worker_progress("step_started", STEP_CAPTURE_FRAMES)
        window._handle_worker_progress(
            "step_failed", (STEP_CAPTURE_FRAMES, "simulated capture failure")
        )
        shown = indicator(window)
        assert shown["state"].startswith("ERROR |")
        assert shown["current"] == (
            "Current: Faulted during: PC trigger command sent; waiting for requested camera frames"
        )
        assert shown["next"] == "Next: No next software action — current phase faulted"

        # The series ends; the fault must not be replaced by IDLE.
        window._handle_worker_progress("experiment_series_active", False)
        after = indicator(window)
        assert after["state"].startswith("ERROR |")
        assert after["current"] == shown["current"]
    finally:
        window.close()


def test_execution_indicator_reports_complete_when_every_step_finished(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        enter_running_repeat(window)
        for step in (
            STEP_INITIALIZE_EXPERIMENT,
            STEP_CONFIGURE_WFG,
            STEP_CONFIGURE_CAMERA,
            STEP_CAPTURE_FRAMES,
            STEP_WAIT_FOR_AD2_COMPLETION,
            STEP_FLUSH,
            STEP_SAVE_RESULTS,
        ):
            window._handle_worker_progress("step_started", step)
            window._handle_worker_progress("step_completed", step)
        window._handle_worker_progress("experiment_series_active", False)
        shown = indicator(window)
        assert shown["state"].startswith("COMPLETE |")
        assert shown["current"] == "Current: Last run unit completed in software"
        assert shown["next"] == "Next: No queued software action"
    finally:
        window.close()


def test_execution_indicator_reports_cleanup_while_shutdown_runs(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        # Do not run a real cleanup thread; only the state the UI already owns.
        monkeypatch.setattr(window, "_set_controls_enabled", lambda enabled: None)
        window._shutdown_in_progress = True
        window._refresh_v3_execution_indicator()
        shown = indicator(window)
        assert shown["state"].startswith("CLEANUP |")
        assert shown["current"] == "Current: Releasing hardware handles during shutdown"
    finally:
        window._shutdown_in_progress = False
        window.close()


def test_execution_indicator_shows_trace_recording_and_degraded_state(monkeypatch, tmp_path):
    app = Application()
    window = make_window(monkeypatch, tmp_path, app=app)
    try:
        toggle = window.findChild(QCheckBox, "v3CommissioningTraceToggle")
        assert toggle is not None
        assert app.commissioning_trace_enabled is False
        assert indicator(window)["trace"] == "Trace: OFF"

        toggle.setChecked(True)
        assert app.commissioning_trace_enabled is True
        # Arming the option alone is not recording: the sequence boundary
        # starts the recorder.
        assert indicator(window)["trace"] == "Trace: OFF"

        series = tmp_path / "series"
        series.mkdir()
        assert app.start_commissioning_trace(series) is TraceState.RECORDING
        window._refresh_v3_execution_indicator()
        assert indicator(window)["trace"] == "Trace: RECORDING"

        app.commissioning_trace._degrade("simulated write failure")
        window._refresh_v3_execution_indicator()
        assert indicator(window)["trace"] == (
            "Trace: DEGRADED — recorded evidence is incomplete"
        )
        app.stop_commissioning_trace()
    finally:
        window.close()


def test_trace_degraded_does_not_compete_with_a_runtime_error(monkeypatch, tmp_path):
    """Lossy evidence and a failed experiment must not read the same.

    Both conditions are forced to be true at once -- the run has faulted AND
    recording has degraded -- because that is the case where a shared colour
    actually misleads: the operator cannot tell which of the two the red is
    for.
    """

    app = Application()
    window = make_window(monkeypatch, tmp_path, app=app)
    try:
        series = tmp_path / "series"
        series.mkdir()
        app.commissioning_trace_enabled = True
        assert app.start_commissioning_trace(series) is TraceState.RECORDING

        enter_running_repeat(window)
        window._handle_worker_progress("step_started", STEP_CAPTURE_FRAMES)
        window._handle_worker_progress(
            "step_failed", (STEP_CAPTURE_FRAMES, "camera returned no frames")
        )
        app.commissioning_trace._degrade("simulated write failure")
        window._refresh_v3_execution_indicator()

        assert indicator(window)["state"].startswith("ERROR")
        assert indicator(window)["trace"].startswith("Trace: DEGRADED")

        styles = indicator_styles(window)
        error_colour = colour_of(styles["state"])
        degraded_colour = colour_of(styles["trace"])

        # Both are conspicuous...
        assert error_colour is not None
        assert degraded_colour is not None
        # ...but they are different conditions with different consequences,
        # so they must not render as the same colour.
        assert error_colour != degraded_colour
        # The experiment failure keeps the saturated failure colour; the
        # evidence problem takes this file's existing divergence marker.
        assert error_colour == "darkred"
        assert degraded_colour == "darkorange"

        app.stop_commissioning_trace()
    finally:
        window.close()


def test_routine_trace_states_stay_quiet(monkeypatch, tmp_path):
    """Normal recording is status, not alarm: no attention colour."""

    app = Application()
    window = make_window(monkeypatch, tmp_path, app=app)
    try:
        assert colour_of(indicator_styles(window)["trace"]) is None

        series = tmp_path / "series"
        series.mkdir()
        app.commissioning_trace_enabled = True
        app.start_commissioning_trace(series)
        window._refresh_v3_execution_indicator()
        recording_colour = colour_of(indicator_styles(window)["trace"])
        assert recording_colour not in {"darkred", "darkorange"}

        app.stop_commissioning_trace()
    finally:
        window.close()


def test_last_completed_action_is_derived_from_emitted_completion_events(
    monkeypatch, tmp_path
):
    """Last tracks the furthest step the runtime actually reported completed."""

    window = make_window(monkeypatch, tmp_path)
    try:
        enter_running_repeat(window)
        # Nothing has completed in this repeat yet.
        assert indicator(window)["last"] == "Last: none yet"

        window._handle_worker_progress("step_started", STEP_INITIALIZE_EXPERIMENT)
        # Starting a step is not completing it.
        assert indicator(window)["last"] == "Last: none yet"

        window._handle_worker_progress("step_completed", STEP_INITIALIZE_EXPERIMENT)
        assert indicator(window)["last"] == "Last: Repeat record created"

        # It advances across a real sequence of transitions, and it always
        # trails Current rather than duplicating it.
        seen: list[tuple[str, str]] = []
        for step, expected in (
            (STEP_CONFIGURE_WFG, "Last: W1 and DigitalOut armed"),
            (STEP_CONFIGURE_CAMERA, "Last: Camera acquisition armed"),
            (STEP_CAPTURE_FRAMES, "Last: Camera capture completed"),
            (STEP_WAIT_FOR_AD2_COMPLETION, "Last: Software output barrier elapsed"),
            (STEP_SAVE_RESULTS, "Last: Results saved"),
        ):
            window._handle_worker_progress("step_started", step)
            during = indicator(window)
            assert during["current"].startswith("Current: ")
            assert during["last"] != during["current"].replace("Current: ", "Last: ", 1)
            window._handle_worker_progress("step_completed", step)
            after = indicator(window)
            assert after["last"] == expected
            seen.append((step, after["last"]))

        # Every transition produced a distinct Last value -- a field stuck on
        # the first completion, or on a constant, would collapse this.
        assert len({text for _step, text in seen}) == len(seen)
    finally:
        window.close()


def test_last_completed_action_survives_a_fault_and_shows_the_last_good_step(
    monkeypatch, tmp_path
):
    """After a fault the operator still needs to know how far the run got."""

    window = make_window(monkeypatch, tmp_path)
    try:
        enter_running_repeat(window)
        for step in (STEP_INITIALIZE_EXPERIMENT, STEP_CONFIGURE_WFG):
            window._handle_worker_progress("step_started", step)
            window._handle_worker_progress("step_completed", step)
        window._handle_worker_progress("step_started", STEP_CONFIGURE_CAMERA)
        window._handle_worker_progress(
            "step_failed", (STEP_CONFIGURE_CAMERA, "camera property rejected")
        )

        shown = indicator(window)
        assert shown["state"].startswith("ERROR")
        # The failed step is NOT reported as completed.
        assert shown["last"] == "Last: W1 and DigitalOut armed"
        assert "Camera acquisition armed" not in shown["last"]
    finally:
        window.close()


def test_last_completed_action_shows_nothing_meaningful_at_idle(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        shown = indicator(window)
        assert shown["state"].startswith("IDLE")
        assert shown["last"] == "Last: none yet"

        # And it returns to that after a run's step state is reset.
        enter_running_repeat(window)
        window._handle_worker_progress("step_started", STEP_INITIALIZE_EXPERIMENT)
        window._handle_worker_progress("step_completed", STEP_INITIALIZE_EXPERIMENT)
        assert indicator(window)["last"] == "Last: Repeat record created"
        window._handle_worker_progress("step_reset", None)
        assert indicator(window)["last"] == "Last: none yet"
    finally:
        window.close()


def test_execution_line_stays_one_row_per_field(monkeypatch, tmp_path):
    """Last is one field on the existing line, not a history panel."""

    window = make_window(monkeypatch, tmp_path)
    try:
        enter_running_repeat(window)
        for step in (STEP_INITIALIZE_EXPERIMENT, STEP_CONFIGURE_WFG, STEP_CONFIGURE_CAMERA):
            window._handle_worker_progress("step_started", step)
            window._handle_worker_progress("step_completed", step)
        shown = indicator(window)["last"]
        # Exactly one completed action is named, not an accumulated list.
        assert shown == "Last: Camera acquisition armed"
        assert chr(10) not in shown
        assert ";" not in shown and " + " not in shown
    finally:
        window.close()


def test_execution_indicator_is_event_driven_and_owns_no_local_clock(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        enter_running_repeat(window)
        window._handle_worker_progress("step_started", STEP_CAPTURE_FRAMES)
        before = indicator(window)

        # Real elapsed time with the Qt event loop spinning, and no new
        # canonical event: an indicator that guessed a phase from elapsed
        # time, or that ran its own timer, would move on here.
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline:
            QApplication.processEvents()
        assert indicator(window) == before

        # It does move when the canonical path actually reports a transition.
        window._handle_worker_progress("step_completed", STEP_CAPTURE_FRAMES)
        window._handle_worker_progress("step_started", STEP_WAIT_FOR_AD2_COMPLETION)
        assert indicator(window) != before
    finally:
        window.close()


def test_execution_indicator_reads_only_reported_condition_and_repeat(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        context = dict(RUNNING_CONTEXT)
        context.update({"condition": "frequency_hz=1.909e+06", "repeat": 2, "repeat_total": 4})
        enter_running_repeat(window, context)
        window._handle_worker_progress("step_started", STEP_SAVE_RESULTS)
        assert indicator(window)["state"] == "SAVING | frequency_hz=1.909e+06 | repeat 2/4"
    finally:
        window.close()
