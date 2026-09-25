"""Small dependency-free rolling temperature graph."""

from __future__ import annotations

from collections import deque
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class TemperaturePlot(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(210)
        self._samples = deque(maxlen=600)

    def add_sample(self, sample: dict) -> None:
        self._samples.append(sample)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#171d24"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = self.rect().adjusted(52, 20, -18, -30)
        painter.setPen(QPen(QColor("#71808e"), 1))
        painter.drawRect(plot)
        painter.drawText(8, 18, "Temperature °C · last 10 min")
        painter.setPen(QColor("#40b7f4"))
        painter.drawText(plot.left(), self.height() - 8, "CH1")
        painter.setPen(QColor("#efad55"))
        painter.drawText(plot.left() + 52, self.height() - 8, "CH2")
        rows = list(self._samples)
        if not rows:
            painter.setPen(QColor("#a3adb7"))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Waiting for TEC readings")
            return
        values = [row.get(key) for row in rows for key in ("channel_1_c", "channel_2_c")]
        values = [float(value) for value in values if value is not None]
        if not values:
            return
        low, high = min(values), max(values)
        padding = max(0.5, (high - low) * 0.1)
        low -= padding
        high += padding
        now = rows[-1]["monotonic_s"]
        start = max(rows[0]["monotonic_s"], now - 600)
        span = max(1.0, now - start)
        painter.setPen(QColor("#b8c4ce"))
        painter.drawText(3, plot.top() + 5, f"{high:.1f}")
        painter.drawText(3, plot.bottom(), f"{low:.1f}")
        for key, color in (("channel_1_c", "#40b7f4"), ("channel_2_c", "#efad55")):
            painter.setPen(QPen(QColor(color), 2))
            previous = None
            for row in rows:
                value = row.get(key)
                if value is None or row["monotonic_s"] < start:
                    previous = None
                    continue
                point = QPointF(plot.left() + (row["monotonic_s"] - start) / span * plot.width(),
                                plot.bottom() - (float(value) - low) / (high - low) * plot.height())
                if previous is not None:
                    painter.drawLine(previous, point)
                previous = point
