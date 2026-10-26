"""Driver behaviour against fake vendor SDK objects (no SDK, no hardware)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from thermo_acoustic.drivers.camera.hamamatsu import HamamatsuDcamDriver, HamamatsuDcamError


def _enum(*names: str) -> SimpleNamespace:
    return SimpleNamespace(**{name: f"{name}" for name in names})


class FakeDcam:
    """Records every property write; `fail_on` names a property whose write is refused."""

    def __init__(self, device_index: int = 0, fail_on: str | None = None) -> None:
        self.opened = False
        self.writes: list[tuple[str, object]] = []
        self.fail_on = fail_on

    def is_opened(self) -> bool:
        return self.opened

    def dev_open(self):
        self.opened = True
        return True

    def lasterr(self):
        return "fake error"

    def prop_setvalue(self, prop, value):
        self.writes.append((prop, value))
        return False if prop == self.fail_on else True

    def prop_setgetvalue(self, prop, value):
        self.writes.append((prop, value))
        return False if prop == self.fail_on else value


def make_driver(fail_on: str | None = None) -> tuple[HamamatsuDcamDriver, FakeDcam]:
    module = SimpleNamespace(
        DCAM_IDPROP=_enum("EXPOSURETIME", "TRIGGERSOURCE", "TRIGGERPOLARITY", "TRIGGERACTIVE",
                          "TRIGGER_MODE", "TRIGGERTIMES", "TRIGGERDELAY", "MASTERPULSE_MODE",
                          "MASTERPULSE_TRIGGERSOURCE", "MASTERPULSE_INTERVAL", "MASTERPULSE_BURSTTIMES",
                          "TRIGGER_GLOBALEXPOSURE"),
        DCAMPROP=SimpleNamespace(
            TRIGGERSOURCE=_enum("INTERNAL", "EXTERNAL", "SOFTWARE", "MASTERPULSE"),
            TRIGGERPOLARITY=_enum("NEGATIVE", "POSITIVE"),
            TRIGGERACTIVE=_enum("EDGE", "LEVEL"),
            TRIGGER_MODE=_enum("NORMAL"),
            MASTERPULSE_MODE=_enum("CONTINUOUS", "START", "BURST"),
            MASTERPULSE_TRIGGERSOURCE=_enum("EXTERNAL", "SOFTWARE"),
        ),
    )
    dcam = FakeDcam(fail_on=fail_on)
    api = SimpleNamespace(init=lambda: True, uninit=lambda: True)
    driver = HamamatsuDcamDriver(dcam_module=module, dcamapi=api, dcam=dcam)
    return driver, dcam


def trigger_source_writes(dcam: FakeDcam) -> list[object]:
    return [value for prop, value in dcam.writes if prop == "TRIGGERSOURCE"]


EXTERNAL_SERIES = {
    "frames": 2, "exposure_ms": 1.0, "trigger_source": "external", "trigger_polarity": "positive",
    "trigger_active": "edge", "trigger_times": 1,
}


def test_snapshot_mode_returns_the_camera_to_internal_trigger_after_an_external_series():
    driver, dcam = make_driver()
    driver.configure_sequence(EXTERNAL_SERIES)
    assert trigger_source_writes(dcam) == ["EXTERNAL"]
    series_writes = len(dcam.writes)
    driver.configure_snapshot({"exposure_ms": 5.0})
    assert trigger_source_writes(dcam) == ["EXTERNAL", "INTERNAL"]
    # Only the trigger source and exposure are written: no blanket reset of other properties.
    assert [prop for prop, _ in dcam.writes[series_writes:]] == ["EXPOSURETIME", "TRIGGERSOURCE"]
    assert driver.sequence_settings is None


def test_next_series_still_writes_its_own_external_trigger_after_a_preview():
    driver, dcam = make_driver()
    driver.configure_sequence(EXTERNAL_SERIES)
    driver.configure_snapshot({"exposure_ms": 5.0})
    driver.configure_sequence(EXTERNAL_SERIES)
    assert trigger_source_writes(dcam) == ["EXTERNAL", "INTERNAL", "EXTERNAL"]
    assert driver.sequence_settings == EXTERNAL_SERIES


def test_failed_internal_trigger_write_is_reported_and_leaves_the_sequence_state():
    driver, dcam = make_driver()
    driver.configure_sequence(EXTERNAL_SERIES)
    dcam.fail_on = "TRIGGERSOURCE"
    with pytest.raises(HamamatsuDcamError, match="TRIGGERSOURCE"):
        driver.configure_snapshot({"exposure_ms": 5.0})
    assert driver.sequence_settings == EXTERNAL_SERIES
