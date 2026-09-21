from __future__ import annotations

import shlex

from ..application.commands import (
    Ad2AnalogOutputIdle,
    Ad2ConfigureDigitalOutputArgs,
    Ad2ConfigureScopeArgs,
    Ad2ConfigureWaveformArgs,
    Ad2DigitalOutputType,
    Ad2ScopeChannelArgs,
    Ad2ScopeTriggerArgs,
    Ad2ScopeTriggerCondition,
    Ad2ScopeTriggerFilter,
    Ad2TriggerSettingsArgs,
    Ad2TriggerSource,
    Ad2WaveformChannelArgs,
    Ad2WaveformFunction,
    CameraMasterPulseMode,
    CameraMasterPulseSource,
    CameraConfigureExposureArgs,
    CameraConfigureRoiArgs,
    CameraConfigureSnapshotArgs,
    CameraConfigureSequenceArgs,
    CameraSequenceTriggerArgs,
    CameraTriggerActive,
    CameraTriggerPolarity,
    CameraTriggerSource,
    DeviceCommand,
    DeviceOperation,
    PumpSetFlowArgs,
    PumpConfigureFlowUnitArgs,
    PumpConfigureSyringeArgs,
    PumpFlowUnit,
    PumpSetFillLevelArgs,
    PumpMoveArgs,
    PumpReferenceMoveArgs,
    PumpSyringePreset,
    PumpUnitArgs,
    TecApplySetpointsArgs,
    TecReadStatusArgs,
    TecWaitStableArgs,
    ValveSetPositionArgs,
    ValveWaitReadyArgs,
    ZStageSetPositionArgs,
)
from ..domain.models import DeviceId


_DEVICES = {device.value: device for device in DeviceId}
_SYRINGE_PRESETS = {
    "bd-1ml": PumpSyringePreset.BD_1_ML,
    "bd-5ml": PumpSyringePreset.BD_5_ML,
    "bd-10ml": PumpSyringePreset.BD_10_ML,
}


def _options(words: list[str]) -> dict[str, str]:
    """Parse explicit --name VALUE pairs without introducing a second CLI parser."""
    if len(words) % 2 or any(not name.startswith("--") for name in words[::2]):
        raise ValueError("Options must be written as --name VALUE pairs")
    result = {name[2:].replace("-", "_"): value for name, value in zip(words[::2], words[1::2])}
    if len(result) != len(words) // 2:
        raise ValueError("Each option may be supplied only once")
    return result


def _bool(value: str) -> bool:
    normalized = value.lower()
    if normalized in {"true", "yes", "1", "on"}:
        return True
    if normalized in {"false", "no", "0", "off"}:
        return False
    raise ValueError(f"Expected boolean true/false, got {value!r}")


def _enum(enum_type, value: str):
    normalized = value.lower()
    for item in enum_type:
        if item.value.lower() == normalized or item.name.lower() == normalized:
            return item
    allowed = ", ".join(item.value for item in enum_type)
    raise ValueError(f"Invalid {enum_type.__name__}: {value!r}; allowed: {allowed}")


def _value(options: dict[str, str], name: str, default, converter):
    return converter(options[name]) if name in options else default


def _only_options(options: dict[str, str], *allowed: str) -> None:
    unknown = set(options) - set(allowed)
    if unknown:
        raise ValueError(f"Unknown option(s): {', '.join('--' + name.replace('_', '-') for name in sorted(unknown))}")


def _trigger(options: dict[str, str], prefix: str) -> Ad2TriggerSettingsArgs:
    prefix = f"{prefix}_" if prefix else ""
    return Ad2TriggerSettingsArgs(
        source=_value(options, f"{prefix}trigger_source", Ad2TriggerSource.NONE, lambda v: _enum(Ad2TriggerSource, v)),
        wait_s=_value(options, f"{prefix}trigger_wait_s", 0.0, float),
        run_s=_value(options, f"{prefix}trigger_run_s", 0.0, float),
        repeat_count=_value(options, f"{prefix}trigger_repeat_count", 0, int),
        repeat_trigger=_value(options, f"{prefix}trigger_repeat", False, _bool),
    )


def help_text() -> str:
    return """General:
  status | devices | connect DEVICE | disconnect DEVICE | abort DEVICE | safe-stop DEVICE | quit

AD2 (all option values use --name VALUE pairs):
  ad2 waveform configure --ch1-frequency-hz 2000 --ch1-amplitude-v 2 --ch2-enabled false
  ad2 waveform start|stop|trigger
  ad2 scope configure --sample-count 8192 --sample-frequency-hz 1000000 --channels 0 --ch1-range-v 5
  ad2 scope trigger|read|capture
  ad2 digital configure --channel 0 --clock-hz 500 --bits 1100
  ad2 digital start|stop|reset|trigger
  Legacy: ad2 configure-do CHANNEL FREQUENCY_HZ [BIT_PATTERN] | ad2 start-do|stop-do|reset-do

Pump:
  pump set-flow UL_MIN | pump stop | pump read-fill-level | pump read-status
  pump set-fill-level ML [UL_MIN] | pump configure-syringe bd-1ml|bd-5ml|bd-10ml
  pump configure-syringe custom DIAMETER_MM STROKE_MM | pump configure-flow-unit ul/min|ml/min|ul/s|ml/s
  pump recover-fault | pump refill [UL_MIN] | pump empty [UL_MIN] | pump reference-move
  Extended: pump refill|empty --flow-ul-min RATE --timeout-s SECONDS --poll-interval-s SECONDS
  Extended: pump reference move --timeout-s SECONDS --poll-interval-s SECONDS

Valve:
  valve set-position 1|2 | valve read-position | valve wait-ready
  valve wait ready --timeout-s SECONDS --poll-interval-s SECONDS

Camera:
  camera configure-snapshot [EXPOSURE_MS] | camera snapshot | camera read-timing
  camera configure-sequence FRAMES [EXPOSURE_MS] | camera sequence | camera capture stop
  camera set-exposure EXPOSURE_MS | camera set-roi X Y WIDTH HEIGHT
  Extended: camera snapshot configure --exposure-ms MS
  Extended: camera sequence configure --frames N [--trigger-enabled true ...]

TEC and Z-stage:
  tec set-temperature C | tec set temperatures --broadcast-c C | tec set temperatures --ch1-c C --ch2-c C
  tec read-status | tec wait-stable C TOLERANCE SETTLE_S MAX_WAIT_S | tec outputs-off
  z-stage check-closed-loop | z-stage enable-closed-loop | z-stage move UM | z-stage read-position"""


def parse_command(line: str, *, source: str = "console") -> DeviceCommand | str | None:
    words = shlex.split(line.strip())
    if not words:
        return None
    if words[0] in ("help", "status", "devices", "quit"):
        return words[0]
    if words[0] in ("connect", "disconnect") and len(words) == 2 and words[1] in _DEVICES:
        operation = (
            DeviceOperation.CONNECT if words[0] == "connect" else DeviceOperation.DISCONNECT
        )
        return DeviceCommand(_DEVICES[words[1]], operation, source=source)
    if words[0] == "abort" and len(words) == 2 and words[1] in _DEVICES:
        return DeviceCommand(
            _DEVICES[words[1]], DeviceOperation.ABORT_ACTIVE, source=source
        )
    if words[0] == "safe-stop" and len(words) == 2 and words[1] in _DEVICES:
        return DeviceCommand(_DEVICES[words[1]], DeviceOperation.SAFE_STOP, source=source)

    if words[:3] == ["ad2", "waveform", "configure"]:
        options = _options(words[3:])
        allowed = tuple(
            f"ch{channel}_{field}"
            for channel in (1, 2)
            for field in (
                "enabled", "function", "frequency_hz", "amplitude_v", "offset_v",
                "symmetry_percent", "phase_deg", "fm_enabled", "fm_function",
                "fm_frequency_hz", "fm_modulation_index_percent", "fm_offset_percent",
                "fm_symmetry_percent", "fm_phase_deg", "idle_state", "trigger_source",
                "trigger_wait_s", "trigger_run_s", "trigger_repeat_count", "trigger_repeat",
            )
        )
        _only_options(options, *allowed)
        channels = []
        for number in (1, 2):
            prefix = f"ch{number}"
            channels.append(Ad2WaveformChannelArgs(
                channel_index=number - 1,
                enabled=_value(options, f"{prefix}_enabled", number == 1, _bool),
                function=_value(options, f"{prefix}_function", Ad2WaveformFunction.SINE, lambda v: _enum(Ad2WaveformFunction, v)),
                frequency_hz=_value(options, f"{prefix}_frequency_hz", 1000.0, float),
                amplitude_v=_value(options, f"{prefix}_amplitude_v", 1.0, float),
                offset_v=_value(options, f"{prefix}_offset_v", 0.0, float),
                symmetry_percent=_value(options, f"{prefix}_symmetry_percent", 50.0, float),
                phase_deg=_value(options, f"{prefix}_phase_deg", 0.0, float),
                fm_enabled=_value(options, f"{prefix}_fm_enabled", False, _bool),
                fm_function=_value(options, f"{prefix}_fm_function", Ad2WaveformFunction.SINE, lambda v: _enum(Ad2WaveformFunction, v)),
                fm_frequency_hz=_value(options, f"{prefix}_fm_frequency_hz", 1000.0, float),
                fm_modulation_index_percent=_value(options, f"{prefix}_fm_modulation_index_percent", 0.0, float),
                fm_offset_percent=_value(options, f"{prefix}_fm_offset_percent", 0.0, float),
                fm_symmetry_percent=_value(options, f"{prefix}_fm_symmetry_percent", 50.0, float),
                fm_phase_deg=_value(options, f"{prefix}_fm_phase_deg", 0.0, float),
                idle_state=_value(options, f"{prefix}_idle_state", Ad2AnalogOutputIdle.INITIAL, lambda v: _enum(Ad2AnalogOutputIdle, v)),
                trigger=_trigger(options, prefix),
            ))
        return DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_WAVEFORM_CONFIGURE,
                             Ad2ConfigureWaveformArgs(channels=tuple(channels)), source=source)
    ad2_simple = {
        ("ad2", "waveform", "start"): DeviceOperation.AD2_WAVEFORM_START,
        ("ad2", "waveform", "stop"): DeviceOperation.AD2_WAVEFORM_STOP,
        ("ad2", "waveform", "trigger"): DeviceOperation.AD2_SOFTWARE_TRIGGER,
        ("ad2", "scope", "trigger"): DeviceOperation.AD2_SOFTWARE_TRIGGER,
        ("ad2", "scope", "read"): DeviceOperation.AD2_SCOPE_READ,
        ("ad2", "scope", "capture"): DeviceOperation.AD2_SCOPE_READ,
        ("ad2", "digital", "start"): DeviceOperation.AD2_DIGITAL_OUTPUT_START,
        ("ad2", "digital", "stop"): DeviceOperation.AD2_DIGITAL_OUTPUT_STOP,
        ("ad2", "digital", "reset"): DeviceOperation.AD2_DIGITAL_OUTPUT_RESET,
        ("ad2", "digital", "trigger"): DeviceOperation.AD2_SOFTWARE_TRIGGER,
    }
    if tuple(words) in ad2_simple:
        return DeviceCommand(DeviceId.AD2, ad2_simple[tuple(words)], source=source)
    if words[:3] == ["ad2", "scope", "configure"]:
        options = _options(words[3:])
        allowed = (
            "sample_count", "sample_frequency_hz", "pretrigger_samples", "timeout_s", "channels",
            "ch1_range_v", "ch1_offset_v", "ch2_range_v", "ch2_offset_v", "trigger_source",
            "trigger_channel", "trigger_condition", "trigger_filter", "trigger_level_v",
            "trigger_hysteresis_v", "trigger_holdoff_s", "trigger_auto_timeout_s",
        )
        _only_options(options, *allowed)
        indices = tuple(int(index) for index in options.get("channels", "0").split(","))
        if any(index not in (0, 1) for index in indices) or len(set(indices)) != len(indices):
            raise ValueError("--channels must be a unique comma-separated list drawn from 0,1")
        channels = tuple(Ad2ScopeChannelArgs(
            index,
            _value(options, f"ch{index + 1}_range_v", 5.0, float),
            _value(options, f"ch{index + 1}_offset_v", 0.0, float),
        ) for index in indices)
        trigger = Ad2ScopeTriggerArgs(
            source=_value(options, "trigger_source", Ad2TriggerSource.DETECTOR_ANALOG_IN, lambda v: _enum(Ad2TriggerSource, v)),
            channel_index=_value(options, "trigger_channel", 0, int),
            condition=_value(options, "trigger_condition", Ad2ScopeTriggerCondition.RISING_POSITIVE, lambda v: _enum(Ad2ScopeTriggerCondition, v)),
            filter=_value(options, "trigger_filter", Ad2ScopeTriggerFilter.DECIMATE, lambda v: _enum(Ad2ScopeTriggerFilter, v)),
            level_v=_value(options, "trigger_level_v", 0.0, float),
            hysteresis_v=_value(options, "trigger_hysteresis_v", 0.1, float),
            holdoff_s=_value(options, "trigger_holdoff_s", 0.0, float),
            auto_timeout_s=_value(options, "trigger_auto_timeout_s", 0.0, float),
        )
        return DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_SCOPE_CONFIGURE,
            Ad2ConfigureScopeArgs(
                sample_count=_value(options, "sample_count", 1000, int), channels=channels,
                sample_frequency_hz=_value(options, "sample_frequency_hz", 100_000_000.0, float),
                pretrigger_samples=_value(options, "pretrigger_samples", 0, int),
                timeout_s=_value(options, "timeout_s", 5.0, float), trigger=trigger,
            ), source=source)
    if words[:3] == ["ad2", "digital", "configure"]:
        options = _options(words[3:])
        allowed = ("channel", "enabled", "type", "clock_hz", "high_bits", "low_bits", "start_high", "bits", "frame_count", "trigger_source", "trigger_wait_s", "trigger_run_s", "trigger_repeat_count", "trigger_repeat")
        _only_options(options, *allowed)
        bits = tuple(int(bit) for bit in options.get("bits", ""))
        if any(bit not in (0, 1) for bit in bits):
            raise ValueError("--bits may contain only 0 and 1")
        return DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_CONFIGURE,
            Ad2ConfigureDigitalOutputArgs(
                channel_index=_value(options, "channel", 0, int),
                enabled=_value(options, "enabled", True, _bool),
                output_type=_value(options, "type", Ad2DigitalOutputType.PULSE, lambda v: _enum(Ad2DigitalOutputType, v)),
                clock_frequency_hz=float(options["clock_hz"]) if "clock_hz" in options else None,
                counter_high_bits=_value(options, "high_bits", 1, int),
                counter_low_bits=_value(options, "low_bits", 1, int),
                start_high=_value(options, "start_high", True, _bool), bits=bits,
                frame_count=int(options["frame_count"]) if "frame_count" in options else None,
                trigger=_trigger(options, ""),
            ), source=source)

    if words[:3] == ["camera", "snapshot", "configure"]:
        options = _options(words[3:])
        _only_options(options, "exposure_ms")
        exposure = float(options["exposure_ms"]) if "exposure_ms" in options else None
        return DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE,
                             CameraConfigureSnapshotArgs(exposure), source=source)
    if words[:3] == ["camera", "sequence", "configure"]:
        options = _options(words[3:])
        allowed = ("frames", "exposure_ms", "timeout_s", "poll_interval_s", "trigger_enabled",
                   "trigger_source", "trigger_polarity", "trigger_active", "trigger_times",
                   "trigger_delay_s", "masterpulse_mode", "masterpulse_source",
                   "masterpulse_interval_s", "masterpulse_burst_times", "global_exposure")
        _only_options(options, *allowed)
        if "frames" not in options:
            raise ValueError("camera sequence configure requires --frames COUNT")
        trigger_enabled = _value(options, "trigger_enabled", False, _bool)
        trigger = None
        if trigger_enabled:
            trigger = CameraSequenceTriggerArgs(
                source=_value(options, "trigger_source", CameraTriggerSource.INTERNAL, lambda v: _enum(CameraTriggerSource, v)),
                polarity=_value(options, "trigger_polarity", CameraTriggerPolarity.POSITIVE, lambda v: _enum(CameraTriggerPolarity, v)),
                active=_value(options, "trigger_active", CameraTriggerActive.EDGE, lambda v: _enum(CameraTriggerActive, v)),
                trigger_times=_value(options, "trigger_times", 1, int),
                delay_s=_value(options, "trigger_delay_s", 0.0, float),
                masterpulse_mode=_value(options, "masterpulse_mode", CameraMasterPulseMode.CONTINUOUS, lambda v: _enum(CameraMasterPulseMode, v)),
                masterpulse_source=_value(options, "masterpulse_source", CameraMasterPulseSource.SOFTWARE, lambda v: _enum(CameraMasterPulseSource, v)),
                masterpulse_interval_s=_value(options, "masterpulse_interval_s", 0.01, float),
                masterpulse_burst_times=_value(options, "masterpulse_burst_times", 1, int),
                global_exposure=_bool(options["global_exposure"]) if "global_exposure" in options else None,
            )
        return DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_CONFIGURE,
            CameraConfigureSequenceArgs(
                frame_count=int(options["frames"]),
                exposure_ms=float(options["exposure_ms"]) if "exposure_ms" in options else None,
                frame_timeout_s=_value(options, "timeout_s", 30.0, float),
                poll_interval_s=_value(options, "poll_interval_s", 0.05, float), trigger=trigger,
            ), source=source)
    if tuple(words) == ("camera", "capture", "stop"):
        return DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_CAPTURE_STOP, source=source)

    if words[:2] in (["pump", "refill"], ["pump", "empty"]) and len(words) > 2 and words[2].startswith("--"):
        options = _options(words[2:])
        _only_options(options, "flow_ul_min", "timeout_s", "poll_interval_s")
        args = PumpMoveArgs(
            float(options["flow_ul_min"]) if "flow_ul_min" in options else None,
            _value(options, "timeout_s", 120.0, float),
            _value(options, "poll_interval_s", 0.1, float),
        )
        operation = DeviceOperation.PUMP_REFILL if words[1] == "refill" else DeviceOperation.PUMP_EMPTY
        return DeviceCommand(DeviceId.PUMP, operation, args, source=source)
    if words[:3] == ["pump", "reference", "move"]:
        options = _options(words[3:])
        _only_options(options, "timeout_s", "poll_interval_s")
        return DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_REFERENCE_MOVE,
            PumpReferenceMoveArgs(_value(options, "timeout_s", 60.0, float),
                                  _value(options, "poll_interval_s", 0.1, float)), source=source)
    if words[:3] == ["valve", "wait", "ready"]:
        options = _options(words[3:])
        _only_options(options, "timeout_s", "poll_interval_s")
        return DeviceCommand(DeviceId.VALVE, DeviceOperation.VALVE_WAIT_READY,
            ValveWaitReadyArgs(_value(options, "timeout_s", 1.0, float),
                               _value(options, "poll_interval_s", 0.05, float)), source=source)
    if words[:3] == ["tec", "set", "temperatures"]:
        options = _options(words[3:])
        _only_options(options, "broadcast_c", "ch1_c", "ch2_c", "channels")
        if "broadcast_c" in options:
            targets: float | dict[int, float] = float(options["broadcast_c"])
        else:
            targets = {index: float(options[f"ch{index}_c"]) for index in (1, 2) if f"ch{index}_c" in options}
            if not targets:
                raise ValueError("Specify --broadcast-c C or --ch1-c/--ch2-c")
        channels = tuple(int(value) for value in options["channels"].split(",")) if "channels" in options else None
        return DeviceCommand(DeviceId.TEC, DeviceOperation.TEC_SETPOINTS_APPLY,
                             TecApplySetpointsArgs(targets, channels), source=source)
    if words[:3] == ["tec", "wait", "stable"] and len(words) > 3 and words[3].startswith("--"):
        options = _options(words[3:])
        allowed = ("broadcast_c", "ch1_c", "ch2_c", "tolerance_c", "settle_s", "max_wait_s", "poll_interval_s", "channels")
        _only_options(options, *allowed)
        if "broadcast_c" in options:
            targets = float(options["broadcast_c"])
        else:
            targets = {index: float(options[f"ch{index}_c"]) for index in (1, 2) if f"ch{index}_c" in options}
            if not targets:
                raise ValueError("Specify --broadcast-c C or --ch1-c/--ch2-c")
        for required in ("tolerance_c", "settle_s", "max_wait_s"):
            if required not in options:
                raise ValueError(f"tec wait stable requires --{required.replace('_', '-')}")
        channels = tuple(int(value) for value in options["channels"].split(",")) if "channels" in options else None
        return DeviceCommand(DeviceId.TEC, DeviceOperation.TEC_WAIT_STABLE,
            TecWaitStableArgs(targets, float(options["tolerance_c"]), float(options["settle_s"]),
                              float(options["max_wait_s"]), _value(options, "poll_interval_s", 1.0, float), channels), source=source)
    if len(words) == 3 and words[:2] == ["pump", "set-flow"]:
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_FLOW_SET,
            PumpSetFlowArgs(float(words[2])),
            source=source,
        )
    if words == ["pump", "stop"]:
        return DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FLOW_STOP, PumpUnitArgs(), source=source)
    if words == ["pump", "read-fill-level"]:
        return DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_READ, PumpUnitArgs(), source=source)
    if words == ["pump", "read-status"]:
        return DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_STATUS_READ, PumpUnitArgs(), source=source)
    if words[:2] == ["pump", "set-fill-level"] and len(words) in (3, 4):
        flow_rate = None if len(words) == 3 else float(words[3])
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_FILL_LEVEL_SET,
            PumpSetFillLevelArgs(float(words[2]), flow_rate),
            source=source,
        )
    if words[:2] == ["pump", "configure-syringe"] and len(words) == 3:
        preset = _SYRINGE_PRESETS.get(words[2].lower())
        if preset is None:
            raise ValueError(f"Unknown syringe preset: {words[2]}")
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_SYRINGE_CONFIGURE,
            PumpConfigureSyringeArgs(preset=preset),
            source=source,
        )
    if words[:3] == ["pump", "configure-syringe", "custom"] and len(words) == 5:
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_SYRINGE_CONFIGURE,
            PumpConfigureSyringeArgs(
                inner_diameter_mm=float(words[3]),
                max_piston_stroke_mm=float(words[4]),
            ),
            source=source,
        )
    if words[:2] == ["pump", "configure-flow-unit"] and len(words) == 3:
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_FLOW_UNIT_CONFIGURE,
            PumpConfigureFlowUnitArgs(PumpFlowUnit(words[2].lower())),
            source=source,
        )
    if words == ["pump", "recover-fault"]:
        return DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FAULT_RECOVER, PumpUnitArgs(), source=source)
    if words[:2] in (["pump", "refill"], ["pump", "empty"]) and len(words) in (2, 3):
        flow_rate = None if len(words) == 2 else float(words[2])
        operation = (
            DeviceOperation.PUMP_REFILL
            if words[1] == "refill"
            else DeviceOperation.PUMP_EMPTY
        )
        return DeviceCommand(
            DeviceId.PUMP, operation, PumpMoveArgs(flow_rate), source=source
        )
    if words == ["pump", "reference-move"]:
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_REFERENCE_MOVE,
            PumpReferenceMoveArgs(),
            source=source,
        )
    if len(words) == 3 and words[:2] == ["valve", "set-position"]:
        return DeviceCommand(
            DeviceId.VALVE,
            DeviceOperation.VALVE_POSITION_SET,
            ValveSetPositionArgs(int(words[2])),
            source=source,
        )
    if words == ["valve", "read-position"]:
        return DeviceCommand(DeviceId.VALVE, DeviceOperation.VALVE_POSITION_READ, source=source)
    if words[:2] == ["valve", "wait-ready"] and len(words) in (2, 3):
        args = ValveWaitReadyArgs() if len(words) == 2 else ValveWaitReadyArgs(float(words[2]))
        return DeviceCommand(DeviceId.VALVE, DeviceOperation.VALVE_WAIT_READY, args, source=source)
    if words == ["camera", "snapshot"]:
        return DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_SNAPSHOT_CAPTURE, source=source)
    if words[:2] == ["camera", "configure-snapshot"] and len(words) in (2, 3):
        exposure = None if len(words) == 2 else float(words[2])
        return DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE,
            CameraConfigureSnapshotArgs(exposure),
            source=source,
        )
    if words[:2] == ["camera", "configure-sequence"] and len(words) in (3, 4):
        exposure = None if len(words) == 3 else float(words[3])
        return DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_SEQUENCE_CONFIGURE,
            CameraConfigureSequenceArgs(int(words[2]), exposure),
            source=source,
        )
    if words == ["camera", "sequence"]:
        return DeviceCommand(
            DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_CAPTURE, source=source
        )
    if words == ["camera", "read-timing"]:
        return DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_TIMING_READ, source=source)
    if words[:2] == ["camera", "set-exposure"] and len(words) == 3:
        return DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_EXPOSURE_CONFIGURE,
            CameraConfigureExposureArgs(float(words[2])),
            source=source,
        )
    if words[:2] == ["camera", "set-roi"] and len(words) == 6:
        return DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_ROI_CONFIGURE,
            CameraConfigureRoiArgs(*(int(value) for value in words[2:])),
            source=source,
        )
    if words[:2] == ["ad2", "configure-do"] and len(words) in (4, 5):
        bits = tuple(int(bit) for bit in words[4]) if len(words) == 5 else ()
        output_type = Ad2DigitalOutputType.CUSTOM if bits else Ad2DigitalOutputType.PULSE
        return DeviceCommand(
            DeviceId.AD2,
            DeviceOperation.AD2_DIGITAL_OUTPUT_CONFIGURE,
            Ad2ConfigureDigitalOutputArgs(
                channel_index=int(words[2]),
                output_type=output_type,
                clock_frequency_hz=float(words[3]),
                bits=bits,
            ),
            source=source,
        )
    ad2_digital_commands = {
        ("ad2", "start-do"): DeviceOperation.AD2_DIGITAL_OUTPUT_START,
        ("ad2", "stop-do"): DeviceOperation.AD2_DIGITAL_OUTPUT_STOP,
        ("ad2", "reset-do"): DeviceOperation.AD2_DIGITAL_OUTPUT_RESET,
    }
    if tuple(words) in ad2_digital_commands:
        return DeviceCommand(DeviceId.AD2, ad2_digital_commands[tuple(words)], source=source)
    if len(words) == 3 and words[:2] == ["tec", "set-temperature"]:
        return DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_SETPOINTS_APPLY,
            TecApplySetpointsArgs(float(words[2])),
            source=source,
        )
    if words == ["tec", "read-status"]:
        return DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_STATUS_READ,
            TecReadStatusArgs(),
            source=source,
        )
    if words == ["tec", "outputs-off"]:
        return DeviceCommand(DeviceId.TEC, DeviceOperation.TEC_OUTPUTS_OFF, source=source)
    if words[:2] == ["tec", "wait-stable"] and len(words) == 6:
        return DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_WAIT_STABLE,
            TecWaitStableArgs(
                target_temperature_c=float(words[2]),
                tolerance_c=float(words[3]),
                min_settle_s=float(words[4]),
                max_wait_s=float(words[5]),
            ),
            source=source,
        )
    if words == ["z-stage", "check-closed-loop"]:
        return DeviceCommand(
            DeviceId.Z_STAGE,
            DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ,
            source=source,
        )
    if words == ["z-stage", "enable-closed-loop"]:
        return DeviceCommand(
            DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE, source=source
        )
    if len(words) == 3 and words[:2] == ["z-stage", "move"]:
        return DeviceCommand(
            DeviceId.Z_STAGE,
            DeviceOperation.Z_STAGE_POSITION_SET,
            ZStageSetPositionArgs(float(words[2])),
            source=source,
        )
    if words == ["z-stage", "read-position"]:
        return DeviceCommand(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_POSITION_READ, source=source)
    raise ValueError(f"Invalid command. Type help for supported commands: {line}")
