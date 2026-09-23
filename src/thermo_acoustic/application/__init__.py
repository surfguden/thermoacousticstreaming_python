"""Single-process application services."""
from .audit import AuditLogger
from .commands import (
    CommandEvent,
    CommandResult,
    DeviceCommand,
    DeviceOperation,
    WorkflowCommand,
    WorkflowOperation,
)
from .configuration import ApplicationConfiguration

__all__ = [
    "ApplicationConfiguration",
    "ApplicationController",
    "AuditLogger",
    "CommandEvent",
    "CommandResult",
    "DeviceCommand",
    "DeviceOperation",
    "WorkflowCommand",
    "WorkflowOperation",
]


def __getattr__(name: str):
    if name == "ApplicationController":
        from .controller import ApplicationController

        return ApplicationController
    raise AttributeError(name)
