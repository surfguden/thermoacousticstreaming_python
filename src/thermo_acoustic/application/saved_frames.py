"""Read-only access to frames saved by an experiment series.

Frame order comes from the ``frames`` list in each experiment's ``experiment.json``
(``index`` 1..N, plus the file and TIFF page). If that record is missing, incomplete or
inconsistent the experiment is refused with the specific reason; order is never guessed
from file names. Frames are read from disk one at a time with a small bounded cache.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

DEFAULT_CACHE_FRAMES = 4


class SavedFramesError(ValueError):
    """The folder is not a readable saved experiment (the message says why)."""


@dataclass(frozen=True)
class SavedFrameRecord:
    index: int  # 1-based, as written by the series
    path: Path
    page_index: int
    camera_sdk_timestamp: Any
    host_received_utc: Any


@dataclass(frozen=True)
class SavedExperimentInfo:
    experiment_id: str
    relative_path: str
    parameters: dict[str, Any]
    repeat_index: int | None
    folder: Path


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SavedFramesError(f"Cannot read {path}: {exc}") from exc


def find_experiments(folder: str | Path) -> list[SavedExperimentInfo]:
    """Experiments with saved frames under ``folder``.

    ``folder`` is either one experiment folder (holds ``experiment.json``) or a series folder
    (holds ``metadata/manifest.json``; only experiments that already have an ``experiment.json``
    are listed, in manifest order).
    """
    folder = Path(folder)
    if (folder / "experiment.json").is_file():
        record = _read_json(folder / "experiment.json")
        return [SavedExperimentInfo(str(record.get("experiment_id", folder.name)), folder.name,
                                    dict(record.get("parameters") or {}), record.get("repeat_index"),
                                    folder)]
    manifest_path = folder / "metadata" / "manifest.json"
    if not manifest_path.is_file():
        raise SavedFramesError(
            f"{folder} is neither an experiment folder (experiment.json) nor a series folder "
            "(metadata/manifest.json)")
    manifest = _read_json(manifest_path)
    entries = manifest.get("experiments") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        raise SavedFramesError(f"{manifest_path} has no experiments list")
    found = []
    for entry in entries:
        experiment_folder = folder / entry["relative_path"]
        if (experiment_folder / "experiment.json").is_file():
            found.append(SavedExperimentInfo(entry["experiment_id"], entry["relative_path"],
                                             dict(entry.get("parameters") or {}),
                                             entry.get("repeat_index"), experiment_folder))
    return found


class SavedExperiment:
    """The frames of one saved experiment, read on demand."""

    def __init__(self, folder: str | Path, *, cache_frames: int = DEFAULT_CACHE_FRAMES) -> None:
        self.folder = Path(folder)
        record = _read_json(self.folder / "experiment.json")
        if not isinstance(record, dict):
            raise SavedFramesError(f"{self.folder / 'experiment.json'} is not a JSON object")
        if record.get("acquisition_status") != "complete":
            raise SavedFramesError(
                f"Acquisition status is {record.get('acquisition_status')!r}, not 'complete'")
        frames = record.get("frames")
        if not isinstance(frames, list) or not frames:
            raise SavedFramesError("experiment.json has no frames list")
        if record.get("frame_count") != len(frames):
            raise SavedFramesError(
                f"frame_count {record.get('frame_count')!r} does not match the {len(frames)} frame records")
        if [item.get("index") for item in frames] != list(range(1, len(frames) + 1)):
            raise SavedFramesError("Frame records are not numbered 1..N in order; frame order is unclear")
        self.experiment_id = str(record.get("experiment_id", self.folder.name))
        self.parameters: dict[str, Any] = dict(record.get("parameters") or {})
        self.image_format = record.get("image_format")
        records = []
        for item in frames:
            path = self.folder / item["filename"]
            if not path.is_file():
                raise SavedFramesError(f"Frame {item['index']}: file {item['filename']} is missing")
            records.append(SavedFrameRecord(item["index"], path, int(item.get("page_index", 0)),
                                            item.get("camera_sdk_timestamp"),
                                            item.get("host_received_utc")))
        self.frames: tuple[SavedFrameRecord, ...] = tuple(records)
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._cache_frames = max(1, cache_frames)
        self.reads = 0  # disk reads so far (cache hits are not counted)

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def load_frame(self, position: int) -> np.ndarray:
        """Pixels of the frame at 0-based ``position`` (frame number ``position + 1``)."""
        if not 0 <= position < len(self.frames):
            raise IndexError(f"Frame position {position} outside 0..{len(self.frames) - 1}")
        cached = self._cache.get(position)
        if cached is not None:
            self._cache.move_to_end(position)
            return cached
        item = self.frames[position]
        try:
            with Image.open(item.path) as image:
                image.seek(item.page_index)
                pixels = np.array(image)
        except (OSError, EOFError, ValueError) as exc:
            raise SavedFramesError(f"Frame {item.index}: cannot read {item.path.name}: {exc}") from exc
        if pixels.ndim != 2:
            raise SavedFramesError(f"Frame {item.index} is not a single-channel image")
        pixels.setflags(write=False)
        self.reads += 1
        self._cache[position] = pixels
        while len(self._cache) > self._cache_frames:
            self._cache.popitem(last=False)
        return pixels
