from __future__ import annotations

import ctypes
import sys
import threading
import time

import numpy as np
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
        TRIGGER_GLOBALEXPOSURE = "TRIGGER_GLOBALEXPOSURE"

    class DCAMPROP:
        class TRIGGERSOURCE:
            INTERNAL = 1
            EXTERNAL = 2
            SOFTWARE = 3

        class TRIGGER_GLOBALEXPOSURE:
            NONE = 1
            ALWAYS = 2
            DELAYED = 3
            EMULATE = 4
            GLOBALRESET = 5

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


class FakeNumpyFrame:
    def __init__(self, fill_value):
        self._fill_value = fill_value

    def copy(self):
        return np.full((2, 2), self._fill_value, dtype="uint16")


class FakeMidSequenceFaultDcamModule(FakeDcamModule):
    instances = []

    class Dcam(FakeDcamModule.Dcam):
        def __init__(self, index):
            self.index = index
            self.opened = False
            self.calls = []
            self._wait_count = 0
            FakeMidSequenceFaultDcamModule.instances.append(self)

        def wait_capevent_frameready(self, timeout):
            self._wait_count += 1
            self.calls.append(("wait", timeout))
            return self._wait_count < 3

        def lasterr(self):
            return "device fault"

        def buf_getlastframedata(self):
            self.calls.append(("buf_getlastframedata",))
            return FakeNumpyFrame(self._wait_count)

        def dev_getcapability(self):
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


class FakePartialSequenceFaultDcamModule(FakeDcamModule):
    instances = []

    class DCAM_IDPROP(FakeDcamModule.DCAM_IDPROP):
        TRIGGERPOLARITY = "TRIGGERPOLARITY"

    class DCAMPROP(FakeDcamModule.DCAMPROP):
        class TRIGGERPOLARITY:
            NEGATIVE = 1
            POSITIVE = 2

    class Dcam(FakeDcamModule.Dcam):
        def __init__(self, index):
            self.index = index
            self.opened = False
            self.calls = []
            FakePartialSequenceFaultDcamModule.instances.append(self)

        def prop_setvalue(self, prop, value):
            self.calls.append(("prop_setvalue", prop, value))
            if prop == "TRIGGERPOLARITY":
                return False
            return True


def test_failed_device_open_rolls_back_dcam_object_and_api_initialization():
    class CountingApi:
        init_calls = 0
        uninit_calls = 0

        @classmethod
        def init(cls):
            cls.init_calls += 1
            return True

        @classmethod
        def uninit(cls):
            cls.uninit_calls += 1
            return True

        @classmethod
        def lasterr(cls):
            return "no camera"

    class FailingOpenDcam(FakeDcamModule.Dcam):
        def dev_open(self):
            self.calls.append(("dev_open",))
            return False

        def lasterr(self):
            return "open failed"

    class FailingOpenModule(FakeDcamModule):
        Dcamapi = CountingApi
        Dcam = FailingOpenDcam

    backend = HamamatsuDcamBackend()
    backend.dcam_module = FailingOpenModule
    backend.dcamapi = CountingApi

    with pytest.raises(HamamatsuDcamError, match="Dcam.dev_open failed"):
        backend.open_camera()

    assert CountingApi.init_calls == 1
    assert CountingApi.uninit_calls == 1
    assert backend.initialized is False
    assert backend.dcam is None


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


def test_configure_trigger_global_exposure_enabled_sets_globalreset():
    # LabVIEW-confirmed: Hamamatsu.lvclass:ConfigureSequence.vi's
    # `globalshutter` Select node picks numeric value 5 for its true case,
    # an exact match for DCAMPROP_TRIGGER_GLOBALEXPOSURE__GLOBALRESET.
    FakeDcamModule.instances = []
    backend = HamamatsuDcamBackend()
    backend.dcam_module = FakeDcamModule
    backend.dcamapi = FakeDcamApi

    backend.configure_trigger_global_exposure(True)

    camera = FakeDcamModule.instances[0]
    assert ("prop_setvalue", "TRIGGER_GLOBALEXPOSURE", FakeDcamModule.DCAMPROP.TRIGGER_GLOBALEXPOSURE.GLOBALRESET) in camera.calls


def test_configure_trigger_global_exposure_disabled_does_not_set_property():
    # Deliberately does NOT call prop_setvalue() at all when disabled --
    # LabVIEW's own false-case value (0) is not a valid
    # TRIGGER_GLOBALEXPOSURE enum member and the property-ID constant
    # visible at that block-diagram call site does not match this
    # property's real value in the vendored DCAM-API v4 header, an
    # unresolved discrepancy (docs/known_open_items.md). Actively setting
    # a specific guessed "off" value risked being systematically wrong for
    # every future experiment's exposure timing; leaving the property
    # untouched is the conservative choice until this is confirmed against
    # the real LabVIEW application directly.
    FakeDcamModule.instances = []
    backend = HamamatsuDcamBackend()
    backend.dcam_module = FakeDcamModule
    backend.dcamapi = FakeDcamApi

    backend.configure_trigger_global_exposure(False)

    camera = FakeDcamModule.instances[0]
    assert not any(call[0] == "prop_setvalue" and call[1] == "TRIGGER_GLOBALEXPOSURE" for call in camera.calls)


def test_configure_sequence_partial_failure_does_not_update_sequence_settings():
    # Finding 1 regression test (hamamatsu_dcam.py review, Session 65):
    # sequence_settings was previously assigned up front, before any of the
    # individual DCAM property writes were confirmed applied. Here
    # trigger_source really gets written to the (fake) device before
    # trigger_polarity fails -- a genuine partial hardware application, not
    # a pre-flight rejection -- and sequence_settings must still reflect
    # the last configuration that was fully confirmed, not the failed one.
    FakePartialSequenceFaultDcamModule.instances = []
    backend = HamamatsuDcamBackend()
    backend.dcam_module = FakePartialSequenceFaultDcamModule
    backend.dcamapi = FakeDcamApi

    backend.configure_sequence({"trigger_source": "internal", "frames": 1})
    assert backend.sequence_settings == {"trigger_source": "internal", "frames": 1}

    with pytest.raises(HamamatsuDcamError):
        backend.configure_sequence({"trigger_source": "external", "trigger_polarity": "negative", "frames": 9})

    camera = FakePartialSequenceFaultDcamModule.instances[0]
    assert (
        "prop_setvalue",
        "TRIGGERSOURCE",
        FakePartialSequenceFaultDcamModule.DCAMPROP.TRIGGERSOURCE.EXTERNAL,
    ) in camera.calls, "trigger_source must have really been written before trigger_polarity failed"
    assert backend.sequence_settings == {"trigger_source": "internal", "frames": 1}, (
        "a mid-sequence failure must not leave sequence_settings reflecting the unconfirmed request"
    )


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


def test_image_sequence_saves_partial_capture_on_mid_sequence_fault(tmp_path):
    FakeMidSequenceFaultDcamModule.instances = []
    backend = HamamatsuDcamBackend(buffer_frames=5)
    backend.dcam_module = FakeMidSequenceFaultDcamModule
    backend.dcamapi = FakeDcamApi

    try:
        backend.image_sequence(5, partial_capture_folder=tmp_path)
    except HamamatsuDcamError as exc:
        assert "wait frame ready failed" in str(exc)
    else:
        raise AssertionError("expected the mid-sequence fault to propagate")
    finally:
        backend.close()

    partial_dir = tmp_path / "partial_2_of_5"
    saved_files = sorted(partial_dir.glob("frame_*.tiff"))
    assert len(saved_files) == 2, "the 2 frames captured before the fault should be saved, tagged as partial"


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
