"""Which devices a runner phase involves, and what the phase means in plain words.

The phase strings are the runner's own constants (`ExperimentManager._run_action` and friends), so
this mapping only labels them for the run monitor; it starts, orders or checks nothing. An
unrecognised phase involves no device in the display and is shown as the runner wrote it.
"""

from __future__ import annotations

from ..domain.models import DeviceId

_PHASES: dict[str, tuple[frozenset[DeviceId], str]] = {
    "Configuring instruments": (frozenset({DeviceId.AD2, DeviceId.CAMERA}), "Setting up the instruments for this experiment."),
    "Configuring camera": (frozenset({DeviceId.CAMERA}), "Setting exposure, ROI and frame count on the camera."),
    "Configuring AD2": (frozenset({DeviceId.AD2}), "Setting the AD2 outputs and timing."),
    "Arming camera": (frozenset({DeviceId.CAMERA}), "The camera is being armed and waits for the trigger."),
    "Arming AD2": (frozenset({DeviceId.AD2}), "The AD2 is being armed and waits for the trigger."),
    "Triggering acquisition": (frozenset({DeviceId.AD2, DeviceId.CAMERA}), "The PC trigger is being sent."),
    "Acquiring frames": (frozenset({DeviceId.CAMERA, DeviceId.AD2}), "Frames are being collected while the outputs run."),
    "Waiting for AD2 outputs": (frozenset({DeviceId.AD2}), "Waiting for the AD2 outputs to finish."),
    "Saving frames": (frozenset(), "Images are being written to disk."),
    "Saving frames + waiting for outputs/flush": (
        frozenset({DeviceId.AD2, DeviceId.PUMP, DeviceId.VALVE}),
        "In parallel: images are written to disk, the AD2 outputs finish and the flush runs. "
        "Saved images do not yet mean the experiment is complete."),
    "Flushing": (frozenset({DeviceId.PUMP, DeviceId.VALVE}), "The pump flushes through the valve."),
    "Setting temperature": (frozenset({DeviceId.TEC}), "A temperature target is being applied."),
    "Waiting for temperature stabilization": (frozenset({DeviceId.TEC}), "Waiting for the controller to report the temperature stable."),
    "Moving Z-stage": (frozenset({DeviceId.Z_STAGE}), "The Z-stage is moving."),
    "Experiment completed": (frozenset(), "This experiment finished (images saved, outputs and flush done)."),
}


def devices_for_phase(phase: str | None) -> frozenset[DeviceId]:
    return _PHASES.get(phase or "", (frozenset(), ""))[0]


def describe_phase(phase: str | None) -> str:
    """Plain-words reading of a phase, or the phase itself when it is not one the runner names above."""
    return _PHASES.get(phase or "", (frozenset(), ""))[1] or (phase or "")
