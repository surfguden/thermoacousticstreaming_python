from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..domain.models import DeviceId


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class DeviceCommand:
    device: DeviceId
    operation: str
    args: tuple[Any, ...] = ()
    request_id: str = field(default_factory=lambda: uuid4().hex[:12])
    source: str = "ui"
    received_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class CommandResult:
    request_id: str
    device: DeviceId | None
    operation: str
    ok: bool
    value: Any = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CommandEvent:
    request_id: str
    state: str
    device: DeviceId | None
    operation: str
    source: str
    message: str = ""
    result: Any = None

