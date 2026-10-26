"""Pixel statistics and line profiles of a frame; raw values only, in pixel units.

Nothing here knows about display stretch, Qt or the camera. Rectangles are
``(x, y, width, height)`` in image pixels with the origin at the top-left pixel.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class RoiStats:
    rect: Rect
    pixel_count: int
    mean: float
    std: float  # population standard deviation (ddof=0)
    minimum: int | float
    maximum: int | float


def clamp_rect(rect: Rect, shape: tuple[int, ...]) -> Rect | None:
    """Intersect a rectangle with an image of ``shape`` (rows, columns); None if nothing remains."""
    rows, columns = shape[0], shape[1]
    x, y, width, height = rect
    left, top = max(x, 0), max(y, 0)
    right, bottom = min(x + width, columns), min(y + height, rows)
    if right <= left or bottom <= top:
        return None
    return left, top, right - left, bottom - top


def rect_from_points(start: tuple[float, float], end: tuple[float, float],
                     shape: tuple[int, ...]) -> Rect | None:
    """Pixel rectangle covering every pixel touched by a drag between two image positions.

    Positions are in image pixel units where pixel ``i`` spans ``[i, i + 1)``. A drag that
    covers no pixel (a plain click) gives None.
    """
    if not all(math.isfinite(value) for value in (*start, *end)):
        return None
    left, right = sorted((start[0], end[0]))
    top, bottom = sorted((start[1], end[1]))
    x0, y0 = math.floor(left), math.floor(top)
    x1, y1 = math.ceil(right), math.ceil(bottom)
    if x1 == x0 or y1 == y0:
        return None
    return clamp_rect((x0, y0, x1 - x0, y1 - y0), shape)


def move_rect(rect: Rect, dx: int, dy: int, shape: tuple[int, ...]) -> Rect:
    """Shift a rectangle, keeping its size and the whole rectangle inside the image."""
    x, y, width, height = rect
    x = min(max(x + dx, 0), max(shape[1] - width, 0))
    y = min(max(y + dy, 0), max(shape[0] - height, 0))
    return x, y, width, height


def roi_statistics(frame: np.ndarray, rect: Rect) -> RoiStats | None:
    """Statistics of the raw pixels inside ``rect`` (clamped to the frame); None if empty."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 2 or frame.size == 0:
        return None
    clamped = clamp_rect(rect, frame.shape)
    if clamped is None:
        return None
    x, y, width, height = clamped
    region = frame[y:y + height, x:x + width]
    return RoiStats(
        rect=clamped,
        pixel_count=int(region.size),
        mean=float(region.mean(dtype=np.float64)),
        std=float(region.std(dtype=np.float64)),
        minimum=region.min().item(),
        maximum=region.max().item(),
    )


def row_profile(frame: np.ndarray, y: int) -> np.ndarray | None:
    """Raw values along row ``y`` (index = column x); None if outside the frame."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 2 or not 0 <= y < frame.shape[0]:
        return None
    return np.array(frame[y, :])


def column_profile(frame: np.ndarray, x: int) -> np.ndarray | None:
    """Raw values down column ``x`` (index = row y); None if outside the frame."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 2 or not 0 <= x < frame.shape[1]:
        return None
    return np.array(frame[:, x])
