from __future__ import annotations

import queue
from dataclasses import dataclass, field
from pathlib import Path
import sys
import threading
import time
from typing import Any


class QmixPumpError(RuntimeError):
    pass


def _default_sdk_python_path() -> Path:
    return Path(__file__).resolve().parents[2] / "qmix_sdk_for_codex" / "python"


def _syringe_stroke_mm(volume_ml: float, inner_diameter_mm: float) -> float:
    area_mm2 = 3.141592653589793 * (inner_diameter_mm / 2.0) ** 2
    return volume_ml * 1000.0 / area_mm2


SYRINGE_PRESETS: dict[str, tuple[float, float]] = {
    # Inner diameters are BD syringe spec values (confirmed authoritative:
    # 1mL=4.78mm, 5mL=12.07mm, 10mL=14.5mm) -- Chemyx BD Plastic Syringe
    # reference table (chemyx.com), cross-checked against BD REF
    # 309628/309649/300912 packaging (no provenance for these three values
    # was ever recorded in this repo's own history prior to Session 51;
    # `git log -p` on this file shows only "confirmed authoritative" with
    # no external citation, back to the syringe feature's original
    # introduction -- added now, not re-deriving anything). Stroke length is
    # not an independently-sourced BD spec value -- it is derived here
    # assuming the full nominal volume is delivered over the full piston
    # travel with a cylindrical bore (stroke = volume / cross-sectional
    # area). No authoritative real BD stroke-length figure was available to
    # verify this assumption against.
    "BD 1ml": (4.78, _syringe_stroke_mm(1.0, 4.78)),
    "BD 5ml": (12.07, _syringe_stroke_mm(5.0, 12.07)),
    "BD 10ml": (14.50, _syringe_stroke_mm(10.0, 14.50)),
}

# Conservative app-level hard bounds for Custom syringe geometry -- unlike
# max_flow_rate_ul_min/max_volume_ml (read back from the pump after
# set_syringe_param() below), there is no live device readback for
# inner_diameter_mm/max_piston_stroke_mm themselves, and CETONI's own SDK
# documentation does not state that pump firmware validates them against
# the syringe actually mounted. A wrong (too-large) value here could ask
# set_syringe_param()'s downstream volume/position math to drive the
# piston holder past its real physical travel.
#
# inner_diameter_mm: spans BD's full published 1mL-60mL product line
# (4.78mm-26.72mm, chemyx.com's BD syringe chart -- consistent with the
# three SYRINGE_PRESETS values above, which are the 1/5/10mL points on
# that same range), padded to [1.0, 35.0] for legitimate brand/size
# variation -- this also comfortably matches CETONI's own NEM-B101-02 E
# hardware manual (Section 5.1), which clamps syringe *outer* diameter to
# 6-30mm on this pump module; 35mm is used as this constant's own ceiling
# since inner diameter is always smaller than outer.
#
# max_piston_stroke_mm: NOT a BD-range-derived value (a prior version of
# this comment padded this module's own volume/diameter->stroke formula
# to [10.0, 200.0], which was wrong -- CETONI's Low Pressure Hardware
# Manual, Section 5.1, NEM-B101-02 E, states this specific pump module's
# absolute mechanical piston travel is "up to 65 mm", independent of
# whatever syringe is mounted; a configured stroke above that can command
# the pump past its own real mechanical limit regardless of the syringe's
# own barrel length, which is exactly the ATTENTION warning in that same
# manual section). 65.0 is a real hardware ceiling, not a padded
# BD-range estimate -- unlike inner_diameter_mm above, do not derive this
# bound from syringe presets/volume math.
MIN_SYRINGE_INNER_DIAMETER_MM = 1.0
MAX_SYRINGE_INNER_DIAMETER_MM = 35.0
MIN_SYRINGE_STROKE_MM = 10.0
MAX_SYRINGE_STROKE_MM = 65.0


@dataclass(slots=True)
class QmixPumpBackend:
    sdk_python_path: Path = field(default_factory=_default_sdk_python_path)
    pump_name: str | None = None
    pump_index: int = 0
    default_fill_flow_rate_ul_min: float | None = None
    reference_move_timeout_s: float = 60.0
    qmixbus: Any = None
    qmixpump: Any = None
    bus: Any = None
    pump: Any = None
    initialized: bool = False
    max_flow_rate_ul_min: float | None = None
    max_volume_ml: float | None = None
    close_timeout_s: float = 5.0

    def _load_sdk(self) -> None:
        if self.qmixbus is not None and self.qmixpump is not None:
            return
        path = str(self.sdk_python_path)
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            from qmixsdk import qmixbus, qmixpump
        except Exception as exc:
            raise QmixPumpError(
                f"Could not import Qmix SDK Python wrapper from {self.sdk_python_path}. "
                "Check that qmix_sdk_for_codex is present and that the Qmix/Cetoni SDK "
                "DLL folder is installed or available through the QMIXSDK environment variable."
            ) from exc
        self.qmixbus = qmixbus
        self.qmixpump = qmixpump

    def initialize(self, configuration_path: Path) -> None:
        self._load_sdk()
        self.bus = self.qmixbus.Bus()
        try:
            self.bus.open(str(configuration_path), 0)
            self.pump = self.qmixpump.Pump()
            if self.pump_name:
                self.pump.lookup_by_name(self.pump_name)
            else:
                self.pump.lookup_by_device_index(self.pump_index)
            self.bus.start()
            self._enable_pump()
            self.configure_flow_unit("ul/min")
            self.pump.set_volume_unit(self.qmixpump.UnitPrefix.milli, self.qmixpump.VolumeUnit.litres)
            self.max_flow_rate_ul_min = float(self.pump.get_flow_rate_max())
            self.max_volume_ml = float(self.pump.get_volume_max())
            self.initialized = True
        except Exception as exc:
            try:
                self.close()
            except Exception as rollback_exc:
                raise QmixPumpError(
                    f"Qmix initialization failed: {exc}; rollback close failed: {rollback_exc}"
                ) from exc
            raise

    def _require_pump(self) -> Any:
        if self.pump is None:
            raise QmixPumpError("Qmix pump is not initialized.")
        return self.pump

    def _enable_pump(self) -> None:
        pump = self._require_pump()
        if pump.is_in_fault_state():
            pump.clear_fault()
        if pump.is_in_fault_state():
            raise QmixPumpError("Qmix pump remains in fault state after clear_fault().")
        if not pump.is_enabled():
            pump.enable(True)

    def _fill_flow_rate(self) -> float:
        if self.default_fill_flow_rate_ul_min is not None:
            return self.default_fill_flow_rate_ul_min
        if self.max_flow_rate_ul_min is None:
            self.max_flow_rate_ul_min = float(self._require_pump().get_flow_rate_max())
        return self.max_flow_rate_ul_min

    def refill(self) -> None:
        pump = self._require_pump()
        max_volume = self.max_volume_ml if self.max_volume_ml is not None else float(pump.get_volume_max())
        self.max_volume_ml = max_volume
        pump.set_fill_level(max_volume, self._fill_flow_rate())

    def empty(self) -> None:
        self._require_pump().set_fill_level(0.0, self._fill_flow_rate())

    def stop(self) -> None:
        if self.pump is not None:
            self.pump.stop_pumping()

    def generate_flow(self, flow_rate: float) -> None:
        pump = self._require_pump()
        self._enable_pump()
        flow_rate = float(flow_rate)
        # Session 51: max_flow_rate_ul_min is already populated (initialize(),
        # configure_syringe(), configure_flow_unit() all read it back from the
        # pump) but was never actually compared against here before this --
        # LCP_GenerateFlow was called with whatever was requested,
        # unconditionally. abs() because a negative flow_rate means aspirate,
        # positive means dispense (generate_flow()'s own docstring) -- the
        # magnitude is what must not exceed the pump's own reported ceiling,
        # in either direction. None means the pump hasn't reported a real
        # ceiling yet (e.g. configure_syringe() never called) -- nothing to
        # validate against, so pass through unchanged, same as before.
        if self.max_flow_rate_ul_min is not None and abs(flow_rate) > self.max_flow_rate_ul_min:
            raise QmixPumpError(
                f"Requested flow_rate={flow_rate!r} exceeds the pump's own reported "
                f"max_flow_rate_ul_min={self.max_flow_rate_ul_min!r} -- rejected before reaching the pump SDK."
            )
        pump.generate_flow(flow_rate)

    def read_fill_level(self) -> float:
        return float(self._require_pump().get_fill_level())

    def set_fill_level(self, fill_level: float, flow_rate: float | None = None) -> None:
        # fill_level is always an absolute mL value -- no auto-detection against
        # a 0.0-1.0 fraction. That heuristic previously misread legitimate small
        # absolute values (e.g. 0.5 mL on a 5 mL syringe) as "50% of capacity".
        pump = self._require_pump()
        self._enable_pump()
        pump.set_fill_level(
            float(fill_level),
            self._fill_flow_rate() if flow_rate is None else float(flow_rate),
        )

    def configure_syringe(self, config: dict | None) -> None:
        if not config:
            return
        pump = self._require_pump()
        inner_diameter = (
            config.get("inner_diameter_mm")
            or config.get("diameter_mm")
            or config.get("innerDiameter")
            or config.get("diameter")
        )
        stroke = (
            config.get("max_piston_stroke_mm")
            or config.get("piston_stroke_mm")
            or config.get("stroke_mm")
            or config.get("stroke")
        )
        name = config.get("name")
        if (inner_diameter is None or stroke is None) and name in SYRINGE_PRESETS:
            inner_diameter, stroke = SYRINGE_PRESETS[str(name)]
        if inner_diameter is None or stroke is None:
            raise QmixPumpError(
                "Qmix syringe configuration requires inner_diameter_mm and "
                "max_piston_stroke_mm, or one of the known presets: "
                + ", ".join(SYRINGE_PRESETS)
            )
        inner_diameter = float(inner_diameter)
        stroke = float(stroke)
        if not (MIN_SYRINGE_INNER_DIAMETER_MM <= inner_diameter <= MAX_SYRINGE_INNER_DIAMETER_MM):
            raise QmixPumpError(
                f"Syringe inner_diameter_mm={inner_diameter!r} is outside the plausible range "
                f"[{MIN_SYRINGE_INNER_DIAMETER_MM}, {MAX_SYRINGE_INNER_DIAMETER_MM}] mm "
                "(spanning BD's full 1mL-60mL product line) -- rejected before reaching the pump SDK."
            )
        if not (MIN_SYRINGE_STROKE_MM <= stroke <= MAX_SYRINGE_STROKE_MM):
            raise QmixPumpError(
                f"Syringe max_piston_stroke_mm={stroke!r} is outside the plausible range "
                f"[{MIN_SYRINGE_STROKE_MM}, {MAX_SYRINGE_STROKE_MM}] mm "
                "(this pump module's own absolute mechanical piston travel is up to 65mm, "
                "CETONI Low Pressure Hardware Manual Section 5.1, NEM-B101-02 E) -- "
                "rejected before reaching the pump SDK."
            )
        pump.set_syringe_param(inner_diameter, stroke)
        self.max_flow_rate_ul_min = float(pump.get_flow_rate_max())
        self.max_volume_ml = float(pump.get_volume_max())

    def configure_flow_unit(self, unit: str | None) -> None:
        pump = self._require_pump()
        text = (unit or "ul/min").strip().lower().replace("µ", "u")
        prefix = self.qmixpump.UnitPrefix.micro
        time_unit = self.qmixpump.TimeUnit.per_minute
        if text in {"ml/min", "millilitre/min", "milliliter/min"}:
            prefix = self.qmixpump.UnitPrefix.milli
        elif text in {"ul/s", "uL/s".lower(), "microlitre/s", "microliter/s"}:
            time_unit = self.qmixpump.TimeUnit.per_second
        elif text in {"ml/s", "millilitre/s", "milliliter/s"}:
            prefix = self.qmixpump.UnitPrefix.milli
            time_unit = self.qmixpump.TimeUnit.per_second
        pump.set_flow_unit(prefix, self.qmixpump.VolumeUnit.litres, time_unit)
        self.max_flow_rate_ul_min = float(pump.get_flow_rate_max())

    def reference_move(self) -> None:
        pump = self._require_pump()
        self._enable_pump()
        pump.calibrate()
        deadline = time.monotonic() + max(self.reference_move_timeout_s, 0.0)
        while time.monotonic() < deadline:
            if pump.is_calibration_finished():
                return
            time.sleep(0.1)
        raise QmixPumpError("Qmix pump reference move timed out.")

    def read_status(self) -> bool:
        if self.pump is None:
            return False
        return bool(self.pump.is_pumping())

    def close(self) -> None:
        errors: list[str] = []
        errors.extend(self._run_close_step("pump stop", self.stop))
        if self.bus is not None:
            errors.extend(self._run_close_step("bus stop", self.bus.stop))
            errors.extend(self._run_close_step("bus close", self.bus.close))
        self.bus = None
        self.pump = None
        self.initialized = False
        if errors:
            raise QmixPumpError("; ".join(errors))

    def _run_close_step(self, name: str, action) -> list[str]:
        result_queue: queue.Queue[BaseException | None] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                action()
            except BaseException as exc:  # pragma: no cover - defensive SDK cleanup path
                result_queue.put(exc)
            else:
                result_queue.put(None)

        worker = threading.Thread(target=run, name=f"qmix-close-{name}", daemon=True)
        worker.start()
        worker.join(max(self.close_timeout_s, 0.0))
        if worker.is_alive():
            return [f"Qmix {name} timed out after {self.close_timeout_s:.1f}s."]
        try:
            error = result_queue.get_nowait()
        except queue.Empty:  # pragma: no cover - thread completed without reporting
            return [f"Qmix {name} finished without reporting a result."]
        if error is not None:
            return [f"Qmix {name} failed: {error}"]
        return []
