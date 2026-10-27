"""Read-only facts a queued definition states plainly: frames, requested timing, temperature strategy.

The queue page shows what Start will run, so these come from the compiled definition itself, whatever
entry created or last edited it (simple form or experiment builder). Nothing is calculated beyond
frames / FPS; a value the definition does not state as a plain number is left out (None) rather than
guessed, and a definition with several different acquisition blocks gives no per-experiment facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanFacts:
    frames: int | None = None
    camera_fps: float | None = None
    camera_start_s: float | None = None
    sound_start_s: float | None = None
    sound_run_s: float | None = None
    laser_start_s: float | None = None
    laser_run_s: float | None = None
    temperature_strategy: str | None = None  # None: no temperature program in the definition
    uniform: bool = True  # False: several acquisition blocks, so no single per-experiment timing


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _walk(steps, found: dict[str, list]) -> None:
    for index, step in enumerate(steps):
        kind = step.get("type")
        if kind == "experiment":
            found["experiments"].append(step)
        elif kind in {"tec_set", "tec_wait_stable"}:
            following = steps[index + 1] if index + 1 < len(steps) else None
            found[kind].append((step, following))
        if "steps" in step:
            _walk(step["steps"], found)
        for branch in step.get("branches", ()):
            _walk(branch, found)


def plan_facts(steps) -> PlanFacts:
    """Facts from a definition's step tree (`Expansion.steps`)."""
    found: dict[str, list] = {"experiments": [], "tec_set": [], "tec_wait_stable": []}
    _walk(list(steps), found)

    strategy = None
    if found["tec_wait_stable"]:
        args, following = found["tec_wait_stable"][0]
        args = args.get("args", {})
        hold = _number(following["args"].get("seconds")) if following and following.get("type") == "wait" else None
        tolerance, settle, maximum = (_number(args.get(key)) for key in ("tolerance_c", "min_settle_s", "max_wait_s"))
        strategy = ("Temperature strategy: wait for stability"
                    + (f" (±{tolerance:g}°C, settled {settle:g}s, max wait {maximum:g}s)"
                       if None not in (tolerance, settle, maximum) else "")
                    + (f", then hold {hold:g}s" if hold is not None else ""))
    elif found["tec_set"]:
        _args, following = found["tec_set"][0]
        hold = _number(following["args"].get("seconds")) if following and following.get("type") == "wait" else None
        strategy = ("Temperature strategy: " + (f"fixed wait of {hold:g}s, " if hold is not None else "")
                    + "no stability check")

    if len(found["experiments"]) != 1:
        return PlanFacts(temperature_strategy=strategy, uniform=False)
    frames = fps = camera_start = sound_start = sound_run = laser_start = laser_run = None
    for step in found["experiments"][0].get("steps", ()):
        args = step.get("args", {})
        if step.get("type") == "camera_configure":
            frames = args.get("frame_count") if isinstance(args.get("frame_count"), int) else None
        elif step.get("type") == "ad2_configure":
            ultrasound, laser, dio = args.get("ultrasound", {}), args.get("laser", {}), args.get("dio", {})
            sound_start, sound_run = _number(ultrasound.get("start_s")), _number(ultrasound.get("run_s"))
            laser_start, laser_run = _number(laser.get("start_s")), _number(laser.get("run_s"))
            fps, camera_start = _number(dio.get("frame_rate_hz")), _number(dio.get("camera_delay_s"))
            if frames is None and isinstance(dio.get("frame_count"), int):
                frames = dio["frame_count"]
    return PlanFacts(frames, fps, camera_start, sound_start, sound_run, laser_start, laser_run, strategy)
