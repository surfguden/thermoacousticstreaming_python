"""Allocate one durable, non-overwriting log directory per UI process."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


@dataclass(frozen=True)
class SessionLogs:
    folder: Path
    ui: Path
    audit: Path
    hardware: Path


def create_session_logs(root: str | Path, mode: str) -> SessionLogs:
    base = Path(root).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for index in range(1000):
        folder = base / f"{stamp}_{mode}{f'_{index:03d}' if index else ''}"
        try:
            folder.mkdir()
            return SessionLogs(folder, folder / "ui_commands.log",
                               folder / "audit.jsonl", folder / "hardware_transactions.log")
        except FileExistsError:
            continue
    raise RuntimeError("Could not allocate a unique application log folder")


class UiLogWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()

    def write(self, line: str) -> str | None:
        try:
            with self._lock, self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except OSError as exc:
            return f"UI log unavailable at {self.path}: {exc}"
        return None
