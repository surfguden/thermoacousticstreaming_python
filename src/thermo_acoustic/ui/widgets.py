from __future__ import annotations

import math

import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class ScopePlot(QWidget):
    """Small dependency-free plot for typed AD2 scope results."""

    _COLORS = (QColor("#4da3ff"), QColor("#ff8c42"), QColor("#5fd35f"), QColor("#d66cff"))

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.samples_by_channel: dict[int, list[float]] = {}
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_samples(self, samples_by_channel: dict[int, list[float]]) -> None:
        self.samples_by_channel = {
            int(channel): [float(value) for value in samples]
            for channel, samples in samples_by_channel.items()
        }
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        area = QRectF(42, 16, max(1, self.width() - 58), max(1, self.height() - 48))
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawRect(area)
        finite = [
            value
            for samples in self.samples_by_channel.values()
            for value in samples
            if math.isfinite(value)
        ]
        if not finite:
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "No scope data")
            return
        low, high = min(finite), max(finite)
        if math.isclose(low, high):
            low -= 0.5
            high += 0.5
        max_count = max((len(samples) for samples in self.samples_by_channel.values()), default=1)
        for color_index, (channel, samples) in enumerate(sorted(self.samples_by_channel.items())):
            points = []
            for index, value in enumerate(samples):
                if not math.isfinite(value):
                    continue
                x = area.left() + area.width() * index / max(max_count - 1, 1)
                y = area.bottom() - area.height() * (value - low) / (high - low)
                points.append(QPointF(x, y))
            painter.setPen(QPen(self._COLORS[color_index % len(self._COLORS)], 1.5))
            if len(points) == 1:
                painter.drawEllipse(points[0], 2, 2)
            elif points:
                painter.drawPolyline(points)
            painter.drawText(
                QPointF(area.left() + color_index * 72, self.height() - 10),
                f"Channel {channel}",
            )
        painter.setPen(self.palette().text().color())
        painter.drawText(2, 22, f"{high:.4g}")
        painter.drawText(2, int(area.bottom()), f"{low:.4g}")
        painter.drawText(area, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, "sample")


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
