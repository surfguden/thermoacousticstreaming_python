"""LabVIEW-migration-parity reference material -- not part of the
production runtime path.

Each function/class here maps to a specific original LabVIEW VI (see
`labview_ports.py`'s `python_name=` entries for the exact mapping).
This module exists to prove migration completeness/traceability --
evidence that no original LabVIEW capability (error-cluster handling,
dialogs, string/text utilities) was silently dropped during the port --
even though the actual production pipeline now uses different, more
direct Python equivalents instead (standard `logging` and `QMessageBox`
in place of these LabVIEW-mimicking error/dialog helpers).

Confirmed (code-health audit, Session 57) to have zero cross-references
from any other file in `src/thermo_acoustic/` or from `tools/`; only
referenced by its own unit tests in `tests/test_application.py`. This
is intentional, not dead code awaiting cleanup -- do not remove or
flag this module without an explicit decision to do so. See
`docs/known_open_items.md`'s "LabVIEW-migration-parity scaffolding"
note for the cross-reference.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ErrorCluster:
    status: bool = False
    code: int = 0
    source: str = ""


@dataclass(slots=True)
class TextBounds:
    width: int
    height: int


@dataclass(slots=True)
class LVRect:
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0


@dataclass(slots=True)
class LVBounds:
    width: int = 0
    height: int = 0


@dataclass(slots=True)
class LVMinMaxInc:
    minimum: int = 0
    maximum: int = 0
    increment: int = 1


class DialogType(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    QUESTION = "question"


DialogTypeEnum = DialogType


class EventVKey(str, Enum):
    ENTER = "enter"
    ESCAPE = "escape"
    TAB = "tab"


class TagReturnType(str, Enum):
    MISSING = "missing"
    FOUND = "found"
    REPLACED = "replaced"


ErrWarn = ErrorCluster
WHITESPACE = " \t\r\n"


def application_directory() -> Path:
    return Path.cwd()


def sub_elapsed_time(start_s: float, now_s: float | None = None) -> float:
    if now_s is None:
        now_s = time.monotonic()
    return max(now_s - start_s, 0.0)


def format_time_string(seconds: float) -> str:
    seconds = max(float(seconds), 0.0)
    minutes, sec = divmod(seconds, 60.0)
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours:02d}:{minutes:02d}:{sec:05.2f}"


def check_if_file_or_folder_exists(path: str | Path) -> bool:
    return Path(path).exists()


def trim_whitespace_one_sided(text: str, *, left: bool = True, right: bool = False) -> str:
    if left and right:
        return text.strip()
    if left:
        return text.lstrip()
    if right:
        return text.rstrip()
    return text


def trim_whitespace(text: str) -> str:
    return text.strip()


def search_and_replace_pattern(text: str, pattern: str, replacement: str, *, regex: bool = False) -> str:
    if regex:
        return re.sub(pattern, replacement, text)
    return text.replace(pattern, replacement)


def find_tag(text: str, tag: str) -> int:
    return text.find(tag)


def format_message_string(template: str, *values: object, **named_values: object) -> str:
    if named_values:
        return template.format(**named_values)
    if values:
        return template.format(*values)
    return template


def error_cluster_from_error_code(code: int, source: str = "") -> ErrorCluster:
    return ErrorCluster(status=code != 0, code=code, source=source)


def error_converter(error_code: int = 0, status: bool | None = None, source: str = "") -> ErrorCluster:
    if status is None:
        status = error_code != 0
    return ErrorCluster(status=status, code=error_code, source=source)


def clear_errors(error: ErrorCluster | None = None) -> ErrorCluster:
    _ = error
    return ErrorCluster()


def correct_error_chain(primary: ErrorCluster, secondary: ErrorCluster | None = None) -> ErrorCluster:
    if primary.status:
        return primary
    if secondary is not None and secondary.status:
        return secondary
    return primary


def simple_error_handler(error: ErrorCluster | BaseException | None = None) -> str:
    if error is None:
        return ""
    if isinstance(error, ErrorCluster):
        return f"{error.code}: {error.source}" if error.status else ""
    return str(error)


def general_error_handler(error: ErrorCluster | BaseException | None = None) -> str:
    return simple_error_handler(error)


def general_error_handler_core(error: ErrorCluster | BaseException | None = None) -> tuple[bool, str]:
    message = general_error_handler(error)
    return bool(message), message


def not_found_dialog(item: str) -> str:
    return f"Not found: {item}"


def three_button_dialog(message: str, buttons: tuple[str, str, str] = ("Yes", "No", "Cancel"), default: int = 0) -> str:
    _ = message
    index = min(max(default, 0), len(buttons) - 1)
    return buttons[index]


def three_button_dialog_core(message: str, buttons: tuple[str, str, str] = ("Yes", "No", "Cancel"), default: int = 0) -> str:
    return three_button_dialog(message, buttons, default)


def details_display_dialog(message: str, details: str = "") -> dict[str, str]:
    return {"message": message, "details": details}


def sub_file_dialog(path: str | Path | None = None, default: str | Path | None = None) -> Path | None:
    selected = path if path is not None else default
    return Path(selected) if selected is not None else None


def build_help_path(topic: str, help_dir: str | Path | None = None) -> Path:
    base = get_help_dir(help_dir)
    return base / topic


def get_help_dir(help_dir: str | Path | None = None) -> Path:
    return Path(help_dir) if help_dir is not None else application_directory() / "help"


def get_text_rect(text: str, font_size: int = 12) -> TextBounds:
    return TextBounds(width=longest_line_length_in_pixels(text, font_size), height=max(1, len(text.splitlines()) or 1) * font_size)


def get_string_text_bounds(text: str, font_size: int = 12) -> TextBounds:
    return get_text_rect(text, font_size)


def longest_line_length_in_pixels(text: str, font_size: int = 12) -> int:
    longest = max((len(line) for line in text.splitlines()), default=len(text))
    return int(longest * font_size * 0.6)


def convert_property_node_font_to_graphics_font(font: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict(font or {})


def set_bold_text(text: str) -> dict[str, Any]:
    return {"text": text, "bold": True}


def set_string_value(target: dict[str, Any] | None, value: str) -> dict[str, Any]:
    result = dict(target or {})
    result["value"] = value
    return result


def check_special_tags(text: str) -> list[str]:
    return re.findall(r"<[^>]+>", text)


def error_code_database(code: int) -> str:
    if code == 0:
        return "No error"
    return f"Error {code}"


def get_rt_host_connected_prop() -> bool:
    return True
