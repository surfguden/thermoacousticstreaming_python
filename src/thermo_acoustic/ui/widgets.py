from __future__ import annotations

import math
from datetime import datetime

import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class ScopePlot(QWidget):
    """Small dependency-free plot for typed AD2 scope results."""

    _COLORS = (QColor("#4da3ff"), QColor("#ff8c42"), QColor("#5fd35f"), QColor("#d66cff"))

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.samples_by_channel: dict[int, list[float]] = {}
        self.sample_frequency_hz = 1.0
        self._x_view: tuple[float, float] | None = None
        self._y_view: tuple[float, float] | None = None
        self._drag_origin: QPoint | None = None
        self._drag_views: tuple[tuple[float, float], tuple[float, float]] | None = None
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_samples(
        self, samples_by_channel: dict[int, list[float]], sample_frequency_hz: float | None = None
    ) -> None:
        self.samples_by_channel = {
            int(channel): [float(value) for value in samples]
            for channel, samples in samples_by_channel.items()
        }
        if sample_frequency_hz is not None and sample_frequency_hz > 0:
            self.sample_frequency_hz = float(sample_frequency_hz)
        self.reset_view()

    def reset_view(self) -> None:
        self._x_view = None
        self._y_view = None
        self.update()

    def _data_bounds(self) -> tuple[tuple[float, float], tuple[float, float]] | None:
        finite = [
            value
            for samples in self.samples_by_channel.values()
            for value in samples
            if math.isfinite(value)
        ]
        if not finite:
            return None
        low, high = min(finite), max(finite)
        if math.isclose(low, high):
            low -= 0.5
            high += 0.5
        count = max((len(samples) for samples in self.samples_by_channel.values()), default=1)
        return (0.0, max((count - 1) / self.sample_frequency_hz, 1 / self.sample_frequency_hz)), (low, high)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        area = QRectF(42, 16, max(1, self.width() - 58), max(1, self.height() - 48))
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawRect(area)
        bounds = self._data_bounds()
        if bounds is None:
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "No scope data")
            return
        (data_x0, data_x1), (data_y0, data_y1) = bounds
        x0, x1 = self._x_view or (data_x0, data_x1)
        low, high = self._y_view or (data_y0, data_y1)
        for color_index, (channel, samples) in enumerate(sorted(self.samples_by_channel.items())):
            points = []
            for index, value in enumerate(samples):
                if not math.isfinite(value):
                    continue
                time_s = index / self.sample_frequency_hz
                if not x0 <= time_s <= x1:
                    continue
                x = area.left() + area.width() * (time_s - x0) / (x1 - x0)
                y = area.bottom() - area.height() * (value - low) / (high - low)
                points.append(QPointF(x, y))
            painter.setPen(QPen(self._COLORS[color_index % len(self._COLORS)], 1.5))
            if len(points) == 1:
                painter.drawEllipse(points[0], 2, 2)
            elif points:
                painter.drawPolyline(points)
            painter.drawText(
                QPointF(area.left() + color_index * 72, self.height() - 10),
                f"CH{channel + 1}",
            )
        painter.setPen(self.palette().text().color())
        painter.drawText(2, 22, f"{high:.4g}")
        painter.drawText(2, int(area.bottom()), f"{low:.4g}")
        painter.drawText(area, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, "time (s)")
        painter.drawText(int(area.left()), self.height() - 10, f"{x0:.5g}")
        painter.drawText(int(area.right()) - 70, self.height() - 10, f"{x1:.5g}")

    def wheelEvent(self, event) -> None:
        bounds = self._data_bounds()
        if bounds is None:
            return
        x_view = self._x_view or bounds[0]
        y_view = self._y_view or bounds[1]
        factor = 0.8 if event.angleDelta().y() > 0 else 1.25
        cursor_x = min(max((event.position().x() - 42) / max(self.width() - 58, 1), 0.0), 1.0)
        cursor_y = min(max((event.position().y() - 16) / max(self.height() - 48, 1), 0.0), 1.0)
        x_anchor = x_view[0] + cursor_x * (x_view[1] - x_view[0])
        y_anchor = y_view[1] - cursor_y * (y_view[1] - y_view[0])
        self._x_view = (
            x_anchor - (x_anchor - x_view[0]) * factor,
            x_anchor + (x_view[1] - x_anchor) * factor,
        )
        self._y_view = (
            y_anchor - (y_anchor - y_view[0]) * factor,
            y_anchor + (y_view[1] - y_anchor) * factor,
        )
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._data_bounds() is not None:
            bounds = self._data_bounds()
            self._drag_origin = event.position().toPoint()
            self._drag_views = (self._x_view or bounds[0], self._y_view or bounds[1])
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is None or self._drag_views is None:
            return
        dx = event.position().x() - self._drag_origin.x()
        dy = event.position().y() - self._drag_origin.y()
        x_view, y_view = self._drag_views
        x_shift = -dx / max(self.width() - 58, 1) * (x_view[1] - x_view[0])
        y_shift = dy / max(self.height() - 48, 1) * (y_view[1] - y_view[0])
        self._x_view = (x_view[0] + x_shift, x_view[1] + x_shift)
        self._y_view = (y_view[0] + y_shift, y_view[1] + y_shift)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            self._drag_views = None
            self.unsetCursor()


class ScopePlotWindow(QDialog):
    """Reusable, non-modal scope viewer with Qt-native zoom and pan."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AD2 oscilloscope capture")
        self.resize(1000, 650)
        layout = QVBoxLayout(self)
        self.plot = ScopePlot()
        layout.addWidget(self.plot, 1)
        hint = QLabel("Mouse wheel: zoom · left drag: pan")
        reset = QPushButton("Autoscale / reset")
        reset.clicked.connect(self.plot.reset_view)
        actions = QHBoxLayout()
        actions.addWidget(hint)
        actions.addStretch(1)
        actions.addWidget(reset)
        layout.addLayout(actions)

    def set_samples(self, samples: dict[int, list[float]], sample_frequency_hz: float) -> None:
        self.plot.set_samples(samples, sample_frequency_hz)


#: Fraction of pixels ignored at each end by the one-shot robust stretch
#: (0.2 % per side, 0.4 % total -- close to ImageJ's Enhance Contrast default of
#: 0.35 % saturated). Deliberately much tighter than junjiebranch's "90 %
#: Dynamic" (5 % per side): sparse bright tracer particles occupy far less
#: than 5 % of a frame and would simply saturate. Untuned against this lab's
#: images; change here if real frames call for a different tail.
ROBUST_TAIL_FRACTION = 0.002

MIN_ZOOM = 0.05
MAX_ZOOM = 64.0
ZOOM_STEP = 1.25


def normalized_display_limits(observed_range: tuple[int, int] | None) -> tuple[int, int] | None:
    """Turn an observed (low, high) into valid, strictly increasing display limits.

    A constant frame (low == high) gets a one-count-wide window so it can still
    be displayed and adjusted instead of dividing by zero.
    """
    if observed_range is None:
        return None
    low, high = observed_range
    if low >= high:
        low, high = (low, low + 1) if low < 65535 else (65534, 65535)
    return int(low), int(high)


def robust_display_limits(frame: object, tail: float = ROBUST_TAIL_FRACTION) -> tuple[int, int] | None:
    """One-shot percentile stretch limits for a 16-bit frame (display only).

    Ignores `tail` of the pixels at each end, so isolated hot or dead pixels do
    not set the window. Exact (65536-bin histogram, no interpolation), so the
    result is a pixel value that occurs in the frame. Returns None for anything
    that is not a non-empty 2-D uint16 array. A frame whose clipped ends meet
    (constant or nearly so) falls back to its observed min/max, normalized.
    """
    if not (isinstance(frame, np.ndarray) and frame.ndim == 2 and frame.dtype == np.uint16 and frame.size):
        return None
    if not 0 <= tail < 0.5:
        raise ValueError("tail must be within [0, 0.5)")
    counts = np.bincount(frame.ravel(), minlength=65536)
    cumulative = np.cumsum(counts)
    total = int(frame.size)
    observed = (int(np.flatnonzero(counts)[0]), int(np.flatnonzero(counts)[-1]))
    low = int(np.searchsorted(cumulative, total * tail, side="right"))
    high = int(np.searchsorted(cumulative, total * (1.0 - tail), side="left"))
    low, high = min(max(low, observed[0]), observed[1]), min(max(high, observed[0]), observed[1])
    if low >= high:
        return normalized_display_limits(observed)
    return low, high


class CameraPreview(QLabel):
    """Owns a copied frame so SDK/NumPy buffers may be released safely.

    Display adjustments (intensity limits, zoom, pan) only change how the copy
    is drawn; the raw frame is never modified. `pixel_at()` maps widget
    positions back through the same view transform, so hover readouts stay
    correct at any zoom and pan.
    """

    pixel_hovered = Signal(object)
    view_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("No image")
        self._image: QImage | None = None
        self._pixmap: QPixmap | None = None
        self._raw_frame: np.ndarray | None = None
        self._display_limits: tuple[int, int] | None = None
        self._hover_position: QPointF | None = None
        # Zoom in "device pixels per image pixel" (1.0 == 100 %); None == fit.
        self._zoom: float | None = None
        self._center: QPointF | None = None
        self._drag_start: tuple[QPointF, QPointF] | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(260, 180)
        self.setFrameShape(QLabel.Shape.Box)
        self.setMouseTracking(True)

    @property
    def has_image(self) -> bool:
        return self._image is not None

    @property
    def raw_frame(self) -> np.ndarray | None:
        return self._raw_frame

    @property
    def display_limits(self) -> tuple[int, int] | None:
        return self._display_limits

    @property
    def is_fit(self) -> bool:
        return self._zoom is None

    def set_frame(self, frame: object, limits: tuple[int, int] | None = None) -> None:
        previous_shape = None if self._image is None else (self._image.height(), self._image.width())
        self._raw_frame = np.ascontiguousarray(frame).copy() if isinstance(frame, np.ndarray) and frame.ndim == 2 else None
        self._display_limits = limits
        try:
            image = self._display_image(frame)
        except (TypeError, ValueError) as exc:
            self._image = None
            self._pixmap = None
            self.setText(f"Frame metadata: {frame!r}\n({exc})")
            self.update()
            self.pixel_hovered.emit(None)
            return
        self._image = image.copy()
        self._pixmap = QPixmap.fromImage(self._image)
        self.setText("")
        if previous_shape != (self._image.height(), self._image.width()):
            self._zoom, self._center = None, None  # new geometry: start from fit
        self.update()
        self.view_changed.emit()
        if self._hover_position is not None:
            self.pixel_hovered.emit(self.pixel_at(self._hover_position))

    def set_display_limits(self, limits: tuple[int, int] | None) -> None:
        self._display_limits = limits
        if self._raw_frame is not None:
            self._image = self._display_image(self._raw_frame)
            self._pixmap = QPixmap.fromImage(self._image)
            self.update()

    def _display_image(self, frame: object) -> QImage:
        raw = self._raw_frame
        if raw is not None and raw.dtype == np.uint16 and self._display_limits is not None:
            low, high = self._display_limits
            if not 0 <= low < high <= 65535:
                raise ValueError("Display limits must be within 0..65535 and increasing")
            scaled = np.clip((raw.astype(np.float32) - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)
            return self._to_qimage(scaled)
        return self._to_qimage(raw if raw is not None else frame)

    # ------------------------------------------------------------------ view
    def _device_ratio(self) -> float:
        return max(float(self.devicePixelRatioF()), 1e-6)

    def effective_scale(self) -> float:
        """Logical (Qt) pixels drawn per image pixel at the current view."""
        if self._image is None:
            return 1.0
        if self._zoom is not None:
            return self._zoom / self._device_ratio()
        area = self.contentsRect()
        return max(min(area.width() / self._image.width(), area.height() / self._image.height()), 1e-6)

    def zoom_percent(self) -> float:
        """Displayed size as a percentage of 1 image pixel per physical screen pixel."""
        return self.effective_scale() * self._device_ratio() * 100.0

    def _view_geometry(self) -> tuple[QRectF, QRectF] | None:
        """(visible source rect in image px, target rect in widget px)."""
        if self._image is None:
            return None
        area = self.contentsRect()
        iw, ih = self._image.width(), self._image.height()
        scale = self.effective_scale()
        vis_w, vis_h = min(float(iw), area.width() / scale), min(float(ih), area.height() / scale)
        center = self._center if self._center is not None else QPointF(iw / 2, ih / 2)
        cx = min(max(center.x(), vis_w / 2), iw - vis_w / 2)
        cy = min(max(center.y(), vis_h / 2), ih - vis_h / 2)
        source = QRectF(cx - vis_w / 2, cy - vis_h / 2, vis_w, vis_h)
        width, height = vis_w * scale, vis_h * scale
        target = QRectF(
            area.x() + (area.width() - width) / 2, area.y() + (area.height() - height) / 2, width, height
        )
        return source, target

    def image_target_rect(self) -> QRectF | None:
        """Widget-coordinate rectangle the visible part of the image is drawn into."""
        geometry = self._view_geometry()
        return None if geometry is None else geometry[1]

    def visible_source_rect(self) -> QRectF | None:
        """Image-coordinate rectangle currently visible."""
        geometry = self._view_geometry()
        return None if geometry is None else geometry[0]

    def fit_to_window(self) -> None:
        self._zoom, self._center = None, None
        self.update()
        self.view_changed.emit()

    def zoom_100(self) -> None:
        self._set_zoom(1.0, anchor=None)

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        if self._image is None:
            return
        self._set_zoom(self.effective_scale() * self._device_ratio() * factor, anchor)

    def _set_zoom(self, zoom: float, anchor: QPointF | None) -> None:
        geometry = self._view_geometry()
        if geometry is None:
            return
        source, target = geometry
        old_scale = self.effective_scale()
        area = self.contentsRect()
        if anchor is None:
            anchor = QPointF(area.center())
        # Image point under the anchor must stay under it after the zoom.
        point = QPointF(
            source.x() + (anchor.x() - target.x()) / old_scale,
            source.y() + (anchor.y() - target.y()) / old_scale,
        )
        zoom = min(max(zoom, MIN_ZOOM), MAX_ZOOM)
        new_scale = zoom / self._device_ratio()
        iw, ih = self._image.width(), self._image.height()
        fit_scale = max(min(area.width() / iw, area.height() / ih), 1e-6)
        if new_scale <= fit_scale + 1e-9:
            self.fit_to_window()
            return
        vis_w, vis_h = min(float(iw), area.width() / new_scale), min(float(ih), area.height() / new_scale)
        left = area.x() + (area.width() - vis_w * new_scale) / 2
        top = area.y() + (area.height() - vis_h * new_scale) / 2
        self._zoom = zoom
        self._center = QPointF(
            point.x() - (anchor.x() - left) / new_scale + vis_w / 2,
            point.y() - (anchor.y() - top) / new_scale + vis_h / 2,
        )
        self.update()
        self.view_changed.emit()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # frame, and the text shown when there is no image
        geometry = self._view_geometry()
        if geometry is None or self._pixmap is None:
            return
        source, target = geometry
        painter = QPainter(self)
        painter.setClipRect(self.contentsRect())
        # Smooth when shrinking; nearest-neighbour when magnifying so single
        # pixels stay visible and readable against the pixel readout.
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.effective_scale() < 1.0)
        painter.drawPixmap(target, self._pixmap, source)
        painter.end()

    # --------------------------------------------------------------- mapping
    def pixel_at(self, position: QPointF) -> tuple[int, int, int | float] | None:
        raw, geometry = self._raw_frame, self._view_geometry()
        if raw is None or geometry is None:
            return None
        source, target = geometry
        if target.width() <= 0 or target.height() <= 0:
            return None
        px, py = position.x() - target.x(), position.y() - target.y()
        if not 0 <= px < target.width() or not 0 <= py < target.height():
            return None
        scale = self.effective_scale()
        x = min(int(source.x() + px / scale), raw.shape[1] - 1)
        y = min(int(source.y() + py / scale), raw.shape[0] - 1)
        return x, y, raw[y, x].item()

    # ---------------------------------------------------------------- events
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._image is not None:
            geometry = self._view_geometry()
            if geometry is not None:
                source = geometry[0]
                self._drag_start = (QPointF(event.position()), source.center())
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None
            self.unsetCursor()
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self._hover_position = QPointF(event.position())
        if self._drag_start is not None and self._zoom is not None:
            origin, center = self._drag_start
            scale = self.effective_scale()
            self._center = QPointF(
                center.x() - (event.position().x() - origin.x()) / scale,
                center.y() - (event.position().y() - origin.y()) / scale,
            )
            self.update()
            self.view_changed.emit()
        elif self._drag_start is None:
            pixel = self.pixel_at(self._hover_position)
            self.setCursor(Qt.CursorShape.CrossCursor if pixel is not None else Qt.CursorShape.ArrowCursor)
        self.pixel_hovered.emit(self.pixel_at(self._hover_position))
        super().mouseMoveEvent(event)

    def wheelEvent(self, event) -> None:
        if self._image is None:
            return
        factor = ZOOM_STEP if event.angleDelta().y() > 0 else 1 / ZOOM_STEP
        self.zoom_by(factor, QPointF(event.position()))
        event.accept()

    def leaveEvent(self, event) -> None:
        self._hover_position = None
        self.pixel_hovered.emit(None)
        self.unsetCursor()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.view_changed.emit()

    @staticmethod
    def _to_qimage(frame: object) -> QImage:
        if isinstance(frame, QImage):
            return frame.copy()
        if isinstance(frame, Image.Image):
            array = np.asarray(frame.convert("RGBA"), dtype=np.uint8)
            return QImage(
                array.data,
                array.shape[1],
                array.shape[0],
                int(array.strides[0]),
                QImage.Format.Format_RGBA8888,
            ).copy()
        if not isinstance(frame, np.ndarray):
            raise TypeError("no pixel array available")
        array = np.ascontiguousarray(frame)
        if array.ndim == 2:
            if array.dtype == np.uint16:
                return QImage(
                    array.data,
                    array.shape[1],
                    array.shape[0],
                    int(array.strides[0]),
                    QImage.Format.Format_Grayscale16,
                ).copy()
            if array.dtype != np.uint8:
                finite = array[np.isfinite(array)]
                if finite.size == 0:
                    array = np.zeros(array.shape, dtype=np.uint8)
                else:
                    low, high = float(finite.min()), float(finite.max())
                    scale = 255.0 / (high - low) if high > low else 1.0
                    array = np.clip((array - low) * scale, 0, 255).astype(np.uint8)
                array = np.ascontiguousarray(array)
            return QImage(
                array.data,
                array.shape[1],
                array.shape[0],
                int(array.strides[0]),
                QImage.Format.Format_Grayscale8,
            ).copy()
        if array.ndim == 3 and array.dtype == np.uint8 and array.shape[2] in (3, 4):
            image_format = (
                QImage.Format.Format_RGB888
                if array.shape[2] == 3
                else QImage.Format.Format_RGBA8888
            )
            return QImage(
                array.data,
                array.shape[1],
                array.shape[0],
                int(array.strides[0]),
                image_format,
            ).copy()
        raise ValueError(f"unsupported frame shape/dtype: {array.shape}/{array.dtype}")


class CameraHistogram(QWidget):
    """Log-height histogram across the full 16-bit pixel-value domain."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.counts = np.zeros(256, dtype=np.int64)
        self.pixel_count = 0
        self.saturated_count = 0
        self.observed_range: tuple[int, int] | None = None
        self.limits: tuple[int, int] | None = None
        self.setMinimumHeight(110)

    def set_frame(self, frame: object) -> None:
        if isinstance(frame, np.ndarray) and frame.ndim == 2 and frame.dtype == np.uint16 and frame.size:
            values = np.bincount(frame.ravel(), minlength=65536)
            self.counts = values.reshape(256, 256).sum(axis=1)
            self.pixel_count = int(frame.size)
            self.saturated_count = int(values[-1])
            occupied = np.flatnonzero(values)
            self.observed_range = (int(occupied[0]), int(occupied[-1]))
        else:
            self.counts = np.zeros(256, dtype=np.int64)
            self.pixel_count = 0
            self.saturated_count = 0
            self.observed_range = None
        self.update()

    def set_limits(self, limits: tuple[int, int] | None) -> None:
        self.limits = limits
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#20242a"))
        left, top = 46, 8
        width, height = max(self.width() - 60, 1), max(self.height() - 31, 1)
        painter.setPen(QPen(QColor("#b6bec9")))
        painter.drawLine(left, top + height, left + width, top + height)
        painter.drawText(2, top + height + 15, "0")
        painter.drawText(left + width - 39, top + height + 15, "65535")
        if self.pixel_count:
            heights = np.log1p(self.counts)
            peak = float(heights.max())
            painter.setPen(QPen(QColor("#8baac4")))
            for bin_index, value in enumerate(heights):
                x = left + round(bin_index * width / 255)
                y = top + height - round(float(value) * height / peak) if peak else top + height
                painter.drawLine(x, top + height, x, y)
        if self.limits is not None:
            for value, color in zip(self.limits, ("#ffb347", "#40d6c4")):
                painter.setPen(QPen(QColor(color), 2))
                x = left + round(value * width / 65535)
                painter.drawLine(x, top, x, top + height)
        painter.end()


class CameraImageWindow(QDialog):
    """Reusable non-modal camera viewer for every acquisition mode.

    Everything here is display-only: intensity limits, zoom and pan change how
    the viewer's copy of a frame is drawn, never the frame itself, what is
    saved, or any camera setting.
    """

    #: Seconds without a new frame, while the camera reports capture active,
    #: before the state line says frames have stopped arriving.
    STALE_AFTER_S = 3.0
    _GREEN, _AMBER, _RED, _GREY = "#2e7d32", "#a65a00", "#b71c1c", "#5f6b7a"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Camera acquisition")
        self.resize(900, 700)
        layout = QVBoxLayout(self)
        self.preview = CameraPreview()
        self.preview.setMinimumSize(640, 480)
        # A QLabel's size hint follows its pixmap. Ignore that hint so each
        # new sensor frame cannot resize or reposition the window.
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.status = QLabel("No acquisition")
        self.status.setWordWrap(True)
        self.preview_state = QLabel("No acquisition yet")
        self.frame_info = QLabel("Image: — · Exposure (camera readback): — · Last frame: none yet")
        self.frame_info.setWordWrap(True)

        self.adjust_intensity_button = QPushButton("Min–max (once)")
        self.adjust_intensity_button.setToolTip(
            "Set the display range to this frame's lowest and highest pixel value, then keep it "
            "for later frames. A single hot pixel can set the high end.")
        self.adjust_intensity_button.setEnabled(False)
        self.adjust_intensity_button.clicked.connect(self.adjust_intensity)
        self.robust_button = QPushButton("Robust auto (once)")
        self.robust_button.setToolTip(
            f"Set the display range from this frame, ignoring the darkest and brightest "
            f"{ROBUST_TAIL_FRACTION * 100:g}% of pixels so isolated hot or dead pixels do not set it, "
            "then keep it for later frames. Display only.")
        self.robust_button.setEnabled(False)
        self.robust_button.clicked.connect(self.robust_auto)
        self.autoscale_checkbox = QCheckBox("Autoscale every frame (min–max)")
        self.autoscale_checkbox.toggled.connect(self._autoscale_changed)
        self.full_range_button = QPushButton("Full range")
        self.full_range_button.setToolTip("Show the full 16-bit range 0–65535.")
        self.full_range_button.clicked.connect(self.full_range)
        self.limit_low = QSpinBox()
        self.limit_high = QSpinBox()
        for box, value in ((self.limit_low, 0), (self.limit_high, 65535)):
            box.setRange(0, 65535)
            box.setValue(value)
            box.setKeyboardTracking(False)
        self.limit_apply_button = QPushButton("Apply range")
        self.limit_apply_button.setToolTip(
            "Use the typed low/high as a fixed display range. It stays in force for every later "
            "frame until you choose another mode.")
        self.limit_apply_button.clicked.connect(self.apply_manual_range)

        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self.preview.fit_to_window)
        self.zoom_100_button = QPushButton("100%")
        self.zoom_100_button.setToolTip("One image pixel per screen pixel. An image already shown larger than that stays at Fit.")
        self.zoom_100_button.clicked.connect(self.preview.zoom_100)
        self.zoom_in_button = QPushButton("Zoom +")
        self.zoom_in_button.clicked.connect(lambda: self.preview.zoom_by(ZOOM_STEP))
        self.zoom_out_button = QPushButton("Zoom −")
        self.zoom_out_button.clicked.connect(lambda: self.preview.zoom_by(1 / ZOOM_STEP))
        self.zoom_label = QLabel("Zoom: —")
        self.preview.view_changed.connect(self._update_zoom_label)

        self.histogram = CameraHistogram()
        self.intensity_status = QLabel("16-bit display: full range 0–65535")
        self.intensity_status.setWordWrap(True)
        self.cursor_status = QLabel("Cursor (frame x, y, value): —")
        self.preview.pixel_hovered.connect(self._show_pixel)

        intensity_row = QHBoxLayout()
        for widget in (self.full_range_button, self.adjust_intensity_button, self.robust_button,
                       self.autoscale_checkbox, QLabel("Low"), self.limit_low, QLabel("High"),
                       self.limit_high, self.limit_apply_button):
            intensity_row.addWidget(widget)
        intensity_row.addStretch(1)
        view_row = QHBoxLayout()
        for widget in (self.fit_button, self.zoom_100_button, self.zoom_out_button,
                       self.zoom_in_button, self.zoom_label):
            view_row.addWidget(widget)
        view_row.addStretch(1)
        layout.addWidget(self.preview_state)
        layout.addWidget(self.frame_info)
        layout.addWidget(self.preview, 1)
        layout.addLayout(view_row)
        layout.addLayout(intensity_row)
        layout.addWidget(self.histogram)
        layout.addWidget(self.intensity_status)
        layout.addWidget(self.cursor_status)
        layout.addWidget(self.status)

        # Preview state. `_clock` is injectable so tests need no real waiting.
        self._clock = datetime.now
        self._connected: bool | None = None
        self._fault: str | None = None
        self._failure: str | None = None
        self._capture_active = False
        self._mode = "snapshot"
        self._waiting = False
        self._exposure_ms: float | None = None
        self._last_frame_at: datetime | None = None
        self._frame_description = "—"
        self._frames_since_start = 0
        self._dismissed = False
        self._limit_source = ""
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._render_state)
        self._update_zoom_label()
        self._render_state()

    # ---------------------------------------------------------- intensity
    @staticmethod
    def _frame_limits(observed_range: tuple[int, int] | None) -> tuple[int, int] | None:
        return normalized_display_limits(observed_range)

    def _apply_limits(self, limits: tuple[int, int] | None, *, update_preview: bool = True,
                      source: str | None = None) -> None:
        if source is not None:
            self._limit_source = source
        if update_preview:
            self.preview.set_display_limits(limits)
        self.histogram.set_limits(limits)
        for box, value in zip((self.limit_low, self.limit_high), limits or (0, 65535)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)
        if not self.histogram.pixel_count:
            self.intensity_status.setText("16-bit histogram unavailable for this frame")
            return
        if limits is None:
            display = "full range 0–65535"
        else:
            display = f"{self._limit_source or 'adjusted'} {limits[0]}–{limits[1]} (orange/teal lines)"
        saturated = self.histogram.saturated_count
        total = self.histogram.pixel_count
        observed_low, observed_high = self.histogram.observed_range
        self.intensity_status.setText(
            f"16-bit display: {display} · frame values: {observed_low}–{observed_high}"
            f" · pixels at 65535: {saturated}/{total} · display only, saved data unchanged"
        )

    def adjust_intensity(self) -> None:
        limits = self._frame_limits(self.histogram.observed_range)
        if limits is not None:
            self._apply_limits(limits, source="min–max")

    def robust_auto(self) -> None:
        limits = robust_display_limits(self.preview.raw_frame)
        if limits is None:
            self.intensity_status.setText("Robust auto needs a 16-bit frame")
            return
        self.autoscale_checkbox.setChecked(False)
        self._apply_limits(limits, source=f"robust ±{ROBUST_TAIL_FRACTION * 100:g}%")

    def apply_manual_range(self) -> None:
        low, high = self.limit_low.value(), self.limit_high.value()
        if low >= high:
            self.intensity_status.setText("Range not applied: low must be smaller than high")
            self._apply_limits(self.preview.display_limits, update_preview=False)
            return
        self.autoscale_checkbox.setChecked(False)
        self._apply_limits((low, high), source="fixed")

    def _autoscale_changed(self, checked: bool) -> None:
        if checked:
            self._limit_source = "autoscale"
            self.adjust_intensity()
            self._limit_source = "autoscale"

    def full_range(self) -> None:
        self.autoscale_checkbox.setChecked(False)
        self._apply_limits(None)

    def _show_pixel(self, pixel: object) -> None:
        self.cursor_status.setText(
            "Cursor (frame x, y, value): —" if pixel is None
            else f"Cursor (frame x, y, value): {pixel[0]}, {pixel[1]}, {pixel[2]}"
        )

    def _update_zoom_label(self) -> None:
        if not self.preview.has_image:
            self.zoom_label.setText("Zoom: —")
            return
        mode = "Fit" if self.preview.is_fit else "Manual"
        self.zoom_label.setText(f"Zoom: {mode} ({self.preview.zoom_percent():.0f}%)")

    # ------------------------------------------------------------- frames
    def show_frame(self, frame: object, status: str) -> None:
        self.histogram.set_frame(frame)
        frame_limits = self._frame_limits(self.histogram.observed_range)
        limits = frame_limits if self.autoscale_checkbox.isChecked() else self.preview.display_limits
        if frame_limits is None:
            limits = None
        self.preview.set_frame(frame, limits)
        self.adjust_intensity_button.setEnabled(frame_limits is not None)
        self.robust_button.setEnabled(frame_limits is not None)
        self._apply_limits(limits, update_preview=False)
        self.status.setText(status)
        if isinstance(frame, np.ndarray) and frame.ndim == 2:
            self._frame_description = f"{frame.shape[1]} × {frame.shape[0]} · {frame.dtype}"
        else:
            self._frame_description = "not a 2-D pixel array"
        self._last_frame_at = self._clock()
        self._frames_since_start += 1
        self._waiting = False
        self._failure = None
        self._render_state()
        # A viewer the operator closed stays closed until they start another
        # acquisition from the camera panel; frames keep updating its content.
        if not self._dismissed and not self.isVisible():
            self.show()

    # -------------------------------------------------------------- state
    def begin_acquisition(self, message: str) -> None:
        """An acquisition command was just issued from the camera panel."""
        self._dismissed = False
        self._waiting = True
        self._failure = None
        self._frames_since_start = 0
        self.status.setText(message)
        self._render_state()
        if not self.isVisible():
            self.show()

    def set_failure(self, message: str) -> None:
        self._failure = message or "unknown error"
        self._waiting = False
        self._render_state()

    def end_waiting(self) -> None:
        self._waiting = False
        self._render_state()

    def set_camera_state(self, *, connected: bool, fault: str | None, capture_active: bool,
                         mode: str | None, exposure_ms: float | None) -> None:
        if capture_active and not self._capture_active:
            self._frames_since_start = 0
            self._waiting = False
            self._failure = None
        self._connected = connected
        self._fault = fault
        self._capture_active = capture_active
        self._mode = mode or "snapshot"
        self._exposure_ms = exposure_ms
        self._render_state()

    def _render_state(self) -> None:
        now = self._clock()
        age = None if self._last_frame_at is None else max((now - self._last_frame_at).total_seconds(), 0.0)
        if self._failure:
            text, color = f"Preview failed: {self._failure}", self._RED
        elif self._connected is False:
            text, color = "Camera disconnected", self._GREY
        elif self._fault:
            text, color = f"Camera fault: {self._fault}", self._RED
        elif self._capture_active:
            label = "Preview running" if self._mode == "continuous" else f"Capture active ({self._mode})"
            if self._frames_since_start == 0:
                text, color = f"{label} — waiting for first frame", self._AMBER
            elif age is not None and age > self.STALE_AFTER_S:
                text, color = f"{label} — no new frame for {age:.0f} s", self._AMBER
            else:
                text, color = label, self._GREEN
        elif self._waiting:
            text, color = "Waiting for camera…", self._AMBER
        elif self._last_frame_at is not None:
            text, color = "Preview stopped", self._GREY
        else:
            text, color = "No acquisition yet", self._GREY
        self.preview_state.setText(text)
        self.preview_state.setStyleSheet(f"color: {color}; font-weight: 600;")
        exposure = ("not reported" if self._exposure_ms is None else f"{self._exposure_ms:g} ms")
        if self._last_frame_at is None:
            last = "none yet"
        else:
            last = f"{self._last_frame_at:%H:%M:%S.%f}"[:-3] + f" ({age:.1f} s ago)"
        self.frame_info.setText(
            f"Image: {self._frame_description} · Exposure (camera readback): {exposure}"
            f" · Last frame received: {last}"
        )

    def showEvent(self, event) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._dismissed = True
        super().closeEvent(event)
