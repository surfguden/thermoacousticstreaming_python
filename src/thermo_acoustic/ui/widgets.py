from __future__ import annotations

import math

import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget


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

    def __init__(self, parent=None) -> None:
        super().__init__("No image")
        self._image: QImage | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(260, 180)
        self.setFrameShape(QLabel.Shape.Box)

    @property
    def has_image(self) -> bool:
        return self._image is not None

    def set_frame(self, frame: object) -> None:
        try:
            image = self._to_qimage(frame)
        except (TypeError, ValueError) as exc:
            self._image = None
            self.setPixmap(QPixmap())
            self.setText(f"Frame metadata: {frame!r}\n({exc})")
            return
        self._image = image.copy()
        self.setText("")
        self._refresh_pixmap()

    def _refresh_pixmap(self) -> None:
        if self._image is None:
            return
        self.setPixmap(
            QPixmap.fromImage(self._image).scaled(
                self.size(),
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


class CameraImageWindow(QDialog):
    """Reusable non-modal camera viewer for every acquisition mode."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Camera acquisition")
        self.resize(900, 700)
        layout = QVBoxLayout(self)
        self.preview = CameraPreview()
        self.preview.setMinimumSize(640, 480)
        self.status = QLabel("No acquisition")
        self.status.setWordWrap(True)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.status)

    def show_frame(self, frame: object, status: str) -> None:
        was_visible = self.isVisible()
        self.preview.set_frame(frame)
        self.status.setText(status)
        self.show()
        if not was_visible:
            self.raise_()
