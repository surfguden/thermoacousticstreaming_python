from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class PiezoStageError(RuntimeError):
    pass


def _decimal_to_float(value: Any) -> float:
    # pythonnet's System.Decimal does not support float() directly --
    # confirmed against real hardware (Session 48): float(channel.
    # GetMaxTravel()) raised "TypeError: float() argument must be a string
    # or a real number, not 'Decimal'". Unlike Python's own stdlib
    # decimal.Decimal (which does implement __float__), System.Decimal only
    # gives a clean numeric string via str(), so that's the reliable path.
    return float(str(value))


DEFAULT_KINESIS_DIR = r"C:\Program Files\Thorlabs\Kinesis"
DEVICE_MANAGER_ASSEMBLY = "Thorlabs.MotionControl.DeviceManagerCLI"
BENCHTOP_PRECISION_PIEZO_ASSEMBLY = "ThorLabs.MotionControl.Benchtop.PrecisionPiezoCLI"

# Confirmed via .NET reflection against the real DLL (Session 45/46), not
# assumed -- the enum member is "CloseLoop", not "ClosedLoop".
CLOSED_LOOP_MODE_NAME = "CloseLoop"


@dataclass(slots=True)
class PiezoStage:
    """Driver wrapper for a Thorlabs PPC001 (1-Channel Precision Piezo
    Controller) via the Kinesis .NET API (pythonnet), confirmed against real
    hardware (Session 45) -- BenchtopPrecisionPiezo, not BenchtopPiezo (the
    BPC301/BPC303 class this device's serial/type ID does not match).

    Drives a single Thorlabs PFM450(E) Piezo Focusing Mount (closed-loop,
    strain-gauge position feedback) for objective Z-focus. MaxTravel/
    MaxOutputVoltage/MinOutputVoltage are read from the device at connect()
    time, never hardcoded, so this class stays correct if it's ever pointed
    at a different unit.

    Testability follows this project's existing SDK-backend pattern (see
    QmixPumpBackend in qmix_backend.py): device_manager_cli/
    benchtop_precision_piezo_cls/closed_loop_mode are injectable, so tests
    can supply fakes without pythonnet or real Kinesis DLLs installed.
    """

    serial_number: str = "44533854"
    channel_index: int = 1
    kinesis_dir: str = DEFAULT_KINESIS_DIR
    polling_interval_ms: int = 250
    settings_timeout_ms: int = 10000

    # Injectable for tests -- see module docstring. Left None in normal use;
    # _load_kinesis() lazily imports the real ones via pythonnet on first
    # connect().
    device_manager_cli: Any = None
    benchtop_precision_piezo_cls: Any = None
    closed_loop_mode: Any = None
    decimal_type: Any = None

    device: Any = None
    channel: Any = None
    connected: bool = False

    # Read from the device at connect() time -- never hardcoded (task
    # requirement), in case this ever runs against a different unit.
    max_travel_um: float | None = None
    max_output_voltage_v: float | None = None
    min_output_voltage_v: float | None = None
    position_control_mode: str | None = None

    def _load_kinesis(self) -> None:
        if (
            self.device_manager_cli is not None
            and self.benchtop_precision_piezo_cls is not None
            and self.decimal_type is not None
        ):
            return
        try:
            import clr
        except ImportError as exc:
            raise PiezoStageError(
                "pythonnet is not installed in this environment. Run: pip install pythonnet"
            ) from exc

        import sys

        if self.kinesis_dir not in sys.path:
            sys.path.append(self.kinesis_dir)
        try:
            clr.AddReference(DEVICE_MANAGER_ASSEMBLY)
            clr.AddReference(BENCHTOP_PRECISION_PIEZO_ASSEMBLY)
            from Thorlabs.MotionControl.Benchtop.PrecisionPiezoCLI import BenchtopPrecisionPiezo
            from Thorlabs.MotionControl.DeviceManagerCLI import DeviceManagerCLI
            from Thorlabs.MotionControl.GenericPiezoCLI.Piezo import PiezoControlModeTypes
            from System import Decimal
        except Exception as exc:
            raise PiezoStageError(
                f"Could not load Kinesis .NET assemblies from {self.kinesis_dir}: {exc}"
            ) from exc
        self.device_manager_cli = DeviceManagerCLI
        self.benchtop_precision_piezo_cls = BenchtopPrecisionPiezo
        self.closed_loop_mode = PiezoControlModeTypes.CloseLoop
        self.decimal_type = Decimal

    def connect(self) -> None:
        """Connect and read the device's own real limits/mode -- never
        switches PositionControlMode on its own (see needs_closed_loop_
        confirmation()/switch_to_closed_loop(), the explicit-confirmation
        pattern agreed in Session 45)."""
        if self.connected:
            return
        self._load_kinesis()

        self.device_manager_cli.BuildDeviceList()
        device = self.benchtop_precision_piezo_cls.CreateBenchtopPiezo(self.serial_number)
        try:
            device.Connect(self.serial_number)
        except Exception as exc:
            raise PiezoStageError(f"Failed to connect to piezo stage {self.serial_number!r}: {exc}") from exc

        try:
            channel = device.GetChannel(self.channel_index)
            channel.WaitForSettingsInitialized(self.settings_timeout_ms)
            channel.StartPolling(self.polling_interval_ms)

            self.device = device
            self.channel = channel
            self.connected = True

            self.max_travel_um = _decimal_to_float(channel.GetMaxTravel())
            self.max_output_voltage_v = _decimal_to_float(channel.GetMaxOutputVoltage())
            self.min_output_voltage_v = _decimal_to_float(channel.GetMinOutputVoltage())
            self.position_control_mode = str(channel.GetPositionControlMode())
        except Exception as exc:
            self.device = None
            self.channel = None
            self.connected = False
            try:
                device.ShutDown()
            except Exception:
                pass
            raise PiezoStageError(f"Failed to initialize piezo stage channel {self.channel_index}: {exc}") from exc

    def disconnect(self) -> None:
        errors: list[str] = []
        if self.channel is not None:
            try:
                self.channel.StopPolling()
            except Exception as exc:  # pragma: no cover - defensive SDK cleanup path
                errors.append(f"StopPolling: {exc}")
        if self.device is not None:
            try:
                self.device.ShutDown()
            except Exception as exc:  # pragma: no cover - defensive SDK cleanup path
                errors.append(f"ShutDown: {exc}")
        self.device = None
        self.channel = None
        self.connected = False
        if errors:
            raise PiezoStageError("; ".join(errors))

    def _require_connected(self) -> Any:
        if not self.connected or self.channel is None:
            raise PiezoStageError("PiezoStage is not connected.")
        return self.channel

    # -- ClosedLoop confirmation pattern (Session 45 design decision) --
    # connect() only ever reads PositionControlMode; it is never switched
    # automatically. Z-scan (or any other caller) must check
    # needs_closed_loop_confirmation() and, only after obtaining explicit
    # user acknowledgment, call switch_to_closed_loop() itself.

    def needs_closed_loop_confirmation(self) -> bool:
        self._require_connected()
        return self.position_control_mode != CLOSED_LOOP_MODE_NAME

    def switch_to_closed_loop(self) -> None:
        """Only call this after the caller has obtained explicit user
        confirmation -- PiezoStage itself never decides to switch modes."""
        channel = self._require_connected()
        try:
            channel.SetPositionControlMode(self.closed_loop_mode)
        except Exception as exc:
            raise PiezoStageError(f"Failed to switch piezo stage to ClosedLoop: {exc}") from exc
        self.position_control_mode = str(channel.GetPositionControlMode())

    def get_position(self) -> float:
        """Position in um. Only meaningful in ClosedLoop mode."""
        channel = self._require_connected()
        if self.position_control_mode != CLOSED_LOOP_MODE_NAME:
            raise PiezoStageError(
                f"PiezoStage is in {self.position_control_mode!r}, not ClosedLoop -- "
                "position readback is not meaningful until switch_to_closed_loop() is confirmed."
            )
        return _decimal_to_float(channel.GetPosition())

    def set_position(self, target_um: float) -> float:
        """Move to target_um, clamped to [0, max_travel_um] (soft limit
        against the device's own reported MaxTravel, read at connect() time
        -- never hardcoded). Returns the clamped value actually sent.
        Only valid in ClosedLoop mode."""
        channel = self._require_connected()
        if self.position_control_mode != CLOSED_LOOP_MODE_NAME:
            raise PiezoStageError(
                f"PiezoStage is in {self.position_control_mode!r}, not ClosedLoop -- "
                "set_position() requires switch_to_closed_loop() to be confirmed first."
            )
        if self.max_travel_um is None:
            raise PiezoStageError("MaxTravel was never read from the device -- cannot soft-limit a move.")
        clamped_um = max(0.0, min(float(target_um), self.max_travel_um))
        channel.SetPosition(self.decimal_type(clamped_um))
        return clamped_um
