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

from PySide6.QtGui import QFontMetrics
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


def execution_fields(window) -> dict[str, QLabel]:
    return {
        "state": window.findChild(QLabel, "v3PersistentExecutionState"),
        "last": window.findChild(QLabel, "v3PersistentExecutionLast"),
        "current": window.findChild(QLabel, "v3PersistentExecutionAction"),
        "next": window.findChild(QLabel, "v3PersistentExecutionNext"),
        "trace": window.findChild(QLabel, "v3PersistentExecutionTrace"),
    }


# The indicator's VALUE is the full string the field was given. `.text()` is
# only the part that fits at the current width, because the strip elides.
# Assertions about what the indicator SAYS read the value; assertions about
# how it RENDERS read `displayed_text()` explicitly.
def indicator(window) -> dict[str, str]:
    return {name: field.full_text() for name, field in execution_fields(window).items()}


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


def test_every_execution_field_carries_its_full_text_as_a_tooltip(monkeypatch, tmp_path):
    """The strip clips; hover must be able to recover what was clipped."""

    app = Application()
    window = make_window(monkeypatch, tmp_path, app=app)
    try:
        series = tmp_path / "series"
        series.mkdir()
        app.commissioning_trace_enabled = True
        app.start_commissioning_trace(series)
        window._refresh_v3_execution_indicator()

        enter_running_repeat(window)
        transitions = [
            ("step_started", STEP_INITIALIZE_EXPERIMENT),
            ("step_completed", STEP_INITIALIZE_EXPERIMENT),
            ("step_started", STEP_CONFIGURE_WFG),
            ("step_completed", STEP_CONFIGURE_WFG),
            ("step_started", STEP_CAPTURE_FRAMES),
            ("step_completed", STEP_CAPTURE_FRAMES),
            ("step_started", STEP_SAVE_RESULTS),
        ]
        distinct: set[str] = set()
        for kind, step in transitions:
            window._handle_worker_progress(kind, step)
            for name, field in execution_fields(window).items():
                # Exactly the label's own text -- not an expanded variant.
                assert field.toolTip() == field.full_text(), name
                assert field.toolTip() != "", name
            distinct.add(execution_fields(window)["current"].full_text())

        # The run genuinely moved through several distinct states, so a
        # tooltip set once at construction and never refreshed would have gone
        # stale at some point above rather than trivially matching.
        assert len(distinct) > 2

        app.stop_commissioning_trace()
    finally:
        window.close()


def test_execution_field_tooltips_do_not_go_stale_on_trace_state_change(
    monkeypatch, tmp_path
):
    app = Application()
    window = make_window(monkeypatch, tmp_path, app=app)
    try:
        trace = execution_fields(window)["trace"]
        assert trace.toolTip() == trace.full_text() == "Trace: OFF"

        series = tmp_path / "series"
        series.mkdir()
        app.commissioning_trace_enabled = True
        app.start_commissioning_trace(series)
        window._refresh_v3_execution_indicator()
        assert trace.toolTip() == trace.full_text() == "Trace: RECORDING"

        app.commissioning_trace._degrade("simulated write failure")
        window._refresh_v3_execution_indicator()
        assert trace.full_text().startswith("Trace: DEGRADED")
        assert trace.toolTip() == trace.full_text()
        # The superseded caption must not survive in the tooltip.
        assert "RECORDING" not in trace.toolTip()

        app.stop_commissioning_trace()
    finally:
        window.close()


ELLIPSIS = "…"


def _running_window(monkeypatch, tmp_path, size, *, ad2=True, degrade=False):
    """A window at a real supported size, mid-repeat, laid out for measurement."""

    app = Application()
    window = make_window(monkeypatch, tmp_path, app=app)
    window.resize(*size)
    window.show()
    QApplication.processEvents()
    if degrade:
        series = tmp_path / "series"
        series.mkdir(exist_ok=True)
        app.commissioning_trace_enabled = True
        app.start_commissioning_trace(series)
        app.commissioning_trace._degrade("simulated write failure")
    context = dict(RUNNING_CONTEXT)
    if not ad2:
        context["subsystems"] = dict(RUNNING_CONTEXT["subsystems"], ad2=False)
        context["ad2_wait_required"] = False
    enter_running_repeat(window, context)
    for step in (STEP_INITIALIZE_EXPERIMENT, STEP_CONFIGURE_WFG, STEP_CONFIGURE_CAMERA):
        window._handle_worker_progress("step_started", step)
        window._handle_worker_progress("step_completed", step)
    window._handle_worker_progress("step_started", STEP_CAPTURE_FRAMES)
    QApplication.processEvents()
    return app, window


@pytest.mark.parametrize("size", [(1366, 768), (1440, 900)])
def test_clipped_execution_fields_render_an_ellipsis_not_a_mid_word_cut(
    monkeypatch, tmp_path, size
):
    """A field too narrow for its value must SAY so, not stop mid-word."""

    app, window = _running_window(monkeypatch, tmp_path, size, ad2=False)
    try:
        fields = execution_fields(window)
        current = fields["current"]

        # The exact string the wording exists to protect. If this ever fits,
        # the premise of the test is gone and it must be revisited.
        assert current.full_text() == (
            "Current: Waiting for requested camera frames; AD2 disabled, "
            "no PC trigger command sent"
        )
        assert QFontMetrics(current.font()).horizontalAdvance(
            current.full_text()
        ) > current.width(), "field unexpectedly fits; this test no longer proves anything"

        shown = current.displayed_text()
        assert shown != current.full_text()
        assert shown.endswith(ELLIPSIS), shown
        # The dangerous reading: a bare truncation looks like an ordinary wait.
        assert not shown.startswith("Current: Waiting for requested camera frames;")

        # The full text stays recoverable and is NOT replaced by the elision.
        assert current.toolTip() == current.full_text()
        assert ELLIPSIS not in current.toolTip()
    finally:
        window.close()
        app.stop_commissioning_trace()


@pytest.mark.parametrize("size", [(1366, 768), (1440, 900)])
def test_every_leading_token_survives_elision(monkeypatch, tmp_path, size):
    """An operator must always be able to tell which field is which."""

    app, window = _running_window(monkeypatch, tmp_path, size, degrade=True)
    try:
        fields = execution_fields(window)
        expected_leads = {
            "state": "RUNNING",
            "last": "Last:",
            "current": "Current:",
            "next": "Next:",
            "trace": "Trace:",
        }
        for name, lead in expected_leads.items():
            shown = fields[name].displayed_text()
            assert shown.startswith(lead), (name, shown)
            # A field reduced to nothing but an ellipsis is useless.
            assert shown.strip(ELLIPSIS).strip() != "", (name, shown)
    finally:
        window.close()
        app.stop_commissioning_trace()


@pytest.mark.parametrize("size", [(1366, 768), (1440, 900)])
def test_trace_degraded_token_survives_elision(monkeypatch, tmp_path, size):
    """DEGRADED must stay readable; only its explanatory tail may elide.

    The degraded caption is the longest string this field ever holds, and it
    also widens the field's share of the row, squeezing its neighbours -- so
    this is the case where the token is most at risk.
    """

    app, window = _running_window(monkeypatch, tmp_path, size, degrade=True)
    try:
        trace = execution_fields(window)["trace"]
        assert trace.full_text() == "Trace: DEGRADED — recorded evidence is incomplete"

        shown = trace.displayed_text()
        assert "DEGRADED" in shown, shown
        assert shown.startswith("Trace: DEGRADED")
        # The tail is what elides, and it stays reachable on hover.
        assert shown != trace.full_text()
        assert trace.toolTip() == trace.full_text()
        assert "recorded evidence is incomplete" in trace.toolTip()
    finally:
        window.close()
        app.stop_commissioning_trace()


def test_elision_does_not_ratchet_across_repeated_layout_passes(monkeypatch, tmp_path):
    """Eliding must not feed back into the width that decided the elision.

    Setting a shorter text lowers a label's reported sizeHint, the row hands
    the freed width to the one stretching field, and the next re-elide is
    computed against a narrower allocation. Measured on a plain QLabel that
    collapses the fields about 12 px per pass. The size hints are pinned to
    the full text specifically to stop this.
    """

    app, window = _running_window(monkeypatch, tmp_path, (1366, 768))
    try:
        fields = execution_fields(window)
        observed: list[tuple] = []
        for _pass in range(8):
            window.resize(1366, 768)
            QApplication.processEvents()
            window._refresh_v3_execution_indicator()
            QApplication.processEvents()
            observed.append(
                tuple((f.width(), f.displayed_text()) for f in fields.values())
            )
        assert len(set(observed)) == 1, "execution field widths/text did not settle"
    finally:
        window.close()
        app.stop_commissioning_trace()


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
