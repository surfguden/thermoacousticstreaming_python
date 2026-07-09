from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.application import Application
from thermo_acoustic.ad2 import CarrierSettings, TriggerSettings, WaveformFunction, WfgChannelConfig, WfgConfig
from thermo_acoustic.experiment_presets import (
    LABVIEW_SCREENSHOT_PRESET_NAME,
    LabviewWorkingPreset,
    labview_screenshot_working_preset,
)
from thermo_acoustic.hardware_config import default_hardware_config
from thermo_acoustic.hardware_factory import HardwareRuntimeConfig, apply_hardware_bundle, build_hardware_bundle
from thermo_acoustic.waveforms import WaveFormsBackend
from thermo_acoustic.workflows import Experiment2, ExperimentSeries2, FlushSettings


CONFIRM_TEXT = "CONFIRM_REAL_HARDWARE"
TIMING_UNCERTAIN_ACK_FLAG = "--acknowledge-timing-uncertain"
PUMP_VALVE_REAL_ACK_FLAG = "--acknowledge-pump-valve-real"
TIMING_UNCERTAIN_REFUSAL = (
    f"This mode requires {TIMING_UNCERTAIN_ACK_FLAG} because AD2 WFG start timing vs pc_trigger is "
    "not yet fully confirmed. trigsrcNone may mean output starts at config_wfg rather than pc_trigger. "
    "CH2/index 1 purpose is unknown and remains disabled. This mode is AD2 CH0 only."
)
PUMP_VALVE_REAL_REFUSAL = (
    f"This mode requires {PUMP_VALVE_REAL_ACK_FLAG} because it opens the real one-pump Qmix backend "
    "and real valve serial backend. Pump flow and valve switching are only allowed when explicitly acknowledged."
)
AD2_LOW_RISK_CHANNEL = 0
AD2_LOW_RISK_FREQUENCY_HZ = 1000.0
AD2_LOW_RISK_AMPLITUDE_V = 0.1
AD2_LOW_RISK_OFFSET_V = 0.0
AD2_LOW_RISK_DURATION_S = 0.5
AD2_TIMING_DEFAULT_PRE_TRIGGER_WAIT_S = 2.0
AD2_LABVIEW_ACOUSTIC_CHANNEL = 0
AD2_LABVIEW_ACOUSTIC_FREQUENCY_HZ = 1.975e6
AD2_LABVIEW_ACOUSTIC_AMPLITUDE_V = 2.0
AD2_LABVIEW_ACOUSTIC_OFFSET_V = 0.0
AD2_LABVIEW_ACOUSTIC_SHORT_DURATION_S = 0.5
AD2_LABVIEW_ACOUSTIC_ORIGINAL_DURATION_S = 60.0


@dataclass(frozen=True, slots=True)
class SmokePlan:
    name: str
    config: HardwareRuntimeConfig
    flush_enabled: bool
    description: str
    requires_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class SmokeRunSettings:
    frames: int
    exposure_ms: float
    trigger_source: str
    roi: dict[str, int] | None = None
    apply_roi: bool = False
    preset: LabviewWorkingPreset | None = None


@dataclass(frozen=True, slots=True)
class Ad2OutputSmokeParameters:
    name: str
    channel: int
    frequency_hz: float
    amplitude_v: float
    offset_v: float
    duration_s: float
    repeat_count: int = 1
    waveform: WaveformFunction = WaveformFunction.SINE


def print_step(message: str) -> None:
    print(f"[real-workflow-smoke] {message}", flush=True)


def print_value(label: str, value: object) -> None:
    print(f"  {label}: {value}", flush=True)


def real_camera_only_plan() -> SmokePlan:
    defaults = default_hardware_config()
    return SmokePlan(
        name="real-camera-only",
        description=(
            "Real Hamamatsu camera acquisition with AD2 simulated, pump "
            "simulated/disabled, valve simulated/disabled, Z-stage disabled, "
            "and experiment flush disabled."
        ),
        config=HardwareRuntimeConfig(
            ad2_enabled=True,
            sim_ad2=True,
            camera_enabled=True,
            sim_camera=False,
            pump_enabled=False,
            sim_pump=True,
            valve_enabled=False,
            sim_valve=True,
            z_enabled=False,
            prior_resource=defaults.z_stage.prior_resource,
            valve_resource="COM6",
            cetoni_config_path=defaults.qmix.config_path,
        ),
        flush_enabled=False,
        requires_confirmation=False,
    )


def real_camera_real_ad2_low_risk_plan() -> SmokePlan:
    defaults = default_hardware_config()
    return SmokePlan(
        name="real-camera-real-ad2-low-risk",
        description=(
            "Combined smoke using real Hamamatsu camera and real AD2 low-risk "
            "output, with pump simulated/disabled, valve simulated/disabled, "
            "Z-stage disabled, Qmix untouched, and experiment flush disabled."
        ),
        config=HardwareRuntimeConfig(
            ad2_enabled=True,
            sim_ad2=False,
            camera_enabled=True,
            sim_camera=False,
            pump_enabled=False,
            sim_pump=True,
            valve_enabled=False,
            sim_valve=True,
            z_enabled=False,
            prior_resource=defaults.z_stage.prior_resource,
            valve_resource="COM6",
            cetoni_config_path=defaults.qmix.config_path,
        ),
        flush_enabled=False,
        requires_confirmation=True,
    )


def real_camera_real_ad2_acoustic_short_plan() -> SmokePlan:
    defaults = default_hardware_config()
    return SmokePlan(
        name="real-camera-real-ad2-acoustic-short",
        description=(
            "Combined smoke using real Hamamatsu camera and real AD2 "
            "LabVIEW acoustic candidate short-duration CH0 output, with pump "
            "simulated/disabled, valve simulated/disabled, Z-stage disabled, "
            "Qmix untouched, and experiment flush disabled."
        ),
        config=HardwareRuntimeConfig(
            ad2_enabled=True,
            sim_ad2=False,
            camera_enabled=True,
            sim_camera=False,
            pump_enabled=False,
            sim_pump=True,
            valve_enabled=False,
            sim_valve=True,
            z_enabled=False,
            prior_resource=defaults.z_stage.prior_resource,
            valve_resource="COM6",
            cetoni_config_path=defaults.qmix.config_path,
        ),
        flush_enabled=False,
        requires_confirmation=True,
    )


def real_full_workflow_short_plan(valve_port: str, *, flush_enabled: bool = False) -> SmokePlan:
    if valve_port not in {"COM5", "COM6"}:
        raise SystemExit("This mode requires explicit --valve-port COM5 or COM6")
    defaults = default_hardware_config()
    return SmokePlan(
        name="real-full-workflow-short",
        description=(
            "Short full workflow using real Hamamatsu camera, real AD2 "
            "LabVIEW acoustic candidate short-duration CH0 output, real "
            "one-pump Qmix backend, and real serial valve, with Z-stage disabled."
        ),
        config=HardwareRuntimeConfig(
            ad2_enabled=True,
            sim_ad2=False,
            camera_enabled=True,
            sim_camera=False,
            pump_enabled=True,
            sim_pump=False,
            valve_enabled=True,
            sim_valve=False,
            z_enabled=False,
            prior_resource=defaults.z_stage.prior_resource,
            valve_resource=valve_port,
            cetoni_config_path=defaults.qmix.config_path,
        ),
        flush_enabled=flush_enabled,
        requires_confirmation=True,
    )


def resolve_smoke_settings(
    preset_name: str | None,
    frames: int | None,
    exposure_ms: float | None,
    apply_roi: bool = False,
) -> SmokeRunSettings:
    if preset_name == LABVIEW_SCREENSHOT_PRESET_NAME:
        preset = labview_screenshot_working_preset()
        return SmokeRunSettings(
            frames=max(int(frames), 1) if frames is not None else 1,
            exposure_ms=float(exposure_ms) if exposure_ms is not None else preset.camera.exposure_ms,
            trigger_source=preset.camera.dcam_trigger_source_camera_only,
            roi=preset.camera.roi_dict(),
            apply_roi=apply_roi,
            preset=preset,
        )
    if preset_name:
        raise SystemExit(f"Unknown preset: {preset_name}")
    return SmokeRunSettings(
        frames=max(int(frames), 1) if frames is not None else 1,
        exposure_ms=float(exposure_ms) if exposure_ms is not None else 10.0,
        trigger_source="internal",
        apply_roi=apply_roi,
    )


def print_labview_preset_summary(preset: LabviewWorkingPreset) -> None:
    print_step("LabVIEW screenshot preset candidates")
    print_value("source", preset.source)
    print_value("camera ROI", preset.camera.roi_dict())
    print_value("camera exposure_ms", preset.camera.exposure_ms)
    print_value("camera FPS", preset.camera.camera_fps)
    print_value("LabVIEW experiment frames", preset.experiment.frames)
    print_value("capture mode", preset.camera.capture_mode)
    print_value("sequence mode/source", f"{preset.camera.sequence_mode} / {preset.camera.sequence_source}")
    print_value("sequence interval/burst", f"{preset.camera.interval_s} / {preset.camera.burst}")
    print_value("external polarity/delay", f"{preset.camera.external_polarity} / {preset.camera.external_delay_s}")
    print_value("experiment ch1 frequency/amplitude", f"{preset.experiment.ch1_frequency_hz} Hz / {preset.experiment.ch1_amplitude_v} V")
    print_value("experiment ch1/ch2 run_s", f"{preset.experiment.ch1_run_s} / {preset.experiment.ch2_run_s}")
    print_value("observed LabVIEW average FPS", preset.experiment.average_fps_observed)
    print_value("flush candidate", "not enabled in smoke path")
    print_value("flush flowrate/volume", f"{preset.flush.experiment_flush_flowrate_ul} uL / {preset.flush.experiment_flush_volume_ml} ml")
    print_value("flush WaitAfterFlush conflict", preset.flush.wait_after_flush_conflict_note)
    print_value("screenshot valve COM candidate", preset.initialization.valve_resource_candidate)
    print_value("screenshot Qmix path candidate", preset.initialization.qmix_config_path_candidate)
    print_value("candidate warning", preset.initialization.candidate_note)


def print_ad2_plan(settings: SmokeRunSettings) -> None:
    preset = settings.preset or labview_screenshot_working_preset()
    print_step("AD2 LabVIEW screenshot plan only")
    print_value("real AD2 initialized", False)
    print_value("real AD2 output", "disabled; no WaveForms device is opened")
    for label, channel in (("ch1", preset.ad2.ch1), ("ch2", preset.ad2.ch2)):
        print_value(
            label,
            (
                f"index={channel.index}, frequency={channel.frequency_hz} Hz, "
                f"amplitude={channel.amplitude_v} V, offset={channel.offset_v}, "
                f"symmetry={channel.symmetry_percent}, phase={channel.phase_deg}, "
                f"function={channel.function}"
            ),
        )
    print_value("WFG trigger source shown", preset.ad2.trigger_source)
    print_value("WFG secRun/secWait/cRepeat shown", f"{preset.ad2.wfg_sec_run_s}/{preset.ad2.wfg_sec_wait_s}/{preset.ad2.wfg_repeat_count}")
    print_value("experiment ch1/ch2 run_s", f"{preset.ad2.experiment_ch1_run_s}/{preset.ad2.experiment_ch2_run_s}")
    print_step("This mode is print-only and does not initialize hardware.")


def print_ad2_labview_candidate(settings: SmokeRunSettings) -> None:
    print_ad2_plan(settings)


def read_ad2_identity(backend: WaveFormsBackend, device_index: int) -> None:
    print_step(f"reading AD2 identity for device index {device_index}")
    try:
        device_count = backend.enum_devices()
    except Exception as exc:
        print_value("device count", f"unavailable: {exc}")
        return
    print_value("device count", device_count)
    if device_count <= 0:
        return
    if device_index < 0 or device_index >= device_count:
        print_value("selected device index", f"{device_index} outside available range 0..{device_count - 1}")
        return
    for label, reader in (
        ("device name", backend.enum_device_name),
        ("serial number", backend.enum_device_serial_number),
        ("opened before open", backend.enum_device_is_opened),
    ):
        try:
            print_value(label, reader(device_index))
        except Exception as exc:
            print_value(label, f"unavailable: {exc}")


def safe_backend_call(label: str, action: object) -> None:
    try:
        action()
        print_step(f"cleanup ok: {label}")
    except Exception as exc:
        print_step(f"cleanup warning: {label} failed: {exc}")


def safe_disable_ad2_outputs(backend: WaveFormsBackend, handle: int) -> None:
    print_step("safe AD2 output disable/reset")
    for channel in (0, 1):
        safe_backend_call(
            f"FDwfAnalogOutConfigure channel {channel} stop",
            lambda channel=channel: backend.analog_out_configure(handle, channel, False),
        )
        for node in (0, 1):
            safe_backend_call(
                f"FDwfAnalogOutNodeEnableSet channel {channel} node {node} false",
                lambda channel=channel, node=node: backend.analog_out_node_enable_set(handle, channel, node, False),
            )
    safe_backend_call("FDwfDigitalOutConfigure stop", lambda: backend.digital_out_configure(handle, False))
    safe_backend_call("FDwfDigitalOutReset", lambda: backend.reset_do(handle))
    safe_backend_call("FDwfDeviceReset", lambda: backend.reset_device(handle))


def run_real_ad2_open_close(device_index: int = 0) -> int:
    print_step("real AD2 open-close smoke")
    print_step("no analog output, digital output, trigger output, PC trigger, camera, pump, valve, or Z-stage action will be run")
    backend: WaveFormsBackend | None = None
    handle: int | None = None
    try:
        backend = WaveFormsBackend()
        print_value("WaveForms DLL", backend.library_path)
        read_ad2_identity(backend, device_index)
        print_step(f"opening AD2 device index {device_index}")
        handle = backend.open_device(device_index)
        print_value("handle", handle)
        print_step("device opened; outputs remain disabled and no configure/start/trigger/output calls are made")
        return 0
    finally:
        print_step("AD2 open-close cleanup")
        if backend is not None and handle is not None:
            safe_disable_ad2_outputs(backend, handle)
            safe_backend_call("FDwfDeviceClose", lambda: backend.close(handle))
        if backend is not None:
            safe_backend_call("FDwfDeviceCloseAll", backend.close_all)


def low_risk_ad2_parameters() -> Ad2OutputSmokeParameters:
    return Ad2OutputSmokeParameters(
        name="low-risk",
        channel=AD2_LOW_RISK_CHANNEL,
        frequency_hz=AD2_LOW_RISK_FREQUENCY_HZ,
        amplitude_v=AD2_LOW_RISK_AMPLITUDE_V,
        offset_v=AD2_LOW_RISK_OFFSET_V,
        duration_s=AD2_LOW_RISK_DURATION_S,
    )


def ad2_timing_check_parameters(duration_s: float | None = None) -> Ad2OutputSmokeParameters:
    duration = AD2_LOW_RISK_DURATION_S if duration_s is None else float(duration_s)
    if duration <= 0:
        raise SystemExit("--duration-s must be greater than 0")
    if duration >= AD2_LABVIEW_ACOUSTIC_ORIGINAL_DURATION_S:
        raise SystemExit("Refusing to use a long duration in the AD2 timing check; keep this smoke test short.")
    return Ad2OutputSmokeParameters(
        name="timing-check",
        channel=AD2_LOW_RISK_CHANNEL,
        frequency_hz=AD2_LOW_RISK_FREQUENCY_HZ,
        amplitude_v=AD2_LOW_RISK_AMPLITUDE_V,
        offset_v=AD2_LOW_RISK_OFFSET_V,
        duration_s=duration,
    )


def labview_acoustic_short_parameters(duration_s: float | None = None) -> Ad2OutputSmokeParameters:
    duration = AD2_LABVIEW_ACOUSTIC_SHORT_DURATION_S if duration_s is None else float(duration_s)
    if duration <= 0:
        raise SystemExit("--duration-s must be greater than 0")
    if duration >= AD2_LABVIEW_ACOUSTIC_ORIGINAL_DURATION_S:
        raise SystemExit(
            "Refusing to run the full LabVIEW acoustic duration in this staged smoke mode "
            f"({AD2_LABVIEW_ACOUSTIC_ORIGINAL_DURATION_S:g} s)."
        )
    return Ad2OutputSmokeParameters(
        name="labview-acoustic-short",
        channel=AD2_LABVIEW_ACOUSTIC_CHANNEL,
        frequency_hz=AD2_LABVIEW_ACOUSTIC_FREQUENCY_HZ,
        amplitude_v=AD2_LABVIEW_ACOUSTIC_AMPLITUDE_V,
        offset_v=AD2_LABVIEW_ACOUSTIC_OFFSET_V,
        duration_s=duration,
    )


def ad2_output_wfg_config(parameters: Ad2OutputSmokeParameters) -> WfgConfig:
    return WfgConfig(
        running=True,
        channels=[
            WfgChannelConfig(
                channel_index=parameters.channel,
                carrier=CarrierSettings(
                    frequency_hz=parameters.frequency_hz,
                    amplitude_v=parameters.amplitude_v,
                    offset_v=parameters.offset_v,
                    symmetry_percent=50.0,
                    phase_deg=0.0,
                    function=parameters.waveform,
                    enable=True,
                ),
                trigger=TriggerSettings(
                    sec_run=parameters.duration_s,
                    sec_wait=0.0,
                    repeat_count=parameters.repeat_count,
                    repeat_trigger=False,
                ),
            )
        ],
        synchronize_state="Independent",
    )


def low_risk_wfg_config() -> WfgConfig:
    return ad2_output_wfg_config(low_risk_ad2_parameters())


def ad2_timing_check_wfg_config(duration_s: float | None = None) -> WfgConfig:
    return ad2_output_wfg_config(ad2_timing_check_parameters(duration_s))


def print_ad2_output_parameters(parameters: Ad2OutputSmokeParameters) -> None:
    print_step(f"real AD2 {parameters.name} output parameters")
    print_value("channel", parameters.channel)
    print_value("frequency_hz", parameters.frequency_hz)
    print_value("amplitude_v", parameters.amplitude_v)
    print_value("offset_v", parameters.offset_v)
    print_value("function", parameters.waveform.value)
    print_value("duration_s", parameters.duration_s)
    print_value("repeat_count", parameters.repeat_count)


def print_low_risk_ad2_output_parameters() -> None:
    print_ad2_output_parameters(low_risk_ad2_parameters())
    print_value("LabVIEW acoustic output", "not used: no 1.975 MHz, 2.0 V, 60 s output in this mode")


def print_ad2_timing_check_plan(
    pre_trigger_wait_s: float,
    duration_s: float | None = None,
    *,
    plan_only: bool = True,
) -> None:
    if pre_trigger_wait_s < 0:
        raise SystemExit("--pre-trigger-wait-s must be greater than or equal to 0")
    parameters = ad2_timing_check_parameters(duration_s)
    print_step("AD2 timing verification plan")
    print_value("real hardware initialized in plan", False if plan_only else "after this printout")
    print_value("purpose", "observe whether trigsrcNone output starts during config_wfg or waits for pc_trigger")
    print_ad2_output_parameters(parameters)
    print_value("trigger source", "trigsrcNone")
    print_value("pre_trigger_wait_s", pre_trigger_wait_s)
    print_value("CH2/index 1", "disabled")
    print_value("DO Clock", "not used")
    print_value("DO Custom", "not used")
    print_value("LabVIEW acoustic output", "not used: no 1.975 MHz, 2.0 V, 60 s output")
    print_step("timing sequence")
    print_value("1", "open AD2")
    print_value("2", "reset/disable AO ch0/ch1 and DO")
    print_value("3", "configure WFG: CH0 1000 Hz sine, 0.1 V amplitude, 0 V offset, trigsrcNone, running=True")
    print_value("4", f"wait {pre_trigger_wait_s} s before pc_trigger")
    print_value("5", "send pc_trigger")
    print_value("6", f"wait output duration {parameters.duration_s} s")
    print_value("7", "stop/disable AO ch0/ch1, reset DO, reset device, close, FDwfDeviceCloseAll")
    print_step("expected oscilloscope/MSO interpretation")
    print_value("if waveform appears during pre-trigger wait", "trigsrcNone/config_wfg starts output immediately")
    print_value("if waveform appears only after pc_trigger", "PC trigger controls start for this configuration")
    print_step("pump, valve, Qmix, Z-stage, Thorlabs/APT, Prior COM7, camera, DO Clock, and DO Custom are not used")


def print_labview_acoustic_short_output_parameters(parameters: Ad2OutputSmokeParameters) -> None:
    print_step("WARNING: LabVIEW acoustic candidate frequency/amplitude selected for short-duration AD2-only smoke")
    print_value("original LabVIEW experiment run_s", AD2_LABVIEW_ACOUSTIC_ORIGINAL_DURATION_S)
    print_value("short smoke duration_s", parameters.duration_s)
    print_ad2_output_parameters(parameters)
    print_value("camera", "not used")
    print_value("pump", "not used")
    print_value("valve", "not used")
    print_value("Qmix", "not used")
    print_value("Z-stage", "not used")
    print_value("Thorlabs/APT", "not used")
    print_value("Prior COM7", "not used")


def run_real_ad2_low_risk_output(device_index: int = 0) -> int:
    print_step("real AD2 low-risk output smoke")
    print_step("camera, pump, valve, Qmix, Z-stage, Thorlabs/APT, and Prior COM7 are not used")
    print_low_risk_ad2_output_parameters()
    backend: WaveFormsBackend | None = None
    handle: int | None = None
    try:
        backend = WaveFormsBackend()
        print_value("WaveForms DLL", backend.library_path)
        read_ad2_identity(backend, device_index)
        print_step(f"opening AD2 device index {device_index}")
        handle = backend.open_device(device_index)
        print_value("handle", handle)
        safe_disable_ad2_outputs(backend, handle)
        print_step("configuring and starting low-risk analog output")
        backend.configure_wfg(handle, low_risk_wfg_config())
        print_step("waiting for low-risk output duration")
        time.sleep(AD2_LOW_RISK_DURATION_S + 0.1)
        return 0
    finally:
        print_step("AD2 low-risk output cleanup")
        if backend is not None and handle is not None:
            safe_disable_ad2_outputs(backend, handle)
            safe_backend_call("FDwfDeviceClose", lambda: backend.close(handle))
        if backend is not None:
            safe_backend_call("FDwfDeviceCloseAll", backend.close_all)


def run_real_ad2_timing_check(
    device_index: int = 0,
    pre_trigger_wait_s: float = AD2_TIMING_DEFAULT_PRE_TRIGGER_WAIT_S,
    duration_s: float | None = None,
) -> int:
    if pre_trigger_wait_s < 0:
        raise SystemExit("--pre-trigger-wait-s must be greater than or equal to 0")
    parameters = ad2_timing_check_parameters(duration_s)
    print_step("real AD2 timing verification smoke")
    print_step("camera, pump, valve, Qmix, Z-stage, Thorlabs/APT, Prior COM7, DO Clock, and DO Custom are not used")
    print_ad2_timing_check_plan(pre_trigger_wait_s, parameters.duration_s, plan_only=False)
    backend: WaveFormsBackend | None = None
    handle: int | None = None
    try:
        backend = WaveFormsBackend()
        print_value("WaveForms DLL", backend.library_path)
        read_ad2_identity(backend, device_index)
        print_step(f"opening AD2 device index {device_index}")
        handle = backend.open_device(device_index)
        print_value("handle", handle)
        safe_disable_ad2_outputs(backend, handle)
        print_step("configuring timing-check WFG now; watch for waveform during the pre-trigger wait")
        backend.configure_wfg(handle, ad2_timing_check_wfg_config(parameters.duration_s))
        print_step(f"pre-trigger observation wait: {pre_trigger_wait_s} s")
        time.sleep(pre_trigger_wait_s)
        print_step("sending AD2 PC trigger now")
        backend.trigger_pc(handle)
        print_step(f"post-trigger observation wait: {parameters.duration_s} s")
        time.sleep(parameters.duration_s + 0.1)
        return 0
    finally:
        print_step("AD2 timing check cleanup")
        if backend is not None and handle is not None:
            safe_disable_ad2_outputs(backend, handle)
            safe_backend_call("FDwfDeviceClose", lambda: backend.close(handle))
        if backend is not None:
            safe_backend_call("FDwfDeviceCloseAll", backend.close_all)


def run_real_ad2_labview_acoustic_short(device_index: int = 0, duration_s: float | None = None) -> int:
    parameters = labview_acoustic_short_parameters(duration_s)
    print_step("real AD2 LabVIEW acoustic short-duration smoke")
    print_step("camera, pump, valve, Qmix, Z-stage, Thorlabs/APT, and Prior COM7 are not used")
    print_labview_acoustic_short_output_parameters(parameters)
    backend: WaveFormsBackend | None = None
    handle: int | None = None
    try:
        backend = WaveFormsBackend()
        print_value("WaveForms DLL", backend.library_path)
        read_ad2_identity(backend, device_index)
        print_step(f"opening AD2 device index {device_index}")
        handle = backend.open_device(device_index)
        print_value("handle", handle)
        safe_disable_ad2_outputs(backend, handle)
        print_step("configuring and starting LabVIEW acoustic candidate short-duration analog output")
        backend.configure_wfg(handle, ad2_output_wfg_config(parameters))
        print_step("waiting for short acoustic smoke output duration")
        time.sleep(parameters.duration_s + 0.1)
        return 0
    finally:
        print_step("AD2 LabVIEW acoustic short cleanup")
        if backend is not None and handle is not None:
            safe_disable_ad2_outputs(backend, handle)
            safe_backend_call("FDwfDeviceClose", lambda: backend.close(handle))
        if backend is not None:
            safe_backend_call("FDwfDeviceCloseAll", backend.close_all)


def print_plan(plan: SmokePlan, output_dir: Path, settings: SmokeRunSettings) -> None:
    print_step(f"plan: {plan.name}")
    print_value("description", plan.description)
    print_value("output directory", output_dir)
    print_value("frames", settings.frames)
    print_value("exposure_ms", settings.exposure_ms)
    print_value("trigger source", settings.trigger_source)
    if settings.roi is None:
        print_value("ROI", "not preset")
    else:
        print_value("LabVIEW ROI candidate", settings.roi)
        if settings.apply_roi:
            print_value("ROI application", "enabled explicitly by --apply-roi")
        else:
            print_value("ROI application", "disabled by default; pass --apply-roi for explicit ROI validation")
    print_value("flush_enabled", plan.flush_enabled)
    print_value("requires confirmation", plan.requires_confirmation)
    print_step("hardware modes")
    print_value("camera", "real Hamamatsu DCAM backend")
    print_value("AD2", "real low-risk" if not plan.config.sim_ad2 else "simulated")
    print_value("pump", "simulated/disabled; no Qmix backend")
    print_value("valve", "simulated/disabled; no serial backend")
    print_value("Z-stage", "disabled; no Prior COM7 or Thorlabs/APT motion")
    print_value("AD2 output", "real low-risk only" if not plan.config.sim_ad2 else "not real; SimulatedAD2Sdk only")
    print_value("pump/valve flush", "disabled")
    if settings.preset is not None:
        print_labview_preset_summary(settings.preset)
        print_value("smoke frame override", f"{settings.frames} frame(s); LabVIEW experiment preset uses {settings.preset.experiment.frames}")
    print_step("default behavior is plan-only; no hardware is initialized unless --real-camera-only is passed")


def print_camera_roi_diagnostics(camera: object, requested_roi: dict[str, int], label: str) -> None:
    print_step(f"ROI diagnostics: {label}")
    print_value("requested ROI", requested_roi)
    try:
        limits, roi = camera.read_subregion_limits_and_value()
        print_value("ROI limits", limits)
        print_value("actual ROI readback", roi)
    except Exception as exc:
        print_value("ROI readback", f"unavailable: {exc}")
    backend = getattr(camera, "backend", None)
    dcam = getattr(backend, "dcam", None)
    dcam_module = getattr(backend, "dcam_module", None)
    if dcam is None or dcam_module is None:
        print_value("DCAM property diagnostics", "unavailable: no real DCAM backend handle")
        return
    props = getattr(dcam_module, "DCAM_IDPROP", None)
    mode_enum = getattr(getattr(dcam_module, "DCAMPROP", None), "MODE", None)
    if props is None:
        print_value("DCAM property diagnostics", "unavailable: no DCAM_IDPROP")
        return
    for name in ("SUBARRAYMODE", "IMAGE_WIDTH", "IMAGE_HEIGHT", "SUBARRAYHPOS", "SUBARRAYVPOS", "SUBARRAYHSIZE", "SUBARRAYVSIZE"):
        if not hasattr(props, name):
            print_value(name, "unavailable")
            continue
        try:
            value = dcam.prop_getvalue(getattr(props, name))
        except Exception as exc:
            print_value(name, f"unavailable: {exc}")
            continue
        if name == "SUBARRAYMODE" and mode_enum is not None:
            if hasattr(mode_enum, "ON") and value == mode_enum.ON:
                value = f"{value} (ON)"
            elif hasattr(mode_enum, "OFF") and value == mode_enum.OFF:
                value = f"{value} (OFF)"
        print_value(name, value)


def require_confirmation_if_needed(plan: SmokePlan, confirmation: str | None) -> None:
    if not plan.requires_confirmation:
        return
    if confirmation != CONFIRM_TEXT:
        raise SystemExit(f"This mode requires --confirm {CONFIRM_TEXT}")


def run_real_camera_only(
    output_dir: Path,
    frames: int | None,
    exposure_ms: float | None,
    preset_name: str | None = None,
    apply_roi: bool = False,
) -> Path:
    plan = real_camera_only_plan()
    settings = resolve_smoke_settings(preset_name, frames, exposure_ms, apply_roi)
    run_dir = output_dir / f"real_camera_only_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print_plan(plan, run_dir, settings)
    print_step("initializing selected hardware")

    app = Application()
    bundle = build_hardware_bundle(plan.config)
    camera_backend = bundle.camera.backend
    buffer_frames = getattr(camera_backend, "buffer_frames", "<unknown>")
    allocation_frames = max(settings.frames, int(buffer_frames) if isinstance(buffer_frames, int) else 1)
    print_step("camera acquisition diagnostics")
    print_value("trigger source", settings.trigger_source)
    print_value("exposure_ms", settings.exposure_ms)
    print_value("requested frame count", settings.frames)
    print_value("backend buffer_frames", buffer_frames)
    print_value("planned buffer allocation frames", allocation_frames)
    print_value("capture order", "configure_sequence -> start_capture/buf_alloc/cap_start -> image_sequence/read -> stop_capture")
    apply_hardware_bundle(app, bundle)
    experiment = Experiment2(
        experiment_folder=run_dir,
        flush_settings=FlushSettings(0.0, 0.0, 0.0),
        flush_enabled=False,
        global_exposure_ms=settings.exposure_ms,
        sequence_settings={
            "frames": settings.frames,
            "trigger_source": settings.trigger_source,
            "exposure_ms": settings.exposure_ms,
        },
        wfg_config={"running": False, "channels": []},
        do_clock_settings={"running": False, "channels": []},
    )
    app.experiment_series = ExperimentSeries2(output_dir, [experiment])

    try:
        app.initialize()
        if settings.roi is not None and settings.apply_roi:
            if hasattr(app.camera, "configure_roi"):
                print_step("applying LabVIEW screenshot ROI to real camera because --apply-roi was provided")
                print_camera_roi_diagnostics(app.camera, settings.roi, "before configure_roi")
                app.camera.configure_roi(settings.roi)
                print_camera_roi_diagnostics(app.camera, settings.roi, "after configure_roi")
            else:
                print_step("LabVIEW screenshot ROI is known but not applied: camera wrapper has no configure_roi")
        elif settings.roi is not None:
            print_step("LabVIEW screenshot ROI is known but not applied; pass --apply-roi for explicit ROI validation")
        print_step("running one real-camera-only experiment")
        ok = app.run_experiment2()
        print_value("experiment ok", ok)
        print_value("experiment folder", run_dir)
        return run_dir
    finally:
        print_step("cleanup")
        app.cleanup()


def run_real_camera_real_ad2_low_risk(
    output_dir: Path,
    frames: int | None,
    exposure_ms: float | None,
    preset_name: str | None = None,
    apply_roi: bool = False,
    device_index: int = 0,
) -> Path:
    _ = device_index
    plan = real_camera_real_ad2_low_risk_plan()
    settings = resolve_smoke_settings(preset_name, frames, exposure_ms, apply_roi)
    run_dir = output_dir / f"camera_ad2_lowrisk_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print_plan(plan, run_dir, settings)
    print_low_risk_ad2_output_parameters()
    print_step("combined smoke uses Application.run_experiment2 with flush_enabled=False")
    print_step("pump, valve, Qmix, Z-stage, Thorlabs/APT, and Prior COM7 remain disabled or unused")

    app = Application()
    bundle = build_hardware_bundle(plan.config)
    camera_backend = bundle.camera.backend
    buffer_frames = getattr(camera_backend, "buffer_frames", "<unknown>")
    allocation_frames = max(settings.frames, int(buffer_frames) if isinstance(buffer_frames, int) else 1)
    print_step("combined acquisition diagnostics")
    print_value("camera trigger source", settings.trigger_source)
    print_value("camera exposure_ms", settings.exposure_ms)
    print_value("camera requested frame count", settings.frames)
    print_value("camera backend buffer_frames", buffer_frames)
    print_value("camera planned buffer allocation frames", allocation_frames)
    print_value("AD2 low-risk config", "CH0 1000 Hz sine, 0.1 V amplitude, 0 V offset, 0.5 s")
    print_value("LabVIEW acoustic output", "not used: no 1.975 MHz, 2.0 V, 60 s output")

    apply_hardware_bundle(app, bundle)
    experiment = Experiment2(
        experiment_folder=run_dir,
        flush_settings=FlushSettings(0.0, 0.0, 0.0),
        flush_enabled=False,
        global_exposure_ms=settings.exposure_ms,
        sequence_settings={
            "frames": settings.frames,
            "trigger_source": settings.trigger_source,
            "exposure_ms": settings.exposure_ms,
        },
        wfg_config=low_risk_wfg_config(),
        do_clock_settings={"running": False, "channels": []},
    )
    app.experiment_series = ExperimentSeries2(output_dir, [experiment])

    try:
        app.initialize()
        if settings.roi is not None and settings.apply_roi:
            if hasattr(app.camera, "configure_roi"):
                print_step("applying LabVIEW screenshot ROI to real camera because --apply-roi was provided")
                print_camera_roi_diagnostics(app.camera, settings.roi, "before configure_roi")
                app.camera.configure_roi(settings.roi)
                print_camera_roi_diagnostics(app.camera, settings.roi, "after configure_roi")
            else:
                print_step("LabVIEW screenshot ROI is known but not applied: camera wrapper has no configure_roi")
        elif settings.roi is not None:
            print_step("LabVIEW screenshot ROI is known but not applied; pass --apply-roi for explicit ROI validation")

        print_step("running combined real-camera + real-AD2 low-risk experiment")
        ok = app.run_experiment2()
        print_value("experiment ok", ok)
        print_value("experiment folder", run_dir)
        return run_dir
    finally:
        print_step("combined smoke cleanup")
        ad2_backend = getattr(app.ad2, "backend", None)
        ad2_handle = getattr(app.ad2, "device_handle", None)
        if isinstance(ad2_backend, WaveFormsBackend) and ad2_handle is not None:
            safe_disable_ad2_outputs(ad2_backend, int(ad2_handle))
        try:
            if hasattr(app.camera, "stop_capture"):
                app.camera.stop_capture()
        except Exception as exc:
            print_step(f"cleanup warning: camera stop_capture failed: {exc}")
        app.cleanup()


def run_real_camera_real_ad2_acoustic_short(
    output_dir: Path,
    frames: int | None,
    exposure_ms: float | None,
    preset_name: str | None = None,
    apply_roi: bool = False,
    device_index: int = 0,
    duration_s: float | None = None,
) -> Path:
    _ = device_index
    plan = real_camera_real_ad2_acoustic_short_plan()
    settings = resolve_smoke_settings(preset_name, frames, exposure_ms, apply_roi)
    acoustic_parameters = labview_acoustic_short_parameters(duration_s)
    run_dir = output_dir / f"camera_ad2_acoustic_short_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print_plan(plan, run_dir, settings)
    print_labview_acoustic_short_output_parameters(acoustic_parameters)
    print_step("combined acoustic-short smoke uses Application.run_experiment2 with flush_enabled=False")
    print_step("CH2/index 1 remains disabled; DO Clock and DO Custom are not used")
    print_step("pump, valve, Qmix, Z-stage, Thorlabs/APT, and Prior COM7 remain disabled or unused")

    app = Application()
    bundle = build_hardware_bundle(plan.config)
    camera_backend = bundle.camera.backend
    buffer_frames = getattr(camera_backend, "buffer_frames", "<unknown>")
    allocation_frames = max(settings.frames, int(buffer_frames) if isinstance(buffer_frames, int) else 1)
    print_step("combined acoustic-short acquisition diagnostics")
    print_value("camera trigger source", settings.trigger_source)
    print_value("camera exposure_ms", settings.exposure_ms)
    print_value("camera requested frame count", settings.frames)
    print_value("camera backend buffer_frames", buffer_frames)
    print_value("camera planned buffer allocation frames", allocation_frames)
    print_value(
        "AD2 acoustic-short config",
        (
            f"CH{acoustic_parameters.channel} {acoustic_parameters.frequency_hz} Hz sine, "
            f"{acoustic_parameters.amplitude_v} V amplitude, {acoustic_parameters.offset_v} V offset, "
            f"{acoustic_parameters.duration_s} s"
        ),
    )
    print_value("CH2/index 1", "disabled")
    print_value("DO Clock", "not used")
    print_value("DO Custom", "not used")
    print_value("pump/valve flush", "disabled")

    apply_hardware_bundle(app, bundle)
    experiment = Experiment2(
        experiment_folder=run_dir,
        flush_settings=FlushSettings(0.0, 0.0, 0.0),
        flush_enabled=False,
        global_exposure_ms=settings.exposure_ms,
        sequence_settings={
            "frames": settings.frames,
            "trigger_source": settings.trigger_source,
            "exposure_ms": settings.exposure_ms,
        },
        wfg_config=ad2_output_wfg_config(acoustic_parameters),
        do_clock_settings={"running": False, "channels": []},
    )
    app.experiment_series = ExperimentSeries2(output_dir, [experiment])

    try:
        app.initialize()
        if settings.roi is not None and settings.apply_roi:
            if hasattr(app.camera, "configure_roi"):
                print_step("applying LabVIEW screenshot ROI to real camera because --apply-roi was provided")
                print_camera_roi_diagnostics(app.camera, settings.roi, "before configure_roi")
                app.camera.configure_roi(settings.roi)
                print_camera_roi_diagnostics(app.camera, settings.roi, "after configure_roi")
            else:
                print_step("LabVIEW screenshot ROI is known but not applied: camera wrapper has no configure_roi")
        elif settings.roi is not None:
            print_step("LabVIEW screenshot ROI is known but not applied; pass --apply-roi for explicit ROI validation")

        print_step("running combined real-camera + real-AD2 LabVIEW acoustic-short experiment")
        ok = app.run_experiment2()
        print_value("experiment ok", ok)
        print_value("experiment folder", run_dir)
        return run_dir
    finally:
        print_step("combined acoustic-short smoke cleanup")
        ad2_backend = getattr(app.ad2, "backend", None)
        ad2_handle = getattr(app.ad2, "device_handle", None)
        if isinstance(ad2_backend, WaveFormsBackend) and ad2_handle is not None:
            safe_disable_ad2_outputs(ad2_backend, int(ad2_handle))
        try:
            if hasattr(app.camera, "stop_capture"):
                app.camera.stop_capture()
        except Exception as exc:
            print_step(f"cleanup warning: camera stop_capture failed: {exc}")
        app.cleanup()


def run_real_full_workflow_short(
    output_dir: Path,
    frames: int | None,
    exposure_ms: float | None,
    preset_name: str | None,
    apply_roi: bool,
    valve_port: str,
    flush_enabled: bool,
    device_index: int = 0,
    duration_s: float | None = None,
) -> Path:
    _ = device_index
    defaults = default_hardware_config()
    plan = real_full_workflow_short_plan(valve_port, flush_enabled=flush_enabled)
    settings = resolve_smoke_settings(preset_name, frames, exposure_ms, apply_roi)
    acoustic_parameters = labview_acoustic_short_parameters(duration_s)
    preset = settings.preset or labview_screenshot_working_preset()
    flush_settings = FlushSettings(
        flush_flowrate=preset.flush.experiment_flush_flowrate_ul,
        flush_volume_ml=preset.flush.experiment_flush_volume_ml,
        wait_after_flush_s=preset.flush.experiment_wait_after_flush_s,
    )
    run_dir = output_dir / f"full_workflow_short_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print_step("REAL FULL WORKFLOW SHORT: camera + AD2 + one-pump Qmix + valve; Z-stage disabled")
    print_value("description", plan.description)
    print_value("frames", settings.frames)
    print_value("exposure_ms", settings.exposure_ms)
    print_value("trigger source", settings.trigger_source)
    if settings.roi is None:
        print_value("ROI", "not preset")
    else:
        print_value("LabVIEW ROI candidate", settings.roi)
        print_value(
            "ROI application",
            "enabled explicitly by --apply-roi" if settings.apply_roi else "disabled by default; pass --apply-roi",
        )
    print_value("camera", "real Hamamatsu DCAM backend")
    print_value("AD2", "real WaveForms backend")
    print_value("pump", "real one-pump Qmix backend")
    print_value("valve", "real serial valve backend")
    print_value("Z-stage", "disabled; no Prior COM7 and no Thorlabs/APT motion")
    print_value("flush_enabled", flush_enabled)
    print_value("output directory", run_dir)
    print_value("Qmix SDK Python path", defaults.qmix.sdk_python_path)
    print_value("QMIXSDK path", defaults.qmix.qmixsdk_path)
    print_value("Qmix config path", defaults.qmix.config_path)
    print_value("Qmix active_units", defaults.qmix.active_units)
    print_value("legacy two-pump config allowed", defaults.qmix.legacy_two_pump_config_allowed)
    print_value("legacy two-pump config selected", "no")
    print_value("selected valve port", valve_port)
    print_value("valve position sequence if flush runs", "position 1 -> pump flow -> position 2")
    print_value("flush flowrate", f"{flush_settings.flush_flowrate} uL/min candidate")
    print_value("flush volume", f"{flush_settings.flush_volume_ml} ml")
    print_value("flush wait_after_flush_s", flush_settings.wait_after_flush_s)
    print_value("Pump&Valve tab wait_after_flush conflict", f"{preset.flush.pump_tab_wait_after_flush_s} s candidate, not used")
    print_labview_acoustic_short_output_parameters(acoustic_parameters)
    print_value("CH2/index 1", "disabled")
    print_value("DO Clock", "not used")
    print_value("DO Custom", "not used")
    print_step("full workflow uses Application.run_experiment2")

    os.environ["QMIXSDK"] = str(defaults.qmix.qmixsdk_path)
    print_value("QMIXSDK set for this process", os.environ["QMIXSDK"])

    app = Application()
    bundle = build_hardware_bundle(plan.config)
    pump_backend = getattr(bundle.pump, "backend", None)
    if pump_backend is not None and hasattr(pump_backend, "sdk_python_path"):
        pump_backend.sdk_python_path = defaults.qmix.sdk_python_path
        print_value("Qmix backend sdk_python_path", pump_backend.sdk_python_path)
    camera_backend = bundle.camera.backend
    buffer_frames = getattr(camera_backend, "buffer_frames", "<unknown>")
    allocation_frames = max(settings.frames, int(buffer_frames) if isinstance(buffer_frames, int) else 1)
    print_step("full workflow acquisition diagnostics")
    print_value("camera trigger source", settings.trigger_source)
    print_value("camera exposure_ms", settings.exposure_ms)
    print_value("camera requested frame count", settings.frames)
    print_value("camera backend buffer_frames", buffer_frames)
    print_value("camera planned buffer allocation frames", allocation_frames)
    print_value(
        "AD2 acoustic-short config",
        (
            f"CH{acoustic_parameters.channel} {acoustic_parameters.frequency_hz} Hz sine, "
            f"{acoustic_parameters.amplitude_v} V amplitude, {acoustic_parameters.offset_v} V offset, "
            f"{acoustic_parameters.duration_s} s"
        ),
    )

    apply_hardware_bundle(app, bundle)
    experiment = Experiment2(
        experiment_folder=run_dir,
        flush_settings=flush_settings,
        flush_enabled=flush_enabled,
        global_exposure_ms=settings.exposure_ms,
        sequence_settings={
            "frames": settings.frames,
            "trigger_source": settings.trigger_source,
            "exposure_ms": settings.exposure_ms,
        },
        wfg_config=ad2_output_wfg_config(acoustic_parameters),
        do_clock_settings={"running": False, "channels": []},
    )
    app.experiment_series = ExperimentSeries2(output_dir, [experiment])

    try:
        app.initialize()
        if settings.roi is not None and settings.apply_roi:
            if hasattr(app.camera, "configure_roi"):
                print_step("applying LabVIEW screenshot ROI to real camera because --apply-roi was provided")
                print_camera_roi_diagnostics(app.camera, settings.roi, "before configure_roi")
                app.camera.configure_roi(settings.roi)
                print_camera_roi_diagnostics(app.camera, settings.roi, "after configure_roi")
            else:
                print_step("LabVIEW screenshot ROI is known but not applied: camera wrapper has no configure_roi")
        elif settings.roi is not None:
            print_step("LabVIEW screenshot ROI is known but not applied; pass --apply-roi for explicit ROI validation")

        print_step("running real full workflow short experiment")
        ok = app.run_experiment2()
        print_value("experiment ok", ok)
        print_value("experiment folder", run_dir)
        return run_dir
    finally:
        print_step("real full workflow short cleanup")
        ad2_backend = getattr(app.ad2, "backend", None)
        ad2_handle = getattr(app.ad2, "device_handle", None)
        if isinstance(ad2_backend, WaveFormsBackend) and ad2_handle is not None:
            safe_disable_ad2_outputs(ad2_backend, int(ad2_handle))
        try:
            if hasattr(app.camera, "stop_capture"):
                app.camera.stop_capture()
        except Exception as exc:
            print_step(f"cleanup warning: camera stop_capture failed: {exc}")
        app.cleanup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Staged real-hardware workflow smoke test. Default mode is "
            "plan-only and performs no hardware initialization."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan-only", action="store_true", help="Print the staged smoke-test plan without touching hardware.")
    mode.add_argument("--ad2-plan-only", action="store_true", help="Print LabVIEW screenshot AD2 parameters without touching hardware.")
    mode.add_argument("--real-ad2-open-close", action="store_true", help="Open and close the real AD2 with safe reset/disable cleanup. Requires --confirm.")
    mode.add_argument(
        "--real-ad2-low-risk-output",
        action="store_true",
        help="Run a deliberately low-risk AD2 output smoke. Requires --confirm.",
    )
    mode.add_argument(
        "--real-ad2-timing-check",
        action="store_true",
        help="Run low-risk AD2 timing check for oscilloscope/MSO observation. Requires --confirm.",
    )
    mode.add_argument(
        "--real-ad2-labview-acoustic-short",
        action="store_true",
        help="Run the LabVIEW acoustic candidate frequency/amplitude for a short AD2-only smoke. Requires --confirm.",
    )
    mode.add_argument(
        "--real-camera-real-ad2-low-risk",
        action="store_true",
        help="Run combined real camera plus real AD2 low-risk workflow. Requires --confirm.",
    )
    mode.add_argument(
        "--real-camera-real-ad2-acoustic-short",
        action="store_true",
        help=(
            "Run combined real camera plus real AD2 LabVIEW acoustic candidate "
            "short-duration workflow. Requires --confirm and --acknowledge-timing-uncertain."
        ),
    )
    mode.add_argument(
        "--real-full-workflow-short",
        action="store_true",
        help=(
            "Run short real camera + AD2 acoustic CH0 + one-pump Qmix + valve workflow "
            "with Z disabled. Requires explicit confirmations and --valve-port."
        ),
    )
    mode.add_argument(
        "--real-camera-only",
        action="store_true",
        help="Run a real Hamamatsu camera-only acquisition. AD2/pump/valve are simulated and Z-stage is disabled.",
    )
    parser.add_argument("--preset", choices=[LABVIEW_SCREENSHOT_PRESET_NAME], default=None)
    parser.add_argument("--ad2-plan", action="store_true", help="Also print LabVIEW screenshot AD2 candidate parameters in plan-only mode.")
    parser.add_argument("--ad2-timing-plan", action="store_true", help="Print low-risk AD2 timing verification sequence without touching hardware.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "hardware_tests" / "_smoke_output")
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--exposure-ms", type=float, default=None)
    parser.add_argument("--device-index", type=int, default=0, help="WaveForms device index for real AD2 smoke modes. Default: 0.")
    parser.add_argument("--valve-port", choices=["COM5", "COM6"], default=None, help="Explicit real valve serial port for full workflow mode.")
    parser.add_argument("--flush-enabled", action="store_true", help="Enable the controlled pump/valve flush in full workflow mode.")
    parser.add_argument(
        "--duration-s",
        type=float,
        default=None,
        help="Duration override for AD2 timing/acoustic short modes. Must remain short.",
    )
    parser.add_argument(
        "--pre-trigger-wait-s",
        type=float,
        default=AD2_TIMING_DEFAULT_PRE_TRIGGER_WAIT_S,
        help="Observation wait after AD2 timing-check config_wfg and before pc_trigger. Default: 2.0.",
    )
    parser.add_argument(
        TIMING_UNCERTAIN_ACK_FLAG,
        action="store_true",
        help=(
            "Required extra acknowledgement for LabVIEW acoustic short modes. "
            "AD2 WFG start timing versus pc_trigger is not yet fully confirmed."
        ),
    )
    parser.add_argument(
        PUMP_VALVE_REAL_ACK_FLAG,
        action="store_true",
        help="Required acknowledgement for modes that open real Qmix pump and real valve backends.",
    )
    parser.add_argument(
        "--apply-roi",
        action="store_true",
        help="Explicitly apply the selected preset ROI before camera capture. Default is to print ROI only.",
    )
    parser.add_argument("--confirm", default=None, help=f"Typed confirmation for future actuator-affecting modes: {CONFIRM_TEXT}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = real_camera_only_plan()
    settings = resolve_smoke_settings(args.preset, args.frames, args.exposure_ms, args.apply_roi)
    if args.ad2_plan_only:
        print_ad2_labview_candidate(settings)
        return 0
    if args.real_ad2_open_close:
        if args.confirm != CONFIRM_TEXT:
            raise SystemExit(f"This mode requires --confirm {CONFIRM_TEXT}")
        run_real_ad2_open_close(args.device_index)
        return 0
    if args.real_ad2_low_risk_output:
        if args.confirm != CONFIRM_TEXT:
            raise SystemExit(f"This mode requires --confirm {CONFIRM_TEXT}")
        run_real_ad2_low_risk_output(args.device_index)
        return 0
    if args.real_ad2_timing_check:
        if args.confirm != CONFIRM_TEXT:
            raise SystemExit(f"This mode requires --confirm {CONFIRM_TEXT}")
        run_real_ad2_timing_check(args.device_index, args.pre_trigger_wait_s, args.duration_s)
        return 0
    if args.real_ad2_labview_acoustic_short:
        if args.confirm != CONFIRM_TEXT:
            raise SystemExit(f"This mode requires --confirm {CONFIRM_TEXT}")
        if not args.acknowledge_timing_uncertain:
            raise SystemExit(TIMING_UNCERTAIN_REFUSAL)
        run_real_ad2_labview_acoustic_short(args.device_index, args.duration_s)
        return 0
    if args.real_camera_real_ad2_low_risk:
        if args.confirm != CONFIRM_TEXT:
            raise SystemExit(f"This mode requires --confirm {CONFIRM_TEXT}")
        run_real_camera_real_ad2_low_risk(
            args.output_dir,
            args.frames,
            args.exposure_ms,
            args.preset,
            args.apply_roi,
            args.device_index,
        )
        return 0
    if args.real_camera_real_ad2_acoustic_short:
        if args.confirm != CONFIRM_TEXT:
            raise SystemExit(f"This mode requires --confirm {CONFIRM_TEXT}")
        if not args.acknowledge_timing_uncertain:
            raise SystemExit(TIMING_UNCERTAIN_REFUSAL)
        run_real_camera_real_ad2_acoustic_short(
            args.output_dir,
            args.frames,
            args.exposure_ms,
            args.preset,
            args.apply_roi,
            args.device_index,
            args.duration_s,
        )
        return 0
    if args.real_full_workflow_short:
        if args.confirm != CONFIRM_TEXT:
            raise SystemExit(f"This mode requires --confirm {CONFIRM_TEXT}")
        if not args.acknowledge_timing_uncertain:
            raise SystemExit(TIMING_UNCERTAIN_REFUSAL)
        if not args.acknowledge_pump_valve_real:
            raise SystemExit(PUMP_VALVE_REAL_REFUSAL)
        if args.valve_port is None:
            raise SystemExit("This mode requires explicit --valve-port COM5 or COM6")
        if args.flush_enabled and not args.acknowledge_pump_valve_real:
            raise SystemExit(PUMP_VALVE_REAL_REFUSAL)
        run_real_full_workflow_short(
            args.output_dir,
            args.frames,
            args.exposure_ms,
            args.preset,
            args.apply_roi,
            args.valve_port,
            args.flush_enabled,
            args.device_index,
            args.duration_s,
        )
        return 0
    if args.real_camera_only:
        require_confirmation_if_needed(plan, args.confirm)
        run_real_camera_only(args.output_dir, args.frames, args.exposure_ms, args.preset, args.apply_roi)
        return 0

    print_plan(plan, args.output_dir, settings)
    if args.ad2_plan:
        print_ad2_labview_candidate(settings)
    if args.ad2_timing_plan:
        print_ad2_timing_check_plan(args.pre_trigger_wait_s, args.duration_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
