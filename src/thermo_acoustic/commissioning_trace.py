"""Passive commissioning-trace recording over the canonical action stream.

This module adds **no** execution mode. A run behaves identically whether
recording is `OFF`, `RECORDING`, or `DEGRADED`: the recorder is a read-only
observer of `hw_logging.log_action()`, which the canonical experiment path
already calls at every software transition it genuinely knows about. Nothing
here opens a device, reads a device, writes a device, sleeps, blocks, or joins
a thread, and nothing here can change the order of hardware calls.

Evidence boundary, deliberately narrow:

- A trace event records that the **software** reached a transition. It proves
  command intent, protocol acknowledgement, and host chronology only.
- `monotonic_ns` orders software events and measures software intervals on one
  host clock. `wall_time_utc` is provenance/display. Neither is a
  common-timebase physical timing measurement, and neither establishes that
  two instruments did anything simultaneously.
- The recorder never manufactures an evidence stage. It copies the stage the
  canonical call site chose, so `PHYSICAL_VERIFIED` can only appear here if
  production started emitting it, which it does not.

Output lives beside the run's existing `action_log.jsonl` in the series
directory; the trace references that run rather than creating a second output
authority, and it never duplicates TDMS scientific data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import logging
from pathlib import Path
import threading
from typing import Any

from .hw_logging import register_action_observer, unregister_action_observer


logger = logging.getLogger(__name__)

TRACE_SCHEMA_VERSION = 1
TRACE_FILENAME = "commissioning_trace.jsonl"
TRACE_SUMMARY_FILENAME = "commissioning_trace_summary.json"

# The evidence vocabulary is shared with the action log and project_control.md.
# Listed here only so the summary can report which stages a run actually
# reached without re-deriving the ordering somewhere else.
EVIDENCE_STAGE_ORDER = (
    "REQUESTED",
    "PLANNED",
    "EFFECTIVE",
    "COMMAND_SENT",
    "PROTOCOL_ACKNOWLEDGED",
    "OBSERVED",
    "PHYSICAL_VERIFIED",
)

TRACE_EVIDENCE_BOUNDARY = (
    "Commissioning trace is software evidence. It records requested, planned, "
    "software-effective, command-sent, protocol-acknowledged and "
    "software-observed transitions plus host chronology. It does not establish "
    "physical timing, electrical levels, optical emission, acoustic pressure, "
    "delivered fluid volume, or cross-instrument simultaneity."
)


class TraceState(str, Enum):
    """Operator-facing recording state; never an execution mode."""

    OFF = "OFF"
    RECORDING = "RECORDING"
    DEGRADED = "DEGRADED"


@dataclass(slots=True)
class CommissioningTraceRecorder:
    """Project the canonical action stream into durable trace evidence.

    ``start()`` subscribes to `hw_logging`'s observer registry; ``stop()``
    unsubscribes and writes the derived summary. Both are called from the
    sequence boundary that already owns the series lifecycle manifest, so this
    class introduces no lifecycle of its own.
    """

    series_path: Path
    state: TraceState = TraceState.OFF
    degraded_reason: str | None = None
    event_count: int = 0
    dropped_event_count: int = 0
    _token: int | None = field(default=None, init=False, repr=False)
    # Reentrant so one critical section can cover sequence assignment and the
    # append together: the concurrent refresh worker also produces actions, and
    # file order must match the assigned sequence order.
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _sequence: int = field(default=0, init=False, repr=False)
    _condition_indexes: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _statuses: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _phases: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _stages: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _first_wall_time: str | None = field(default=None, init=False, repr=False)
    _last_wall_time: str | None = field(default=None, init=False, repr=False)
    _first_monotonic_ns: int | None = field(default=None, init=False, repr=False)
    _last_monotonic_ns: int | None = field(default=None, init=False, repr=False)
    _errors: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _started_utc: str | None = field(default=None, init=False, repr=False)

    @property
    def trace_path(self) -> Path:
        return Path(self.series_path) / TRACE_FILENAME

    @property
    def summary_path(self) -> Path:
        return Path(self.series_path) / TRACE_SUMMARY_FILENAME

    def start(self) -> TraceState:
        """Begin observing. Failure here degrades recording, never the run."""

        if self._token is not None:
            return self.state
        self._started_utc = datetime.now(timezone.utc).isoformat()
        try:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            # Truncate once at the sequence boundary so a re-run of the same
            # series directory cannot silently interleave two runs' events.
            with self.trace_path.open("w", encoding="utf-8", newline="\n"):
                pass
        except Exception as exc:  # pragma: no cover - exercised by the failure test
            self._degrade(f"trace file could not be created: {exc}")
            return self.state
        self.state = TraceState.RECORDING
        self._token = register_action_observer(self._observe)
        return self.state

    def stop(self) -> TraceState:
        """Stop observing and write the derived summary. Never raises."""

        token, self._token = self._token, None
        if token is not None:
            unregister_action_observer(token)
        if self.state is TraceState.OFF:
            return self.state
        self._write_summary()
        return self.state

    # -- observer -------------------------------------------------------
    def _observe(self, record: dict[str, Any]) -> None:
        """Called synchronously by `log_action`. Must not raise or recurse.

        This is the only place trace events are produced, so the trace can
        never contain a transition the canonical execution path did not
        actually report.
        """

        if self.state is not TraceState.RECORDING:
            self.dropped_event_count += 1
            return
        try:
            with self._lock:
                event = self._project(record)
                line = json.dumps(event, separators=(",", ":"), sort_keys=True)
                with self.trace_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line)
                    handle.write("\n")
                    handle.flush()
                self.event_count += 1
        except Exception as exc:
            # A failed trace write must not propagate into hardware control,
            # and reporting it must not re-enter the action stream that
            # produced it. Degrade once, then keep counting what was lost.
            self.dropped_event_count += 1
            self._degrade(f"trace write failed: {exc}")

    def _project(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
            condition = record.get("condition")
            condition_key = "" if condition is None else str(condition)
            condition_index = self._condition_indexes.setdefault(
                condition_key, len(self._condition_indexes) + 1
            )
            wall_time = record.get("timestamp_utc")
            monotonic_ns = record.get("monotonic_ns")
            if self._first_wall_time is None:
                self._first_wall_time = wall_time
            self._last_wall_time = wall_time
            if isinstance(monotonic_ns, int):
                if self._first_monotonic_ns is None:
                    self._first_monotonic_ns = monotonic_ns
                self._last_monotonic_ns = monotonic_ns
            status = str(record.get("status", ""))
            phase = str(record.get("phase", ""))
            stage = str(record.get("evidence_stage", ""))
            self._statuses[status] = self._statuses.get(status, 0) + 1
            self._phases[phase] = self._phases.get(phase, 0) + 1
            self._stages[stage] = self._stages.get(stage, 0) + 1
            if record.get("error") is not None and len(self._errors) < 50:
                self._errors.append(
                    {
                        "sequence": sequence,
                        "software_phase": phase,
                        "event": record.get("operation"),
                        "subsystem": record.get("subsystem"),
                        "error": record.get("error"),
                    }
                )

        event: dict[str, Any] = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "sequence": sequence,
            "run_id": record.get("run_id"),
            "wall_time_utc": wall_time,
            "monotonic_ns": monotonic_ns,
            "elapsed_s": record.get("elapsed_s"),
            "condition": condition,
            "condition_index": condition_index,
            "repeat": record.get("repeat"),
            "software_phase": phase or None,
            "subsystem": record.get("subsystem"),
            "event": record.get("operation"),
            "evidence_stage": stage or None,
            "verification_scope": record.get("verification_scope"),
            "status": status or None,
        }
        # Optional payloads stay absent rather than null-padded: an absent
        # requested/effective field means the call site had nothing to report,
        # which is different from reporting an empty value.
        for source_key, target_key in (
            ("requested", "requested"),
            ("effective", "planned_effective"),
            ("result", "result"),
            ("error", "error"),
            ("source", "source"),
        ):
            if record.get(source_key) is not None:
                event[target_key] = record[source_key]
        return event

    # -- summary --------------------------------------------------------
    def _degrade(self, reason: str) -> None:
        if self.state is TraceState.DEGRADED:
            return
        self.state = TraceState.DEGRADED
        self.degraded_reason = reason
        # Plain module logging only: this must never re-enter log_action.
        logger.error("Commissioning trace degraded: %s", reason)

    def summary(self) -> dict[str, Any]:
        """Derive the summary from the recorded event stream."""

        with self._lock:
            span_ns = (
                None
                if self._first_monotonic_ns is None or self._last_monotonic_ns is None
                else self._last_monotonic_ns - self._first_monotonic_ns
            )
            return {
                "schema_version": TRACE_SCHEMA_VERSION,
                "series_path": str(self.series_path),
                "trace_file": TRACE_FILENAME,
                "action_log_file": "action_log.jsonl",
                "recording_state": self.state.value,
                "degraded_reason": self.degraded_reason,
                "recording_started_utc": self._started_utc,
                "summary_written_utc": datetime.now(timezone.utc).isoformat(),
                "event_count": self.event_count,
                "dropped_event_count": self.dropped_event_count,
                "first_wall_time_utc": self._first_wall_time,
                "last_wall_time_utc": self._last_wall_time,
                "monotonic_span_ns": span_ns,
                "conditions_observed": dict(self._condition_indexes),
                "software_phase_counts": dict(self._phases),
                "status_counts": dict(self._statuses),
                "evidence_stage_counts": dict(self._stages),
                "physical_verified_event_count": self._stages.get("PHYSICAL_VERIFIED", 0),
                "errors": list(self._errors),
                "evidence_boundary": TRACE_EVIDENCE_BOUNDARY,
            }

    def _write_summary(self) -> None:
        payload = self.summary()
        try:
            self.summary_path.parent.mkdir(parents=True, exist_ok=True)
            with self.summary_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
        except Exception as exc:  # pragma: no cover - exercised by the failure test
            self._degrade(f"trace summary could not be written: {exc}")


def read_trace_events(series_path: Path) -> list[dict[str, Any]]:
    """Read back a recorded trace. Offline evidence review helper only."""

    path = Path(series_path) / TRACE_FILENAME
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events
