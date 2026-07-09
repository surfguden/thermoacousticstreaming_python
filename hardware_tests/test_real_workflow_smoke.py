from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
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
AD2_LOW_RISK_CHANNEL = 0
AD2_LOW_RISK_FREQUENCY_HZ = 1000.0
AD2_LOW_RISK_AMPLITUDE_V = 0.1
AD2_LOW_RISK_OFFSET_V = 0.0
AD2_LOW_RISK_DURATION_S = 0.5


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


def low_risk_wfg_config() -> WfgConfig:
    return WfgConfig(
        running=True,
        channels=[
            WfgChannelConfig(
                channel_index=AD2_LOW_RISK_CHANNEL,
                carrier=CarrierSettings(
                    frequency_hz=AD2_LOW_RISK_FREQUENCY_HZ,
                    amplitude_v=AD2_LOW_RISK_AMPLITUDE_V,
                    offset_v=AD2_LOW_RISK_OFFSET_V,
                    symmetry_percent=50.0,
                    phase_deg=0.0,
                    function=WaveformFunction.SINE,
                    enable=True,
                ),
                trigger=TriggerSettings(
                    sec_run=AD2_LOW_RISK_DURATION_S,
                    sec_wait=0.0,
                    repeat_count=1,
                    repeat_trigger=False,
                ),
            )
        ],
        synchronize_state="Independent",
    )


def print_low_risk_ad2_output_parameters() -> None:
    print_step("real AD2 low-risk output parameters")
    print_value("channel", AD2_LOW_RISK_CHANNEL)
    print_value("frequency_hz", AD2_LOW_RISK_FREQUENCY_HZ)
    print_value("amplitude_v", AD2_LOW_RISK_AMPLITUDE_V)
    print_value("offset_v", AD2_LOW_RISK_OFFSET_V)
    print_value("function", "Sine")
    print_value("duration_s", AD2_LOW_RISK_DURATION_S)
    print_value("repeat_count", 1)
    print_value("LabVIEW acoustic output", "not used: no 1.975 MHz, 2.0 V, 60 s output in this mode")


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
    print_value("AD2", "simulated")
    print_value("pump", "simulated/disabled; no Qmix backend")
    print_value("valve", "simulated/disabled; no serial backend")
    print_value("Z-stage", "disabled; no Prior COM7 or Thorlabs/APT motion")
    print_value("AD2 output", "not real; SimulatedAD2Sdk only")
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
        "--real-camera-only",
        action="store_true",
        help="Run a real Hamamatsu camera-only acquisition. AD2/pump/valve are simulated and Z-stage is disabled.",
    )
    parser.add_argument("--preset", choices=[LABVIEW_SCREENSHOT_PRESET_NAME], default=None)
    parser.add_argument("--ad2-plan", action="store_true", help="Also print LabVIEW screenshot AD2 candidate parameters in plan-only mode.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "hardware_tests" / "_smoke_output")
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--exposure-ms", type=float, default=None)
    parser.add_argument("--device-index", type=int, default=0, help="WaveForms device index for real AD2 smoke modes. Default: 0.")
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
    if args.real_camera_only:
        require_confirmation_if_needed(plan, args.confirm)
        run_real_camera_only(args.output_dir, args.frames, args.exposure_ms, args.preset, args.apply_roi)
        return 0

    print_plan(plan, args.output_dir, settings)
    if args.ad2_plan:
        print_ad2_labview_candidate(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
