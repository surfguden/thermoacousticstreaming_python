from time import monotonic, sleep

from PySide6.QtWidgets import QApplication

from thermo_acoustic.application.commands import DeviceCommand, DeviceOperation
from thermo_acoustic.application.controller import ApplicationController
from thermo_acoustic.application.z_stack import ZStackSettings
from thermo_acoustic.domain.models import DeviceId, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry


def wait(app, predicate, timeout=6):
    deadline = monotonic() + timeout
    while monotonic() < deadline and not predicate():
        app.processEvents()
        sleep(0.01)
    assert predicate()


def test_simulated_z_stack_saves_verified_positions_and_camera_metadata(tmp_path):
    app = QApplication.instance() or QApplication(["test-z-stack"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    try:
        for device in (DeviceId.CAMERA, DeviceId.Z_STAGE):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        wait(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok
                              for result in results) == 2)
        controller.submit(DeviceCommand(DeviceId.Z_STAGE,
                                        DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ))
        wait(app, lambda: any(result.operation is DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ
                              and result.ok for result in results))
        controller.submit(DeviceCommand(DeviceId.Z_STAGE,
                                        DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE))
        wait(app, lambda: controller.statuses()[DeviceId.Z_STAGE].readback.closed_loop)
        controller.z_stack.start(ZStackSettings(10, 12, 3, 2.5, (0, 0, 16, 16), tmp_path))
        wait(app, lambda: controller.z_stack.state in {"completed", "failed"}, timeout=12)
        assert controller.z_stack.state == "completed", controller.z_stack.detail
        import json
        metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
        assert [point["target_um"] for point in metadata["points"]] == [10, 11, 12]
        assert [point["observed_um"] for point in metadata["points"]] == [10, 11, 12]
        assert metadata["applied_camera_settings"]["roi"]["horizontal_size"] == 16
        assert len(list(tmp_path.glob("point_*.tif"))) == 3
    finally:
        controller.shutdown()
