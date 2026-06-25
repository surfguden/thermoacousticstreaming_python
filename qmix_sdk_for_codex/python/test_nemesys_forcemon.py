import test_common
import unittest
import time
import sys

from qmixsdk import qmixbus
from qmixsdk import qmixpump
from qmixsdk.qmixbus import UnitPrefix, TimeUnit

class CapiNemesysTestCase(test_common.QmixTestBase):
    """
    Test for testing the python integration of the QmixSDK pump interface
    """

    def step01_capi_open(self):
        print("Opening bus with deviceconfig ", deviceconfig)
        self.bus = qmixbus.Bus()
        self.bus.open(deviceconfig, 0)


    def step02_device_name_lookup(self):
        print("Looking up devices...")
        self.pump = qmixpump.Pump()
        self.pump.lookup_by_name("Nemesys_S_1_Pump")


    def step03_force_monitoring_config(self):
        self.assertTrue(self.pump.has_force_monitoring())
        print("Force unit: ", self.pump.get_force_unit())
        print("Max device force: ", self.pump.get_max_device_force())


    def step04_bus_start(self):
        print("Starting bus communication...")
        self.bus.start()


    def step04_pump_enable(self):
        self.pump.enable_force_monitoring(True)
        print("Enabling pump drive...")
        if self.pump.is_in_fault_state():
            self.pump.clear_fault()
        self.assertFalse(self.pump.is_in_fault_state())
        if not self.pump.is_enabled():
            self.pump.enable(True)
        self.assertTrue(self.pump.is_enabled())
        # Nemesys S pumps have an absolute encoder and the position sensing
        # sysem should be initialized right from power on
        self.assertTrue(self.pump.is_position_sensing_initialized())


    def step05_safety_stop(self):
        self.pump.write_force_limit(0.11)
        self.pump.enable_force_monitoring(True)
        time.sleep(0.3)
        if self.pump.is_force_safety_stop_active():
            print("Safety stop active")
            return

        # now generate force by moving against a fixed block
        print("\nGenerating high force...")
        flow = self.pump.get_flow_rate_max() / 100
        print("Flow: ", flow)
        self.pump.generate_flow(flow)
        safety_stop_active = self.pump.is_force_safety_stop_active()
        while not safety_stop_active:
            time.sleep(0.5)
            print("Current force: ", self.pump.read_force_sensor())
            safety_stop_active = self.pump.is_force_safety_stop_active()


    def step06_resolve_force_overload(self):
        if not self.pump.is_force_safety_stop_active():
            print("Safety stop not active")
            return

        print("\nResolving force overload...")
        
        # disable force monitoring
        self.pump.enable_force_monitoring(False)
        time.sleep(0.3)

        # force monitoring should be inactive now and safety stop should be
        # disabled
        self.assertFalse(self.pump.is_force_monitoring_enabled(), "self.pump.is_force_monitoring_enabled()")
        self.assertFalse(self.pump.is_force_safety_stop_active(), "self.pump.is_force_safety_stop_active()")

        # Now reduce force by aspirating with a low flow rate
        print("\nReducing force below threshold...")
        flow = 0  - self.pump.get_flow_rate_max() / 100
        print("Flow: ", flow)
        self.pump.generate_flow(flow)
        safety_stop_active = False
        while not safety_stop_active:
            time.sleep(0.1)
            print("Current force: ", self.pump.read_force_sensor())
            safety_stop_active = self.pump.is_force_safety_stop_active()


        # We are below the force limit and can reenable force monitoring
        self.pump.enable_force_monitoring(True)
        time.sleep(0.3)
        self.assertTrue(self.pump.is_force_monitoring_enabled(), "self.pump.is_force_monitoring_enabled()")
        self.assertFalse(self.pump.is_force_safety_stop_active(), "self.pump.is_force_safety_stop_active()")
        
        # now we reduce force to almost 0
        print("\nLowering force to near 0...")
        self.pump.generate_flow(flow)
        current_force = self.pump.read_force_sensor()
        while (current_force > 0.04):
            time.sleep(0.5)
            print("Current force: ", current_force)
            current_force = self.pump.read_force_sensor()

        self.pump.stop_pumping()
        
        # The following function call is not required here it is just for 
        # testing if the C library function call works
        self.pump.clear_force_safety_stop()


    def step07_force_monitoring_switching(self):
        # Normally force safety stop should be inactive
        self.assertFalse(self.pump.is_force_safety_stop_active(), "self.pump.is_force_safety_stop_active()")
        
        # disable force monitoring
        print("Disabling force monitoring...")
        self.pump.enable_force_monitoring(False)
        time.sleep(0.3)

        # force monitoring should be off now and safety stop should be active
        self.assertFalse(self.pump.is_force_monitoring_enabled(), "self.pump.is_force_monitoring_enabled()")
        self.assertTrue(self.pump.is_force_safety_stop_active(), "self.pump.is_force_safety_stop_active()")

        # if safety stop is on, then pump should not be enabled
        self.assertFalse(self.pump.is_enabled())

        # We enable force monitoring - this should clear the safety stop
        print("Enabling force monitoring...")
        self.pump.enable_force_monitoring(True)
        time.sleep(0.3)

        # force monitoring should be on now and safety stop should be inactive
        self.assertTrue(self.pump.is_force_monitoring_enabled(), "self.pump.is_force_monitoring_enabled()")
        self.assertFalse(self.pump.is_force_safety_stop_active(), "self.pump.is_force_safety_stop_active()")

        # Pump should be enabled again
        self.assertTrue(self.pump.is_enabled())


    def step25_capi_close(self):
        print("Closing bus...")
        self.bus.stop()
        self.bus.close()


    
if __name__ == '__main__':
    deviceconfig = test_common.parse_test_args("testconfig_qmixsdk")
    del sys.argv[1:]
    unittest.main()
