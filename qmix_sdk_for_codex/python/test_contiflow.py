from qmixsdk.qmixpump import ContiFlowProperty, ContiFlowPump, ContiFlowSwitchingMode
import test_common
import unittest
import time
import sys

from qmixsdk import qmixbus
from qmixsdk import qmixpump
from qmixsdk import qmixvalve
from test_common import parse_test_args

class CapiNemesysTestCase(test_common.QmixTestBase):
    """
    Test for testing the python integration of the QmixSDK pump interface
    """

    def step01_capi_open(self):
        """
        Tests opening the connection to the devices
        """
        print("Opening bus with deviceconfig ", deviceconfig)
        self.bus = qmixbus.Bus()
        self.bus.open(deviceconfig, 0)


    def step02_pump_construction(self):
        """
        Tests the runtime construction of a continuous flow pump from two
        syringe pumps
        """
        print("Building conti flow pump...")
        syringe_pump1 = qmixpump.Pump()
        syringe_pump1.lookup_by_name("neMESYS_Low_Pressure_1_Pump")
        syringe_pump2 = qmixpump.Pump()
        syringe_pump2.lookup_by_name("neMESYS_Low_Pressure_2_Pump")
        self.contiflow_pump1 = ContiFlowPump()
        self.contiflow_pump1.create(syringe_pump1, syringe_pump2)

        valve1 = qmixvalve.Valve()
        valve1.lookup_by_name("neMESYS_Low_Pressure_1_Valve")
        self.contiflow_pump1.configure_contiflow_valve(0, 0, valve1, 1, 0, -1)

        valve2 = qmixvalve.Valve()
        valve2.lookup_by_name("neMESYS_Low_Pressure_2_Valve")
        self.contiflow_pump1.configure_contiflow_valve(1, 0, valve2, 1, 0, -1)


    def step03_bus_start(self):
        print("Starting bus communication...")
        self.bus.start()


    def step04_contiflow_pump_configuration(self):
        """
        Tests configuration of continuous flow pump
        """
        print("Configuring pump devices...")
        syringe_pump1 = self.contiflow_pump1.get_syringe_pump(0)
        syringe_pump1.set_syringe_param(4.60659, 60)
        syringe_pump2 = self.contiflow_pump1.get_syringe_pump(1)
        syringe_pump2.set_syringe_param(4.60659, 60)
        self.contiflow_pump1.set_volume_unit(qmixpump.UnitPrefix.milli, qmixpump.VolumeUnit.litres)
        self.contiflow_pump1.set_flow_unit(qmixpump.UnitPrefix.milli, qmixpump.VolumeUnit.litres, 
            qmixpump.TimeUnit.per_second)


    @staticmethod
    def setup_contiflow_parameters(pump : ContiFlowPump, crossflow_seconds):
        """
        Helper function to avoid code duplication
        """
        pump.set_device_property(ContiFlowProperty.SWITCHING_MODE,
        ContiFlowSwitchingMode.CROSS_FLOW)
        max_refill_flow = pump.get_device_property(ContiFlowProperty.MAX_REFILL_FLOW)
        pump.set_device_property(ContiFlowProperty.REFILL_FLOW, max_refill_flow / 2.0)
        pump.set_device_property(ContiFlowProperty.CROSSFLOW_DURATION_S, crossflow_seconds)
        pump.set_device_property(ContiFlowProperty.OVERLAP_DURATION_S, 0)
        max_conti_flow = pump.get_flow_rate_max()
        print("Max. conti flow rate: ", max_conti_flow)



    def step05_contiflow_parameters(self):
        """
        Tests the setting of the continuous flow parameters
        """
        self.setup_contiflow_parameters(self.contiflow_pump1, 2)


    def step06_set_devices_enabled(self):
        """
        This function clears all device errors and sets all devices into
        enabled state
        """
        print("Setting devices into enabled state..")
        self.contiflow_pump1.clear_fault()
        self.contiflow_pump1.enable(True)


    def step07_initialize_contiflow(self):
        """
        This function tests the initialization procedure for the continuous
        flow pump
        """
        print("Running reference move for both syringe pumps..")
        syringe_pump1 = self.contiflow_pump1.get_syringe_pump(0)
        syringe_pump1.calibrate()
        syringe_pump2 = self.contiflow_pump1.get_syringe_pump(1)
        syringe_pump2.calibrate()
        timeout_timer = qmixbus.PollingTimer(30000)
        timeout_timer.wait_until(syringe_pump1.is_calibration_finished, True)
        timeout_timer.wait_until(syringe_pump2.is_calibration_finished, True)

        print("Initializing continuous flow..")
        self.contiflow_pump1.initialize()
        timeout_timer.wait_until(self.contiflow_pump1.is_initialized, True)


    def step08_continuous_flow(self):
        """
        Test continuous flow functionality
        """
        flow_rate = self.contiflow_pump1.get_flow_rate_max()
        print("Starting continuous flow with flow rate ", flow_rate)
        self.contiflow_pump1.generate_flow(flow_rate)
        timer = qmixbus.PollingTimer(30000)
        while not timer.is_expired():
            time.sleep(1)
            print("Current flow: ", self.contiflow_pump1.get_flow_is(),
                " Remaining seconds: ", timer.get_msecs_to_expiration() / 1000) 

        flow_rate = flow_rate / 2
        print("Starting continuous flow with flow rate ", flow_rate)
        self.contiflow_pump1.generate_flow(flow_rate)
        timer.set_period(34000)
        timer.restart()
        while not timer.is_expired():
            time.sleep(1)
            print("Current flow: ", self.contiflow_pump1.get_flow_is(),
                " Remaining seconds: ", timer.get_msecs_to_expiration() / 1000) 

        self.contiflow_pump1.stop_pumping()
        time.sleep(1)


    def step09_device_lookup(self):
        """
        Tests lookup of conti flow pump declared in device properties XML file
        """
        print("Looking up ContiFlowPump_1...")
        self.contiflow_pump2 = ContiFlowPump()
        self.contiflow_pump2.lookup_by_name("ContiFlowPump_1")  
        self.setup_contiflow_parameters(self.contiflow_pump2, 1)
        if not self.contiflow_pump2.is_initialized():
            self.contiflow_pump2.initialize()
            timeout_timer = qmixbus.PollingTimer(30000)
            timeout_timer.wait_until(self.contiflow_pump2.is_initialized, True)


    def step10_volume_dosing(self):
        """
        Tests volume dosing in continuous flow
        """
        syringe_pump1 = self.contiflow_pump2.get_syringe_pump(0)
        max_syringe_level = syringe_pump1.get_volume_max()  
        flow_rate = self.contiflow_pump2.get_flow_rate_max()
        target_volume = max_syringe_level * 1.5
        print("Starting volume dosing with target volume ", target_volume)
        self.contiflow_pump2.pump_volume(target_volume, flow_rate)  
        time.sleep(0.1)
        timer = qmixbus.PollingTimer(60000)
        while (self.contiflow_pump2.is_pumping() == True) and not timer.is_expired():
            time.sleep(1)
            print("Dosed volume: ", self.contiflow_pump2.get_dosed_volume()) 


    def step25_capi_close(self):
        """
        Tests closing of the bus api
        """
        print("Closing bus...")
        self.bus.stop()
        self.bus.close()


if __name__ == '__main__':
    deviceconfig = parse_test_args("contiflow")
    del sys.argv[1:]
    unittest.main()
