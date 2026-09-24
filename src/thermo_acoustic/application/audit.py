from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class AuditLogger:
    def __init__(self, path: str | Path | None = None) -> None:
        # Anchor a caller-supplied relative path before an SDK can change the
        # process working directory. No machine-specific location is used.
        self.path = Path(path).expanduser().resolve() if path else None
        self._lock = Lock()

    def write(self, event: str, **fields: Any) -> str | None:
        if self.path is None:
            return
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        # A log failure must never prevent a hardware command or urgent stop.
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, default=str, sort_keys=True) + "\n")
            except OSError as exc:
                return f"Audit log unavailable at {self.path}: {exc}"
        return None
