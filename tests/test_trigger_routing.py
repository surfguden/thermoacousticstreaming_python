from __future__ import annotations

from thermo_acoustic.application.commands import (
    Ad2ConfigureDigitalOutputArgs,
    Ad2ConfigureWaveformArgs,
    Ad2TriggerSettingsArgs,
    Ad2TriggerSource,
    CameraConfigureSequenceArgs,
    CameraMasterPulseMode,
    CameraMasterPulseSource,
    CameraSequenceTriggerArgs,
    CameraTriggerActive,
    CameraTriggerPolarity,
    CameraTriggerSource,
)
from thermo_acoustic.hal.ad2 import AD2Worker
from thermo_acoustic.hal.camera import CameraWorker
from thermo_acoustic.drivers.ad2.configuration import coerce_wfg_config


def test_ad2_hal_forwards_waveform_and_digital_trigger_settings() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeAd2:
        def initialize(self) -> None:
            pass

        def wfg_configure(self, settings: dict[str, object]) -> None:
            calls.append(("wave", settings))

        def wfg_readback(self):
            return coerce_wfg_config(calls[-1][1])

        def do_configure(self, settings: dict[str, object]) -> None:
            calls.append(("digital", settings))

    worker = AD2Worker(FakeAd2)
    worker.connect_device()
    trigger = Ad2TriggerSettingsArgs(
        source=Ad2TriggerSource.DIGITAL_IN,
        wait_s=0.2,
        run_s=0.4,
        repeat_count=5,
        repeat_trigger=True,
    )
    worker.configure_waveform(Ad2ConfigureWaveformArgs(trigger=trigger))
    worker.configure_digital_output(Ad2ConfigureDigitalOutputArgs(trigger=trigger))

    expected = {
        "source": Ad2TriggerSource.DIGITAL_IN.value,
        "sec_wait": 0.2,
        "sec_run": 0.4,
        "repeat_count": 5,
        "repeat_trigger": True,
    }
    assert calls[0][1]["channels"][0]["trigger"] == expected
    assert calls[1][1]["trigger"] == expected


def test_camera_hal_forwards_sequence_trigger_and_global_exposure() -> None:
    calls: list[tuple[str, object]] = []

    class FakeCamera:
        def open_camera(self) -> None:
            pass

        def configure_trigger_global_exposure(self, enabled: bool) -> None:
            calls.append(("global_exposure", enabled))

        def configure_sequence(self, settings: dict[str, object]) -> None:
            calls.append(("sequence", settings))

    worker = CameraWorker(FakeCamera)
    worker.connect_device()
    trigger = CameraSequenceTriggerArgs(
        source=CameraTriggerSource.EXTERNAL,
        polarity=CameraTriggerPolarity.NEGATIVE,
        active=CameraTriggerActive.LEVEL,
        trigger_times=7,
        delay_s=0.15,
        masterpulse_mode=CameraMasterPulseMode.BURST,
        masterpulse_source=CameraMasterPulseSource.EXTERNAL,
        masterpulse_interval_s=0.025,
        masterpulse_burst_times=9,
        global_exposure=True,
    )
    worker.configure_sequence(CameraConfigureSequenceArgs(12, trigger=trigger))

    assert calls[0] == ("global_exposure", True)
    settings = calls[1][1]
    assert settings == {
        "frames": 12,
        "trigger_source": "external",
        "trigger_polarity": "negative",
        "trigger_active": "level",
        "trigger_mode": "normal",
        "trigger_times": 7,
        "trigger_delay_s": 0.15,
        "masterpulse_mode": "burst",
        "masterpulse_source": "external",
        "masterpulse_interval_s": 0.025,
        "masterpulse_burst_times": 9,
    }
