from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def _load_tool(name: str):
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def test_project_state_report_separates_staged_unstaged_untracked_and_ignored(tmp_path):
    tool = _load_tool("project_state_report")
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Repository Tool Test")
    (tmp_path / "tracked.txt").write_text("base\n", encoding="utf-8")
    (tmp_path / "staged.txt").write_text("base\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\naddopts = "--basetemp=.pytest_tmp_scratch"\n',
        encoding="utf-8",
    )
    _git(tmp_path, "add", "tracked.txt", "staged.txt", "pyproject.toml")
    _git(tmp_path, "commit", "-m", "base")

    (tmp_path / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (tmp_path / "staged.txt").write_text("staged change\n", encoding="utf-8")
    _git(tmp_path, "add", "staged.txt")
    (tmp_path / "untracked.txt").write_text("new\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".pytest_cache/\n", encoding="utf-8")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "marker").write_text("cache", encoding="utf-8")

    report = tool.build_report(tmp_path)

    assert report["head"]
    assert report["upstream"] is None
    assert report["unstaged_tracked_changes"] == [{"status": "M", "path": "tracked.txt"}]
    assert report["staged_changes"] == [{"status": "M", "path": "staged.txt"}]
    assert "untracked.txt" in report["untracked_files"]
    assert ".pytest_cache/marker" in report["relevant_ignored_files"]
    assert report["pytest_collection"]["testpaths"] == ["tests"]
    assert report["generated_cache_directories"] == [".pytest_cache"]


def test_change_surface_reports_no_super_override_and_references(tmp_path):
    tool = _load_tool("audit_change_surface")
    source = tmp_path / "src"
    tests = tmp_path / "tests"
    docs = tmp_path / "docs"
    source.mkdir()
    tests.mkdir()
    docs.mkdir()
    (source / "ui.py").write_text(
        "class MainWindow:\n"
        "    def _shared_builder(self):\n"
        "        return 1\n\n"
        "class MainWindowV2(MainWindow):\n"
        "    def _shared_builder(self):\n"
        "        return 2\n\n"
        "class MainWindowV3(MainWindowV2):\n"
        "    def _shared_builder(self):\n"
        "        return super()._shared_builder()\n",
        encoding="utf-8",
    )
    (tests / "test_ui.py").write_text(
        "def test_builder(window):\n    assert window._shared_builder()\n",
        encoding="utf-8",
    )
    (docs / "boundary.md").write_text("Review `_shared_builder` in every UI.\n", encoding="utf-8")

    audit = tool.audit_symbols(tmp_path, ["_shared_builder"])
    report = audit["symbols"]["_shared_builder"]

    assert report["multiple_implementations"] is True
    overrides = {row["owner"]: row for row in report["overrides"]}
    assert overrides["MainWindowV2"]["override_without_super"] is True
    assert overrides["MainWindowV3"]["override_without_super"] is False
    assert any(row["path"] == "tests/test_ui.py" for row in report["test_references"])
    assert report["documentation_references"] == [{"path": "docs/boundary.md", "line": 1}]
    summary = {row["owner"]: row for row in audit["ui_inheritance_overrides"]}
    assert summary["MainWindowV2"]["override_without_super"] is True
    assert summary["MainWindowV3"]["calls_super"] is True


def test_hygiene_path_policy_is_directory_specific():
    tool = _load_tool("check_repository_hygiene")

    assert tool.is_disposable_tracked_path("src/pkg/__pycache__/module.cpython-311.pyc")
    assert tool.is_disposable_tracked_path(".pytest_tmp_run/case/output.txt")
    assert not tool.is_disposable_tracked_path("logs/retained_hardware_evidence.log")
    assert not tool.is_disposable_tracked_path("runs/retained_measurement.tdms")


def test_current_labview_export_matches_manifest_and_has_no_tracked_caches():
    tool = _load_tool("check_repository_hygiene")

    report = tool.validate_repository(ROOT)

    assert report["ok"], report["issues"]
    assert report["tracked_disposable_paths"] == []
    assert report["labview_export_consistent"] is True


def test_pytest_and_ci_keep_real_hardware_outside_collection():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    workflow = (ROOT / ".github" / "workflows" / "offline-ci.yml").read_text(encoding="utf-8")

    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
    assert "hardware_tests/" not in workflow
    assert "manual_" not in workflow
