from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import math
from time import monotonic

from ..application.commands import DeviceOperation, NoArguments, PumpConnectArgs, PumpConfigurationResult, PumpConfigureFlowUnitArgs, PumpConfigureSyringeArgs, PumpFillLevelResult, PumpFlowUnit, PumpMoveArgs, PumpMovementResult, PumpRecoveryResult, PumpReferenceMoveArgs, PumpSetFillLevelArgs, PumpSetFlowArgs, PumpStatusResult, PumpUnitArgs
from ..application.configuration import DEFAULT_PUMP_CONFIGURATION_DIR, validate_pump_configuration_dir
from ..domain.models import DeviceId, PumpReadback, PumpUnitReadback
from .base import DeferredProgress, DeviceWorker


class PumpWorker(DeviceWorker):
    """Serialize commands for the Qmix pump bank and publish per-unit readback."""
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.PUMP, device_factory, readback_factory=PumpReadback, poll_interval_s=0.5, parent=parent)
        for operation, handler in ((DeviceOperation.PUMP_FLOW_SET, self.set_flow), (DeviceOperation.PUMP_FLOW_STOP, self.stop_flow), (DeviceOperation.PUMP_FILL_LEVEL_READ, self.read_fill_level), (DeviceOperation.PUMP_STATUS_READ, self.read_status), (DeviceOperation.PUMP_FILL_LEVEL_SET, self.set_fill_level), (DeviceOperation.PUMP_SYRINGE_CONFIGURE, self.configure_syringe), (DeviceOperation.PUMP_FLOW_UNIT_CONFIGURE, self.configure_flow_unit), (DeviceOperation.PUMP_FAULT_RECOVER, self.recover_fault), (DeviceOperation.PUMP_REFILL, self.refill), (DeviceOperation.PUMP_EMPTY, self.empty), (DeviceOperation.PUMP_REFERENCE_MOVE, self.reference_move)):
            self.register(operation, handler)

    def _count(self) -> int: return int(getattr(self.device, "unit_count", 1))
    @staticmethod
    def _index(args: object) -> int: return getattr(args, "unit_index", 0)
    def _check(self, index: int) -> None:
        if not isinstance(index, int) or not 0 <= index < self._count(): raise ValueError(f"Pump unit must be within 1..{self._count()}")
    def _call(self, index: int, name: str, *args):
        self._check(index); method = getattr(self.device, name)
        return method(index, *args) if hasattr(self.device, "unit_count") else method(*args)
    def _unit(self, index: int, *, flow: float | None = None) -> PumpUnitReadback:
        self._check(index)
        previous = self.state.readback.units[index] if index < len(self.state.readback.units) else PumpUnitReadback(index)
        volume, maximum_flow = getattr(self.device, "max_volume_ml", None), getattr(self.device, "max_flow_rate_ul_min", None)
        if hasattr(self.device, "capabilities"): volume, maximum_flow = self.device.capabilities(index)
        return replace(previous, max_volume_ml=volume, max_flow_rate_ul_min=maximum_flow, current_flow_ul_min=previous.current_flow_ul_min if flow is None else flow)
    def _replace_unit(self, unit: PumpUnitReadback) -> None:
        units = list(self.state.readback.units)
        while len(units) <= unit.unit_index: units.append(PumpUnitReadback(len(units)))
        units[unit.unit_index] = unit
        self.state.readback = replace(self.state.readback, units=tuple(units), fill_level_ml=units[0].fill_level_ml if units else None, max_volume_ml=units[0].max_volume_ml if units else None, max_flow_rate_ul_min=units[0].max_flow_rate_ul_min if units else None)
        self.state.active = any(item.is_pumping for item in units)
    def _refresh(self) -> None:
        if not hasattr(self.device, "unit_count") and not (hasattr(self.device, "read_fill_level") and hasattr(self.device, "read_status")):
            return
        for index in range(self._count()):
            unit = self._unit(index)
            try:
                level = float(self._call(index, "read_fill_level"))
                pumping = bool(self._call(index, "read_status"))
                flow = float(self._call(index, "read_flow")) if hasattr(self.device, "read_flow") else (unit.current_flow_ul_min if pumping else 0.0)
                faulted = bool(self._call(index, "read_fault")) if hasattr(self.device, "read_fault") else None
                syringe = self._call(index, "read_syringe") if hasattr(self.device, "read_syringe") else None
                self._replace_unit(replace(unit, fill_level_ml=level, is_pumping=pumping,
                    current_flow_ul_min=flow, is_faulted=faulted,
                    syringe_inner_diameter_mm=syringe[0] if syringe else unit.syringe_inner_diameter_mm,
                    syringe_max_piston_stroke_mm=syringe[1] if syringe else unit.syringe_max_piston_stroke_mm))
            except Exception:
                self._replace_unit(replace(unit, is_faulted=True))
                raise
    def prepare_connection(self, device: object, arguments: object) -> None:
        selected = arguments.configuration_dir if isinstance(arguments, PumpConnectArgs) else DEFAULT_PUMP_CONFIGURATION_DIR
        path = validate_pump_configuration_dir(selected)
        configure = getattr(device, "set_configuration_path", None)
        if callable(configure):
            configure(path)

    def connect_device(self, arguments: object = NoArguments()) -> None:
        super().connect_device(arguments); self._refresh()
    def poll_once(self) -> None:
        if self.state.connected and not self.state.busy:
            try: self._refresh()
            except Exception as exc: self.state.fault = str(exc)
            self._emit_status()
    def set_flow(self, args: PumpSetFlowArgs) -> None:
        unit = self._unit(args.unit_index)
        if not math.isfinite(args.flow_ul_min) or unit.max_flow_rate_ul_min is None or abs(args.flow_ul_min) > unit.max_flow_rate_ul_min:
            raise ValueError(f"flow_ul_min must be within +/-{unit.max_flow_rate_ul_min} µL/min")
        self._call(args.unit_index, "generate_flow", args.flow_ul_min)
    def stop_flow(self, args: PumpUnitArgs) -> None:
        index = self._index(args); self._call(index, "stop"); self._replace_unit(replace(self._unit(index, flow=0.0), is_pumping=False))
    def read_fill_level(self, args: PumpUnitArgs) -> PumpFillLevelResult:
        index = self._index(args); level = float(self._call(index, "read_fill_level")); self._replace_unit(replace(self._unit(index), fill_level_ml=level)); return PumpFillLevelResult(level)
    def read_status(self, args: PumpUnitArgs) -> PumpStatusResult:
        index = self._index(args); pumping = bool(self._call(index, "read_status")); current = self._unit(index); self._replace_unit(replace(current, is_pumping=pumping, current_flow_ul_min=current.current_flow_ul_min if pumping else 0.0)); return PumpStatusResult(pumping)
    def set_fill_level(self, args: PumpSetFillLevelArgs) -> None:
        unit = self._unit(args.unit_index)
        if unit.max_volume_ml is None or not math.isfinite(args.fill_level_ml) or not 0 <= args.fill_level_ml <= unit.max_volume_ml:
            raise ValueError(f"fill_level_ml must be within 0..{unit.max_volume_ml} mL for the configured syringe")
        if args.flow_rate_ul_min is not None and (not math.isfinite(args.flow_rate_ul_min) or args.flow_rate_ul_min <= 0 or unit.max_flow_rate_ul_min is None or args.flow_rate_ul_min > unit.max_flow_rate_ul_min):
            raise ValueError(f"flow_rate_ul_min must be within 0..{unit.max_flow_rate_ul_min} µL/min")
        self._call(args.unit_index, "set_fill_level", args.fill_level_ml, args.flow_rate_ul_min)
    def configure_syringe(self, args: PumpConfigureSyringeArgs) -> PumpConfigurationResult:
        if args.preset is None and (args.inner_diameter_mm is None or args.max_piston_stroke_mm is None): raise ValueError("Choose a syringe preset or provide diameter and piston stroke")
        config = {"name": args.preset.value if args.preset else None, "inner_diameter_mm": args.inner_diameter_mm, "max_piston_stroke_mm": args.max_piston_stroke_mm}
        self._call(args.unit_index, "configure_syringe", config); unit = replace(self._unit(args.unit_index), syringe_name=config["name"]); self._replace_unit(unit); return PumpConfigurationResult(flow_unit=PumpFlowUnit.MICROLITRE_PER_MINUTE, max_volume_ml=unit.max_volume_ml, max_flow_rate_ul_min=unit.max_flow_rate_ul_min)
    def configure_flow_unit(self, args: PumpConfigureFlowUnitArgs) -> PumpConfigurationResult:
        if args.unit is not PumpFlowUnit.MICROLITRE_PER_MINUTE: raise ValueError("Pump flow units are fixed to ul/min")
        self._call(args.unit_index, "configure_flow_unit", PumpFlowUnit.MICROLITRE_PER_MINUTE.value)
        unit = self._unit(args.unit_index); self._replace_unit(unit)
        return PumpConfigurationResult(flow_unit=PumpFlowUnit.MICROLITRE_PER_MINUTE, max_volume_ml=unit.max_volume_ml, max_flow_rate_ul_min=unit.max_flow_rate_ul_min)
    def recover_fault(self, args: PumpUnitArgs) -> PumpRecoveryResult:
        if hasattr(self.device, "clear_fault_and_reinitialize"): self.device.clear_fault_and_reinitialize()
        else:
            self.device.cleanup(); self.device.initialize()
        self._refresh(); self.state.readback = replace(self.state.readback, last_recovery_succeeded=True); return PumpRecoveryResult(True)
    def _move(self, movement: str, args: PumpMoveArgs) -> object:
        unit = self._unit(args.unit_index)
        if unit.max_flow_rate_ul_min is None: raise RuntimeError("Pump maximum flow is unavailable")
        flow = abs(float(unit.max_flow_rate_ul_min)) / 2.0
        self._call(args.unit_index, movement, flow)
        # Completion means the SDK accepted the start command, not that the
        # syringe has reached its target. Ordinary polling reports progress.
        return PumpMovementResult()
    def refill(self, args: PumpMoveArgs) -> object: return self._move("refill", args)
    def empty(self, args: PumpMoveArgs) -> object: return self._move("empty", args)
    def reference_move(self, args: PumpReferenceMoveArgs) -> object:
        self._call(args.unit_index, "start_reference_move")
        deadline = monotonic() + args.timeout_s

        def step() -> DeferredProgress:
            if self._call(args.unit_index, "reference_move_finished"):
                return DeferredProgress(True, PumpMovementResult())
            if monotonic() >= deadline:
                raise TimeoutError(f"Pump {args.unit_index + 1} reference move timed out")
            return DeferredProgress()

        return self.defer_operation(
            step,
            cancel=lambda: self.stop_flow(PumpUnitArgs(args.unit_index)),
            poll_interval_s=args.poll_interval_s,
        )
    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            for index in range(self._count()): self._call(index, "stop")
            self._refresh()
