"""Shared hardware-transaction logging, so a real hardware failure can be
diagnosed from a log file alone without needing to reproduce it live.

Every backend module (thorlabs_piezo.py, waveforms.py, hamamatsu_dcam.py,
qmix_backend.py, instruments.py's serial/valve backends) routes its real
device commands and responses through `log_transaction()` (explicit) or
`log_call()` (a context manager for the common "one command, one
response/error" shape). One shared logger/file is used deliberately, not
one per device -- a single chronologically-merged timeline is what makes
cross-device interference (e.g. the documented shared-USB-hub risk)
diagnosable from the log at all; per-device files would need manual
timestamp interleaving to answer the same question.

Deliberately synchronous, plain `logging` + `RotatingFileHandler` -- no
threading/async. This project's own documented real-hardware call
latencies run from single-digit milliseconds up to multiple *seconds*
(e.g. the valve's pre-Session-55 `readline()` bug blocked ~5s per call);
a synchronous file write is microseconds by comparison (see
`tests/test_hw_logging.py`'s own timing assertion), so added complexity
here would be solving a problem that doesn't exist for this call
frequency.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator

DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "hardware_transactions.log"

_logger = logging.getLogger("thermo_acoustic.hw")
_logger.setLevel(logging.INFO)
_logger.propagate = False  # never leak onto the root logger / stderr

_lock = threading.Lock()
_configured_path: Path | None = None


def configure(log_file: Path | None = None, *, max_bytes: int = 5_000_000, backup_count: int = 5) -> Path:
    """(Re)point the module at a log file, replacing any existing handler.
    Safe to call more than once -- tests use this to redirect into a
    tmp_path instead of the real logs/ directory. Returns the resolved
    path actually in use."""
    global _configured_path
    target = Path(log_file) if log_file is not None else DEFAULT_LOG_FILE
    with _lock:
        if _configured_path == target:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        for handler in list(_logger.handlers):
            _logger.removeHandler(handler)
            handler.close()
        handler = RotatingFileHandler(target, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
        _logger.addHandler(handler)
        _configured_path = target
    return target


def _ensure_configured() -> None:
    if _configured_path is None:
        configure()


def log_transaction(
    device: str,
    operation: str,
    *,
    command: object = None,
    response: object = None,
    success: bool = True,
    error: str | None = None,
) -> None:
    """One structured record per hardware transaction: which device, what
    operation, what was sent, what came back (or the error), and whether
    it succeeded. Fire-and-forget from the caller's perspective -- never
    raises (a logging failure must never take down a real hardware call)."""
    _ensure_configured()
    outcome = "OK" if success else "FAIL"
    parts = [f"{device:<10}", f"{operation:<28}", outcome]
    if command is not None:
        parts.append(f"cmd={command!r}")
    if response is not None:
        parts.append(f"resp={response!r}")
    if error is not None:
        parts.append(f"error={error}")
    try:
        _logger.info(" | ".join(parts))
    except Exception:  # pragma: no cover - logging must never break a hardware call
        pass


@contextmanager
def log_call(device: str, operation: str, *, command: object = None) -> Iterator[dict]:
    """Wrap one real hardware call: logs success with whatever the caller
    stores in `result["response"]` before the block ends, or logs failure
    (with the exception's message) and re-raises if the block raises.

    Usage:
        with log_call("valve", "query_status", command=cmd) as result:
            result["response"] = self.port.read_until(...)
    """
    result: dict = {"response": None}
    try:
        yield result
    except Exception as exc:
        log_transaction(device, operation, command=command, success=False, error=str(exc))
        raise
    else:
        log_transaction(device, operation, command=command, response=result["response"], success=True)
