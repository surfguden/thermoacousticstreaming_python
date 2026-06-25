from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
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
    "BD 1ml": (4.78, _syringe_stroke_mm(1.0, 4.78)),
    "BD 5ml": (12.06, _syringe_stroke_mm(5.0, 12.06)),
    "BD 10ml": (14.50, _syringe_stroke_mm(10.0, 14.50)),
}


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

    def _coerce_fill_level_ml(self, fill_level: float) -> float:
        value = float(fill_level)
        if 0.0 <= value <= 1.0:
            if self.max_volume_ml is None:
                self.max_volume_ml = float(self._require_pump().get_volume_max())
            return value * self.max_volume_ml
        return value

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
        pump.generate_flow(float(flow_rate))

    def set_fill_level(self, fill_level: float) -> None:
        pump = self._require_pump()
        self._enable_pump()
        pump.set_fill_level(self._coerce_fill_level_ml(fill_level), self._fill_flow_rate())

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
        pump.set_syringe_param(float(inner_diameter), float(stroke))
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
        try:
            self.stop()
        finally:
            if self.bus is not None:
                try:
                    self.bus.stop()
                finally:
                    self.bus.close()
            self.bus = None
            self.pump = None
            self.initialized = False
