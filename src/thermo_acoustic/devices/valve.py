from .base import DeviceWorker
from ..domain.models import DeviceId
class ValveWorker(DeviceWorker):
    def __init__(self, driver=None, parent=None):
        super().__init__(DeviceId.VALVE, parent=parent); self.driver = driver; self.register("set-position", self.set_position)
    def set_position(self, position: int):
        if position not in (1, 2): raise ValueError("position must be 1 or 2")
        if self.driver: self.driver.set_position(position)
        self.state.readings["position"] = position

