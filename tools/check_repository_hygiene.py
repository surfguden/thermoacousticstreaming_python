"""Validate tracked disposable files and repository-root pytest scratch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


def _git(root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line.replace("\\", "/") for line in result.stdout.splitlines() if line]


def is_disposable_tracked_path(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name
    return (
        "__pycache__" in parts
        or ".pytest_cache" in parts
        or any(part.startswith(".pytest_tmp") for part in parts)
        or any(part.startswith(".pytest-") and part != ".pytest_cache" for part in parts)
        or "_pytest_tmp" in parts
        or name.endswith((".pyc", ".pyo"))
    )


def repository_root_pytest_scratch_directories(root: Path) -> list[str]:
    """Return generated pytest bases at the repository root, never fixtures.

    The normal pytest policy deliberately uses the external system temporary
    location.  These names therefore mean a caller explicitly reintroduced a
    repository-relative ``--basetemp`` and need cleanup rather than an ignore
    rule.  ``.pytest_cache`` is pytest's separate cache-provider directory.
    """
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir()
        and (
            path.name.startswith(".pytest_tmp")
            or path.name.startswith(".pytest-")
            or path.name == "_pytest_tmp"
        )
    )


def validate_repository(root: Path) -> dict[str, object]:
    root = root.resolve()
    tracked = sorted(_git(root, "ls-files"))
    disposable = [path for path in tracked if is_disposable_tracked_path(path)]
    issues = [f"tracked disposable path: {path}" for path in disposable]
    root_pytest_scratch = repository_root_pytest_scratch_directories(root)
    issues.extend(
        f"repository-root pytest scratch directory: {path}"
        for path in root_pytest_scratch
    )
    return {
        "repository_root": str(root),
        "tracked_file_count": len(tracked),
        "tracked_disposable_paths": disposable,
        "repository_root_pytest_scratch_directories": root_pytest_scratch,
        "issues": issues,
        "ok": not issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = validate_repository(args.root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
