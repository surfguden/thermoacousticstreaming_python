from .base import DeviceWorker
from ..domain.models import DeviceId

class PumpWorker(DeviceWorker):
    def __init__(self, driver=None, parent=None):
        super().__init__(DeviceId.PUMP, parent=parent); self.driver = driver
        self.register("set-flow", self.set_flow); self.register("stop", self.stop)
    def set_flow(self, flow_ul_min: float):
        if not -10000 <= flow_ul_min <= 10000: raise ValueError("flow_ul_min out of range")
        if self.driver: self.driver.generate_flow(flow_ul_min)
        self.state.readings["flow_ul_min"] = flow_ul_min; self.state.active = flow_ul_min != 0
    def stop(self):
        if self.driver: self.driver.stop()
        self.state.active = False
