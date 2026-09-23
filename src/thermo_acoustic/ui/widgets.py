from __future__ import annotations

import math

import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget


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


class CameraPreview(QLabel):
    """Owns a copied QImage so SDK/NumPy buffers may be released safely."""

    pixel_hovered = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__("No image")
        self._image: QImage | None = None
        self._raw_frame: np.ndarray | None = None
        self._display_limits: tuple[int, int] | None = None
        self._hover_position: QPointF | None = None
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

    def set_frame(self, frame: object, limits: tuple[int, int] | None = None) -> None:
        self._raw_frame = np.ascontiguousarray(frame).copy() if isinstance(frame, np.ndarray) and frame.ndim == 2 else None
        self._display_limits = limits
        try:
            image = self._display_image(frame)
        except (TypeError, ValueError) as exc:
            self._image = None
            self.setPixmap(QPixmap())
            self.setText(f"Frame metadata: {frame!r}\n({exc})")
            self.pixel_hovered.emit(None)
            return
        self._image = image.copy()
        self.setText("")
        self._refresh_pixmap()
        if self._hover_position is not None:
            self.pixel_hovered.emit(self.pixel_at(self._hover_position))

    def set_display_limits(self, limits: tuple[int, int] | None) -> None:
        self._display_limits = limits
        if self._raw_frame is not None:
            self._image = self._display_image(self._raw_frame)
            self._refresh_pixmap()

    def _display_image(self, frame: object) -> QImage:
        raw = self._raw_frame
        if raw is not None and raw.dtype == np.uint16 and self._display_limits is not None:
            low, high = self._display_limits
            if not 0 <= low < high <= 65535:
                raise ValueError("Display limits must be within 0..65535 and increasing")
            scaled = np.clip((raw.astype(np.float32) - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)
            return self._to_qimage(scaled)
        return self._to_qimage(raw if raw is not None else frame)

    def pixel_at(self, position: QPointF) -> tuple[int, int, int | float] | None:
        raw, pixmap = self._raw_frame, self.pixmap()
        if raw is None or pixmap.isNull() or pixmap.width() <= 0 or pixmap.height() <= 0:
            return None
        area = self.contentsRect()
        left = area.x() + (area.width() - pixmap.width()) / 2
        top = area.y() + (area.height() - pixmap.height()) / 2
        px, py = position.x() - left, position.y() - top
        if not 0 <= px < pixmap.width() or not 0 <= py < pixmap.height():
            return None
        x = min(int(px * raw.shape[1] / pixmap.width()), raw.shape[1] - 1)
        y = min(int(py * raw.shape[0] / pixmap.height()), raw.shape[0] - 1)
        return x, y, raw[y, x].item()

    def mouseMoveEvent(self, event) -> None:
        self._hover_position = QPointF(event.position())
        pixel = self.pixel_at(self._hover_position)
        self.setCursor(Qt.CursorShape.CrossCursor if pixel is not None else Qt.CursorShape.ArrowCursor)
        self.pixel_hovered.emit(pixel)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_position = None
        self.pixel_hovered.emit(None)
        self.unsetCursor()
        super().leaveEvent(event)

    def _refresh_pixmap(self) -> None:
        if self._image is None:
            return
        self.setPixmap(
            QPixmap.fromImage(self._image).scaled(
                self.contentsRect().size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_pixmap()

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
    """Reusable non-modal camera viewer for every acquisition mode."""

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
        self.adjust_intensity_button = QPushButton("Adjust intensity")
        self.adjust_intensity_button.setEnabled(False)
        self.adjust_intensity_button.clicked.connect(self.adjust_intensity)
        self.autoscale_checkbox = QCheckBox("Autoscale every frame")
        self.autoscale_checkbox.toggled.connect(self._autoscale_changed)
        self.full_range_button = QPushButton("Full range")
        self.full_range_button.clicked.connect(self.full_range)
        self.histogram = CameraHistogram()
        self.intensity_status = QLabel("16-bit display: full range 0–65535")
        self.cursor_status = QLabel("Cursor (frame x, y, value): —")
        self.preview.pixel_hovered.connect(self._show_pixel)
        actions = QHBoxLayout()
        actions.addWidget(self.adjust_intensity_button)
        actions.addWidget(self.autoscale_checkbox)
        actions.addWidget(self.full_range_button)
        actions.addStretch(1)
        layout.addWidget(self.preview, 1)
        layout.addLayout(actions)
        layout.addWidget(self.histogram)
        layout.addWidget(self.intensity_status)
        layout.addWidget(self.cursor_status)
        layout.addWidget(self.status)

    @staticmethod
    def _frame_limits(observed_range: tuple[int, int] | None) -> tuple[int, int] | None:
        if observed_range is None:
            return None
        low, high = observed_range
        if low == high:
            low, high = (low, low + 1) if low < 65535 else (65534, 65535)
        return low, high

    def _apply_limits(self, limits: tuple[int, int] | None, *, update_preview: bool = True) -> None:
        if update_preview:
            self.preview.set_display_limits(limits)
        self.histogram.set_limits(limits)
        if not self.histogram.pixel_count:
            self.intensity_status.setText("16-bit histogram unavailable for this frame")
            return
        if limits is None:
            display = "full range 0–65535"
        else:
            display = f"adjusted {limits[0]}–{limits[1]} (orange/teal lines)"
        saturated = self.histogram.saturated_count
        total = self.histogram.pixel_count
        observed_low, observed_high = self.histogram.observed_range
        self.intensity_status.setText(
            f"16-bit display: {display} · frame values: {observed_low}–{observed_high}"
            f" · pixels at 65535: {saturated}/{total}"
        )

    def adjust_intensity(self) -> None:
        limits = self._frame_limits(self.histogram.observed_range)
        if limits is not None:
            self._apply_limits(limits)

    def _autoscale_changed(self, checked: bool) -> None:
        if checked:
            self.adjust_intensity()

    def full_range(self) -> None:
        self.autoscale_checkbox.setChecked(False)
        self._apply_limits(None)

    def _show_pixel(self, pixel: object) -> None:
        self.cursor_status.setText(
            "Cursor (frame x, y, value): —" if pixel is None
            else f"Cursor (frame x, y, value): {pixel[0]}, {pixel[1]}, {pixel[2]}"
        )

    def show_frame(self, frame: object, status: str) -> None:
        self.histogram.set_frame(frame)
        frame_limits = self._frame_limits(self.histogram.observed_range)
        limits = frame_limits if self.autoscale_checkbox.isChecked() else self.preview.display_limits
        if frame_limits is None:
            limits = None
        self.preview.set_frame(frame, limits)
        self.adjust_intensity_button.setEnabled(frame_limits is not None)
        self._apply_limits(limits, update_preview=False)
        self.status.setText(status)
        if not self.isVisible():
            self.show()
