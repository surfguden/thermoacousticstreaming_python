"""Validate tracked disposable-file hygiene and LabVIEW export consistency."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
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
        or "_pytest_tmp" in parts
        or name.endswith((".pyc", ".pyo"))
    )


def check_labview_export(root: Path) -> list[str]:
    issues: list[str] = []
    export = root / "main_html" / "main.html"
    manifest_path = root / "labview_manifest.json"
    parser_path = root / "tools" / "parse_labview_export.py"
    for path in (export, manifest_path, parser_path):
        if not path.is_file():
            issues.append(f"missing canonical LabVIEW artifact: {path.relative_to(root).as_posix()}")
    if issues:
        return issues

    parser = runpy.run_path(str(parser_path))
    documented = parser["parse_export"]()
    document = export.read_text(encoding="utf-8", errors="replace")
    referenced = parser["_referenced_items"](document)
    expected = {
        "export_html": "main_html/main.html",
        "documented_vis": [
            {"name": item.name, "images": item.images, "source_path": item.source_path}
            for item in documented
        ],
        "referenced_items": [
            {"name": item.name, "source_path": item.source_path} for item in referenced
        ],
    }
    actual = json.loads(manifest_path.read_text(encoding="utf-8"))
    if actual != expected:
        issues.append("labview_manifest.json does not match main_html/main.html parser output")
    missing_images = sorted(
        image
        for item in documented
        for image in item.images
        if not (root / "main_html" / image).is_file()
    )
    if missing_images:
        preview = ", ".join(missing_images[:5])
        suffix = " ..." if len(missing_images) > 5 else ""
        issues.append(f"LabVIEW export references {len(missing_images)} missing image(s): {preview}{suffix}")
    return issues


def validate_repository(root: Path) -> dict[str, object]:
    root = root.resolve()
    tracked = sorted(_git(root, "ls-files"))
    disposable = [path for path in tracked if is_disposable_tracked_path(path)]
    issues = [f"tracked disposable path: {path}" for path in disposable]
    issues.extend(check_labview_export(root))
    return {
        "repository_root": str(root),
        "tracked_file_count": len(tracked),
        "tracked_disposable_paths": disposable,
        "labview_export_consistent": not any("LabVIEW" in issue or "labview_" in issue for issue in issues),
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
