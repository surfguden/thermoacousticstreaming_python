from __future__ import annotations

import time

from thermo_acoustic.instruments import SerialTextCommandBackend


class _FakeCarriageReturnOnlyPort:
    """Mimics a real device that only ever terminates responses with "\\r",
    never "\\n" -- matches the real valve hardware behavior confirmed in a
    real-hardware verification session. `read()` mirrors pyserial's own
    semantics: it returns buffered bytes instantly if any are available,
    otherwise blocks for `timeout` seconds and returns empty. `readline()`
    is a faithful reimplementation of the generic algorithm the real
    `serial.Serial.readline()` falls back to (documented via the OLD
    behavior actually observed on real hardware, Session 54): drain
    whatever is buffered, then block for the full timeout on the next
    read() before giving up -- because it never finds the "\\n" it's
    looking for, even though the correct "\\r"-terminated bytes were
    already sitting in the buffer. `read_until()` reimplements pyserial
    3.5's real algorithm (confirmed via `inspect.getsource` against the
    installed package): read byte-by-byte, stop as soon as the requested
    terminator is seen.
    """

    def __init__(self, response: bytes, timeout: float) -> None:
        self._buffer = bytearray(response)
        self.timeout = timeout
        self.written: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if self._buffer:
            chunk = bytes(self._buffer[:size])
            del self._buffer[:size]
            return chunk
        time.sleep(self.timeout)
        return b""

    def readline(self) -> bytes:
        line = bytearray()
        while True:
            c = self.read(1)
            if not c:
                break
            line += c
        return bytes(line)

    def read_until(self, expected: bytes = b"\n", size: int | None = None) -> bytes:
        lenterm = len(expected)
        line = bytearray()
        while True:
            c = self.read(1)
            if c:
                line += c
                if line[-lenterm:] == expected:
                    break
                if size is not None and len(line) >= size:
                    break
            else:
                break
        return bytes(line)

    def close(self) -> None:
        pass


def test_query_returns_as_soon_as_carriage_return_terminator_arrives():
    port = _FakeCarriageReturnOnlyPort(b"01\r", timeout=0.3)
    backend = SerialTextCommandBackend(port=port, line_ending="\r")

    start = time.monotonic()
    result = backend.query("S")
    elapsed = time.monotonic() - start

    assert result == "01\r"
    assert port.written == [b"S\r"]
    assert elapsed < 0.1, (
        f"query() took {elapsed:.3f}s but the \\r-terminated response was "
        "available immediately -- it should not wait anywhere near the "
        "configured timeout_s"
    )


class _FakePortThatRaisesOnClose:
    def __init__(self) -> None:
        self.close_attempts = 0

    def close(self) -> None:
        self.close_attempts += 1
        raise RuntimeError("simulated OS-level close failure")


def test_close_resets_port_to_none_even_when_port_close_raises():
    # M1 (instruments.py line-by-line review): previously self.port = None
    # only ran after port.close() returned -- if close() raised, self.port
    # stayed set to the broken handle, so a future _open() would see
    # self.port is not None and skip reopening entirely (permanently
    # reusing a broken handle), and a future close() would try to close
    # the same broken handle again.
    port = _FakePortThatRaisesOnClose()
    backend = SerialTextCommandBackend(port=port)

    try:
        backend.close()
        raise AssertionError("close() must still propagate the real exception")
    except RuntimeError as exc:
        assert "simulated OS-level close failure" in str(exc)

    assert backend.port is None, "port must be reset even though close() raised"

    # A subsequent close() must not try to close the same broken port again.
    backend.close()
    assert port.close_attempts == 1


def test_readline_based_read_would_have_blocked_for_the_full_timeout():
    """Proves the bug the fix above closes: the exact call the old
    query() implementation made (self.port.readline()) reproduces the
    real, hardware-confirmed failure mode (Session 54) against this same
    fake -- the correct bytes ("01\\r") are available immediately, but
    readline() still blocks for the full configured timeout before
    returning them, since it's looking for a "\\n" that never arrives.
    """
    port = _FakeCarriageReturnOnlyPort(b"01\r", timeout=0.2)

    start = time.monotonic()
    result = port.readline()
    elapsed = time.monotonic() - start

    assert result == b"01\r"
    assert elapsed >= 0.2
