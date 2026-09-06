"""Offline proof for the V3_SOFTWARE_USABILITY_AND_SHAKEDOWN_UNLOCK checkpoint.

Two bounded, presentation-only changes, both reusing state the shared
preflight already computes:

1. The Preparation checklist rows that tell an operator to "open the manual
   X panel" now carry a button that actually opens it, instead of leaving
   the operator to find Manual & Service themselves.
2. The persistent Readiness chip and the Run-control gate summary, which
   previously showed only a blocking/warning COUNT, now carry the actual
   issue message(s) as a tooltip.

Neither changes what is blocked, how it is blocked, or any hardware call
ordering. Nothing here touches real hardware.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from conftest import build_with_retry
from thermo_acoustic import qt_ui, qt_ui_v3
from thermo_acoustic.application import Application
from thermo_acoustic.experiment_planning import PreflightIssue

from test_v3_execution_indicator import FORBIDDEN_PHRASES


def make_window(monkeypatch, tmp_path, app: Application | None = None) -> qt_ui_v3.MainWindowV3:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    return build_with_retry(lambda: qt_ui_v3.MainWindowV3(app=app))


# --------------------------------------------------------------------------
# Preparation checklist: quick-open navigation to the panel it names
# --------------------------------------------------------------------------


def test_pump_preparation_row_can_open_the_pump_and_valve_panel_directly(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        pump_row = window.findChild(QLabel, None)  # sanity: window built
        assert pump_row is not None
        button = window.findChild(QPushButton, "v3PrepareOpenPanel4")
        assert button is not None
        assert button.text() == "Open Pump & Valve panel"
        assert "PumpValve" not in window._manual_panels

        button.click()

        assert "PumpValve" in window._manual_panels
        dialog = window._manual_panels["PumpValve"]
        assert dialog.isVisible()
        assert "Pump & Valve" in dialog.windowTitle()
    finally:
        window.close()


def test_imaging_focus_row_can_open_the_camera_panel_directly(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        button = window.findChild(QPushButton, "v3PrepareOpenPanel5")
        assert button is not None
        assert button.text() == "Open Camera panel"

        button.click()

        assert "Camera" in window._manual_panels
        assert window._manual_panels["Camera"].isVisible()
    finally:
        window.close()


@pytest.mark.parametrize("index", [1, 2, 3, 6, 7])
def test_checklist_rows_without_a_named_panel_have_no_quick_open_button(monkeypatch, tmp_path, index):
    """Only the two rows that actually say "open the manual X panel" get one.

    Equipment readiness, Environment/Temperature, Sample/Fluidics, Laser/
    Optics, and Acoustic Precheck point at Initialize or Configure/Review,
    which are already one click away without a shortcut.
    """

    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.findChild(QPushButton, f"v3PrepareOpenPanel{index}") is None
    finally:
        window.close()


def test_opening_a_prepare_checklist_panel_issues_no_hardware_call(monkeypatch, tmp_path):
    """The navigation button must be exactly that -- navigation.

    A spy Application records every attribute access on its instrument
    facades; opening the panel and building its widgets must not touch any
    of them.
    """

    calls: list[str] = []

    class WatchedInstrument:
        def __init__(self, calls: list[str], name: str):
            object.__setattr__(self, "_calls", calls)
            object.__setattr__(self, "_name", name)
            # Attributes the panel legitimately reads to render cached state
            # (never a live query) without counting as a "hardware call".
            object.__setattr__(self, "enabled", True)
            object.__setattr__(self, "simulate", True)
            object.__setattr__(self, "fill_level", 1.0)
            object.__setattr__(self, "position", None)
            object.__setattr__(self, "status_note", None)

        def __getattr__(self, item):
            self._calls.append(f"{self._name}.{item}")

            def method(*args, **kwargs):
                self._calls.append(f"{self._name}.{item}()")

            return method

    app = Application()
    app.pump = WatchedInstrument(calls, "pump")
    app.valve = WatchedInstrument(calls, "valve")
    app.camera = WatchedInstrument(calls, "camera")
    window = make_window(monkeypatch, tmp_path, app=app)
    try:
        calls.clear()
        window.findChild(QPushButton, "v3PrepareOpenPanel4").click()
        window.findChild(QPushButton, "v3PrepareOpenPanel5").click()
        QApplication.processEvents()
        hardware_calls = [c for c in calls if c.endswith("()")]
        assert hardware_calls == [], f"opening a panel issued hardware call(s): {hardware_calls}"
    finally:
        window.close()


# --------------------------------------------------------------------------
# Readiness chip / run gate: the actual blocker, not just a count
# --------------------------------------------------------------------------


def fake_result(*, blocking=(), warnings=()):
    issues = tuple(
        PreflightIssue(code=f"b{i}", message=msg, blocking=True) for i, msg in enumerate(blocking)
    ) + tuple(
        PreflightIssue(code=f"w{i}", message=msg, blocking=False) for i, msg in enumerate(warnings)
    )
    preflight = SimpleNamespace(
        issues=issues,
        blocking_issues=tuple(i for i in issues if i.blocking),
        warnings=tuple(i for i in issues if not i.blocking),
    )
    return SimpleNamespace(preflight=preflight)


def test_readiness_tooltip_names_the_actual_blocking_issue():
    result = fake_result(blocking=["AD2 is disabled; canonical acquisition requires it."])
    tooltip = qt_ui_v3.MainWindowV3._v3_readiness_tooltip(result)
    assert tooltip == "Blocking: AD2 is disabled; canonical acquisition requires it."


def test_readiness_tooltip_lists_every_blocking_issue_and_counts_warnings():
    result = fake_result(
        blocking=["First blocker.", "Second blocker."],
        warnings=["A warning nobody needs to act on yet."],
    )
    tooltip = qt_ui_v3.MainWindowV3._v3_readiness_tooltip(result)
    lines = tooltip.splitlines()
    assert lines[0] == "Blocking: First blocker."
    assert lines[1] == "Blocking: Second blocker."
    assert lines[2] == "(1 additional warning(s); open Review run for detail)"


def test_readiness_tooltip_shows_warnings_when_nothing_is_blocking():
    result = fake_result(warnings=["Output path is configured; writeability is unverified."])
    tooltip = qt_ui_v3.MainWindowV3._v3_readiness_tooltip(result)
    assert tooltip == "Warning: Output path is configured; writeability is unverified."


def test_readiness_tooltip_reports_no_issues_when_the_plan_is_clean():
    result = fake_result()
    tooltip = qt_ui_v3.MainWindowV3._v3_readiness_tooltip(result)
    assert tooltip == "No shared preflight issues."


def test_readiness_tooltip_never_uses_physical_claim_wording():
    # The tooltip only ever echoes PreflightIssue.message strings, which are
    # already evidence-vetted elsewhere -- this guards the composition (the
    # "Blocking:"/"Warning:" framing and the additional-warnings summary)
    # against ever adding a claim of its own.
    result = fake_result(
        blocking=["AD2 is disabled; canonical acquisition requires it."],
        warnings=["W1, DIO0, DIO1 are requested API timings, not measured simultaneity."],
    )
    tooltip = qt_ui_v3.MainWindowV3._v3_readiness_tooltip(result).lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in tooltip, f"readiness tooltip must not claim {phrase!r}"


def test_readiness_chip_and_run_gate_show_the_live_blocking_reason(monkeypatch, tmp_path):
    """End-to-end: a real blocking condition reaches both tooltips identically."""

    window = make_window(monkeypatch, tmp_path)
    try:
        # A fresh window's own default Camera FPS is 0, which raises its own
        # (unrelated, pre-existing) blocking issue before the planner ever
        # reaches the W2 check this test targets. Clear that first so the
        # only remaining blocker is the one this test forces.
        window.exp_camera_fps.setValue(20.0)
        ch0, ch1 = window.exp_ad2_channels
        ch1["enable"].setChecked(True)  # W2 selected -> production-blocked
        window._refresh_v3_relationships()

        readiness = window.findChild(QLabel, "v3PersistentReadinessState")
        run_gate = window._v3_run_gate
        assert readiness.text().startswith("BLOCKED —")
        assert "laser Analog In" in readiness.toolTip()
        assert readiness.toolTip() == run_gate.toolTip()

        before = readiness.toolTip()
        ch1["enable"].setChecked(False)
        window._refresh_v3_relationships()
        assert readiness.toolTip() != before
        assert readiness.toolTip() == window._v3_run_gate.toolTip()
    finally:
        window.close()
