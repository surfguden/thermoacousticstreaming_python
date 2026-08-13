"""Launch the local, opt-in v3 layout preview.

V3 reuses the v2 runtime and is not independently hardware-verified. The v3
files are intentionally local/untracked at the current repository state; v2 is
the tracked rollback/reference UI.
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
