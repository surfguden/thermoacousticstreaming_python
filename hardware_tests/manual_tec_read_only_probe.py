"""Read-only Meerstetter TEC probe.

This manual diagnostic is intentionally outside pytest collection. It performs
only named reads of the project's reviewed MeCom parameters: Device Status
(104), Error Number (105, only when status is Error), Object Temperature
(1000), and Output Enable Status (2010). It contains no write call.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


__test__ = False

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.tec import (  # noqa: E402
    _MECOM_PARAM_DEVICE_STATUS,
    _MECOM_PARAM_ERROR_NUMBER,
    _MECOM_PARAM_OBJECT_TEMP,
    _MECOM_PARAM_OUTPUT_ENABLE,
    _PyMeComTecClient,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(record: dict[str, object]) -> None:
    print(json.dumps(record, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only dual-channel Meerstetter TEC probe.")
    parser.add_argument("--port", required=True, help="Reviewed TEC serial port, for example COM6.")
    parser.add_argument("--channels", type=int, nargs="+", default=(1, 2))
    args = parser.parse_args()

    client = _PyMeComTecClient(port=args.port)
    emit({"event": "probe_start", "port": args.port, "timestamp_utc": utc_now(), "writes": "none"})
    try:
        client.connect()
        mc = client._require_client()
        device_status = int(
            mc.get_parameter(parameter_name=_MECOM_PARAM_DEVICE_STATUS, parameter_instance=1)
        )
        emit(
            {
                "channel": "device-wide",
                "parameter_id": 104,
                "parameter_name": _MECOM_PARAM_DEVICE_STATUS,
                "raw_value": device_status,
                "timestamp_utc": utc_now(),
            }
        )
        if device_status == 3:
            error_number = mc.get_parameter(
                parameter_name=_MECOM_PARAM_ERROR_NUMBER,
                parameter_instance=1,
            )
            emit(
                {
                    "channel": "device-wide",
                    "parameter_id": 105,
                    "parameter_name": _MECOM_PARAM_ERROR_NUMBER,
                    "raw_value": error_number,
                    "timestamp_utc": utc_now(),
                }
            )
        for channel in args.channels:
            temperature = float(
                mc.get_parameter(
                    parameter_name=_MECOM_PARAM_OBJECT_TEMP,
                    parameter_instance=channel,
                )
            )
            output_enable = int(
                mc.get_parameter(
                    parameter_name=_MECOM_PARAM_OUTPUT_ENABLE,
                    parameter_instance=channel,
                )
            )
            emit(
                {
                    "channel": channel,
                    "object_temperature_c": temperature,
                    "output_enable_status": output_enable,
                    "parameter_ids": [1000, 2010],
                    "timestamp_utc": utc_now(),
                }
            )
        emit({"event": "probe_complete", "timestamp_utc": utc_now(), "writes": "none"})
        return 0
    except Exception as exc:
        emit(
            {
                "event": "probe_error",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "timestamp_utc": utc_now(),
            }
        )
        return 1
    finally:
        try:
            client.close()
            emit({"event": "client_closed", "timestamp_utc": utc_now()})
        except Exception as exc:
            emit(
                {
                    "event": "close_error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "timestamp_utc": utc_now(),
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
