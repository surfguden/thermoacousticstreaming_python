from __future__ import annotations

import sys
import time
import unittest

from thermo_acoustic.application import DeviceNotConnectedError
from thermo_acoustic.domain import (
    ConfigureWaveform,
    ConnectDevice,
    DeviceId,
    ExperimentPlan,
    ExperimentState,
    ExperimentStep,
    MoveZStage,
    SetPumpFlow,
    StartWaveform,
    WaveformConfig,
)
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


def wait_for_experiment(app, timeout_s: float = 2.0) -> ExperimentState:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = app.experiment.status().state
        if state is not ExperimentState.RUNNING:
            return state
        time.sleep(0.005)
    raise AssertionError("Experiment did not finish")


class LabApplicationTests(unittest.TestCase):
    def test_simulated_startup_does_not_import_hardware_modules(self) -> None:
        app = build_simulated_application()
        self.addCleanup(app.shutdown)

        self.assertEqual(app.snapshot().mode.value, "simulation")
        self.assertTrue(HARDWARE_MODULES.isdisjoint(sys.modules))

    def test_typed_actions_require_connection_and_validate_at_creation(self) -> None:
        app = build_simulated_application()
        self.addCleanup(app.shutdown)

        with self.assertRaisesRegex(DeviceNotConnectedError, "Connect ad2"):
            app.execute(StartWaveform())
        with self.assertRaisesRegex(ValueError, "amplitude_v"):
            WaveformConfig(frequency_hz=1_000_000, amplitude_v=6)

        app.connect(DeviceId.AD2)
        config = WaveformConfig(frequency_hz=1_000_000, amplitude_v=1)
        app.execute(ConfigureWaveform(config))
        app.execute(StartWaveform())
        status = app.snapshot().devices[DeviceId.AD2]
        self.assertEqual(status.readings["waveform"], config)
        self.assertTrue(status.active)

    def test_z_stage_requires_explicit_closed_loop_enable(self) -> None:
        app = build_simulated_application()
        self.addCleanup(app.shutdown)
        app.connect(DeviceId.Z_STAGE)

        with self.assertRaisesRegex(RuntimeError, "Closed-loop"):
            app.execute(MoveZStage(10))

    def test_experiment_runner_owns_sequence_progression(self) -> None:
        app = build_simulated_application()
        self.addCleanup(app.shutdown)
        plan = ExperimentPlan(
            "offline",
            (
                ExperimentStep(ConnectDevice(DeviceId.AD2)),
                ExperimentStep(ConfigureWaveform(WaveformConfig(frequency_hz=1000, amplitude_v=0.5))),
                ExperimentStep(StartWaveform()),
            ),
        )

        app.start_experiment(plan)

        self.assertIs(wait_for_experiment(app), ExperimentState.COMPLETED)
        self.assertTrue(app.snapshot().devices[DeviceId.AD2].active)
        self.assertEqual(app.snapshot().message, "Experiment completed")

    def test_failed_experiment_applies_safe_stop(self) -> None:
        app = build_simulated_application()
        self.addCleanup(app.shutdown)
        app.connect(DeviceId.PUMP)
        app.execute(SetPumpFlow(100))
        plan = ExperimentPlan("fails", (ExperimentStep(StartWaveform()),))

        app.start_experiment(plan)

        self.assertIs(wait_for_experiment(app), ExperimentState.FAILED)
        self.assertFalse(app.snapshot().devices[DeviceId.PUMP].active)

    def test_shutdown_disconnects_every_simulated_device(self) -> None:
        app = build_simulated_application()
        for device in DeviceId:
            app.connect(device)

        self.assertEqual(app.shutdown(), [])
        self.assertTrue(all(not state.active for state in app.snapshot().devices.values()))
        self.assertTrue(all(state.connection.value == "disconnected" for state in app.snapshot().devices.values()))
