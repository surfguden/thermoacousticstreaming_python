from __future__ import annotations
from dataclasses import dataclass
import time
from ..common.serial import TextCommandTransport


class ValveError(RuntimeError):
    pass


@dataclass(slots=True)
class Valve:
    transport: TextCommandTransport
    enabled: bool = True
    # The port is selected for each connection. Never silently open a fixed
    # COM number, which can identify a different device on another computer.
    visa_resource: str | None = None
    # Protocol-confirmed numeric positions. The physical fluidic routing of
    # P01/P02 remains a bench-confirmation item; do not infer Open/Closed
    # semantics from the serial position token alone.
    command_position_1: str = "P01"
    command_position_2: str = "P02"
    status_query_command: str = "S"
    position: int = 1
    requested_position: int | None = None
    initialized: bool = False
    status_note: str = ""

    def initialize(self) -> None:
        if not self.visa_resource:
            raise ValveError("Select a valve COM port before connecting")
        self.status_note = ""
        try:
            self.transport.write(f"OPEN {self.visa_resource}")
            raw_response = self.transport.query(self.status_query_command)
            if not self._apply_status_response(raw_response):
                raise ValveError(
                    f"Valve returned unrecognized status on {self.visa_resource}: {self.status_note}"
                )
        except Exception as exc:
            self.initialized = False
            try:
                self.transport.close()
            except Exception as cleanup_exc:
                raise ValveError(
                    f"Valve initialize failed on {self.visa_resource}: {exc}; "
                    f"cleanup after failed initialize also failed: {cleanup_exc}"
                ) from exc
            raise
        self.initialized = True

    def _apply_status_response(self, raw_response: str) -> bool:
        # "S\r" is the existing application query. The public IDEX driver
        # package does not specify its byte-level command/reply protocol;
        # retain it until a separately authorized read-only probe confirms a
        # change is needed.
        # Zero bytes back within the read timeout means nothing is on the
        # other end of the port -- that is the real disconnect signal, so it
        # must be checked before any stripping collapses it into a lone "\r".
        if raw_response == "":
            raise ValveError(f"Valve did not respond on {self.visa_resource}")
        text = raw_response.strip()
        if text in ("*", "**"):
            self.status_note = "busy"
            return True
        # The MX status reply is an explicit position token, not arbitrary
        # chatter containing a digit. In particular, do not treat strings
        # such as ``device=1`` or ``foo2bar`` as a confirmed valve position.
        # ``01``/``02`` are the observed protocol replies; the other exact
        # forms accept equivalent position tokens.
        position_responses = {
            "1": 1,
            "01": 1,
            "P01": 1,
            "2": 2,
            "02": 2,
            "P02": 2,
        }
        if text in position_responses:
            self.position = position_responses[text]
            self.status_note = "confirmed"
            return True
        self.status_note = f"unverified position response: {text!r}"
        return False

    def _ensure_connected(self) -> None:
        # Lazy reconnect (2026-08-13 architecture fix), matching the pattern
        # already proven for AnalogDiscovery2._open_first_device()/
        # HamamatsuDcamDriver.open_camera(): a manual Pump&Valve-tab action
        # must not require a prior, successful, whole-system
        # Application.initialize() -- e.g. this Valve was skipped because an
        # earlier device in the reporting order failed under the old
        # cross-device-abort design, or
        # was simply never initialized this session for any other reason.
        # Deliberately calls initialize() itself rather than a shortcut
        # "just open the port" duplicate: unlike AD2/Camera's lazy-open,
        # Valve.initialize() is not just a handle open, it also runs the
        # real "S" status handshake/validation (_apply_status_response()) --
        # skipping that here would silently accept an unconfirmed connection
        # on the fluid-routing-critical path. No-op when already initialized.
        if not self.initialized:
            self.initialize()

    def set_position(self, position: int) -> None:
        # Position numbers map directly to the protocol tokens P01/P02. Their
        # physical routing is intentionally not inferred here.
        if position not in (1, 2):
            raise ValueError(f"Unsupported valve position: {position}")
        self._ensure_connected()
        command = self.command_position_1 if position == 1 else self.command_position_2
        self.transport.write(command)
        self.requested_position = position
        # A successful serial write confirms only that the command was
        # accepted by the host serial API. The next status query confirms the
        # requested protocol position.
        self.status_note = f"requested {command}; confirmation pending"

    def read_position(self) -> int:
        """Read and return the valve position without waiting for motion."""
        _ready, position = self.read_state()
        if position is None:
            raise ValveError(
                f"Valve position is not currently confirmed on {self.visa_resource}: "
                f"{self.status_note}"
            )
        return position

    def read_state(self) -> tuple[bool, int | None]:
        """Query the existing status command without inferring a busy position."""
        self._ensure_connected()
        raw_response = self.transport.query(self.status_query_command)
        if not self._apply_status_response(raw_response):
            raise ValveError(
                f"Valve status on {self.visa_resource}: {self.status_note}"
            )
        if self.status_note != "confirmed":
            return False, None
        if self.requested_position is not None and self.position != self.requested_position:
            self.status_note = (
                f"position {self.position}; awaiting requested {self.requested_position}"
            )
            return False, self.position
        return True, self.position

    def wait_until_ready(self, timeout_s: float = 1.0, poll_interval_s: float = 0.05) -> bool:
        # Bounded poll of the same "S\r" handshake used at initialize() time,
        # so a real mechanical-transition confirmation replaces a fixed sleep
        # after set_position(). A real disconnect (empty response) still
        # raises ValveError immediately via _apply_status_response -- only a
        # "still busy" result is tolerated up to the timeout, at which point
        # this returns False. Hardware workflows must treat that as an
        # unconfirmed position and stop their next actuator command.
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while True:
            ready, _position = self.read_state()
            if ready:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(max(poll_interval_s, 0.0))

    def cleanup(self) -> None:
        self.transport.close()
        self.initialized = False
        self.status_note = ""
