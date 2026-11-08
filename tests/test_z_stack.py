from time import monotonic, sleep

from PySide6.QtWidgets import QApplication

from thermo_acoustic.application.commands import DeviceCommand, DeviceOperation, ZStageSetPositionArgs
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


# ------------------------------------------------ stale callbacks and late results after a run has ended
import json
import threading
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QObject, Signal

from thermo_acoustic.application.z_stack import ZStackRunner
from thermo_acoustic.domain.models import ConnectionState, DeviceStatus, ZStageReadback


class FakeController(QObject):
    """Just enough controller for the runner: it records every command and lets a test deliver results itself."""
    command_result = Signal(object)

    def __init__(self):
        super().__init__()
        self.commands = []
        self.experiments = SimpleNamespace(batch_active=False, status=lambda: {"syringe_preflight_active": False})
        self.count_preflight_active = False
        self.close_requested = False

    def statuses(self):
        stage = ZStageReadback(closed_loop=True, max_travel_um=450.0)
        return {DeviceId.CAMERA: DeviceStatus(DeviceId.CAMERA, ConnectionState.CONNECTED),
                DeviceId.Z_STAGE: DeviceStatus(DeviceId.Z_STAGE, ConnectionState.CONNECTED, readback=stage)}

    def submit(self, command):
        self.commands.append(command)
        return command.request_id

    def reads(self):
        return [c for c in self.commands if c.operation is DeviceOperation.Z_STAGE_POSITION_READ]

    def deliver(self, command, value=None, ok=True, error=None):
        self.command_result.emit(SimpleNamespace(request_id=command.request_id, ok=ok, value=value, error=error,
                                                 operation=command.operation))


def _runner(tmp_path, name="a"):
    controller = FakeController()
    runner = ZStackRunner(controller)
    folder = tmp_path / name
    folder.mkdir()
    return controller, runner, folder


def _start_run(runner, folder, points=3):
    runner.start(ZStackSettings(10, 12, points, 2.5, (0, 0, 16, 16), folder))
    return runner


def _into_position_wait(controller, runner):
    """Take a run to the state in the report: a position read came back short of the target, so the next read is
    scheduled on a 100 ms timer."""
    runner._camera_ready = lambda readback: None  # skip configuring; set up the point directly
    runner.current_index = 0
    runner._deadline = monotonic() + 30
    runner._position_read(SimpleNamespace(position_um=0.0))  # far from the target: schedules the retry


def _spin(app, seconds):
    end = monotonic() + seconds
    while monotonic() < end:
        app.processEvents()
        sleep(0.005)


def test_a_retry_timer_scheduled_before_a_panic_abort_sends_nothing_and_keeps_the_aborted_state(tmp_path):
    app = QApplication.instance() or QApplication(["test-z-stack"])
    controller, runner, folder = _runner(tmp_path)
    _start_run(runner, folder)
    controller.commands.clear()
    _into_position_wait(controller, runner)
    runner.abort_for_panic()
    assert runner.state == "aborted"
    _spin(app, 0.4)  # the old 100 ms timer fires here
    assert controller.reads() == []  # it used to send one more position read
    assert json.loads((folder / "metadata.json").read_text())["state"] == "aborted"
    assert runner.state == "aborted"


def test_an_old_retry_timer_cannot_touch_a_run_started_afterwards(tmp_path):
    app = QApplication.instance() or QApplication(["test-z-stack"])
    controller, runner, first = _runner(tmp_path, "first")
    _start_run(runner, first)
    _into_position_wait(controller, runner)
    runner.abort_for_panic()
    second = tmp_path / "second"
    second.mkdir()
    controller.commands.clear()
    _start_run(runner, second)  # a new run is "running" when the old timer fires
    _spin(app, 0.4)
    assert controller.reads() == []  # the first run's timer did not send a read for the second run
    assert json.loads((first / "metadata.json").read_text())["state"] == "aborted"


def test_a_late_result_after_a_failure_does_not_continue_the_run(tmp_path):
    controller, runner, folder = _runner(tmp_path)
    _start_run(runner, folder)
    runner.current_index = 0
    runner._send(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_POSITION_SET, ZStageSetPositionArgs(10.0), runner._move_accepted)
    pending = controller.commands[-1]
    runner._fail("simulated failure")
    controller.commands.clear()
    controller.deliver(pending, SimpleNamespace(position_um=10.0))  # the move result arrives after the failure
    assert controller.commands == [] and runner.state == "failed"  # it used to send the next position read


def test_a_save_finishing_after_an_abort_is_kept_and_belongs_to_the_run_that_started_it(tmp_path):
    app = QApplication.instance() or QApplication(["test-z-stack"])
    controller, runner, first = _runner(tmp_path, "first")
    _start_run(runner, first)
    release = threading.Event()
    original = ZStackRunner._save_frame

    def slow_save(path, frame):
        assert release.wait(10)
        original(path, frame)
    runner._save_frame = slow_save
    runner.current_index = 0
    runner._observed_position = 10.0
    runner._captured(SimpleNamespace(frame=np.zeros((4, 4), np.uint16)))
    runner.abort_for_panic()
    second = tmp_path / "second"
    second.mkdir()
    controller.commands.clear()
    _start_run(runner, second)
    release.set()
    _spin(app, 0.5)
    assert (first / "point_0001.tif").exists()  # the image that was being written is kept
    saved = json.loads((first / "metadata.json").read_text())
    assert saved["state"] == "aborted" and [p["file"] for p in saved["points"]] == ["point_0001.tif"]
    assert runner._records == []  # and it was not added to the new run
    assert json.loads((second / "metadata.json").read_text())["points"] == []


# ------------------------------------------------ closing while an image is still being saved
def _blocked_save_run(tmp_path, name="first"):
    controller, runner, folder = _runner(tmp_path, name)
    _start_run(runner, folder)
    release = threading.Event()
    original = ZStackRunner._save_frame

    def slow_save(path, frame):
        assert release.wait(10)
        original(path, frame)
    runner._save_frame = slow_save
    runner.current_index = 0
    runner._observed_position = 10.0
    runner._captured(SimpleNamespace(frame=np.zeros((4, 4), np.uint16)))
    return controller, runner, folder, release


def _points(folder):
    data = json.loads((folder / "metadata.json").read_text())
    return data["state"], [p["file"] for p in data["points"]]


def test_close_during_a_save_returns_with_the_image_and_its_record_together(tmp_path):
    controller, runner, folder, release = _blocked_save_run(tmp_path)
    threading.Timer(0.1, release.set).start()  # the save finishes while close() is waiting for it
    runner.close()  # no event processing afterwards: what is on disk now is what a reader sees
    assert (folder / "point_0001.tif").exists()
    assert _points(folder) == ("aborted", ["point_0001.tif"])  # used to be [] until a later Qt event
    assert runner.state == "aborted"


def test_late_callbacks_and_a_second_close_after_close_change_nothing(tmp_path):
    app = QApplication.instance() or QApplication(["test-z-stack"])
    controller, runner, folder, release = _blocked_save_run(tmp_path)
    threading.Timer(0.1, release.set).start()
    runner.close()
    controller.commands.clear()
    _spin(app, 0.3)  # the polling timer from before close fires here
    runner.close()
    assert _points(folder) == ("aborted", ["point_0001.tif"])  # recorded once, state untouched
    assert controller.commands == [] and runner.state == "aborted" and len(runner._records) == 1


def test_a_failing_save_is_reported_not_recorded(tmp_path):
    controller, runner, folder = _runner(tmp_path)
    _start_run(runner, folder)
    notices = []
    runner.notice.connect(notices.append)
    release = threading.Event()

    def failing_save(path, frame):
        assert release.wait(10)
        raise OSError("disk full")
    runner._save_frame = failing_save
    runner.current_index = 0
    runner._observed_position = 10.0
    runner._captured(SimpleNamespace(frame=np.zeros((4, 4), np.uint16)))
    runner.abort_for_panic()  # the run ends while the save is still going to fail
    threading.Timer(0.1, release.set).start()
    runner.close()
    assert _points(folder) == ("aborted", [])  # nothing is claimed that is not on disk
    assert any("disk full" in text for text in notices)


def test_a_save_from_an_old_run_closed_over_a_new_run_stays_with_the_old_run(tmp_path):
    controller, runner, first, release = _blocked_save_run(tmp_path, "first")
    runner.abort_for_panic()
    second = tmp_path / "second"
    second.mkdir()
    _start_run(runner, second)
    threading.Timer(0.1, release.set).start()
    runner.close()  # closes the second run too, while the first run's save is finishing
    assert _points(first) == ("aborted", ["point_0001.tif"])
    assert _points(second) == ("aborted", [])
