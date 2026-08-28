from __future__ import annotations

import ctypes
from ctypes import byref, c_char, c_double, c_int, c_ubyte, c_uint, create_string_buffer
from ctypes.util import find_library
from pathlib import Path
import time
from typing import Iterable

from .ad2 import (
    DigitalOutIdleState,
    DigitalOutType,
    DoConfig,
    TriggerSource,
    WaveformFunction,
    WfgConfig,
)
from .hw_logging import log_call


class WaveFormsError(RuntimeError):
    """Raised when the Digilent WaveForms SDK returns an error."""


class WaveFormsBackend:
    """Small ctypes wrapper around the Digilent WaveForms DWF API."""

    _FUNCTIONS = {
        WaveformFunction.DC: 0,
        WaveformFunction.SINE: 1,
        WaveformFunction.SQUARE: 2,
        WaveformFunction.TRIANGLE: 3,
        WaveformFunction.RAMP_UP: 4,
        WaveformFunction.RAMP_DOWN: 5,
    }
    _DO_TYPES = {
        DigitalOutType.PULSE: 0,
        DigitalOutType.CUSTOM: 1,
        DigitalOutType.RANDOM: 2,
    }
    _DO_IDLE = {
        DigitalOutIdleState.INITIAL: 0,
        DigitalOutIdleState.LOW: 1,
        DigitalOutIdleState.HIGH: 2,
        DigitalOutIdleState.ZET: 3,
    }
    _TRIGGER_SOURCES = {
        TriggerSource.NONE: 0,
        TriggerSource.PC: 1,
        TriggerSource.DETECTOR_ANALOG_IN: 2,
        TriggerSource.DETECTOR_DIGITAL_IN: 3,
        TriggerSource.ANALOG_IN: 4,
        TriggerSource.DIGITAL_IN: 5,
        TriggerSource.DIGITAL_OUT: 6,
        TriggerSource.ANALOG_OUT_1: 7,
        TriggerSource.ANALOG_OUT_2: 8,
        TriggerSource.ANALOG_OUT_3: 9,
        TriggerSource.ANALOG_OUT_4: 10,
    }
    _OUTPUT_MODES = {
        "pushpull": 0,
        "opendrain": 1,
        "opensource": 2,
        "threestate": 3,
    }

    def __init__(self, library_path: str | Path | None = None, dwf: object | None = None) -> None:
        if dwf is not None:
            self.library_path = Path(library_path) if library_path is not None else None
            self._dwf = dwf
        else:
            self.library_path = self._resolve_library(library_path)
            self._dwf = (
                ctypes.WinDLL(str(self.library_path))
                if hasattr(ctypes, "WinDLL")
                else ctypes.CDLL(str(self.library_path))
            )
        self._bind_signatures()

    @classmethod
    def is_available(cls) -> bool:
        try:
            cls._resolve_library(None)
        except WaveFormsError:
            return False
        return True

    @staticmethod
    def _candidate_paths() -> Iterable[Path]:
        for found in (find_library("dwf"), find_library("dwf.dll")):
            if found:
                yield Path(found)
        yield Path(r"C:\Windows\System32\dwf.dll")
        yield Path(r"C:\Windows\SysWOW64\dwf.dll")
        yield Path(r"C:\Program Files\Digilent\WaveFormsSDK\lib\x64\dwf.dll")
        yield Path(r"C:\Program Files (x86)\Digilent\WaveFormsSDK\lib\x86\dwf.dll")

    @classmethod
    def _resolve_library(cls, library_path: str | Path | None) -> Path:
        if library_path is not None:
            path = Path(library_path)
            if path.exists():
                return path
            raise WaveFormsError(f"WaveForms library was not found: {path}")

        for path in cls._candidate_paths():
            if path.exists():
                return path
        raise WaveFormsError("Could not find dwf.dll. Install Digilent WaveForms or pass library_path.")

    def _bind_signatures(self) -> None:
        signatures = {
            "FDwfGetLastErrorMsg": ([ctypes.POINTER(c_char)], c_int),
            "FDwfDeviceOpen": ([c_int, ctypes.POINTER(c_int)], c_int),
            "FDwfDeviceClose": ([c_int], c_int),
            "FDwfDeviceCloseAll": ([], c_int),
            "FDwfDeviceReset": ([c_int], c_int),
            "FDwfDeviceAutoConfigureSet": ([c_int, c_int], c_int),
            "FDwfDeviceTriggerPC": ([c_int], c_int),
            "FDwfEnum": ([c_int, ctypes.POINTER(c_int)], c_int),
            "FDwfEnumDeviceIsOpened": ([c_int, ctypes.POINTER(c_int)], c_int),
            "FDwfEnumDeviceName": ([c_int, ctypes.POINTER(c_char)], c_int),
            "FDwfEnumSN": ([c_int, ctypes.POINTER(c_char)], c_int),
            "FDwfGetLastError": ([ctypes.POINTER(c_int)], c_int),
            "FDwfAnalogOutNodeEnableSet": ([c_int, c_int, c_int, c_int], c_int),
            "FDwfAnalogOutNodeEnableGet": ([c_int, c_int, c_int, ctypes.POINTER(c_int)], c_int),
            "FDwfAnalogOutNodeFunctionSet": ([c_int, c_int, c_int, c_int], c_int),
            "FDwfAnalogOutNodeFunctionGet": ([c_int, c_int, c_int, ctypes.POINTER(c_int)], c_int),
            "FDwfAnalogOutNodeFrequencySet": ([c_int, c_int, c_int, c_double], c_int),
            "FDwfAnalogOutNodeFrequencyGet": ([c_int, c_int, c_int, ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutNodeFrequencyInfo": ([c_int, c_int, c_int, ctypes.POINTER(c_double), ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutNodeAmplitudeSet": ([c_int, c_int, c_int, c_double], c_int),
            "FDwfAnalogOutNodeAmplitudeGet": ([c_int, c_int, c_int, ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutNodeAmplitudeInfo": ([c_int, c_int, c_int, ctypes.POINTER(c_double), ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutNodeOffsetSet": ([c_int, c_int, c_int, c_double], c_int),
            "FDwfAnalogOutNodeOffsetGet": ([c_int, c_int, c_int, ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutNodeOffsetInfo": ([c_int, c_int, c_int, ctypes.POINTER(c_double), ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutNodeSymmetrySet": ([c_int, c_int, c_int, c_double], c_int),
            "FDwfAnalogOutNodeSymmetryGet": ([c_int, c_int, c_int, ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutNodeSymmetryInfo": ([c_int, c_int, c_int, ctypes.POINTER(c_double), ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutNodePhaseSet": ([c_int, c_int, c_int, c_double], c_int),
            "FDwfAnalogOutNodePhaseGet": ([c_int, c_int, c_int, ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutNodePhaseInfo": ([c_int, c_int, c_int, ctypes.POINTER(c_double), ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutRunSet": ([c_int, c_int, c_double], c_int),
            "FDwfAnalogOutRunGet": ([c_int, c_int, ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutWaitSet": ([c_int, c_int, c_double], c_int),
            "FDwfAnalogOutWaitGet": ([c_int, c_int, ctypes.POINTER(c_double)], c_int),
            "FDwfAnalogOutRepeatSet": ([c_int, c_int, c_int], c_int),
            "FDwfAnalogOutRepeatGet": ([c_int, c_int, ctypes.POINTER(c_int)], c_int),
            "FDwfAnalogOutRepeatTriggerSet": ([c_int, c_int, c_int], c_int),
            "FDwfAnalogOutRepeatTriggerGet": ([c_int, c_int, ctypes.POINTER(c_int)], c_int),
            "FDwfAnalogOutTriggerSourceSet": ([c_int, c_int, c_int], c_int),
            "FDwfAnalogOutTriggerSourceGet": ([c_int, c_int, ctypes.POINTER(c_int)], c_int),
            "FDwfAnalogOutIdleSet": ([c_int, c_int, c_int], c_int),
            "FDwfAnalogOutMasterSet": ([c_int, c_int, c_int], c_int),
            "FDwfAnalogOutConfigure": ([c_int, c_int, c_int], c_int),
            "FDwfAnalogInChannelEnableSet": ([c_int, c_int, c_int], c_int),
            "FDwfAnalogInChannelRangeSet": ([c_int, c_int, c_double], c_int),
            "FDwfAnalogInChannelOffsetSet": ([c_int, c_int, c_double], c_int),
            "FDwfAnalogInFrequencySet": ([c_int, c_double], c_int),
            "FDwfAnalogInBufferSizeSet": ([c_int, c_int], c_int),
            "FDwfAnalogInTriggerSourceSet": ([c_int, c_int], c_int),
            "FDwfAnalogInConfigure": ([c_int, c_int, c_int], c_int),
            "FDwfAnalogInStatus": ([c_int, c_int, ctypes.POINTER(c_int)], c_int),
            "FDwfAnalogInStatusData": ([c_int, c_int, ctypes.POINTER(c_double), c_int], c_int),
            "FDwfDigitalOutReset": ([c_int], c_int),
            "FDwfDigitalOutCount": ([c_int, ctypes.POINTER(c_int)], c_int),
            "FDwfDigitalOutInternalClockInfo": ([c_int, ctypes.POINTER(c_double)], c_int),
            "FDwfDigitalOutEnableSet": ([c_int, c_int, c_int], c_int),
            "FDwfDigitalOutDividerSet": ([c_int, c_int, c_uint], c_int),
            "FDwfDigitalOutDividerInfo": ([c_int, c_int, ctypes.POINTER(c_uint), ctypes.POINTER(c_uint)], c_int),
            "FDwfDigitalOutCounterInitSet": ([c_int, c_int, c_int, c_uint], c_int),
            "FDwfDigitalOutCounterSet": ([c_int, c_int, c_uint, c_uint], c_int),
            "FDwfDigitalOutIdleSet": ([c_int, c_int, c_int], c_int),
            "FDwfDigitalOutTypeSet": ([c_int, c_int, c_int], c_int),
            "FDwfDigitalOutOutputSet": ([c_int, c_int, c_int], c_int),
            "FDwfDigitalOutDataSet": ([c_int, c_int, ctypes.POINTER(c_ubyte), c_int], c_int),
            "FDwfDigitalOutDataInfo": ([c_int, c_int, ctypes.POINTER(c_uint)], c_int),
            "FDwfDigitalOutWaitSet": ([c_int, c_double], c_int),
            "FDwfDigitalOutRunSet": ([c_int, c_double], c_int),
            "FDwfDigitalOutRepeatSet": ([c_int, c_int], c_int),
            "FDwfDigitalOutRepeatTriggerSet": ([c_int, c_int], c_int),
            "FDwfDigitalOutTriggerSourceSet": ([c_int, c_int], c_int),
            "FDwfDigitalOutConfigure": ([c_int, c_int], c_int),
        }
        for name, (argtypes, restype) in signatures.items():
            func = getattr(self._dwf, name)
            func.argtypes = argtypes
            func.restype = restype

    def _last_error(self) -> str:
        buffer = create_string_buffer(512)
        self._dwf.FDwfGetLastErrorMsg(buffer)
        return buffer.value.decode(errors="replace")

    def _check(self, result: int, operation: str) -> None:
        if not result:
            message = self._last_error()
            raise WaveFormsError(f"{operation} failed: {message}")

    @staticmethod
    def _enum_value(mapping: dict, value: object) -> int:
        if isinstance(value, int):
            return value
        for key, mapped in mapping.items():
            if value == key or value == getattr(key, "value", None):
                return mapped
        raise WaveFormsError(f"Unsupported WaveForms enum value: {value!r}")

    def _output_mode_value(self, output_mode: object) -> int:
        # Finding 1 (waveforms.py review, Session 66): output_mode is a
        # free-form str field (DoSingleChannelConfig.output_mode), not an
        # enum -- unlike function/trigger_source, nothing upstream (
        # coerce_do_channel_config() in ad2.py just casts to str, no
        # validation) can ever catch a typo before it reaches here. This is
        # the only real defense point in the whole pipeline, so a silent
        # fallback to "pushpull" would mean a bad config string silently
        # commands the real AD2 digital output into the wrong electrical
        # drive mode with zero error.
        key = str(output_mode).replace(" ", "").lower()
        if key not in self._OUTPUT_MODES:
            raise WaveFormsError(
                f"Unsupported digital-out output_mode: {output_mode!r} "
                f"(expected one of {sorted(self._OUTPUT_MODES)}, case/space-insensitive)."
            )
        return self._OUTPUT_MODES[key]

    def open_first_device(self) -> int:
        return self.open_device(-1)

    def open_device(self, device_index: int = -1) -> int:
        with log_call("ad2", "open_device", command=device_index) as result:
            handle = c_int()
            self._check(self._dwf.FDwfDeviceOpen(c_int(device_index), byref(handle)), "FDwfDeviceOpen")
            if handle.value == 0:
                raise WaveFormsError("FDwfDeviceOpen returned no device handle.")
            result["response"] = handle.value
        return handle.value

    def close(self, handle: int) -> None:
        with log_call("ad2", "close", command=handle) as result:
            self._check(self._dwf.FDwfDeviceClose(c_int(handle)), "FDwfDeviceClose")
            result["response"] = "closed"

    def close_all(self) -> None:
        # Real reachable call site: tools/release_ad2.py (a standalone
        # "release stuck AD2 handles" utility).
        with log_call("ad2", "close_all") as result:
            self._check(self._dwf.FDwfDeviceCloseAll(), "FDwfDeviceCloseAll")
            result["response"] = "all closed"

    def reset_device(self, handle: int) -> None:
        # Real reachable call site: hardware_tests/test_real_workflow_smoke.py's
        # safe_disable_ad2_outputs() (real post-test AD2 output cleanup).
        with log_call("ad2", "reset_device", command=handle) as result:
            self._check(self._dwf.FDwfDeviceReset(c_int(handle)), "FDwfDeviceReset")
            result["response"] = "reset"

    def set_auto_configure(self, handle: int, enabled: bool) -> None:
        self._check(self._dwf.FDwfDeviceAutoConfigureSet(c_int(handle), c_int(int(enabled))), "FDwfDeviceAutoConfigureSet")

    def trigger_pc(self, handle: int) -> None:
        with log_call("ad2", "trigger_pc", command=handle) as result:
            self._check(self._dwf.FDwfDeviceTriggerPC(c_int(handle)), "FDwfDeviceTriggerPC")
            result["response"] = "triggered"

    def get_last_error_code(self) -> int:
        code = c_int()
        self._dwf.FDwfGetLastError(byref(code))
        return code.value

    def get_last_error_message(self) -> str:
        return self._last_error()

    def enum_devices(self, filter_id: int = 0) -> int:
        # Real reachable call sites: tools/release_ad2.py and
        # hardware_tests/test_real_workflow_smoke.py's read_ad2_identity()
        # (real device-identity probes, not just dead SDK surface).
        with log_call("ad2", "enum_devices", command=filter_id) as result:
            count = c_int()
            self._check(self._dwf.FDwfEnum(c_int(filter_id), byref(count)), "FDwfEnum")
            result["response"] = count.value
        return count.value

    def enum_device_is_opened(self, device_index: int) -> bool:
        with log_call("ad2", "enum_device_is_opened", command=device_index) as result:
            opened = c_int()
            self._check(self._dwf.FDwfEnumDeviceIsOpened(c_int(device_index), byref(opened)), "FDwfEnumDeviceIsOpened")
            result["response"] = bool(opened.value)
        return bool(opened.value)

    def enum_device_name(self, device_index: int) -> str:
        with log_call("ad2", "enum_device_name", command=device_index) as result:
            buffer = create_string_buffer(64)
            self._check(self._dwf.FDwfEnumDeviceName(c_int(device_index), buffer), "FDwfEnumDeviceName")
            name = buffer.value.decode(errors="replace")
            result["response"] = name
        return name

    def enum_device_serial_number(self, device_index: int) -> str:
        with log_call("ad2", "enum_device_serial_number", command=device_index) as result:
            buffer = create_string_buffer(64)
            self._check(self._dwf.FDwfEnumSN(c_int(device_index), buffer), "FDwfEnumSN")
            serial = buffer.value.decode(errors="replace")
            result["response"] = serial
        return serial

    def _analog_out_set_double(self, function_name: str, handle: int, channel_index: int, value: float) -> None:
        self._check(getattr(self._dwf, function_name)(c_int(handle), c_int(channel_index), c_double(value)), function_name)

    def _analog_out_get_double(self, function_name: str, handle: int, channel_index: int) -> float:
        value = c_double()
        self._check(getattr(self._dwf, function_name)(c_int(handle), c_int(channel_index), byref(value)), function_name)
        return value.value

    def _analog_out_set_int(self, function_name: str, handle: int, channel_index: int, value: int) -> None:
        self._check(getattr(self._dwf, function_name)(c_int(handle), c_int(channel_index), c_int(value)), function_name)

    def _analog_out_get_int(self, function_name: str, handle: int, channel_index: int) -> int:
        value = c_int()
        self._check(getattr(self._dwf, function_name)(c_int(handle), c_int(channel_index), byref(value)), function_name)
        return value.value

    def _analog_node_set_double(self, function_name: str, handle: int, channel_index: int, node: int, value: float) -> None:
        self._check(getattr(self._dwf, function_name)(c_int(handle), c_int(channel_index), c_int(node), c_double(value)), function_name)

    def _analog_node_get_double(self, function_name: str, handle: int, channel_index: int, node: int) -> float:
        value = c_double()
        self._check(getattr(self._dwf, function_name)(c_int(handle), c_int(channel_index), c_int(node), byref(value)), function_name)
        return value.value

    def _analog_node_info_double(self, function_name: str, handle: int, channel_index: int, node: int) -> tuple[float, float]:
        minimum = c_double()
        maximum = c_double()
        self._check(
            getattr(self._dwf, function_name)(c_int(handle), c_int(channel_index), c_int(node), byref(minimum), byref(maximum)),
            function_name,
        )
        return minimum.value, maximum.value

    def _analog_node_set_int(self, function_name: str, handle: int, channel_index: int, node: int, value: int) -> None:
        self._check(getattr(self._dwf, function_name)(c_int(handle), c_int(channel_index), c_int(node), c_int(value)), function_name)

    def _analog_node_get_int(self, function_name: str, handle: int, channel_index: int, node: int) -> int:
        value = c_int()
        self._check(getattr(self._dwf, function_name)(c_int(handle), c_int(channel_index), c_int(node), byref(value)), function_name)
        return value.value

    def analog_out_node_enable_set(self, handle: int, channel_index: int, node: int, enabled: bool) -> None:
        # Real reachable call site: hardware_tests/test_real_workflow_smoke.py's
        # safe_disable_ad2_outputs() (real post-test AD2 output cleanup).
        with log_call("ad2", "analog_out_node_enable_set", command=(channel_index, node, enabled)) as result:
            self._analog_node_set_int("FDwfAnalogOutNodeEnableSet", handle, channel_index, node, int(enabled))
            result["response"] = "applied"

    def analog_out_node_enable_get(self, handle: int, channel_index: int, node: int) -> bool:
        return bool(self._analog_node_get_int("FDwfAnalogOutNodeEnableGet", handle, channel_index, node))

    def analog_out_node_function_set(self, handle: int, channel_index: int, node: int, function: int | WaveformFunction) -> None:
        self._analog_node_set_int("FDwfAnalogOutNodeFunctionSet", handle, channel_index, node, self._enum_value(self._FUNCTIONS, function))

    def analog_out_node_function_get(self, handle: int, channel_index: int, node: int) -> int:
        return self._analog_node_get_int("FDwfAnalogOutNodeFunctionGet", handle, channel_index, node)

    def analog_out_node_frequency_set(self, handle: int, channel_index: int, node: int, frequency_hz: float) -> None:
        self._analog_node_set_double("FDwfAnalogOutNodeFrequencySet", handle, channel_index, node, frequency_hz)

    def analog_out_node_frequency_get(self, handle: int, channel_index: int, node: int) -> float:
        return self._analog_node_get_double("FDwfAnalogOutNodeFrequencyGet", handle, channel_index, node)

    def analog_out_node_frequency_info(self, handle: int, channel_index: int, node: int) -> tuple[float, float]:
        return self._analog_node_info_double("FDwfAnalogOutNodeFrequencyInfo", handle, channel_index, node)

    def analog_out_node_amplitude_set(self, handle: int, channel_index: int, node: int, amplitude_v: float) -> None:
        self._analog_node_set_double("FDwfAnalogOutNodeAmplitudeSet", handle, channel_index, node, amplitude_v)

    def analog_out_node_amplitude_get(self, handle: int, channel_index: int, node: int) -> float:
        return self._analog_node_get_double("FDwfAnalogOutNodeAmplitudeGet", handle, channel_index, node)

    def analog_out_node_amplitude_info(self, handle: int, channel_index: int, node: int) -> tuple[float, float]:
        return self._analog_node_info_double("FDwfAnalogOutNodeAmplitudeInfo", handle, channel_index, node)

    def analog_out_node_offset_set(self, handle: int, channel_index: int, node: int, offset_v: float) -> None:
        self._analog_node_set_double("FDwfAnalogOutNodeOffsetSet", handle, channel_index, node, offset_v)

    def analog_out_node_offset_get(self, handle: int, channel_index: int, node: int) -> float:
        return self._analog_node_get_double("FDwfAnalogOutNodeOffsetGet", handle, channel_index, node)

    def analog_out_node_offset_info(self, handle: int, channel_index: int, node: int) -> tuple[float, float]:
        return self._analog_node_info_double("FDwfAnalogOutNodeOffsetInfo", handle, channel_index, node)

    def analog_out_node_symmetry_set(self, handle: int, channel_index: int, node: int, symmetry_percent: float) -> None:
        self._analog_node_set_double("FDwfAnalogOutNodeSymmetrySet", handle, channel_index, node, symmetry_percent)

    def analog_out_node_symmetry_get(self, handle: int, channel_index: int, node: int) -> float:
        return self._analog_node_get_double("FDwfAnalogOutNodeSymmetryGet", handle, channel_index, node)

    def analog_out_node_symmetry_info(self, handle: int, channel_index: int, node: int) -> tuple[float, float]:
        return self._analog_node_info_double("FDwfAnalogOutNodeSymmetryInfo", handle, channel_index, node)

    def analog_out_node_phase_set(self, handle: int, channel_index: int, node: int, phase_deg: float) -> None:
        self._analog_node_set_double("FDwfAnalogOutNodePhaseSet", handle, channel_index, node, phase_deg)

    def analog_out_node_phase_get(self, handle: int, channel_index: int, node: int) -> float:
        return self._analog_node_get_double("FDwfAnalogOutNodePhaseGet", handle, channel_index, node)

    def analog_out_node_phase_info(self, handle: int, channel_index: int, node: int) -> tuple[float, float]:
        return self._analog_node_info_double("FDwfAnalogOutNodePhaseInfo", handle, channel_index, node)

    def analog_out_run_set(self, handle: int, channel_index: int, run_s: float) -> None:
        self._analog_out_set_double("FDwfAnalogOutRunSet", handle, channel_index, run_s)

    def analog_out_run_get(self, handle: int, channel_index: int) -> float:
        return self._analog_out_get_double("FDwfAnalogOutRunGet", handle, channel_index)

    def analog_out_wait_set(self, handle: int, channel_index: int, wait_s: float) -> None:
        self._analog_out_set_double("FDwfAnalogOutWaitSet", handle, channel_index, wait_s)

    def analog_out_wait_get(self, handle: int, channel_index: int) -> float:
        return self._analog_out_get_double("FDwfAnalogOutWaitGet", handle, channel_index)

    def analog_out_repeat_set(self, handle: int, channel_index: int, repeat_count: int) -> None:
        self._analog_out_set_int("FDwfAnalogOutRepeatSet", handle, channel_index, repeat_count)

    def analog_out_repeat_get(self, handle: int, channel_index: int) -> int:
        return self._analog_out_get_int("FDwfAnalogOutRepeatGet", handle, channel_index)

    def analog_out_repeat_trigger_set(self, handle: int, channel_index: int, repeat_trigger: bool) -> None:
        self._analog_out_set_int("FDwfAnalogOutRepeatTriggerSet", handle, channel_index, int(repeat_trigger))

    def analog_out_repeat_trigger_get(self, handle: int, channel_index: int) -> bool:
        return bool(self._analog_out_get_int("FDwfAnalogOutRepeatTriggerGet", handle, channel_index))

    def analog_out_trigger_source_set(self, handle: int, channel_index: int, trigger_source: int | TriggerSource) -> None:
        self._analog_out_set_int("FDwfAnalogOutTriggerSourceSet", handle, channel_index, self._enum_value(self._TRIGGER_SOURCES, trigger_source))

    def analog_out_trigger_source_get(self, handle: int, channel_index: int) -> int:
        return self._analog_out_get_int("FDwfAnalogOutTriggerSourceGet", handle, channel_index)

    def analog_out_idle_set(self, handle: int, channel_index: int, idle: int) -> None:
        self._analog_out_set_int("FDwfAnalogOutIdleSet", handle, channel_index, idle)

    def analog_out_master_set(self, handle: int, channel_index: int, master_channel_index: int) -> None:
        self._analog_out_set_int("FDwfAnalogOutMasterSet", handle, channel_index, master_channel_index)

    def analog_out_configure(self, handle: int, channel_index: int, start: bool) -> None:
        # Real reachable call site: hardware_tests/test_real_workflow_smoke.py's
        # safe_disable_ad2_outputs() (real post-test AD2 output cleanup).
        with log_call("ad2", "analog_out_configure", command=(channel_index, start)) as result:
            self._analog_out_set_int("FDwfAnalogOutConfigure", handle, channel_index, int(start))
            result["response"] = "applied"

    def configure_wfg(self, handle: int, config: WfgConfig) -> None:
        with log_call("ad2", "configure_wfg", command=f"{len(config.channels)} channel(s), running={config.running}") as result:
            h = c_int(handle)
            for channel in config.channels:
                idx = c_int(channel.channel_index)
                carrier_out_of_range = self._configure_analog_node(h, idx, 0, channel.carrier)
                fm_out_of_range = False
                if channel.fm_mod.enable:
                    fm_out_of_range = self._configure_analog_node(h, idx, 1, channel.fm_mod)
                # Session 51: never assigned True anywhere before this -- WfgConfig.
                # check_valid()/wfg_check_config_valid() existed but had no producer,
                # so they always reported "valid" regardless of what was actually
                # applied. Now reflects whether *this* configure_wfg() call clamped
                # either node's frequency/amplitude against the device's own real
                # AnalogOutNode*Info() range.
                channel.out_of_range = carrier_out_of_range or fm_out_of_range

                trigger = channel.trigger
                self._check(self._dwf.FDwfAnalogOutRunSet(h, idx, c_double(trigger.sec_run)), "FDwfAnalogOutRunSet")
                self._check(self._dwf.FDwfAnalogOutWaitSet(h, idx, c_double(trigger.sec_wait)), "FDwfAnalogOutWaitSet")
                self._check(self._dwf.FDwfAnalogOutRepeatSet(h, idx, c_int(trigger.repeat_count)), "FDwfAnalogOutRepeatSet")
                self._check(
                    self._dwf.FDwfAnalogOutRepeatTriggerSet(h, idx, c_int(int(trigger.repeat_trigger))),
                    "FDwfAnalogOutRepeatTriggerSet",
                )
                self._check(
                    self._dwf.FDwfAnalogOutTriggerSourceSet(
                        h,
                        idx,
                        c_int(self._enum_value(self._TRIGGER_SOURCES, trigger.source)),
                    ),
                    "FDwfAnalogOutTriggerSourceSet",
                )
                self._check(
                    self._dwf.FDwfAnalogOutConfigure(h, idx, c_int(int(config.running))),
                    "FDwfAnalogOutConfigure",
                )
            result["response"] = f"applied, out_of_range={[c.out_of_range for c in config.channels]}"

    def _configure_analog_node(self, handle: c_int, channel_index: c_int, node: int, settings: object) -> bool:
        node_id = c_int(node)
        self._check(
            self._dwf.FDwfAnalogOutNodeEnableSet(handle, channel_index, node_id, c_int(int(settings.enable))),
            "FDwfAnalogOutNodeEnableSet",
        )
        self._check(
            self._dwf.FDwfAnalogOutNodeFunctionSet(
                handle,
                channel_index,
                node_id,
                c_int(self._enum_value(self._FUNCTIONS, settings.function)),
            ),
            "FDwfAnalogOutNodeFunctionSet",
        )

        # Session 51: the WaveForms SDK's own *Set functions never fail or
        # reject an out-of-range value -- they silently clamp to whatever the
        # device can actually do and still report success (confirmed against
        # Digilent's own WaveForms SDK reference manual). So validate/clamp
        # against the device's own live-read AnalogOutNode*Info() range
        # ourselves, before the Set calls below, rather than trusting the SDK
        # to reject anything or relying on a later Get-based readback to
        # notice the substitution after the fact.
        frequency_min = c_double()
        frequency_max = c_double()
        self._check(
            self._dwf.FDwfAnalogOutNodeFrequencyInfo(handle, channel_index, node_id, byref(frequency_min), byref(frequency_max)),
            "FDwfAnalogOutNodeFrequencyInfo",
        )
        amplitude_min = c_double()
        amplitude_max = c_double()
        self._check(
            self._dwf.FDwfAnalogOutNodeAmplitudeInfo(handle, channel_index, node_id, byref(amplitude_min), byref(amplitude_max)),
            "FDwfAnalogOutNodeAmplitudeInfo",
        )
        clamped_frequency_hz = min(max(settings.frequency_hz, frequency_min.value), frequency_max.value)
        clamped_amplitude_v = min(max(settings.amplitude_v, amplitude_min.value), amplitude_max.value)
        out_of_range = clamped_frequency_hz != settings.frequency_hz or clamped_amplitude_v != settings.amplitude_v

        self._check(
            self._dwf.FDwfAnalogOutNodeFrequencySet(handle, channel_index, node_id, c_double(clamped_frequency_hz)),
            "FDwfAnalogOutNodeFrequencySet",
        )
        self._check(
            self._dwf.FDwfAnalogOutNodeAmplitudeSet(handle, channel_index, node_id, c_double(clamped_amplitude_v)),
            "FDwfAnalogOutNodeAmplitudeSet",
        )
        self._check(
            self._dwf.FDwfAnalogOutNodeOffsetSet(handle, channel_index, node_id, c_double(settings.offset_v)),
            "FDwfAnalogOutNodeOffsetSet",
        )
        self._check(
            self._dwf.FDwfAnalogOutNodeSymmetrySet(handle, channel_index, node_id, c_double(settings.symmetry_percent)),
            "FDwfAnalogOutNodeSymmetrySet",
        )
        self._check(
            self._dwf.FDwfAnalogOutNodePhaseSet(handle, channel_index, node_id, c_double(settings.phase_deg)),
            "FDwfAnalogOutNodePhaseSet",
        )
        return out_of_range

    def configure_do(self, handle: int, config: DoConfig) -> None:
        with log_call("ad2", "configure_do", command=f"{len(config.channels)} channel(s), running={config.running}") as result:
            h = c_int(handle)
            trigger = None
            trigger_source = TriggerSource.NONE
            # WaveForms exposes Wait/Run/Repeat/TriggerSource once for the
            # whole DigitalOut instrument, not once per channel. Refuse an
            # ambiguous multi-channel request rather than silently applying
            # the last channel's timing to every enabled output.
            trigger_signatures = {
                (
                    float(channel.trigger.sec_wait),
                    float(channel.trigger.sec_run),
                    int(channel.trigger.repeat_count),
                    bool(channel.trigger.repeat_trigger),
                    str(channel.trigger.source),
                )
                for channel in config.channels
                if channel.enable
            }
            if len(trigger_signatures) > 1:
                raise WaveFormsError(
                    "Digital output channels request different global trigger timing; "
                    "WaveForms applies one Wait/Run/Repeat/TriggerSource configuration to the whole device."
                )
            for channel in config.channels:
                idx = c_int(channel.channel_index)
                # These settings are device-global. Only an enabled line may
                # select them; otherwise a trailing disabled channel could
                # silently replace the timing intended for the live output.
                if channel.enable:
                    trigger = channel.trigger
                    trigger_source = channel.trigger.source
                bits = channel.custom_data.bits
                clock_divider = channel.clock_divider
                if channel.clock_frequency_hz is not None:
                    if channel.clock_frequency_hz <= 0:
                        raise WaveFormsError("Digital output clock frequency must be greater than 0 Hz.")
                    internal_clock_hz = self.digital_out_internal_clock_info(handle)
                    if internal_clock_hz <= 0:
                        raise WaveFormsError("Digital output internal clock frequency is not available.")
                    clock_divider = int((internal_clock_hz / channel.clock_frequency_hz) / 2.0)
                    # Finding E: clock_divider is an integer, so the real achieved
                    # frequency can differ from the requested clock_frequency_hz --
                    # record it so that gap is visible instead of only ever
                    # recording the requested value. clock_divider == 0 (requested
                    # frequency close to/above internal_clock_hz/2) is left
                    # unrecorded rather than guessed at -- this codebase has no
                    # confirmed real-hardware behavior for a zero divider to derive
                    # an achieved-frequency formula from.
                    channel.achieved_clock_frequency_hz = (
                        internal_clock_hz / (2.0 * clock_divider) if clock_divider > 0 else None
                    )

                self._check(self._dwf.FDwfDigitalOutEnableSet(h, idx, c_int(int(channel.enable))), "FDwfDigitalOutEnableSet")
                self._check(
                    self._dwf.FDwfDigitalOutDividerSet(h, idx, c_uint(max(clock_divider, 0))),
                    "FDwfDigitalOutDividerSet",
                )
                self._check(
                    self._dwf.FDwfDigitalOutCounterInitSet(
                        h,
                        idx,
                        c_int(int(channel.start_high)),
                        c_uint(max(channel.counter_initial_bits, 0)),
                    ),
                    "FDwfDigitalOutCounterInitSet",
                )
                self._check(
                    self._dwf.FDwfDigitalOutCounterSet(
                        h,
                        idx,
                        c_uint(max(channel.counter_low_bits, 0)),
                        c_uint(max(channel.counter_high_bits, 0)),
                    ),
                    "FDwfDigitalOutCounterSet",
                )
                self._check(
                    self._dwf.FDwfDigitalOutTypeSet(
                        h,
                        idx,
                        c_int(self._enum_value(self._DO_TYPES, channel.output_type)),
                    ),
                    "FDwfDigitalOutTypeSet",
                )
                self._check(
                    self._dwf.FDwfDigitalOutIdleSet(
                        h,
                        idx,
                        c_int(self._enum_value(self._DO_IDLE, channel.idle_state)),
                    ),
                    "FDwfDigitalOutIdleSet",
                )
                self._check(
                    self._dwf.FDwfDigitalOutOutputSet(
                        h,
                        idx,
                        c_int(self._output_mode_value(channel.output_mode)),
                    ),
                    "FDwfDigitalOutOutputSet",
                )
                if bits:
                    data = (c_ubyte * len(bits))(*[int(bool(bit)) for bit in bits])
                    self._check(
                        self._dwf.FDwfDigitalOutDataSet(h, idx, data, c_int(len(bits))),
                        "FDwfDigitalOutDataSet",
                    )

            if trigger is not None:
                self._check(self._dwf.FDwfDigitalOutWaitSet(h, c_double(trigger.sec_wait)), "FDwfDigitalOutWaitSet")
                self._check(self._dwf.FDwfDigitalOutRunSet(h, c_double(trigger.sec_run)), "FDwfDigitalOutRunSet")
                self._check(self._dwf.FDwfDigitalOutRepeatSet(h, c_int(trigger.repeat_count)), "FDwfDigitalOutRepeatSet")
                self._check(
                    self._dwf.FDwfDigitalOutRepeatTriggerSet(h, c_int(int(trigger.repeat_trigger))),
                    "FDwfDigitalOutRepeatTriggerSet",
                )
            self._check(
                self._dwf.FDwfDigitalOutTriggerSourceSet(
                    h,
                    c_int(self._enum_value(self._TRIGGER_SOURCES, trigger_source)),
                ),
                "FDwfDigitalOutTriggerSourceSet",
            )
            self._check(self._dwf.FDwfDigitalOutConfigure(h, c_int(int(config.running))), "FDwfDigitalOutConfigure")
            result["response"] = f"applied, achieved_clock_hz={[c.achieved_clock_frequency_hz for c in config.channels]}"

    def reset_do(self, handle: int) -> None:
        with log_call("ad2", "reset_do", command=handle) as result:
            self._check(self._dwf.FDwfDigitalOutReset(c_int(handle)), "FDwfDigitalOutReset")
            result["response"] = "reset"

    def digital_out_count(self, handle: int) -> int:
        count = c_int()
        self._check(self._dwf.FDwfDigitalOutCount(c_int(handle), byref(count)), "FDwfDigitalOutCount")
        return count.value

    def digital_out_internal_clock_info(self, handle: int) -> float:
        clock_hz = c_double()
        self._check(self._dwf.FDwfDigitalOutInternalClockInfo(c_int(handle), byref(clock_hz)), "FDwfDigitalOutInternalClockInfo")
        return clock_hz.value

    def digital_out_enable_set(self, handle: int, channel_index: int, enabled: bool) -> None:
        self._check(
            self._dwf.FDwfDigitalOutEnableSet(c_int(handle), c_int(channel_index), c_int(int(enabled))),
            "FDwfDigitalOutEnableSet",
        )

    def digital_out_divider_set(self, handle: int, channel_index: int, divider: int) -> None:
        self._check(
            self._dwf.FDwfDigitalOutDividerSet(c_int(handle), c_int(channel_index), c_uint(max(divider, 0))),
            "FDwfDigitalOutDividerSet",
        )

    def digital_out_divider_info(self, handle: int, channel_index: int) -> tuple[int, int]:
        minimum = c_uint()
        maximum = c_uint()
        self._check(
            self._dwf.FDwfDigitalOutDividerInfo(c_int(handle), c_int(channel_index), byref(minimum), byref(maximum)),
            "FDwfDigitalOutDividerInfo",
        )
        return minimum.value, maximum.value

    def digital_out_counter_init_set(self, handle: int, channel_index: int, start_high: bool, initial_bits: int) -> None:
        self._check(
            self._dwf.FDwfDigitalOutCounterInitSet(
                c_int(handle),
                c_int(channel_index),
                c_int(int(start_high)),
                c_uint(max(initial_bits, 0)),
            ),
            "FDwfDigitalOutCounterInitSet",
        )

    def digital_out_counter_set(self, handle: int, channel_index: int, low_bits: int, high_bits: int) -> None:
        self._check(
            self._dwf.FDwfDigitalOutCounterSet(
                c_int(handle),
                c_int(channel_index),
                c_uint(max(low_bits, 0)),
                c_uint(max(high_bits, 0)),
            ),
            "FDwfDigitalOutCounterSet",
        )

    def digital_out_type_set(self, handle: int, channel_index: int, output_type: int | DigitalOutType) -> None:
        mapped = self._enum_value(self._DO_TYPES, output_type)
        self._check(
            self._dwf.FDwfDigitalOutTypeSet(c_int(handle), c_int(channel_index), c_int(mapped)),
            "FDwfDigitalOutTypeSet",
        )

    def digital_out_idle_set(self, handle: int, channel_index: int, idle_state: int | DigitalOutIdleState) -> None:
        mapped = self._enum_value(self._DO_IDLE, idle_state)
        self._check(
            self._dwf.FDwfDigitalOutIdleSet(c_int(handle), c_int(channel_index), c_int(mapped)),
            "FDwfDigitalOutIdleSet",
        )

    def digital_out_data_set(self, handle: int, channel_index: int, bits: list[int]) -> None:
        data = (c_ubyte * len(bits))(*[int(bool(bit)) for bit in bits])
        self._check(
            self._dwf.FDwfDigitalOutDataSet(c_int(handle), c_int(channel_index), data, c_int(len(bits))),
            "FDwfDigitalOutDataSet",
        )

    def digital_out_data_info(self, handle: int, channel_index: int) -> int:
        maximum = c_uint()
        self._check(self._dwf.FDwfDigitalOutDataInfo(c_int(handle), c_int(channel_index), byref(maximum)), "FDwfDigitalOutDataInfo")
        return maximum.value

    def digital_out_wait_set(self, handle: int, wait_s: float) -> None:
        self._check(self._dwf.FDwfDigitalOutWaitSet(c_int(handle), c_double(wait_s)), "FDwfDigitalOutWaitSet")

    def digital_out_run_set(self, handle: int, run_s: float) -> None:
        self._check(self._dwf.FDwfDigitalOutRunSet(c_int(handle), c_double(run_s)), "FDwfDigitalOutRunSet")

    def digital_out_repeat_set(self, handle: int, repeat_count: int) -> None:
        self._check(self._dwf.FDwfDigitalOutRepeatSet(c_int(handle), c_int(repeat_count)), "FDwfDigitalOutRepeatSet")

    def digital_out_repeat_trigger_set(self, handle: int, repeat_trigger: bool) -> None:
        self._check(self._dwf.FDwfDigitalOutRepeatTriggerSet(c_int(handle), c_int(int(repeat_trigger))), "FDwfDigitalOutRepeatTriggerSet")

    def digital_out_trigger_source_set(self, handle: int, trigger_source: int | TriggerSource) -> None:
        mapped = self._enum_value(self._TRIGGER_SOURCES, trigger_source)
        self._check(self._dwf.FDwfDigitalOutTriggerSourceSet(c_int(handle), c_int(mapped)), "FDwfDigitalOutTriggerSourceSet")

    def digital_out_configure(self, handle: int, start: bool) -> None:
        # Real reachable call site: hardware_tests/test_real_workflow_smoke.py's
        # safe_disable_ad2_outputs() (real post-test AD2 output cleanup).
        with log_call("ad2", "digital_out_configure", command=start) as result:
            self._check(self._dwf.FDwfDigitalOutConfigure(c_int(handle), c_int(int(start))), "FDwfDigitalOutConfigure")
            result["response"] = "applied"

    def capture_analog_in(
        self,
        handle: int,
        *,
        channel_index: int = 0,
        sample_frequency_hz: float = 10_000.0,
        sample_count: int = 4096,
        range_v: float = 1.0,
        offset_v: float = 0.0,
        timeout_s: float = 5.0,
    ) -> list[float]:
        with log_call(
            "ad2", "capture_analog_in",
            command=f"ch={channel_index}, fs={sample_frequency_hz}, n={sample_count}, range={range_v}",
        ) as log_result:
            h = c_int(handle)
            idx = c_int(channel_index)
            count = max(1, int(sample_count))

            self._check(self._dwf.FDwfAnalogInChannelEnableSet(h, idx, c_int(1)), "FDwfAnalogInChannelEnableSet")
            self._check(self._dwf.FDwfAnalogInChannelRangeSet(h, idx, c_double(range_v)), "FDwfAnalogInChannelRangeSet")
            self._check(self._dwf.FDwfAnalogInChannelOffsetSet(h, idx, c_double(offset_v)), "FDwfAnalogInChannelOffsetSet")
            self._check(self._dwf.FDwfAnalogInFrequencySet(h, c_double(sample_frequency_hz)), "FDwfAnalogInFrequencySet")
            self._check(self._dwf.FDwfAnalogInBufferSizeSet(h, c_int(count)), "FDwfAnalogInBufferSizeSet")
            self._check(self._dwf.FDwfAnalogInConfigure(h, c_int(1), c_int(1)), "FDwfAnalogInConfigure")

            # Not logging each poll iteration individually (this loop can run
            # hundreds of times per capture) -- only the terminal outcome, via
            # the outer log_call above, matching the "diagnostic log, not a
            # database" instruction.
            status = c_int()
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                self._check(self._dwf.FDwfAnalogInStatus(h, c_int(1), byref(status)), "FDwfAnalogInStatus")
                if status.value == 2:
                    break
                time.sleep(0.01)
            else:
                raise WaveFormsError("AnalogIn capture timed out before acquisition completed.")

            samples = (c_double * count)()
            self._check(self._dwf.FDwfAnalogInStatusData(h, idx, samples, c_int(count)), "FDwfAnalogInStatusData")
            result = list(samples)
            log_result["response"] = f"{len(result)} samples, first={result[:3]}"
        return result

    def analog_in_trigger_source_set(self, handle: int, trigger_source: int | TriggerSource) -> None:
        mapped = self._enum_value(self._TRIGGER_SOURCES, trigger_source)
        self._check(self._dwf.FDwfAnalogInTriggerSourceSet(c_int(handle), c_int(mapped)), "FDwfAnalogInTriggerSourceSet")

    def capture_analog_in_channels(
        self,
        handle: int,
        *,
        channel_indices: list[int],
        sample_frequency_hz: float = 10_000.0,
        sample_count: int = 4096,
        range_v: float = 1.0,
        offset_v: float = 0.0,
        trigger_source: TriggerSource | str = TriggerSource.NONE,
        timeout_s: float = 5.0,
    ) -> dict[int, list[float]]:
        h = c_int(handle)
        count = max(1, int(sample_count))
        selected = sorted(set(int(index) for index in channel_indices))
        if not selected:
            return {}

        with log_call(
            "ad2", "capture_analog_in_channels",
            command=f"channels={selected}, fs={sample_frequency_hz}, n={sample_count}, trigger={trigger_source}",
        ) as log_result:
            for index in (0, 1):
                self._check(
                    self._dwf.FDwfAnalogInChannelEnableSet(h, c_int(index), c_int(1 if index in selected else 0)),
                    "FDwfAnalogInChannelEnableSet",
                )
            for index in selected:
                idx = c_int(index)
                self._check(self._dwf.FDwfAnalogInChannelRangeSet(h, idx, c_double(range_v)), "FDwfAnalogInChannelRangeSet")
                self._check(self._dwf.FDwfAnalogInChannelOffsetSet(h, idx, c_double(offset_v)), "FDwfAnalogInChannelOffsetSet")
            self._check(self._dwf.FDwfAnalogInFrequencySet(h, c_double(sample_frequency_hz)), "FDwfAnalogInFrequencySet")
            self._check(self._dwf.FDwfAnalogInBufferSizeSet(h, c_int(count)), "FDwfAnalogInBufferSizeSet")
            self.analog_in_trigger_source_set(handle, trigger_source)
            self._check(self._dwf.FDwfAnalogInConfigure(h, c_int(1), c_int(1)), "FDwfAnalogInConfigure")

            # Not logging each poll iteration individually -- see
            # capture_analog_in()'s matching comment above.
            status = c_int()
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                self._check(self._dwf.FDwfAnalogInStatus(h, c_int(1), byref(status)), "FDwfAnalogInStatus")
                if status.value == 2:
                    break
                time.sleep(0.01)
            else:
                raise WaveFormsError("AnalogIn capture timed out before acquisition completed.")

            captured: dict[int, list[float]] = {}
            for index in selected:
                samples = (c_double * count)()
                self._check(self._dwf.FDwfAnalogInStatusData(h, c_int(index), samples, c_int(count)), "FDwfAnalogInStatusData")
                captured[index] = list(samples)
            log_result["response"] = f"channels={list(captured.keys())}, {count} samples each"
        return captured
