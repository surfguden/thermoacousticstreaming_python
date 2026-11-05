"""Read-only facts a queued definition states plainly: frames, requested timing, temperature strategy.

The queue page shows what Start will run, so these come from the compiled definition itself, whatever
entry created or last edited it (simple form or experiment builder). Nothing is calculated beyond
frames / FPS. A value the definition does not state as a plain number is left out (None); an output
the definition disables is reported as disabled, not as a duration; and a definition that is not one
uniform acquisition block (several blocks, several configure steps, different temperature blocks) gives
no single summary and says why in `note` instead of presenting its first block as the whole series.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanFacts:
    frames: int | None = None
    camera_fps: float | None = None
    camera_start_s: float | None = None
    sound_enabled: bool | None = None  # None: the definition does not say
    sound_start_s: float | None = None
    sound_run_s: float | None = None
    laser_enabled: bool | None = None
    laser_start_s: float | None = None
    laser_run_s: float | None = None
    temperature_strategy: str | None = None  # None: no temperature program in the definition
    uniform: bool = True  # False: no single per-experiment summary (see note)
    note: str = ""
    # In-experiment frequency sweep as the ultrasound step states it: None when there is no single AD2
    # step to read; the period is None when the definition does not give it as a plain number.
    sweep_enabled: bool | None = None
    sweep_period_ms: float | None = None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _walk(steps, found: dict[str, list]) -> None:
    for index, step in enumerate(steps):
        kind = step.get("type")
        following = steps[index + 1] if index + 1 < len(steps) else None
        if kind == "experiment":
            found["experiments"].append(step)
        elif kind == "tec_wait_stable":
            found["tec_wait_stable"].append((step, following))
        elif kind == "tec_set" and not (following and following.get("type") == "tec_wait_stable"):
            found["tec_fixed"].append((step, following))
        if "steps" in step:
            _walk(step["steps"], found)
        for branch in step.get("branches", ()):
            _walk(branch, found)


def _hold(following) -> float | None:
    return _number(following["args"].get("seconds")) if following and following.get("type") == "wait" else None


def _strategies(found: dict[str, list]) -> set[str]:
    described = set()
    for step, following in found["tec_wait_stable"]:
        args = step.get("args", {})
        tolerance, settle, maximum = (_number(args.get(key)) for key in ("tolerance_c", "min_settle_s", "max_wait_s"))
        hold = _hold(following)
        described.add("Temperature strategy: wait for stability"
                      + (f" (±{tolerance:g}°C, settled {settle:g}s, max wait {maximum:g}s)"
                         if None not in (tolerance, settle, maximum) else "")
                      + (f", then hold {hold:g}s" if hold is not None else ""))
    for _step, following in found["tec_fixed"]:
        hold = _hold(following)
        described.add("Temperature strategy: " + (f"fixed wait of {hold:g}s, " if hold is not None else "")
                      + "no stability check")
    return described


def plan_facts(steps) -> PlanFacts:
    """Facts from a definition's step tree (`Expansion.steps`)."""
    found: dict[str, list] = {"experiments": [], "tec_wait_stable": [], "tec_fixed": []}
    _walk(list(steps), found)
    described = _strategies(found)
    strategy = None
    notes = []
    if len(described) == 1:
        strategy = next(iter(described))
    elif len(described) > 1:
        strategy = "Temperature strategy: differs between temperature blocks (not summarised)"
        notes.append("different temperature strategies")

    blocks = found["experiments"]
    if not blocks:
        return PlanFacts(temperature_strategy=strategy, uniform=False,
                         note="; ".join(["the definition has no acquisition blocks", *notes]))
    # A scanned series has one block per experiment; they only differ in resolved values (frequency, exposure...),
    # which are not facts of this summary. The summary is given when every block states the same facts.
    results = [_block_facts(block) for block in blocks]
    first = results[0]
    if isinstance(first, str):
        return PlanFacts(temperature_strategy=strategy, uniform=False, note=first)
    if any(result != first for result in results):
        return PlanFacts(temperature_strategy=strategy, uniform=False,
                         note="; ".join([f"the definition has {len(blocks)} acquisition blocks that are not alike", *notes]))
    return PlanFacts(*first[:9], strategy, True, "; ".join(notes), *first[9:])


def _block_facts(block: dict[str, Any]):
    """The facts one acquisition block states, as a tuple (frames, fps, camera_start, sound_enabled, sound_start,
    sound_run, laser_enabled, laser_start, laser_run, sweep_enabled, sweep_period); a string says why it has none."""
    block_steps = block.get("steps", ())
    camera_steps = [s for s in block_steps if s.get("type") == "camera_configure"]
    ad2_steps = [s for s in block_steps if s.get("type") == "ad2_configure"]
    if len(camera_steps) > 1 or len(ad2_steps) > 1:
        return "the acquisition block configures the camera or AD2 more than once"
    frames = fps = camera_start = None
    sound_enabled = laser_enabled = None
    sound_start = sound_run = laser_start = laser_run = None
    sweep_enabled = sweep_period = None
    if camera_steps:
        value = camera_steps[0].get("args", {}).get("frame_count")
        frames = value if isinstance(value, int) and not isinstance(value, bool) else None
    if ad2_steps:
        args = ad2_steps[0].get("args", {})
        ultrasound, laser, dio = args.get("ultrasound", {}), args.get("laser", {}), args.get("dio", {})
        sound_enabled, laser_enabled = _flag(ultrasound.get("enabled")), _flag(laser.get("enabled"))
        sound_start, sound_run = _number(ultrasound.get("start_s")), _number(ultrasound.get("run_s"))
        if sound_enabled is not False and ultrasound:
            sweep_enabled = "sweep_width_hz" in ultrasound
            sweep_period = _number(ultrasound.get("sweep_period_ms")) if sweep_enabled else None
        laser_start, laser_run = _number(laser.get("start_s")), _number(laser.get("run_s"))
        fps, camera_start = _number(dio.get("frame_rate_hz")), _number(dio.get("camera_delay_s"))
        if frames is None and isinstance(dio.get("frame_count"), int):
            frames = dio["frame_count"]
    return (frames, fps, camera_start, sound_enabled, sound_start, sound_run, laser_enabled, laser_start, laser_run,
            sweep_enabled, sweep_period)
