"""Asynchronous, per-series temperature CSV writer."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import csv
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic


_FIELDS = ("timestamp_utc", "elapsed_s", "channel_1_c", "channel_2_c",
           "channel_1_target_c", "channel_2_target_c", "error")


class TemperatureRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.started_at = monotonic()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="temperature-log")
        self._futures: list[Future] = []
        self._closed = False
        # A requested log must exist before the first hardware action.
        with path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=_FIELDS)
            writer.writeheader()
            writer.writerow({"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                             "elapsed_s": 0, "error": "series_start"})

    def add(self, sample: dict) -> None:
        if self._closed:
            return
        row = {key: sample.get(key) for key in _FIELDS}
        row["elapsed_s"] = max(0.0, sample["monotonic_s"] - self.started_at)
        self._futures.append(self._executor.submit(self._write, row))

    def _write(self, row: dict) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as stream:
            csv.DictWriter(stream, fieldnames=_FIELDS).writerow(row)

    def error(self) -> str | None:
        remaining = []
        for future in self._futures:
            if not future.done():
                remaining.append(future)
            else:
                try:
                    future.result()
                except Exception as exc:
                    return str(exc)
        self._futures = remaining
        return None

    def close(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=False)

    def drained(self) -> bool:
        return all(future.done() for future in self._futures)
