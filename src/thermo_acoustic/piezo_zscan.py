from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class ZScanError(RuntimeError):
    pass


@dataclass(slots=True)
class ZScanFrameResult:
    """Kept as structured data during the scan itself (not just embedded in
    the saved filename) so a metadata/manifest file could be added later
    without a rewrite -- per explicit instruction."""

    target_um: float
    measured_um: float
    filename: str


def _filename_for(measured_um: float) -> str:
    # z_XXXX.XXum.tif -- e.g. 125.3 -> "z_0125.30um.tif". Real closed-loop
    # readback, not the commanded target, so any small settling residual is
    # captured accurately in the filename itself (explicit requirement).
    return f"z_{measured_um:07.2f}um.tif"


@dataclass(slots=True)
class ZScanCalibration:
    """Standalone Z-scan calibration acquisition routine: drives a
    PiezoStage (thorlabs_piezo.py) and a camera object exposing the same
    capture_snapshot()/configure_exposure_time() interface HamamatsuCamera
    (instruments.py) already provides -- reuses that existing single-frame
    capture path directly, does not reinvent camera triggering.

    Explicit boundary (enforced by construction, not just documented): this
    class only ever calls methods on the `piezo` and `camera` objects it is
    given. It never imports or references Valve/CetoniPump/QmixPumpBackend/
    AD2Sdk/WaveFormsBackend/PriorZMotor -- whatever state those are in when
    a scan starts is left completely untouched. See
    tests/test_piezo_zscan.py's test_module_never_imports_other_hardware_
    classes (static import check) and test_scan_only_calls_piezo_and_camera_
    methods (a fake object exposing *only* the methods this class is
    supposed to call, so any accidental extra call fails loudly as an
    AttributeError) for the two independent checks that make this an
    enforced boundary rather than a comment.
    """

    piezo: Any
    camera: Any
    # Caller-supplied confirmation hook for the ClosedLoop-mode pattern
    # agreed in Session 45/46: PiezoStage.connect() only ever reads the
    # live mode, it never switches it. If the stage isn't already in
    # ClosedLoop, this callable is invoked (CLI: a y/n prompt; eventual UI:
    # a confirmation dialog) and must return True before this class will
    # call piezo.switch_to_closed_loop() itself. None means "never switch,
    # fail instead" -- the safe default for a routine that might be called
    # non-interactively.
    confirm_closed_loop_switch: Callable[[], bool] | None = None
    # ClosedLoop only establishes a position-control mode; it is never an
    # authorization to move hardware. Every scan must receive a separate,
    # affirmative motion authorization from its GUI or CLI caller. None is a
    # fail-closed default so direct/non-interactive use cannot move merely
    # because the controller was already in ClosedLoop.
    confirm_motion: Callable[[], bool] | None = None
    # Optional cooperative-abort hook (Phase 4 UI integration): checked once
    # per position, before that position's own move/settle/capture -- an
    # in-flight position always finishes once started, matching this
    # class's existing "stop, don't skip" partial-completion convention
    # (see the move/capture-failure handling below) rather than interrupting
    # a move/capture mid-flight. None (the default) means never abort.
    should_abort: Callable[[], bool] | None = None

    def run(
        self,
        z_start_um: float,
        z_end_um: float,
        step_size_um: float,
        output_dir: Path,
        exposure_ms: float,
        settle_delay_ms: float = 75.0,
    ) -> list[ZScanFrameResult]:
        if step_size_um <= 0:
            raise ValueError(f"step_size_um must be > 0, got {step_size_um}")
        if z_end_um < z_start_um:
            raise ValueError(f"z_end_um ({z_end_um}) must be >= z_start_um ({z_start_um})")
        if exposure_ms <= 0:
            raise ValueError(f"exposure_ms must be > 0, got {exposure_ms}")
        if settle_delay_ms < 0:
            raise ValueError(f"settle_delay_ms must be >= 0, got {settle_delay_ms}")

        self._ensure_closed_loop()
        self._ensure_motion_authorized()

        # Explicit exposure_ms parameter, applied here rather than trusting
        # whatever the camera happens to be pre-configured to -- a
        # calibration scan's capture conditions must be fully specified by
        # its own inputs, not external caller state (matches PiezoStage's
        # own explicit-parameter, no-hidden-state convention).
        self.camera.configure_exposure_time(exposure_ms)

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        targets = self._build_targets(z_start_um, z_end_um, step_size_um)
        results: list[ZScanFrameResult] = []

        for index, target_um in enumerate(targets):
            if self.should_abort is not None and self.should_abort():
                raise ZScanError(
                    f"Z-scan aborted at position {index + 1}/{len(targets)} "
                    f"(target={target_um:.2f} um). {len(results)} of {len(targets)} "
                    "positions completed successfully before this abort -- this is a "
                    "PARTIAL, incomplete stack, not silently treated as done."
                )
            try:
                results.append(self._acquire_one(target_um, output_dir, settle_delay_ms))
            except Exception as exc:
                raise ZScanError(
                    f"Z-scan stopped at position {index + 1}/{len(targets)} "
                    f"(target={target_um:.2f} um): {exc}. {len(results)} of {len(targets)} "
                    "positions completed successfully before this failure -- this is a "
                    "PARTIAL, incomplete stack, not silently treated as done."
                ) from exc

        return results

    def _acquire_one(self, target_um: float, output_dir: Path, settle_delay_ms: float) -> ZScanFrameResult:
        self.piezo.set_position(target_um)
        # Fixed settle delay, not a position-convergence check -- confirmed
        # design choice (Phase 3 instruction), deliberately not replaced
        # with threshold-based confirmation logic.
        time.sleep(settle_delay_ms / 1000.0)

        image = self.camera.capture_snapshot()
        if image is None:
            raise ZScanError(f"Camera capture failed at target {target_um:.2f} um.")

        # Real closed-loop readback, not the commanded target -- explicit
        # requirement, so filename-embedded Z reflects actual position.
        measured_um = self.piezo.get_position()
        filename = _filename_for(measured_um)

        from PIL import Image as PILImage

        PILImage.fromarray(image).save(output_dir / filename, format="TIFF")

        return ZScanFrameResult(target_um=target_um, measured_um=measured_um, filename=filename)

    @staticmethod
    def _build_targets(z_start_um: float, z_end_um: float, step_size_um: float) -> list[float]:
        # Include both requested endpoints without ever stepping past the
        # requested end. A partial final interval is preferable to moving the
        # piezo outside the operator-confirmed range.
        span = z_end_um - z_start_um
        n_full_steps = int(span // step_size_um)
        targets = [z_start_um + i * step_size_um for i in range(n_full_steps + 1)]
        if not targets or not math.isclose(targets[-1], z_end_um, rel_tol=0.0, abs_tol=1e-9):
            targets.append(z_end_um)
        return targets

    def _ensure_closed_loop(self) -> None:
        if not self.piezo.needs_closed_loop_confirmation():
            return
        if self.confirm_closed_loop_switch is None:
            raise ZScanError(
                f"Piezo stage is in {self.piezo.position_control_mode!r}, not ClosedLoop, and "
                "no confirmation callback was provided to authorize switching -- refusing to "
                "proceed without explicit confirmation."
            )
        if not self.confirm_closed_loop_switch():
            raise ZScanError("User declined to switch the piezo stage to ClosedLoop mode -- scan aborted.")
        self.piezo.switch_to_closed_loop()

    def _ensure_motion_authorized(self) -> None:
        if self.confirm_motion is None:
            raise ZScanError(
                "No explicit PPC001 motion authorization was provided -- refusing to start a Z-scan. "
                "ClosedLoop mode alone does not authorize piezo movement."
            )
        if not self.confirm_motion():
            raise ZScanError("User declined PPC001 motion authorization -- scan aborted before any movement.")


def _print_step(message: str) -> None:
    print(f"[piezo-zscan] {message}", flush=True)


def _cli_confirm_closed_loop(piezo: Any) -> bool:
    current_mode = piezo.position_control_mode
    print(
        f"Device is currently in {current_mode} mode. Z-scan requires ClosedLoop "
        "for position accuracy. Switch now? [y/n]"
    )
    answer = input("> ").strip().lower()
    return answer == "y"


def _cli_confirm_motion() -> bool:
    print("This will move the PPC001 piezo through the requested Z-scan range and capture images. Continue? [y/n]")
    answer = input("> ").strip().lower()
    return answer == "y"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standalone Z-scan calibration acquisition (piezo + camera only)")
    parser.add_argument("--z-start", type=float, required=True, help="Start Z position in um")
    parser.add_argument("--z-end", type=float, required=True, help="End Z position in um")
    parser.add_argument("--step-size", type=float, required=True, help="Step size in um")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory for TIFF frames")
    parser.add_argument("--exposure-ms", type=float, required=True, help="Camera exposure time in ms")
    parser.add_argument("--settle-delay-ms", type=float, default=75.0, help="Fixed post-move settle delay in ms (default: 75)")
    parser.add_argument("--serial", default="44533854", help="Piezo stage serial number (default: 44533854)")
    args = parser.parse_args(argv)

    from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend
    from thermo_acoustic.instruments import HamamatsuCamera
    from thermo_acoustic.thorlabs_piezo import PiezoStage

    piezo = PiezoStage(serial_number=args.serial)
    camera = HamamatsuCamera(backend=HamamatsuDcamBackend())

    _print_step(f"connecting to piezo stage {args.serial!r}...")
    piezo.connect()
    _print_step(
        f"connected. ChannelCount read, MaxTravel={piezo.max_travel_um}um, "
        f"PositionControlMode={piezo.position_control_mode}"
    )
    _print_step("initializing camera...")
    camera.initialize()
    _print_step("camera initialized.")

    scan = ZScanCalibration(
        piezo=piezo,
        camera=camera,
        confirm_closed_loop_switch=lambda: _cli_confirm_closed_loop(piezo),
        confirm_motion=_cli_confirm_motion,
    )

    try:
        results = scan.run(
            z_start_um=args.z_start,
            z_end_um=args.z_end,
            step_size_um=args.step_size,
            output_dir=args.output_dir,
            exposure_ms=args.exposure_ms,
            settle_delay_ms=args.settle_delay_ms,
        )
    except ZScanError as exc:
        _print_step(f"FAILED: {exc}")
        return 1
    finally:
        _print_step("disconnecting...")
        try:
            piezo.disconnect()
        except Exception as exc:  # pragma: no cover - defensive cleanup path
            _print_step(f"warning: piezo disconnect raised: {exc}")
        try:
            camera.cleanup()
        except Exception as exc:  # pragma: no cover - defensive cleanup path
            _print_step(f"warning: camera cleanup raised: {exc}")

    _print_step(f"scan complete: {len(results)} frames written to {args.output_dir}")
    for result in results:
        _print_step(f"  target={result.target_um:.2f}um measured={result.measured_um:.2f}um -> {result.filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
