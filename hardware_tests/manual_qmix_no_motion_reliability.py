"""Bounded no-motion Qmix/CAN reliability probe.

This manual diagnostic is intentionally outside pytest collection. It opens
and starts the reviewed project, reads passive status/error state, then stops
and closes. It never enables, clears a fault, references, calibrates, or moves
a pump. A cleanup failure stops the trial series to avoid reopening over an
uncertain/stale bus owner.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time


__test__ = False

ROOT = Path(__file__).resolve().parents[1]
HARDWARE_TESTS = ROOT / "hardware_tests"
if str(HARDWARE_TESTS) not in sys.path:
    sys.path.insert(0, str(HARDWARE_TESTS))

from test_qmix_discovery import import_qmix, validate_path  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(record: dict[str, object]) -> None:
    print(json.dumps(record, sort_keys=True), flush=True)


def measured_call(label: str, action) -> tuple[bool, float, object | None]:
    started = time.monotonic()
    try:
        result = action()
    except Exception as exc:
        duration = time.monotonic() - started
        emit(
            {
                "event": label,
                "ok": False,
                "duration_s": duration,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "error_code": getattr(exc, "errorcode", None),
                "timestamp_utc": utc_now(),
            }
        )
        return False, duration, exc
    duration = time.monotonic() - started
    emit(
        {
            "event": label,
            "ok": True,
            "duration_s": duration,
            "result": result,
            "timestamp_utc": utc_now(),
        }
    )
    return True, duration, result


def main() -> int:
    parser = argparse.ArgumentParser(description="Repeated no-motion Qmix/CAN reliability probe.")
    parser.add_argument("--sdk-python-path", type=Path, required=True)
    parser.add_argument(
        "--qmixsdk-path",
        type=Path,
        required=True,
        help="Directory containing the CETONI runtime DLLs; exported as QMIXSDK before import.",
    )
    parser.add_argument("--config-path", type=Path, required=True)
    parser.add_argument("--pump-index", type=int, default=0)
    parser.add_argument("--trials", type=int, choices=range(3, 6), default=3)
    parser.add_argument(
        "--confirm",
        help="Must be exactly NO_MOTION_CAN to open/start the bus.",
    )
    args = parser.parse_args()
    if args.confirm != "NO_MOTION_CAN":
        raise SystemExit("Refusing to open/start Qmix without --confirm NO_MOTION_CAN")

    validate_path("Qmix configuration path", args.config_path)
    validate_path("Qmix SDK runtime path", args.qmixsdk_path)
    os.environ["QMIXSDK"] = str(args.qmixsdk_path)
    qmixbus, qmixpump = import_qmix(args.sdk_python_path)
    emit(
        {
            "event": "series_start",
            "config_path": str(args.config_path),
            "pump_index": args.pump_index,
            "requested_trials": args.trials,
            "timestamp_utc": utc_now(),
            "policy": "no enable, no fault clear, no motion",
        }
    )

    successful_trials = 0
    for trial in range(1, args.trials + 1):
        opened = False
        started = False
        cleanup_ok = True
        emit({"event": "trial_start", "trial": trial, "timestamp_utc": utc_now()})
        try:
            ok, _duration, _result = measured_call(
                "bus_open",
                lambda: qmixbus.Bus.open(str(args.config_path), 0),
            )
            if not ok:
                break
            opened = True
            ok, _duration, _result = measured_call("bus_start", qmixbus.Bus.start)
            if not ok:
                break
            started = True

            pump_count = int(qmixpump.Pump.get_no_of_pumps())
            emit(
                {
                    "event": "pump_count",
                    "trial": trial,
                    "value": pump_count,
                    "timestamp_utc": utc_now(),
                }
            )
            if args.pump_index < 0 or args.pump_index >= pump_count:
                raise IndexError(f"pump index {args.pump_index} outside 0..{pump_count - 1}")
            pump = qmixpump.Pump()
            pump.lookup_by_device_index(args.pump_index)
            last_error = pump.read_last_error()
            emit(
                {
                    "event": "pump_status",
                    "trial": trial,
                    "pump_name": pump.get_pump_name(),
                    "device_name": pump.get_device_name(),
                    "node_id": pump.get_node_id(),
                    "fault": pump.is_in_fault_state(),
                    "enabled": pump.is_enabled(),
                    "pumping": pump.is_pumping(),
                    "position_sensing_initialized": pump.is_position_sensing_initialized(),
                    "last_error_code": last_error.code,
                    "last_error_message": last_error.message,
                    "timestamp_utc": utc_now(),
                }
            )
            successful_trials += 1
        except Exception as exc:
            emit(
                {
                    "event": "trial_error",
                    "trial": trial,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "error_code": getattr(exc, "errorcode", None),
                    "timestamp_utc": utc_now(),
                }
            )
        finally:
            if started:
                ok, _duration, _result = measured_call("bus_stop", qmixbus.Bus.stop)
                cleanup_ok = cleanup_ok and ok
            if opened:
                ok, _duration, _result = measured_call("bus_close", qmixbus.Bus.close)
                cleanup_ok = cleanup_ok and ok
            emit(
                {
                    "event": "trial_complete",
                    "trial": trial,
                    "cleanup_ok": cleanup_ok,
                    "timestamp_utc": utc_now(),
                }
            )
        if not cleanup_ok:
            emit(
                {
                    "event": "series_stopped",
                    "reason": "cleanup uncertainty; refusing another open",
                    "timestamp_utc": utc_now(),
                }
            )
            break
        time.sleep(0.5)

    emit(
        {
            "event": "series_complete",
            "successful_status_trials": successful_trials,
            "requested_trials": args.trials,
            "timestamp_utc": utc_now(),
        }
    )
    return 0 if successful_trials == args.trials else 1


if __name__ == "__main__":
    raise SystemExit(main())
