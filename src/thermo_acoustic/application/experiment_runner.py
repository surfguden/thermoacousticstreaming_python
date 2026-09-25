"""Nonblocking application-owned execution of declarative experiment series."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import math
import json
import shutil
import sys
from time import monotonic
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from ..domain.models import ConnectionState, DeviceId, OperatingMode, PumpReadback
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


class ExperimentManager(QObject):
    changed = Signal(object)
    notice = Signal(str)

    def __init__(self, controller, *, confirm_batch: Callable[[str], bool] | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.confirm_batch = confirm_batch or (lambda _summary: False)
        self.confirm_unchecked: Callable[[str], bool] = lambda _summary: True
        self._simple_preflight_passes: dict[str, tuple[int, float | None]] = {}
        self._queued: deque[tuple[Expansion, SeriesStorage]] = deque()
        self._batch_items: list[tuple[Expansion, SeriesStorage]] = []
        self._series_states: dict[Path, str] = {}
        self._approved = 0
        self._current: tuple[Expansion, SeriesStorage] | None = None
        self._experiment: PlannedExperiment | None = None
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
        self._failed = False
        self._failure_reason = None
        self._state = "idle"
        self._completed = 0
        self._planned_total = 0
        self._batch_completed_at_start = 0
        self._batch_series_total = 0
        self._phase = "Idle"
        self._parallel_depth = 0
        self._series_completed_at_start = 0
        controller.command_result.connect(self._command_result)

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

    def queue(self, definition: dict[str, Any], output_root: str | Path,
              image_format: str | None = None) -> Path:
        if self._state in {"running", "stopping", "aborting"}:
            raise RuntimeError("Cannot queue a series while an experiment batch is running")
        if self.controller.panic_status()["state"] == "stopping":
            raise RuntimeError("Cannot queue a series during Panic safe stop")
        if not isinstance(definition.get("description"), str) or not definition["description"].strip():
            raise ValueError("Enter a series descriptor before queueing")
        definition = {**definition, "description": definition["description"].strip()}
        if self._state in {"completed", "failed", "aborted", "stopped"}:
            self._state = "idle"
            self._phase = "Idle"
            self._planned_total = 0
            self._batch_series_total = 0
            self._batch_completed_at_start = self._completed
            self._batch_items = []
            self._series_states.clear()
            self._batch_output_root = None
        expansion = validate_definition(definition)
        output = Path(output_root).expanduser().resolve()
        if self._batch_output_root is not None and output != self._batch_output_root:
            raise ValueError("All queued series in one batch must use the same experiment base folder")
        storage = SeriesStorage(output, expansion,
                                image_format or definition.get("tiff_format", "frames"),
                                continuing_batch=self._batch_output_root is not None)
        self._batch_output_root = output
        self._queued.append((expansion, storage))
        self._series_states[storage.folder] = "queued"
        self._publish()
        return storage.folder

    def status(self) -> dict[str, Any]:
        queued = self._batch_items if self._batch_items else list(self._queued)
        queue_details = []
        pump = self.controller.statuses()[DeviceId.PUMP].readback
        for expansion, storage in queued:
            passed = False
            if expansion.definition.get("simple_series"):
                fingerprint = json.dumps(expansion.definition, sort_keys=True, allow_nan=False)
                proof = self._simple_preflight_passes.get(fingerprint)
                if proof is not None and isinstance(pump, PumpReadback):
                    unit = next((item for item in pump.units if item.unit_index == proof[0]), None)
                    passed = unit is not None and unit.fill_level_ml == proof[1]
            queue_details.append({"description": expansion.definition["description"],
                                  "folder": str(storage.folder),
                                  "experiment_count": len(expansion.experiments),
                                  "preflight_passed": passed,
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
                "current_series": str(self._current[1].folder) if self._current else None,
                "current_experiment": self._experiment.experiment_id if self._experiment else None,
                "completed_experiments": self._completed,
                "stop_after_current": self._stop_after_current}

    def _publish(self) -> None:
        self.changed.emit(self.status())

    def start(self) -> bool:
        if self.controller.panic_status()["state"] == "stopping":
            raise RuntimeError("Wait for Panic safe stop to finish before starting a batch")
        if self.controller.count_preflight_active:
            raise RuntimeError("Wait for count preflight to finish before starting a batch")
        if self._current is not None or self._state == "running":
            raise RuntimeError("An experiment batch is already running")
        if not self._queued:
            raise RuntimeError("Queue at least one experiment series")
        unchecked = []
        for expansion, _storage in self._queued:
            if not expansion.definition.get("simple_series"):
                continue
            fingerprint = json.dumps(expansion.definition, sort_keys=True, allow_nan=False)
            proof = self._simple_preflight_passes.get(fingerprint)
            unit = next(item["args"]["unit_index"] for item in expansion.steps
                        if item["type"] == "flush")
            pump = self.controller.statuses()[DeviceId.PUMP].readback
            current = next((item.fill_level_ml for item in pump.units if item.unit_index == unit), None) \
                if isinstance(pump, PumpReadback) else None
            if proof != (unit, current):
                unchecked.append(expansion.definition["name"])
        if unchecked and not self.confirm_unchecked(
            f"Count preflight has not passed for {len(unchecked)} queued simple series with their current "
            "settings and syringe level. Continue with standard Start validation?"
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
        self._state = "running"
        self._publish()
        QTimer.singleShot(0, self._next_series)
        return True

    def record_simple_preflight(self, fingerprint: str, unit_index: int,
                                fill_level_ml: float | None) -> None:
        self._simple_preflight_passes[fingerprint] = (unit_index, fill_level_ml)
        self._publish()

    def stop_after_current(self) -> None:
        if self._state != "running":
            return
        self._stop_after_current = True
        self._publish()

    def abort(self) -> None:
        if self._state != "running":
            return
        self._abort_requested = True
        self._state = "aborting"
        for timer in self._timers:
            timer.stop()
            timer.deleteLater()
        self._timers.clear()
        self.controller.cancel_active_workflow()
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE):
            if self.controller.statuses()[device].connection is ConnectionState.CONNECTED:
                self.controller.submit(DeviceCommand(device, DeviceOperation.SAFE_STOP,
                                                     NoArguments(), source="experiment"))
        self._fail("Operator aborted experiment batch")

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
        totals: dict[int, float] = {}
        def visit(items):
            for item in items:
                if item["type"] == "flush":
                    args = item["args"]
                    totals[args["unit_index"]] = totals.get(args["unit_index"], 0) + args["volume_ml"]
                elif item["type"] == "experiment":
                    visit(item["steps"])
                elif item["type"] == "parallel":
                    for branch in item["branches"]:
                        visit(branch)
        visit(expansion.steps)
        pump = status[DeviceId.PUMP].readback
        units = {unit.unit_index: unit for unit in pump.units} if isinstance(pump, PumpReadback) else {}
        if any(unit.is_pumping for unit in units.values()):
            raise RuntimeError("Stop active pump movement before starting an experiment series")
        for index, volume in totals.items():
            unit = units.get(index)
            if unit is None or unit.fill_level_ml is None:
                raise RuntimeError(f"Pump unit {index + 1} has no readable fill level")
            if unit.fill_level_ml < volume:
                raise RuntimeError(f"Pump unit {index + 1} needs {volume:g} mL total flush volume "
                                   f"but currently has {unit.fill_level_ml:g} mL")
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
            minimum = timing.minimum_trigger_interval_s
            if minimum is not None and interval < minimum:
                self._fail(f"Requested camera trigger interval {interval:g}s is below live SDK minimum {minimum:g}s")
                return
            if timing.readout_time_s is not None and interval < timing.readout_time_s:
                self._fail("Requested frame interval is below live camera readout time")
                return
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
                storage.event("configuration_preflight", camera=camera, ad2=ad2,
                              applied_digital=json_ready(value))
                configure_next()
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

    def _complete_series(self, storage: SeriesStorage) -> None:
        if self._recorder is not None:
            self._recorder.close()
            if not self._recorder.drained():
                QTimer.singleShot(50, lambda: self._complete_series(storage))
                return
            error = self._recorder.error()
            self._recorder = None
            if error:
                self._fail(f"Temperature log write failed: {error}")
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
            self._phase = "Configuring instruments"
            self._capture = None
            self._triggered_at = None
            self._settings = {}
            self._applied = {}
            storage.event("experiment_started", experiment_id=self._experiment.experiment_id)
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
                self._phase = "Experiment completed"
                storage.event("experiment_completed", experiment_id=self._experiment.experiment_id)
                self._experiment = None
                self._publish()
                if self._stop_after_current:
                    storage.status("stopped_after_current", {"completed_experiments":
                                                             self._completed - self._series_completed_at_start})
                    self._series_states[storage.folder] = "stopped"
                    self._current = None
                    self._approved = 0
                    self._state = "stopped"
                    self._phase = "Stopped after current experiment"
                    self._publish()
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
        if not self._parallel_depth:
            self._phase = {
                "flush": "Flushing", "wait": "Waiting for temperature stabilization"
                    if self._current and self._current[0].definition.get("simple_series")
                    and self._experiment is None else "Waiting",
                "tec_set": "Setting temperature", "tec_wait_stable": "Waiting for temperature stabilization",
                "stage_move": "Moving Z-stage", "camera_configure": "Configuring camera",
                "ad2_configure": "Configuring AD2", "camera_arm": "Arming camera",
                "ad2_arm": "Arming AD2", "pc_trigger": "Triggering acquisition",
                "await_frames": "Acquiring frames", "wait_outputs": "Waiting for AD2 outputs",
                "save_frames": "Saving frames",
            }.get(kind, kind)
            self._publish()
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
            self._command(DeviceId.TEC, DeviceOperation.TEC_WAIT_STABLE,
                          TecWaitStableArgs(**self._tec_args(args)),
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

    def _record(self, name: str, requested: Any, applied: Any, done: Callable[[], None]) -> None:
        if name == "flush":
            self._settings.setdefault("flushes", []).append(requested)
            self._applied.setdefault("flushes", []).append({"status": "completed"})
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
            statuses = self.controller.statuses()
            for device in (DeviceId.AD2, DeviceId.CAMERA):
                if statuses[device].connection is ConnectionState.CONNECTED:
                    try:
                        self.controller.submit(DeviceCommand(device, DeviceOperation.SAFE_STOP,
                                                             NoArguments(), source="experiment"))
                    except RuntimeError:
                        pass
        self._finish_failure_when_safe()

    def _finish_failure_when_safe(self) -> None:
        if self._failure_reason is None:
            return
        if (self.controller._flush is not None or any(not future.done() for future in self._file_futures)
                or (self._recorder is not None and not self._recorder.drained())):
            QTimer.singleShot(100, self._finish_failure_when_safe)
            return
        self._recorder = None
        reason = self._failure_reason
        if self._current is not None and self._experiment is not None:
            storage = self._current[1]
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
        self._phase = f"Experiment series failed: {reason}"
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
