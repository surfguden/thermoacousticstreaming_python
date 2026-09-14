from .base import DeviceWorker
from ..domain.models import DeviceId
class CameraWorker(DeviceWorker):
    def __init__(self, driver=None, parent=None):
        super().__init__(DeviceId.CAMERA, parent=parent); self.driver = driver; self.register("snapshot", self.snapshot)
    def snapshot(self):
        return self.driver.capture_snapshot() if self.driver else {"frames": 1}

