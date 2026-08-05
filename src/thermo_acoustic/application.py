from __future__ import annotations

from contextlib import contextmanager
import logging
from dataclasses import dataclass, field
import math
import time
from typing import Callable

from .ad2 import coerce_do_config, coerce_wfg_config
from .hw_logging import run_with_timeout
from .instruments import AD2Sdk, CetoniPump, HamamatsuCamera, SimulatedAD2Sdk, Valve, ZStage
from .messages import Message, MessageName, QueueResult, UiEvent
from .queues import LabViewQueue
from .tec import TecController
from .workflows import Experiment2, ExperimentSeries2, FlushSettings, TemperatureSeries


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

# Single source of truth for the per-repeat step order (v2's
# ExperimentSequenceView card order and the Phase 3 step-progress breadcrumb,
# 2026-08-04, both derive from this rather than each hardcoding it
# separately). Deliberately excludes STEP_SET_TEC_TARGET/STEP_WAIT_TEC_STABLE
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
    if progress:
        progress("step_started", name)
    try:
        yield
    except Exception as exc:
        if progress:
            progress("step_failed", (name, str(exc)))
        raise
    else:
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
    errors: list[BaseException | str] = field(default_factory=list)
    stop_fired: bool = False
    _running: bool = False
    cleanup_device_timeout_s: float = 5.0
    cleanup_total_timeout_s: float = 15.0

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

    def fire_status_event(self, status: str) -> None:
        self.status = status
        self.status_events.append(status)
        self.fire_ui_event(MessageName.UPDATE_STATUS, status)

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

    def get_experiment_series_general(self) -> ExperimentSeries2:
        return self.experiment_series

    def set_experiment_series_general(self, experiment_series: ExperimentSeries2) -> None:
        self.experiment_series = experiment_series

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
        self.create_queues()
        self.register_events()
        self.fire_status_event("Initializing")
        initialized: list[tuple[str, str, object]] = []
        for name, display_name, instrument in (
            ("ad2", "AD2", self.ad2),
            ("camera", "Camera", self.camera),
            ("pump", "Pump", self.pump),
            ("valve", "Valve", self.valve),
            ("z_motor", "Z-stage", self.z_motor),
            ("tec", "TEC", self.tec),
        ):
            if progress:
                progress("init_device", (display_name, "In Progress"))
            try:
                instrument.initialize()
            except Exception as exc:
                if progress:
                    progress("init_device", (display_name, "Failed"))
                rollback_errors = self._cleanup_instruments(
                    [
                        (initialized_name, initialized_instrument)
                        for initialized_name, _display, initialized_instrument in initialized
                    ]
                )
                if progress:
                    for _initialized_name, initialized_display, _instrument in initialized:
                        progress(
                            "init_device",
                            (initialized_display, f"Rolled back ({display_name} init failed)"),
                        )
                error_name = display_name if progress else name
                details = [f"{error_name} initialize failed: {exc}"]
                details.extend(rollback_errors)
                raise RuntimeError("; ".join(details)) from exc
            initialized.append((name, display_name, instrument))
            if progress:
                status_note = getattr(instrument, "status_note", "")
                complete_text = f"Complete ({status_note})" if status_note else "Complete"
                progress("init_device", (display_name, complete_text))
        self.fire_status_event("System Initialized")

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
        # camera_fps is read from the DO clock channel because that is the
        # only place the intended frame rate is recorded on Experiment2.
        camera_fps = self._configured_camera_fps(experiment)
        if camera_fps is None or camera_fps <= 0:
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
        frame_period_s = exposure_s + readout_s
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
                # The final fill-level update can command the real pump too;
                # leave it untouched when the return position is unconfirmed.
                self.fire_status_event("FlushValvePosition2NotReady")
                return False
            self.wait(settings.wait_after_flush_s)
            self.pump.set_fill_level(new_fill_level)
            self.fire_status_event("FlushComplete")
            return True

    def run_experiment2(self, progress: Callable[[str, object], None] | None = None) -> bool:
        experiment, timed_out = self.experiment_series.dequeue_experiment()
        if timed_out or experiment is None:
            self.fire_status_event("NoExperiment")
            return False

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

            # Finding B (silent-failure/data-integrity sweep): record which
            # instruments were simulated for this specific run, read from live
            # instrument state, not requested/enabled config -- so a simulated
            # dry-run and a real experiment don't produce structurally identical
            # data.tdms files with no way to tell them apart later.
            experiment.sim_ad2 = isinstance(self.ad2, SimulatedAD2Sdk)
            experiment.sim_camera = self.camera.simulate
            experiment.sim_pump = self.pump.simulate
            experiment.sim_valve = self.valve.simulate

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

            self.fire_status_event("Initializing Experiment")
            experiment_folder = experiment.create_folder_and_tdms()
            experiment.save_settings()

        with _report_step(progress, STEP_CONFIGURE_WFG):
            if self.ad2.enabled:
                self.ad2.config_wfg(experiment.wfg_config)
                self.ad2.config_do_clock_special(experiment.do_clock_settings)
                # Finding 1 (application.py review, Session 67): point
                # experiment.wfg_config/do_clock_settings at the confirmed,
                # post-clamping objects AD2Sdk now holds (only assigned there
                # after the real hardware call succeeds, since Session 66's
                # Fix 2) rather than leaving them at whatever was originally
                # passed in. coerce_wfg_config()/coerce_do_config() return the
                # SAME object unchanged when given an already-typed WfgConfig/
                # DoConfig, but build a brand-new, disconnected object when
                # given a dict -- so when experiment.wfg_config/do_clock_settings
                # started out as a dict (a documented, type-hinted input shape,
                # used by hardware_tests/test_real_workflow_smoke.py), the
                # object WaveFormsBackend.configure_wfg()/configure_do() just
                # mutated with the real clamping result was never the same
                # object as experiment.wfg_config -- the re-snapshot below
                # would silently keep reading the untouched original dict's
                # pre-configure defaults. Reassigning here makes the fix work
                # for both input shapes without changing coerce_wfg_config()/
                # coerce_do_config() themselves (which have other read-only
                # callers, e.g. _ad2_completion_wait_seconds() below, that
                # must not start mutating a caller-supplied dict as a side
                # effect).
                experiment.wfg_config = self.ad2.get_wfg_config()
                experiment.do_clock_settings = self.ad2.get_do_config()
            else:
                self.fire_status_event("AD2Disabled -- WFG/DO configuration skipped")

            # Re-snapshot settings now that config_wfg() has run. The first
            # save_settings() call above is deliberately kept (not replaced) so a
            # partial record with the *requested* settings still exists on disk
            # even if config_wfg()/config_do_clock_special() itself raises -- this
            # second call only refreshes fields that hardware configuration can
            # change after the fact, currently WfgChannelConfig.out_of_range
            # (set by WaveFormsBackend.configure_wfg()'s live-range clamping,
            # Session 51 / commit 23e17d5) and DOFreqActual (achieved DO-clock
            # frequency after integer-divider rounding). Without this,
            # WFGOutOfRangeCh1/Ch2 and DOFreqActual in data.tdms always
            # reflected the pre-configure default, because config_wfg()/
            # config_do_clock_special() -- the only places that ever set them
            # -- ran after the metadata snapshot that recorded them.
            experiment.save_settings()

        with _report_step(progress, STEP_CONFIGURE_CAMERA):
            if self.camera.enabled:
                # configure_exposure_time() (not the plain configure() bookkeeping
                # setter) is what actually writes DCAM_IDPROP.EXPOSURETIME to real
                # hardware -- matches the manual Camera tab's _configure_camera(),
                # which already calls it. Previously this path only updated
                # self.camera.exposure_ms without ever pushing it to the device.
                applied_exposure_ms = self.camera.configure_exposure_time(experiment.global_exposure_ms)
                # Finding E (silent-failure/data-integrity sweep): configure_exposure_time()
                # now returns the real applied exposure (DCAM's own internal
                # quantization can differ slightly from the request); record that
                # real value into data.tdms's ExposureTime, not the raw requested
                # one, so the saved record matches what was actually pushed to
                # hardware. Third save_settings() call this run -- cheap (same write
                # path used twice already above) and keeps the "record what actually
                # happened, not just what was requested" guarantee Finding A already
                # established for WFGOutOfRange consistent for this field too.
                experiment.global_exposure_ms = applied_exposure_ms
                experiment.save_settings()

                self.camera.configure_sequence(experiment.sequence_settings)
                self.fire_status_event(
                    "Configuring camera trigger global exposure; this may only take effect with compatible trigger source settings"
                )
                self.camera.configure_trigger_global_exposure(experiment.trigger_global_exposure)
                self._check_camera_timing_budget(experiment)
            else:
                self.fire_status_event("CameraDisabled -- camera configuration skipped")

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
                        if capture_error is None:
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

        if experiment.flush_enabled:
            if self.pump.enabled and self.valve.enabled:
                flush_completed = self.flush(experiment.flush_settings, progress=progress)
                # Finding D (silent-failure/data-integrity sweep): record the
                # flush result into this repeat's own data.tdms, on both the
                # success and failure paths -- Session 7 already made a failed
                # flush surface loudly (status event, log, Application.errors),
                # but only at the process level, not into the saved record
                # itself.
                experiment.save_flush_result(flush_completed)
                if not flush_completed:
                    message = (
                        f"Flush failed for experiment repeat {experiment.repeat_id}: "
                        f"flush_flowrate={experiment.flush_settings.flush_flowrate}, "
                        f"flush_volume_ml={experiment.flush_settings.flush_volume_ml}, "
                        f"wait_after_flush_s={experiment.flush_settings.wait_after_flush_s}"
                    )
                    logger.error(message)
                    self.check_loop_error(message)
                    self.fire_status_event("ExperimentFlushFailed")
                    experiment.cleanup()
                    return False
            else:
                # Flush requires both the pump and the valve -- flush() moves
                # fluid via the pump between two valve positions, it isn't
                # meaningful with either one disabled. Skipped, not attempted,
                # not marked failed -- PumpEnabled/ValveEnabled in data.tdms
                # (alongside FlushFlowrate/FlushVolume still recording what
                # was requested) is what distinguishes this from either "flush
                # wasn't requested" or "flush was requested and failed."
                self.fire_status_event("FlushSkippedInstrumentDisabled")

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

        self.fire_status_event("ExperimentComplete")
        return True

    def run_temperature_series(
        self,
        temperature_series: TemperatureSeries,
        experiment_groups: list[ExperimentSeries2],
        progress: Callable[[str, object], None] | None = None,
    ) -> bool:
        if not temperature_series.enabled:
            raise ValueError("Temperature series requires at least one temperature point.")
        if len(experiment_groups) != len(temperature_series.temperature_points_c):
            raise ValueError(
                "Temperature series group count must match the number of temperature points "
                f"({len(experiment_groups)} groups, {len(temperature_series.temperature_points_c)} points)."
            )
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
            # target: a plain float when temperature_series is locked
            # (broadcasts to every configured channel, today's original
            # behavior, unchanged); a {1: ..., 2: ...} dict when unlocked
            # -- TecController.apply_static_setpoint()/wait_until_stable()
            # both accept either shape directly (2026-08-04 extension).
            target = temperature_series.target_at(group_index - 1)
            target_label = f"{target:.3f} C" if isinstance(target, float) else (
                ", ".join(f"ch{channel}={value:.3f}C" for channel, value in target.items())
            )
            self.fire_status_event(f"Setting TEC {target_label}")
            with _report_step(progress, STEP_SET_TEC_TARGET):
                self.tec.apply_static_setpoint(target)
            self.fire_status_event(f"Waiting for TEC {target_label}")
            with _report_step(progress, STEP_WAIT_TEC_STABLE):
                self.tec.wait_until_stable(
                    target,
                    tolerance_c=temperature_series.tolerance_c,
                    min_settle_s=temperature_series.min_settle_s,
                    max_wait_s=temperature_series.max_wait_s,
                    poll_interval_s=temperature_series.poll_interval_s,
                )
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
            self.set_experiment_series_general(group)
            while self.experiment_series.see_elements_left():
                if not self.run_experiment2(progress=progress):
                    return False
        self.fire_status_event("TemperatureSeriesComplete")
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
