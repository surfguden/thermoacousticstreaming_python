from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any


class HardwareCommandExecutor:
    """Runs blocking device calls away from the Qt event thread."""

    def __init__(self, max_workers: int = 6) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="lab-device")

    def submit(self, action: Callable[[], Any]) -> Future[Any]:
        return self._pool.submit(action)

    def shutdown(self, *, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)
