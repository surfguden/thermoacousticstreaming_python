from __future__ import annotations

from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[1]


def test_parser_targets_the_tracked_main_html_export() -> None:
    parser = runpy.run_path(str(ROOT / "tools" / "parse_labview_export.py"))

    export_path = parser["EXPORT_HTML_PATH"]
    documented_vis = parser["parse_export"]()

    assert export_path == ROOT / "main_html" / "main.html"
    assert export_path.is_file()
    assert len(documented_vis) == 305
