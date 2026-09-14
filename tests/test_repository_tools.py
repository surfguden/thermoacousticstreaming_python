from __future__ import annotations

import importlib.util
from pathlib import Path
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


def test_hygiene_path_policy_is_directory_specific():
    tool = _load_tool("check_repository_hygiene")

    assert tool.is_disposable_tracked_path("src/pkg/__pycache__/module.cpython-311.pyc")
    assert tool.is_disposable_tracked_path(".pytest_tmp_run/case/output.txt")
    assert tool.is_disposable_tracked_path(".pytest-manual-run/case/output.txt")
    assert not tool.is_disposable_tracked_path("logs/retained_hardware_evidence.log")
    assert not tool.is_disposable_tracked_path("runs/retained_measurement.tdms")


def test_hygiene_detects_repository_root_pytest_bases(tmp_path):
    tool = _load_tool("check_repository_hygiene")
    (tmp_path / ".pytest_tmp_manual").mkdir()
    (tmp_path / ".pytest-contracts").mkdir()
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / "fixtures").mkdir()

    assert tool.repository_root_pytest_scratch_directories(tmp_path) == [
        ".pytest-contracts",
        ".pytest_tmp_manual",
    ]


def test_current_repository_has_no_tracked_caches_or_root_pytest_scratch():
    tool = _load_tool("check_repository_hygiene")

    report = tool.validate_repository(ROOT)

    assert report["ok"], report["issues"]
    assert report["tracked_disposable_paths"] == []
    assert report["repository_root_pytest_scratch_directories"] == []


def test_pytest_and_ci_keep_real_hardware_outside_collection():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    workflow = (ROOT / ".github" / "workflows" / "offline-ci.yml").read_text(encoding="utf-8")

    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
    assert "hardware_tests/" not in workflow
    assert "manual_" not in workflow
