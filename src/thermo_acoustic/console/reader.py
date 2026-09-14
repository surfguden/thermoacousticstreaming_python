from __future__ import annotations
import sys
from PySide6.QtCore import QThread, Signal
from .parser import parse_command

class ConsoleCommandReader(QThread):
    command = Signal(object)
    output = Signal(str)
    def run(self) -> None:
        while True:
            try: line = sys.stdin.readline()
            except Exception as exc: self.output.emit(f"stdin error: {exc}"); return
            if line == "": return
            try: parsed = parse_command(line)
            except (ValueError, TypeError) as exc: self.output.emit(f"validation error: {exc}"); continue
            self.command.emit(parsed)
            if parsed == "quit": return

