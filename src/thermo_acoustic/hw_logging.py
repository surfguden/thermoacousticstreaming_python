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

The logging primitives above (`configure()`/`log_transaction()`/`log_call()`)
are deliberately synchronous, plain `logging` + `RotatingFileHandler` -- no
threading/async. This project's own documented real-hardware call
latencies run from single-digit milliseconds up to multiple *seconds*
(e.g. the valve's pre-Session-55 `readline()` bug blocked ~5s per call);
a synchronous file write is microseconds by comparison (see
`tests/test_hw_logging.py`'s own timing assertion), so added complexity
here would be solving a problem that doesn't exist for this call
frequency.

During a normal experiment, `action_scope()` also points these same primitives
at one bounded series-local JSONL action stream. That stream adds
run/condition/repeat/phase correlation and explicit evidence stages without
creating another hardware wrapper or writing inside per-frame loops. The
rotating text log remains the global transport diagnostic timeline; per-repeat
TDMS and the series lifecycle manifest retain their existing scientific and
aggregate authority.

That JSONL stream is also the project's single canonical software event
stream. `register_action_observer()` lets an additional passive consumer --
the commissioning-trace recorder, a live execution indicator -- receive the
SAME records rather than deriving its own parallel interpretation of what the
run did. Observers are read-only projections: they never issue hardware I/O,
never call back into `log_action()`, and an observer that raises is swallowed
here, exactly like a failed JSONL write.

`run_with_timeout()` below is a separate, unrelated utility that DOES use a
background thread -- shared home in this module because it's the other
piece of cross-cutting hardware infrastructure (the standard
timeout-guarded-cleanup-thread shape, previously hand-copied independently
in Application/QmixPumpBackend/PiezoStage; see
docs/hardware_safety_patterns.md).
"""

from __future__ import annotations

from contextvars import ContextVar, copy_context
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import queue
import threading
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Iterator

DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "hardware_transactions.log"

_logger = logging.getLogger("thermo_acoustic.hw")
_logger.setLevel(logging.INFO)
_logger.propagate = False  # never leak onto the root logger / stderr

_lock = threading.Lock()
_configured_path: Path | None = None
_action_lock = threading.Lock()
_action_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "thermo_acoustic_action_context", default=None
)
_observer_lock = threading.Lock()
_action_observers: dict[int, Callable[[dict[str, Any]], None]] = {}
_next_observer_token = 0


def register_action_observer(observer: Callable[[dict[str, Any]], None]) -> int:
    """Subscribe a passive consumer to the canonical software action stream.

    Observers exist so a second consumer (the commissioning trace recorder, a
    live execution indicator) can project the SAME records `action_log.jsonl`
    already receives, instead of running a parallel logger with its own
    interpretation of what happened. An observer is called synchronously, on
    whatever thread produced the action, with a private JSON-safe copy of the
    record plus a ``monotonic_ns`` field. It must never raise (``log_action``
    swallows it if it does), must never issue hardware I/O, and must never
    call ``log_action`` itself.
    """

    global _next_observer_token
    with _observer_lock:
        _next_observer_token += 1
        token = _next_observer_token
        _action_observers[token] = observer
    return token


def unregister_action_observer(token: int) -> None:
    """Remove a previously registered observer; unknown tokens are ignored."""

    with _observer_lock:
        _action_observers.pop(token, None)


@contextmanager
def action_scope(
    log_file: Path | None,
    *,
    run_id: str,
    condition: str,
    repeat: int | None,
    phase: str = "RUN",
) -> Iterator[None]:
    """Bind durable action-log correlation to the current execution context.

    The scope is intentionally local to one run/repeat. Existing backend
    ``log_call`` sites inherit it without receiving new control parameters,
    and a missing/unwritable action log can never change hardware behavior.
    ``elapsed_s`` is host monotonic duration since this scope began; it is
    diagnostic chronology, not a hardware-synchronization measurement.
    """

    started_monotonic_ns = time.monotonic_ns()
    context = {
        "log_file": None if log_file is None else Path(log_file),
        "run_id": str(run_id),
        "condition": str(condition),
        "repeat": None if repeat is None else int(repeat),
        "phase": str(phase),
        "started_monotonic": started_monotonic_ns / 1_000_000_000,
        "started_monotonic_ns": started_monotonic_ns,
    }
    token = _action_context.set(context)
    try:
        yield
    finally:
        _action_context.reset(token)


@contextmanager
def action_phase(phase: str) -> Iterator[None]:
    """Temporarily refine the current action phase (for example CLEANUP)."""

    current = _action_context.get()
    if current is None:
        yield
        return
    updated = dict(current)
    updated["phase"] = str(phase)
    token = _action_context.set(updated)
    try:
        yield
    finally:
        _action_context.reset(token)


def _json_safe(value: object, *, depth: int = 0) -> object:
    """Bound action payloads to concise JSON-safe scientific evidence."""

    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 2_000:
            return value[:2_000] + "...<truncated>"
        return value
    if depth >= 6:
        return f"<{type(value).__name__}>"
    if isinstance(value, Enum):
        return _json_safe(value.value, depth=depth + 1)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value), depth=depth + 1)
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        bounded = [_json_safe(item, depth=depth + 1) for item in items[:100]]
        if len(items) > 100:
            bounded.append(f"...<{len(items) - 100} more>")
        return bounded
    scalar = getattr(value, "item", None)
    if callable(scalar):
        try:
            return _json_safe(scalar(), depth=depth + 1)
        except Exception:
            pass
    return _json_safe(str(value), depth=depth + 1)


def log_action(
    subsystem: str,
    operation: str,
    *,
    evidence_stage: str,
    status: str,
    requested: object = None,
    effective: object = None,
    result: object = None,
    error: object = None,
    verification_scope: str = "SOFTWARE",
    source: str | None = None,
) -> None:
    """Append one concise structured action record for the active repeat.

    The evidence vocabulary deliberately keeps REQUESTED, PLANNED,
    EFFECTIVE, COMMAND_SENT, PROTOCOL_ACKNOWLEDGED, OBSERVED, and
    PHYSICAL_VERIFIED distinct. Callers must not use PHYSICAL_VERIFIED for a
    software/API result. This function never raises: evidence persistence
    failure must not trigger or interrupt hardware.

    Registered observers receive the same record after the JSONL append is
    attempted, so a live indicator and a durable trace always describe the
    same event. Observers run inside the caller's thread but cannot affect it.
    """

    context = _action_context.get()
    if context is None:
        return
    # One monotonic reading serves both the existing diagnostic elapsed_s and
    # the observer stream's nanosecond ordering field, so one record can never
    # carry two slightly different notions of when it happened.
    monotonic_ns = time.monotonic_ns()
    started_monotonic_ns = int(
        context.get("started_monotonic_ns")
        or float(context["started_monotonic"]) * 1_000_000_000
    )
    payload: dict[str, object] = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": max((monotonic_ns - started_monotonic_ns) / 1_000_000_000, 0.0),
        "run_id": context["run_id"],
        "condition": context["condition"],
        "repeat": context["repeat"],
        "phase": context["phase"],
        "subsystem": str(subsystem),
        "operation": str(operation),
        "evidence_stage": str(evidence_stage).upper(),
        "verification_scope": str(verification_scope).upper(),
        "status": str(status).upper(),
    }
    optional = {
        "requested": requested,
        "effective": effective,
        "result": result,
        "error": error,
        "source": source,
    }
    payload.update({key: _json_safe(value) for key, value in optional.items() if value is not None})
    log_file = context.get("log_file")
    if log_file is not None:
        try:
            target = Path(log_file)
            with _action_lock:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8", newline="\n") as handle:
                    json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
                    handle.write("\n")
                    handle.flush()
        except Exception:  # pragma: no cover - logging must never alter hardware behavior
            pass
    with _observer_lock:
        observers = list(_action_observers.values())
    if not observers:
        return
    # Observers get a private copy carrying the extra monotonic_ns field, so
    # no consumer can mutate what action_log.jsonl already wrote and the
    # persisted action-log schema stays exactly as before.
    record = dict(payload)
    record["monotonic_ns"] = monotonic_ns
    for observer in observers:
        try:
            observer(record)
        except Exception:  # pragma: no cover - evidence must never alter hardware behavior
            pass


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
    effective: object = None,
    success: bool = True,
    error: str | None = None,
    evidence_stage: str = "PROTOCOL_ACKNOWLEDGED",
    verification_scope: str = "PROTOCOL",
    record_requested: bool = True,
) -> None:
    """One structured record per hardware transaction: which device, what
    operation, what was sent, what came back (or the error), and whether
    it succeeded. Fire-and-forget from the caller's perspective -- never
    raises (a logging failure must never take down a real hardware call)."""
    outcome = "OK" if success else "FAIL"
    parts = [f"{device:<10}", f"{operation:<28}", outcome]
    context = _action_context.get()
    if context is None:
        parts.append("phase=MANUAL_SERVICE")
    else:
        parts.extend(
            [
                f"phase={context['phase']}",
                f"run_id={context['run_id']}",
                f"condition={context['condition']}",
                f"repeat={context['repeat']}",
            ]
        )
    if command is not None:
        parts.append(f"cmd={command!r}")
    if response is not None:
        parts.append(f"resp={response!r}")
    if error is not None:
        parts.append(f"error={error}")
    try:
        _ensure_configured()
        _logger.info(" | ".join(parts))
    except Exception:  # pragma: no cover - logging must never break a hardware call
        pass
    log_action(
        device,
        operation,
        evidence_stage=evidence_stage if success else "COMMAND_SENT",
        verification_scope=verification_scope,
        status="OK" if success else "FAILED",
        requested=command if record_requested else None,
        effective=effective,
        result=response,
        error=error,
        source="hw_logging.log_transaction",
    )


@contextmanager
def log_call(
    device: str,
    operation: str,
    *,
    command: object = None,
    response_stage: str = "PROTOCOL_ACKNOWLEDGED",
    verification_scope: str = "PROTOCOL",
) -> Iterator[dict]:
    """Wrap one real hardware call: logs success with whatever the caller
    stores in `result["response"]` before the block ends, or logs failure
    (with the exception's message) and re-raises if the block raises.

    Usage:
        with log_call("valve", "query_status", command=cmd) as result:
            result["response"] = self.port.read_until(...)
    """
    result: dict = {"response": None, "effective": None}
    log_action(
        device,
        operation,
        evidence_stage="COMMAND_SENT",
        verification_scope=verification_scope,
        status="ATTEMPTED",
        requested=command,
        source="hw_logging.log_call",
    )
    try:
        yield result
    except Exception as exc:
        log_transaction(
            device,
            operation,
            command=command,
            effective=result.get("effective"),
            success=False,
            error=str(exc),
            verification_scope=verification_scope,
            record_requested=False,
        )
        raise
    else:
        log_transaction(
            device,
            operation,
            command=command,
            response=result["response"],
            effective=result.get("effective"),
            success=True,
            evidence_stage=response_stage,
            verification_scope=verification_scope,
            record_requested=False,
        )


def run_with_timeout(action: Callable[[], None], name: str, timeout_s: float) -> str | None:
    """Run `action()` in a daemon thread, waiting up to `timeout_s` seconds
    for it to finish -- so a real hardware cleanup/close/disconnect call
    that hangs (a documented real risk for .NET/SDK calls this project has
    hit) cannot block the caller indefinitely. Never raises itself: returns
    `None` on success, or a one-line description of what went wrong
    (timeout, a raised exception, or the thread finishing without reporting
    a result) for the caller to collect/log/re-raise as it sees fit.

    `name` should already include whatever context belongs in the message
    (device/step name, and "cleanup" if that's the caller's own convention)
    -- this function does not add its own prefix, so callers control their
    own message wording exactly as before extracting this from three
    independent hand-copied implementations (Application, QmixPumpBackend,
    PiezoStage -- the standard hardware-cleanup shape documented in
    docs/hardware_safety_patterns.md).

    Usage:
        error = run_with_timeout(self.stop, "pump stop", self.close_timeout_s)
        if error is not None:
            errors.append(error)
    """
    result_queue: queue.Queue[BaseException | None] = queue.Queue(maxsize=1)
    caller_context = copy_context()

    def run() -> None:
        try:
            caller_context.run(action)
        except BaseException as exc:  # pragma: no cover - defensive hardware cleanup path
            result_queue.put(exc)
        else:
            result_queue.put(None)

    worker = threading.Thread(target=run, name=f"hw-timeout-{name}", daemon=True)
    worker.start()
    worker.join(max(timeout_s, 0.0))
    if worker.is_alive():
        return f"{name} timed out after {timeout_s:.1f}s."
    try:
        error = result_queue.get_nowait()
    except queue.Empty:  # pragma: no cover - thread completed without reporting
        return f"{name} finished without reporting a result."
    if error is not None:
        return f"{name} failed: {error}"
    return None
