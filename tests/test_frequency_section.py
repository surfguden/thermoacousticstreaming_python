"""Frequency and sweep area of the experiment form.

Two independent choices - the centre frequency (fixed / scanned across experiments) and a sweep inside each
experiment (off / on, its width fixed / scanned) - are views on the existing Start / Stop / Steps parameters.
These tests check that the views add no state of their own: the compiled definitions, stored values, precision
and profile round trip are the ones the parameters give.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application.plan_facts import plan_facts
from thermo_acoustic.application.experiments import validate_definition
from thermo_acoustic.application.simple_series import (
    NumericRange, compile_simple_series, simple_series_settings_from_profile, simple_series_settings_to_profile,
)
from thermo_acoustic.domain.models import OperatingMode
from thermo_acoustic.application.controller import ApplicationController
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.frequency_section import FrequencySpinBox
from thermo_acoustic.ui.simple_series_panel import SimpleSeriesPanel
from thermo_acoustic.ui.status_text import describe_condition, sweep_summary


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-frequency-section"])


@pytest.fixture
def panel(qt_app):
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
    panel = SimpleSeriesPanel(controller)
    panel.pump_unit.addItem("Pump unit 1", 0)  # a flush unit so the form compiles; nothing is connected or sent
    panel.pump_unit.setCurrentIndex(0)
    panel.description.setText("frequency section")
    panel.show()
    yield panel
    panel.close()


def _set(controls, values):
    for widget, value in zip(controls, values):
        widget.setValue(value)


def test_mode_is_the_steps_value_and_switching_loses_nothing(panel):
    editor = panel._editors["Frequency"]
    start, stop, steps = panel.frequency
    _set(panel.frequency, (1_000_000, 1_400_000, 3))
    assert editor.scan_button.isChecked() and not editor.stop.isHidden()
    editor.fixed_button.click()
    assert steps.value() == 1 and editor.fixed_button.isChecked() and editor.stop.isHidden()
    assert stop.value() == 1_400_000  # the hidden Stop keeps its value
    assert "Stop (1.4 MHz) is kept but not used with 1 point" in editor.info.text()
    editor.scan_button.click()
    assert steps.value() == 3 and (start.value(), stop.value()) == (1_000_000, 1_400_000)  # restored, not reset
    steps.setValue(1)  # typing Points = 1 is the same as choosing Fixed
    assert editor.fixed_button.isChecked()


@pytest.mark.parametrize("center_scan,sweep,width_scan", list(itertools.product((False, True), repeat=3)))
def test_every_combination_compiles_to_the_same_definition_the_parameters_give(panel, center_scan, sweep, width_scan):
    _set(panel.frequency, (1_000_000, 1_400_000, 3 if center_scan else 1))
    panel.sweep_enabled.setChecked(sweep)
    _set(panel.sweep_width, (100_000, 200_000, 2 if width_scan else 1))
    panel.sweep_period.setValue(5)
    expected_settings = panel._settings()
    assert expected_settings.frequency_hz == NumericRange(1_000_000, 1_400_000, 3 if center_scan else 1)
    definition = panel._definition()
    assert definition == compile_simple_series(replace(
        expected_settings, frequency_hz=NumericRange(1_000_000, 1_400_000, 3 if center_scan else 1)))
    centers, widths = (3 if center_scan else 1), ((2 if width_scan else 1) if sweep else 1)
    assert len(validate_definition(definition).experiments) == centers * widths  # one repeat, one value elsewhere
    plan = panel.frequency_plan.text()
    assert f"= {centers * widths} frequency combination" in plan
    assert f"Total experiments: {centers * widths}" in plan  # from the compiled plan
    facts = plan_facts(validate_definition(definition).steps)
    assert facts.sweep_enabled is sweep and facts.sweep_period_ms == (5 if sweep else None)
    assert panel.sweep_detail.isHidden() is (not sweep)  # hidden, not cleared
    assert panel.sweep_width[0].value() == 100_000


def test_total_comes_from_the_compiled_plan_and_not_the_frequency_product(panel):
    _set(panel.frequency, (1_000_000, 1_400_000, 3))
    panel.sweep_enabled.setChecked(True)
    _set(panel.sweep_width, (100_000, 200_000, 2))
    panel.repeats.setValue(2)
    _set(panel.amplitude, (1, 2, 2))
    text = panel.frequency_plan.text()
    assert "3 center frequencies × 2 sweep widths = 6 frequency combinations" in text
    assert "Total experiments: 24" in text  # 6 combinations x 2 amplitudes x 2 repeats


def test_a_form_that_does_not_compile_states_the_combinations_and_no_total_and_locates_the_error(panel):
    _set(panel.frequency, (1_000_000, 1_400_000, 3))
    panel.sweep_enabled.setChecked(True)
    _set(panel.sweep_width, (3_000_000, 3_000_000, 1))  # center - width/2 is negative
    text = panel.frequency_plan.text()
    assert "3 center frequencies × 1 sweep width = 3 frequency combinations" in text
    assert "Total experiments: not available — Sweep start frequency must be positive" in text
    assert not panel._editors["Sweep width"].error.isHidden() and not panel._editors["Frequency"].error.isHidden()
    panel.sweep_width[0].setValue(100_000)
    assert panel._editors["Sweep width"].error.isHidden() and "Total experiments: 3" in panel.frequency_plan.text()


def test_unit_choice_changes_text_only_and_typed_values_are_exact(panel):
    editor = panel._editors["Frequency"]
    start = panel.frequency[0]
    changes = []
    start.valueChanged.connect(changes.append)
    start.setValue(1_234_567.891)
    for unit, shown in (("MHz", "1.234567891"), ("kHz", "1234.567891"), ("Hz", "1234567.891")):
        editor.unit.setCurrentText(unit)
        assert start.text() == shown
        assert start.value() == 1_234_567.891
    assert changes == [1_234_567.891]  # switching units never changed the value
    for unit, typed, hz in (("MHz", "1.2", 1_200_000), ("kHz", "1200", 1_200_000), ("Hz", "1200000", 1_200_000),
                            ("MHz", "1.1", 1_100_000), ("MHz", "0.333333", 333_333)):
        editor.unit.setCurrentText(unit)
        start.lineEdit().setText(typed)
        start.interpretText()
        assert start.value() == hz, (unit, typed, start.value())
    assert isinstance(start, FrequencySpinBox) and start.minimum() == 0 and start.maximum() == 100_000_000
    assert start.decimals() == 6  # same precision as before


def test_profile_round_trip_keeps_mode_values_and_the_hidden_stop(panel):
    _set(panel.frequency, (1_234_567.891, 2_000_000, 1))  # fixed, with a stop that is kept but unused
    panel.sweep_enabled.setChecked(False)
    _set(panel.sweep_width, (123_456.789, 200_000, 1))
    panel.sweep_period.setValue(2.5)
    profile = simple_series_settings_to_profile(panel._settings())
    restored = simple_series_settings_from_profile(profile)
    _set(panel.frequency, (5_000_000, 6_000_000, 4))
    _set(panel.sweep_width, (50_000, 60_000, 3))
    panel.sweep_enabled.setChecked(True)
    panel._apply_settings(restored)
    assert panel._settings() == restored
    assert panel.frequency[1].value() == 2_000_000 and panel._editors["Frequency"].fixed_button.isChecked()
    assert panel.sweep_detail.isHidden() and panel._editors["Sweep width"].unit.currentText() == "kHz"
    assert panel._editors["Frequency"].unit.currentText() == "MHz"  # chosen to read well; values are unchanged


def test_schematic_is_per_combination_and_labelled_requested(panel):
    assert panel.schematic_picker.isHidden()  # one combination: nothing to choose
    _set(panel.frequency, (1_000_000, 1_400_000, 3))
    panel.sweep_enabled.setChecked(True)
    _set(panel.sweep_width, (100_000, 200_000, 2))
    panel.sweep_period.setValue(5)
    assert not panel.schematic_picker.isHidden() and panel.combination.maximum() == 6
    assert "of 6: center 1 MHz · full width 100 kHz" in panel.combination_label.text()
    assert "not a measured waveform" in panel.schematic_note.text()
    panel.combination.setValue(6)
    assert "center 1.4 MHz · full width 200 kHz" in panel.combination_label.text()
    assert panel.schematic._sweep and panel.schematic._width == 200_000 and panel.schematic._center == 1_400_000
    panel.sweep_enabled.setChecked(False)
    assert not panel.schematic._sweep  # a fixed frequency is a horizontal line


def test_stored_conditions_say_unknown_instead_of_borrowing_the_current_form():
    running = {"sweep_enabled": True, "sweep_period_ms": 5.0}
    parameters = {"frequency_hz": 1_200_000.0, "sweep_width_hz": 100_000.0}
    assert sweep_summary(parameters, running) == "sweep full width 100 kHz (1.15 MHz … 1.25 MHz), 5 ms triangle (requested)"
    assert sweep_summary({"frequency_hz": 1e6, "sweep_width_hz": "NaN"}, {"sweep_enabled": False}) == "sweep off"
    assert sweep_summary(parameters, {"sweep_enabled": True}) .endswith("period not stated")
    # a saved acquisition has only its own parameters: the period is not recorded there
    assert describe_condition(parameters).endswith("period not recorded")
    assert sweep_summary({"frequency_hz": 1e6}) is None  # nothing about a sweep: nothing invented


def test_scanned_series_still_summarise_timing_and_sweep_from_the_definition(panel):
    """A scan makes one acquisition block per experiment; blocks that state the same facts are one summary."""
    _set(panel.frequency, (1_000_000, 1_400_000, 3))
    panel.sweep_enabled.setChecked(True)
    _set(panel.sweep_width, (100_000, 200_000, 2))
    panel.sweep_period.setValue(5)
    facts = plan_facts(validate_definition(panel._definition()).steps)
    assert facts.uniform and facts.sweep_enabled is True and facts.sweep_period_ms == 5
    assert facts.sound_enabled is True and facts.frames == panel.frames.value()
    assert "Frequency sweep inside each experiment: ON · triangle · 5 ms (requested)" in panel.summary.text()
    assert "Center frequency: 1 MHz .. 1.4 MHz (3 values)" in panel.summary.text()
    assert "Sweep full width: 100 kHz .. 200 kHz (2 values)" in panel.summary.text()
