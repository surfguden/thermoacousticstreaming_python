from __future__ import annotations
from dataclasses import dataclass
import time
from ..common.serial import TextCommandBackend

class ValveError(RuntimeError):
    pass


@dataclass(slots=True)
class Valve:
    enabled: bool = True
    simulate: bool = True
    # Real-hardware-confirmed default (a real-hardware verification session,
    # re-confirmed by a prior session too, not a one-off): the valve responds
    # correctly to the documented "S" status-query protocol on COM5, not the
    # previously-documented COM6 -- COM6 was a standing documentation error,
    # not a transient port reassignment.
    visa_resource: str = "COM5"
    backend: TextCommandBackend | None = None
    # Protocol-confirmed numeric positions. The physical fluidic routing of
    # P01/P02 remains a bench-confirmation item; do not infer Open/Closed
    # semantics from the serial position token alone.
    command_position_1: str = "P01"
    command_position_2: str = "P02"
    status_query_command: str = "S"
    position: int = 1
    initialized: bool = False
    status_note: str = ""

    def initialize(self) -> None:
        self.status_note = ""
        if self.backend is not None:
            try:
                self.backend.write(f"OPEN {self.visa_resource}")
                raw_response = self.backend.query(self.status_query_command)
                if not self._apply_status_response(raw_response):
                    raise ValveError(
                        f"Valve returned unrecognized status on {self.visa_resource}: {self.status_note}"
                    )
            except Exception as exc:
                self.initialized = False
                try:
                    self.backend.close()
                except Exception as cleanup_exc:
                    raise ValveError(
                        f"Valve initialize failed on {self.visa_resource}: {exc}; "
                        f"cleanup after failed initialize also failed: {cleanup_exc}"
                    ) from exc
                raise
        self.initialized = True

    def _apply_status_response(self, raw_response: str) -> bool:
        # Protocol confirmed against IDEX MX Series II driver docs (via the
        # linnarsson-lab/MXII-valve reference driver): "S\r" queries status.
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
        # forms keep compatibility with existing simulated/echo responses.
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
        # already proven for AD2Sdk.open_and_use_first_device()/
        # HamamatsuDcamBackend.open_camera(): a manual Pump&Valve-tab action
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
        # on the fluid-routing-critical path. No-op when already initialized
        # or simulated (backend is None).
        if self.backend is not None and not self.initialized:
            self.initialize()

    def set_position(self, position: int) -> None:
        # Position numbers map directly to the protocol tokens P01/P02. Their
        # physical routing is intentionally not inferred here.
        if position not in (1, 2):
            raise ValueError(f"Unsupported valve position: {position}")
        self._ensure_connected()
        # Valve-driver review: self.position is now only
        # assigned after backend.write() returns without raising -- assigning
        # it first (the old order) meant a raised exception from write() left
        # self.position claiming a move that was never actually sent.
        if self.backend is not None:
            command = self.command_position_1 if position == 1 else self.command_position_2
            self.backend.write(command)
        self.position = position
        if self.backend is not None:
            # A successful serial write confirms only that the command was
            # accepted by the host serial API. Do not carry a previous
            # position's "confirmed" status across this new request; the next
            # S-query/readback must confirm the requested protocol position.
            command = self.command_position_1 if position == 1 else self.command_position_2
            self.status_note = f"requested {command}; confirmation pending"

    def wait_until_ready(self, timeout_s: float = 1.0, poll_interval_s: float = 0.05) -> bool:
        # Bounded poll of the same "S\r" handshake used at initialize() time,
        # so a real mechanical-transition confirmation replaces a fixed sleep
        # after set_position(). A real disconnect (empty response) still
        # raises ValveError immediately via _apply_status_response -- only a
        # "still busy" result is tolerated up to the timeout, at which point
        # this returns False. Hardware workflows must treat that as an
        # unconfirmed position and stop their next actuator command.
        if self.backend is None:
            return True
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while True:
            raw_response = self.backend.query(self.status_query_command)
            self._apply_status_response(raw_response)
            if self.status_note in ("ready", "confirmed"):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(max(poll_interval_s, 0.0))

    def cleanup(self) -> None:
        if self.backend is not None:
            self.backend.close()
        self.initialized = False
        self.status_note = ""
