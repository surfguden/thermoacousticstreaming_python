from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from thermo_acoustic import piezo_zscan
from thermo_acoustic.piezo_zscan import ZScanCalibration, ZScanError, ZScanFrameResult


class FakePiezo:
    """Deliberately narrow: only implements the methods ZScanCalibration is
    supposed to call. Any accidental extra call (e.g. to a pump/valve/AD2
    method that doesn't belong on a piezo at all) raises AttributeError
    immediately -- this is what makes the "only piezo and camera are
    touched" boundary an enforced test failure, not just a comment. See
    test_scan_only_calls_piezo_and_camera_methods_no_other_hardware_touched."""

    def __init__(self, max_travel_um=450.0, mode="CloseLoop", start_position_um=0.0):
        self.max_travel_um = max_travel_um
        self.position_control_mode = mode
        self._position_um = start_position_um
        self.set_position_calls: list[float] = []
        self.switch_to_closed_loop_calls = 0
        self.fail_at_target_um: float | None = None
        # Simulates a small settling residual: measured position differs
        # slightly from the commanded target, confirming the filename uses
        # the real readback, not the nominal target.
        self.residual_um = 0.0

    def needs_closed_loop_confirmation(self) -> bool:
        return self.position_control_mode != "CloseLoop"

    def switch_to_closed_loop(self) -> None:
        self.switch_to_closed_loop_calls += 1
        self.position_control_mode = "CloseLoop"

    def set_position(self, target_um: float) -> float:
        self.set_position_calls.append(target_um)
        if self.fail_at_target_um is not None and target_um == self.fail_at_target_um:
            raise RuntimeError("simulated move failure")
        self._position_um = target_um + self.residual_um
        return self._position_um

    def get_position(self) -> float:
        return self._position_um


class FakeCamera:
    """Deliberately narrow -- see FakePiezo's docstring."""

    def __init__(self, fail_at_frame_index: int | None = None):
        self.configure_exposure_time_calls: list[float] = []
        self.capture_snapshot_calls = 0
        self.fail_at_frame_index = fail_at_frame_index

    def configure_exposure_time(self, exposure_ms: float) -> None:
        self.configure_exposure_time_calls.append(exposure_ms)

    def capture_snapshot(self):
        self.capture_snapshot_calls += 1
        if self.fail_at_frame_index is not None and self.capture_snapshot_calls == self.fail_at_frame_index:
            return None
        return np.zeros((4, 4), dtype=np.uint16)


def make_scan(piezo=None, camera=None, confirm=None, confirm_motion=lambda: True) -> tuple[ZScanCalibration, FakePiezo, FakeCamera]:
    piezo = piezo or FakePiezo()
    camera = camera or FakeCamera()
    scan = ZScanCalibration(
        piezo=piezo,
        camera=camera,
        confirm_closed_loop_switch=confirm,
        confirm_motion=confirm_motion,
    )
    return scan, piezo, camera


def test_scan_writes_expected_number_of_frames_with_correct_filenames(tmp_path, monkeypatch):
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    scan, piezo, camera = make_scan()

    results = scan.run(
        z_start_um=0.0, z_end_um=20.0, step_size_um=10.0,
        output_dir=tmp_path, exposure_ms=40.0,
    )

    assert len(results) == 3  # 0, 10, 20 -- inclusive of both endpoints
    assert [r.target_um for r in results] == [0.0, 10.0, 20.0]
    assert [r.measured_um for r in results] == [0.0, 10.0, 20.0]
    assert results[1].filename == "z_0010.00um.tif"
    for result in results:
        assert (tmp_path / result.filename).exists()


def test_filename_uses_real_measured_position_not_nominal_target(tmp_path, monkeypatch):
    # Explicit requirement: a settling residual must show up in the
    # filename, since it comes from get_position() (real readback), not
    # the value passed to set_position().
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    piezo = FakePiezo()
    piezo.residual_um = 0.3
    scan, _, _ = make_scan(piezo=piezo)

    results = scan.run(z_start_um=125.0, z_end_um=125.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    assert results[0].target_um == 125.0
    assert results[0].measured_um == pytest.approx(125.3)
    assert results[0].filename == "z_0125.30um.tif"


def test_exposure_configured_once_at_scan_start_not_per_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    scan, _, camera = make_scan()

    scan.run(z_start_um=0.0, z_end_um=20.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=33.5)

    assert camera.configure_exposure_time_calls == [33.5]


def test_settle_delay_is_fixed_and_configurable_not_hardcoded(tmp_path, monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: sleep_calls.append(s))
    scan, _, _ = make_scan()

    scan.run(
        z_start_um=0.0, z_end_um=10.0, step_size_um=10.0,
        output_dir=tmp_path, exposure_ms=40.0, settle_delay_ms=150.0,
    )

    assert sleep_calls == [0.15, 0.15]  # 2 positions, each a fixed 150ms/1000

    sleep_calls.clear()
    scan2, _, _ = make_scan()
    scan2.run(z_start_um=0.0, z_end_um=0.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)
    assert sleep_calls == [0.075]  # default 75ms


def test_non_integral_range_appends_exact_end_without_overshooting_requested_scan_interval():
    assert ZScanCalibration._build_targets(0.0, 15.0, 10.0) == [0.0, 10.0, 15.0]


def test_validation_rejects_bad_inputs(tmp_path):
    scan, _, _ = make_scan()
    with pytest.raises(ValueError, match="step_size_um"):
        scan.run(z_start_um=0.0, z_end_um=10.0, step_size_um=0.0, output_dir=tmp_path, exposure_ms=40.0)
    with pytest.raises(ValueError, match="z_end_um"):
        scan.run(z_start_um=10.0, z_end_um=0.0, step_size_um=1.0, output_dir=tmp_path, exposure_ms=40.0)
    with pytest.raises(ValueError, match="exposure_ms"):
        scan.run(z_start_um=0.0, z_end_um=10.0, step_size_um=1.0, output_dir=tmp_path, exposure_ms=0.0)
    with pytest.raises(ValueError, match="settle_delay_ms"):
        scan.run(z_start_um=0.0, z_end_um=10.0, step_size_um=1.0, output_dir=tmp_path, exposure_ms=40.0, settle_delay_ms=-1.0)


# -- Error handling: stop, don't skip, report position + completed count --

def test_move_failure_stops_scan_and_reports_position_and_completed_count(tmp_path, monkeypatch):
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    piezo = FakePiezo()
    piezo.fail_at_target_um = 20.0  # 3rd of 4 positions (0, 10, 20, 30)
    scan, _, _ = make_scan(piezo=piezo)

    with pytest.raises(ZScanError) as exc_info:
        scan.run(z_start_um=0.0, z_end_um=30.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    message = str(exc_info.value)
    assert "position 3/4" in message
    assert "2 of 4" in message
    assert "PARTIAL" in message
    # Only the 2 successful frames were written -- no silent skip/continue.
    assert len(list(tmp_path.glob("*.tif"))) == 2


def test_capture_failure_stops_scan_and_reports_position_and_completed_count(tmp_path, monkeypatch):
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    camera = FakeCamera(fail_at_frame_index=2)  # fails on the 2nd capture
    scan, _, _ = make_scan(camera=camera)

    with pytest.raises(ZScanError) as exc_info:
        scan.run(z_start_um=0.0, z_end_um=20.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    message = str(exc_info.value)
    assert "position 2/3" in message
    assert "1 of 3" in message
    assert len(list(tmp_path.glob("*.tif"))) == 1


# -- ClosedLoop confirmation pattern (Session 45/46 design decision) --

def test_already_closed_loop_never_invokes_confirmation_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)

    def confirm_should_never_be_called():
        raise AssertionError("confirm callback must not be invoked when already ClosedLoop")

    piezo = FakePiezo(mode="CloseLoop")
    scan, _, _ = make_scan(
        piezo=piezo,
        confirm=confirm_should_never_be_called,
        confirm_motion=lambda: True,
    )

    scan.run(z_start_um=0.0, z_end_um=0.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    assert piezo.switch_to_closed_loop_calls == 0


def test_closed_loop_still_requires_explicit_motion_authorization(tmp_path, monkeypatch):
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    piezo = FakePiezo(mode="CloseLoop")
    scan, _, camera = make_scan(piezo=piezo, confirm_motion=None)

    with pytest.raises(ZScanError, match="motion authorization"):
        scan.run(z_start_um=0.0, z_end_um=10.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    assert piezo.set_position_calls == []
    assert camera.configure_exposure_time_calls == []


def test_declined_motion_authorization_aborts_before_any_movement(tmp_path, monkeypatch):
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    piezo = FakePiezo(mode="CloseLoop")
    scan, _, _ = make_scan(piezo=piezo, confirm_motion=lambda: False)

    with pytest.raises(ZScanError, match="declined PPC001 motion authorization"):
        scan.run(z_start_um=0.0, z_end_um=10.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    assert piezo.set_position_calls == []


def test_open_loop_with_confirmed_switch_proceeds(tmp_path, monkeypatch):
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    piezo = FakePiezo(mode="OpenLoop")
    scan, _, _ = make_scan(piezo=piezo, confirm=lambda: True)

    results = scan.run(z_start_um=0.0, z_end_um=0.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    assert piezo.switch_to_closed_loop_calls == 1
    assert len(results) == 1


def test_open_loop_with_declined_switch_aborts_before_any_movement(tmp_path, monkeypatch):
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    piezo = FakePiezo(mode="OpenLoop")
    scan, _, _ = make_scan(piezo=piezo, confirm=lambda: False)

    with pytest.raises(ZScanError, match="declined"):
        scan.run(z_start_um=0.0, z_end_um=20.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    assert piezo.switch_to_closed_loop_calls == 0
    assert piezo.set_position_calls == []


def test_open_loop_with_no_confirmation_callback_refuses_to_proceed(tmp_path, monkeypatch):
    # PiezoStage/ZScanCalibration must never auto-switch -- no callback at
    # all means "fail safe", not "assume yes".
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    piezo = FakePiezo(mode="OpenLoop")
    scan, _, _ = make_scan(piezo=piezo, confirm=None)

    with pytest.raises(ZScanError, match="ClosedLoop"):
        scan.run(z_start_um=0.0, z_end_um=20.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    assert piezo.switch_to_closed_loop_calls == 0
    assert piezo.set_position_calls == []


# -- Cooperative abort (Phase 4 UI integration) --

def test_should_abort_stops_before_next_position_and_reports_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    scan, piezo, _ = make_scan()
    call_count = 0

    def should_abort() -> bool:
        nonlocal call_count
        call_count += 1
        return call_count > 2  # let the first 2 positions complete, then abort

    scan.should_abort = should_abort

    with pytest.raises(ZScanError) as exc_info:
        scan.run(z_start_um=0.0, z_end_um=30.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    message = str(exc_info.value)
    assert "position 3/4" in message
    assert "2 of 4" in message
    assert "PARTIAL" in message
    assert len(list(tmp_path.glob("*.tif"))) == 2
    # The aborted position itself never reached the piezo/camera at all.
    assert piezo.set_position_calls == [0.0, 10.0]


def test_should_abort_none_never_checked_scan_runs_to_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    scan, _, _ = make_scan()
    assert scan.should_abort is None

    results = scan.run(z_start_um=0.0, z_end_um=20.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    assert len(results) == 3


# -- Boundary: pump/valve/AD2/laser are never touched --

def test_module_never_imports_other_hardware_classes():
    source = Path(piezo_zscan.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name.split(".")[0] for alias in node.names)
    forbidden = {"Valve", "CetoniPump", "QmixPumpBackend", "AD2Sdk", "WaveFormsBackend", "PriorZMotor", "Application"}
    overlap = imported_names & forbidden
    assert not overlap, f"piezo_zscan.py must never import other hardware classes, found: {overlap}"


def test_scan_only_calls_piezo_and_camera_methods_no_other_hardware_touched(tmp_path, monkeypatch):
    # FakePiezo/FakeCamera above are deliberately narrow -- they implement
    # *only* the methods ZScanCalibration is supposed to call. A full,
    # multi-position scan (including the ClosedLoop-switch path) completing
    # without an AttributeError is itself the enforcement: any accidental
    # call to a method that isn't piezo/camera-appropriate would fail this
    # test immediately, not silently pass.
    monkeypatch.setattr(piezo_zscan.time, "sleep", lambda s: None)
    piezo = FakePiezo(mode="OpenLoop")
    scan, _, camera = make_scan(piezo=piezo, confirm=lambda: True)

    results = scan.run(z_start_um=0.0, z_end_um=20.0, step_size_um=10.0, output_dir=tmp_path, exposure_ms=40.0)

    assert len(results) == 3
    assert camera.capture_snapshot_calls == 3


def test_manual_ppc001_probe_is_quarantined_and_not_a_pytest_test():
    repo_root = Path(__file__).resolve().parents[1]
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
    assert "hardware_tests/manual_ppc001_piezo_probe.py" in gitignore
    assert "hardware_tests/test_bpc_piezo_probe.py" not in gitignore

    probe = repo_root / "hardware_tests" / "manual_ppc001_piezo_probe.py"
    if not probe.exists():
        return
    assert not probe.name.startswith("test_")
    source = probe.read_text(encoding="utf-8")
    assert "Manual Thorlabs PPC001 Precision Piezo Controller probe" in source
    assert "BPC303 Benchtop Piezo Controller probe" not in source
    assert "historical" in source.lower()
    assert "--confirm SEND" in source


def test_legacy_action_capable_tools_are_explicitly_manual_only():
    repo_root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "tools/legacy_hamamatsu_camera_probe.py",
        "tools/legacy_qmix_pump_probe.py",
        "tools/capture_ad2_wavegen_scope.py",
        "tools/capture_ad2_wavegen_scope_matplotlib.py",
    ):
        source = (repo_root / relative_path).read_text(encoding="utf-8")
        assert "manual" in source.lower()
        assert "__test__ = False" in source
