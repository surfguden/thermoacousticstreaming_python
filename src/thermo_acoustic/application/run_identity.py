"""Which software produced a batch: the Git commit and whether tracked files were modified.

Read once per process (when the first series is queued), never during acquisition. Anything that
cannot be read is recorded as "unknown" and never blocks a run.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GIT_TIMEOUT_S = 3.0
_UNKNOWN = {"git_commit": "unknown", "git_dirty": "unknown", "source": "unavailable"}
_cached: dict | None = None


def _git(run, root: Path, *arguments: str):
    kwargs = {"capture_output": True, "text": True, "timeout": _GIT_TIMEOUT_S, "check": False}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return run(["git", "-C", str(root), *arguments], **kwargs)


def software_identity(root: Path | None = None, *, run=None) -> dict:
    """Commit and dirty state of the checkout at `root` (tracked files only; untracked ones are ignored)."""
    run = run or subprocess.run
    root = _REPO_ROOT if root is None else Path(root)
    try:
        head = _git(run, root, "rev-parse", "HEAD")
        if head.returncode != 0 or not head.stdout.strip():
            return dict(_UNKNOWN)
        commit = head.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return dict(_UNKNOWN)
    try:
        status = _git(run, root, "status", "--porcelain", "--untracked-files=no")
        dirty: bool | str = bool(status.stdout.strip()) if status.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        dirty = "unknown"
    return {"git_commit": commit, "git_dirty": dirty, "source": "git"}


def cached_software_identity() -> dict:
    global _cached
    if _cached is None:
        # A packaged install has no checkout; do not pick up some unrelated enclosing repository.
        _cached = software_identity() if (_REPO_ROOT / ".git").exists() else dict(_UNKNOWN)
    return dict(_cached)
