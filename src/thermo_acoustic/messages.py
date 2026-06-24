from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class MessageName(str, Enum):
    INITIALIZE = "Initialize"
    CONFIGURE_CAMERA = "HamamatsuConfigure"
    CAMERA_CONFIGURED = "CameraConfigured"
    PUMP_INIT = "PumpInit"
    CETONI_REFILL = "CetoniRefill"
    CETONI_EMPTY = "CetoniEmpty"
    CETONI_STOP_DOSING = "CetoniStopDosing"
    CETONI_GENERATE_FLOW = "CetoniGenerateFlow"
    CETONI_SET_FILL_LEVEL = "CetoniSetFillLevel"
    VALVE_POS_1 = "ValvePos1"
    VALVE_POS_2 = "ValvePos2"
    FLUSH = "Flush"
    RUN_EXPERIMENT2 = "RunExperiment2"
    EXIT = "Exit"
    ABORT = "Abort"
    UPDATE_STATUS = "UpdateStatus"
    UPDATE_UI = "UpdateUI"
    STOP = "Stop"


@dataclass(slots=True)
class Message:
    name: MessageName | str
    data: Any = None
    priority: bool = False


@dataclass(slots=True)
class QueueResult:
    message: Message | None
    elements_remaining: int


@dataclass(slots=True)
class UiEvent:
    message: MessageName | str
    data: Any = None
