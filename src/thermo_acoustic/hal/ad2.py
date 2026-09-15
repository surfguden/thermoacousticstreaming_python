from .base import DeviceWorker
from ..domain.models import DeviceId

class AD2Worker(DeviceWorker):
    """HAL worker; the real AD2 SDK is supplied by a lazy driver factory."""
    def __init__(self, driver=None, parent=None):
        super().__init__(DeviceId.AD2, parent=parent); self.driver = driver
        self.register("configure", self.configure); self.register("start", self.start); self.register("stop", self.stop)
    def configure(self, frequency_hz=1000.0, amplitude_v=1.0):
        if frequency_hz <= 0 or not 0 <= amplitude_v <= 5: raise ValueError("invalid AD2 settings")
        self.state.configured = True; self.state.readings.update(frequency_hz=frequency_hz, amplitude_v=amplitude_v)
        if self.driver: self.driver.wfg_configure({})
    def start(self):
        if self.driver: self.driver.wfg_start_stop_all_ch(True)
        self.state.active = True
    def stop(self):
        if self.driver: self.driver.wfg_start_stop_all_ch(False)
        self.state.active = False
