from __future__ import annotations

from ..domain import (
    CameraConfig,
    CaptureSnapshot,
    ConfigureCamera,
    ConfigureWaveform,
    ConnectDevice,
    DeviceId,
    DisconnectDevice,
    ExperimentPlan,
    ExperimentStep,
    StopWaveform,
    WaveformConfig,
)


def simulation_demo_plan() -> ExperimentPlan:
    """Small offline plan used to demonstrate application-owned sequencing."""
    return ExperimentPlan(
        "Simulation demonstration",
        (
            ExperimentStep(ConnectDevice(DeviceId.AD2), label="Connect waveform generator"),
            ExperimentStep(ConnectDevice(DeviceId.CAMERA), label="Connect camera"),
            ExperimentStep(
                ConfigureWaveform(WaveformConfig(frequency_hz=1_000_000, amplitude_v=1.0)),
                delay_after_s=0.2,
                label="Configure waveform",
            ),
            ExperimentStep(
                ConfigureCamera(CameraConfig(exposure_ms=1.0, frame_count=1)),
                delay_after_s=0.2,
                label="Configure camera",
            ),
            ExperimentStep(CaptureSnapshot(), label="Take snapshot"),
            ExperimentStep(StopWaveform(), label="Ensure waveform stopped"),
            ExperimentStep(DisconnectDevice(DeviceId.CAMERA), label="Disconnect camera"),
            ExperimentStep(DisconnectDevice(DeviceId.AD2), label="Disconnect waveform generator"),
        ),
    )
