"""One-shot passive Qmix pump readiness snapshot.

This manual hardware procedure opens and starts the reviewed one-pump Qmix
project, reads pump identity and passive state, then stops and closes the bus.
Normal execution never clears a fault, enables/disables, references,
calibrates, restores a counter, configures a syringe, commands fill/flow, or
moves the pump. If and only if the first pumping-state read unexpectedly
reports active motion, it sends the established emergency ``stop_pumping()``
command and terminates with a safety-stop classification.

The script is outside pytest collection and requires an explicit confirmation
token before it may open/start the real bus.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, TextIO


__test__ = False

ROOT = Path(__file__).resolve().parents[1]
HARDWARE_TESTS = ROOT / "hardware_tests"
if str(HARDWARE_TESTS) not in sys.path:
    sys.path.insert(0, str(HARDWARE_TESTS))

from test_qmix_discovery import import_qmix, validate_path  # noqa: E402


CONFIRMATION = "CONFIRM_QMIX_READ_ONLY_READINESS"
EXPECTED_PUMP_NAME = "neMESYS_Low_Pressure_1_Pump"
EXPECTED_NODE_ID = 2
BLOCKED_PROCESS_MARKERS = ("qmix", "labview", "canana", "canalyser", "cananalyser")
OUTPUT: TextIO | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(record: dict[str, Any]) -> None:
    line = json.dumps(record, sort_keys=True)
    print(line, flush=True)
    if OUTPUT is not None:
        OUTPUT.write(line + "\n")
        OUTPUT.flush()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def assert_single_client_process_ownership() -> None:
    if os.name != "nt":
        raise RuntimeError("This hardware procedure is approved only for the current Windows host.")
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-Process | Select-Object Id,ProcessName | ConvertTo-Csv -NoTypeInformation",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    blockers: list[dict[str, object]] = []
    for row in csv.DictReader(io.StringIO(completed.stdout)):
        name = str(row.get("ProcessName", ""))
        try:
            pid = int(row.get("Id", ""))
        except (TypeError, ValueError):
            continue
        lowered = name.lower()
        is_other_python = lowered in {"python", "pythonw"} and pid != os.getpid()
        is_named_client = any(marker in lowered for marker in BLOCKED_PROCESS_MARKERS)
        if is_other_python or is_named_client:
            blockers.append({"name": name, "pid": pid})
    emit(
        {
            "event": "single_client_process_check",
            "current_pid": os.getpid(),
            "blockers": blockers,
            "ok": not blockers,
            "timestamp_utc": utc_now(),
        }
    )
    if blockers:
        raise RuntimeError(f"Possible competing Qmix/CAN client processes found: {blockers}")


def measured_call(label: str, action: Any) -> tuple[bool, Any]:
    started = time.monotonic()
    try:
        result = action()
    except Exception as exc:
        emit(
            {
                "event": label,
                "ok": False,
                "duration_s": time.monotonic() - started,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "error_code": getattr(exc, "errorcode", None),
                "timestamp_utc": utc_now(),
            }
        )
        return False, exc
    emit(
        {
            "event": label,
            "ok": True,
            "duration_s": time.monotonic() - started,
            "result": result,
            "timestamp_utc": utc_now(),
        }
    )
    return True, result


def unit_record(value: Any) -> dict[str, Any]:
    fields = getattr(value, "_fields", ())
    if fields:
        return {name: repr(getattr(value, name)) for name in fields}
    return {"repr": repr(value)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-shot passive Qmix readiness snapshot.")
    parser.add_argument("--sdk-python-path", type=Path, required=True)
    parser.add_argument("--qmixsdk-path", type=Path, required=True)
    parser.add_argument("--config-path", type=Path, required=True)
    parser.add_argument("--output-path", type=Path, required=True)
    parser.add_argument("--pump-index", type=int, choices=(0,), default=0)
    parser.add_argument("--expected-git-head", required=True)
    parser.add_argument("--confirm")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.confirm != CONFIRMATION:
        raise SystemExit(f"Refusing to open/start Qmix without --confirm {CONFIRMATION}")
    args.output_path.parent.mkdir(parents=True, exist_ok=True)

    global OUTPUT
    with args.output_path.open("x", encoding="utf-8", newline="\n") as output:
        OUTPUT = output
        opened = False
        started = False
        qmixbus = None
        classification = "SAFETY/TRANSPORT_STOP"
        cleanup_ok = True
        emergency_stop_sent = False
        try:
            current_head = git_head()
            emit(
                {
                    "event": "procedure_start",
                    "timestamp_utc": utc_now(),
                    "git_head": current_head,
                    "expected_git_head": args.expected_git_head,
                    "script_path": str(Path(__file__).resolve()),
                    "script_sha256": sha256_file(Path(__file__).resolve()),
                    "sdk_python_path": str(args.sdk_python_path),
                    "qmixsdk_path": str(args.qmixsdk_path),
                    "config_path": str(args.config_path),
                    "pump_index": args.pump_index,
                    "policy": "read-only pump state; emergency stop only if pumping is unexpectedly true",
                    "prohibited_calls": [
                        "clear_fault",
                        "enable",
                        "calibrate",
                        "restore_position_counter_value",
                        "set_fill_level",
                        "generate_flow",
                        "aspirate",
                        "dispense",
                    ],
                }
            )
            if current_head != args.expected_git_head:
                raise RuntimeError("Git HEAD mismatch")
            validate_path("Qmix configuration path", args.config_path)
            validate_path("Qmix SDK runtime path", args.qmixsdk_path)
            assert_single_client_process_ownership()
            os.environ["QMIXSDK"] = str(args.qmixsdk_path)
            qmixbus, qmixpump = import_qmix(args.sdk_python_path)
            emit(
                {
                    "event": "runtime_loaded",
                    "qmixbus_module": str(Path(qmixbus.__file__).resolve()),
                    "qmixpump_module": str(Path(qmixpump.__file__).resolve()),
                    "timestamp_utc": utc_now(),
                }
            )

            ok, _ = measured_call("bus_open", lambda: qmixbus.Bus.open(str(args.config_path), 0))
            if not ok:
                raise RuntimeError("Bus open failed")
            opened = True
            ok, _ = measured_call("bus_start", qmixbus.Bus.start)
            if not ok:
                raise RuntimeError("Bus start failed")
            started = True

            pump_count = int(qmixpump.Pump.get_no_of_pumps())
            emit({"event": "pump_count", "value": pump_count, "timestamp_utc": utc_now()})
            if pump_count != 1:
                raise RuntimeError(f"Expected exactly one configured pump, found {pump_count}")

            pump = qmixpump.Pump()
            pump.lookup_by_device_index(args.pump_index)
            pump_name = str(pump.get_pump_name())
            device_name = str(pump.get_device_name())
            node_id = int(pump.get_node_id())
            emit(
                {
                    "event": "pump_identity",
                    "pump_name": pump_name,
                    "device_name": device_name,
                    "node_id": node_id,
                    "timestamp_utc": utc_now(),
                }
            )
            if pump_name != EXPECTED_PUMP_NAME or device_name != EXPECTED_PUMP_NAME or node_id != EXPECTED_NODE_ID:
                raise RuntimeError(
                    f"Unexpected pump identity: pump_name={pump_name!r}, "
                    f"device_name={device_name!r}, node_id={node_id}"
                )

            pumping = bool(pump.is_pumping())
            if pumping:
                emit(
                    {
                        "event": "unexpected_active_motion",
                        "pumping": True,
                        "action": "emergency stop_pumping",
                        "timestamp_utc": utc_now(),
                    }
                )
                ok, _ = measured_call("emergency_stop_pumping", pump.stop_pumping)
                emergency_stop_sent = ok
                classification = "SAFETY/TRANSPORT_STOP"
            else:
                snapshot_started = time.monotonic()
                fault = bool(pump.is_in_fault_state())
                enabled = bool(pump.is_enabled())
                position_sensing_initialized = bool(pump.is_position_sensing_initialized())
                fill_level = float(pump.get_fill_level())
                maximum_volume = float(pump.get_volume_max())
                maximum_flow = float(pump.get_flow_rate_max())
                flow_unit = unit_record(pump.get_flow_unit())
                volume_unit = unit_record(pump.get_volume_unit())
                position_counter = int(pump.get_position_counter_value())
                snapshot = {
                    "event": "readiness_snapshot",
                    "timestamp_utc": utc_now(),
                    "read_duration_s": time.monotonic() - snapshot_started,
                    "pump_name": pump_name,
                    "device_name": device_name,
                    "node_id": node_id,
                    "fault": fault,
                    "enabled": enabled,
                    "pumping": pumping,
                    "position_sensing_initialized": position_sensing_initialized,
                    "fill_level": fill_level,
                    "maximum_volume": maximum_volume,
                    "maximum_flow": maximum_flow,
                    "flow_unit": flow_unit,
                    "volume_unit": volume_unit,
                    "position_counter": position_counter,
                    "error_status_evidence": "is_in_fault_state only; read_last_error deliberately omitted",
                }
                emit(snapshot)
                classification = (
                    "READY_FOR_INTERPRETATION"
                    if not fault and position_sensing_initialized
                    else "NOT_READY_STATE"
                )
        except Exception as exc:
            emit(
                {
                    "event": "procedure_error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "error_code": getattr(exc, "errorcode", None),
                    "timestamp_utc": utc_now(),
                }
            )
            classification = "SAFETY/TRANSPORT_STOP"
        finally:
            if started and qmixbus is not None:
                ok, _ = measured_call("bus_stop", qmixbus.Bus.stop)
                cleanup_ok = cleanup_ok and ok
            if opened and qmixbus is not None:
                ok, _ = measured_call("bus_close", qmixbus.Bus.close)
                cleanup_ok = cleanup_ok and ok
            if not cleanup_ok:
                classification = "SAFETY/TRANSPORT_STOP"
            emit(
                {
                    "event": "procedure_complete",
                    "classification": classification,
                    "cleanup_ok": cleanup_ok,
                    "emergency_stop_sent": emergency_stop_sent,
                    "normal_pump_state_changing_commands_sent": False,
                    "timestamp_utc": utc_now(),
                }
            )
            OUTPUT = None

    return 0 if classification in {"READY_FOR_INTERPRETATION", "NOT_READY_STATE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
