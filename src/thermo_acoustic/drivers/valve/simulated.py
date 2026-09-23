from __future__ import annotations

class SimulatedValve:
    def __init__(self) -> None:
        self.initialized = False
        self.position = 1
        self.status_note = ""

    def initialize(self) -> None:
        self.initialized = True
        self.status_note = "confirmed"

    def cleanup(self) -> None:
        self.initialized = False
        self.status_note = ""

    def set_position(self, position: int) -> None:
        if position not in (1, 2):
            raise ValueError("position must be 1 or 2")
        self.position = position
        self.status_note = "requested P%02d; confirmation pending" % position

    def read_position(self) -> int:
        if not self.initialized:
            raise RuntimeError("valve is not initialized")
        if self.status_note != "confirmed":
            raise RuntimeError(f"valve position is not confirmed: {self.status_note}")
        return self.position

    def read_state(self) -> tuple[bool, int | None]:
        if not self.initialized:
            raise RuntimeError("valve is not initialized")
        if self.status_note != "confirmed":
            self.status_note = "confirmed"
        return True, self.position

    def wait_until_ready(self, timeout_s: float = 1.0, poll_interval_s: float = 0.05) -> bool:
        del timeout_s, poll_interval_s
        if not self.initialized:
            raise RuntimeError("valve is not initialized")
        self.status_note = "confirmed"
        return True
