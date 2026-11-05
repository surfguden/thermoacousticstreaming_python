"""A few small icons, drawn here so they follow the palette and need no image files.

Two groups, kept apart on purpose:

* action icons (connect, disconnect, preview, capture, stop, folder, settings) go on buttons that
  already carry a text label; the icon never replaces the word;
* state marks (connected, not connected, busy, active, waiting, failed, stop) are shapes that go with
  a word and a colour, so a state is never carried by colour alone.

"Active" is only for what a device reports. A run stage that merely involves a device uses the
separate "involved" mark and wording.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QPushButton, QStyle

GREEN, RED, AMBER, BLUE, GREY = "#2e7d32", "#b71c1c", "#a65a00", "#1f4e8c", "#616161"
_SIZE = 16

# state -> (colour, word). The word is what carries the state when colour is not seen.
STATE_MARKS = {
    "connected": (GREEN, "connected"),
    "disconnected": (GREY, "not connected"),
    "busy": (BLUE, "busy"),
    "active": (GREEN, "active"),
    "waiting": (AMBER, "waiting"),
    "failed": (RED, "last operation failed"),
    "stop": (RED, "stopped"),
    "involved": (BLUE, "used in this stage"),
}


def _draw(kind: str, color: str, size: int = _SIZE) -> QPixmap:
    scale = 3
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale * size / 16, scale * size / 16)
    c = QColor(color)
    pen = QPen(c, 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    fill = Qt.BrushStyle.SolidPattern
    if kind == "connected":
        painter.setBrush(c)
        painter.drawEllipse(QRectF(3.5, 3.5, 9, 9))
    elif kind == "disconnected":
        painter.drawEllipse(QRectF(3.5, 3.5, 9, 9))
    elif kind == "busy":
        painter.drawArc(QRectF(2.5, 2.5, 11, 11), 30 * 16, 280 * 16)
    elif kind == "active":
        painter.setBrush(c)
        painter.drawPolygon(QPolygonF([QPointF(4.5, 2.5), QPointF(13, 8), QPointF(4.5, 13.5)]))
    elif kind == "waiting":
        painter.drawEllipse(QRectF(2.5, 2.5, 11, 11))
        painter.drawLine(QPointF(8, 8), QPointF(8, 4.5))
        painter.drawLine(QPointF(8, 8), QPointF(10.8, 8))
    elif kind == "failed":
        painter.drawPolygon(QPolygonF([QPointF(8, 2), QPointF(14.5, 13.5), QPointF(1.5, 13.5)]))
        painter.drawLine(QPointF(8, 6), QPointF(8, 9.5))
        painter.drawPoint(QPointF(8, 11.6))
    elif kind in {"stop"}:
        painter.setBrush(c)
        painter.drawRect(QRectF(3.5, 3.5, 9, 9))
    elif kind == "involved":  # an outlined bracket: "this stage works with it", not a device report
        painter.drawLine(QPointF(5, 3), QPointF(3, 3))
        painter.drawLine(QPointF(3, 3), QPointF(3, 13))
        painter.drawLine(QPointF(3, 13), QPointF(5, 13))
        painter.drawLine(QPointF(11, 3), QPointF(13, 3))
        painter.drawLine(QPointF(13, 3), QPointF(13, 13))
        painter.drawLine(QPointF(13, 13), QPointF(11, 13))
    elif kind == "connect":  # plug
        painter.drawLine(QPointF(6, 2.5), QPointF(6, 6))
        painter.drawLine(QPointF(10, 2.5), QPointF(10, 6))
        painter.drawRoundedRect(QRectF(4, 6, 8, 4), 1, 1)
        painter.drawLine(QPointF(8, 10), QPointF(8, 13.5))
    elif kind == "disconnect":
        painter.drawLine(QPointF(6, 2.5), QPointF(6, 6))
        painter.drawLine(QPointF(10, 2.5), QPointF(10, 6))
        painter.drawRoundedRect(QRectF(4, 6, 8, 4), 1, 1)
        painter.drawLine(QPointF(2.5, 13.5), QPointF(13.5, 2.5))
    elif kind == "capture":  # camera
        painter.drawRoundedRect(QRectF(1.8, 4.5, 12.4, 8.5), 1.5, 1.5)
        painter.drawEllipse(QRectF(5.3, 6.1, 5.4, 5.4))
    elif kind == "settings":  # sliders
        for y, x in ((4, 5.5), (8, 10.5), (12, 6.5)):
            painter.drawLine(QPointF(2.5, y), QPointF(13.5, y))
            painter.setBrush(c)
            painter.drawEllipse(QPointF(x, y), 1.6, 1.6)
            painter.setBrush(Qt.BrushStyle.NoBrush)
    del fill
    painter.end()
    pixmap.setDevicePixelRatio(scale)  # drawn at 3x, shown at `size`
    return pixmap


def state_pixmap(kind: str, size: int = _SIZE) -> QPixmap:
    """Shape for a state, in the colour that goes with it (see STATE_MARKS)."""
    color = STATE_MARKS.get(kind, (GREY, ""))[0]
    return _draw(kind, color, size)


# Plain stop: neutral square. Abort: amber. Panic: white on the red button. Hierarchy lives in the colour of the
# button as well as the label; no icon is the only carrier.
_ACTIONS = {"stop": ("stop", None), "abort": ("stop", AMBER), "panic": ("failed", "#ffffff")}


def action_icon(name: str) -> QIcon:
    """Icon for a button that also has a text label. Qt standard icons where one exists."""
    app = QApplication.instance()
    style = app.style() if app is not None else None
    standard = {"preview": QStyle.StandardPixmap.SP_MediaPlay, "folder": QStyle.StandardPixmap.SP_DirOpenIcon}
    if name in standard and style is not None:
        return style.standardIcon(standard[name])
    text = app.palette().windowText().color().name() if app is not None else "#222222"
    kind, color = _ACTIONS.get(name, (name, None))
    return QIcon(_draw(kind, color or text))


def set_action_icon(button: QPushButton, name: str) -> QPushButton:
    button.setIcon(action_icon(name))
    return button
