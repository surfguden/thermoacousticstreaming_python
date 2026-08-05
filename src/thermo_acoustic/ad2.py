from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WaveformFunction(str, Enum):
    SINE = "Sine"
    SQUARE = "Square"
    TRIANGLE = "Triangle"
    RAMP_UP = "RampUp"
    RAMP_DOWN = "RampDown"
    DC = "DC"


class DigitalOutType(str, Enum):
    PULSE = "Pulse"
    CUSTOM = "Custom"
    RANDOM = "Random"


class DigitalOutIdleState(str, Enum):
    INITIAL = "Initial"
    LOW = "Low"
    HIGH = "High"
    ZET = "Zet"


class TriggerSource(str, Enum):
    NONE = "trigsrcNone"
    PC = "trigsrcPC"
    DETECTOR_ANALOG_IN = "trigsrcDetectorAnalogIn"
    DETECTOR_DIGITAL_IN = "trigsrcDetectorDigitalIn"
    ANALOG_IN = "trigsrcAnalogIn"
    DIGITAL_IN = "trigsrcDigitalIn"
    DIGITAL_OUT = "trigsrcDigitalOut"
    ANALOG_OUT_1 = "trigsrcAnalogOut1"
    ANALOG_OUT_2 = "trigsrcAnalogOut2"
    ANALOG_OUT_3 = "trigsrcAnalogOut3"
    ANALOG_OUT_4 = "trigsrcAnalogOut4"


@dataclass(slots=True)
class TriggerSettings:
    sec_run: float = 0.0
    sec_wait: float = 0.0
    repeat_count: int = 0
    repeat_trigger: bool = False
    source: TriggerSource | str = TriggerSource.NONE


@dataclass(slots=True)
class CarrierSettings:
    frequency_hz: float = 1000.0
    amplitude_v: float = 1.0
    offset_v: float = 0.0
    symmetry_percent: float = 50.0
    phase_deg: float = 0.0
    function: WaveformFunction = WaveformFunction.SINE
    enable: bool = True


@dataclass(slots=True)
class WfgChannelConfig:
    channel_index: int = 0
    out_of_range: bool = False
    carrier: CarrierSettings = field(default_factory=CarrierSettings)
    trigger: TriggerSettings = field(default_factory=TriggerSettings)
    fm_mod: CarrierSettings = field(default_factory=lambda: CarrierSettings(enable=False))


@dataclass(slots=True)
class WfgConfig:
    running: bool = False
    channels: list[WfgChannelConfig] = field(
        default_factory=lambda: [WfgChannelConfig(0), WfgChannelConfig(1)]
    )
    synchronize_state: str = "Independent"

    def check_valid(self) -> bool:
        return all(not channel.out_of_range for channel in self.channels)


_FM_SWEEP_TYPE_TO_FUNCTION: dict[str, WaveformFunction] = {
    "Symmetric": WaveformFunction.TRIANGLE,
    "RampUp": WaveformFunction.RAMP_UP,
    "RampDown": WaveformFunction.RAMP_DOWN,
}


@dataclass(slots=True)
class FmSweepSettings:
    """Millisecond-timescale FM sweep calibration parameters, translated
    into the AD2's native FM modulation node (waveforms.py's node=1 path,
    already wired for the manual WFG tab's "FM Mod" group).

    Reference test case (Martens et al., PhysRevApplied.23.024043):
    "actuation frequency centered at 1.934 MHz with a sweep of 50 kHz and
    a sweep time of 1 ms" -> center_hz=1_934_000, width_hz=50_000,
    sweep_time_ms=1.0.

    Distinct from Frequency Scanning / Dynamic Frequency, which runs one
    full experiment per discrete frequency point across Repeats -- this
    sweeps continuously within a single acoustic drive.

    Unverified against real hardware or LabVIEW's compiled block diagram
    (investigation could only read front-panel control names, not wiring
    logic -- see WfgConfigureSweepCh1.vi / BasicSweepSettings.ctl):
    - The exact Sweep Type -> Function 2 enum correspondence below
      (Symmetric->Triangle, RampUp->RampUp, RampDown->RampDown) is the
      most architecturally plausible mapping, not a confirmed one.
    - Whether enabling the sweep should force Carrier.enable=True in
      addition to fm_mod.enable=True (this class's own convention, per
      this feature's spec) matches LabVIEW's actual wiring.
    """

    center_hz: float
    width_hz: float
    sweep_time_ms: float
    sweep_type: str = "Symmetric"

    def __post_init__(self) -> None:
        if self.sweep_time_ms <= 0:
            raise ValueError(f"Sweep Time must be greater than 0 ms; got {self.sweep_time_ms}.")

    @property
    def top_hz(self) -> float:
        return self.center_hz + self.width_hz / 2.0

    @property
    def bottom_hz(self) -> float:
        return self.center_hz - self.width_hz / 2.0

    @property
    def fm_frequency_hz(self) -> float:
        return 1000.0 / self.sweep_time_ms

    @property
    def fm_amplitude_pct(self) -> float:
        if self.center_hz == 0:
            raise ValueError("Center Frequency must be non-zero to compute sweep amplitude.")
        return (self.width_hz / self.center_hz) * 100.0

    @property
    def fm_function(self) -> WaveformFunction:
        try:
            return _FM_SWEEP_TYPE_TO_FUNCTION[self.sweep_type]
        except KeyError:
            raise ValueError(f"Unsupported Sweep Type: {self.sweep_type!r}") from None

    def fm_mod_settings(self) -> CarrierSettings:
        return CarrierSettings(
            frequency_hz=self.fm_frequency_hz,
            amplitude_v=self.fm_amplitude_pct,
            offset_v=0.0,
            symmetry_percent=50.0,
            phase_deg=0.0,
            function=self.fm_function,
            enable=True,
        )


@dataclass(slots=True)
class DoCustomData:
    count_of_bits: int = 0
    bits: list[int] = field(default_factory=list)


@dataclass(slots=True)
class DoSingleChannelConfig:
    channel_index: int = 0
    enable: bool = False
    clock_divider: int = 0
    clock_frequency_hz: float | None = None
    # Finding E (silent-failure/data-integrity sweep): the real achieved
    # frequency after WaveFormsBackend.configure_do() rounds clock_frequency_hz
    # down to an integer divider -- None until a real configure_do() call sets
    # it (mirrors WfgChannelConfig.out_of_range's "never assigned until the
    # real hardware call runs" pattern). Requested and achieved can differ by
    # up to one divider step; recording both means that gap is visible in
    # data.tdms instead of only the requested value being recorded.
    achieved_clock_frequency_hz: float | None = None
    output_type: DigitalOutType = DigitalOutType.PULSE
    output_mode: str = "PushPull"
    idle_state: DigitalOutIdleState = DigitalOutIdleState.INITIAL
    counter_high_bits: int = 0
    counter_low_bits: int = 0
    counter_initial_bits: int = 0
    start_high: bool = True
    custom_data: DoCustomData = field(default_factory=DoCustomData)
    trigger: TriggerSettings = field(default_factory=TriggerSettings)


@dataclass(slots=True)
class DoConfig:
    channels: list[DoSingleChannelConfig] = field(default_factory=list)
    running: bool = False

    def channel(self, index: int) -> DoSingleChannelConfig:
        for item in self.channels:
            if item.channel_index == index:
                return item
        created = DoSingleChannelConfig(channel_index=index)
        self.channels.append(created)
        return created


@dataclass(slots=True)
class MsoConfig:
    device_handle: object | int | None = None
    range_ch1: float | None = None
    range_ch2: float | None = None
    sample_frequency_hz: float | None = None
    sample_count: int | None = None
    trigger_source: TriggerSource | str = TriggerSource.NONE


def _first_present(data: dict[str, Any], *names: str, default: Any = None) -> Any:
    normalized = {key.lower().replace("_", "").replace(" ", ""): value for key, value in data.items()}
    for name in names:
        key = name.lower().replace("_", "").replace(" ", "")
        if key in normalized:
            return normalized[key]
    return default


def _coerce_enum(enum_type: type[Enum], value: Any, default: Any) -> Any:
    if isinstance(value, enum_type):
        return value
    if value is None:
        return default
    text = str(value)
    for item in enum_type:
        if text == item.value or text.lower() == item.name.lower() or text.lower() == item.value.lower():
            return item
    # A missing field may use its documented compatibility default. An
    # explicitly supplied, unrecognised value must fail closed instead of
    # silently selecting a potentially active hardware mode.
    raise ValueError(f"Unsupported {enum_type.__name__}: {value!r}")


def coerce_trigger_settings(config: TriggerSettings | dict[str, Any] | None) -> TriggerSettings:
    if isinstance(config, TriggerSettings):
        return config
    if config is None:
        return TriggerSettings()
    return TriggerSettings(
        sec_run=float(_first_present(config, "sec_run", "secRun", "run", default=0.0) or 0.0),
        sec_wait=float(_first_present(config, "sec_wait", "secWait", "wait", default=0.0) or 0.0),
        repeat_count=int(_first_present(config, "repeat_count", "repeatCount", "repeat", default=0) or 0),
        repeat_trigger=bool(_first_present(config, "repeat_trigger", "repeatTrigger", default=False)),
        source=_coerce_enum(
            TriggerSource,
            _first_present(config, "source", "trigger_source", "triggerSource", default=TriggerSource.NONE),
            TriggerSource.NONE,
        ),
    )


def coerce_carrier_settings(config: CarrierSettings | dict[str, Any] | None, *, enable: bool = True) -> CarrierSettings:
    if isinstance(config, CarrierSettings):
        return config
    if config is None:
        return CarrierSettings(enable=enable)
    return CarrierSettings(
        frequency_hz=float(_first_present(config, "frequency_hz", "frequencyHz", "frequency", "freq", default=1000.0) or 0.0),
        amplitude_v=float(_first_present(config, "amplitude_v", "amplitudeV", "amplitude", default=1.0) or 0.0),
        offset_v=float(_first_present(config, "offset_v", "offsetV", "offset", default=0.0) or 0.0),
        symmetry_percent=float(_first_present(config, "symmetry_percent", "symmetryPercent", "symmetry", default=50.0) or 0.0),
        phase_deg=float(_first_present(config, "phase_deg", "phaseDeg", "phase", default=0.0) or 0.0),
        function=_coerce_enum(
            WaveformFunction,
            _first_present(config, "function", "waveform", "waveform_function", default=WaveformFunction.SINE),
            WaveformFunction.SINE,
        ),
        enable=bool(_first_present(config, "enable", "enabled", default=enable)),
    )


def coerce_wfg_channel_config(config: WfgChannelConfig | dict[str, Any] | None, index: int = 0) -> WfgChannelConfig:
    if isinstance(config, WfgChannelConfig):
        return config
    if config is None:
        return WfgChannelConfig(channel_index=index)
    carrier_data = _first_present(config, "carrier", "carrier_settings", default=config)
    fm_data = _first_present(config, "fm_mod", "fmMod", "fm", default=None)
    return WfgChannelConfig(
        channel_index=int(_first_present(config, "channel_index", "channelIndex", "channel", "idx", default=index) or 0),
        out_of_range=bool(_first_present(config, "out_of_range", "outOfRange", default=False)),
        carrier=coerce_carrier_settings(carrier_data, enable=True),
        trigger=coerce_trigger_settings(_first_present(config, "trigger", "trigger_settings", default=None)),
        fm_mod=coerce_carrier_settings(fm_data, enable=False),
    )


def coerce_wfg_config(config: WfgConfig | dict[str, Any] | None) -> WfgConfig:
    if isinstance(config, WfgConfig):
        return config
    if config is None:
        return WfgConfig()
    wfg = WfgConfig()
    if "running" in config:
        wfg.running = bool(config["running"])
    if "synchronize_state" in config:
        wfg.synchronize_state = str(config["synchronize_state"])
    raw_channels = _first_present(config, "channels", "channel_configs", default=None)
    if isinstance(raw_channels, list):
        wfg.channels = [coerce_wfg_channel_config(channel, index) for index, channel in enumerate(raw_channels)]
    elif raw_channels is None:
        channel_keys = [
            ("channel_0", 0),
            ("channel0", 0),
            ("ch0", 0),
            ("channel_1", 1),
            ("channel1", 1),
            ("ch1", 1),
        ]
        channels = []
        for key, index in channel_keys:
            if key in config:
                channels.append(coerce_wfg_channel_config(config[key], index))
        if channels:
            wfg.channels = channels
        elif any(
            key in config
            for key in (
                "frequency_hz",
                "frequencyHz",
                "frequency",
                "freq",
                "amplitude_v",
                "amplitude",
                "offset_v",
                "offset",
                "symmetry_percent",
                "symmetry",
                "phase_deg",
                "phase",
                "function",
                "waveform",
                "waveform_function",
                "enable",
                "enabled",
                "trigger",
                "trigger_settings",
            )
        ):
            wfg.channels = [coerce_wfg_channel_config(config, 0), WfgChannelConfig(1, carrier=CarrierSettings(enable=False))]
    return wfg


def coerce_do_custom_data(config: DoCustomData | dict[str, Any] | list[int] | None) -> DoCustomData:
    if isinstance(config, DoCustomData):
        return config
    if config is None:
        return DoCustomData()
    if isinstance(config, list):
        bits = [int(bool(bit)) for bit in config]
        return DoCustomData(count_of_bits=len(bits), bits=bits)
    bits = _first_present(config, "bits", "data", "pattern", default=[])
    bits = [int(bool(bit)) for bit in bits]
    return DoCustomData(
        count_of_bits=int(_first_present(config, "count_of_bits", "countOfBits", "count", default=len(bits)) or len(bits)),
        bits=bits,
    )


def coerce_do_channel_config(config: DoSingleChannelConfig | dict[str, Any] | None, index: int = 0) -> DoSingleChannelConfig:
    if isinstance(config, DoSingleChannelConfig):
        return config
    if config is None:
        return DoSingleChannelConfig(channel_index=index)
    return DoSingleChannelConfig(
        channel_index=int(_first_present(config, "channel_index", "channelIndex", "channel", "idx", default=index) or 0),
        enable=bool(_first_present(config, "enable", "enabled", default=False)),
        clock_divider=int(_first_present(config, "clock_divider", "clockDivider", "divider", default=0) or 0),
        clock_frequency_hz=(
            None
            if _first_present(config, "clock_frequency_hz", "clockFrequencyHz", "frequency_hz", "frequencyHz", "frequency", default=None) is None
            else float(_first_present(config, "clock_frequency_hz", "clockFrequencyHz", "frequency_hz", "frequencyHz", "frequency", default=0.0) or 0.0)
        ),
        output_type=_coerce_enum(
            DigitalOutType,
            _first_present(config, "output_type", "outputType", "type", default=DigitalOutType.PULSE),
            DigitalOutType.PULSE,
        ),
        output_mode=str(_first_present(config, "output_mode", "outputMode", "mode", default="PushPull")),
        idle_state=_coerce_enum(
            DigitalOutIdleState,
            _first_present(config, "idle_state", "idleState", "idle", default=DigitalOutIdleState.INITIAL),
            DigitalOutIdleState.INITIAL,
        ),
        counter_high_bits=int(_first_present(config, "counter_high_bits", "counterHighBits", "high_bits", "highBits", default=0) or 0),
        counter_low_bits=int(_first_present(config, "counter_low_bits", "counterLowBits", "low_bits", "lowBits", default=0) or 0),
        counter_initial_bits=int(_first_present(config, "counter_initial_bits", "counterInitialBits", "initial_bits", default=0) or 0),
        start_high=bool(_first_present(config, "start_high", "startHigh", default=True)),
        custom_data=coerce_do_custom_data(_first_present(config, "custom_data", "customData", "pattern", "bits", default=None)),
        trigger=coerce_trigger_settings(_first_present(config, "trigger", "trigger_settings", default=None)),
    )


def coerce_do_config(config: DoConfig | dict[str, Any] | None) -> DoConfig:
    if isinstance(config, DoConfig):
        return config
    if config is None:
        return DoConfig()
    do_config = DoConfig()
    if "running" in config:
        do_config.running = bool(config["running"])
    raw_channels = _first_present(config, "channels", "channel_configs", default=None)
    if isinstance(raw_channels, list):
        do_config.channels = [coerce_do_channel_config(channel, index) for index, channel in enumerate(raw_channels)]
    elif any(
        key in config
        for key in (
            "pattern",
            "bits",
            "clock_divider",
            "clockDivider",
            "divider",
            "clock_frequency_hz",
            "clockFrequencyHz",
            "frequency_hz",
            "frequencyHz",
            "frequency",
            "enable",
            "enabled",
            "output_type",
            "outputType",
            "type",
            "output_mode",
            "outputMode",
            "idle_state",
            "idleState",
            "idle",
            "trigger",
            "trigger_settings",
        )
    ):
        do_config.channels = [coerce_do_channel_config(config, 0)]
    return do_config
