from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import math
from time import monotonic

from ..application.commands import (
    DeviceOperation,
    NoArguments,
    PumpConfigurationResult,
    PumpConfigureFlowUnitArgs,
    PumpConfigureSyringeArgs,
    PumpFillLevelResult,
    PumpFlowUnit,
    PumpRecoveryResult,
    PumpMoveArgs,
    PumpMovementResult,
    PumpReferenceMoveArgs,
    PumpSetFillLevelArgs,
    PumpSetFlowArgs,
    PumpStatusResult,
)
from ..domain.models import DeviceId, PumpReadback
from .base import DeferredProgress, DeviceWorker


class PumpWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.PUMP, device_factory, readback_factory=PumpReadback, parent=parent)
        self.register(DeviceOperation.PUMP_FLOW_SET, self.set_flow)
        self.register(DeviceOperation.PUMP_FLOW_STOP, self.stop_flow)
        self.register(DeviceOperation.PUMP_FILL_LEVEL_READ, self.read_fill_level)
        self.register(DeviceOperation.PUMP_STATUS_READ, self.read_status)
        self.register(DeviceOperation.PUMP_FILL_LEVEL_SET, self.set_fill_level)
        self.register(DeviceOperation.PUMP_SYRINGE_CONFIGURE, self.configure_syringe)
        self.register(DeviceOperation.PUMP_FLOW_UNIT_CONFIGURE, self.configure_flow_unit)
        self.register(DeviceOperation.PUMP_FAULT_RECOVER, self.recover_fault)
        self.register(DeviceOperation.PUMP_REFILL, self.refill)
        self.register(DeviceOperation.PUMP_EMPTY, self.empty)
        self.register(DeviceOperation.PUMP_REFERENCE_MOVE, self.reference_move)

    def set_flow(self, args: PumpSetFlowArgs) -> None:
        self.device.generate_flow(args.flow_ul_min)
        self.state.active = args.flow_ul_min != 0
        self.state.readback = replace(
            self.state.readback,
            requested_flow_ul_min=args.flow_ul_min,
            is_pumping=self.state.active,
        )

    def stop_flow(self, _args: NoArguments) -> None:
        self.safe_stop()

    def read_fill_level(self, _args: NoArguments) -> PumpFillLevelResult:
        result = PumpFillLevelResult(float(self.device.read_fill_level()))
        self.state.readback = replace(self.state.readback, fill_level_ml=result.fill_level_ml)
        return result

    def read_status(self, _args: NoArguments) -> PumpStatusResult:
        result = PumpStatusResult(bool(self.device.read_status()))
        self.state.active = result.is_pumping
        self.state.readback = replace(self.state.readback, is_pumping=result.is_pumping)
        return result

    def set_fill_level(self, args: PumpSetFillLevelArgs) -> None:
        if not math.isfinite(args.fill_level_ml):
            raise ValueError("fill_level_ml must be finite")
        maximum = getattr(self.device, "max_volume_ml", None)
        if args.fill_level_ml < 0 or (
            maximum is not None and args.fill_level_ml > float(maximum)
        ):
            raise ValueError(
                f"fill_level_ml must be within 0..{maximum} mL for the configured syringe"
            )
        self.device.set_fill_level(args.fill_level_ml, args.flow_rate_ul_min)
        self.state.active = True
        self.state.readback = replace(
            self.state.readback,
            requested_fill_level_ml=args.fill_level_ml,
            is_pumping=True,
        )

    def _configuration_result(
        self, flow_unit: PumpFlowUnit | None = None
    ) -> PumpConfigurationResult:
        return PumpConfigurationResult(
            flow_unit=flow_unit,
            max_volume_ml=getattr(self.device, "max_volume_ml", None),
            max_flow_rate_ul_min=getattr(self.device, "max_flow_rate_ul_min", None),
        )

    def configure_syringe(
        self, args: PumpConfigureSyringeArgs
    ) -> PumpConfigurationResult:
        if args.preset is None and (
            args.inner_diameter_mm is None or args.max_piston_stroke_mm is None
        ):
            raise ValueError("Choose a syringe preset or provide diameter and piston stroke")
        if args.preset is not None and (
            args.inner_diameter_mm is not None or args.max_piston_stroke_mm is not None
        ):
            raise ValueError("Choose either a syringe preset or custom geometry, not both")
        if args.preset is None and (
            args.inner_diameter_mm <= 0 or args.max_piston_stroke_mm <= 0
        ):
            raise ValueError("Custom syringe diameter and piston stroke must be positive")
        config = {
            "name": args.preset.value if args.preset is not None else None,
            "inner_diameter_mm": args.inner_diameter_mm,
            "max_piston_stroke_mm": args.max_piston_stroke_mm,
        }
        self.device.configure_syringe(config)
        result = self._configuration_result()
        self.state.configured = True
        self.state.readback = replace(
            self.state.readback,
            syringe_name=args.preset.value if args.preset is not None else None,
            syringe_inner_diameter_mm=args.inner_diameter_mm,
            syringe_max_piston_stroke_mm=args.max_piston_stroke_mm,
            max_volume_ml=result.max_volume_ml,
            max_flow_rate_ul_min=result.max_flow_rate_ul_min,
        )
        return result

    def configure_flow_unit(
        self, args: PumpConfigureFlowUnitArgs
    ) -> PumpConfigurationResult:
        self.device.configure_flow_unit(args.unit.value)
        result = self._configuration_result(args.unit)
        self.state.readback = replace(
            self.state.readback,
            flow_unit=args.unit.value,
            max_flow_rate_ul_min=result.max_flow_rate_ul_min,
        )
        return result

    def recover_fault(self, _args: NoArguments) -> PumpRecoveryResult:
        try:
            self.device.clear_fault_and_reinitialize()
        except Exception:
            self.state.readback = replace(
                self.state.readback, last_recovery_succeeded=False
            )
            raise
        self.state.active = False
        self.state.readback = replace(
            self.state.readback,
            requested_flow_ul_min=0.0,
            is_pumping=False,
            last_recovery_succeeded=True,
        )
        return PumpRecoveryResult(True)

    def _defer_fill_movement(
        self, movement: str, args: PumpMoveArgs
    ) -> object:
        if movement == "refill":
            self.device.refill(args.flow_rate_ul_min)
            target_fill_level = float(self.device.max_volume_ml)
        else:
            self.device.empty(args.flow_rate_ul_min)
            target_fill_level = 0.0
        deadline = monotonic() + args.timeout_s
        self.state.active = True
        self.state.readback = replace(
            self.state.readback, is_pumping=True, movement=movement
        )

        def cancel() -> None:
            self.safe_stop()
            self.state.readback = replace(self.state.readback, movement=None)

        def step() -> DeferredProgress:
            pumping = bool(self.device.read_status())
            self.state.active = pumping
            self.state.readback = replace(self.state.readback, is_pumping=pumping)
            fill_level = float(self.device.read_fill_level())
            if pumping or not math.isclose(
                fill_level, target_fill_level, rel_tol=1e-6, abs_tol=1e-9
            ):
                if monotonic() >= deadline:
                    raise TimeoutError(
                        f"Pump {movement} timed out after {args.timeout_s:.3f}s "
                        f"at {fill_level:.6g} mL"
                    )
                return DeferredProgress()
            self.state.readback = replace(
                self.state.readback,
                fill_level_ml=fill_level,
                requested_fill_level_ml=fill_level,
                movement=None,
            )
            return DeferredProgress(True, PumpMovementResult(fill_level_ml=fill_level))

        return self.defer_operation(
            step, cancel=cancel, poll_interval_s=args.poll_interval_s
        )

    def refill(self, args: PumpMoveArgs) -> object:
        return self._defer_fill_movement("refill", args)

    def empty(self, args: PumpMoveArgs) -> object:
        return self._defer_fill_movement("empty", args)

    def reference_move(self, args: PumpReferenceMoveArgs) -> object:
        self.device.start_reference_move()
        deadline = monotonic() + args.timeout_s
        self.state.active = True
        self.state.readback = replace(self.state.readback, movement="reference")

        def cancel() -> None:
            self.safe_stop()
            self.state.readback = replace(self.state.readback, movement=None)

        def step() -> DeferredProgress:
            if self.device.reference_move_finished():
                self.state.active = False
                self.state.readback = replace(
                    self.state.readback, movement=None, referenced=True
                )
                return DeferredProgress(True, PumpMovementResult(referenced=True))
            if monotonic() >= deadline:
                raise TimeoutError(
                    f"Pump reference movement timed out after {args.timeout_s:.3f}s"
                )
            return DeferredProgress()

        return self.defer_operation(
            step, cancel=cancel, poll_interval_s=args.poll_interval_s
        )

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self.device.stop()
        self.state.active = False
        self.state.readback = replace(
            self.state.readback,
            requested_flow_ul_min=0.0,
            is_pumping=False,
            movement=None,
        )
