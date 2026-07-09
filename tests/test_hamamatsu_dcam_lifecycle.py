from __future__ import annotations

from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend


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

        def cap_stop(self):
            self.calls.append(("cap_stop",))
            return True

        def wait_capevent_frameready(self, timeout):
            self.calls.append(("wait", timeout))
            return True

        def buf_getlastframedata(self):
            self.calls.append(("buf_getlastframedata",))
            return FakeFrame()


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
