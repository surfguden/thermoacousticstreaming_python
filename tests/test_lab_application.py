from __future__ import annotations

import sys
import unittest

from thermo_acoustic.application.validation import ActionValidationError
from thermo_acoustic.domain import DeviceId, ExperimentPlan, ExperimentState, ExperimentStep
from thermo_acoustic.infrastructure import build_simulated_application


HARDWARE_MODULES = {
    "thermo_acoustic.instruments",
    "thermo_acoustic.waveforms",
    "thermo_acoustic.hamamatsu_dcam",
    "thermo_acoustic.qmix_backend",
    "thermo_acoustic.nemesys_pump",
    "thermo_acoustic.thorlabs_piezo",
    "thermo_acoustic.tec",
}


class LabApplicationTests(unittest.TestCase):
    def test_simulated_startup_does_not_import_hardware_modules(self) -> None:
        app = build_simulated_application()

        self.assertEqual(app.snapshot().mode.value, "simulation")
        self.assertTrue(HARDWARE_MODULES.isdisjoint(sys.modules))

    def test_actions_require_connection_and_are_validated(self) -> None:
        app = build_simulated_application()

        with self.assertRaisesRegex(ActionValidationError, "Connect ad2"):
            app.execute(DeviceId.AD2, "start")

        app.connect(DeviceId.AD2)
        with self.assertRaisesRegex(ActionValidationError, "amplitude_v"):
            app.execute(
                DeviceId.AD2,
                "configure_waveform",
                {"frequency_hz": 1_000_000, "amplitude_v": 6},
            )

        app.execute(
            DeviceId.AD2,
            "configure_waveform",
            {"frequency_hz": 1_000_000, "amplitude_v": 1},
        )
        self.assertEqual(
            app.snapshot().devices[DeviceId.AD2].values["frequency_hz"],
            1_000_000,
        )

    def test_experiment_runner_owns_sequence_progression(self) -> None:
        app = build_simulated_application()
        app.connect(DeviceId.AD2)
        plan = ExperimentPlan(
            "offline",
            (
                ExperimentStep(
                    DeviceId.AD2,
                    "configure_waveform",
                    {"frequency_hz": 1000, "amplitude_v": 0.5},
                ),
                ExperimentStep(DeviceId.AD2, "start"),
            ),
        )

        app.experiment.start(plan, now=0)
        self.assertTrue(app.experiment.tick(now=0))
        self.assertIs(app.experiment.state, ExperimentState.RUNNING)
        self.assertTrue(app.experiment.tick(now=0))
        self.assertIs(app.experiment.state, ExperimentState.COMPLETED)
        self.assertTrue(app.snapshot().devices[DeviceId.AD2].values["running"])

    def test_shutdown_disconnects_every_simulated_device(self) -> None:
        app = build_simulated_application()
        for device in DeviceId:
            app.connect(device)

        self.assertEqual(app.shutdown(), [])
        self.assertTrue(
            all(
                state.connection.value == "disconnected"
                for state in app.snapshot().devices.values()
            )
        )
