from __future__ import annotations

import time

import pytest

from thermo_acoustic import hw_logging


@pytest.fixture(autouse=True)
def _redirect_log(tmp_path):
    # Every test gets its own log file -- never touches the real logs/
    # directory (conftest.py's session-scoped _hw_logging_isolated fixture
    # already guarantees that as a baseline; this narrows it further to a
    # fresh file per test in this file specifically, so tests don't see
    # each other's log lines). Deliberately does not reset _configured_path
    # to None in teardown -- that would make the *next* test needing
    # hw_logging fall back to _ensure_configured()'s real-path default
    # before conftest.py's own fixture protection kicks back in.
    log_file = tmp_path / "hardware_transactions.log"
    hw_logging.configure(log_file)
    yield log_file


def _read_log(log_file) -> list[str]:
    if not log_file.exists():
        return []
    return log_file.read_text(encoding="utf-8").splitlines()


def test_log_transaction_records_a_successful_call(_redirect_log):
    hw_logging.log_transaction(
        "valve", "query_status", command="S", response="01", success=True,
    )

    lines = _read_log(_redirect_log)
    assert len(lines) == 1
    assert "valve" in lines[0]
    assert "query_status" in lines[0]
    assert "OK" in lines[0]
    assert "cmd='S'" in lines[0]
    assert "resp='01'" in lines[0]


def test_log_transaction_records_a_failed_call_with_error_detail(_redirect_log):
    hw_logging.log_transaction(
        "z_motor", "initialize", command="OPEN COM7", success=False,
        error="could not open port 'COM7': FileNotFoundError(...)",
    )

    lines = _read_log(_redirect_log)
    assert len(lines) == 1
    assert "z_motor" in lines[0]
    assert "initialize" in lines[0]
    assert "FAIL" in lines[0]
    assert "COM7" in lines[0]
    assert "FileNotFoundError" in lines[0]


def test_log_transaction_omits_absent_fields_rather_than_printing_none(_redirect_log):
    hw_logging.log_transaction("piezo", "connect", success=True)

    lines = _read_log(_redirect_log)
    assert len(lines) == 1
    assert "cmd=" not in lines[0]
    assert "resp=" not in lines[0]
    assert "error=" not in lines[0]


def test_each_record_is_timestamped(_redirect_log):
    hw_logging.log_transaction("camera", "capture_frame", success=True)

    lines = _read_log(_redirect_log)
    # RotatingFileHandler's formatter prefixes "%(asctime)s | " -- a real
    # record should start with a parseable date, not silently omit it.
    assert lines[0][:4].isdigit()


def test_log_call_captures_the_response_on_success(_redirect_log):
    with hw_logging.log_call("ad2", "read_output_range", command="AnalogOutNodeInfo") as result:
        result["response"] = (-5.0, 5.0)

    lines = _read_log(_redirect_log)
    assert len(lines) == 1
    assert "OK" in lines[0]
    assert "(-5.0, 5.0)" in lines[0]


def test_log_call_logs_failure_and_still_reraises(_redirect_log):
    with pytest.raises(RuntimeError, match="device unreachable"):
        with hw_logging.log_call("pump", "generate_flow", command=100.0):
            raise RuntimeError("device unreachable")

    lines = _read_log(_redirect_log)
    assert len(lines) == 1
    assert "FAIL" in lines[0]
    assert "device unreachable" in lines[0]
    assert "pump" in lines[0]


def test_configure_creates_the_log_directory_if_missing(tmp_path):
    nested = tmp_path / "does" / "not" / "exist" / "hw.log"
    assert not nested.parent.exists()

    hw_logging.configure(nested)
    hw_logging.log_transaction("valve", "initialize", success=True)

    assert nested.exists()


def test_configure_is_idempotent_for_the_same_path_does_not_duplicate_handlers(_redirect_log):
    before = len(hw_logging._logger.handlers)
    hw_logging.configure(_redirect_log)
    hw_logging.configure(_redirect_log)
    assert len(hw_logging._logger.handlers) == before


def test_synchronous_logging_overhead_is_negligible_for_real_call_frequency(_redirect_log):
    # Pending feedback / Part A requirement: confirm plain synchronous
    # logging is fast enough before reaching for async/threaded
    # complexity. This project's own documented real-hardware call
    # latencies run from single-digit milliseconds to multiple *seconds*
    # (e.g. the pre-Session-55 valve readline() bug blocked ~5s/call) --
    # 500 log calls finishing in well under 250ms (0.5ms/call average) is
    # many orders of magnitude below that, so no async wrapper is needed.
    start = time.perf_counter()
    for i in range(500):
        hw_logging.log_transaction("valve", "query_status", command=f"S{i}", response="01", success=True)
    elapsed_s = time.perf_counter() - start

    assert elapsed_s < 0.25, f"500 synchronous log calls took {elapsed_s:.3f}s -- reconsider the sync-only design"
