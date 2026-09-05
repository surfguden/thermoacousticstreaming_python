from __future__ import annotations

from contextlib import contextmanager
from contextvars import copy_context
from datetime import datetime, timezone
import logging
from dataclasses import dataclass, field
import math
from pathlib import Path
import threading
import time
from typing import Callable

from .ad2 import coerce_do_config, coerce_wfg_config
from .commissioning_trace import CommissioningTraceRecorder, TraceState
from .hw_logging import action_phase, action_scope, log_action, run_with_timeout
from .instruments import AD2Sdk, CetoniPump, HamamatsuCamera, SimulatedAD2Sdk, Valve, ZStage
from .messages import Message, MessageName, QueueResult, UiEvent
from .queues import LabViewQueue
from .runtime_truth import (
    EvidenceBasis,
    EvidenceFreshness,
    EvidenceValue,
    RuntimeEvent,
    RuntimeEventSeverity,
    RuntimeEvidenceSnapshot,
    SubsystemEvidence,
    VerificationScope,
)
from .tec import TecController, TecPartialApplicationError
from .workflows import Experiment2, ExperimentSeries2, FlushSettings, SeriesLifecycleManifest, TemperatureSeries


logger = logging.getLogger(__name__)

# Step names for the v2 sequence-visualization feature's live progress
# events (progress("step_started"/"step_completed"/"step_failed", ...),
# consumed by run_experiment2()/flush()/run_temperature_series()'s new
# optional `progress` parameter -- see _report_step() below). Two design
# decisions, confirmed with the user, recorded here (not left only
# conversational) so they carry into UI Phase 2/3 unchanged:
#
# 1. FLUSH GRANULARITY: Flush is ONE card/step, not decomposed into
#    sub-steps -- valve position 1/pump move/valve position 2/post-wait stay
#    internal to flush()'s own body, not individually visualized.
#    flush() fires exactly one step_started/step_completed/step_failed
#    trio around its entire body, not per-internal-action events.
# 2. TEC-SCAN RENDERING: when a TEC temperature scan is enabled, the v2
#    UI is expected to show a SINGLE step-card list (not one list per
#    temperature point). The current target temperature and which point
#    in the sequence (e.g. "2 of 3") is a separate, top-level indicator
#    outside the step-card list itself; the same step-card list is
#    reused/reset visually as the sequence advances through each
#    temperature point. This is why STEP_SET_TEC_TARGET/
#    STEP_WAIT_TEC_STABLE below are their own two steps, wrapping the
#    per-repeat step list from outside (once per temperature point in
#    run_temperature_series()), not folded into run_experiment2()'s own
#    per-repeat steps.
STEP_INITIALIZE_EXPERIMENT = "InitializeExperiment"
STEP_CONFIGURE_WFG = "ConfigureWfg"
STEP_CONFIGURE_CAMERA = "ConfigureCamera"
STEP_CAPTURE_FRAMES = "CaptureFrames"
STEP_WAIT_FOR_AD2_COMPLETION = "WaitForAd2Completion"
STEP_FLUSH = "Flush"
STEP_SAVE_RESULTS = "SaveResults"
STEP_SET_TEC_TARGET = "SetTecTarget"
STEP_WAIT_TEC_STABLE = "WaitTecStable"

# Single source of truth for the per-repeat step order (v2's Phase 3
# step-progress breadcrumb, 2026-08-04, derives from this rather than
# hardcoding it separately). Deliberately excludes STEP_SET_TEC_TARGET/STEP_WAIT_TEC_STABLE
# -- see the TEC-SCAN RENDERING note above; those wrap this list from
# outside, once per temperature point, not part of the reused/reset sequence.
STEP_ORDER = (
    STEP_INITIALIZE_EXPERIMENT,
    STEP_CONFIGURE_WFG,
    STEP_CONFIGURE_CAMERA,
    STEP_CAPTURE_FRAMES,
    STEP_WAIT_FOR_AD2_COMPLETION,
    STEP_FLUSH,
    STEP_SAVE_RESULTS,
)


@contextmanager
def _report_step(progress: Callable[[str, object], None] | None, name: str):
    """Fire step_started/step_completed/step_failed around a block of real
    work, then re-raise any exception unchanged -- behavior is identical
    whether or not a progress callable is supplied. Exceptions are the
    only step_failed trigger: a step that returns normally, even with a
    "did not succeed" result (e.g. flush()'s own `return False` on a
    pump-wait timeout), is still reported step_completed -- matching this
    module's existing convention elsewhere of using fire_status_event()/
    return values, not exceptions, for expected non-exceptional stop
    conditions like abort or timeout. A live UI can tell "step ran to
    completion but the overall experiment still stopped" apart from "step
    itself raised" by also watching the existing status-event stream.
    """
    log_action(
        "run",
        name,
        evidence_stage="OBSERVED",
        verification_scope="SOFTWARE",
        status="STARTED",
        source="application._report_step",
    )
    if progress:
        progress("step_started", name)
    try:
        yield
    except Exception as exc:
        log_action(
            "run",
            name,
            evidence_stage="OBSERVED",
            verification_scope="SOFTWARE",
            status="FAILED",
            error=str(exc),
            source="application._report_step",
        )
        if progress:
            progress("step_failed", (name, str(exc)))
        raise
    else:
        log_action(
            "run",
            name,
            evidence_stage="OBSERVED",
            verification_scope="SOFTWARE",
            status="COMPLETED",
            source="application._report_step",
        )
        if progress:
            progress("step_completed", name)


@dataclass(slots=True)
class Application:
    ad2: AD2Sdk = field(default_factory=AD2Sdk)
    camera: HamamatsuCamera = field(default_factory=HamamatsuCamera)
    pump: CetoniPump = field(default_factory=CetoniPump)
    valve: Valve = field(default_factory=Valve)
    z_motor: ZStage = field(default_factory=ZStage)
    tec: TecController = field(default_factory=TecController)
    experiment_series: ExperimentSeries2 = field(default_factory=ExperimentSeries2)
    status: str = "System Not Initialized"
    main_queue: LabViewQueue = field(default_factory=lambda: LabViewQueue("Main Queue"))
    ui_events: list[UiEvent] = field(default_factory=list)
    status_events: list[str] = field(default_factory=list)
    runtime_events: list[RuntimeEvent] = field(default_factory=list)
    errors: list[BaseException | str] = field(default_factory=list)
    stop_fired: bool = False
    _running: bool = False
    cleanup_device_timeout_s: float = 5.0
    cleanup_total_timeout_s: float = 15.0
    # Set by clear_pump_fault_and_retry() below -- never anywhere else.
    # Session-scoped (not persisted to settings.json): a fresh app process
    # starts False again, matching that the underlying CAN-bus fault is a
    # live hardware condition, not a saved preference. run_experiment2()
    # copies this onto Experiment2.pump_fault_manually_cleared for every
    # repeat's data.tdms, same pattern as the sim_*/*_enabled flags below, so
    # a run whose pump fault was manually cleared this session is
    # distinguishable after the fact from one where it never faulted.
    pump_fault_manually_cleared_this_session: bool = False
    # Commissioning trace recording is an observability option over the normal
    # canonical experiment, never a second execution mode: execution behaves
    # identically whether it is off, recording, or degraded. The recorder is a
    # passive observer of the existing action stream (see commissioning_trace).
    commissioning_trace_enabled: bool = False
    commissioning_trace: CommissioningTraceRecorder | None = field(default=None, init=False, repr=False)
    _active_experiment: Experiment2 | None = field(default=None, init=False, repr=False)
    # A sequence owner calls set_experiment_series_general() before its first
    # repeat.  Keep the optional pre-repeat refresh there rather than inferring
    # a new sequence from Experiment2.repeat_id, which is local to a condition
    # and can restart at zero in a temperature scan.
    _initial_flush_pending: bool = field(default=False, init=False, repr=False)

    def create_queues(self) -> None:
        self.main_queue = LabViewQueue("Main Queue")

    def create_ui_event(self) -> None:
        self.ui_events.clear()

    def create_stop_event(self) -> None:
        self.stop_fired = False

    def register_events(self) -> None:
        # LabVIEW registers UI and stop events for the event loop. In Python the
        # lists above are the observable event streams.
        self.create_ui_event()
        self.create_stop_event()

    def enqueue_main(self, message: Message) -> None:
        self.main_queue.enqueue(message)

    def dequeue_main(self, timeout_ms: int = -1) -> QueueResult:
        return self.main_queue.dequeue(timeout_ms=timeout_ms)

    def peek_queue_main(self) -> QueueResult:
        return self.main_queue.peek()

    def flush_main_queue(self) -> list[Message]:
        return self.main_queue.flush()

    def fire_stop_event(self) -> None:
        self.stop_fired = True
        self._running = False

    def fire_ui_event(self, message: MessageName | str, data: object = None) -> None:
        self.ui_events.append(UiEvent(message=message, data=data))

    def emit_event(self, event: RuntimeEvent, *, update_legacy_status: bool = True) -> RuntimeEvent:
        self.runtime_events.append(event)
        log_action(
            event.subsystem,
            event.operation,
            evidence_stage="OBSERVED",
            verification_scope="SOFTWARE",
            status=event.severity.value,
            result=event.message,
            source="application.emit_event",
        )
        if update_legacy_status:
            self.status = event.message
            self.status_events.append(event.message)
            self.fire_ui_event(MessageName.UPDATE_STATUS, event.message)
        return event

    def fire_status_event(self, status: str) -> None:
        self.emit_event(
            RuntimeEvent.create(
                severity=RuntimeEventSeverity.INFO,
                subsystem="application",
                operation="status",
                message=status,
                may_continue=True,
            )
        )

    def runtime_evidence_snapshot(self) -> RuntimeEvidenceSnapshot:
        """Adapt current in-memory state without issuing any hardware query."""

        captured_at = datetime.now(timezone.utc)

        def live_software(value, source: str, note: str | None = None):
            return EvidenceValue(
                value=value,
                # This is current process state, not a device readback.
                # Reserve OBSERVED for values returned by a real backend.
                basis=EvidenceBasis.DERIVED,
                freshness=EvidenceFreshness.FRESH,
                verification=VerificationScope.SOFTWARE,
                observed_at_utc=captured_at,
                source_operation=source,
                note=note,
            )

        camera_real = self.camera.enabled and not self.camera.simulate
        camera = SubsystemEvidence(
            {
                "enabled": live_software(self.camera.enabled, "camera.enabled"),
                "simulated": live_software(self.camera.simulate, "camera.simulate"),
                "connected": EvidenceValue(
                    value=self.camera.handle is not None,
                    basis=EvidenceBasis.DERIVED,
                    freshness=EvidenceFreshness.CACHED,
                    verification=VerificationScope.SOFTWARE,
                    observed_at_utc=None,
                    source_operation="camera.handle",
                    note="Facade handle state; not a fresh device query.",
                ),
                "capturing": live_software(self.camera.capturing, "camera.capturing"),
                "sequence": EvidenceValue(
                    value=self.camera.sequence_config,
                    basis=EvidenceBasis.APPLIED if camera_real and self.camera.sequence_config is not None else EvidenceBasis.DERIVED,
                    freshness=EvidenceFreshness.UNKNOWN,
                    verification=VerificationScope.PROTOCOL if camera_real else VerificationScope.SOFTWARE,
                    observed_at_utc=None,
                    source_operation="camera.configure_sequence",
                    note="No hardware readback timestamp is retained.",
                ),
                "roi": EvidenceValue(
                    value=self.camera.roi,
                    basis=EvidenceBasis.APPLIED if camera_real and self.camera.roi is not None else EvidenceBasis.DERIVED,
                    freshness=EvidenceFreshness.UNKNOWN,
                    verification=VerificationScope.PROTOCOL if camera_real else VerificationScope.SOFTWARE,
                    observed_at_utc=None,
                    source_operation="camera.configure_roi/read_subregion_limits_and_value",
                    note="Physical field of view is not independently verified.",
                ),
            }
        )

        tec_real = self.tec.enabled and not self.tec.simulate
        tec_status_basis = EvidenceBasis.OBSERVED if tec_real else EvidenceBasis.DERIVED
        tec = SubsystemEvidence(
            {
                "enabled": live_software(self.tec.enabled, "tec.enabled"),
                "simulated": live_software(self.tec.simulate, "tec.simulate"),
                "initialized": live_software(self.tec.initialized, "tec.initialized"),
                "status": EvidenceValue(
                    value=dict(self.tec.last_status),
                    basis=tec_status_basis,
                    freshness=EvidenceFreshness.CACHED if tec_real else EvidenceFreshness.FRESH,
                    verification=VerificationScope.PROTOCOL if tec_real else VerificationScope.SOFTWARE,
                    observed_at_utc=self.tec.last_status_at_utc if tec_real else captured_at,
                    source_operation="tec.last_status",
                    note=(
                        "Real status timestamp marks the completed facade read; the snapshot remains cached. "
                        "Real target-temperature readback is unavailable."
                    ),
                ),
            }
        )

        pump_real = self.pump.enabled and not self.pump.simulate
        pump = SubsystemEvidence(
            {
                "enabled": live_software(self.pump.enabled, "pump.enabled"),
                "simulated": live_software(self.pump.simulate, "pump.simulate"),
                "initialized": live_software(self.pump.initialized, "pump.initialized"),
                "fill_level_ml": EvidenceValue(
                    value=self.pump.fill_level,
                    basis=EvidenceBasis.OBSERVED if pump_real and self.pump.initialized else EvidenceBasis.DERIVED,
                    freshness=EvidenceFreshness.CACHED if pump_real else EvidenceFreshness.FRESH,
                    verification=VerificationScope.PROTOCOL if pump_real else VerificationScope.SOFTWARE,
                    observed_at_utc=None if pump_real else captured_at,
                    source_operation="pump.fill_level",
                    note="Protocol readback/bookkeeping; not physical liquid-volume verification.",
                ),
                "referenced": EvidenceValue(
                    value=self.pump.referenced,
                    basis=EvidenceBasis.APPLIED if self.pump.referenced else EvidenceBasis.DERIVED,
                    freshness=EvidenceFreshness.CACHED,
                    verification=VerificationScope.PROTOCOL if pump_real else VerificationScope.SOFTWARE,
                    observed_at_utc=None,
                    source_operation="pump.reference_move",
                    note="No fresh reference-status query is made for this snapshot.",
                ),
            }
        )

        valve_real = self.valve.enabled and not self.valve.simulate
        valve_confirmed = valve_real and self.valve.status_note == "confirmed"
        valve = SubsystemEvidence(
            {
                "enabled": live_software(self.valve.enabled, "valve.enabled"),
                "simulated": live_software(self.valve.simulate, "valve.simulate"),
                "initialized": live_software(self.valve.initialized, "valve.initialized"),
                "protocol_position": EvidenceValue(
                    value=self.valve.position,
                    basis=EvidenceBasis.OBSERVED if valve_confirmed else EvidenceBasis.REQUESTED,
                    freshness=EvidenceFreshness.CACHED,
                    verification=VerificationScope.PROTOCOL if valve_confirmed else VerificationScope.UNVERIFIED,
                    observed_at_utc=None,
                    source_operation="valve.status_note",
                    note=self.valve.status_note or "No protocol confirmation retained.",
                ),
                "physical_route": EvidenceValue(
                    value=None,
                    basis=EvidenceBasis.DERIVED,
                    freshness=EvidenceFreshness.UNKNOWN,
                    verification=VerificationScope.UNVERIFIED,
                    observed_at_utc=None,
                    source_operation="valve physical routing bench check",
                    note="P01/P02 physical fluidic meaning remains bench-unverified.",
                ),
            }
        )

        experiment = SubsystemEvidence(
            {
                "status": live_software(self.status, "application.status"),
                "queue_remaining": EvidenceValue(
                    value=self.experiment_series.see_elements_left(),
                    basis=EvidenceBasis.DERIVED,
                    freshness=EvidenceFreshness.FRESH,
                    verification=VerificationScope.SOFTWARE,
                    observed_at_utc=captured_at,
                    source_operation="experiment_series.see_elements_left",
                ),
                "stop_requested": live_software(self.stop_fired, "application.stop_fired"),
            }
        )
        return RuntimeEvidenceSnapshot(
            captured_at_utc=captured_at,
            camera=camera,
            tec=tec,
            pump=pump,
            valve=valve,
            experiment=experiment,
        )

    def get_ad2_sdk(self) -> AD2Sdk:
        return self.ad2

    def set_ad2_sdk(self, ad2: AD2Sdk) -> None:
        self.ad2 = ad2

    def get_hamamatsu(self) -> HamamatsuCamera:
        return self.camera

    def set_hamamatsu(self, camera: HamamatsuCamera) -> None:
        self.camera = camera

    def get_valve(self) -> Valve:
        return self.valve

    def set_valve(self, valve: Valve) -> None:
        self.valve = valve

    def get_cetoni_pump(self) -> CetoniPump:
        return self.pump

    def set_cetoni_pump(self, pump: CetoniPump) -> None:
        self.pump = pump

    def get_z_stage(self) -> ZStage:
        return self.z_motor

    def set_z_stage(self, z_motor: ZStage) -> None:
        self.z_motor = z_motor

    def get_tec_controller(self) -> TecController:
        return self.tec

    def set_tec_controller(self, tec: TecController) -> None:
        self.tec = tec

    def set_tec_output_stage_static_off(
        self,
        channels: tuple[int, ...] | None = None,
    ):
        """Explicit shared Static OFF path with structured failure evidence."""

        try:
            result = self.tec.set_output_stage_static_off(channels)
        except Exception as exc:
            self.emit_event(
                RuntimeEvent.create(
                    severity=RuntimeEventSeverity.HARDWARE_FAULT,
                    subsystem="tec",
                    operation="static_off",
                    message=f"TEC Static OFF failed: {exc}",
                    may_continue=False,
                    operator_next_action="Verify both output stages are OFF in TEC Service Software before continuing.",
                ),
                update_legacy_status=False,
            )
            raise
        self.emit_event(
            RuntimeEvent.create(
                severity=RuntimeEventSeverity.INFO,
                subsystem="tec",
                operation="static_off",
                message="TEC Static OFF confirmed by protocol readback.",
                may_continue=True,
                evidence_refs=("runtime_snapshot.tec.status",),
            ),
            update_legacy_status=False,
        )
        return result

    def commissioning_trace_state(self) -> TraceState:
        """Current recording state for read-only presentation. No I/O."""

        recorder = self.commissioning_trace
        return TraceState.OFF if recorder is None else recorder.state

    def start_commissioning_trace(self, series_path) -> TraceState:
        """Arm passive trace recording for one sequence, if the operator asked.

        Called from the same sequence boundary that already creates the series
        lifecycle manifest. It touches no instrument and cannot fail the run:
        a recorder that cannot write reports DEGRADED and the sequence
        proceeds unchanged.
        """

        self.stop_commissioning_trace()
        if not self.commissioning_trace_enabled:
            self.commissioning_trace = None
            return TraceState.OFF
        recorder = CommissioningTraceRecorder(series_path=Path(series_path))
        self.commissioning_trace = recorder
        return recorder.start()

    def stop_commissioning_trace(self) -> TraceState:
        """Disarm trace recording and persist its derived summary."""

        recorder = self.commissioning_trace
        if recorder is None:
            return TraceState.OFF
        return recorder.stop()

    def get_experiment_series_general(self) -> ExperimentSeries2:
        return self.experiment_series

    def set_experiment_series_general(
        self,
        experiment_series: ExperimentSeries2,
        *,
        preserve_initial_flush_state: bool = False,
    ) -> None:
        # The sequence-level initial refresh is owed exactly once, by whichever
        # call arms it below. A preserved-state group re-uses an already-armed
        # (or already-consumed) sequence flush, so it must not be charged again.
        self._preflight_automatic_flush_volume(
            experiment_series, include_initial_flush=not preserve_initial_flush_state
        )
        self.experiment_series = experiment_series
        if not preserve_initial_flush_state:
            self._initial_flush_pending = True

    def _preflight_automatic_flush_volume(
        self,
        experiment_series: ExperimentSeries2,
        *,
        include_initial_flush: bool = True,
    ) -> None:
        """Reject an underfilled automatic-refresh series before its first valve action.

        ``include_initial_flush`` mirrors the sequence lifecycle: exactly one
        automatic initial refresh belongs to a whole sequence, so a temperature
        group that reuses an already-armed sequence charges only its own
        post-repeat refreshes. This uses tracked pump state only as a
        feasibility gate; it does not assert that any physical volume has been
        delivered.
        """
        experiments = list(experiment_series.experiments or [])
        automatic = [item for item in experiments if item.flush_enabled]
        if not automatic or not (self.pump.enabled and self.valve.enabled):
            return
        flush_count = len(automatic) + (1 if include_initial_flush else 0)
        required_ml = sum(item.flush_settings.flush_volume_ml for item in automatic)
        if include_initial_flush:
            required_ml += automatic[0].flush_settings.flush_volume_ml
        if required_ml > self.pump.fill_level + 1e-12:
            raise ValueError(
                f"Automatic refresh requires {required_ml} ml for {flush_count} flushes, "
                f"but tracked pump fill is {self.pump.fill_level} ml; refusing before any valve or pump command."
            )

    def _run_initial_flush_if_required(
        self,
        experiment: Experiment2,
        progress: Callable[[str, object], None] | None,
    ) -> bool:
        """Run the one series-level automatic refresh before repeat one.

        This is intentionally outside Experiment2: it has no repeat TDMS
        record to mutate, and it must not be repeated for later temperature
        groups whose local repeat index also starts at zero.
        """
        if not self._initial_flush_pending:
            return True
        self._initial_flush_pending = False
        if not experiment.flush_enabled:
            return True
        if not (self.pump.enabled and self.valve.enabled):
            self.fire_status_event("InitialFlushSkippedInstrumentDisabled")
            return True

        completed = self.flush(experiment.flush_settings, progress=progress)
        if not completed:
            message = (
                "Initial flush failed before experiment repeat 1: "
                f"flush_flowrate={experiment.flush_settings.flush_flowrate}, "
                f"flush_volume_ml={experiment.flush_settings.flush_volume_ml}, "
                f"wait_after_flush_s={experiment.flush_settings.wait_after_flush_s}"
            )
            logger.error(message)
            self.check_loop_error(message)
            self.fire_status_event("InitialFlushFailed")
            return False
        log_action(
            "sample_refresh",
            "initial_series_refresh",
            evidence_stage="OBSERVED",
            verification_scope=("SOFTWARE" if self.pump.simulate or self.valve.simulate else "PROTOCOL"),
            status="COMPLETED",
            requested=experiment.flush_settings,
            result={
                "wait_after_flush_s": experiment.flush_settings.wait_after_flush_s,
                "physical_fluid_refresh_verified": False,
            },
            source="application._run_initial_flush_if_required",
        )
        return True

    def check_loop_error(self, error: BaseException | str | None = None) -> bool:
        if error is None:
            return False
        self.errors.append(error)
        return True

    def error_handler_event_loop(self, error: BaseException | str | None = None) -> bool:
        if not self.check_loop_error(error):
            return False
        self.fire_status_event("EventLoopError")
        return True

    def error_handler_main_loop(self, error: BaseException | str | None = None) -> bool:
        if not self.check_loop_error(error):
            return False
        self.fire_status_event("MainLoopError")
        self.fire_stop_event()
        return True

    def initialize(self, progress: Callable[[str, object], None] | None = None) -> None:
        # Devices are independent (2026-08-13 architecture fix): each one's
        # initialize() only ever touches its own fields/backend -- none reads
        # another instrument's state or takes one as an argument (confirmed
        # by inspection of every initialize() in instruments.py/tec.py before
        # this change). AD2 -> Camera -> Pump -> Valve -> Z-stage -> TEC is
        # therefore an arbitrary reporting order, not a dependency chain: one
        # device failing must not stop the others from getting their own
        # attempt, and a device that DID succeed must not be torn back down
        # just because a later, unrelated device failed. This replaces the
        # previous "stop at the first failure and roll back everything
        # already-succeeded" loop -- see docs/hardware_repair_plan.md's
        # "Initialization And Failure Recovery" section and
        # docs/claude_code_change_log.md's dated entry for the investigation
        # that found the old cross-device rollback had no documented
        # dependency rationale anywhere in this project's history; every
        # actual per-device rollback gap this project fixed (Sessions 96-99)
        # was about a device cleaning up its OWN partial-init state, never
        # about one device's failure requiring another's teardown. Per-device
        # rollback-on-partial-failure inside a single instrument's own
        # initialize() (Valve/CetoniPump/PiezoStage/TEC's own local cleanup
        # paths) is untouched by this change.
        self.create_queues()
        self.register_events()
        self.fire_status_event("Initializing")
        devices = (
            ("ad2", "AD2", self.ad2),
            ("camera", "Camera", self.camera),
            ("pump", "Pump", self.pump),
            ("valve", "Valve", self.valve),
            ("z_motor", "Z-stage", self.z_motor),
            ("tec", "TEC", self.tec),
        )
        failures: list[tuple[str, Exception]] = []
        succeeded_count = 0
        for name, display_name, instrument in devices:
            if progress:
                progress("init_device", (display_name, "In Progress"))
            try:
                with action_scope(
                    None,
                    run_id="application_session",
                    condition=name,
                    repeat=None,
                    phase="SETUP",
                ):
                    instrument.initialize()
            except Exception as exc:
                if progress:
                    progress("init_device", (display_name, "Failed"))
                failures.append((display_name, exc))
                self.emit_event(
                    RuntimeEvent.create(
                        severity=RuntimeEventSeverity.HARDWARE_FAULT,
                        subsystem=name,
                        operation="initialize",
                        message=f"{display_name} initialize failed: {exc}",
                        may_continue=True,
                        operator_next_action=(
                            "Inspect the Qmix/CAN fault and use only the reviewed recovery path."
                            if name == "pump"
                            else f"Inspect {display_name} configuration and connection evidence."
                        ),
                    ),
                    update_legacy_status=False,
                )
                continue
            succeeded_count += 1
            if progress:
                status_note = getattr(instrument, "status_note", "")
                complete_text = f"Complete ({status_note})" if status_note else "Complete"
                progress("init_device", (display_name, complete_text))
        if failures:
            failed_names = ", ".join(display_name for display_name, _exc in failures)
            details = "; ".join(f"{display_name} initialize failed: {exc}" for display_name, exc in failures)
            self.emit_event(
                RuntimeEvent.create(
                    severity=RuntimeEventSeverity.HARDWARE_FAULT,
                    subsystem="hardware",
                    operation="initialize",
                    message=(
                        f"System Partially Initialized ({succeeded_count}/{len(devices)} succeeded; "
                        f"failed: {failed_names})"
                    ),
                    may_continue=True,
                    operator_next_action="Review each failed subsystem before using it.",
                )
            )
            # Chained from the first failure for traceback context; when
            # several devices fail independently, all of them are still
            # named in the combined message above, not just the first.
            raise RuntimeError(details) from failures[0][1]
        self.fire_status_event("System Initialized")

    def clear_pump_fault_and_retry(self) -> None:
        """Explicitly reconnect after a fault observed outside normal initialization.

        Normal Qmix initialization now clears the vendor fault latch before
        the final enable gate. This operator-only action remains for a fault
        that occurs after initialization, or when an operator wants an
        explicit fresh reconnect. It stays behind the UI warning dialog and
        still fails loudly if the fault remains or relatches after clearing.

        Records the manual recovery both in the live status/history log
        (fire_status_event(), same mechanism every other status transition in
        this file uses) and in pump_fault_manually_cleared_this_session, which
        run_experiment2() copies onto Experiment2.pump_fault_manually_cleared
        for every subsequent repeat's data.tdms -- so a manual clear this
        session stays traceable in saved data, not just in the live log.
        """
        self.fire_status_event("Clearing Pump Fault (manual operator action)")
        try:
            self.pump.clear_fault_and_reinitialize()
        except Exception as exc:
            self.fire_status_event(f"PumpFaultClearFailed: {exc}")
            raise
        self.pump_fault_manually_cleared_this_session = True
        self.fire_status_event("PumpFaultClearedAndReconnected (manual operator action)")

    def cleanup(self) -> None:
        errors = self._cleanup_instruments(
            (
                ("camera", self.camera),
                ("pump", self.pump),
                ("valve", self.valve),
                ("z_motor", self.z_motor),
                ("tec", self.tec),
                ("ad2", self.ad2),
            )
        )
        self.fire_stop_event()
        self.fire_status_event("System Not Initialized")
        if errors:
            raise RuntimeError("; ".join(errors))

    def _cleanup_instruments(self, instruments) -> list[str]:
        errors: list[str] = []
        deadline = time.monotonic() + max(self.cleanup_total_timeout_s, 0.0)
        for name, instrument in instruments:
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                message = f"{name} cleanup skipped because overall cleanup timed out."
                logger.error(message)
                self.check_loop_error(message)
                errors.append(message)
                continue
            timeout_s = min(max(self.cleanup_device_timeout_s, 0.0), remaining_s)
            with action_scope(
                None,
                run_id="application_session",
                condition=name,
                repeat=None,
                phase="CLEANUP",
            ):
                error = self._run_cleanup_call_with_timeout(name, instrument.cleanup, timeout_s)
            if error is not None:
                logger.error(error)
                self.check_loop_error(error)
                errors.append(error)
        return errors

    def _run_cleanup_call_with_timeout(self, name: str, action, timeout_s: float) -> str | None:
        # Cross-module architecture review (2026-08-02): was previously its
        # own hand-copied implementation of the same timeout-guarded-thread
        # shape QmixPumpBackend._run_close_step()/PiezoStage._run_disconnect_step()
        # each independently re-implemented -- now the shared
        # hw_logging.run_with_timeout() utility. Message wording unchanged
        # ("{name} cleanup ..."), so this stays a drop-in replacement.
        return run_with_timeout(action, f"{name} cleanup", timeout_s)

    def wait(self, seconds: float) -> Message | None:
        deadline = time.monotonic() + max(seconds, 0.0)
        while time.monotonic() < deadline:
            result = self.peek_queue_main()
            if result.message is not None:
                return result.message
            time.sleep(min(0.05, max(deadline - time.monotonic(), 0.0)))
        return None

    def listen_abort(self) -> bool:
        result = self.peek_queue_main()
        if result.message is None:
            return False
        return result.message.name in (MessageName.ABORT, MessageName.EXIT, "Abort", "Exit")

    def _ad2_completion_wait_seconds(self, experiment: Experiment2) -> float:
        wfg_config = coerce_wfg_config(experiment.wfg_config)
        channel0 = next((channel for channel in wfg_config.channels if channel.channel_index == 0), None)
        channel1 = next((channel for channel in wfg_config.channels if channel.channel_index == 1), None)
        if wfg_config.running and channel1 is not None and (channel1.carrier.enable or channel1.fm_mod.enable):
            raise ValueError(
                "Normal production AD2 channel 1 / W2 is connected to the laser Analog In and must "
                "remain disabled until the current laser input polarity, scaling, and enable semantics "
                "are confirmed."
            )
        if experiment.fm_sweep is not None and experiment.frequency_scan_selected_hz is not None:
            raise ValueError(
                "FM Sweep and Frequency Scan cannot be used in the same condition because the "
                "scan would invalidate the configured sweep limits."
            )
        if experiment.fm_sweep is not None and (
            not wfg_config.running or channel0 is None or not channel0.carrier.enable
        ):
            raise ValueError(
                "FM Sweep requires Channel 0 to be explicitly enabled and the waveform generator to be running."
            )
        if (
            wfg_config.running
            and channel0 is not None
            and channel0.carrier.enable
            and channel0.trigger.repeat_count != 1
        ):
            raise ValueError(
                "Normal production AD2 channel 0 Repeat must be exactly 1; Repeat=0 is infinite and "
                "finite Repeat values above 1 are not supported by the completion budget."
            )
        wait_seconds = 0.0
        if wfg_config.running:
            for channel in wfg_config.channels:
                if not channel.carrier.enable:
                    continue
                wait_seconds = max(
                    wait_seconds,
                    self._ad2_trigger_completion_seconds(
                        label=f"AD2 channel {channel.channel_index}",
                        sec_run=float(channel.trigger.sec_run),
                        sec_wait=float(channel.trigger.sec_wait),
                    ),
                )

        do_config = coerce_do_config(experiment.do_clock_settings)
        if do_config.running:
            for channel in do_config.channels:
                if not channel.enable:
                    continue
                wait_seconds = max(
                    wait_seconds,
                    self._ad2_trigger_completion_seconds(
                        label=f"AD2 digital channel {channel.channel_index}",
                        sec_run=float(channel.trigger.sec_run),
                        sec_wait=float(channel.trigger.sec_wait),
                    ),
                )
        return wait_seconds

    def _configured_camera_fps(self, experiment: Experiment2) -> float | None:
        # Normal production records the canonical ExperimentRequest camera
        # rate in sequence_settings. The DO clock is intentionally disabled
        # there, so it cannot be the authority for camera timing. Retain the
        # DO lookup only as a compatibility fallback for older/manual
        # Experiment2 records that predate the independent planner field.
        sequence_settings = experiment.sequence_settings or {}
        if sequence_settings.get("camera_fps") is not None:
            return float(sequence_settings["camera_fps"])
        do_config = coerce_do_config(experiment.do_clock_settings)
        for channel in do_config.channels:
            if channel.enable and channel.clock_frequency_hz:
                return float(channel.clock_frequency_hz)
        return None

    def _check_camera_timing_budget(self, experiment: Experiment2) -> None:
        # Concrete implementation of the previously-deferred "exposure vs.
        # readout timing" check (LabVIEW's Camera tab shows a live-computed
        # "N is Vertical is max for <fps> fps" readback derived from DCAM's
        # own DCAM_IDPROP_TIMING_READOUTTIME; Python had no equivalent).
        # camera_fps comes from canonical experiment planning and drives the
        # bounded DIO0 frame cadence.  It remains requested planning truth;
        # a real DigitalOut configure may separately record a quantized
        # achieved clock frequency.
        camera_fps = self._configured_camera_fps(experiment)
        if camera_fps is None or camera_fps <= 0:
            return
        sequence_settings = experiment.sequence_settings or {}
        if str(sequence_settings.get("trigger_source", "")).lower() == "external":
            reader = getattr(self.camera, "read_min_trigger_interval", None)
            # Older offline test doubles predate this real-camera capability
            # readback. Production HamamatsuCamera always provides it.
            min_interval_s = reader() if reader is not None else 0.0
            if min_interval_s is None:
                raise ValueError(
                    "Could not read the camera's minimum external trigger interval -- cannot verify "
                    "the configured Camera FPS for canonical External-trigger acquisition."
                )
            requested_period_s = 1.0 / camera_fps
            if requested_period_s < max(min_interval_s, 0.0):
                raise ValueError(
                    f"Configured Camera FPS ({camera_fps:.3f}) requires {requested_period_s * 1000:.3f} ms "
                    f"external trigger spacing, below the camera minimum of {min_interval_s * 1000:.3f} ms."
                )
            return
        # Read back self.camera.exposure_ms (the value configure_exposure_time()
        # just applied to real hardware above) rather than experiment.global_exposure_ms
        # directly, so this check verifies the actual applied exposure instead of
        # trusting the experiment dict to match what was really pushed to the device.
        exposure_s = max(self.camera.exposure_ms, 0.0) / 1000.0
        raw_readout_s = self.camera.read_readout_time()
        if raw_readout_s is None:
            # Finding 3 (hamamatsu_dcam.py review, Session 65): a real
            # readout-time query failure now surfaces as None rather than a
            # silently-substituted 0.0 -- treat "unknown" the same as any
            # other unverifiable state this check guards against: refuse
            # to claim the configured FPS is achievable rather than
            # optimistically letting it through on a masked value.
            raise ValueError(
                "Could not read the camera's real readout time from hardware -- cannot verify "
                "the configured Camera FPS is achievable for the current exposure/ROI. Retry, or "
                "check the camera connection before starting this experiment."
            )
        readout_s = max(raw_readout_s, 0.0)
        # C15440-20UP free-running timing is overlap-limited: when exposure is
        # longer than frame readout, frame rate is 1/exposure; when it is
        # shorter, readout/interface timing is limiting. Adding the two would
        # incorrectly reject valid requests (for example 25 fps at 40 ms
        # exposure with an 11.22 ms Fast full-frame readout).
        frame_period_s = max(exposure_s, readout_s)
        if frame_period_s <= 0:
            return
        achievable_fps = 1.0 / frame_period_s
        if camera_fps > achievable_fps:
            raise ValueError(
                f"Configured Camera FPS ({camera_fps:.3f}) exceeds what the current exposure "
                f"({exposure_s * 1000:.3f} ms) and ROI readout time ({readout_s * 1000:.3f} ms) "
                f"can sustain (max {achievable_fps:.3f} fps for this ROI/exposure combination). "
                "Reduce Camera FPS, exposure, or vertical ROI size before starting this experiment."
            )

    def _ad2_trigger_completion_seconds(self, *, label: str, sec_run: float, sec_wait: float) -> float:
        if sec_run == 0:
            raise ValueError(
                f"{label} is configured for continuous output (sec_run=0), which has no "
                "defined completion time -- flush/save cannot safely proceed. Set a finite "
                "Run Duration before starting this experiment."
            )
        if not math.isfinite(sec_run) or not math.isfinite(sec_wait):
            raise ValueError(f"{label} has non-finite run/wait timing; flush/save cannot safely proceed.")
        return max(sec_run, 0.0) + max(sec_wait, 0.0)

    def wait_for_pump(self, timeout_s: float) -> bool:
        # Abort no longer interrupts an in-progress pump move (2026-08-04
        # safety-behavior change): once a flush/refill/empty move has
        # started, it must run to genuine completion or genuine timeout --
        # the only remaining abort check is the between-repeats one in
        # qt_ui.py's _run_experiment_series_body(), before the *next*
        # repeat starts.
        self.fire_status_event("Waiting for Pump")
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while self.pump.read_status():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True

    # H1 (qmix_backend.py line-by-line review, 2026-07-31) + Finding 1
    # (qt_ui.py targeted UI audit, 2026-07-31) independently found the
    # identical bug on three different pump-move buttons: refill()/empty()
    # issue the same asynchronous, target-based set_fill_level() SDK call
    # flush() uses but returned as soon as the command was issued, not when
    # the real pump actually arrived; the manual "GO" button's
    # go_to_level() had the same shape. Cross-module architecture review
    # (2026-08-02) consolidated the now-identical fix (issue move -> wait
    # -> unconditional resync -> fire one of two status events) into this
    # shared helper rather than three hand-copied bodies -- the third
    # near-identical copy (go_to_level()) was direct evidence a fourth
    # button would eventually repeat the same mistake if this stayed
    # unshared. flush() is deliberately NOT migrated here -- it has its
    # own capacity pre-check and a sandwiched valve move that don't
    # generalize cleanly into this shape.
    def _move_pump_and_confirm(self, action: Callable[[], None], timeout_s: float, event_prefix: str) -> bool:
        action()
        completed = self.wait_for_pump(timeout_s)
        if not completed:
            # A timeout means the last real status poll still reported an
            # active move. Fail closed: request an SDK stop before reporting
            # TimedOut. This is distinct from Abort, which intentionally does
            # not interrupt an in-progress pump operation.
            self.pump.stop()
        # Always re-sync after waiting, not only on timeout: CetoniPump.
        # refill()'s own internal sync (inside action() above, for refill()
        # specifically) already ran before this wait, so even the success
        # path needs a fresh read to capture the value actually confirmed
        # by wait_for_pump() -- not flush()'s exact shape (which re-issues
        # a second set_fill_level() call to refresh its own already-correct
        # target), but the same "don't trust a pre-confirmation snapshot"
        # principle.
        self.pump.sync_fill_level()
        if not completed:
            self.fire_status_event(f"{event_prefix}TimedOut")
            return False
        self.fire_status_event(f"{event_prefix}Complete")
        return True

    # Default timeout_s=60.0 mirrors QmixPumpBackend.reference_move_timeout_s's
    # own default -- both are bounded, generous-for-a-full-stroke-move
    # timeouts with no equivalent to FlushSettings' volume/flowrate-derived
    # formula (these three have no caller-supplied settings object).
    def refill(self, flow_rate: float | None = None, timeout_s: float = 60.0) -> bool:
        return self._move_pump_and_confirm(lambda: self.pump.refill(flow_rate), timeout_s, "Refill")

    def empty(self, flow_rate: float | None = None, timeout_s: float = 60.0) -> bool:
        return self._move_pump_and_confirm(lambda: self.pump.empty(flow_rate), timeout_s, "Empty")

    def go_to_level(self, level: float, flow_rate: float | None = None, timeout_s: float = 60.0) -> bool:
        return self._move_pump_and_confirm(
            lambda: self.pump.set_fill_level(level, flow_rate), timeout_s, "GoToLevel"
        )

    def flush(self, settings: FlushSettings, progress: Callable[[str, object], None] | None = None) -> bool:
        with _report_step(progress, STEP_FLUSH):
            if settings.flush_volume_ml > settings.syringe_volume_ml:
                raise ValueError(
                    f"Flush volume {settings.flush_volume_ml} ml exceeds syringe capacity "
                    f"{settings.syringe_volume_ml} ml; refusing to flush."
                )
            if settings.flush_flowrate <= 0:
                raise ValueError(
                    f"Flush flow rate must be greater than 0 uL/min for the dispense workflow; "
                    f"got {settings.flush_flowrate}. Refusing to move the valve or pump."
                )
            # Hardware-safety-priority fix (found by an end-to-end simulated
            # dry-run verification pass, not a fresh audit): the capacity check
            # above only bounds flush_volume_ml against the syringe's total
            # physical capacity -- it says nothing about whether the syringe
            # currently holds enough liquid to flush *right now*. Without this,
            # new_fill_level below could go negative with no error at all: the
            # automated path never calls refill()/reference_move() (confirmed
            # manual-only, Session 21), so an operator starting a series before
            # refilling, or a series that has already drawn the syringe down,
            # would silently succeed with a normal-looking "ExperimentComplete"/
            # data.tdms and a physically impossible negative pump.fill_level
            # pushed straight to set_fill_level() -- and, on real hardware,
            # straight to the Qmix SDK. docs/hardware_safety_patterns.md's
            # decision tree: this is neither a live device query nor a fixed
            # vendor-manual ceiling -- it's already-known in-memory application
            # state (self.pump.fill_level, no vendor research or device round
            # trip needed) -- but the "reject, don't clamp" choice still
            # applies, for the same reason Patterns (c)/(d) reject rather than
            # substitute a value: silently flushing less than requested would
            # itself be a data-integrity bug, since the FlushVolume recorded in
            # data.tdms would then no longer match what actually happened.
            if settings.flush_volume_ml > self.pump.fill_level:
                raise ValueError(
                    f"Flush volume {settings.flush_volume_ml} ml exceeds the syringe's current fill level "
                    f"{self.pump.fill_level} ml; refusing to flush -- refill the syringe first."
                )
            self.fire_status_event("Flushing")
            self.valve.set_position(1)
            if not self.valve.wait_until_ready(timeout_s=1.0):
                # A bounded busy response is not confirmation that the valve
                # reached the requested route. Do not begin the pump move
                # until the first position is confirmed.
                self.fire_status_event("FlushValvePosition1NotReady")
                return False

            # fill_level and flush_volume_ml are both absolute mL -- see
            # QmixPumpBackend.set_fill_level(), which no longer auto-detects units.
            new_fill_level = self.pump.fill_level - settings.flush_volume_ml
            self.pump.set_fill_level(new_fill_level, settings.flush_flowrate)

            completed = self.wait_for_pump(settings.timeout_s)
            if not completed:
                # H1 (instruments.py line-by-line review): set_fill_level()
                # above updates self.pump.fill_level optimistically, to the
                # target, before the real pump confirms it got there --
                # correct on the success path (wait_for_pump() confirmed
                # arrival), but left silently wrong here otherwise, with
                # nothing else re-syncing it. A later flush's own
                # over-draw guard (`flush_volume_ml > self.pump.fill_level`,
                # above) would then trust a fabricated number instead of
                # reality. Re-sync from real hardware before returning --
                # deliberately not caught: if the real read itself fails, a
                # pump we already know is unconfirmed AND now unreadable is
                # worse than the timeout alone, and must not be swallowed
                # into a quiet False return the caller could mistake for an
                # ordinary "flush failed, state is otherwise known" outcome.
                # wait_for_pump() only returns False while the last status
                # poll still says the move is active. Request an SDK stop before
                # returning a failed flush; otherwise motion could
                # continue after the UI reports failure.
                self.pump.stop()
                self.pump.sync_fill_level()
                return False

            self.valve.set_position(2)
            if not self.valve.wait_until_ready(timeout_s=1.0):
                # The return route must be confirmed before the workflow can
                # be reported complete, even though the one pump move has
                # already completed at position 1.
                self.fire_status_event("FlushValvePosition2NotReady")
                return False
            self.wait(settings.wait_after_flush_s)
            self.fire_status_event("FlushComplete")
            return True

    def run_experiment2(self, progress: Callable[[str, object], None] | None = None) -> bool:
        """Run one repeat and finalize an already-created TDMS record.

        The legacy workflow remains authoritative. This wrapper only makes its
        terminal outcome explicit when the initial record was successfully
        created; it does not convert requested metadata into applied evidence.
        """
        experiment, timed_out = self.experiment_series.dequeue_experiment()
        if timed_out or experiment is None:
            self.fire_status_event("NoExperiment")
            return False
        self._active_experiment = experiment
        if progress:
            # Presentation-only projection of the authoritative dequeued
            # experiment and live software enable gates.  The Monitor uses
            # this with the existing step_* events; it is not hardware
            # telemetry and does not claim that any command or physical
            # effect occurred.
            progress(
                "execution_context",
                {
                    "condition": experiment.action_condition,
                    "repeat": experiment.repeat_id + 1,
                    "repeat_total": experiment.planned_repeat_count,
                    "temperature_point": (
                        None
                        if experiment.temperature_point_index is None
                        else experiment.temperature_point_index + 1
                    ),
                    "subsystems": {
                        "ad2": bool(self.ad2.enabled),
                        "camera": bool(self.camera.enabled),
                        "sample_refresh": bool(
                            experiment.flush_enabled and self.pump.enabled and self.valve.enabled
                        ),
                        "tec": bool(
                            experiment.temperature_point_index is not None and self.tec.enabled
                        ),
                        "record": True,
                    },
                    # Filled after the established validation/completion-budget
                    # calculation runs inside InitializeExperiment.  Keeping it
                    # unknown here avoids moving validation ahead of the action
                    # scope merely for presentation.
                    "ad2_wait_required": None,
                    "tec_condition_ready": False,
                },
            )
        with action_scope(
            experiment.action_log_path,
            run_id=experiment.action_run_id,
            condition=experiment.action_condition,
            repeat=experiment.repeat_id + 1,
        ):
            log_action(
                "run",
                "condition_planned",
                evidence_stage="PLANNED",
                verification_scope="SOFTWARE",
                status="READY",
                requested={
                    "experiment_folder": experiment.experiment_folder,
                    "tdms_path": experiment.tdms_path,
                    "planned_repeat_count": experiment.planned_repeat_count,
                    "temperature_point_index": experiment.temperature_point_index,
                    "tec_targets_c": experiment.tec_targets_c,
                    "frequency_scan_selected_hz": experiment.frequency_scan_selected_hz,
                    "requested_exposure_ms": experiment.requested_exposure_ms,
                    "sequence_settings": experiment.sequence_settings,
                    "wfg_config": experiment.wfg_config,
                    "fm_sweep": (
                        experiment.fm_sweep.requested_evidence()
                        if hasattr(experiment.fm_sweep, "requested_evidence")
                        else experiment.fm_sweep
                    ),
                    "flush_enabled": experiment.flush_enabled,
                    "flush_settings": experiment.flush_settings,
                },
                source="application.run_experiment2",
            )
            try:
                if not self._run_initial_flush_if_required(experiment, progress):
                    return False
                completed = self._run_experiment2_unfinalized(experiment, progress=progress)
            except BaseException as exc:
                cleanup_failure = experiment._tdms_properties.get("CleanupFailure") or None
                primary_failure = None if cleanup_failure == str(exc) else exc
                if experiment._record_created:
                    experiment.finalize_record(
                        "FAILED",
                        primary_failure=primary_failure,
                        cleanup_failure=cleanup_failure,
                    )
                if primary_failure is not None:
                    log_action(
                        "run",
                        "primary_failure",
                        evidence_stage="OBSERVED",
                        verification_scope="SOFTWARE",
                        status="FAILED",
                        error=str(primary_failure),
                        source="application.run_experiment2",
                    )
                if cleanup_failure is not None:
                    with action_phase("CLEANUP"):
                        log_action(
                            "run",
                            "cleanup_failure",
                            evidence_stage="OBSERVED",
                            verification_scope="SOFTWARE",
                            status="FAILED",
                            error=str(cleanup_failure),
                            source="application.run_experiment2",
                        )
                raise
            else:
                if experiment._record_created:
                    if completed:
                        experiment.finalize_record("COMPLETED")
                    else:
                        experiment.finalize_record("FAILED", primary_failure=self.status)
                log_action(
                    "run",
                    "repeat_outcome",
                    evidence_stage="OBSERVED",
                    verification_scope="SOFTWARE",
                    status="COMPLETED" if completed else "FAILED",
                    result={"record_outcome": "COMPLETED" if completed else "FAILED", "status": self.status},
                    source="application.run_experiment2",
                )
                return completed
            finally:
                self._active_experiment = None

    def _run_experiment2_unfinalized(
        self,
        experiment: Experiment2,
        progress: Callable[[str, object], None] | None = None,
    ) -> bool:

        # Explicit reset before this repeat's first step is marked active --
        # not left for step_started(STEP_INITIALIZE_EXPERIMENT) below to imply
        # it by omission. Without this, a v2 breadcrumb/step-card display
        # would carry the PREVIOUS repeat's steps 2-7 forward as "completed"
        # for however long it takes this repeat to touch each one again --
        # the exact stale-highlight mistake already avoided elsewhere in this
        # codebase (see qt_ui.py's _stopping_after_current_repeat handling).
        if progress:
            progress("step_reset", None)
        with _report_step(progress, STEP_INITIALIZE_EXPERIMENT):
            ad2_wait_seconds = self._ad2_completion_wait_seconds(experiment)
            if progress:
                progress(
                    "execution_context_update",
                    {"ad2_wait_required": bool(self.ad2.enabled and ad2_wait_seconds > 0)},
                )

            # Finding B (silent-failure/data-integrity sweep): record which
            # instruments were simulated for this specific run, read from live
            # instrument state, not requested/enabled config -- so a simulated
            # dry-run and a real experiment don't produce structurally identical
            # data.tdms files with no way to tell them apart later.
            experiment.sim_ad2 = isinstance(self.ad2, SimulatedAD2Sdk)
            experiment.sim_camera = self.camera.simulate
            experiment.sim_pump = self.pump.simulate
            experiment.sim_valve = self.valve.simulate
            experiment.sim_tec = self.tec.simulate

            # Full-project audit finding (2026-07-31): a real (non-simulated)
            # instrument left disabled for this run previously had its
            # per-step hardware calls silently skipped (AD2) or attempted
            # anyway despite being marked disabled (Camera/Pump/Valve), with
            # no record either way -- SimAD2 alone can't distinguish "AD2 was
            # active" from "AD2 was disabled and skipped." Recorded here,
            # read from live instrument state like the sim_* flags above, so
            # every step below can gate on it and data.tdms can record what
            # actually happened.
            experiment.ad2_enabled = self.ad2.enabled
            experiment.camera_enabled = self.camera.enabled
            experiment.pump_enabled = self.pump.enabled
            experiment.valve_enabled = self.valve.enabled
            experiment.tec_enabled = self.tec.enabled

            # Session 104: whether clear_pump_fault_and_retry() (the manual,
            # operator-initiated fault-clear escape hatch) has been used at
            # any point this session, read from live Application state like
            # the sim_*/*_enabled flags above -- so data.tdms stays
            # traceable if a manual fault clear happened before this repeat.
            experiment.pump_fault_manually_cleared = self.pump_fault_manually_cleared_this_session

            self.fire_status_event("Initializing Experiment")
            experiment_folder = experiment.create_folder_and_tdms()
            experiment.save_settings()

        with _report_step(progress, STEP_CONFIGURE_WFG):
            # Canonical planning supplies one shared PC-triggered DigitalOut
            # program: DIO0 is the finite camera-frame pulse train and DIO1
            # is the finite LED window.  It is configured after W1 but before
            # the camera is armed; the backend rejects divergent per-line
            # global trigger signatures instead of inventing two clocks.
            canonical_triggered_do = (
                (experiment.sequence_settings or {}).get("trigger_architecture")
                == "canonical_pc_triggered_ad2_camera_led"
            )
            if canonical_triggered_do and not self.ad2.enabled:
                raise ValueError(
                    "Canonical External-trigger acquisition requires AD2 enabled and available to generate DIO0 camera triggers."
                )
            experiment.do_clock_settings = coerce_do_config(
                experiment.do_clock_settings if canonical_triggered_do else None
            )
            if self.ad2.enabled:
                self.ad2.config_wfg(experiment.wfg_config)
                # Point the experiment at the confirmed WFG object. Requested
                # values remain in carrier/fm_mod; successful post-clamp SDK
                # arguments are held separately in effective_carrier/
                # effective_fm_mod.
                experiment.wfg_config = coerce_wfg_config(self.ad2.get_wfg_config())
                log_action(
                    "acoustic_laser_control",
                    "wfg_configuration_effective",
                    evidence_stage="EFFECTIVE",
                    verification_scope=("SOFTWARE" if experiment.sim_ad2 else "PROTOCOL"),
                    status="EFFECTIVE",
                    effective={
                        "project_ch1_api_0_w1_role": "acoustic amplifier and transducer",
                        "project_ch2_api_1_w2_role": "laser Analog In electrical control",
                        "configuration": experiment.wfg_config.effective_evidence(),
                        "dio0_camera_trigger": "CANONICAL_FINITE_FRAME_TRIGGER",
                        "dio1_led_timing": "CANONICAL_FINITE_IMAGING_WINDOW",
                        "physical_acoustic_pressure_verified": False,
                        "optical_emission_verified": False,
                    },
                    source="application._run_experiment2_unfinalized",
                )
                if canonical_triggered_do:
                    self.ad2.config_do_clock_special(experiment.do_clock_settings)
                    experiment.do_clock_settings = coerce_do_config(self.ad2.get_do_config())
                    experiment.do_configured_by_runtime = True
            else:
                self.fire_status_event("AD2Disabled -- WFG and DigitalOut configuration skipped")
                log_action(
                    "acoustic_laser_control",
                    "wfg_configuration_effective",
                    evidence_stage="EFFECTIVE",
                    verification_scope="SOFTWARE",
                    status="DISABLED",
                    effective={"wfg": "not attempted", "dio0_camera_trigger": "not attempted", "dio1_led_timing": "not attempted"},
                    source="application._run_experiment2_unfinalized",
                )

            # Re-snapshot settings now that config_wfg() has run. The first
            # save_settings() call above is deliberately kept (not replaced) so a
            # partial record with the *requested* settings still exists on disk
            # even if config_wfg() itself raises -- this
            # second call adds the separate software-effective WFG arguments
            # and out-of-range result produced by configure_wfg(), plus the
            # DigitalOut achieved-frequency evidence set by its backend.
            experiment.save_settings()

        with _report_step(progress, STEP_CONFIGURE_CAMERA):
            if self.camera.enabled:
                camera_sequence_settings = dict(experiment.sequence_settings or {})
                requested_roi = camera_sequence_settings.pop("roi", None)
                if requested_roi is not None:
                    # The request is not evidence of what DCAM accepted. Apply
                    # it first, then force a fresh backend readback; the camera
                    # facade updates its ROI cache with that applied value, and
                    # STEP_SAVE_RESULTS later persists that cache as metadata.
                    self.camera.configure_roi(requested_roi)
                    self.camera.read_subregion_limits_and_value()
                # configure_exposure_time() (not the plain configure() bookkeeping
                # setter) is what actually writes DCAM_IDPROP.EXPOSURETIME to real
                # hardware -- matches the manual Camera tab's _configure_camera(),
                # which already calls it. Previously this path only updated
                # self.camera.exposure_ms without ever pushing it to the device.
                requested_exposure_ms = (
                    experiment.global_exposure_ms
                    if experiment.requested_exposure_ms is None
                    else experiment.requested_exposure_ms
                )
                experiment.requested_exposure_ms = float(requested_exposure_ms)
                applied_exposure_ms = self.camera.configure_exposure_time(requested_exposure_ms)
                # Finding E (silent-failure/data-integrity sweep): configure_exposure_time()
                # now returns the real applied exposure (DCAM's own internal
                # quantization can differ slightly from the request); record that
                # real value into data.tdms's ExposureTime, not the raw requested
                # one, so the saved record matches what was actually pushed to
                # hardware. Third save_settings() call this run -- cheap (same write
                # path used twice already above) and keeps the "record what actually
                # happened, not just what was requested" guarantee Finding A already
                # established for WFGOutOfRange consistent for this field too.
                experiment.applied_exposure_ms = float(applied_exposure_ms)
                experiment.global_exposure_ms = applied_exposure_ms
                experiment.save_settings()

                self.camera.configure_sequence(camera_sequence_settings)
                self.fire_status_event(
                    "Configuring camera trigger global exposure; this may only take effect with compatible trigger source settings"
                )
                self.camera.configure_trigger_global_exposure(experiment.trigger_global_exposure)
                self._check_camera_timing_budget(experiment)
                log_action(
                    "camera",
                    "acquisition_settings_effective",
                    evidence_stage="EFFECTIVE",
                    verification_scope=("SOFTWARE" if experiment.sim_camera else "PROTOCOL"),
                    # ROI is freshly read back and exposure comes from DCAM's
                    # set/get result, but sequence_config remains accepted
                    # software configuration rather than a complete device
                    # readback. Keep the aggregate claim at EFFECTIVE.
                    status="EFFECTIVE",
                    requested={
                        "roi": requested_roi,
                        "exposure_ms": requested_exposure_ms,
                        "sequence": camera_sequence_settings,
                        "trigger_global_exposure": experiment.trigger_global_exposure,
                    },
                    effective={
                        "roi": self.camera.get_sub_region(),
                        "exposure_ms": experiment.applied_exposure_ms,
                        "sequence": self.camera.sequence_config,
                        "trigger_source": camera_sequence_settings.get("trigger_source"),
                        "dio0_physical_connection_used": False,
                    },
                    source="application._run_experiment2_unfinalized",
                )
            else:
                self.fire_status_event("CameraDisabled -- camera configuration skipped")
                log_action(
                    "camera",
                    "acquisition_settings_effective",
                    evidence_stage="EFFECTIVE",
                    verification_scope="SOFTWARE",
                    status="DISABLED",
                    effective="camera calls not attempted",
                    source="application._run_experiment2_unfinalized",
                )

        # Safety-behavior change (2026-08-04): once a repeat has started
        # (past this point), it always runs to full completion -- through
        # capture, the AD2-completion wait, flush, and save -- regardless
        # of abort state. Abort no longer bails mid-repeat (previously via
        # listen_abort() checks here and in wait_for_pump()); it now only
        # ever prevents the *next* repeat from starting, via
        # qt_ui.py's _run_experiment_series_body() between-repeats check.
        # This guarantees captured frames are never silently discarded and
        # the valve is never left mid-flush at position 1.
        image_data: list = []
        frame_timestamps: list[str] = []
        ad2_triggered_at: float | None = None
        with _report_step(progress, STEP_CAPTURE_FRAMES):
            capture_error: BaseException | None = None
            try:
                if self.camera.enabled:
                    self.camera.start_capture()
                if self.ad2.enabled:
                    self.ad2.pc_trigger()
                    ad2_triggered_at = time.monotonic()
                    # The single FDwfDeviceTriggerPC call is the software
                    # logical t=0 for the already-armed W1/DIO0/DIO1 paths.
                    # COMMAND_SENT is the strongest stage software can claim:
                    # no electrical edge, acoustic onset, LED emission, or
                    # camera exposure start is observed here. Recorded after
                    # the monotonic reading so the reading is not delayed, and
                    # immediately before the status event that already writes
                    # at this point, so no hardware call spacing changes.
                    log_action(
                        "acoustic_laser_control",
                        "pc_trigger_command_sent",
                        evidence_stage="COMMAND_SENT",
                        verification_scope=("SOFTWARE" if experiment.sim_ad2 else "PROTOCOL"),
                        status="SENT",
                        requested={
                            "call": "FDwfDeviceTriggerPC",
                            "armed_paths": ["w1_analog_out", "dio0_camera_trigger", "dio1_led_timing"],
                        },
                        result={
                            "logical_t0": "software",
                            "physical_onset_verified": False,
                        },
                        source="application._run_experiment2_unfinalized",
                    )
                else:
                    self.fire_status_event("AD2Disabled -- PC trigger skipped")

                self.fire_status_event("Running Experiment Frame")
                if self.camera.enabled:
                    frame_count = 0
                    if experiment.sequence_settings:
                        frame_count = int(experiment.sequence_settings.get("frames", 0) or 0)
                    image_data = self.camera.image_sequence(
                        frame_count=frame_count, partial_capture_folder=experiment_folder
                    )
                    frame_timestamps = self.camera.read_frame_timestamps()
                else:
                    self.fire_status_event("CameraDisabled -- frame capture skipped")
            except BaseException as exc:
                capture_error = exc
                raise
            finally:
                if self.camera.enabled:
                    try:
                        self.camera.stop_capture()
                    except Exception as cleanup_exc:
                        experiment._tdms_properties["CleanupFailure"] = str(cleanup_exc)
                        if capture_error is None:
                            # Preserve the category before the outer repeat
                            # finalizer records the terminal FAILED outcome.
                            raise
                        logger.error(
                            "Camera stop failed while preserving an earlier capture error: %s",
                            cleanup_exc,
                        )
                        self.check_loop_error(cleanup_exc)

        if ad2_triggered_at is not None:
            remaining_ad2_wait_s = max(ad2_wait_seconds - (time.monotonic() - ad2_triggered_at), 0.0)
            if remaining_ad2_wait_s > 0:
                with _report_step(progress, STEP_WAIT_FOR_AD2_COMPLETION):
                    self.fire_status_event("Waiting for AD2 completion")
                    self.wait(remaining_ad2_wait_s)

        # The AD2 wait above is the conservative programmed-output completion
        # barrier.  It is software timing policy, not physical proof.  Only
        # after that barrier may the next-sample refresh begin.  The flush
        # worker never touches Experiment2 or TDMS; the main thread remains
        # the sole writer and finalizes the worker result after both branches
        # rendezvous.
        flush_requested = experiment.flush_enabled and self.pump.enabled and self.valve.enabled
        flush_result: dict[str, bool] = {}
        flush_error: list[BaseException] = []
        flush_worker: threading.Thread | None = None
        if flush_requested:
            worker_context = copy_context()

            def run_flush() -> None:
                try:
                    flush_result["completed"] = bool(
                        worker_context.run(self.flush, experiment.flush_settings, None)
                    )
                except BaseException as exc:  # re-raised by the main finalizer after the rendezvous
                    flush_error.append(exc)

            log_action(
                "run", STEP_FLUSH, evidence_stage="OBSERVED", verification_scope="SOFTWARE",
                status="STARTED", source="application._run_experiment2_unfinalized",
            )
            if progress:
                progress("step_started", STEP_FLUSH)
            flush_worker = threading.Thread(target=run_flush, name="repeat-flush", daemon=False)
            flush_worker.start()
        elif experiment.flush_enabled:
            # Flush requires both the pump and the valve.  This remains a
            # skipped request, not an attempted/failed refresh.
            self.fire_status_event("FlushSkippedInstrumentDisabled")
            log_action(
                "sample_refresh", "repeat_to_repeat_refresh", evidence_stage="EFFECTIVE",
                verification_scope="SOFTWARE", status="DISABLED", requested=experiment.flush_settings,
                result="pump and/or valve disabled; no refresh command attempted",
                source="application._run_experiment2_unfinalized",
            )

        save_error: BaseException | None = None
        try:
            with _report_step(progress, STEP_SAVE_RESULTS):
                if self.camera.enabled:
                    self.camera.save_sequence(image_data, experiment_folder)
                    experiment.save_image_data(image_data, frame_timestamps=frame_timestamps)
                    experiment.save_camera_settings(
                        {
                            "buffer_size": self.camera.get_camera_buffer_size(),
                            "sub_region": self.camera.get_sub_region(),
                            "readout_time": self.camera.read_readout_time(),
                        }
                    )
                else:
                    experiment.save_image_data(image_data, frame_timestamps=frame_timestamps)
                    experiment.save_camera_settings({"buffer_size": 0, "sub_region": {}, "readout_time": 0.0})
                experiment.cleanup()
                log_action(
                    "run", "results_saved", evidence_stage="OBSERVED", verification_scope="SOFTWARE",
                    status="COMPLETED",
                    result={
                        "experiment_folder": experiment.experiment_folder,
                        "tdms_path": experiment.tdms_path,
                        "frame_count": len(image_data),
                        "camera_timestamp_count": len(frame_timestamps),
                    },
                    source="application._run_experiment2_unfinalized",
                )
        except BaseException as exc:
            save_error = exc
        finally:
            if flush_worker is not None:
                flush_worker.join()

        if flush_requested:
            flush_completed = not flush_error and flush_result.get("completed", False)
            # Canonical single-writer finalization: this is the only point at
            # which the asynchronous hardware result becomes repeat evidence.
            experiment.save_flush_result(flush_completed)
            if flush_error:
                log_action(
                    "run", STEP_FLUSH, evidence_stage="OBSERVED", verification_scope="SOFTWARE",
                    status="FAILED", error=str(flush_error[0]),
                    source="application._run_experiment2_unfinalized",
                )
                if progress:
                    progress("step_failed", (STEP_FLUSH, str(flush_error[0])))
            else:
                log_action(
                    "run", STEP_FLUSH, evidence_stage="OBSERVED", verification_scope="SOFTWARE",
                    status="COMPLETED", source="application._run_experiment2_unfinalized",
                )
                if progress:
                    progress("step_completed", STEP_FLUSH)
        else:
            flush_completed = True

        # The save branch and the hardware-only refresh worker have both
        # finished by here (the join above is the rendezvous) and the main
        # thread has finalized the worker result. Recorded as one explicit
        # transition so the trace can show where the concurrent branches
        # rejoined instead of leaving it implied by adjacent step events.
        log_action(
            "run",
            "save_flush_rendezvous",
            evidence_stage="OBSERVED",
            verification_scope="SOFTWARE",
            status="COMPLETED",
            result={
                "refresh_requested": bool(flush_requested),
                "refresh_completed": bool(flush_completed),
                "save_failed": save_error is not None,
                "physical_fluid_refresh_verified": False,
            },
            source="application._run_experiment2_unfinalized",
        )

        if save_error is not None:
            if not flush_completed:
                experiment._tdms_properties["CleanupFailure"] = (
                    "Flush failure while preserving save failure: "
                    + (str(flush_error[0]) if flush_error else "flush returned False")
                )
            raise save_error

        if not flush_completed:
            message = (
                f"Flush failed for experiment repeat {experiment.repeat_id + 1}: "
                f"flush_flowrate={experiment.flush_settings.flush_flowrate}, "
                f"flush_volume_ml={experiment.flush_settings.flush_volume_ml}, "
                f"wait_after_flush_s={experiment.flush_settings.wait_after_flush_s}"
            )
            logger.error(message)
            self.check_loop_error(message)
            self.fire_status_event("ExperimentFlushFailed")
            if flush_error:
                raise flush_error[0]
            return False

        if flush_requested:
            log_action(
                "sample_refresh", "repeat_to_repeat_refresh", evidence_stage="OBSERVED",
                verification_scope=("SOFTWARE" if experiment.sim_pump or experiment.sim_valve else "PROTOCOL"),
                status="COMPLETED", requested=experiment.flush_settings,
                result={
                    "p01_confirmed_by_protocol": True,
                    "pump_refresh_completed_by_software": True,
                    "p02_confirmed_by_protocol": True,
                    "wait_after_flush_s": experiment.flush_settings.wait_after_flush_s,
                    "physical_fluid_refresh_verified": False,
                },
                source="application._run_experiment2_unfinalized",
            )

        self.fire_status_event("ExperimentComplete")
        return True

    def run_temperature_series(
        self,
        temperature_series: TemperatureSeries,
        experiment_groups: list[ExperimentSeries2],
        progress: Callable[[str, object], None] | None = None,
        lifecycle_manifest: SeriesLifecycleManifest | None = None,
    ) -> bool:
        if not temperature_series.enabled:
            raise ValueError("Temperature series requires at least one temperature point.")
        if len(experiment_groups) != len(temperature_series.temperature_points_c):
            raise ValueError(
                "Temperature series group count must match the number of temperature points "
                f"({len(experiment_groups)} groups, {len(temperature_series.temperature_points_c)} points)."
            )
        if not self.tec.enabled or self.tec.simulate:
            self.emit_event(
                RuntimeEvent.create(
                    severity=RuntimeEventSeverity.WARNING,
                    subsystem="tec",
                    operation="run_temperature_series",
                    message=(
                        "TEC temperature series requested with the TEC "
                        + ("disabled" if not self.tec.enabled else "simulated")
                        + "; no real temperature-control evidence will be produced."
                    ),
                    may_continue=True,
                    operator_next_action="Treat TDMS TEC values as requested/simulated, not physically applied.",
                    evidence_refs=("tec.enabled", "tec.simulated"),
                ),
                update_legacy_status=False,
            )
        # Temperature groups are one canonical experiment sequence for this
        # purpose: permit one pre-repeat refresh before group one's repeat one.
        # Validate the complete flattened sequence before either the initial
        # refresh or a TEC action can issue a pump/valve command.
        self._preflight_automatic_flush_volume(
            ExperimentSeries2(
                experiments=[
                    experiment
                    for group in experiment_groups
                    for experiment in (group.experiments or ())
                ]
            )
        )
        self._initial_flush_pending = True
        for group_index, group in enumerate(experiment_groups, start=1):
            # Safety-behavior change (2026-08-04, closing a gap Session 78's
            # non-TEC abort fix didn't reach): self.stop_fired is the ONLY
            # abort check anywhere in this method, checked here -- once per
            # temperature point, before that point does anything -- exactly
            # mirroring qt_ui.py's _run_experiment_series_body()'s
            # between-repeats `if self.app.stop_fired:` check. Once a
            # temperature point's sequence starts (target set), it always
            # runs to full completion -- wait for stability, the post-
            # stable hold, and its ENTIRE experiment group including every
            # repeat -- regardless of abort state. The previous
            # listen_abort()-based checks at target-set/wait_until_stable()/
            # post_stable_hold_s/the inner repeat loop were all confirmed
            # dead (qt_ui.py's real _abort() never enqueues the message
            # listen_abort() reads -- identical to the pattern Session 78
            # found and fixed in run_experiment2()/wait_for_pump(); this
            # TEC-scan code was simply out of scope for that pass). Removed
            # entirely, not replaced, matching "finish the current unit,
            # then stop" applied at the temperature-point granularity.
            if self.stop_fired:
                self.fire_status_event("TemperatureSeriesAborted")
                if lifecycle_manifest is not None:
                    lifecycle_manifest.finalize("GRACEFULLY_ABORTED", graceful_abort_requested=True)
                return False
            # Explicit reset at the temperature-point boundary too, not just
            # inside run_experiment2() below: SetTecTarget/WaitTecStable/the
            # post-stable hold can run for a long time before this point's
            # first repeat ever calls run_experiment2() (whose own reset
            # covers repeats). Without this, a v2 breadcrumb would keep
            # showing the PREVIOUS temperature point's steps as "completed"
            # for that entire stabilization wait -- the same stale-highlight
            # risk, at the point granularity instead of the repeat one.
            if progress:
                progress("step_reset", None)
            if lifecycle_manifest is not None:
                lifecycle_manifest.tec_point_started()
            # target: a plain float when temperature_series is locked
            # (broadcasts to every configured channel, today's original
            # behavior, unchanged); a {1: ..., 2: ...} dict when unlocked
            # -- TecController.apply_static_setpoint()/wait_until_stable()
            # both accept either shape directly (2026-08-04 extension).
            target = temperature_series.target_at(group_index - 1)
            target_label = f"{target:.3f} C" if isinstance(target, float) else (
                ", ".join(f"ch{channel}={value:.3f}C" for channel, value in target.items())
            )
            if progress:
                first_experiment = group.experiments[0] if group.experiments else None
                progress(
                    "execution_context",
                    {
                        "condition": f"temperature point {group_index}/{len(experiment_groups)}: {target_label}",
                        "repeat": None,
                        "repeat_total": (
                            None if first_experiment is None else first_experiment.planned_repeat_count
                        ),
                        "temperature_point": group_index,
                        "temperature_point_total": len(experiment_groups),
                        "subsystems": {
                            "ad2": bool(self.ad2.enabled),
                            "camera": bool(self.camera.enabled),
                            "sample_refresh": bool(
                                first_experiment is not None
                                and first_experiment.flush_enabled
                                and self.pump.enabled
                                and self.valve.enabled
                            ),
                            "tec": bool(self.tec.enabled),
                            "record": True,
                        },
                        "ad2_wait_required": False,
                        "tec_condition_ready": False,
                    },
                )
            log_action(
                "tec",
                "temperature_condition_planned",
                evidence_stage="PLANNED",
                verification_scope="SOFTWARE",
                status="READY",
                requested={
                    "group_index": group_index,
                    "group_count": len(experiment_groups),
                    "target": target,
                    "tolerance_c": temperature_series.tolerance_c,
                    "min_settle_s": temperature_series.min_settle_s,
                    "max_wait_s": temperature_series.max_wait_s,
                    "post_stable_hold_s": temperature_series.post_stable_hold_s,
                },
                source="application.run_temperature_series",
            )
            self.fire_status_event(f"Setting TEC {target_label}")
            with _report_step(progress, STEP_SET_TEC_TARGET):
                try:
                    self.tec.apply_static_setpoint(target)
                except TecPartialApplicationError as exc:
                    self.emit_event(
                        RuntimeEvent.create(
                            severity=RuntimeEventSeverity.HARDWARE_FAULT,
                            subsystem="tec",
                            operation="apply_static_setpoint_partial",
                            message=str(exc),
                            may_continue=False,
                            operator_next_action=(
                                "Verify both TEC output stages are OFF before retrying; do not infer target rollback."
                            ),
                            evidence_refs=("runtime_snapshot.tec.status",),
                        ),
                        update_legacy_status=False,
                    )
                    raise
            self.fire_status_event(f"Waiting for TEC {target_label}")
            with _report_step(progress, STEP_WAIT_TEC_STABLE):
                try:
                    self.tec.wait_until_stable(
                        target,
                        tolerance_c=temperature_series.tolerance_c,
                        min_settle_s=temperature_series.min_settle_s,
                        max_wait_s=temperature_series.max_wait_s,
                        poll_interval_s=temperature_series.poll_interval_s,
                    )
                except Exception as exc:
                    self.emit_event(
                        RuntimeEvent.create(
                            severity=RuntimeEventSeverity.HARDWARE_FAULT,
                            subsystem="tec",
                            operation="wait_until_stable",
                            message=f"TEC status/stability verification failed: {exc}",
                            may_continue=False,
                            operator_next_action="Inspect TEC status and confirm both output stages before continuing.",
                            evidence_refs=("runtime_snapshot.tec.status",),
                        ),
                        update_legacy_status=False,
                    )
                    raise
            # post_stable_hold_s is deliberately separate from min_settle_s
            # above: min_settle_s is part of HOW wait_until_stable() itself
            # decides the TEC's own sensor reading is "stable" (continuous
            # time within tolerance); this is an ADDITIONAL hold applied
            # only after that stability is already confirmed, for real
            # sample thermal equilibration, which can lag behind the TEC
            # sensor. Default 0.0 -- no wait, unchanged existing behavior.
            if temperature_series.post_stable_hold_s > 0:
                self.fire_status_event(
                    f"Holding {temperature_series.post_stable_hold_s:.3f}s after TEC stability "
                    "for sample equilibration"
                )
                self.wait(temperature_series.post_stable_hold_s)
            self.fire_status_event(f"Running temperature group {group_index}/{len(experiment_groups)}")
            # Each temperature group has its own local repeat numbering, but
            # the optional initial refresh belongs to the enclosing sequence
            # and must already have happened before its first group.
            self.set_experiment_series_general(group, preserve_initial_flush_state=True)
            while self.experiment_series.see_elements_left():
                if lifecycle_manifest is not None:
                    lifecycle_manifest.repeat_started()
                try:
                    completed = self.run_experiment2(progress=progress)
                except Exception:
                    if lifecycle_manifest is not None:
                        lifecycle_manifest.repeat_failed()
                        lifecycle_manifest.finalize("FAILED")
                    raise
                if not completed:
                    if lifecycle_manifest is not None:
                        lifecycle_manifest.repeat_failed()
                        lifecycle_manifest.finalize("FAILED")
                    return False
                if lifecycle_manifest is not None:
                    lifecycle_manifest.repeat_completed()
            if lifecycle_manifest is not None:
                lifecycle_manifest.tec_point_completed()
        if self.stop_fired:
            # The current outer unit finished before observing Abort; retain
            # the abort truth even when it was also the final TEC point.
            self.fire_status_event("TemperatureSeriesAborted")
            if lifecycle_manifest is not None:
                lifecycle_manifest.finalize("GRACEFULLY_ABORTED", graceful_abort_requested=True)
            return False
        self.fire_status_event("TemperatureSeriesComplete")
        if lifecycle_manifest is not None:
            lifecycle_manifest.finalize("COMPLETED")
        return True

    def handle_message(self, message: Message) -> None:
        name = MessageName(message.name) if message.name in MessageName._value2member_map_ else message.name

        if name == MessageName.INITIALIZE:
            self.initialize()
        elif name == MessageName.CONFIGURE_CAMERA:
            self.fire_status_event("Configuring Camera")
            exposure_ms = message.data.get("exposure_ms") if isinstance(message.data, dict) else None
            self.camera.configure(exposure_ms=exposure_ms)
            self.enqueue_main(Message(MessageName.CAMERA_CONFIGURED))
        elif name == MessageName.CAMERA_CONFIGURED:
            self.fire_status_event("CameraConfigured")
        elif name == MessageName.PUMP_INIT:
            self.pump.initialize()
        elif name == MessageName.CETONI_REFILL:
            self.pump.refill()
        elif name == MessageName.CETONI_EMPTY:
            self.pump.empty()
        elif name == MessageName.CETONI_STOP_DOSING:
            self.pump.stop()
        elif name == MessageName.CETONI_GENERATE_FLOW:
            flow_rate = float(message.data or 0.0)
            self.pump.generate_flow(flow_rate)
        elif name == MessageName.CETONI_SET_FILL_LEVEL:
            self.pump.set_fill_level(float(message.data or 0.0))
        elif name == MessageName.VALVE_POS_1:
            self.valve.set_position(1)
        elif name == MessageName.VALVE_POS_2:
            self.valve.set_position(2)
        elif name == MessageName.FLUSH:
            if not isinstance(message.data, FlushSettings):
                raise TypeError("Flush message requires FlushSettings data")
            self.flush(message.data)
        elif name == MessageName.RUN_EXPERIMENT2:
            self.run_experiment2()
        elif name in (MessageName.EXIT, MessageName.ABORT):
            self.fire_stop_event()
        else:
            raise ValueError(f"Unhandled message: {message.name}")

    def run_until_idle(self) -> None:
        self._running = True
        while self._running and len(self.main_queue):
            result = self.dequeue_main()
            if result.message is not None:
                self.handle_message(result.message)
