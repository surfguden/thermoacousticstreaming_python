"""LabVIEW-migration-parity reference material -- not part of the
production runtime path.

Each function/class here maps to a specific original LabVIEW file-type
detection VI (see `labview_ports.py`'s `python_name=` entries). This
module exists to prove migration completeness/traceability -- evidence
that no original LabVIEW capability was silently dropped during the
port -- even though nothing in the actual production pipeline currently
needs to classify LabVIEW project file types at runtime.

Confirmed (code-health audit, Session 57) to have zero cross-references
from any other file in `src/thermo_acoustic/` or from `tools/`; only
referenced by its own unit tests in `tests/test_application.py`. This
is intentional, not dead code awaiting cleanup -- do not remove or
flag this module without an explicit decision to do so. See
`docs/known_open_items.md`'s "LabVIEW-migration-parity scaffolding"
note for the cross-reference.
"""

from __future__ import annotations

import zipfile
from enum import Enum
from pathlib import Path


class LVFileType(str, Enum):
    UNKNOWN = "unknown"
    DIRECTORY = "directory"
    VI = "vi"
    CONTROL = "control"
    PROJECT = "project"
    LIBRARY = "library"
    LLB = "llb"
    PACKED_LIBRARY = "packed_library"
    ZIP_ARCHIVE = "zip_archive"


FT_FILE_TYPES = tuple(item.value for item in LVFileType)


def is_file_an_llb(path: str | Path) -> bool:
    return Path(path).suffix.lower() == ".llb"


def get_file_type(path: str | Path) -> LVFileType:
    path = Path(path)
    if path.is_dir():
        return LVFileType.DIRECTORY

    suffix = path.suffix.lower()
    if suffix == ".vi":
        return LVFileType.VI
    if suffix == ".ctl":
        return LVFileType.CONTROL
    if suffix == ".lvproj":
        return LVFileType.PROJECT
    if suffix in {".lvlib", ".lvclass"}:
        return LVFileType.LIBRARY
    if suffix == ".llb":
        return LVFileType.LLB
    if suffix == ".lvlibp":
        return LVFileType.PACKED_LIBRARY
    if suffix == ".zip":
        return LVFileType.ZIP_ARCHIVE
    return LVFileType.UNKNOWN


def get_exported_file_list(path: str | Path) -> list[Path | str]:
    path = Path(path)
    if path.is_dir():
        return sorted(item for item in path.rglob("*") if item.is_file())
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return sorted(name for name in archive.namelist() if not name.endswith("/"))
    if path.is_file():
        return [path]
    return []
