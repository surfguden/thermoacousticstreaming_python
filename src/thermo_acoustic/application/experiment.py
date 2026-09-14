from __future__ import annotations

from collections.abc import Callable
import time

from ..domain import ExperimentPlan, ExperimentState
from .validation import validate_plan


class ExperimentRunner:
    """Non-blocking sequence state machine; presentation code only ticks it."""

    def __init__(self, execute: Callable[..., None]) -> None:
        self._execute = execute
        self.plan: ExperimentPlan | None = None
        self.state = ExperimentState.IDLE
        self.step_index = 0
        self.next_step_at = 0.0
        self.error: str | None = None

    def start(self, plan: ExperimentPlan, *, now: float | None = None) -> None:
        if self.state is ExperimentState.RUNNING:
            raise RuntimeError("An experiment is already running")
        validate_plan(plan)
        self.plan = plan
        self.state = ExperimentState.RUNNING
        self.step_index = 0
        self.next_step_at = time.monotonic() if now is None else now
        self.error = None

    def cancel(self) -> None:
        if self.state is ExperimentState.RUNNING:
            self.state = ExperimentState.CANCELLED

    def tick(self, *, now: float | None = None) -> bool:
        if self.state is not ExperimentState.RUNNING or self.plan is None:
            return False
        current_time = time.monotonic() if now is None else now
        if current_time < self.next_step_at:
            return False
        step = self.plan.steps[self.step_index]
        try:
            self._execute(step.device, step.command, step.parameters)
        except Exception as exc:
            self.error = str(exc)
            self.state = ExperimentState.FAILED
            return True
        self.step_index += 1
        if self.step_index >= len(self.plan.steps):
            self.state = ExperimentState.COMPLETED
        else:
            self.next_step_at = current_time + step.delay_after_s
        return True
