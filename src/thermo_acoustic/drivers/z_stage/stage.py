from __future__ import annotations
from dataclasses import dataclass, field
from .thorlabs_piezo import PiezoStage

@dataclass(slots=True)
class ZStage:
    """Initialize-dialog-facing wrapper around the real Thorlabs piezo
    Z-stage (thorlabs_piezo.PiezoStage), matching the same enabled/
    initialize()/cleanup() shape every other HardwareBundle member already
    uses (HamamatsuCamera/CetoniPump/Valve each wrap a real SDK backend the
    same way) -- so the Initialize dialog's uniform per-instrument loop can
    treat the Z-stage like every other device. Reuses PiezoStage's own real
    connect()/disconnect() untouched; does not create a second, divergent
    connection path.

    Replaces the legacy PriorZMotor/COM7 path:
    PriorZMotor pointed the Initialize dialog's "Z-stage" checkbox at a
    serial port ('COM7') that never existed on this lab's hardware and was
    never actually the real piezo -- confirmed via real-hardware
    investigation, not assumed. z_stack()/go_to_abs_pos() (the only other
    PriorZMotor-specific API) had zero real callers anywhere in the live
    UI/experiment path (confirmed via a repo-wide search), so nothing else
    depended on that class either.
    """

    enabled: bool = False
    stage: PiezoStage = field(default_factory=PiezoStage)
    status_note: str = ""

    def initialize(self) -> None:
        self.status_note = ""
        if not self.enabled:
            return
        self.stage.connect()
        self.status_note = (
            f"serial={self.stage.serial_number}, max_travel_um={self.stage.max_travel_um}, "
            f"mode={self.stage.position_control_mode}"
        )

    def cleanup(self) -> None:
        if self.stage.connected:
            self.stage.disconnect()
        self.status_note = ""
