import unittest
import argparse
import os

class QmixTestBase(unittest.TestCase):
    def _steps(self):
        for name in sorted(dir(self)):
            if name.startswith("step"):
                yield name, getattr(self, name) 


    def test_steps(self):
        for name, step in self._steps():
            try:
                step()
            except Exception as e:
                self.fail("{} failed ({}: {})".format(step, type(e), e))


def parse_test_args(default_dev_cfg_name):
    """
    Function parses the command line arguments and return the device config
    path
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--devcfg_name", help="name of the device configuration that is located in the deviceconfig_folder", default=default_dev_cfg_name)
    parser.add_argument("devcfg_folder", help="path to the folder that contains the device configuration")
    args = parser.parse_args()
    deviceconfig = os.path.join(args.devcfg_folder, args.devcfg_name)
    return deviceconfig