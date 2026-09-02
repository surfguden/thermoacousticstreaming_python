from __future__ import annotations

import json
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
    assert "phase=MANUAL_SERVICE" in lines[0]


def test_text_log_labels_setup_context_without_creating_an_action_file(_redirect_log):
    with hw_logging.action_scope(
        None,
        run_id="application_session",
        condition="camera",
        repeat=None,
        phase="SETUP",
    ):
        hw_logging.log_transaction("camera", "open_camera", response="opened")

    line = _read_log(_redirect_log)[0]
    assert "phase=SETUP" in line
    assert "run_id=application_session" in line
    assert "condition=camera" in line
    assert "repeat=None" in line


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


def test_action_scope_records_command_and_protocol_result_with_correlation(tmp_path):
    action_log = tmp_path / "series" / "action_log.jsonl"

    with hw_logging.action_scope(
        action_log,
        run_id="series-001",
        condition="frequency_hz=1934000",
        repeat=2,
    ):
        with hw_logging.log_call("ad2", "configure_wfg", command={"amplitude_v": 6.0}) as result:
            result["effective"] = {"amplitude_v": 5.0}
            result["response"] = "applied with clamp"

    records = [json.loads(line) for line in action_log.read_text(encoding="utf-8").splitlines()]
    assert [record["evidence_stage"] for record in records] == [
        "COMMAND_SENT",
        "PROTOCOL_ACKNOWLEDGED",
    ]
    assert [record["status"] for record in records] == ["ATTEMPTED", "OK"]
    assert all(record["run_id"] == "series-001" for record in records)
    assert all(record["condition"] == "frequency_hz=1934000" for record in records)
    assert all(record["repeat"] == 2 for record in records)
    assert records[0]["requested"] == {"amplitude_v": 6.0}
    assert records[1]["effective"] == {"amplitude_v": 5.0}
    assert records[1]["result"] == "applied with clamp"
    assert all(record["elapsed_s"] >= 0.0 for record in records)
    assert all(record["verification_scope"] == "PROTOCOL" for record in records)
    assert "physical_verified" not in records[1]


def test_action_scope_retains_failed_command_and_cleanup_phase(tmp_path):
    action_log = tmp_path / "action_log.jsonl"

    with hw_logging.action_scope(
        action_log,
        run_id="failed-run",
        condition="default",
        repeat=1,
    ):
        with pytest.raises(RuntimeError, match="transport lost"):
            with hw_logging.log_call("valve", "write", command="P01"):
                raise RuntimeError("transport lost")
        with hw_logging.action_phase("CLEANUP"):
            hw_logging.log_action(
                "valve",
                "close",
                evidence_stage="OBSERVED",
                verification_scope="SOFTWARE",
                status="FAILED",
                error="close timed out",
            )

    records = [json.loads(line) for line in action_log.read_text(encoding="utf-8").splitlines()]
    assert records[0]["status"] == "ATTEMPTED"
    assert records[1]["status"] == "FAILED"
    assert records[1]["evidence_stage"] == "COMMAND_SENT"
    assert records[1]["error"] == "transport lost"
    assert records[2]["phase"] == "CLEANUP"
    assert records[2]["error"] == "close timed out"


def test_action_log_failure_never_changes_wrapped_operation(tmp_path):
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("blocks child creation", encoding="utf-8")

    with hw_logging.action_scope(
        blocking_file / "action_log.jsonl",
        run_id="logging-failure",
        condition="default",
        repeat=1,
    ):
        with hw_logging.log_call("camera", "start_capture") as result:
            result["response"] = "started"

    assert blocking_file.read_text(encoding="utf-8") == "blocks child creation"


def test_global_log_configuration_failure_never_changes_wrapped_operation(monkeypatch):
    monkeypatch.setattr(
        hw_logging,
        "_ensure_configured",
        lambda: (_ for _ in ()).throw(OSError("log directory unavailable")),
    )

    with hw_logging.log_call("camera", "start_capture") as result:
        result["response"] = "started"

    assert result["response"] == "started"
