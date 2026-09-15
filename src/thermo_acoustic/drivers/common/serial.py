from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from .logging import log_call

class TextCommandTransport(Protocol):
    def write(self, command: str) -> None: ...

    def query(self, command: str) -> str: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class SerialTextCommandTransport:
    baud_rate: int = 19200
    timeout_s: float = 1.0
    write_timeout_s: float = 5.0
    line_ending: str = "\r"
    port: object | None = None
    # Which device this instance's transactions get tagged as in the shared
    # hw_logging log (e.g. "valve") -- set by the caller that constructs this
    # transport, since the transport itself is generic and has no device identity
    # of its own. Left at the generic default only if a caller forgets to set it.
    device_name: str = "serial"

    def _open(self, resource: str) -> None:
        if self.port is not None:
            return
        with log_call(self.device_name, "connect", command=resource) as result:
            try:
                import serial
            except ImportError as exc:  # pragma: no cover - depends on optional runtime package
                raise RuntimeError("pyserial is required for real serial hardware. Install with: python -m pip install pyserial") from exc
            self.port = serial.Serial(
                resource,
                baudrate=self.baud_rate,
                timeout=self.timeout_s,
                write_timeout=self.write_timeout_s,
            )
            result["response"] = "connected"

    def _send(self, command: str) -> None:
        text = command.strip()
        if text.upper().startswith("OPEN "):
            self._open(text.split(maxsplit=1)[1])
            return
        if self.port is None:
            raise RuntimeError("Serial port is not open.")
        self.port.write((command + self.line_ending).encode("ascii"))

    def write(self, command: str) -> None:
        if command.strip().upper().startswith("OPEN "):
            # _send() -> _open() already logs this as its own "connect"
            # transaction -- avoid a redundant second "write" line for the
            # same pseudo-command.
            self._send(command)
            return
        with log_call(self.device_name, "write", command=command) as result:
            self._send(command)
            result["response"] = "sent"

    def query(self, command: str) -> str:
        with log_call(
            self.device_name, "query", command=command, response_stage="OBSERVED"
        ) as result:
            self._send(command)
            if self.port is None:
                raise RuntimeError("Serial port is not open.")
            # readline() splits on b"\n", but this transport's own devices are
            # only ever confirmed to terminate responses with line_ending
            # ("\r" by default -- see write() above). Real-hardware timing
            # characterization (Session 54) showed every query() call blocking
            # for the entire configured timeout_s before returning, regardless
            # of how quickly the device actually responded -- the signature of
            # readline() never finding the "\n" it was looking for. Reading
            # until the same terminator this transport writes with fixes that.
            terminator = self.line_ending.encode("ascii")
            response = self.port.read_until(expected=terminator).decode("ascii", errors="replace")
            result["response"] = response
        return response

    def close(self) -> None:
        with log_call(self.device_name, "close") as result:
            # Serial-transport review: self.port must be
            # reset to None even if port.close() itself raises -- otherwise
            # a future _open() sees self.port is not None and skips
            # reopening entirely, permanently reusing the broken handle,
            # and a future close() tries to close the same broken handle
            # again. The exception itself still propagates (log_call()
            # logs and re-raises), this only guarantees the reset happens
            # first.
            try:
                if self.port is not None:
                    self.port.close()
            finally:
                self.port = None
            result["response"] = "closed"
