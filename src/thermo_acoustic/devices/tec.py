from .base import DeviceWorker
from ..domain.models import DeviceId
class TecWorker(DeviceWorker):
    def __init__(self, driver=None, parent=None):
        super().__init__(DeviceId.TEC, parent=parent); self.driver = driver; self.register("set-temperature", self.set_temperature); self.register("outputs-off", self.stop)
    def set_temperature(self, temperature_c: float):
        if not -20 <= temperature_c <= 120: raise ValueError("temperature_c out of range")
        if self.driver: self.driver.apply_static_setpoint({1: temperature_c})
        self.state.readings["temperature_c"] = temperature_c; self.state.active = True
    def stop(self): self.state.active = False

