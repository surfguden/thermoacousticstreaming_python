from __future__ import annotations

from collections.abc import Callable
import threading

from ..domain import ExperimentPlan, ExperimentState, ExperimentStatus, LabCommand


class ExperimentRunner:
    """Application-owned sequence runner using flags and an interruptible worker."""

    def __init__(
        self,
        execute: Callable[[LabCommand], object],
        on_finish: Callable[[ExperimentState, str | None], None] | None = None,
    ) -> None:
        self._execute = execute
        self._on_finish = on_finish
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = ExperimentState.IDLE
        self._completed_steps = 0
        self._total_steps = 0
        self._fault: str | None = None

    def status(self) -> ExperimentStatus:
        with self._lock:
            return ExperimentStatus(
                state=self._state,
                completed_steps=self._completed_steps,
                total_steps=self._total_steps,
                fault=self._fault,
            )

    def start(self, plan: ExperimentPlan) -> None:
        with self._lock:
            if self._state is ExperimentState.RUNNING:
                raise RuntimeError("An experiment is already running")
            self._cancel.clear()
            self._state = ExperimentState.RUNNING
            self._completed_steps = 0
            self._total_steps = len(plan.steps)
            self._fault = None
            self._thread = threading.Thread(
                target=self._run,
                args=(plan,),
                name="experiment-runner",
                daemon=True,
            )
            self._thread.start()

    def cancel(self, *, wait: bool = False, timeout_s: float = 5.0) -> None:
        self._cancel.set()
        thread = self._thread
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(timeout_s, 0.0))

    def _run(self, plan: ExperimentPlan) -> None:
        try:
            for step in plan.steps:
                if self._cancel.is_set():
                    self._finish(ExperimentState.CANCELLED)
                    return
                self._execute(step.command)
                with self._lock:
                    self._completed_steps += 1
                if step.delay_after_s and self._cancel.wait(step.delay_after_s):
                    self._finish(ExperimentState.CANCELLED)
                    return
        except Exception as exc:
            self._finish(ExperimentState.FAILED, str(exc))
            return
        self._finish(ExperimentState.COMPLETED)

    def _finish(self, state: ExperimentState, fault: str | None = None) -> None:
        with self._lock:
            self._state = state
            self._fault = fault
        if self._on_finish is not None:
            self._on_finish(state, fault)
