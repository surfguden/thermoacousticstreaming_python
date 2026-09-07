"""Offline coverage for the explicit V3 hardware-session lifecycle:

    Initialize hardware -> (use) -> Shutdown hardware -> Initialize hardware

added by CHECKPOINT_S_CLOSURE_DEBUG_AND_HARDWARE_SESSION_LIFECYCLE_V2.

Deliberately proves the *architecture* invariants the task specification
requires, not merely that the button is clickable:

- Shutdown hardware reuses the exact same canonical Application.cleanup()
  authority Application Exit already uses (via the inherited, unmodified
  _start_shutdown() coordinator) -- no second cleanup implementation.
- Shutdown hardware reaches the same canonical Pump-stop backend authority
  manual Stop pump already uses -- no second Pump-stop implementation.
- The button is gated by the exact same busy/active-work flags this window
  already uses elsewhere (_busy_count/_experiment_series_active/
  _zscan_active/_manual_z_operation_active) -- no second busy/lifecycle
  authority, and no hardware close races a live worker.
- Reinitialization (Initialize hardware again, same process) actually works
  by subsystem, and operator-set configuration (widget state) survives the
  round trip while runtime/connection state does not falsely persist.
"""

from __future__ import annotations

import json
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication, QGroupBox

from thermo_acoustic import qt_ui, qt_ui_v3
from thermo_acoustic.application import Application

from conftest import build_with_retry


def process_events_until(condition, timeout_s: float = 2.0) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return condition()


def make_window(monkeypatch, tmp_path, app: Application | None = None) -> qt_ui_v3.MainWindowV3:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    return build_with_retry(lambda: qt_ui_v3.MainWindowV3(app=app))


def _close(window) -> None:
    process_events_until(lambda: not window._threads, 2.0)
    window._cleanup_complete_for_close = True
    window.close()


def test_v3_shutdown_hardware_button_lives_in_the_instrument_bar_not_manual_service(monkeypatch, tmp_path):
    """Section 20: the lifecycle counterpart to Initialize hardware lives in
    the same persistent instrument-bar area as Initialize hardware, not
    inside a Manual & Service dialog."""
    window = make_window(monkeypatch, tmp_path)
    try:
        # The button must share an ancestor with Initialize hardware (the
        # persistent instrument bar), and that ancestor must not be one of
        # the lazily-built Manual & Service dialogs.
        bar = window.findChild(QGroupBox, "v3InstrumentBar")
        assert bar is not None
        assert bar.findChild(type(window.connection_button), "v3InitializeHardwareButton") is not None
        assert bar.findChild(type(window.shutdown_hardware_button), "v3ShutdownHardwareButton") is not None
        for panel_name in ("PumpValve", "Camera", "ZScan"):
            panel = window._ensure_manual_panel(panel_name)
            assert panel.findChild(type(window.shutdown_hardware_button), "v3ShutdownHardwareButton") is None
    finally:
        _close(window)


def test_v3_shutdown_hardware_present_labelled_and_initially_enabled(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.shutdown_hardware_button.text() == "Shutdown hardware"
        assert window.shutdown_hardware_button.isEnabled()
        tooltip = window.shutdown_hardware_button.toolTip()
        assert "power" not in tooltip.lower() or "not physical power-off" in tooltip.lower()
        assert "physically off" not in tooltip.lower()
        # Section 20: must not be visually merged with CRITICAL_STOP.
        assert window.shutdown_hardware_button.property("uiRole") != "critical_stop"
    finally:
        _close(window)


def test_v3_shutdown_hardware_invokes_the_canonical_application_cleanup(monkeypatch, tmp_path):
    """Section 13: the button must not implement its own tec.off()/pump.stop()/
    ad2.reset()/camera.close() -- it must call the one canonical Application-
    level cleanup authority, unchanged."""
    window = make_window(monkeypatch, tmp_path)
    calls = []
    original_cleanup = qt_ui.Application.cleanup

    def spy_cleanup(self):
        calls.append("cleanup")
        return original_cleanup(self)

    try:
        monkeypatch.setattr(qt_ui.Application, "cleanup", spy_cleanup)
        window._v3_shutdown_hardware()
        assert process_events_until(lambda: calls, 2.0)
        assert process_events_until(lambda: not window._shutdown_in_progress, 2.0)
        assert calls == ["cleanup"]
        assert "System Not Initialized" in window.app.status or window.app.status == "Error"
    finally:
        _close(window)


def test_v3_shutdown_hardware_reaches_the_same_pump_stop_authority_as_manual_stop(monkeypatch, tmp_path):
    """Section 18/19: Shutdown hardware must reach the same backend Pump-stop
    call manual Stop pump reaches -- not a second, independent implementation.
    """
    window = make_window(monkeypatch, tmp_path)
    backend_calls: list[str] = []

    class FakePumpBackend:
        def stop(self):
            backend_calls.append("stop")

        def close(self):
            backend_calls.append("close")

    try:
        window.app.pump.backend = FakePumpBackend()
        window.app.pump.initialized = True

        window._v3_shutdown_hardware()
        assert process_events_until(lambda: not window._shutdown_in_progress, 2.0)

        # The canonical CetoniPump.cleanup() path: stop() then backend.close(),
        # the exact same backend.stop() the manual Stop-pump button dispatches
        # through self.app.pump.stop() (qt_ui.py's _pump_stop_button()) -- no
        # second Pump-stop implementation was introduced for shutdown.
        assert backend_calls == ["stop", "close"]
    finally:
        _close(window)


def test_v3_shutdown_hardware_disabled_and_refused_while_a_manual_action_is_busy(monkeypatch, tmp_path):
    """Section 16/17/19: no device cleanup while a run worker can still
    legitimately use that device -- proven with a still-in-progress fake
    motion, not merely an idle busy flag."""
    window = make_window(monkeypatch, tmp_path)
    motion_started = threading.Event()
    release_motion = threading.Event()
    backend_calls: list[str] = []

    class BlockingPumpBackend:
        def refill(self, flow_rate=None):
            backend_calls.append("refill_started")
            motion_started.set()
            release_motion.wait(2.0)
            backend_calls.append("refill_released")

        def read_fill_level(self):
            return 0.0

        def stop(self):
            backend_calls.append("stop")

        def close(self):
            backend_calls.append("close")

    cleanup_calls = []
    original_cleanup = qt_ui.Application.cleanup

    def spy_cleanup(self):
        cleanup_calls.append("app_cleanup")
        return original_cleanup(self)

    try:
        window.app.pump.backend = BlockingPumpBackend()
        window.app.pump.initialized = True
        monkeypatch.setattr(qt_ui.Application, "cleanup", spy_cleanup)

        window._run_action(lambda progress: window.app.pump.refill(), "Refilling")
        assert motion_started.wait(1.0), "fake refill never started"
        assert window._busy_count == 1
        window._refresh_v3_shutdown_hardware_button()
        assert not window.shutdown_hardware_button.isEnabled()

        # Defense-in-depth re-check inside the handler itself, not merely the
        # button's enabled state.
        window._v3_shutdown_hardware()
        QApplication.processEvents()
        assert cleanup_calls == [], "Shutdown must not close hardware while a manual action is in flight"
        assert "stop" not in backend_calls

        release_motion.set()
        assert process_events_until(lambda: window._busy_count == 0 and not window._threads, 2.0)
        window._refresh_v3_shutdown_hardware_button()
        assert window.shutdown_hardware_button.isEnabled()

        # Now that nothing is busy, the same request must actually go through,
        # reaching the same backend.stop() manual Stop pump reaches.
        window._v3_shutdown_hardware()
        assert process_events_until(lambda: cleanup_calls, 2.0)
        assert process_events_until(lambda: "stop" in backend_calls, 2.0)
    finally:
        release_motion.set()
        _close(window)


def test_v3_shutdown_hardware_disabled_while_an_experiment_series_is_active(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window._handle_worker_progress("experiment_series_active", True)
        window._refresh_v3_shutdown_hardware_button()
        assert not window.shutdown_hardware_button.isEnabled()

        cleanup_calls = []
        monkeypatch.setattr(qt_ui.Application, "cleanup", lambda self: cleanup_calls.append("cleanup"))
        window._v3_shutdown_hardware()
        QApplication.processEvents()
        assert cleanup_calls == []

        window._handle_worker_progress("experiment_series_active", False)
        window._refresh_v3_shutdown_hardware_button()
        assert window.shutdown_hardware_button.isEnabled()
    finally:
        _close(window)


def test_v3_double_shutdown_hardware_is_safe_and_idempotent(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window._v3_shutdown_hardware()
        # Immediately request again while the first is still in flight --
        # _start_shutdown()'s own _shutdown_in_progress guard must absorb
        # this, not a second concurrent cleanup thread.
        window._v3_shutdown_hardware()
        assert process_events_until(lambda: not window._shutdown_in_progress, 2.0)

        # A second, fully sequential shutdown after the first completed must
        # also be safe (nothing left to close).
        window._v3_shutdown_hardware()
        assert process_events_until(lambda: not window._shutdown_in_progress, 2.0)
        assert not any("timed out" in str(err).lower() for err in window.app.errors)
    finally:
        _close(window)


def test_v3_reinitialize_after_shutdown_hardware_reconnects_by_subsystem(monkeypatch, tmp_path):
    """Section 14/18 test-matrix #2: Initialize -> Shutdown -> Initialize in
    the same process must actually reconnect every selected subsystem, not
    merely leave the button clickable."""
    window = make_window(monkeypatch, tmp_path)
    try:
        window._start_initialize()
        assert process_events_until(lambda: window._busy_count == 0, 2.0)
        assert window.app.pump.initialized is True
        assert window.app.valve.initialized is True

        window._v3_shutdown_hardware()
        assert process_events_until(lambda: not window._shutdown_in_progress, 2.0)
        assert window.app.pump.initialized is False
        assert window.app.valve.initialized is False

        window._start_initialize()
        assert process_events_until(lambda: window._busy_count == 0, 2.0)
        assert window.app.pump.initialized is True
        assert window.app.valve.initialized is True
        assert window.app.status == "System Initialized"
    finally:
        _close(window)


def test_v3_shutdown_hardware_preserves_operator_widget_configuration(monkeypatch, tmp_path):
    """Section 26 test-matrix #3: explicit hardware-session shutdown must not
    destroy the operator's already-entered experiment configuration, which
    lives in the Qt widgets, not in the instrument objects cleanup()/
    initialize() touch."""
    window = make_window(monkeypatch, tmp_path)
    try:
        window._start_initialize()
        assert process_events_until(lambda: window._busy_count == 0, 2.0)

        window.exp_exposure_ms.setValue(37.5)
        window.exp_camera_fps.setValue(12.0)
        window.syringe.setCurrentText("BD 5ml")

        window._v3_shutdown_hardware()
        assert process_events_until(lambda: not window._shutdown_in_progress, 2.0)

        assert window.exp_exposure_ms.value() == pytest.approx(37.5)
        assert window.exp_camera_fps.value() == pytest.approx(12.0)
        assert window.syringe.currentText() == "BD 5ml"

        window._start_initialize()
        assert process_events_until(lambda: window._busy_count == 0, 2.0)
        assert window.exp_exposure_ms.value() == pytest.approx(37.5)
        assert window.exp_camera_fps.value() == pytest.approx(12.0)
        assert window.syringe.currentText() == "BD 5ml"
    finally:
        _close(window)


def test_v3_shutdown_hardware_stops_projecting_stale_connected_state(monkeypatch, tmp_path):
    """Section 25 test-matrix #4: after a successful shutdown, the connection
    indicators must stop claiming Connected."""
    window = make_window(monkeypatch, tmp_path)
    try:
        window._start_initialize()
        assert process_events_until(lambda: window._busy_count == 0, 2.0)
        window._refresh_status()
        assert window.pump_connection_status.text().startswith("Connected")
        assert window.valve_connection_status.text().startswith("Connected")

        window._v3_shutdown_hardware()
        assert process_events_until(lambda: not window._shutdown_in_progress, 2.0)
        window._refresh_status()
        assert not window.pump_connection_status.text().startswith("Connected")
        assert not window.valve_connection_status.text().startswith("Connected")
    finally:
        _close(window)


def test_v3_shutdown_hardware_does_not_disturb_application_exit_determinism(monkeypatch, tmp_path):
    """Section 22: Exit must still work whether or not the operator pressed
    Shutdown hardware first, and cleanup must be safely repeatable."""
    window = make_window(monkeypatch, tmp_path)
    window._start_initialize()
    assert process_events_until(lambda: window._busy_count == 0, 2.0)

    window._v3_shutdown_hardware()
    assert process_events_until(lambda: not window._shutdown_in_progress, 2.0)

    window.show()
    QApplication.processEvents()
    window.close()
    assert process_events_until(lambda: not window.isVisible(), 2.0)
    assert not any("timed out" in str(err).lower() for err in window.app.errors)
