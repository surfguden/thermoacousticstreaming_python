"""Controls for the experiment form's scanned values, and the requested-frequency schematic.

`RangeEditor` is a view on the existing Start / Stop / Steps parameters of a `NumericRange`; it adds no
state of its own. "Fixed" simply means Steps = 1 (only Start is used) and "Scan across experiments" means
Steps > 1. Switching modes only changes Steps: Start and Stop keep their values, so going back restores
what was entered. For frequencies the spin boxes show Hz, kHz or MHz; the value they hold, their range and
their 6-decimal precision are the same as before (Hz), the unit only changes how the text is shown/typed.

`SweepSchematic` draws the *requested* centre / band / period of one combination. It is an illustration
of the form values, not a measurement and not a signal generator.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QValidator
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

from ..application.simple_series import NumericRange
from .status_text import format_frequency

UNITS = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6}
_NUMBER = re.compile(r"\d+(\.\d*)?|\.\d+")
STEPS_TIP = ("Points is the number of evenly spaced values. With 1 point, only Start is used "
             "and Stop is ignored. With 2 or more points, both endpoints are included.")


class FrequencySpinBox(QDoubleSpinBox):
    """A spin box whose value is always in Hz; only the text is in the chosen unit."""

    def __init__(self, scale: float = 1e6) -> None:
        super().__init__()
        self._scale = scale
        self.setKeyboardTracking(False)
        self.set_scale(scale)

    def scale(self) -> float:
        return self._scale

    def set_scale(self, scale: float) -> None:
        self._scale = scale
        self.setSingleStep(1.0 if scale == 1.0 else scale / 100)
        self.lineEdit().setText(self.textFromValue(self.value()))  # text only; the value is untouched

    def textFromValue(self, value: float) -> str:
        """The stored Hz value in the chosen unit, from its shortest exact decimal (no float noise)."""
        shown = Decimal(repr(float(value))) / Decimal(int(self._scale))
        text = format(shown, "f")
        if "." in text:
            text = text.rstrip("0")
        whole, _, fraction = text.partition(".")
        minimum = 0 if self._scale == 1.0 else 3
        return whole + ("." + fraction.ljust(minimum, "0") if fraction or minimum else "")

    def valueFromText(self, text: str) -> float:
        try:
            return float(Decimal(text.strip()) * Decimal(int(self._scale)))
        except (InvalidOperation, ValueError):
            return self.value()

    def validate(self, text: str, pos: int):
        stripped = text.strip()
        if not stripped:
            return QValidator.State.Intermediate, text, pos
        if _NUMBER.fullmatch(stripped):
            return QValidator.State.Acceptable, text, pos
        return QValidator.State.Invalid, text, pos


def wrapped_label(text: str = "", lines: int = 2) -> QLabel:
    """A word-wrapped label that keeps room for `lines` lines. Grid and form layouts size by minimum height and
    ignore the extra lines a wrapped label needs, which squeezes the controls next to it."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setMinimumHeight(label.fontMetrics().lineSpacing() * lines + 2)
    label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    return label


def plain_spin(value: float, minimum: float, maximum: float) -> QDoubleSpinBox:
    control = QDoubleSpinBox()
    control.setRange(minimum, maximum)
    control.setDecimals(6)
    control.setValue(value)
    control.setKeyboardTracking(False)
    return control


def _fmt(value: float, frequency: bool) -> str:
    return format_frequency(value) if frequency else f"{value:g}"


def bounded_values(values: list[float], frequency: bool, limit: int = 6) -> str:
    """The actual points, never more than `limit` entries: first three and last two when there are many."""
    shown = [_fmt(v, frequency) for v in values]
    if len(shown) > limit:
        shown = [*shown[:3], "…", *shown[-2:]]
    return " · ".join(shown)


class RangeEditor(QWidget):
    """Fixed value or scan across experiments, over the same start / stop / steps spin boxes."""

    def __init__(self, name: str, start: float, stop: float, *, minimum: float = 0, maximum: float = 100_000_000,
                 frequency: bool = False, unit: str = "MHz") -> None:
        super().__init__()
        # `name` is the word the compile step uses in its messages (e.g. "Frequency", "Sweep width"), so an error
        # from the existing validation can be matched to this input.
        self.name, self.frequency = name, frequency
        self._scan_steps = 2  # what "Scan" restores when Steps is 1; updated whenever Steps is above 1
        if frequency:
            self.start, self.stop = FrequencySpinBox(), FrequencySpinBox()
            for control in (self.start, self.stop):
                control.setRange(minimum, maximum)
                control.setDecimals(6)
            self.start.setValue(start)
            self.stop.setValue(stop)
        else:
            self.start, self.stop = plain_spin(start, minimum, maximum), plain_spin(stop, minimum, maximum)
        self.steps = QSpinBox()
        self.steps.setRange(1, 100_000)
        self.steps.setValue(1)
        self.steps.setKeyboardTracking(False)
        self.controls = (self.start, self.stop, self.steps)
        for control in (self.steps, self.stop):
            control.setToolTip(STEPS_TIP)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        top = QHBoxLayout()
        self.fixed_button = QPushButton("Fixed")
        self.scan_button = QPushButton("Scan across experiments")
        top.setSpacing(0)
        group = QButtonGroup(self)
        for button, tip in ((self.fixed_button, "One value, the same in every experiment (Points = 1)."),
                            (self.scan_button, "Several values, one per experiment (Points of 2 or more).")):
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setStyleSheet("QPushButton:checked { background: #1f4e8c; color: white; font-weight: 600 }")
            group.addButton(button)
            top.addWidget(button)
        top.addStretch(1)
        self.unit = QComboBox()
        if frequency:
            self.unit.addItems(list(UNITS))
            self.unit.setCurrentText(unit)
            self.unit.setToolTip("Unit for entering and showing these frequencies. The stored value is in Hz and "
                                 "does not change when the unit does.")
            top.addWidget(self.unit)
        layout.addLayout(top)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        self.start_caption, self.stop_caption, self.steps_caption = QLabel("Value"), QLabel("To"), QLabel("Points")
        for column, (caption, control) in enumerate(((self.start_caption, self.start), (self.stop_caption, self.stop),
                                                     (self.steps_caption, self.steps))):
            grid.addWidget(caption, 0, column)
            grid.addWidget(control, 1, column)
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        self.info = QLabel()  # one line; the bounded point list never needs wrapping
        self.info.setStyleSheet("color: #444")
        layout.addWidget(self.info)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b71c1c; font-weight: 600")
        self.error.setVisible(False)
        layout.addWidget(self.error)

        self.fixed_button.clicked.connect(self._choose_fixed)
        self.scan_button.clicked.connect(self._choose_scan)
        self.steps.valueChanged.connect(self.refresh)
        self.start.valueChanged.connect(self.refresh)
        self.stop.valueChanged.connect(self.refresh)
        if frequency:
            self.unit.currentTextChanged.connect(self._unit_changed)
            self._unit_changed(unit)
        self.refresh()

    # -- the mode is the Steps value; these only write Steps
    def _choose_fixed(self) -> None:
        if self.steps.value() > 1:
            self._scan_steps = self.steps.value()
            self.steps.setValue(1)
        self.refresh()

    def _choose_scan(self) -> None:
        if self.steps.value() == 1:
            self.steps.setValue(self._scan_steps)
        self.refresh()

    def is_scan(self) -> bool:
        return self.steps.value() > 1

    def range(self) -> NumericRange:
        return NumericRange(self.start.value(), self.stop.value(), self.steps.value())

    def points(self) -> list[float]:
        """The values the experiments will use, from the same NumericRange the compile uses."""
        return self.range().values(self.name)

    # -- units (frequency only; display only)
    def _unit_changed(self, name: str) -> None:
        if self.frequency and name in UNITS:
            for control in (self.start, self.stop):
                control.set_scale(UNITS[name])
            self.refresh()

    def fit_unit(self) -> None:
        """Choose the unit that reads best for the current values (after a load). Display only."""
        if not self.frequency:
            return
        biggest = max(abs(self.start.value()), abs(self.stop.value()) if self.is_scan() else 0)
        self.unit.setCurrentText("MHz" if biggest >= 1e6 else "kHz" if biggest >= 1e3 else "Hz")

    def refresh(self, *_args) -> None:
        scan = self.is_scan()
        if scan:
            self._scan_steps = self.steps.value()
        for button, checked in ((self.fixed_button, not scan), (self.scan_button, scan)):
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)
        self.start_caption.setText("From" if scan else "Value")
        for widget in (self.stop, self.stop_caption, self.steps, self.steps_caption):
            widget.setVisible(scan)
        self.start_caption.setVisible(scan)  # a single field needs no "Value" caption; the mode button says it
        self.info.setVisible(True)
        if scan:
            try:
                self.info.setText(f"{self.steps.value()} points: " + bounded_values(self.points(), self.frequency))
            except ValueError as exc:
                self.info.setText(str(exc))
        else:
            kept = ""
            if self.stop.value() != self.start.value():
                kept = f" Stop ({_fmt(self.stop.value(), self.frequency)}) is kept but not used with 1 point."
            self.info.setText(kept.strip())
            self.info.setVisible(bool(kept))  # "same value in every experiment" is the Fixed button's tooltip

    def set_error(self, text: str | None) -> None:
        """Show an error of the existing validation under the input it is about. Text and a warning sign carry
        it; the spin boxes are left alone (a stylesheet on them changes their size)."""
        self.error.setText(f"⚠ {text}" if text else "")
        self.error.setVisible(bool(text))


class SweepSchematic(QWidget):
    """Requested frequency against time inside one experiment, for one combination (illustration only)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(96)
        self.setMaximumHeight(120)
        self._center = self._width = self._period = None
        self._sweep = False

    def show_combination(self, center: float | None, width: float | None, period_ms: float | None, sweep: bool) -> None:
        self._center, self._width, self._period, self._sweep = center, width, period_ms, sweep
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        if self._center is None:
            return
        text, line = palette.text().color(), QColor("#1f4e8c")
        box = QRectF(78, 8, max(40, self.width() - 92), self.height() - 28)
        painter.setPen(QPen(QColor("#999"), 1))
        painter.drawRect(box)
        center = self._center
        if self._sweep and self._width:
            low, high = center - self._width / 2, center + self._width / 2
            span = high - low
            top, bottom = high + span * 0.3, low - span * 0.3
        else:
            low = high = center
            top, bottom = center * 1.002, center * 0.998

        def y(value: float) -> float:
            return box.top() + (top - value) / (top - bottom) * box.height()
        painter.setPen(QPen(line, 2))
        if self._sweep and self._width:
            points = [QPointF(box.left() + box.width() * i / 4, y(low if i % 2 == 0 else high)) for i in range(5)]
            painter.drawPolyline(QPolygonF(points))
            painter.setPen(QPen(QColor("#888"), 1, Qt.PenStyle.DashLine))
            for value in (low, high):
                painter.drawLine(QPointF(box.left(), y(value)), QPointF(box.right(), y(value)))
            painter.setPen(text)
            for value in (high, low):
                painter.drawText(QRectF(2, y(value) - 8, 74, 16), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                                 format_frequency(value))
            if self._period:
                painter.drawText(QRectF(box.left() + 4, box.bottom() + 2, box.width(), 16),
                                 int(Qt.AlignmentFlag.AlignLeft), f"2 of the periods shown · period {self._period:g} ms")
        else:
            painter.drawLine(QPointF(box.left(), y(center)), QPointF(box.right(), y(center)))
            painter.setPen(text)
            painter.drawText(QRectF(2, y(center) - 8, 74, 16), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                             format_frequency(center))
            painter.drawText(QRectF(box.left() + 4, box.bottom() + 2, box.width(), 16),
                             int(Qt.AlignmentFlag.AlignLeft), "fixed frequency during the experiment")
        painter.end()
