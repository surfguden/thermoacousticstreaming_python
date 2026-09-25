"""Experiment-series output; only host-owned frame copies enter this worker."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from concurrent.futures import Future, ThreadPoolExecutor
import shutil
import tempfile
from typing import Any

import numpy as np
from PIL import Image

from .commands import CameraSequenceResult
from .experiments import Expansion, PlannedExperiment


def json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(json_ready(value), stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    temporary.replace(path)


class SeriesStorage:
    def __init__(self, root: Path, expansion: Expansion, image_format: str,
                 *, continuing_batch: bool = False) -> None:
        if image_format not in {"frames", "stacked"}:
            raise ValueError("TIFF format must be frames or stacked")
        if not root.is_dir():
            raise ValueError("Experiment base folder must exist and be a directory")
        existing = list(root.iterdir())
        if existing and not continuing_batch:
            raise ValueError("Experiment base folder must be empty before queueing a batch")
        if continuing_batch and any(not path.is_dir() or not path.name.startswith("experiment_batch_")
                                    for path in existing):
            raise ValueError("Experiment base folder contains files outside this batch")
        for index in range(1, 1001):
            candidate = root / f"experiment_batch_{index:04d}"
            try:
                candidate.mkdir()
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeError("Could not allocate a unique experiment series folder")
        self.folder = candidate
        self.metadata = candidate / "metadata"
        self.metadata.mkdir()
        self.image_format = image_format
        self.events = self.metadata / "events.jsonl"
        write_json(self.metadata / "definition.json", expansion.definition)
        write_json(self.metadata / "manifest.json", {
            "schema_version": 1,
            "experiments": [{"experiment_id": item.experiment_id,
                             "relative_path": item.relative_path,
                             "parameters": item.parameters,
                             "repeat_index": item.repeat_index}
                            for item in expansion.experiments],
        })
        self.status("queued", {})

    def status(self, state: str, detail: dict[str, Any]) -> None:
        write_json(self.metadata / "status.json", {
            "state": state, "updated_utc": datetime.now(timezone.utc).isoformat(), **detail,
        })

    def event(self, kind: str, **detail: Any) -> None:
        with self.events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(json_ready({"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                                                 "event": kind, **detail}), allow_nan=False) + "\n")

    def save_frames(self, experiment: PlannedExperiment, capture: CameraSequenceResult,
                    metadata: dict[str, Any]) -> dict[str, Any]:
        destination = self.folder / experiment.relative_path
        expected = next(step["args"]["frame_count"] for step in experiment.steps
                        if step["type"] == "camera_configure")
        count = len(capture.frames)
        if count != expected or len(capture.timestamps) != count or len(capture.host_received_utc) != count:
            raise ValueError(f"Incomplete camera acquisition: expected {expected}, got {count} frames, "
                             f"{len(capture.timestamps)} SDK stamps and {len(capture.host_received_utc)} host stamps")
        if any(not stamp for stamp in capture.timestamps):
            raise ValueError("Camera SDK timestamp missing; refusing to label acquisition complete")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"Experiment folder already exists: {destination}")
        folder = Path(tempfile.mkdtemp(prefix=".capture_", dir=destination.parent))
        try:
            record = self._write_frames(folder, experiment, capture, metadata, count)
            folder.rename(destination)
            return record
        finally:
            if folder.exists():
                shutil.rmtree(folder)

    def _write_frames(self, folder: Path, experiment: PlannedExperiment,
                      capture: CameraSequenceResult, metadata: dict[str, Any],
                      count: int) -> dict[str, Any]:
        frame_data = [np.array(frame, copy=True) for frame in capture.frames]
        if any(data.ndim != 2 for data in frame_data):
            raise ValueError("Camera sequence contains a non-grayscale image")
        pages: list[dict[str, Any]] = []
        if self.image_format == "frames":
            for index, data in enumerate(frame_data, 1):
                name = f"frame_{index:06d}.tif"
                Image.fromarray(data).save(folder / name)
                pages.append({"index": index, "filename": name, "page_index": 0})
        else:
            images = [Image.fromarray(data) for data in frame_data]
            images[0].save(folder / "sequence.tif", save_all=True, append_images=images[1:])
            pages = [{"index": index, "filename": "sequence.tif", "page_index": index - 1}
                     for index in range(1, count + 1)]
        frame_records = [{**page, "camera_sdk_timestamp": capture.timestamps[index],
                          "host_received_utc": capture.host_received_utc[index]}
                         for index, page in enumerate(pages)]
        record = {
            "schema_version": 1, "experiment_id": experiment.experiment_id,
            "relative_path": experiment.relative_path,
            "parameters": experiment.parameters, "repeat_index": experiment.repeat_index,
            "image_format": self.image_format, "acquisition_status": "complete",
            "physical_dio0_edges_verified": False,
            "frame_interval_accuracy_verified": False,
            "timing_evidence_note": (
                "Finite SDK configuration and N captured frames are recorded; "
                "without hardware loopback they do not prove exact physical edge count or interval accuracy"
            ),
            "frame_count": count, "frames": frame_records,
            "timestamp_clock_domains": {
                "camera_sdk_timestamp": "DCAM camera clock; epoch/UTC relationship not assumed",
                "host_received_utc": "Host UTC wall clock when frame copy arrived",
            },
            "camera_settings": capture.settings, **metadata,
        }
        write_json(folder / "experiment.json", record)
        return record

    def finalize_experiment(self, experiment: PlannedExperiment, outcome: dict[str, Any]) -> None:
        path = self.folder / experiment.relative_path / "experiment.json"
        with path.open("r", encoding="utf-8") as stream:
            record = json.load(stream)
        record["post_acquisition"] = outcome
        write_json(path, record)

class FileWorker:
    """One serialized file thread; frames never reference a DCAM-owned buffer."""

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="experiment-files")

    def submit(self, storage: SeriesStorage, experiment: PlannedExperiment,
               capture: CameraSequenceResult, metadata: dict[str, Any]) -> Future:
        # CameraWorker has already copied each frame out of the DCAM buffer.
        # Do not duplicate a potentially large sequence on the Qt/UI thread.
        return self._pool.submit(storage.save_frames, experiment, capture, metadata)

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=False)
