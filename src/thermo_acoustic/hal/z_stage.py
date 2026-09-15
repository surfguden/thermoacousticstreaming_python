from .base import DeviceWorker
from ..domain.models import DeviceId
class ZStageWorker(DeviceWorker):
    def __init__(self, driver=None, parent=None):
        super().__init__(DeviceId.Z_STAGE, parent=parent); self.driver = driver; self.register("enable-closed-loop", self.enable); self.register("move", self.move)
    def enable(self): self.state.configured = True; self.state.readings["closed_loop"] = True
    def move(self, position_um: float):
        if not 0 <= position_um <= 450: raise ValueError("position_um must be between 0 and 450")
        if not self.state.readings.get("closed_loop"): raise RuntimeError("Enable closed-loop before moving")
        if self.driver: self.driver.move_to(position_um)
        self.state.readings["position_um"] = position_um
