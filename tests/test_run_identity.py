"""Run identity in the batch metadata: operating mode and software commit/dirty state."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application.run_identity import software_identity
from test_simple_series import _connected_temperature_series_harness


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-run-identity"])


def fake_git(answers):
    """answers maps the git subcommand to (returncode, stdout) or an exception to raise."""
    def run(command, **_kwargs):
        answer = answers[command[command.index("git") + 1 + (2 if "-C" in command else 0)]]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(returncode=answer[0], stdout=answer[1])
    return run


COMMIT = "0123456789abcdef0123456789abcdef01234567"


def test_clean_checkout_reports_commit_and_not_dirty(tmp_path):
    identity = software_identity(tmp_path, run=fake_git({"rev-parse": (0, COMMIT + "\n"), "status": (0, "")}))
    assert identity == {"git_commit": COMMIT, "git_dirty": False, "source": "git"}


def test_modified_checkout_reports_dirty(tmp_path):
    identity = software_identity(
        tmp_path, run=fake_git({"rev-parse": (0, COMMIT + "\n"), "status": (0, " M src/thermo_acoustic/x.py\n")}))
    assert identity["git_commit"] == COMMIT and identity["git_dirty"] is True


@pytest.mark.parametrize("failure", [
    FileNotFoundError("git"),
    subprocess.TimeoutExpired("git", 3),
    OSError("blocked"),
], ids=["no_git", "timeout", "os_error"])
def test_missing_or_unreadable_git_is_unknown_and_never_raises(tmp_path, failure):
    identity = software_identity(tmp_path, run=fake_git({"rev-parse": failure, "status": failure}))
    assert identity == {"git_commit": "unknown", "git_dirty": "unknown", "source": "unavailable"}


def test_not_a_repository_is_unknown(tmp_path):
    identity = software_identity(tmp_path, run=fake_git({"rev-parse": (128, ""), "status": (128, "")}))
    assert identity["git_commit"] == "unknown" and identity["git_dirty"] == "unknown"


def test_commit_known_but_status_unreadable_keeps_the_commit(tmp_path):
    identity = software_identity(tmp_path, run=fake_git({"rev-parse": (0, COMMIT), "status": (1, "")}))
    assert identity["git_commit"] == COMMIT and identity["git_dirty"] == "unknown"


def test_the_batch_manifest_records_mode_and_software_identity(qt_app, tmp_path):
    controller, panel, results, events = _connected_temperature_series_harness(qt_app, repeats=1)
    try:
        folder = controller.experiments.queue(panel._definition(), tmp_path)
        manifest = json.loads((folder / "metadata" / "manifest.json").read_text())
        assert manifest["schema_version"] == 1 and manifest["experiments"]  # existing fields unchanged
        assert manifest["run"]["mode"] == "simulation"
        software = manifest["run"]["software"]
        assert set(software) == {"git_commit", "git_dirty", "source"}
    finally:
        panel.close()
        controller.shutdown()


def test_an_unreadable_git_does_not_stop_the_series_from_being_queued(qt_app, tmp_path, monkeypatch):
    from thermo_acoustic.application import run_identity
    monkeypatch.setattr(run_identity, "_cached", None)
    monkeypatch.setattr(run_identity.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("git")))
    controller, panel, results, events = _connected_temperature_series_harness(qt_app, repeats=1)
    try:
        folder = controller.experiments.queue(panel._definition(), tmp_path)
        manifest = json.loads((folder / "metadata" / "manifest.json").read_text())
        assert manifest["run"]["software"]["git_commit"] == "unknown"
        assert manifest["run"]["mode"] == "simulation"
    finally:
        panel.close()
        controller.shutdown()
        monkeypatch.setattr(run_identity, "_cached", None)
