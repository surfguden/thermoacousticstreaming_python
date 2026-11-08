"""Nonblocking application-owned execution of declarative experiment series."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import math
import json
import shutil
import sys
from time import monotonic
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .plan_facts import plan_facts
from .pump_volume import volume_available
from ..domain.models import ConnectionState, DeviceId, OperatingMode, PumpReadback, ZStageReadback
from .run_identity import cached_software_identity
from .commands import (
    Ad2AnalogOutputIdle, Ad2ConfigureWaveformArgs, Ad2ExperimentDigitalArgs,
    Ad2TriggerSettingsArgs, Ad2TriggerSource, Ad2WaveformChannelArgs,
    Ad2WaveformFunction, CameraConfigureRoiArgs, CameraConfigureSequenceArgs, CameraConfigureSnapshotArgs,
    CameraSequenceResult, CameraSequenceTriggerArgs, CameraTriggerActive,
    CameraTriggerPolarity, CameraTriggerSource, DeviceCommand, DeviceOperation,
    FlushArgs, NoArguments, PumpUnitArgs, TecApplySetpointsArgs, TecWaitStableArgs,
    WaitArgs, WorkflowCommand, WorkflowOperation, ZStageSetPositionArgs,
)
from .experiment_storage import FileWorker, SeriesStorage, json_ready
from .experiments import Expansion, PlannedExperiment, validate_definition
from .temperature_recording import TemperatureRecorder
from .simple_preflight import camera_preflight_fingerprint


@dataclass(frozen=True)
class StartReadiness:
    blocking: tuple[str, ...]
    reminders: tuple[str, ...]


BATCH_ACTIVE_STATES = frozenset({"running", "stopping", "aborting"})


class ExperimentManager(QObject):
    changed = Signal(object)
    notice = Signal(str)

    def __init__(self, controller, *, confirm_batch: Callable[[str], bool] | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.confirm_batch = confirm_batch or (lambda _summary: False)
        self.confirm_unchecked: Callable[[str], bool] = lambda _summary: True
        self._camera_preflight_passes: set[str] = set()
        self._syringe_preflight_levels: dict[int, float] | None = None
        self._syringe_preflight_pending: dict[str, tuple[Callable[[Any], None], Callable[[bool, str], None]]] = {}
        self._syringe_preflight_active = False
        self._camera_was_connected = False
        self._pump_was_connected = False
        self._queued: deque[tuple[Expansion, SeriesStorage]] = deque()
        self._batch_items: list[tuple[Expansion, SeriesStorage]] = []
        self._series_states: dict[Path, str] = {}
        self._approved = 0
        self._current: tuple[Expansion, SeriesStorage] | None = None
        self._experiment: PlannedExperiment | None = None
        # Set by the UI-side save-result callback after storage.save_frames()
        # succeeded, not merely when its Future became done. Failure finalization
        # also waits for the callback set to empty before consulting this flag.
        # Reset at each experiment; this distinguishes a saved acquisition from
        # completion of its remaining output/flush steps.
        self._experiment_frames_saved = False
        self._capture: CameraSequenceResult | None = None
        self._triggered_at: float | None = None
        self._batch_output_root: Path | None = None
        self._settings: dict[str, Any] = {}
        self._applied: dict[str, Any] = {}
        self._laser_frequency_hz: float | None = None
        self._callbacks: dict[str, Callable[[Any], None]] = {}
        self._timers: list[QTimer] = []
        self._file_worker = FileWorker()
        self._file_futures: set[Any] = set()
        self._recorder: TemperatureRecorder | None = None
        self._failure_reason: str | None = None
        self._stop_after_current = False
        self._abort_requested = False
        self._stop_sent: set[DeviceId] = set()  # devices already asked to stop in this wind-down
        self._stop_pending: dict[str, DeviceId] = {}  # request id -> device, until its result returns
        self._stop_failures: list[str] = []  # stops that failed or could not be requested, shown with the end state
        self._failed = False
        self._failure_reason = None
        self._state = "idle"
        self._completed = 0
        self._planned_total = 0
        self._batch_completed_at_start = 0
        self._batch_series_total = 0
        self._phase = "Idle"
        self._parallel_depth = 0
        # The newest acquisition whose images are on disk, for the run monitor (read-only):
        # outcome is "saved" (images written; flush and closing may still be running), "completed"
        # (the whole experiment finished), "failed_after_save" (a later fault) or "aborted_after_save"
        # (the operator or Panic stopped the batch). Cleared when a batch starts.
        self._last_saved: dict[str, Any] | None = None
        # Kind of the action that just finished (display only: tells a timed wait that follows a
        # temperature stability check or a temperature set from any other timed wait).
        self._previous_action: str | None = None
        self._series_completed_at_start = 0
        controller.command_result.connect(self._command_result)
        controller.command_result.connect(self._syringe_preflight_result)
        controller.status_changed.connect(self._preflight_device_status)

    def _preflight_device_status(self, statuses: dict) -> None:
        camera_connected = statuses[DeviceId.CAMERA].connection is ConnectionState.CONNECTED
        pump_connected = statuses[DeviceId.PUMP].connection is ConnectionState.CONNECTED
        changed = False
        if self._camera_was_connected and not camera_connected:
            changed = bool(self._camera_preflight_passes)
            self._camera_preflight_passes.clear()
        if self._pump_was_connected and not pump_connected:
            changed = changed or self._syringe_preflight_levels is not None
            self._invalidate_syringe_preflight()
        self._camera_was_connected = camera_connected
        self._pump_was_connected = pump_connected
        if changed:
            self._publish()

    def attach_temperature_monitor(self, monitor) -> None:
        monitor.sample.connect(self._temperature_sample)

    def _temperature_sample(self, sample: dict) -> None:
        if self._recorder is None:
            return
        error = self._recorder.error()
        if error:
            self._fail(f"Temperature log write failed: {error}")
            return
        self._recorder.add(sample)

    @property
    def batch_active(self) -> bool:
        """True from Start until the batch has fully stopped (including the stop/abort drain)."""
        return self._state in BATCH_ACTIVE_STATES

    def queue(self, definition: dict[str, Any], output_root: str | Path,
              image_format: str | None = None) -> Path:
        if self._syringe_preflight_active or self.controller.count_preflight_active:
            raise RuntimeError("Wait for preflight to finish before changing the batch")
        if self.batch_active:
            raise RuntimeError("Cannot queue a series while an experiment batch is running")
        if self.controller.panic_status()["state"] == "stopping":
            raise RuntimeError("Cannot queue a series during Panic safe stop")
        if not isinstance(definition.get("description"), str) or not definition["description"].strip():
            raise ValueError("Enter a series descriptor before queueing")
        definition = {**definition, "description": definition["description"].strip()}
        # A finished batch is forgotten only once the new series is really stored: a rejected
        # Queue (invalid definition, bad folder, storage error) must leave the old record as it was.
        finished = self._state in {"completed", "failed", "aborted", "stopped"}
        batch_root = None if finished else self._batch_output_root
        expansion = validate_definition(definition)
        output = Path(output_root).expanduser().resolve()
        if batch_root is not None and output != batch_root:
            raise ValueError("All queued series in one batch must use the same experiment base folder")
        storage = SeriesStorage(output, expansion,
                                image_format or definition.get("tiff_format", "frames"),
                                continuing_batch=batch_root is not None,
                                run_identity={"mode": self.controller.mode.value,
                                              "software": cached_software_identity()})
        if finished:
            self._state = "idle"
            self._phase = "Idle"
            self._planned_total = 0
            self._batch_series_total = 0
            self._batch_completed_at_start = self._completed
            self._batch_items = []
            self._series_states.clear()
        self._batch_output_root = output
        self._queued.append((expansion, storage))
        self._invalidate_syringe_preflight()
        self._series_states[storage.folder] = "queued"
        self._publish()
        return storage.folder

    def queued_flush_budget(self, folder: str | Path | None = None) -> dict[int, float]:
        """Flush volume per pump unit (mL) in the compiled steps of the queued series: all of them, or just
        `folder`. Read-only; the same computation the batch syringe preflight uses."""
        items = [(expansion, storage) for expansion, storage in self._queued
                 if folder is None or storage.folder == Path(folder)]
        return self._flush_totals(items)

    def queued_definition(self, folder: str | Path) -> dict[str, Any]:
        return next(expansion.definition for expansion, storage in self._queued
                    if storage.folder == Path(folder))

    def update_queued(self, folder: str | Path, definition: dict[str, Any]) -> None:
        if self._syringe_preflight_active or self.controller.count_preflight_active:
            raise RuntimeError("Wait for preflight to finish before changing the batch")
        if self._state == "running":
            raise RuntimeError("Cannot edit a running batch")
        expansion = validate_definition(definition)
        items = list(self._queued)
        for index, (_old, storage) in enumerate(items):
            if storage.folder == Path(folder):
                storage.update_definition(expansion)
                storage.image_format = definition.get("tiff_format", storage.image_format)
                items[index] = (expansion, storage)
                self._queued = deque(items)
                self._invalidate_syringe_preflight()
                self._publish()
                return
        raise ValueError("Selected series is not queued")

    def remove_queued(self, folder: str | Path) -> None:
        if self._syringe_preflight_active or self.controller.count_preflight_active:
            raise RuntimeError("Wait for preflight to finish before changing the batch")
        if self._state == "running":
            raise RuntimeError("Cannot remove a series from a running batch")
        items = list(self._queued)
        for index, (_expansion, storage) in enumerate(items):
            if storage.folder == Path(folder):
                storage.status("removed_from_queue", {})
                del items[index]
                self._queued = deque(items)
                self._series_states.pop(storage.folder, None)
                self._invalidate_syringe_preflight()
                self._publish()
                return
        raise ValueError("Selected series is not queued")

    def record_camera_preflight(self, fingerprint: str) -> None:
        self._camera_preflight_passes.add(fingerprint)
        self._publish()

    def camera_preflighted(self, definition: dict[str, Any]) -> bool:
        return camera_preflight_fingerprint(validate_definition(definition)) in self._camera_preflight_passes

    @staticmethod
    def _flush_totals(items: list[tuple[Expansion, SeriesStorage]]) -> dict[int, float]:
        volumes: dict[int, list[float]] = {}
        def visit(steps):
            for step in steps:
                if step["type"] == "flush":
                    args = step["args"]
                    volumes.setdefault(args["unit_index"], []).append(args["volume_ml"])
                elif step["type"] == "experiment":
                    visit(step["steps"])
                elif step["type"] == "parallel":
                    for branch in step["branches"]:
                        visit(branch)
        for expansion, _storage in items:
            visit(expansion.steps)
        return {index: math.fsum(values) for index, values in volumes.items()}  # no accumulated rounding error

    @staticmethod
    def _check_flush_capacity(totals: dict[int, float], units: dict) -> None:
        """Each pump unit must hold what the series flushes through it. One rule for all units and for the
        preflight (`volume_available`); an unreadable level is an error, never "enough"."""
        for index, volume in totals.items():
            unit = units.get(index)
            if unit is None or unit.fill_level_ml is None:
                raise RuntimeError(f"Pump unit {index + 1} has no readable fill level")
            if not math.isfinite(unit.fill_level_ml):
                raise RuntimeError(f"Pump unit {index + 1} reports a fill level that is not a number")
            if not volume_available(unit.fill_level_ml, volume):
                raise RuntimeError(f"Pump unit {index + 1} needs {volume:g} mL total flush volume "
                                   f"but currently has {unit.fill_level_ml:g} mL")

    def _invalidate_syringe_preflight(self) -> None:
        self._syringe_preflight_levels = None

    def _syringe_preflight_current(self) -> bool:
        levels = self._syringe_preflight_levels
        if levels is None:
            return False
        pump = self.controller.statuses()[DeviceId.PUMP].readback
        if not isinstance(pump, PumpReadback):
            return False
        units = {unit.unit_index: unit for unit in pump.units}
        return all(index in units and units[index].fill_level_ml is not None
                   and units[index].fill_level_ml + 1e-6 >= level
                   and units[index].is_pumping is False
                   for index, level in levels.items())

    def preflight_syringe(self, finished: Callable[[bool, str], None]) -> None:
        if self._syringe_preflight_active or self._state == "running":
            raise RuntimeError("Syringe preflight is already active or batch is running")
        if not self._queued:
            raise RuntimeError("Queue a series before checking syringe capacity")
        if self.controller.statuses()[DeviceId.PUMP].connection is not ConnectionState.CONNECTED:
            raise RuntimeError("Connect the pump before syringe preflight")
        totals = self._flush_totals(list(self._queued))
        self._invalidate_syringe_preflight()
        self._syringe_preflight_active = True
        indices = deque(sorted(totals))
        def complete(ok: bool, message: str) -> None:
            self._syringe_preflight_active = False
            self._publish()
            finished(ok, message)
        def next_unit(_value=None):
            if not indices:
                pump = self.controller.statuses()[DeviceId.PUMP].readback
                units = {unit.unit_index: unit for unit in pump.units} if isinstance(pump, PumpReadback) else {}
                levels = {}
                for index, needed in totals.items():
                    unit = units.get(index)
                    if (unit is None or unit.fill_level_ml is None or not math.isfinite(unit.fill_level_ml)
                            or unit.is_pumping is not False):
                        complete(False, f"Pump {index + 1} has no idle, readable fill level")
                        return
                    if not volume_available(unit.fill_level_ml, needed):
                        complete(False, f"Pump {index + 1} needs {needed:g} mL; has {unit.fill_level_ml:g} mL")
                        return
                    levels[index] = unit.fill_level_ml
                self._syringe_preflight_levels = levels
                complete(True, "Batch syringe capacity passed")
                return
            index = indices.popleft()
            def send(operation, callback):
                command = DeviceCommand(DeviceId.PUMP, operation, PumpUnitArgs(index), source="experiment-preflight")
                self._syringe_preflight_pending[command.request_id] = callback, complete
                try:
                    self.controller.submit(command)
                except Exception as exc:
                    self._syringe_preflight_pending.pop(command.request_id, None)
                    complete(False, str(exc))
            send(DeviceOperation.PUMP_STATUS_READ,
                 lambda _value: send(DeviceOperation.PUMP_FILL_LEVEL_READ, next_unit))
        next_unit()

    def _syringe_preflight_result(self, result) -> None:
        pending = self._syringe_preflight_pending.pop(result.request_id, None)
        if pending is None:
            return
        callback, complete = pending
        if result.ok:
            callback(result.value)
        else:
            complete(False, result.error or "Syringe preflight failed")

    def status(self) -> dict[str, Any]:
        queued = self._batch_items if self._batch_items else list(self._queued)
        queue_details = []
        syringe_passed = self._syringe_preflight_current()
        for expansion, storage in queued:
            camera_applicable = bool(expansion.experiments)
            passed = camera_applicable and camera_preflight_fingerprint(expansion) in self._camera_preflight_passes
            queue_details.append({"description": expansion.definition["description"],
                                  "folder": str(storage.folder),
                                  "experiment_count": len(expansion.experiments),
                                  "camera_preflight_applicable": camera_applicable,
                                  "camera_preflight_passed": passed,
                                  "syringe_preflight_applicable": bool(self._flush_totals([(expansion, storage)])),
                                  "syringe_preflight_passed": syringe_passed,
                                  "state": self._series_states.get(storage.folder, "queued"),
                                  "current": self._current is not None and storage is self._current[1]})
        return {"state": self._state, "queued_series": len(self._queued),
                "approved_remaining": self._approved,
                "batch_series_total": self._batch_series_total,
                "planned_experiments": self._planned_total,
                "batch_completed_experiments": self._completed - self._batch_completed_at_start,
                "current_experiment_number": (self._completed - self._batch_completed_at_start + 1
                                               if self._experiment is not None else None),
                "phase": self._phase,
                "failure_reason": self._failure_reason,
                "series": queue_details,
                "last_saved": dict(self._last_saved) if self._last_saved else None,
                "stop_failures": list(self._stop_failures),
                "current_plan": asdict(plan_facts(self._current[0].steps)) if self._current else None,
                "current_series": str(self._current[1].folder) if self._current else None,
                "current_experiment": self._experiment.experiment_id if self._experiment else None,
                "current_parameters": dict(self._experiment.parameters) if self._experiment else None,
                "current_repeat": self._experiment.repeat_index if self._experiment else None,
                "completed_experiments": self._completed,
                "stop_after_current": self._stop_after_current,
                "syringe_preflight_passed": syringe_passed,
                "syringe_preflight_active": self._syringe_preflight_active}

    def _publish(self) -> None:
        self.changed.emit(self.status())

    def _unchecked_camera_series(self) -> list[str]:
        return [expansion.definition["description"] for expansion, _storage in self._queued
                if camera_preflight_fingerprint(expansion) not in self._camera_preflight_passes]

    def start_readiness(self) -> StartReadiness:
        """What stops Start, and what it only warns about. Read-only: no device command, no state change,
        no dialog. `start()` refuses on the first `blocking` entry, so the UI and Start share one rule."""
        blocking: list[str] = []
        reminders: list[str] = []
        if self.controller.close_requested:
            blocking.append("The application is closing; no new batch can start")
        if self.controller.z_stack.state == "running":
            blocking.append("Wait for the Z stack to finish before starting the batch")
        if self.controller.panic_status()["state"] == "stopping":
            blocking.append("Wait for Panic safe stop to finish before starting a batch")
        if self.controller.count_preflight_active:
            blocking.append("Wait for count preflight to finish before starting a batch")
        if self._current is not None or self._state == "running":
            blocking.append("An experiment batch is already running")
        if not self._queued:
            blocking.append("Queue at least one experiment series")
        if self._syringe_preflight_active:
            blocking.append("Wait for syringe preflight to finish")
        syringe_needed = bool(self._queued) and bool(self._flush_totals(list(self._queued)))
        syringe_current = syringe_needed and self._syringe_preflight_current()
        if self.controller.mode is OperatingMode.REAL and syringe_needed and not syringe_current:
            blocking.append("Run syringe preflight for the current batch before Start")
        if self._queued:
            unchecked = self._unchecked_camera_series()
            if unchecked:
                reminders.append(f"Camera preflight is not current for {len(unchecked)} queued series "
                                 "(optional; Start asks to continue)")
            if syringe_needed and not syringe_current and self.controller.mode is not OperatingMode.REAL:
                reminders.append("Batch syringe preflight not run (required in real mode)")
            if self.controller.mode is OperatingMode.REAL:
                reminders.append("Start asks for confirmation before using real hardware")
            reminders.append("Checked only when the series starts: devices connected, pump level, camera "
                             "buffer, no manual AD2 output")
        return StartReadiness(tuple(blocking), tuple(reminders))

    def start(self) -> bool:
        blocking = self.start_readiness().blocking
        if blocking:
            raise RuntimeError(blocking[0])
        unchecked = self._unchecked_camera_series()
        if unchecked and not self.confirm_unchecked(
            f"Camera preflight has not passed for {len(unchecked)} queued series with their current "
            "camera settings. Continue with standard Start validation?"
        ):
            return False
        queued_now = len(self._queued)
        count = sum(len(expansion.experiments) for expansion, _ in self._queued)
        if self.controller.mode is OperatingMode.REAL:
            if not self.confirm_batch(
                f"Run {queued_now} queued experiment series ({count} experiments) on connected real hardware? "
                "This may move pumps/stage and activate ultrasound, laser, LED and camera."
            ):
                return False
        self._last_saved = None
        self._approved = queued_now
        self._batch_items = list(self._queued)
        self._planned_total = count
        self._batch_completed_at_start = self._completed
        self._batch_series_total = queued_now
        self._phase = "Preparing experiment batch"
        self._parallel_depth = 0
        self._failed = False
        self._abort_requested = False
        self._stop_after_current = False
        self._stop_sent.clear()
        self._stop_pending.clear()
        self._stop_failures.clear()
        self._state = "running"
        self._publish()
        QTimer.singleShot(0, self._next_series)
        return True

    def stop_after_current(self) -> None:
        if self._state != "running":
            return
        self._stop_after_current = True
        self._publish()

    def abort(self, reason: str = "Operator aborted experiment batch") -> None:
        if self._state != "running":
            return
        self._abort_requested = True
        self._state = "aborting"
        for timer in self._timers:
            timer.stop()
            timer.deleteLater()
        self._timers.clear()
        self.controller.cancel_active_workflow()
        self._request_stops((DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE))
        self._fail(reason)

    def _request_stops(self, devices) -> None:
        """Ask each of `devices` once, in this wind-down, to stop; remember the request so its result is waited for
        and a failure is reported. A device whose last operation failed (ERROR) is still connected and still gets its
        stop; only a disconnected one is skipped. TEC regulation is not touched here (Panic/exit handle that)."""
        statuses = self.controller.statuses()
        for device in devices:
            if device in self._stop_sent or statuses[device].connection is ConnectionState.DISCONNECTED:
                continue
            self._stop_sent.add(device)
            command = DeviceCommand(device, DeviceOperation.SAFE_STOP, NoArguments(), source="experiment")
            self._stop_pending[command.request_id] = device
            try:
                self.controller.submit(command)
            except Exception as exc:
                self._stop_pending.pop(command.request_id, None)
                self._stop_failures.append(f"{device.value}: the stop could not be requested ({exc})")

    def panic_abort(self) -> None:
        """Stop batch dispatch without asking the flush workflow to move the valve."""
        if self._state not in {"running", "stopping", "aborting"} or self._failed:
            return
        self._abort_requested = True
        self._fail("Operator pressed Panic", stop_outputs=False)

    def _next_series(self) -> None:
        if self._failed or self._abort_requested:
            return
        if self._approved <= 0 or not self._queued or self._stop_after_current:
            self._state = "stopped" if self._stop_after_current else "completed"
            self._phase = "Stopped after current experiment" if self._stop_after_current else "Experiment series completed"
            self._publish()
            return
        self._current = self._queued.popleft()
        self._series_states[self._current[1].folder] = "running"
        self._phase = "Preparing series"
        self._approved -= 1
        self._series_completed_at_start = self._completed
        expansion, storage = self._current
        storage.status("preflight", {"experiment_count": len(expansion.experiments)})
        storage.event("series_started")
        if expansion.definition.get("temperature_logging"):
            try:
                self._recorder = TemperatureRecorder(storage.metadata / "temperature.csv")
            except Exception as exc:
                self._fail(f"Temperature log could not be opened: {exc}")
                return
        self._publish()
        try:
            self._require_devices(expansion.steps)
        except Exception as exc:
            self._fail(str(exc))
            return
        def after_pump_refresh() -> None:
            try:
                self._check_capacity(expansion, storage)
            except Exception as exc:
                self._fail(str(exc))
                return
            self._command(DeviceId.CAMERA, DeviceOperation.CAMERA_TIMING_READ, NoArguments(),
                          lambda timing: self._after_camera_timing(expansion, storage, timing))
        self._refresh_pump_preflight(expansion.steps, after_pump_refresh)

    def _refresh_pump_preflight(self, steps: tuple[dict[str, Any], ...],
                                done: Callable[[], None]) -> None:
        indices: set[int] = set()
        def visit(items):
            for item in items:
                if item["type"] == "flush":
                    indices.add(item["args"]["unit_index"])
                elif item["type"] == "experiment":
                    visit(item["steps"])
                elif item["type"] == "parallel":
                    for branch in item["branches"]:
                        visit(branch)
        visit(steps)
        if (self._current is not None and self._current[0].definition.get("preflight")
                and self.controller.statuses()[DeviceId.PUMP].connection is ConnectionState.CONNECTED):
            readback = self.controller.statuses()[DeviceId.PUMP].readback
            if isinstance(readback, PumpReadback):
                indices.update(unit.unit_index for unit in readback.units)
        tasks = deque((index, operation) for index in sorted(indices)
                      for operation in (DeviceOperation.PUMP_STATUS_READ,
                                        DeviceOperation.PUMP_FILL_LEVEL_READ))
        def next_task(_value=None):
            if not tasks:
                done()
                return
            index, operation = tasks.popleft()
            self._command(DeviceId.PUMP, operation, PumpUnitArgs(index), next_task)
        next_task()

    def _require_devices(self, steps: tuple[dict[str, Any], ...]) -> None:
        resources: set[str] = set()
        def visit(items):
            for item in items:
                kind = item["type"]
                if kind == "experiment":
                    visit(item["steps"])
                elif kind == "parallel":
                    for branch in item["branches"]:
                        visit(branch)
                elif kind == "flush":
                    resources.update({"pump", "valve"})
                elif kind.startswith("camera_") or kind == "await_frames":
                    resources.add("camera")
                elif kind.startswith("ad2_") or kind in {"pc_trigger", "wait_outputs"}:
                    resources.add("ad2")
                elif kind.startswith("tec_"):
                    resources.add("tec")
                elif kind == "stage_move":
                    resources.add("z_stage")
        visit(steps)
        statuses = self.controller.statuses()
        if (self._current is not None and self._current[0].definition.get("temperature_logging")
                and statuses[DeviceId.TEC].connection is not ConnectionState.CONNECTED):
            raise RuntimeError("Temperature logging requires a connected TEC")
        for device in DeviceId:
            if device.value in resources and statuses[device].connection is not ConnectionState.CONNECTED:
                raise RuntimeError(f"Required device is not connected: {device.value}")
        if "z_stage" in resources:
            # Checked here, before any flush, heating or capture, so a stage_move that
            # cannot run fails the series at once. Closed loop is required, never
            # enabled on the operator's behalf, and the stage is not moved.
            stage = statuses[DeviceId.Z_STAGE].readback
            if not isinstance(stage, ZStageReadback) or not stage.closed_loop:
                raise RuntimeError(
                    "Z stage closed-loop control must be confirmed and enabled before a stage_move step")
        if statuses[DeviceId.CAMERA].busy:
            raise RuntimeError("Camera has a pending operation; wait before starting the series")
        ad2 = statuses[DeviceId.AD2].readback
        if ad2 is not None and (getattr(ad2, "waveform_running", False)
                                or getattr(ad2, "digital_output_running", False)):
            raise RuntimeError("Stop manual AD2 outputs before starting the series")

    def _check_capacity(self, expansion: Expansion, storage: SeriesStorage) -> None:
        status = self.controller.statuses()
        camera = status[DeviceId.CAMERA].readback
        roi = getattr(camera, "roi", None)
        if roi is None and any(
            "roi" not in step["args"] for item in expansion.experiments for step in item.steps
            if step["type"] == "camera_configure"
        ):
            raise RuntimeError("Camera ROI readback is unavailable for memory/disk preflight")
        limits = getattr(camera, "roi_limits", None)
        width_margin = max(0, limits.horizontal_size.increment - 1) if limits else 0
        height_margin = max(0, limits.vertical_size.increment - 1) if limits else 0
        frame_bytes = max(
            ((step["args"].get("roi", {}).get("width", roi.horizontal_size if roi else 0) + width_margin)
             * (step["args"].get("roi", {}).get("height", roi.vertical_size if roi else 0) + height_margin) * 2
             for item in expansion.experiments for step in item.steps
             if step["type"] == "camera_configure"), default=0,
        )
        total_frames = sum(next(step["args"]["frame_count"] for step in item.steps
                                if step["type"] == "camera_configure")
                           for item in expansion.experiments)
        max_frames = max(next(step["args"]["frame_count"] for step in item.steps
                              if step["type"] == "camera_configure")
                         for item in expansion.experiments)
        estimated_disk = int(total_frames * frame_bytes * 1.2)
        estimated_memory = frame_bytes * (max_frames * 3 + 3)  # DCAM, host, file, preview
        free_disk = shutil.disk_usage(storage.folder).free
        if free_disk < estimated_disk:
            raise RuntimeError(f"Insufficient disk: estimate {estimated_disk} B, free {free_disk} B")
        try:
            import psutil  # optional, never required for UI launch
            free_memory = psutil.virtual_memory().available
        except ImportError:
            free_memory = None
            if sys.platform == "win32":
                import ctypes
                class MemoryStatus(ctypes.Structure):
                    _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                                ("total_physical", ctypes.c_ulonglong),
                                ("available_physical", ctypes.c_ulonglong),
                                ("total_page", ctypes.c_ulonglong),
                                ("available_page", ctypes.c_ulonglong),
                                ("total_virtual", ctypes.c_ulonglong),
                                ("available_virtual", ctypes.c_ulonglong),
                                ("available_extended", ctypes.c_ulonglong)]
                memory = MemoryStatus()
                memory.length = ctypes.sizeof(MemoryStatus)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
                    free_memory = memory.available_physical
        if free_memory is not None and free_memory < estimated_memory:
            raise RuntimeError(f"Insufficient memory: estimate {estimated_memory} B, available {free_memory} B")
        volumes: dict[int, list[float]] = {}
        def visit(items):
            for item in items:
                if item["type"] == "flush":
                    args = item["args"]
                    volumes.setdefault(args["unit_index"], []).append(args["volume_ml"])
                elif item["type"] == "experiment":
                    visit(item["steps"])
                elif item["type"] == "parallel":
                    for branch in item["branches"]:
                        visit(branch)
        visit(expansion.steps)
        totals = {index: math.fsum(values) for index, values in volumes.items()}
        pump = status[DeviceId.PUMP].readback
        units = {unit.unit_index: unit for unit in pump.units} if isinstance(pump, PumpReadback) else {}
        if any(unit.is_pumping for unit in units.values()):
            raise RuntimeError("Stop active pump movement before starting an experiment series")
        self._check_flush_capacity(totals, units)
        storage.event("capacity_estimate", frame_bytes=frame_bytes,
                      estimated_memory_bytes=estimated_memory,
                      available_memory_bytes=free_memory,
                      estimated_disk_bytes=estimated_disk, free_disk_bytes=free_disk,
                      total_flush_ml_by_unit=totals)

    def _after_camera_timing(self, expansion: Expansion, storage: SeriesStorage, timing: Any) -> None:
        try:
            self._laser_frequency_hz = self._read_laser_min_frequency()
        except (RuntimeError, ValueError) as exc:
            self._fail(str(exc))
            return
        for item in expansion.experiments:
            camera = next(step["args"] for step in item.steps if step["type"] == "camera_configure")
            ad2 = next(step["args"] for step in item.steps if step["type"] == "ad2_configure")
            try:
                self._validate_laser_window(ad2, self._laser_frequency_hz)
            except ValueError as exc:
                self._fail(str(exc))
                return
            dio = ad2["dio"]
            interval = 1 / dio["frame_rate_hz"]
            if camera["exposure_ms"] / 1000 >= interval:
                self._fail("Camera exposure exceeds frame interval")
                return
            # Only checks that do not depend on the camera's current configuration are made
            # here. The camera's minimum trigger interval and readout time depend on the ROI,
            # exposure and trigger mode, none of which this series has applied yet, so
            # comparing against `timing` would judge the previous configuration. Those limits
            # are checked in _configure_all_before_fluidics() against the readback taken
            # after each configuration has been applied (and against the AD2's achieved rate).
        # `timing` is the camera's state before this series configured it: recorded for
        # reference only.
        storage.event("camera_timing_preflight", readback=json_ready(timing))
        def configured() -> None:
            if expansion.definition.get("preflight") and self.controller.mode is OperatingMode.REAL:
                self._run_count_preflights(expansion, storage, lambda: self._begin_steps(expansion, storage))
            else:
                self._begin_steps(expansion, storage)
        self._configure_all_before_fluidics(expansion, storage, configured)

    def _read_laser_min_frequency(self) -> float:
        readback = self.controller.statuses()[DeviceId.AD2].readback
        capabilities = getattr(readback, "capabilities", None)
        if capabilities is None:
            raise RuntimeError("AD2 capabilities are unavailable for WFG2 laser frequency")
        channel = next((item for item in capabilities.waveform_channels
                        if item.channel_index == 1), None)
        if channel is None or Ad2WaveformFunction.SQUARE.value not in channel.carrier.functions:
            raise RuntimeError("AD2 WFG2 does not report support for Square output")
        minimum = float(channel.carrier.frequency_hz.minimum)
        maximum = float(channel.carrier.frequency_hz.maximum)
        if not math.isfinite(minimum) or minimum <= 0 or minimum > maximum:
            raise ValueError("AD2 WFG2 reported an invalid minimum carrier frequency")
        return minimum

    @staticmethod
    def _validate_laser_window(args: dict[str, Any], frequency_hz: float) -> None:
        laser = args["laser"]
        if laser["enabled"] and laser["run_s"] * frequency_hz >= 0.5:
            raise ValueError("Laser run window would reach the low half of the WFG2 square wave")

    def _configure_all_before_fluidics(self, expansion: Expansion, storage: SeriesStorage,
                                       done: Callable[[], None]) -> None:
        """Ask the connected SDKs to validate every unique configuration before a flush."""
        configurations: dict[str, tuple[dict, dict]] = {}
        for item in expansion.experiments:
            camera = next(step["args"] for step in item.steps if step["type"] == "camera_configure")
            ad2 = next(step["args"] for step in item.steps if step["type"] == "ad2_configure")
            configurations[repr((camera, ad2))] = camera, ad2
        pending = iter(configurations.values())
        def configure_next() -> None:
            try:
                camera, ad2 = next(pending)
            except StopIteration:
                done()
                return
            def waveform(value):
                for channel in value.channels:
                    if channel.enabled and (channel.trigger.wait_s + channel.trigger.run_s
                                            >= ad2["output_timeout_s"]):
                        self._fail("Applied waveform window exceeds the bounded output timeout")
                        return
                dio = ad2["dio"]
                self._command(DeviceId.AD2, DeviceOperation.AD2_EXPERIMENT_DIGITAL_CONFIGURE,
                              Ad2ExperimentDigitalArgs(dio["frame_count"], dio["frame_rate_hz"],
                                                       dio["camera_delay_s"]),
                              lambda value: applied(value))
            def applied(value):
                if value.global_run_s >= ad2["output_timeout_s"]:
                    self._fail("Achieved DigitalOut window exceeds the bounded output timeout")
                    return
                # _after_camera_timing()'s earlier check only compared the
                # REQUESTED frame rate against live camera limits -- a
                # legal request can still fail here, because the AD2's own
                # clock division rounds the requested rate to whatever its
                # hardware divider can actually produce, and the ACHIEVED
                # rate (now known, from this same real configuration
                # round-trip) can be higher than requested, shortening the
                # real frame interval below what the camera can sustain.
                # Reusing the existing CAMERA_TIMING_READ round-trip here
                # (not a new check system) gets the limits that actually
                # apply to this exposure/ROI, read fresh after
                # _configure_camera() above has genuinely applied them --
                # not whatever the camera happened to report before any
                # experiment-specific configuration this round.
                achieved_interval = 1 / value.achieved_frame_rate_hz
                def checked(timing):
                    # Read the exposure actually applied, not the
                    # requested camera["exposure_ms"] dict value -- DCAM
                    # (and camera SDKs generally) can quantize a requested
                    # exposure to a different real value (confirmed on
                    # real hardware previously: a 15.0ms request read back
                    # as 15.00025ms). Reuses the existing
                    # CAMERA_SETTINGS_READ/read_exposure_time() round-trip;
                    # not a new check path.
                    def with_applied_exposure(readback):
                        applied_exposure_ms = readback.exposure_ms
                        if applied_exposure_ms is None:
                            # Backend doesn't report a real readback (no
                            # read_exposure_time()) -- nothing to check
                            # against but the request; not silently
                            # treated as "no exposure," which would pass
                            # every interval.
                            applied_exposure_ms = camera["exposure_ms"]
                        if applied_exposure_ms / 1000 >= achieved_interval:
                            self._fail(
                                f"Achieved frame interval {achieved_interval:g}s (AD2 rounded the "
                                f"requested {ad2['dio']['frame_rate_hz']:g} Hz to "
                                f"{value.achieved_frame_rate_hz:g} Hz) does not leave room for the "
                                f"actually-applied {applied_exposure_ms:g} ms exposure (requested "
                                f"{camera['exposure_ms']:g} ms)")
                            return
                        minimum = timing.minimum_trigger_interval_s
                        if minimum is not None and achieved_interval < minimum:
                            self._fail(
                                f"Achieved frame interval {achieved_interval:g}s is below the live SDK "
                                f"minimum {minimum:g}s, even though the requested rate "
                                f"{ad2['dio']['frame_rate_hz']:g} Hz was not -- the AD2's own clock "
                                f"division rounded the achieved rate to {value.achieved_frame_rate_hz:g} Hz")
                            return
                        if timing.readout_time_s is not None and achieved_interval < timing.readout_time_s:
                            self._fail(
                                f"Achieved frame interval {achieved_interval:g}s is below this "
                                f"ROI/exposure's readout time {timing.readout_time_s:g}s (achieved rate "
                                f"{value.achieved_frame_rate_hz:g} Hz)")
                            return
                        storage.event("configuration_preflight", camera=camera, ad2=ad2,
                                      applied_digital=json_ready(value), applied_camera_timing=json_ready(timing),
                                      applied_exposure_ms=applied_exposure_ms)
                        configure_next()
                    self._command(DeviceId.CAMERA, DeviceOperation.CAMERA_SETTINGS_READ,
                                  NoArguments(), with_applied_exposure)
                self._command(DeviceId.CAMERA, DeviceOperation.CAMERA_TIMING_READ, NoArguments(), checked)
            self._configure_camera(camera,
                           lambda _value: self._command(DeviceId.AD2,
                                                        DeviceOperation.AD2_WAVEFORM_CONFIGURE,
                                                        self._waveform_args(ad2, self._laser_frequency_hz),
                                                        waveform))
        configure_next()

    def _run_count_preflights(self, expansion: Expansion, storage: SeriesStorage,
                              done: Callable[[], None]) -> None:
        combinations: dict[str, tuple[dict, dict]] = {}
        for item in expansion.experiments:
            camera = next(step["args"] for step in item.steps if step["type"] == "camera_configure")
            dio = next(step["args"]["dio"] for step in item.steps if step["type"] == "ad2_configure")
            combinations[repr((camera, dio))] = camera, dio
        pairs = iter(combinations.values())
        def next_pair() -> None:
            try:
                camera, dio = next(pairs)
            except StopIteration:
                done()
                return
            expected_window = dio["camera_delay_s"] + dio["frame_count"] / dio["frame_rate_hz"]
            bounded_window = max(2.0, expected_window * 1.5 + 1.0)
            collection_started = 0.0
            applied_dio = None
            guard = QTimer(self)
            guard.setSingleShot(True)
            guard.timeout.connect(lambda: self._fail("Count preflight exceeded the expected frame window"))
            self._timers.append(guard)
            def release_guard() -> None:
                guard.stop()
                if guard in self._timers:
                    self._timers.remove(guard)
                guard.deleteLater()
            def configured(_value):
                self._command(DeviceId.AD2, DeviceOperation.AD2_EXPERIMENT_DIGITAL_CONFIGURE,
                              Ad2ExperimentDigitalArgs(dio["frame_count"], dio["frame_rate_hz"],
                                                       dio["camera_delay_s"], led_enabled=False), armed_camera)
            def armed_camera(value):
                nonlocal applied_dio
                applied_dio = json_ready(value)
                self._command(DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_ARM, NoArguments(), armed_dio)
            def armed_dio(_value):
                self._command(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_START, NoArguments(), trigger)
            def trigger(_value):
                self._command(DeviceId.AD2, DeviceOperation.AD2_SOFTWARE_TRIGGER, NoArguments(), collect)
            def collect(_value):
                nonlocal collection_started
                collection_started = monotonic()
                guard.start(round(bounded_window * 1000))
                self._command(DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_COLLECT, NoArguments(), check)
            def check(result):
                release_guard()
                if monotonic() - collection_started > bounded_window:
                    self._fail("Count preflight exceeded the expected frame window")
                    return
                if len(result.frames) != camera["frame_count"] or len(result.timestamps) != camera["frame_count"]:
                    self._fail("Count-only timing preflight did not collect exactly N timestamped frames")
                    return
                def finished_digital() -> None:
                    storage.event("count_preflight", camera=camera, dio=dio,
                                  applied_dio=applied_dio,
                                  collected_frames=len(result.frames),
                                  physical_dio0_edges_verified=False,
                                  note="No loopback: finite camera buffer cannot prove absence of extra DIO0 edges")
                    self._command(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_STOP, NoArguments(),
                                  lambda _value: next_pair())
                self._wait_preflight_digital_done(
                    monotonic() + max(2.0, expected_window + 2),
                    finished_digital,
                )
            preflight_camera = dict(camera)
            preflight_camera["frame_timeout_s"] = max(
                0.5, dio["camera_delay_s"] + 2 / dio["frame_rate_hz"]
            )
            self._configure_camera(preflight_camera, configured)
        self._command(DeviceId.AD2, DeviceOperation.AD2_WAVEFORM_STOP, NoArguments(),
                      lambda _value: next_pair())

    def _wait_preflight_digital_done(self, deadline: float, done: Callable[[], None]) -> None:
        def poll() -> None:
            self._command(DeviceId.AD2, DeviceOperation.AD2_OUTPUT_STATUS_READ, NoArguments(), check)
        def check(value: Any) -> None:
            if value.digital_state == "done":
                done()
            elif monotonic() >= deadline:
                self._fail("Count preflight DigitalOut did not report Done")
            else:
                QTimer.singleShot(100, poll)
        poll()

    def _begin_steps(self, expansion: Expansion, storage: SeriesStorage) -> None:
        storage.status("running", {})
        self._preview(lambda: self._run_nodes(list(expansion.steps), lambda: self._complete_series(storage)))

    def _close_temperature_recorder(self, done: Callable[[], None]) -> None:
        """Drain, error-check, and close the series' TemperatureRecorder
        (if one is open) before calling done(). Shared by normal series
        completion and stop_after_current -- a series that just ended must
        stop accepting further temperature samples (attach_temperature_monitor()'s
        standing connection keeps delivering them regardless of series
        state) and must not be left open for the next series' own
        recorder to silently replace without ever closing it."""
        if self._recorder is None:
            done()
            return
        self._recorder.close()
        if not self._recorder.drained():
            QTimer.singleShot(50, lambda: self._close_temperature_recorder(done))
            return
        error = self._recorder.error()
        self._recorder = None
        if error:
            self._fail(f"Temperature log write failed: {error}")
            return
        done()

    def _complete_series(self, storage: SeriesStorage) -> None:
        self._close_temperature_recorder(lambda: self._finish_series_completed(storage))

    def _finish_series_completed(self, storage: SeriesStorage) -> None:
        if self._failed or self._abort_requested:
            # Something (panic/abort/a failure) finalized this batch while
            # this callback's own recorder-drain wait (_close_temperature_recorder(),
            # scheduled before that happened) was still pending.
            # _finish_failure_when_safe() is already the authoritative
            # finalizer for this series now -- writing "completed" here
            # too would leave disk and memory disagreeing about how the
            # series actually ended.
            return
        storage.status("completed", {"completed_experiments":
                                      self._completed - self._series_completed_at_start})
        self._series_states[storage.folder] = "completed"
        storage.event("series_completed")
        self._current = None
        self._experiment = None
        self._phase = "Series completed"
        self._publish()
        QTimer.singleShot(0, self._next_series)

    def _run_nodes(self, steps: list[dict[str, Any]], done: Callable[[], None]) -> None:
        if self._failed or self._abort_requested:
            return
        if not steps:
            done()
            return
        node, rest = steps[0], steps[1:]
        kind = node["type"]
        continuation = lambda: self._run_nodes(rest, done)
        if kind == "experiment":
            expansion, storage = self._current
            self._experiment = next(item for item in expansion.experiments
                                    if item.experiment_id == node["experiment_id"])
            self._experiment_frames_saved = False
            self._phase = "Configuring instruments"
            self._capture = None
            self._triggered_at = None
            self._settings = {}
            self._applied = {}
            storage.event("experiment_started", experiment_id=self._experiment.experiment_id)
            storage.record_experiment_started()
            self._publish()
            def finished() -> None:
                try:
                    storage.finalize_experiment(self._experiment, {
                        "completion_utc": datetime.now(timezone.utc).isoformat(),
                        "applied_settings": dict(self._applied),
                        "device_readbacks": {device.value: json_ready(status.readback)
                                             for device, status in self.controller.statuses().items()},
                    })
                except Exception as exc:
                    self._fail(f"Final experiment metadata could not be written: {exc}")
                    return
                self._completed += 1
                if self._last_saved and self._last_saved["experiment_id"] == self._experiment.experiment_id:
                    self._last_saved = {**self._last_saved, "outcome": "completed"}
                self._phase = "Experiment completed"
                storage.event("experiment_completed", experiment_id=self._experiment.experiment_id)
                storage.record_experiment_completed()
                self._experiment = None
                self._publish()
                if self._stop_after_current:
                    def finish_stop() -> None:
                        if self._failed or self._abort_requested:
                            # Same reasoning as _finish_series_completed():
                            # panic/abort/a failure already finalized this
                            # batch while this callback's own recorder-drain
                            # wait was pending -- do not also write
                            # "stopped_after_current" over whatever
                            # _finish_failure_when_safe() already recorded.
                            return
                        storage.status("stopped_after_current", {"completed_experiments":
                                                                 self._completed - self._series_completed_at_start})
                        self._series_states[storage.folder] = "stopped"
                        self._current = None
                        self._approved = 0
                        self._state = "stopped"
                        self._phase = "Stopped after current experiment"
                        self._publish()
                    # Same reasoning as normal series completion
                    # (_complete_series()): the series is done the moment
                    # this experiment finishes, so its TemperatureRecorder
                    # must stop accepting samples and be fully drained/
                    # closed now -- not left open for
                    # attach_temperature_monitor()'s standing connection to
                    # keep writing into after the series is already
                    # reported "stopped," and not silently overwritten,
                    # unclosed, by whatever series starts next. This does
                    # not touch TEC output itself -- only the log file.
                    self._close_temperature_recorder(finish_stop)
                    return
                continuation()
            self._run_nodes(node["steps"], finished)
        elif kind == "parallel":
            remaining = len(node["branches"])
            self._parallel_depth += 1
            self._phase = ("Saving frames + waiting for outputs/flush"
                           if any(any(step["type"] == "save_frames" for step in branch)
                                  for branch in node["branches"]) else "Parallel steps running")
            self._publish()
            def branch_done() -> None:
                nonlocal remaining
                remaining -= 1
                if remaining == 0 and not self._failed:
                    self._parallel_depth -= 1
                    continuation()
            for branch in node["branches"]:
                self._run_nodes(branch, branch_done)
        else:
            self._run_action(node, continuation)

    def _run_action(self, node: dict[str, Any], done: Callable[[], None]) -> None:
        kind, args = node["type"], node["args"]
        previous, finish = self._previous_action, done

        def done() -> None:
            self._previous_action = kind
            finish()
        if not self._parallel_depth:
            # A timed wait is named for what precedes it: it is never reported as a stability check.
            wait_phase = {"tec_wait_stable": "Holding after temperature stability",
                          "tec_set": "Fixed wait after setting temperature"}.get(previous or "", "Timed wait")
            self._phase = {
                "flush": "Flushing", "wait": wait_phase,
                "tec_set": "Setting temperature", "tec_wait_stable": "Checking temperature stability",
                "stage_move": "Moving Z-stage", "camera_configure": "Configuring camera",
                "ad2_configure": "Configuring AD2", "camera_arm": "Arming camera",
                "ad2_arm": "Arming AD2", "pc_trigger": "Triggering acquisition",
                "await_frames": "Acquiring frames", "wait_outputs": "Waiting for AD2 outputs",
                "save_frames": "Saving frames",
            }.get(kind, kind)
            self._publish()
        # Include argument construction in failure handling, not just submission.
        # This covers dataclass validation before controller.submit() is called.
        # The TEC polling interval below already adapts to a short max_wait_s.
        try:
            if kind == "flush":
                command = WorkflowCommand(WorkflowOperation.FLUSH,
                                          FlushArgs(**args), source="experiment")
                self._submit(command, lambda value: self._record("flush", args, value, done))
            elif kind == "wait":
                self._submit(WorkflowCommand(WorkflowOperation.WAIT, WaitArgs(**args), source="experiment"),
                             lambda _value: done())
            elif kind == "tec_set":
                self._command(DeviceId.TEC, DeviceOperation.TEC_SETPOINTS_APPLY,
                              TecApplySetpointsArgs(**self._tec_args(args)),
                              lambda value: self._record("tec_set", args, value, done))
            elif kind == "tec_wait_stable":
                tec_args = self._tec_args(args)
                # poll_interval_s is not part of the declarative schema (no
                # caller can set it) and TecWaitStableArgs requires
                # poll_interval_s <= max_wait_s -- rather than reject a
                # short max_wait_s, make the poll interval consistent with
                # whatever max_wait_s actually is. A real device still gets
                # at least one check at t=0 (hal/tec.py's defer_operation
                # starts its timer at 0) and, for a sub-1s max_wait_s, one
                # more at the deadline; this is not a new framework, just
                # computing one already-existing field from another.
                tec_args["poll_interval_s"] = min(1.0, tec_args["max_wait_s"])
                self._command(DeviceId.TEC, DeviceOperation.TEC_WAIT_STABLE,
                              TecWaitStableArgs(**tec_args),
                              lambda value: self._record("tec_wait_stable", args, value, done))
            elif kind == "stage_move":
                self._command(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_POSITION_SET,
                              ZStageSetPositionArgs(**args), lambda value: self._record("stage_move", args, value, done))
            elif kind == "camera_configure":
                self._settings[kind] = args
                self._configure_camera(args, lambda _value: done())
            elif kind == "ad2_configure":
                self._settings[kind] = args
                self._command(DeviceId.AD2, DeviceOperation.AD2_WAVEFORM_CONFIGURE,
                              self._waveform_args(args, self._laser_frequency_hz),
                              lambda value: self._ad2_digital_after_waveform(args, value, done))
            elif kind == "camera_arm":
                self._command(DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_ARM, NoArguments(),
                              lambda _value: done())
            elif kind == "ad2_arm":
                self._command(DeviceId.AD2, DeviceOperation.AD2_WAVEFORM_START, NoArguments(),
                              lambda _value: self._command(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_START,
                                                           NoArguments(), lambda _value: done()))
            elif kind == "pc_trigger":
                self._command(DeviceId.AD2, DeviceOperation.AD2_SOFTWARE_TRIGGER, NoArguments(),
                              lambda _value: self._mark_trigger(done))
            elif kind == "await_frames":
                self._command(DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_COLLECT, NoArguments(),
                              lambda value: self._frames_collected(value, done))
            elif kind == "wait_outputs":
                self._wait_outputs(done)
            elif kind == "save_frames":
                self._save_frames(done)
            else:
                self._fail(f"Unsupported execution action {kind}")
        except Exception as exc:
            self._fail(f"{kind} step rejected its own arguments: {exc}")

    def _record(self, name: str, requested: Any, applied: Any, done: Callable[[], None]) -> None:
        if name == "flush":
            self._settings.setdefault("flushes", []).append(requested)
            self._applied.setdefault("flushes", []).append({"status": "completed"})
        elif name == "stage_move":
            # The controller accepted a (possibly clamped) target; the step does not wait for
            # the stage or read its position, so it is not recorded as an applied position.
            self._settings[name] = requested
            self._applied[name] = {"requested_um": requested["position_um"],
                                   "sent_um": applied.position_um, "position_confirmed": False}
        else:
            self._settings[name] = requested
            self._applied[name] = json_ready(applied)
        done()

    def _ad2_digital_after_waveform(self, args: dict[str, Any], waveform: Any,
                                    done: Callable[[], None]) -> None:
        self._applied["ad2_waveform"] = json_ready(waveform)
        dio = args["dio"]
        self._command(DeviceId.AD2, DeviceOperation.AD2_EXPERIMENT_DIGITAL_CONFIGURE,
                      Ad2ExperimentDigitalArgs(dio["frame_count"], dio["frame_rate_hz"],
                                               dio["camera_delay_s"]),
                      lambda value: self._record("ad2_digital", dio, value, done))

    def _frames_collected(self, value: CameraSequenceResult, done: Callable[[], None]) -> None:
        expected = self._settings["camera_configure"]["frame_count"]
        if len(value.frames) != expected or len(value.timestamps) != expected or any(not item for item in value.timestamps):
            self._fail("Incomplete sequence or missing SDK timestamp")
            return
        self._capture = value
        # Queue live preview immediately, but do not wait for camera setup
        # before dispatching the independent host-file save branch.
        self._preview(lambda: None)
        done()

    def _mark_trigger(self, done: Callable[[], None]) -> None:
        self._triggered_at = monotonic()
        done()

    def _wait_outputs(self, done: Callable[[], None]) -> None:
        settings = self._settings["ad2_configure"]
        deadline = (self._triggered_at or monotonic()) + settings["output_timeout_s"]
        def poll() -> None:
            self._command(DeviceId.AD2, DeviceOperation.AD2_OUTPUT_STATUS_READ, NoArguments(), check)
        def check(value: Any) -> None:
            enabled = [settings["ultrasound"]["enabled"], settings["laser"]["enabled"]]
            complete = value.digital_state == "done" and all(
                not enabled[index] or state == "done"
                for index, state in enumerate(value.waveform_states)
            )
            if complete:
                self._applied["output_completion"] = json_ready(value)
                self._command(DeviceId.AD2, DeviceOperation.AD2_WAVEFORM_STOP, NoArguments(),
                              lambda _value: self._command(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_STOP,
                                                           NoArguments(), lambda _value: done()))
            elif monotonic() >= deadline:
                self._fail("AD2 outputs did not report Done within the bounded output window")
            else:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda: (self._timers.remove(timer), timer.deleteLater(), poll()))
                self._timers.append(timer)
                timer.start(100)
        poll()

    def _save_frames(self, done: Callable[[], None]) -> None:
        if self._capture is None or self._experiment is None or self._current is None:
            self._fail("No complete sequence to save")
            return
        storage = self._current[1]
        metadata = {"requested_settings": dict(self._settings),
                    "applied_settings": dict(self._applied),
                    "device_readbacks": {device.value: json_ready(status.readback)
                                         for device, status in self.controller.statuses().items()},
                    "saved_utc": datetime.now(timezone.utc).isoformat()}
        future = self._file_worker.submit(storage, self._experiment, self._capture, metadata)
        self._file_futures.add(future)
        def poll() -> None:
            if not future.done():
                QTimer.singleShot(50, poll)
                return
            self._file_futures.discard(future)
            try:
                record = future.result()
            except Exception as exc:
                self._fail(f"Saving experiment images failed: {exc}")
                return
            storage.event("frames_saved", experiment_id=record["experiment_id"],
                          frame_count=record["frame_count"])
            self._experiment_frames_saved = True
            experiment = self._experiment
            if experiment is not None:
                self._last_saved = {
                    "series_folder": str(storage.folder), "experiment_id": experiment.experiment_id,
                    "experiment_folder": str((storage.folder / experiment.relative_path).resolve()),
                    "parameters": dict(experiment.parameters), "repeat_index": experiment.repeat_index,
                    "frame_count": record["frame_count"], "outcome": "saved", "reason": ""}
                self._publish()
            done()
        QTimer.singleShot(0, poll)

    def _preview(self, done: Callable[[], None]) -> None:
        self._command(DeviceId.CAMERA, DeviceOperation.CAMERA_CONTINUOUS_CAPTURE,
                      CameraConfigureSnapshotArgs(), lambda _value: done())

    @staticmethod
    def _tec_args(args: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(args)
        targets = normalized.get("target_temperature_c")
        if isinstance(targets, dict):
            normalized["target_temperature_c"] = {int(channel): value
                                                   for channel, value in targets.items()}
        if "channels" in normalized:
            normalized["channels"] = tuple(int(channel) for channel in normalized["channels"])
        return normalized

    @staticmethod
    def _camera_args(args: dict[str, Any]) -> CameraConfigureSequenceArgs:
        return CameraConfigureSequenceArgs(
            args["frame_count"], args["exposure_ms"], args.get("frame_timeout_s", 30),
            trigger=CameraSequenceTriggerArgs(
                source=CameraTriggerSource.EXTERNAL,
                polarity=CameraTriggerPolarity.POSITIVE,
                active=CameraTriggerActive.EDGE,
                global_exposure=args["global_exposure"],
            ),
        )

    def _configure_camera(self, args: dict[str, Any], done: Callable[[Any], None]) -> None:
        def configure_sequence(_value=None) -> None:
            self._command(DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_CONFIGURE,
                          self._camera_args(args), done)
        roi = args.get("roi")
        if roi is None:
            configure_sequence()
        else:
            self._command(DeviceId.CAMERA, DeviceOperation.CAMERA_ROI_CONFIGURE,
                          CameraConfigureRoiArgs(roi["x"], roi["y"], roi["width"], roi["height"]),
                          configure_sequence)

    @staticmethod
    def _waveform_args(args: dict[str, Any], laser_frequency_hz: float | None) -> Ad2ConfigureWaveformArgs:
        if laser_frequency_hz is None:
            raise RuntimeError("WFG2 minimum frequency was not checked before configuration")
        channels = []
        for index, key in enumerate(("ultrasound", "laser")):
            output = args[key]
            trigger = Ad2TriggerSettingsArgs(source=Ad2TriggerSource.PC,
                                             wait_s=output["start_s"],
                                             run_s=output["run_s"], repeat_count=1)
            channels.append(Ad2WaveformChannelArgs(
                channel_index=index, enabled=output["enabled"],
                function=Ad2WaveformFunction.SINE if index == 0 else Ad2WaveformFunction.SQUARE,
                frequency_hz=output["frequency_hz"] if index == 0 else laser_frequency_hz,
                amplitude_v=output["amplitude_v"] if index == 0 else output["on_voltage_v"],
                offset_v=output["offset_v"] if index == 0 else 0.0,
                idle_state=Ad2AnalogOutputIdle.OFFSET,
                fm_enabled=index == 0 and "sweep_width_hz" in output,
                fm_function=Ad2WaveformFunction.TRIANGLE,
                fm_frequency_hz=(1000.0 / output["sweep_period_ms"]
                                 if index == 0 and "sweep_width_hz" in output else 1000.0),
                fm_modulation_index_percent=(50.0 * output["sweep_width_hz"] / output["frequency_hz"]
                                             if index == 0 and "sweep_width_hz" in output else 0.0),
                trigger=trigger,
            ))
        return Ad2ConfigureWaveformArgs(channels=tuple(channels))

    def _command(self, device: DeviceId, operation: DeviceOperation, arguments: Any,
                 callback: Callable[[Any], None]) -> None:
        self._submit(DeviceCommand(device, operation, arguments, source="experiment"), callback)

    def _submit(self, command: DeviceCommand | WorkflowCommand,
                callback: Callable[[Any], None]) -> None:
        if self._failed or self._abort_requested:
            return
        self._callbacks[command.request_id] = callback
        try:
            self.controller.submit(command)
        except Exception as exc:
            self._callbacks.pop(command.request_id, None)
            self._fail(str(exc))

    def _command_result(self, result: Any) -> None:
        stopped = self._stop_pending.pop(result.request_id, None)
        if stopped is not None:  # a stop this batch asked for: note a failure, never run a step callback
            error = str(result.error or "")
            if not result.ok and not error.startswith("Cancelled by Panic"):  # Panic sends its own stops
                self._stop_failures.append(f"{stopped.value}: {error or 'safe stop failed'}")
            return
        callback = self._callbacks.pop(result.request_id, None)
        if callback is None or self._failed or self._abort_requested:
            return
        if not result.ok:
            self._fail(result.error or f"{result.operation.value} failed")
            return
        callback(result.value)

    def _fail(self, reason: str, *, stop_outputs: bool = True) -> None:
        if self._failed:
            return
        self._failed = True
        if self._recorder is not None:
            self._recorder.close()
        for timer in self._timers:
            timer.stop()
            timer.deleteLater()
        self._timers.clear()
        self._failure_reason = reason
        self._state = "stopping"
        self._phase = f"Safe stop after failure: {reason}"
        # Stop active electrical/camera outputs. An already-started flush is
        # allowed to perform its own valve/pump cleanup; a host-owned file save
        # is allowed to finish. No subsequent experiment is dispatched.
        if stop_outputs:
            self._cancel_active_tec_wait()
            self._request_stops((DeviceId.AD2, DeviceId.CAMERA))  # skips what Abort already asked
        self._finish_failure_when_safe()

    def _cancel_active_tec_wait(self) -> None:
        """End a running TEC stability wait so it stops polling and frees the command lane.

        This cancels the wait only (the worker's cancel hook leaves regulation
        on); switching the TEC output off stays a separate action (Panic/exit).
        """
        active = self.controller.active_device_command()
        if (active is not None and active.device is DeviceId.TEC
                and active.operation is DeviceOperation.TEC_WAIT_STABLE):
            try:
                self.controller.submit(DeviceCommand(DeviceId.TEC, DeviceOperation.ABORT_ACTIVE,
                                                     NoArguments(), source="experiment"))
            except RuntimeError:
                pass

    def _finish_failure_when_safe(self) -> None:
        if self._failure_reason is None:
            return
        # self._file_futures must be genuinely EMPTY here, not merely
        # "every future is done()". A save Future can finish on its
        # background thread (future.done() == True) before _save_frames()'s
        # own poll() callback -- the only thing that sets
        # self._experiment_frames_saved and removes the future from this
        # set -- has actually run; that callback is only scheduled, not
        # guaranteed to have executed yet, at the moment a failure on the
        # OTHER parallel branch (e.g. the post-acquisition flush) reaches
        # here. Checking future.done() instead of set membership would
        # read _experiment_frames_saved before poll() had a chance to set
        # it, and wrongly discard data that genuinely exists.
        if (self.controller._flush is not None or bool(self._file_futures) or bool(self._stop_pending)
                or (self._recorder is not None and not self._recorder.drained())):
            QTimer.singleShot(100, self._finish_failure_when_safe)
            return
        self._recorder = None
        reason = self._failure_reason
        if self._stop_failures:  # every stop has returned: a failed one is part of how this ended
            reason += "; safe stop problems: " + "; ".join(self._stop_failures)
            if self._current is not None:
                self._current[1].event("safe_stop_failed", failures=list(self._stop_failures))
        if self._current is not None and self._experiment is not None:
            storage = self._current[1]
            storage.record_experiment_failed()
            if self._experiment_frames_saved:
                # Images/timestamps/parameters for this experiment are
                # already genuinely written to disk (_save_frames()
                # returned before this failure happened, e.g. a
                # post-acquisition flush failing afterward) -- discarding
                # the directory would destroy real, successfully-captured
                # data over an unrelated later failure. record_experiment_failed()
                # above already keeps this out of the "completed" count,
                # so acquisition success and overall experiment success
                # stay visibly distinct; the failed step/reason is recorded
                # on the experiment's own existing metadata file rather
                # than inventing a parallel record of it.
                try:
                    storage.finalize_experiment(self._experiment, {
                        "completion_utc": datetime.now(timezone.utc).isoformat(),
                        "outcome": "failed",
                        "error": reason,
                    })
                except Exception as exc:
                    reason += f"; failure outcome could not be recorded on the saved experiment: {exc}"
                storage.event("experiment_preserved_after_later_failure",
                              experiment_id=self._experiment.experiment_id, reason=reason)
                if self._last_saved and self._last_saved["experiment_id"] == self._experiment.experiment_id:
                    # An operator abort (or Panic) after the images were written is not a device or saving
                    # fault: say which, and let the reason carry the details.
                    outcome = "aborted_after_save" if self._abort_requested else "failed_after_save"
                    self._last_saved = {**self._last_saved, "outcome": outcome, "reason": reason}
            else:
                incomplete = (storage.folder / self._experiment.relative_path).resolve()
                if not incomplete.is_relative_to(storage.folder.resolve()):
                    reason += "; unsafe unfinished experiment path could not be discarded"
                elif incomplete.is_dir():
                    try:
                        shutil.rmtree(incomplete)
                        storage.event("incomplete_experiment_discarded",
                                      experiment_id=self._experiment.experiment_id)
                    except OSError as exc:
                        reason += f"; unfinished experiment files could not be discarded: {exc}"
        self._state = "failed" if not self._abort_requested else "aborted"
        # Wording only: an operator abort is not a device or saving fault. The persisted state,
        # status.json `error` and the series_failed event keep their existing values.
        self._phase = (f"Experiment batch aborted: {reason}" if self._state == "aborted"
                       else f"Experiment series failed: {reason}")
        if self._current is not None:
            storage = self._current[1]
            self._series_states[storage.folder] = self._state
            storage.event("series_failed", reason=reason,
                          experiment_id=self._experiment.experiment_id if self._experiment else None)
            storage.status(self._state, {"error": reason,
                                         "completed_experiments": self._completed - self._series_completed_at_start})
        for _, storage in self._queued:
            self._series_states[storage.folder] = "cancelled"
            storage.status("cancelled", {"reason": f"Earlier series failed: {reason}"})
        self._queued.clear()
        self._approved = 0
        self._current = None
        self._experiment = None
        self._failure_reason = None
        self.notice.emit(reason)
        self._publish()

    def close(self) -> None:
        if self._recorder is not None:
            self._recorder.close()
        self._file_worker.close()
