"""Manual, gated WFG1-to-Scope1 loopback probe; never run in automated tests."""

from __future__ import annotations

__test__ = False

import argparse
import csv
import json
import math
import statistics
import sys
import time
from ctypes import byref, c_double, c_int
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


CONFIRMATION = "CONFIRM_REAL_AD2_WFG1_SCOPE1_LOOPBACK"
SAMPLE_RATE_HZ = 20_000.0
SAMPLE_COUNT = 2_048
RUN_S = 3.0
CASES = ("dc_disabled", "square_min_frequency_offset")
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voltage-v", type=float, required=True,
                        help="Positive loopback test voltage in volts; no default")
    parser.add_argument("--confirm", required=True,
                        help=f"Exact hardware acknowledgement: {CONFIRMATION}")
    args = parser.parse_args()
    if args.confirm != CONFIRMATION:
        parser.error(f"refusing hardware access without --confirm {CONFIRMATION}")
    if not math.isfinite(args.voltage_v) or not 0 < args.voltage_v <= 5:
        parser.error("--voltage-v must be finite and greater than 0, at most 5 V")
    return args


def sdk_capabilities(ad2) -> dict:
    """Read the exact channel-0 masks/range before sending a WFG setting."""
    handle = ad2.device_handle
    if handle is None:
        raise RuntimeError("AD2 did not open")
    idle_mask = c_int()
    minimum = c_double()
    maximum = c_double()
    ad2._check(ad2._dwf.FDwfAnalogOutIdleInfo(c_int(handle), c_int(0), byref(idle_mask)),
               "FDwfAnalogOutIdleInfo")
    ad2._check(ad2._dwf.FDwfAnalogOutNodeFrequencyInfo(
        c_int(handle), c_int(0), c_int(0), byref(minimum), byref(maximum)),
        "FDwfAnalogOutNodeFrequencyInfo")
    return {
        "idle_mask": idle_mask.value,
        "idle_supported": {
            name: bool(idle_mask.value & (1 << index))
            for index, name in enumerate(("Disabled", "Offset", "Initial", "Hold"))
        },
        "carrier_frequency_range_hz": [minimum.value, maximum.value],
    }


def wavegen_status(ad2) -> dict:
    handle = ad2.device_handle
    if handle is None:
        raise RuntimeError("AD2 is not open")
    state = c_int()
    ad2._check(ad2._dwf.FDwfAnalogOutStatus(c_int(handle), c_int(0), byref(state)),
               "FDwfAnalogOutStatus")
    names = {0: "ready", 1: "armed", 2: "done", 3: "running",
             4: "config", 5: "prefill", 7: "wait"}
    return {"code": state.value, "name": names.get(state.value, "unknown")}


def await_wavegen_status(ad2, expected: str, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = wavegen_status(ad2)
        if last["name"] == expected:
            return last
        time.sleep(0.01)
    raise RuntimeError(f"WFG1 did not reach {expected} within {timeout_s:g} s; last={last}")


def make_config(case: str, voltage_v: float, minimum_frequency_hz: float):
    from thermo_acoustic.drivers.ad2.configuration import (
        AnalogOutputIdleState, CarrierSettings, TriggerSettings, TriggerSource,
        WaveformFunction, WfgChannelConfig, WfgConfig,
    )

    if case == "dc_disabled":
        carrier = CarrierSettings(function=WaveformFunction.DC, frequency_hz=1.0,
                                  amplitude_v=0.0, offset_v=voltage_v,
                                  phase_deg=0.0, enable=True)
        idle = AnalogOutputIdleState.DISABLED
    else:
        carrier = CarrierSettings(function=WaveformFunction.SQUARE,
                                  frequency_hz=minimum_frequency_hz,
                                  amplitude_v=voltage_v, offset_v=0.0,
                                  phase_deg=0.0, enable=True)
        idle = AnalogOutputIdleState.OFFSET
    channel = WfgChannelConfig(
        channel_index=0, carrier=carrier, idle_state=idle,
        trigger=TriggerSettings(source=TriggerSource.PC, sec_wait=0.0,
                                sec_run=RUN_S, repeat_count=1),
    )
    return WfgConfig(running=True, channels=[channel])


def capture_phase(ad2, case_dir: Path, phase: str, scope_range_v: float) -> dict:
    state_before = wavegen_status(ad2)
    started_at = utc_now()
    samples = ad2.capture_scope(channel_index=0,
                                sample_frequency_hz=SAMPLE_RATE_HZ,
                                sample_count=SAMPLE_COUNT, range_v=scope_range_v)
    ended_at = utc_now()
    state_after = wavegen_status(ad2)
    csv_path = case_dir / f"{phase}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("sample_index", "relative_time_s", "voltage_v"))
        writer.writerows((index, index / SAMPLE_RATE_HZ, voltage)
                         for index, voltage in enumerate(samples))
    return {
        "csv": csv_path.name,
        "started_utc": started_at,
        "ended_utc": ended_at,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "sample_count": len(samples),
        "scope_range_v": scope_range_v,
        "wfg_status_before": state_before,
        "wfg_status_after": state_after,
        "min_v": min(samples),
        "max_v": max(samples),
        "mean_v": statistics.fmean(samples),
    }


def run_case(case: str, voltage_v: float, run_dir: Path) -> dict:
    # Import and create the driver only after the explicit hardware gate.
    from thermo_acoustic.drivers.ad2 import AnalogDiscovery2

    case_dir = run_dir / case
    case_dir.mkdir()
    record: dict = {
        "case": case,
        "status": "failed",
        "started_utc": utc_now(),
        "scope_capture_method": "three sequential short captures, not a continuous trigger-aligned trace",
        "captures": {},
        "events": [],
    }
    ad2 = None
    try:
        ad2 = AnalogDiscovery2()
        ad2.initialize()
        record["events"].append({"event": "device_opened", "utc": utc_now()})
        record["sdk_capabilities"] = sdk_capabilities(ad2)
        if case == "dc_disabled" and not record["sdk_capabilities"]["idle_supported"]["Disabled"]:
            record["status"] = "skipped_unsupported_idle"
            return record
        if case == "square_min_frequency_offset" and not record["sdk_capabilities"]["idle_supported"]["Offset"]:
            record["status"] = "skipped_unsupported_idle"
            return record

        minimum_frequency_hz = record["sdk_capabilities"]["carrier_frequency_range_hz"][0]
        config = make_config(case, voltage_v, minimum_frequency_hz)
        record["requested"] = asdict(config)
        record["requested_minimum_frequency_hz"] = minimum_frequency_hz
        ad2.wfg_configure(config)
        record["events"].append({"event": "wfg_armed", "utc": utc_now()})
        try:
            record["sdk_readback"] = asdict(ad2.wfg_readback())
            if case == "square_min_frequency_offset":
                actual_hz = record["sdk_readback"]["channels"][0]["carrier"]["frequency_hz"]
                record["frequency_readback_hz"] = actual_hz
                record["frequency_readback_matches_minimum"] = math.isclose(
                    actual_hz, minimum_frequency_hz, rel_tol=1e-9, abs_tol=0.0)
        except Exception as exc:
            record["readback_error"] = f"{type(exc).__name__}: {exc}"

        # Capture windows are short relative to the 3 s output run.
        scope_range_v = max(1.0, 2.0 * voltage_v)
        record["captures"]["armed_idle"] = capture_phase(ad2, case_dir, "armed_idle", scope_range_v)
        if record["captures"]["armed_idle"]["wfg_status_after"]["name"] not in {"armed", "wait"}:
            raise RuntimeError("WFG1 was not waiting for the PC trigger during idle capture")
        ad2.pc_trigger()
        record["events"].append({"event": "pc_trigger_sent", "utc": utc_now()})
        await_wavegen_status(ad2, "running", 1.0)
        record["captures"]["running"] = capture_phase(ad2, case_dir, "running", scope_range_v)
        if record["captures"]["running"]["wfg_status_before"]["name"] != "running":
            raise RuntimeError("WFG1 was not running at the start of active capture")
        await_wavegen_status(ad2, "done", RUN_S + 1.0)
        record["captures"]["done_idle"] = capture_phase(ad2, case_dir, "done_idle", scope_range_v)
        record["status"] = "captured"
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if ad2 is not None:
            try:
                ad2.cleanup()
                record["events"].append({"event": "device_cleaned_up", "utc": utc_now()})
            except Exception as exc:
                record["cleanup_error"] = f"{type(exc).__name__}: {exc}"
                record["status"] = "failed_cleanup"
        record["finished_utc"] = utc_now()
        write_json(case_dir / "case.json", record)
    return record


def main() -> int:
    args = parse_args()
    # No device library is imported before the gate and input validation above.
    run_dir = RESULTS_DIR / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True)
    manifest = {
        "probe": "wfg_dc_sine_idle_test",
        "started_utc": utc_now(),
        "wiring_required": "WFG1 to Scope1 BNC loopback only; laser and other loads disconnected",
        "requested_voltage_v": args.voltage_v,
        "cases": {},
    }
    write_json(run_dir / "manifest.json", manifest)
    for case in CASES:
        print(f"Running {case}...", flush=True)
        record = run_case(case, args.voltage_v, run_dir)
        manifest["cases"][case] = {"status": record["status"], "path": f"{case}/case.json"}
        write_json(run_dir / "manifest.json", manifest)
        print(f"{case}: {record['status']}", flush=True)
        if record["status"] == "failed_cleanup":
            print("Stopping: AD2 cleanup failed; physical output state is uncertain.",
                  file=sys.stderr, flush=True)
            break
    manifest["finished_utc"] = utc_now()
    write_json(run_dir / "manifest.json", manifest)
    print(f"Results: {run_dir}")
    return 0 if all(item["status"] == "captured" for item in manifest["cases"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
