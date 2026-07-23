from __future__ import annotations

import ctypes
import sys
import threading
import time

import pytest

from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend, HamamatsuDcamError


class FakeFrame:
    def copy(self):
        return "frame-copy"


class FakeDcamApi:
    @classmethod
    def init(cls):
        return True

    @classmethod
    def uninit(cls):
        return True

    @classmethod
    def lasterr(cls):
        return "ok"


class FakeDcamModule:
    Dcamapi = FakeDcamApi
    instances = []

    class DCAM_IDPROP:
        EXPOSURETIME = "EXPOSURETIME"
        TRIGGERSOURCE = "TRIGGERSOURCE"

    class DCAMPROP:
        class TRIGGERSOURCE:
            INTERNAL = 1
            EXTERNAL = 2
            SOFTWARE = 3

    class Dcam:
        def __init__(self, index):
            self.index = index
            self.opened = False
            self.calls = []
            FakeDcamModule.instances.append(self)

        def is_opened(self):
            return self.opened

        def dev_open(self):
            self.opened = True
            self.calls.append(("dev_open",))
            return True

        def dev_close(self):
            self.opened = False
            self.calls.append(("dev_close",))
            return True

        def lasterr(self):
            return "ok"

        def prop_setgetvalue(self, prop, value, option=0):
            self.calls.append(("prop_setgetvalue", prop, value, option))
            return value

        def prop_setvalue(self, prop, value):
            self.calls.append(("prop_setvalue", prop, value))
            return True

        def buf_release(self):
            self.calls.append(("buf_release",))
            return True

        def buf_alloc(self, frames):
            self.calls.append(("buf_alloc", frames))
            return True

        def cap_start(self, sequence=True):
            self.calls.append(("cap_start", sequence))
            return True

        def cap_snapshot(self):
            self.calls.append(("cap_snapshot",))
            return True

        def cap_stop(self):
            self.calls.append(("cap_stop",))
            return True

        def wait_capevent_frameready(self, timeout):
            self.calls.append(("wait", timeout))
            return True

        def buf_getlastframedata(self):
            self.calls.append(("buf_getlastframedata",))
            return FakeFrame()

        def dev_getcapability(self):
            self.calls.append(("dev_getcapability",))
            return False


class FakeCapabilitySupportsTimestamp:
    def is_support_timestamp(self):
        return True


class FakeDcamTimestamp:
    def __init__(self, sec, microsec):
        self.sec = sec
        self.microsec = microsec


class FakeFrameStruct:
    def __init__(self, sec, microsec):
        self.timestamp = FakeDcamTimestamp(sec, microsec)


class FakeTimestampDcamModule(FakeDcamModule):
    instances = []

    class Dcam(FakeDcamModule.Dcam):
        def __init__(self, index):
            self.index = index
            self.opened = False
            self.calls = []
            self._next_frame_sec = 1000
            FakeTimestampDcamModule.instances.append(self)

        def dev_getcapability(self):
            self.calls.append(("dev_getcapability",))
            return FakeCapabilitySupportsTimestamp()

        def buf_getframe(self, iframe):
            self.calls.append(("buf_getframe", iframe))
            sec = self._next_frame_sec
            self._next_frame_sec += 1
            return FakeFrameStruct(sec, 500), FakeFrame()


class FakeTimeoutError:
    def is_timeout(self):
        return True

    def __str__(self):
        return "timeout"


class FakeTimeoutDcamModule(FakeDcamModule):
    instances = []

    class Dcam(FakeDcamModule.Dcam):
        def __init__(self, index):
            self.index = index
            self.opened = False
            self.calls = []
            FakeTimeoutDcamModule.instances.append(self)

        def lasterr(self):
            return FakeTimeoutError()

        def wait_capevent_frameready(self, timeout):
            self.calls.append(("wait", timeout))
            return False


def test_image_sequence_reuses_active_capture_buffer_without_reallocating():
    FakeDcamModule.instances = []
    backend = HamamatsuDcamBackend(buffer_frames=3)
    backend.dcam_module = FakeDcamModule
    backend.dcamapi = FakeDcamApi

    backend.configure_sequence({"frames": 1, "trigger_source": "internal", "exposure_ms": 10})
    backend.start_capture()
    frames = backend.image_sequence(1)
    backend.stop_capture()
    backend.close()

    camera = FakeDcamModule.instances[0]
    assert frames == ["frame-copy"]
    assert ("buf_alloc", 3) in camera.calls
    assert camera.calls.count(("buf_alloc", 3)) == 1
    assert camera.calls.count(("cap_start", True)) == 1
    assert camera.calls.index(("buf_alloc", 3)) < camera.calls.index(("cap_start", True))
    assert ("wait", 1000) in camera.calls
    assert ("buf_getlastframedata",) in camera.calls


def test_image_sequence_still_starts_capture_when_not_already_active():
    FakeDcamModule.instances = []
    backend = HamamatsuDcamBackend(buffer_frames=3)
    backend.dcam_module = FakeDcamModule
    backend.dcamapi = FakeDcamApi

    frames = backend.image_sequence(2)
    backend.close()

    camera = FakeDcamModule.instances[0]
    assert frames == ["frame-copy", "frame-copy"]
    assert ("buf_alloc", 3) in camera.calls
    assert ("cap_start", True) in camera.calls
    assert camera.calls.index(("buf_alloc", 3)) < camera.calls.index(("cap_start", True))


def test_image_sequence_captures_real_dcam_timestamps_when_supported():
    FakeTimestampDcamModule.instances = []
    backend = HamamatsuDcamBackend(buffer_frames=3)
    backend.dcam_module = FakeTimestampDcamModule
    backend.dcamapi = FakeDcamApi

    frames = backend.image_sequence(3)
    timestamps = backend.read_frame_timestamps()
    backend.close()

    camera = FakeTimestampDcamModule.instances[0]
    assert frames == ["frame-copy", "frame-copy", "frame-copy"]
    assert len(timestamps) == 3
    assert len(set(timestamps)) == 3, "each frame should get its own distinct timestamp, not one shared value"
    assert all(ts.startswith("dcam_clock:") for ts in timestamps)
    assert ("dev_getcapability",) in camera.calls
    assert ("buf_getframe", -1) in camera.calls
    assert ("buf_getlastframedata",) not in camera.calls


def test_wait_frame_timeout_stops_capture_releases_buffer_and_raises():
    FakeTimeoutDcamModule.instances = []
    backend = HamamatsuDcamBackend(buffer_frames=3, timeout_ms=1, frame_total_timeout_s=0.003)
    backend.dcam_module = FakeTimeoutDcamModule
    backend.dcamapi = FakeDcamApi

    try:
        backend.capture_snapshot()
    except HamamatsuDcamError as exc:
        assert "Timed out waiting for Hamamatsu frame during capture_snapshot" in str(exc)
    else:
        raise AssertionError("frame-ready timeout should raise")
    finally:
        backend.close()

    camera = FakeTimeoutDcamModule.instances[0]
    assert ("cap_snapshot",) in camera.calls
    assert camera.calls.count(("cap_stop",)) == 1
    assert camera.calls.count(("buf_release",)) >= 1
    assert ("buf_getlastframedata",) not in camera.calls
    assert backend.capture_active is False
    assert backend.allocated_buffer_frames == 0


def test_ctypes_style_blocking_wait_allows_second_python_thread_to_run():
    if sys.platform != "win32":
        pytest.skip("ctypes DCAM wait wrapper in this repository uses windll on Windows.")

    sleep = ctypes.windll.kernel32.Sleep
    sleep.argtypes = [ctypes.c_ulong]
    sleep.restype = None

    class CtypesBlockingWait:
        def wait_capevent_frameready(self, timeout_ms):
            sleep(int(timeout_ms))
            return False

    started = threading.Event()
    second_thread_ran = threading.Event()
    finished = threading.Event()
    timing: dict[str, float] = {}
    wait_object = CtypesBlockingWait()

    def blocking_wait():
        timing["wait_started"] = time.perf_counter()
        started.set()
        wait_object.wait_capevent_frameready(250)
        timing["wait_finished"] = time.perf_counter()
        finished.set()

    def simple_python_operation():
        timing["second_thread_ran"] = time.perf_counter()
        second_thread_ran.set()

    wait_thread = threading.Thread(target=blocking_wait)
    wait_thread.start()
    assert started.wait(1.0)
    worker_thread = threading.Thread(target=simple_python_operation)
    worker_thread.start()

    assert second_thread_ran.wait(0.1)
    assert timing["second_thread_ran"] < timing.get("wait_finished", float("inf"))
    elapsed_s = timing["second_thread_ran"] - timing["wait_started"]
    print(f"CTYPES_BLOCKING_WAIT_SECOND_THREAD_DELAY_S={elapsed_s:.6f}")

    assert elapsed_s < 0.1
    assert finished.wait(1.0)
    wait_thread.join(1.0)
    worker_thread.join(1.0)
