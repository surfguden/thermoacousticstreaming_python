from __future__ import annotations


class SimulatedCamera:
    def __init__(self) -> None:
        self.initialized = False
        self.capture_active = False
        self.frame_count = 0

    def open_camera(self) -> object:
        self.initialized = True
        return self

    def close(self) -> None:
        self.stop_capture()
        self.initialized = False

    def capture_snapshot(self) -> dict[str, int]:
        self.frame_count += 1
        return {"frames": 1, "frame_number": self.frame_count}

    def stop_capture(self) -> None:
        self.capture_active = False
