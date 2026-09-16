from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import math

from ..application.commands import (
    DeviceOperation,
    NoArguments,
    PumpConfigurationResult,
    PumpConfigureFlowUnitArgs,
    PumpConfigureSyringeArgs,
    PumpFillLevelResult,
    PumpFlowUnit,
    PumpRecoveryResult,
    PumpSetFillLevelArgs,
    PumpSetFlowArgs,
    PumpStatusResult,
)
from ..domain.models import DeviceId, PumpReadback
from .base import DeviceWorker


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

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self.device.stop()
        self.state.active = False
        self.state.readback = replace(
            self.state.readback, requested_flow_ul_min=0.0, is_pumping=False
        )
