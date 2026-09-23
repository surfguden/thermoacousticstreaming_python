from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import json
from pathlib import Path

from .commands import CommandEvent, NoArguments
from ..domain.models import DEVICE_LABELS


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def operation_label(event: CommandEvent) -> str:
    operation = event.operation.value
    device_prefix = f"{event.device.value}." if event.device is not None else ""
    if operation.startswith(device_prefix):
        operation = operation[len(device_prefix):]
    if operation.startswith("lifecycle."):
        operation = operation.removeprefix("lifecycle.")
    return operation.replace("_", " ").replace(".", " ")


def device_label(event: CommandEvent) -> str:
    return DEVICE_LABELS[event.device] if event.device is not None else "Application"


def event_summary(event: CommandEvent) -> str | None:
    subject = f"{device_label(event)} {operation_label(event)}"
    if event.state == "queued":
        return f"{subject}…"
    if event.state == "running":
        return None
    if event.state == "completed":
        return f"{subject} — done!"
    if event.state == "cancelled":
        return f"{subject} — cancelled{f': {event.message}' if event.message else ''}"
    if event.state == "failed":
        return f"{subject} — failed{f': {event.message}' if event.message else ''}"
    return f"{subject} — {event.state}"


def detailed_event_text(event: CommandEvent) -> str:
    timestamp = event.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    fields = [
        timestamp,
        f"[{event.request_id}]",
        event.source,
        device_label(event),
        operation_label(event),
        event.state,
    ]
    if event.state == "queued" and not isinstance(event.arguments, NoArguments):
        fields.append(
            "arguments=" + json.dumps(_plain(event.arguments), ensure_ascii=False, sort_keys=True)
        )
    if event.message:
        fields.append(f"message={event.message}")
    if event.result is not None:
        result_text = repr(_plain(event.result))
        fields.append(f"result={result_text[:500]}{'…' if len(result_text) > 500 else ''}")
    return " · ".join(fields)
