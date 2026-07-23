from __future__ import annotations

import json
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QDoubleSpinBox
from PySide6.QtWidgets import QApplication

from thermo_acoustic import qt_ui
from thermo_acoustic.camera import SubRegion
from thermo_acoustic.hardware_config import ZStageBackend, default_hardware_config


def make_window(monkeypatch, tmp_path, settings: dict | None = None) -> qt_ui.MainWindow:
    settings_path = tmp_path / "settings.json"
    if settings is not None:
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    return qt_ui.MainWindow()


def combo_items(widget) -> list[str]:
    return [widget.itemText(index) for index in range(widget.count())]


def process_events_until(condition, timeout_s: float = 2.0) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return condition()


def test_focus_wheel_guard_ignores_unfocused_spinbox_wheel():
    QApplication.instance() or QApplication([])
    guard = qt_ui.FocusWheelGuard()
    spin = QDoubleSpinBox()

    try:
        event = QEvent(QEvent.Type.Wheel)

        handled = guard.eventFilter(spin, event)

        assert handled is True
        assert not event.isAccepted()
    finally:
        spin.close()


def test_wfg_synchronize_state_is_visibly_disabled_stub(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    assert not window.wfg_sync.isEnabled()
    assert "Not implemented" in window.wfg_sync.toolTip()


def test_qt_ui_uses_passive_hardware_config_defaults(monkeypatch, tmp_path):
    defaults = default_hardware_config()

    window = make_window(monkeypatch, tmp_path)

    assert window.z_backend.currentText() == ZStageBackend.DISABLED.value
    assert window.prior_resource.text() == defaults.z_stage.prior_resource
    assert window.thorlabs_apt_serial.text() == defaults.z_stage.thorlabs_apt_serial
    assert window.thorlabs_apt_backend.text() == defaults.z_stage.thorlabs_apt_backend
    assert window.thorlabs_apt_discovery_only.isChecked() is True
    assert window.cetoni_config_path.text() == str(defaults.qmix.config_path)
    assert window.qmix_sdk_python_path.text() == str(defaults.qmix.sdk_python_path)
    assert window.qmix_qmixsdk_path.text() == str(defaults.qmix.qmixsdk_path)


def test_qt_ui_settings_dict_includes_passive_hardware_fields(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    settings = window._settings_dict()

    assert settings["z_backend"] == ZStageBackend.DISABLED.value
    assert settings["prior_resource"] == "COM7"
    assert settings["thorlabs_apt_serial"] == "44533854"
    assert settings["thorlabs_apt_backend"] == "pylablib"
    assert settings["thorlabs_apt_discovery_only"] is True
    assert settings["qmix_sdk_python_path"].endswith(r"qmix_sdk_for_codex\python")
    assert settings["qmix_qmixsdk_path"] == r"C:\Users\Lab user\AppData\Local\CETONI_SDK"
    assert "Cetoni_1pump_config_FM" in settings["cetoni_config_path"]


def test_qt_ui_load_settings_is_backward_compatible(monkeypatch, tmp_path):
    old_settings = {
        "z_enabled": False,
        "prior_resource": "COM7",
        "valve_resource": "COM6",
        "cetoni_config_path": r"C:\Users\Public\Documents\QmixElements\Projects",
    }

    window = make_window(monkeypatch, tmp_path, old_settings)

    assert window.z_backend.currentText() == ZStageBackend.DISABLED.value
    assert window.thorlabs_apt_serial.text() == "44533854"
    assert window.thorlabs_apt_backend.text() == "pylablib"
    assert window.thorlabs_apt_discovery_only.isChecked() is True
    assert window.qmix_sdk_python_path.text().endswith(r"qmix_sdk_for_codex\python")
    assert window.qmix_qmixsdk_path.text() == r"C:\Users\Lab user\AppData\Local\CETONI_SDK"
    assert window.cetoni_config_path.text() == old_settings["cetoni_config_path"]


def test_qt_ui_save_and_restore_passive_hardware_fields(monkeypatch, tmp_path):
    first_window = make_window(monkeypatch, tmp_path)
    first_window.z_backend.setCurrentText(ZStageBackend.THORLABS_APT.value)
    first_window.thorlabs_apt_serial.setText("44533854")
    first_window.thorlabs_apt_backend.setText("pylablib")
    first_window.thorlabs_apt_discovery_only.setChecked(False)
    first_window.qmix_sdk_python_path.setText(r"C:\sdk\python")
    first_window.qmix_qmixsdk_path.setText(r"C:\sdk\dll")
    first_window.cetoni_config_path.setText(r"C:\configs\one-pump")

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["z_backend"] == ZStageBackend.THORLABS_APT.value
    assert saved["thorlabs_apt_discovery_only"] is False
    assert saved["qmix_sdk_python_path"] == r"C:\sdk\python"

    second_window = qt_ui.MainWindow()

    assert second_window.z_backend.currentText() == ZStageBackend.THORLABS_APT.value
    assert second_window.thorlabs_apt_serial.text() == "44533854"
    assert second_window.thorlabs_apt_backend.text() == "pylablib"
    assert second_window.thorlabs_apt_discovery_only.isChecked() is False
    assert second_window.qmix_sdk_python_path.text() == r"C:\sdk\python"
    assert second_window.qmix_qmixsdk_path.text() == r"C:\sdk\dll"
    assert second_window.cetoni_config_path.text() == r"C:\configs\one-pump"


def test_qt_ui_experiment_flush_is_disabled_by_default_and_explicitly_enabled(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(20)

    series, _total_frames, _config = window._build_experiment_series()

    assert series.experiments is not None
    assert [experiment.flush_enabled for experiment in series.experiments] == [False]
    assert [experiment.trigger_global_exposure for experiment in series.experiments] == [False]
    assert series.experiments[0].do_clock_settings.running is True
    assert series.experiments[0].do_clock_settings.channels[0].channel_index == 1
    assert series.experiments[0].do_clock_settings.channels[0].clock_frequency_hz == 100.0
    assert series.experiments[0].do_clock_settings.channels[0].trigger.sec_run == 0.2

    window.exp_flush_enabled.setChecked(True)
    window.global_exposure.setChecked(True)
    series, _total_frames, _config = window._build_experiment_series()

    assert series.experiments is not None
    assert [experiment.flush_enabled for experiment in series.experiments] == [True]
    assert [experiment.trigger_global_exposure for experiment in series.experiments] == [True]


def test_qt_ui_experiment_do_clock_config_uses_camera_timing_fields(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.exp_camera_fps.setValue(200.0)
    window.exp_camera_start.setValue(0.125)
    window.exp_frames.setValue(50)

    do_config = window._experiment_do_clock_config(0)

    assert do_config.running is True
    assert len(do_config.channels) == 1
    channel = do_config.channels[0]
    assert channel.channel_index == 1
    assert channel.enable is True
    assert channel.clock_frequency_hz == 200.0
    assert channel.output_type == qt_ui.DigitalOutType.PULSE
    assert channel.idle_state == qt_ui.DigitalOutIdleState.INITIAL
    assert channel.counter_high_bits == 1
    assert channel.counter_low_bits == 1
    assert channel.counter_initial_bits == 0
    assert channel.start_high is True
    assert channel.trigger.sec_run == 0.25
    assert channel.trigger.sec_wait == 0.125
    assert channel.trigger.repeat_count == 0
    assert channel.trigger.repeat_trigger is False
    assert channel.trigger.source == qt_ui.TriggerSource.NONE

    window.dynamic_camera_start.setChecked(True)
    window.camera_start_array[2].setValue(0.333)

    dynamic_config = window._experiment_do_clock_config(2)

    assert dynamic_config.channels[0].trigger.sec_wait == 0.333


def test_qt_ui_experiment_do_clock_rejects_zero_camera_fps(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.exp_camera_fps.setValue(0.0)

    try:
        window._experiment_do_clock_config(0)
    except ValueError as exc:
        assert "Camera FPS must be greater than 0" in str(exc)
    else:
        raise AssertionError("Camera FPS=0 should be rejected before deriving DO clock")


def test_qt_ui_experiment_ad2_fields_seed_once_from_wfg(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    wfg_ch0 = window.wfg_channels[0]
    wfg_ch1 = window.wfg_channels[1]
    wfg_ch0["frequency"].setValue(1234.0)
    wfg_ch0["amplitude"].setValue(0.25)
    wfg_ch0["offset"].setValue(0.5)
    wfg_ch0["function"].setCurrentText(qt_ui.WaveformFunction.SQUARE.value)
    wfg_ch0["enable"].setChecked(True)
    wfg_ch0["sec_wait"].setValue(0.2)
    wfg_ch0["sec_run"].setValue(0.3)
    wfg_ch0["repeat"].setValue(4)
    wfg_ch0["trigger_source"].setCurrentText("trigsrcPC")
    wfg_ch1["frequency"].setValue(5678.0)
    wfg_ch1["amplitude"].setValue(0.75)
    wfg_ch1["enable"].setChecked(False)

    window._seed_experiment_ad2_from_wfg_once()

    assert window.exp_ch1_freq.value() == 1234.0
    assert window.exp_ch1_amp.value() == 0.25
    assert window.exp_ch1_offset.value() == 0.5
    assert window.exp_ch1_function.currentText() == qt_ui.WaveformFunction.SQUARE.value
    assert window.exp_ch1_enable.isChecked() is True
    assert window.exp_ch1_start.value() == 0.2
    assert window.exp_ch1_run.value() == 0.3
    assert window.exp_ch1_repeat.value() == 4
    assert window.exp_ch1_trigger_source.currentText() == "trigsrcPC"
    assert window.exp_ch2_freq.value() == 5678.0
    assert window.exp_ch2_amp.value() == 0.75
    assert window.exp_ch2_enable.isChecked() is False

    wfg_ch0["frequency"].setValue(9999.0)
    window._seed_experiment_ad2_from_wfg_once()

    assert window.exp_ch1_freq.value() == 1234.0


def test_qt_ui_experiment_wfg_config_uses_only_experiment_ad2_fields(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window._experiment_ad2_seeded = True
    window.wfg_running.setChecked(False)
    window.wfg_sync.setCurrentText("Synchronized")
    for channel in window.wfg_channels:
        channel["frequency"].setValue(99_999.0)
        channel["amplitude"].setValue(9.9)
        channel["offset"].setValue(9.9)
        channel["function"].setCurrentText(qt_ui.WaveformFunction.DC.value)
        channel["enable"].setChecked(False)
        channel["sec_wait"].setValue(9.9)
        channel["sec_run"].setValue(9.9)
        channel["repeat"].setValue(99)
        channel["repeat_trigger"].setChecked(True)
        channel["trigger_source"].setCurrentText("trigsrcAnalogIn")
        channel["symmetry"].setValue(10.0)
        channel["phase"].setValue(90.0)
        channel["fm_enable"].setChecked(True)

    window.exp_ch1_enable.setChecked(True)
    window.exp_ch1_function.setCurrentText(qt_ui.WaveformFunction.SINE.value)
    window.exp_ch1_freq.setValue(1_975_000.0)
    window.exp_ch1_amp.setValue(2.0)
    window.exp_ch1_offset.setValue(0.0)
    window.exp_ch1_start.setValue(0.1)
    window.exp_ch1_run.setValue(0.5)
    window.exp_ch1_repeat.setValue(1)
    window.exp_ch1_trigger_source.setCurrentText("trigsrcPC")
    window.exp_ch2_enable.setChecked(False)
    window.exp_ch2_function.setCurrentText(qt_ui.WaveformFunction.SQUARE.value)
    window.exp_ch2_freq.setValue(1000.0)
    window.exp_ch2_amp.setValue(0.1)
    window.exp_ch2_offset.setValue(0.2)
    window.exp_ch2_start.setValue(0.3)
    window.exp_ch2_run.setValue(0.4)
    window.exp_ch2_repeat.setValue(2)
    window.exp_ch2_trigger_source.setCurrentText("trigsrcNone")

    config = window._experiment_wfg_config()

    assert config.running is True
    assert config.synchronize_state == "Independent"
    assert config.channels[0].carrier.frequency_hz == 1_975_000.0
    assert config.channels[0].carrier.amplitude_v == 2.0
    assert config.channels[0].carrier.offset_v == 0.0
    assert config.channels[0].carrier.function == qt_ui.WaveformFunction.SINE
    assert config.channels[0].carrier.enable is True
    assert config.channels[0].carrier.symmetry_percent == 50.0
    assert config.channels[0].carrier.phase_deg == 0.0
    assert config.channels[0].trigger.sec_wait == 0.1
    assert config.channels[0].trigger.sec_run == 0.5
    assert config.channels[0].trigger.repeat_count == 1
    assert config.channels[0].trigger.repeat_trigger is False
    assert config.channels[0].trigger.source == "trigsrcPC"
    assert config.channels[0].fm_mod.enable is False
    assert config.channels[1].carrier.frequency_hz == 1000.0
    assert config.channels[1].carrier.amplitude_v == 0.1
    assert config.channels[1].carrier.offset_v == 0.2
    assert config.channels[1].carrier.function == qt_ui.WaveformFunction.SQUARE
    assert config.channels[1].carrier.enable is False
    assert config.channels[1].trigger.sec_wait == 0.3
    assert config.channels[1].trigger.sec_run == 0.4
    assert config.channels[1].trigger.repeat_count == 2
    assert config.channels[1].trigger.source == "trigsrcNone"
    assert config.channels[1].fm_mod.enable is False


def test_camera_sequence_settings_use_confirmed_dcam_options(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    assert combo_items(window.sequence_mode) == ["Continuous", "Start (single)", "Burst"]
    assert combo_items(window.sequence_source) == ["External", "Software"]
    assert combo_items(window.dcam_source) == ["Internal", "External", "Software", "MasterPulse"]
    assert combo_items(window.external_polarity) == ["Negative", "Positive"]
    assert window.sequence_burst.minimum() == 1
    assert window.sequence_burst.maximum() == 65535
    assert window.sequence_burst.value() == 1
    assert window.sequence_interval.minimum() == 0.000005
    assert window.sequence_interval.maximum() == 10.0
    assert window.external_delay.maximum() == 10.000002


def test_camera_sequence_settings_are_passed_to_manual_configure(monkeypatch, tmp_path):
    class FakeCamera:
        def __init__(self) -> None:
            self.calls = []

        def configure_exposure_time(self, exposure_ms: float) -> None:
            self.calls.append(("configure_exposure_time", exposure_ms))

        def configure_roi(self, roi: SubRegion) -> None:
            self.calls.append(("configure_roi", roi))

        def configure_sequence(self, settings: dict[str, object] | None) -> None:
            self.calls.append(("configure_sequence", settings))

        def center_roi(self) -> None:
            self.calls.append(("center_roi",))

    window = make_window(monkeypatch, tmp_path)
    fake_camera = FakeCamera()
    window.app.camera = fake_camera
    window.sequence_mode.setCurrentText("Burst")
    window.sequence_source.setCurrentText("Software")
    window.sequence_interval.setValue(0.125)
    window.sequence_burst.setValue(3)
    window.sequence_frames.setValue(7)
    window.dcam_source.setCurrentText("MasterPulse")
    window.external_polarity.setCurrentText("Positive")
    window.external_delay.setValue(0.25)

    settings = window._camera_sequence_settings()

    assert settings == {
        "masterpulse_mode": "Burst",
        "masterpulse_source": "Software",
        "masterpulse_interval_s": 0.125,
        "masterpulse_burst_times": 3,
        "frames": 7,
        "trigger_source": "MasterPulse",
        "trigger_polarity": "Positive",
        "trigger_delay_s": 0.25,
    }
    assert "exposure_ms" not in settings
    assert "capture_mode" not in settings

    roi = SubRegion(horizontal_offset=1, vertical_offset=2, horizontal_size=3, vertical_size=4)
    result = window._configure_camera(roi, 12.5, False, settings)

    assert result == "Camera configured"
    assert fake_camera.calls == [
        ("configure_exposure_time", 12.5),
        ("configure_roi", roi),
        ("configure_sequence", settings),
    ]


def test_camera_preview_converts_16_bit_frame_to_display_image():
    QApplication.instance() or QApplication([])
    preview = qt_ui.ImagePreviewWindow()
    try:
        frame = np.array([[0, 32768], [65535, 65535]], dtype=np.uint16)

        image = preview._convert_to_display_image(frame, method="Full Dynamic", shifts=0)

        assert image.width() == 2
        assert image.height() == 2
        assert image.format() == image.Format.Format_Grayscale8
        assert preview._last_display_range == (0.0, 65535.0)
    finally:
        preview.close()


def test_camera_preview_conversion_modes():
    QApplication.instance() or QApplication([])
    preview = qt_ui.ImagePreviewWindow()
    try:
        frame = np.arange(100, dtype=np.uint16).reshape(10, 10)

        preview._convert_to_display_image(frame, method="90% Dynamic", shifts=0)

        assert preview._last_display_range == (5.0, 94.0)

        downshift = preview._convert_to_display_image(
            np.array([[0, 256, 512]], dtype=np.uint16),
            method="Downshift",
            shifts=8,
        )

        assert preview._last_display_range is None
        assert downshift.pixelColor(0, 0).value() == 0
        assert downshift.pixelColor(1, 0).value() == 1
        assert downshift.pixelColor(2, 0).value() == 2
    finally:
        preview.close()


def test_camera_conversion_policy_controls(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    assert combo_items(window.conversion_method) == ["Full Dynamic", "90% Dynamic", "Downshift"]
    assert window.conversion_method.currentText() == "Full Dynamic"
    assert window.conversion_min.isReadOnly()
    assert window.conversion_max.isReadOnly()
    assert window.conversion_min.isEnabled()
    assert window.conversion_max.isEnabled()
    assert not window.conversion_shifts.isEnabled()

    window.conversion_method.setCurrentText("Downshift")

    assert not window.conversion_min.isEnabled()
    assert not window.conversion_max.isEnabled()
    assert window.conversion_shifts.isEnabled()


def test_camera_capture_updates_preview_and_last_frame(monkeypatch, tmp_path):
    class FakeCamera:
        def __init__(self, frame) -> None:
            self.frame = frame

        def capture_snapshot(self):
            return self.frame

    window = make_window(monkeypatch, tmp_path)
    window.image_continuous.setChecked(False)
    frame = np.array([[10, 20], [30, 40]], dtype=np.uint16)
    window.app.camera = FakeCamera(frame)
    progress_events = []

    result = window._capture_camera_image(lambda kind, value: progress_events.append((kind, value)))
    window._ensure_camera_preview()
    window._handle_worker_progress("camera_image", frame)

    assert result is frame
    assert window._last_camera_image_data is not None
    assert window._last_camera_image_data[0] is frame
    assert len(progress_events) == 1
    assert progress_events[0][0] == "camera_image"
    assert progress_events[0][1] is frame
    assert window._camera_preview is not None
    pixmap = window._camera_preview.image_label.pixmap()
    assert pixmap is not None
    assert not pixmap.isNull()
    assert window.conversion_min.value() == 10.0
    assert window.conversion_max.value() == 40.0
    window._camera_preview.close()


def test_camera_adjust_reprocesses_last_raw_frame_without_recapture(monkeypatch, tmp_path):
    class FakeCamera:
        def __init__(self, frame) -> None:
            self.frame = frame
            self.capture_count = 0

        def capture_snapshot(self):
            self.capture_count += 1
            return self.frame

    window = make_window(monkeypatch, tmp_path)
    frame = np.array([[0, 256, 512]], dtype=np.uint16)
    fake_camera = FakeCamera(frame)
    window.app.camera = fake_camera

    captured = window._capture_camera_image()
    window._ensure_camera_preview()
    window._handle_worker_progress("camera_image", captured)
    window.conversion_method.setCurrentText("Downshift")
    window.conversion_shifts.setValue(8)
    window._adjust_camera_preview()

    assert fake_camera.capture_count == 1
    assert window._last_camera_image_data is not None
    assert window._last_camera_image_data[0] is frame
    assert window._camera_preview is not None
    assert window._camera_preview._last_display_range is None
    window._camera_preview.close()


def test_camera_adjust_without_prior_capture_reports_status(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    window._adjust_camera_preview()

    assert window.status.text() == "No image captured yet"
    assert window._camera_preview is None


def test_camera_preview_timer_starts_and_stops(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window._busy_count = 1

    window.image_continuous.setChecked(True)

    assert window._camera_preview is not None
    assert window._camera_preview_timer.isActive()

    window.image_continuous.setChecked(False)

    assert not window._camera_preview_timer.isActive()
    window._camera_preview.close()


def test_single_image_capture_does_not_start_continuous_timer(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    run_actions = []

    def fake_run_action(action, status):
        run_actions.append((action, status))

    window._run_action = fake_run_action

    window._start_capture_camera_image()

    assert window._camera_preview is not None
    assert run_actions and run_actions[0][1] == "Capturing image"
    assert not window._camera_preview_timer.isActive()
    window._camera_preview.close()


def test_closing_camera_preview_stops_continuous_and_late_callback_does_not_reopen(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window._busy_count = 1
    frame = np.array([[1, 2], [3, 4]], dtype=np.uint16)

    window.image_continuous.setChecked(True)

    assert window._camera_preview is not None
    assert window._camera_preview_active is True
    assert window._camera_preview_timer.isActive()

    window._camera_preview.close()

    assert window._camera_preview is None
    assert window._camera_preview_active is False
    assert not window._camera_preview_timer.isActive()
    assert window.image_continuous.isChecked() is False

    window._handle_worker_progress("camera_image", frame)
    window._handle_worker_progress("camera_capture_failed", "Capture failed")

    assert window._camera_preview is None
    assert not window._camera_preview_timer.isActive()


def test_abort_hardware_worker_starts_while_another_action_is_blocked(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    blocked_started = threading.Event()
    release_blocked = threading.Event()
    abort_stop_started = threading.Event()
    call_times: dict[str, float] = {}

    class AbortProbePump:
        def stop(self):
            call_times["pump_stop"] = time.perf_counter()
            abort_stop_started.set()

        def cleanup(self):
            pass

    class AbortProbeCamera:
        def stop_capture(self):
            call_times["camera_stop_capture"] = time.perf_counter()

        def cleanup(self):
            pass

    class AbortProbeAd2:
        def wfg_start_stop_all_ch(self, running):
            call_times["ad2_stop"] = time.perf_counter()
            assert running is False

        def cleanup(self):
            pass

    def blocked_action(progress):
        _ = progress
        blocked_started.set()
        release_blocked.wait(2.0)
        return "Blocked action released"

    try:
        window.app.pump = AbortProbePump()
        window.app.camera = AbortProbeCamera()
        window.app.ad2 = AbortProbeAd2()

        window._run_action(blocked_action, "Blocking action")
        assert blocked_started.wait(1.0)
        assert window._busy_count == 1

        clicked_at = time.perf_counter()
        window._abort()

        assert abort_stop_started.wait(0.5)
        assert call_times["pump_stop"] - clicked_at < 0.5
        assert "camera_stop_capture" in call_times
        assert "ad2_stop" in call_times

        release_blocked.set()
        assert process_events_until(lambda: window._busy_count == 0 and not window._threads, 2.0)
    finally:
        release_blocked.set()
        process_events_until(lambda: not window._threads, 2.0)
        window._cleanup_complete_for_close = True
        window.close()


def test_abort_stops_dcam_wait_and_releases_buffer_with_measured_elapsed_time(monkeypatch, tmp_path):
    from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend, HamamatsuDcamError

    window = make_window(monkeypatch, tmp_path)
    release_completed = threading.Event()
    capture_finished = threading.Event()
    capture_started = threading.Event()
    call_times: dict[str, float] = {}
    captured_errors: list[str] = []

    class TimeoutError:
        def is_timeout(self):
            return True

        def __str__(self):
            return "timeout"

    class BlockingDcamModule:
        class DCAM_IDPROP:
            pass

        class DCAMPROP:
            pass

        class Dcam:
            def __init__(self, index):
                _ = index
                self.opened = False

            def is_opened(self):
                return self.opened

            def dev_open(self):
                self.opened = True
                return True

            def dev_close(self):
                self.opened = False
                return True

            def lasterr(self):
                return TimeoutError()

            def buf_release(self):
                if call_times.get("abort_clicked") is not None and "buf_release_after_abort" not in call_times:
                    call_times["buf_release_after_abort"] = time.perf_counter()
                    release_completed.set()
                return True

            def buf_alloc(self, frames):
                _ = frames
                return True

            def cap_snapshot(self):
                capture_started.set()
                return True

            def cap_stop(self):
                call_times.setdefault("cap_stop", time.perf_counter())
                return True

            def wait_capevent_frameready(self, timeout):
                threading.Event().wait(timeout / 1000.0)
                return False

    class BlockingDcamApi:
        @classmethod
        def init(cls):
            return True

        @classmethod
        def uninit(cls):
            return True

        @classmethod
        def lasterr(cls):
            return "ok"

    backend = HamamatsuDcamBackend(timeout_ms=25, frame_total_timeout_s=1.0)
    backend.dcam_module = BlockingDcamModule
    backend.dcamapi = BlockingDcamApi

    class AbortCamera:
        def stop_capture(self):
            backend.stop_capture()

        def cleanup(self):
            backend.close()

    class NoopPump:
        def stop(self):
            pass

        def cleanup(self):
            pass

    class NoopAd2:
        def wfg_start_stop_all_ch(self, running):
            assert running is False

        def cleanup(self):
            pass

    def capture_action(progress):
        _ = progress
        try:
            backend.capture_snapshot()
        except HamamatsuDcamError as exc:
            captured_errors.append(str(exc))
        finally:
            call_times["capture_finished"] = time.perf_counter()
            capture_finished.set()
        return "Capture worker exited"

    try:
        window.app.camera = AbortCamera()
        window.app.pump = NoopPump()
        window.app.ad2 = NoopAd2()

        window._run_action(capture_action, "Blocking DCAM capture")
        assert capture_started.wait(1.0)

        call_times["abort_clicked"] = time.perf_counter()
        window._abort()

        assert release_completed.wait(0.5)
        assert capture_finished.wait(0.5)
        elapsed_s = max(call_times["buf_release_after_abort"], call_times["capture_finished"]) - call_times["abort_clicked"]
        print(f"ABORT_TO_DCAM_STOPPED_AND_RELEASED_S={elapsed_s:.6f}")

        assert elapsed_s < 0.5
        assert any("Capture stopped while waiting for Hamamatsu frame" in error for error in captured_errors)
        assert call_times["cap_stop"] >= call_times["abort_clicked"]
        assert call_times["buf_release_after_abort"] >= call_times["cap_stop"]

        assert process_events_until(lambda: window._busy_count == 0 and not window._threads, 2.0)
    finally:
        process_events_until(lambda: not window._threads, 2.0)
        window._cleanup_complete_for_close = True
        window.close()


def test_shown_then_hidden_window_still_uses_async_cleanup_path(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    shutdown_calls = []

    def record_shutdown(*, close_after):
        shutdown_calls.append(close_after)

    try:
        window.show()
        QApplication.processEvents()
        window.hide()
        QApplication.processEvents()
        window._start_shutdown = record_shutdown

        window.close()

        assert window._window_was_shown is True
        assert shutdown_calls == [True]
    finally:
        window._cleanup_complete_for_close = True
        window.close()


def test_window_close_times_out_blocked_cleanup_without_freezing(monkeypatch, tmp_path):
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    cleanup_started = threading.Event()

    class BlockingCleanupApp(qt_ui.Application):
        def cleanup(self):
            cleanup_started.set()
            threading.Event().wait()

    window = qt_ui.MainWindow(app=BlockingCleanupApp())
    window._shutdown_timeout_s = 0.1
    window.show()
    QApplication.processEvents()

    window.close()

    assert cleanup_started.wait(1.0)
    assert process_events_until(lambda: not window.isVisible(), timeout_s=1.0)
    assert any("Shutdown timed out" in str(error) for error in window.app.errors)
    assert settings_path.exists()


def test_run_experiment_series_stops_after_failed_repeat(monkeypatch, tmp_path, caplog):
    from thermo_acoustic.workflows import Experiment2, ExperimentSeries2

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])

    call_count = {"n": 0}

    class FailingRunApplication(qt_ui.Application):
        def run_experiment2(self) -> bool:
            call_count["n"] += 1
            self.status = "ExperimentFlushFailed"
            return False

    window = qt_ui.MainWindow(app=FailingRunApplication())
    try:
        series = ExperimentSeries2(series_path=tmp_path)
        series.enqueue_experiments([Experiment2(), Experiment2()])
        config = window._experiment_wfg_config()

        with caplog.at_level("ERROR", logger="thermo_acoustic.qt_ui"):
            try:
                window._run_experiment_series(series, total_frames=1, config=config)
            except RuntimeError as exc:
                assert "repeat 1" in str(exc)
            else:
                raise AssertionError("expected RuntimeError when a repeat fails")

        assert call_count["n"] == 1
        assert any("repeat 1" in record.message for record in caplog.records)
    finally:
        window.close()
