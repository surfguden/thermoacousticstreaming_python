"""Launch the tracked, opt-in v3 layout.

V3 reuses the v2 runtime and is not independently hardware-verified. The v3
files are formally accepted repository content; v2 remains the
rollback/reference UI and v1 remains the default operator entry point.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.qt_ui_v3 import main


if __name__ == "__main__":
    main()
