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
    "Arming camera": (frozenset({DeviceId.CAMERA}), "The camera is being armed to wait for the trigger."),
    "Arming AD2": (frozenset({DeviceId.AD2}), "The AD2 is being armed to wait for the trigger."),
    "Triggering acquisition": (frozenset({DeviceId.AD2, DeviceId.CAMERA}), "The PC trigger is being sent."),
    "Acquiring frames": (frozenset({DeviceId.CAMERA, DeviceId.AD2}), "Waiting for the camera to deliver the requested frames after the trigger."),
    "Waiting for AD2 outputs": (frozenset({DeviceId.AD2}), "Waiting for the AD2 outputs to finish."),
    "Saving frames": (frozenset(), "Images are being written to disk."),
    "Saving frames + waiting for outputs/flush": (
        frozenset({DeviceId.AD2, DeviceId.PUMP, DeviceId.VALVE}),
        "Two paths run side by side: the images are written to disk; and the AD2 outputs are awaited, "
        "after which the flush follows. Saved images do not yet mean the experiment is complete."),
    "Flushing": (frozenset({DeviceId.PUMP, DeviceId.VALVE}), "The flush workflow is running on the pump and valve."),
    "Setting temperature": (frozenset({DeviceId.TEC}), "A temperature target is being applied."),
    "Checking temperature stability": (
        frozenset({DeviceId.TEC}),
        "Waiting until the TEC controller reports the temperature stable (within tolerance for the settle time) "
        "or the maximum wait ends."),
    "Holding after temperature stability": (
        frozenset(), "Stability was reported; now waiting the extra hold time before the next step."),
    "Fixed wait after setting temperature": (
        frozenset(), "Waiting the set time after applying the temperature. No stability check is made, so the "
        "temperature is not confirmed stable."),
    "Timed wait": (frozenset(), "Waiting for the set time; this wait does not check any device."),
    "Moving Z-stage": (
        frozenset({DeviceId.Z_STAGE}),
        "A Z-stage move command is being sent. The controller accepting it is not a confirmation that the "
        "stage has arrived."),
    "Experiment completed": (frozenset(), "This experiment finished (images saved, outputs and flush done)."),
}


def devices_for_phase(phase: str | None) -> frozenset[DeviceId]:
    return _PHASES.get(phase or "", (frozenset(), ""))[0]


def describe_phase(phase: str | None) -> str:
    """Plain-words reading of a phase, or the phase itself when it is not one the runner names above."""
    return _PHASES.get(phase or "", (frozenset(), ""))[1] or (phase or "")
