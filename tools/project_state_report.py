"""Print objective, read-only repository state for a new work session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tomllib


UI_FILES = {
    "v1": (
        "src/thermo_acoustic/qt_ui.py",
        "launch_gui.bat",
        "tools/run_ui.py",
    ),
    "v2": (
        "src/thermo_acoustic/qt_ui_v2.py",
        "launch_gui_v2.bat",
        "tools/run_ui_v2.py",
    ),
    "v3": (
        "src/thermo_acoustic/qt_ui_v3.py",
        "src/thermo_acoustic/qt_ui_v3_support.py",
        "launch_gui_v3.bat",
        "tools/run_ui_v3.py",
        "tests/test_qt_ui_v3.py",
    ),
}

CACHE_NAMES = {"__pycache__", ".pytest_cache", "_pytest_tmp"}


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def repository_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    return Path(_git(start, "rev-parse", "--show-toplevel")).resolve()


def _name_status(root: Path, *, staged: bool) -> list[dict[str, str]]:
    args = ["diff", "--name-status"]
    if staged:
        args.append("--cached")
    output = _git(root, *args)
    changes: list[dict[str, str]] = []
    for line in output.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        record = {"status": fields[0], "path": fields[-1].replace("\\", "/")}
        if len(fields) == 3:
            record["old_path"] = fields[1].replace("\\", "/")
        changes.append(record)
    return changes


def _is_relevant_ignored(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name
    return (
        path == ".thermo_acoustic_ui.json"
        or path.endswith(".tdms")
        or (parts and parts[0] in {"logs", "runs"})
        or path.startswith("hardware_tests/output/")
        or any(part in CACHE_NAMES or part.startswith(".pytest_tmp") for part in parts)
        or name in CACHE_NAMES
        or name.startswith(".pytest_tmp")
        or name.endswith((".pyc", ".pyo"))
    )


def _tracked(root: Path, path: str) -> bool:
    return bool(_git(root, "ls-files", "--", path, check=False))


def _pytest_boundary(root: Path) -> dict[str, object]:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return {"testpaths": [], "addopts": None}
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    pytest_config = config.get("tool", {}).get("pytest", {}).get("ini_options", {})
    return {
        "testpaths": list(pytest_config.get("testpaths", [])),
        "addopts": pytest_config.get("addopts"),
    }


def _cache_directories(root: Path) -> list[str]:
    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_dir() or ".git" in path.parts:
            continue
        if path.name in CACHE_NAMES or path.name.startswith(".pytest_tmp"):
            found.append(path.relative_to(root).as_posix())
    return sorted(found)


def build_report(root: Path | None = None) -> dict[str, object]:
    root = repository_root(root)
    branch = _git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False) or None
    head = _git(root, "rev-parse", "HEAD")
    upstream = _git(
        root,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        check=False,
    ) or None
    ahead = behind = None
    if upstream:
        counts = _git(root, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        behind_text, ahead_text = counts.split()
        ahead, behind = int(ahead_text), int(behind_text)

    untracked = sorted(
        line.replace("\\", "/")
        for line in _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
        if line
    )
    ignored = sorted(
        path.replace("\\", "/")
        for path in _git(
            root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
        ).splitlines()
        if path and _is_relevant_ignored(path.replace("\\", "/"))
    )
    ui = {
        variant: {path: _tracked(root, path) for path in paths}
        for variant, paths in UI_FILES.items()
    }
    return {
        "repository_root": str(root),
        "branch": branch,
        "head": head,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "unstaged_tracked_changes": _name_status(root, staged=False),
        "staged_changes": _name_status(root, staged=True),
        "untracked_files": untracked,
        "relevant_ignored_files": ignored,
        "ui_tracking": ui,
        "pytest_collection": _pytest_boundary(root),
        "generated_cache_directories": _cache_directories(root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Repository path (defaults to the current repository).")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()
    report = build_report(args.root)
    print(json.dumps(report, indent=None if args.compact else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
