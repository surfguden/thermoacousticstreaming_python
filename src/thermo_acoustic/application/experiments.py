"""Portable, declarative experiment definitions and deterministic expansion.

This module deliberately has no device imports or executable expressions.  A
definition is data, not a program supplied by the JSON author.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import json
import math
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = 1
ACTION_RESOURCES = {
    "flush": frozenset({"pump", "valve"}),
    "wait": frozenset(),
    "tec_set": frozenset({"tec"}),
    "tec_wait_stable": frozenset({"tec"}),
    "stage_move": frozenset({"stage"}),
    "ad2_configure": frozenset({"ad2"}),
    "ad2_arm": frozenset({"ad2"}),
    "camera_configure": frozenset({"camera"}),
    "camera_arm": frozenset({"camera"}),
    "pc_trigger": frozenset({"ad2"}),
    "await_frames": frozenset({"camera"}),
    "wait_outputs": frozenset({"ad2"}),
    "save_frames": frozenset({"file"}),
}
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_PATH_TOKEN = re.compile(r"[^A-Za-z0-9_.=-]+")


@dataclass(frozen=True)
class PlannedExperiment:
    experiment_id: str
    parameters: dict[str, Any]
    repeat_index: int
    relative_path: str
    steps: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Expansion:
    definition: dict[str, Any]
    steps: tuple[dict[str, Any], ...]
    experiments: tuple[PlannedExperiment, ...]


def load_definition(path: str | Path) -> dict[str, Any]:
    def reject_constant(token: str) -> Any:
        raise ValueError(f"Non-finite JSON number is not allowed: {token}")
    with Path(path).open("r", encoding="utf-8") as stream:
        value = json.load(stream, parse_constant=reject_constant)
    validate_definition(value)
    return value


def save_definition(path: str | Path, definition: dict[str, Any]) -> None:
    validate_definition(definition)
    target = Path(path)
    with target.open("w", encoding="utf-8") as stream:
        json.dump(definition, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be at least {minimum:g}")
    return float(value)


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _keys(value: dict, allowed: set[str], required: set[str], label: str) -> None:
    extra = set(value) - allowed
    missing = required - set(value)
    if extra or missing:
        raise ValueError(f"{label}: unknown {sorted(extra)}; missing {sorted(missing)}")


def _values(spec: Any, label: str) -> tuple[Any, ...]:
    if isinstance(spec, list):
        if not spec:
            raise ValueError(f"{label} must not be empty")
        values = tuple(spec)
    elif isinstance(spec, dict):
        _keys(spec, {"start", "stop", "step"}, {"start", "stop", "step"}, label)
        start = _number(spec["start"], f"{label}.start")
        stop = _number(spec["stop"], f"{label}.stop")
        step = _number(spec["step"], f"{label}.step")
        if step == 0 or (stop - start) * step < 0:
            raise ValueError(f"{label}.step must advance towards stop")
        count = math.floor((stop - start) / step + 1e-10) + 1
        if not 1 <= count <= 100_000:
            raise ValueError(f"{label} range has invalid or excessive length")
        values = tuple(start + i * step for i in range(count))
    else:
        raise ValueError(f"{label} must be a nonempty list or numeric range")
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError(f"{label} values must be strings or finite numbers")
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError(f"{label} values must be finite")
    return values


def _resolve(value: Any, parameters: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        if "$param" in value:
            if set(value) != {"$param"} or value["$param"] not in parameters:
                raise ValueError(f"Unknown or malformed parameter reference: {value!r}")
            return parameters[value["$param"]]
        return {key: _resolve(item, parameters) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, parameters) for item in value]
    return value


def _action(step: dict[str, Any]) -> None:
    kind = step["type"]
    if kind not in ACTION_RESOURCES:
        raise ValueError(f"Unsupported experiment action: {kind!r}")
    _keys(step, {"type", "args"}, {"type", "args"}, kind)
    args = step["args"]
    if not isinstance(args, dict):
        raise ValueError(f"{kind}.args must be an object")
    fields = {
        "flush": ({"unit_index", "volume_ml", "flow_ul_min", "wait_after_s"}, {"unit_index", "volume_ml", "flow_ul_min"}),
        "wait": ({"seconds"}, {"seconds"}),
        "tec_set": ({"target_temperature_c", "channels"}, {"target_temperature_c"}),
        "tec_wait_stable": ({"target_temperature_c", "tolerance_c", "min_settle_s", "max_wait_s", "channels"}, {"target_temperature_c", "tolerance_c", "min_settle_s", "max_wait_s"}),
        "stage_move": ({"position_um"}, {"position_um"}),
        "ad2_configure": ({"ultrasound", "laser", "dio", "output_timeout_s"}, {"ultrasound", "laser", "dio", "output_timeout_s"}),
        "ad2_arm": (set(), set()),
        "camera_configure": ({"frame_count", "exposure_ms", "global_exposure", "frame_timeout_s"}, {"frame_count", "exposure_ms", "global_exposure"}),
        "camera_arm": (set(), set()),
        "pc_trigger": (set(), set()),
        "await_frames": (set(), set()),
        "wait_outputs": (set(), set()),
        "save_frames": (set(), set()),
    }[kind]
    _keys(args, *fields, kind)
    if kind in {"tec_set", "tec_wait_stable"}:
        channels = args.get("channels")
        if channels is not None:
            if not isinstance(channels, list) or not channels:
                raise ValueError("TEC channels must be a nonempty list")
            normalized = [_integer(channel, "TEC channel", minimum=1) for channel in channels]
            if len(set(normalized)) != len(normalized):
                raise ValueError("TEC channels must be unique")
        targets = args["target_temperature_c"]
        if isinstance(targets, dict):
            if not targets:
                raise ValueError("TEC target map must not be empty")
            for channel, target in targets.items():
                if not isinstance(channel, str) or not channel.isdigit() or str(int(channel)) != channel:
                    raise ValueError("TEC target keys must be canonical channel numbers as strings")
                _integer(int(channel), "TEC channel", minimum=1)
                _number(target, "TEC target_temperature_c")
        else:
            _number(targets, "TEC target_temperature_c")
    if kind == "flush":
        _integer(args["unit_index"], "flush.unit_index")
        _number(args["volume_ml"], "flush.volume_ml", minimum=1e-12)
        _number(args["flow_ul_min"], "flush.flow_ul_min", minimum=1e-12)
        delay = _number(args.get("wait_after_s", 0), "flush.wait_after_s")
        if not 0 <= delay <= 100:
            raise ValueError("flush.wait_after_s must be within 0..100")
    elif kind == "wait":
        _number(args["seconds"], "wait.seconds", minimum=0)
    elif kind == "camera_configure":
        _integer(args["frame_count"], "camera.frame_count", minimum=1)
        _number(args["exposure_ms"], "camera.exposure_ms", minimum=0)
        if not isinstance(args["global_exposure"], bool):
            raise ValueError("camera.global_exposure must be boolean")
        _number(args.get("frame_timeout_s", 30), "camera.frame_timeout_s", minimum=1e-12)
    elif kind == "stage_move":
        _number(args["position_um"], "stage.position_um")
    elif kind == "tec_wait_stable":
        _number(args["tolerance_c"], "tec tolerance_c", minimum=0)
        _number(args["min_settle_s"], "tec min_settle_s", minimum=0)
        _number(args["max_wait_s"], "tec max_wait_s", minimum=1e-12)
    elif kind == "ad2_configure":
        _number(args["output_timeout_s"], "ad2.output_timeout_s", minimum=1e-12)
        dio = args["dio"]
        if not isinstance(dio, dict):
            raise ValueError("ad2.dio must be an object")
        _keys(dio, {"frame_rate_hz", "camera_delay_s", "frame_count"},
              {"frame_rate_hz", "camera_delay_s", "frame_count"}, "ad2.dio")
        _number(dio["frame_rate_hz"], "ad2.dio.frame_rate_hz", minimum=1e-12)
        _number(dio["camera_delay_s"], "ad2.dio.camera_delay_s", minimum=0)
        _integer(dio["frame_count"], "ad2.dio.frame_count", minimum=1)
        for output in ("ultrasound", "laser"):
            item = args[output]
            if not isinstance(item, dict):
                raise ValueError(f"ad2.{output} must be an object")
            fields = ({"enabled", "start_s", "run_s", "frequency_hz", "amplitude_v", "offset_v"}
                      if output == "ultrasound" else
                      {"enabled", "start_s", "run_s", "on_voltage_v"})
            _keys(item, fields, fields, f"ad2.{output}")
            if not isinstance(item["enabled"], bool):
                raise ValueError(f"ad2.{output}.enabled must be boolean")
            for field in ("start_s", "run_s"):
                _number(item[field], f"ad2.{output}.{field}", minimum=0)
            if output == "ultrasound":
                _number(item["frequency_hz"], "ad2.ultrasound.frequency_hz", minimum=1e-12)
                _number(item["amplitude_v"], "ad2.ultrasound.amplitude_v", minimum=0)
                _number(item["offset_v"], "ad2.ultrasound.offset_v")
            else:
                _number(item["on_voltage_v"], "ad2.laser.on_voltage_v")
            if item["enabled"] and item["run_s"] <= 0:
                raise ValueError(f"ad2.{output} requires a finite positive run_s")
        expected_window = dio["camera_delay_s"] + dio["frame_count"] / dio["frame_rate_hz"]
        for output in ("ultrasound", "laser"):
            item = args[output]
            if item["enabled"]:
                expected_window = max(expected_window, item["start_s"] + item["run_s"])
        if args["output_timeout_s"] <= expected_window:
            raise ValueError("ad2.output_timeout_s must exceed every finite output window")


def _leaf_name(value: Any) -> str:
    token = _PATH_TOKEN.sub("_", str(value)).strip("._")[:64]
    return token or "value"


def validate_definition(value: Any) -> Expansion:
    if not isinstance(value, dict):
        raise ValueError("Experiment definition must be a JSON object")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Definition must contain only finite JSON data: {exc}") from exc
    _keys(value, {"version", "name", "steps", "preflight", "tiff_format"},
          {"version", "name", "steps"}, "definition")
    if value["version"] != SCHEMA_VERSION:
        raise ValueError(f"Unsupported experiment definition version: {value['version']!r}")
    if not isinstance(value["name"], str) or not _NAME.fullmatch(value["name"]):
        raise ValueError("Definition name must start with a letter and contain only letters, digits or underscore")
    if not isinstance(value.get("preflight", False), bool):
        raise ValueError("preflight must be boolean")
    if value.get("tiff_format", "frames") not in ("frames", "stacked"):
        raise ValueError("tiff_format must be frames or stacked")
    if not isinstance(value["steps"], list) or not value["steps"]:
        raise ValueError("Definition steps must be a nonempty list")
    planned: list[PlannedExperiment] = []
    expanded: list[dict[str, Any]] = []
    max_nodes = 100_000

    def walk(steps: list, parameters: dict[str, Any], repeat: int, path: tuple[str, ...],
             *, inside_experiment: bool = False, inside_parallel: bool = False) -> list[dict[str, Any]]:
        if not isinstance(steps, list):
            raise ValueError("Block steps must be a list")
        result: list[dict[str, Any]] = []
        for node in steps:
            if not isinstance(node, dict) or not isinstance(node.get("type"), str):
                raise ValueError("Every step needs a type")
            kind = node["type"]
            if inside_parallel and kind not in {"save_frames", "wait_outputs", "flush", "wait"}:
                raise ValueError(f"{kind} is not permitted inside a parallel branch")
            if not inside_experiment and kind in {
                "ad2_configure", "ad2_arm", "camera_configure", "camera_arm",
                "pc_trigger", "await_frames", "wait_outputs", "save_frames",
            }:
                raise ValueError(f"{kind} requires an experiment block")
            if kind == "sweep":
                if inside_experiment:
                    raise ValueError("Place sweeps outside experiment blocks")
                _keys(node, {"type", "parameters", "steps"}, {"type", "parameters", "steps"}, "sweep")
                specs = node["parameters"]
                if not isinstance(specs, dict) or not specs:
                    raise ValueError("sweep.parameters must be a nonempty object")
                names = tuple(specs)
                if any(not _NAME.fullmatch(name) or name in parameters for name in names):
                    raise ValueError("Invalid or shadowed sweep parameter name")
                choices = tuple(_values(specs[name], name) for name in names)
                if math.prod(len(items) for items in choices) > max_nodes:
                    raise ValueError("Sweep expands to too many parameter combinations")
                combinations = product(*choices)
                for combination in combinations:
                    local = dict(zip(names, combination))
                    segments = tuple(f"{name}={_leaf_name(item)}" for name, item in local.items())
                    result.extend(walk(node["steps"], parameters | local, repeat, path + segments))
                    if len(result) + len(planned) > max_nodes:
                        raise ValueError("Experiment plan is too large")
            elif kind == "repeat":
                if inside_experiment:
                    raise ValueError("Place repeats outside experiment blocks")
                _keys(node, {"type", "count", "steps"}, {"type", "count", "steps"}, "repeat")
                count = _integer(_resolve(node["count"], parameters), "repeat.count", minimum=1)
                if count > max_nodes:
                    raise ValueError("Excessive repeat count")
                for index in range(1, count + 1):
                    result.extend(walk(node["steps"], parameters, index, path))
                    if len(result) + len(planned) > max_nodes:
                        raise ValueError("Experiment plan is too large")
            elif kind == "experiment":
                if inside_experiment:
                    raise ValueError("Experiment blocks cannot be nested")
                _keys(node, {"type", "steps"}, {"type", "steps"}, "experiment")
                body = walk(node["steps"], parameters, repeat, path, inside_experiment=True)
                _validate_experiment(body)
                experiment_id = f"experiment_{len(planned) + 1:06d}"
                folder = "/".join(path + (f"repeat_{repeat:04d}",))
                if any(item.relative_path == folder for item in planned):
                    folder = "/".join(path + (experiment_id, f"repeat_{repeat:04d}"))
                if len(folder) > 180:
                    raise ValueError("Expanded parameter folder path is too long")
                item = PlannedExperiment(experiment_id, dict(parameters), repeat, folder, tuple(body))
                planned.append(item)
                result.append({"type": "experiment", "experiment_id": experiment_id,
                               "steps": body, "parameters": dict(parameters), "relative_path": folder})
            elif kind == "parallel":
                if not inside_experiment:
                    raise ValueError("Parallel blocks are only permitted inside an experiment")
                _keys(node, {"type", "branches"}, {"type", "branches"}, "parallel")
                branches = node["branches"]
                if not isinstance(branches, list) or len(branches) < 2:
                    raise ValueError("parallel requires at least two branches")
                resolved = [walk(branch, parameters, repeat, path,
                                 inside_experiment=True, inside_parallel=True)
                            for branch in branches]
                resources = [_resources(branch) for branch in resolved]
                for i in range(len(resources)):
                    for j in range(i + 1, len(resources)):
                        conflict = resources[i] & resources[j]
                        if conflict:
                            raise ValueError(f"parallel resource conflict: {', '.join(sorted(conflict))}")
                result.append({"type": "parallel", "branches": resolved})
            else:
                resolved = _resolve(node, parameters)
                _action(resolved)
                result.append(resolved)
            if len(result) + len(planned) > max_nodes:
                raise ValueError("Experiment plan is too large")
        return result

    expanded = walk(value["steps"], {}, 1, ())
    if not planned:
        raise ValueError("Definition must contain at least one experiment")
    return Expansion(value, tuple(expanded), tuple(planned))


def _resources(steps: list[dict[str, Any]]) -> frozenset[str]:
    result: set[str] = set()
    for step in steps:
        if step["type"] == "parallel":
            for branch in step["branches"]:
                result.update(_resources(branch))
        elif step["type"] == "experiment":
            result.update(_resources(step["steps"]))
        else:
            result.update(ACTION_RESOURCES[step["type"]])
    return frozenset(result)


def _validate_experiment(steps: list[dict[str, Any]]) -> None:
    # The acquisition arm and trigger sequence is necessarily serial.  Saving
    # and output-completion/flush may be parallel only after frames are copied.
    sequential: list[str] = []
    parallel: list[dict[str, Any]] = []
    for step in steps:
        if step["type"] == "parallel":
            parallel.append(step)
        else:
            sequential.append(step["type"])
    for kind in ("camera_configure", "ad2_configure", "camera_arm", "ad2_arm",
                 "pc_trigger", "await_frames"):
        if sequential.count(kind) != 1:
            raise ValueError(f"Experiment requires exactly one {kind} step")
    order = ("camera_configure", "ad2_configure", "camera_arm", "ad2_arm",
             "pc_trigger", "await_frames")
    if any(sequential.index(a) > sequential.index(b) for a, b in zip(order, order[1:])):
        raise ValueError("Configure and arm camera/AD2 before the single PC trigger; then await frames")
    camera = next(item["args"] for item in steps if item["type"] == "camera_configure")
    ad2 = next(item["args"] for item in steps if item["type"] == "ad2_configure")
    if camera["frame_count"] != ad2["dio"]["frame_count"]:
        raise ValueError("Camera frame_count and DIO0 frame_count must match")
    if camera["exposure_ms"] / 1000 >= 1 / ad2["dio"]["frame_rate_hz"]:
        raise ValueError("Camera exposure must fit within the requested frame interval")
    flat = sequential + [item["type"] for block in parallel for branch in block["branches"] for item in branch]
    if flat.count("save_frames") != 1:
        raise ValueError("Experiment requires exactly one save_frames step")
    if flat.count("wait_outputs") != 1:
        raise ValueError("Experiment requires exactly one wait_outputs step")
    frame_index = next(i for i, item in enumerate(steps) if item["type"] == "await_frames")
    arm_index = next(i for i, item in enumerate(steps) if item["type"] == "camera_arm")
    trigger_index = next(i for i, item in enumerate(steps) if item["type"] == "pc_trigger")
    for index, item in enumerate(steps):
        if item["type"] in {"tec_set", "tec_wait_stable", "stage_move"} and index >= arm_index:
            raise ValueError("TEC and stage positioning must finish before camera arming")
        if item["type"] == "wait" and trigger_index < index < frame_index:
            raise ValueError("Do not insert a software wait between PC trigger and frame collection")
        if item["type"] in {"save_frames", "wait_outputs", "flush"} and index <= frame_index:
            raise ValueError("Save and post-acquisition fluidics require completed frame collection")
    if "flush" in sequential:
        flush_index = next(i for i, item in enumerate(steps) if item["type"] == "flush")
        output_index = next((i for i, item in enumerate(steps) if item["type"] == "wait_outputs"), -1)
        if output_index < frame_index or output_index > flush_index:
            raise ValueError("Fluid movement requires wait_outputs first")
    for block in parallel:
        if steps.index(block) < frame_index:
            raise ValueError("Parallel saving may start only after await_frames")
        for branch in block["branches"]:
            types = [item["type"] for item in branch]
            if "flush" in types and ("wait_outputs" not in types or types.index("wait_outputs") > types.index("flush")):
                raise ValueError("Fluid movement requires wait_outputs in the same branch first")


def default_definition() -> dict[str, Any]:
    """Editable example; no device commands are sent by creating it."""
    return {
        "version": 1, "name": "example", "preflight": False, "tiff_format": "frames",
        "steps": [
            {"type": "flush", "args": {"unit_index": 0, "volume_ml": 0.1, "flow_ul_min": 500, "wait_after_s": 1}},
            {"type": "sweep", "parameters": {"frequency_hz": [2000000], "amplitude_v": [1.0]}, "steps": [
                {"type": "repeat", "count": 1, "steps": [{"type": "experiment", "steps": [
                    {"type": "camera_configure", "args": {"frame_count": 10, "exposure_ms": 1, "global_exposure": False}},
                    {"type": "ad2_configure", "args": {
                        "ultrasound": {"enabled": True, "start_s": 0, "run_s": 1, "frequency_hz": {"$param": "frequency_hz"}, "amplitude_v": {"$param": "amplitude_v"}, "offset_v": 0},
                        "laser": {"enabled": False, "start_s": 0, "run_s": 1, "on_voltage_v": 0},
                        "dio": {"frame_rate_hz": 10, "camera_delay_s": 0.1, "frame_count": 10},
                        "output_timeout_s": 10}},
                    {"type": "camera_arm", "args": {}}, {"type": "ad2_arm", "args": {}},
                    {"type": "pc_trigger", "args": {}}, {"type": "await_frames", "args": {}},
                    {"type": "parallel", "branches": [
                        [{"type": "save_frames", "args": {}}],
                        [{"type": "wait_outputs", "args": {}}, {"type": "flush", "args": {"unit_index": 0, "volume_ml": 0.1, "flow_ul_min": 500}}],
                    ]},
                ]}]},
            ]},
        ],
    }
