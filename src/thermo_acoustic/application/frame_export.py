"""Save one camera frame exactly as it was received.

Used for the "Save current raw frame" action of the image viewer. It writes the pixels it is given, as a
TIFF through the same PIL path the experiment storage uses, and nothing else: no display range, zoom,
analysis ROI or marks, no camera command, no experiment folder. A frame carries no reliable exposure or
timestamp here, so none is recorded.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

SUPPORTED_DTYPES = (np.uint8, np.uint16)


def save_raw_frame(frame: object, path: str | Path) -> Path:
    """Write `frame` (a 2-D uint8/uint16 array) to `path` (.tif added when missing) and return the final path.
    The file is written beside the target and moved into place, so a failure leaves no half-written image."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 2 or frame.size == 0:
        raise ValueError("There is no 2-D grayscale frame to save")
    if frame.dtype.type not in SUPPORTED_DTYPES:
        raise ValueError(f"Frame pixel type {frame.dtype} is not saved (uint8 and uint16 are)")
    target = Path(path)
    if target.suffix.lower() not in {".tif", ".tiff"}:
        target = target.with_name(target.name + ".tif")
    pixels = np.array(frame, copy=True)  # never the viewer's or the camera's buffer
    partial = target.with_name(f".{target.name}.part")
    try:
        Image.fromarray(pixels).save(partial, format="TIFF")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target
