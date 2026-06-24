from __future__ import annotations

from dataclasses import dataclass, field
import time

from .instruments import AD2Sdk, CetoniPump, HamamatsuCamera, PriorZMotor, Valve
from .messages import Message, MessageName, QueueResult, UiEvent
from .queues import LabViewQueue
from .workflows import Experiment2, ExperimentSeries2, FlushSettings


@dataclass(slots=True)
class Application:
    ad2: AD2Sdk = field(default_factory=AD2Sdk)
    camera: HamamatsuCamera = field(default_factory=HamamatsuCamera)
    pump: CetoniPump = field(default_factory=CetoniPump)
    valve: Valve = field(default_factory=Valve)
    z_motor: PriorZMotor = field(default_factory=PriorZMotor)
    experiment_series: ExperimentSeries2 = field(default_factory=ExperimentSeries2)
    status: str = "System Not Initialized"
    main_queue: LabViewQueue = field(default_factory=lambda: LabViewQueue("Main Queue"))
    ui_events: list[UiEvent] = field(default_factory=list)
    status_events: list[str] = field(default_factory=list)
    errors: list[BaseException | str] = field(default_factory=list)
    stop_fired: bool = False
    _running: bool = False

    def create_queues(self) -> None:
        self.main_queue = LabViewQueue("Main Queue")

    def create_ui_event(self) -> None:
        self.ui_events.clear()

    def create_stop_event(self) -> None:
        self.stop_fired = False

    def register_events(self) -> None:
        # LabVIEW registers UI and stop events for the event loop. In Python the
        # lists above are the observable event streams.
        self.create_ui_event()
        self.create_stop_event()

    def enqueue_main(self, message: Message) -> None:
        self.main_queue.enqueue(message)

    def dequeue_main(self, timeout_ms: int = -1) -> QueueResult:
        return self.main_queue.dequeue(timeout_ms=timeout_ms)

    def peek_queue_main(self) -> QueueResult:
        return self.main_queue.peek()

    def flush_main_queue(self) -> list[Message]:
        return self.main_queue.flush()

    def fire_stop_event(self) -> None:
        self.stop_fired = True
        self._running = False

    def fire_ui_event(self, message: MessageName | str, data: object = None) -> None:
        self.ui_events.append(UiEvent(message=message, data=data))

    def fire_status_event(self, status: str) -> None:
        self.status = status
        self.status_events.append(status)
        self.fire_ui_event(MessageName.UPDATE_STATUS, status)

    def get_ad2_sdk(self) -> AD2Sdk:
        return self.ad2

    def set_ad2_sdk(self, ad2: AD2Sdk) -> None:
        self.ad2 = ad2

    def get_hamamatsu(self) -> HamamatsuCamera:
        return self.camera

    def set_hamamatsu(self, camera: HamamatsuCamera) -> None:
        self.camera = camera

    def get_valve(self) -> Valve:
        return self.valve

    def set_valve(self, valve: Valve) -> None:
        self.valve = valve

    def get_cetoni_pump(self) -> CetoniPump:
        return self.pump

    def set_cetoni_pump(self, pump: CetoniPump) -> None:
        self.pump = pump

    def get_prior_zmotor(self) -> PriorZMotor:
        return self.z_motor

    def set_prior_zmotor(self, z_motor: PriorZMotor) -> None:
        self.z_motor = z_motor

    def get_experiment_series_general(self) -> ExperimentSeries2:
        return self.experiment_series

    def set_experiment_series_general(self, experiment_series: ExperimentSeries2) -> None:
        self.experiment_series = experiment_series

    def check_loop_error(self, error: BaseException | str | None = None) -> bool:
        if error is None:
            return False
        self.errors.append(error)
        return True

    def error_handler_event_loop(self, error: BaseException | str | None = None) -> bool:
        if not self.check_loop_error(error):
            return False
        self.fire_status_event("EventLoopError")
        return True

    def error_handler_main_loop(self, error: BaseException | str | None = None) -> bool:
        if not self.check_loop_error(error):
            return False
        self.fire_status_event("MainLoopError")
        self.fire_stop_event()
        return True

    def z_stack(self, positions: list[float], exposure_ms: float | None = None) -> list[object]:
        if exposure_ms is not None:
            self.camera.configure_exposure_time(exposure_ms)

        images: list[object] = []
        for position in positions:
            if self.listen_abort():
                self.fire_status_event("ZStackAborted")
                break
            self.z_motor.go_to_abs_pos(position)
            images.append(self.camera.capture_snapshot())
        if images and self.status != "ZStackAborted":
            self.fire_status_event("ZStackComplete")
        return images

    def initialize(self) -> None:
        self.create_queues()
        self.register_events()
        self.fire_status_event("Initializing")
        for instrument in (self.ad2, self.camera, self.pump, self.valve, self.z_motor):
            instrument.initialize()
        self.fire_status_event("System Initialized")

    def cleanup(self) -> None:
        for instrument in (self.camera, self.pump, self.valve, self.z_motor, self.ad2):
            instrument.cleanup()
        self.fire_stop_event()
        self.fire_status_event("System Not Initialized")

    def wait(self, seconds: float) -> Message | None:
        deadline = time.monotonic() + max(seconds, 0.0)
        while time.monotonic() < deadline:
            result = self.peek_queue_main()
            if result.message is not None:
                return result.message
            time.sleep(min(0.05, max(deadline - time.monotonic(), 0.0)))
        return None

    def listen_abort(self) -> bool:
        result = self.peek_queue_main()
        if result.message is None:
            return False
        return result.message.name in (MessageName.ABORT, MessageName.EXIT, "Abort", "Exit")

    def wait_for_pump(self, timeout_s: float) -> bool:
        self.fire_status_event("Waiting for Pump")
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while self.pump.read_status():
            if self.listen_abort():
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True

    def flush(self, settings: FlushSettings) -> bool:
        self.fire_status_event("Flushing")
        self.valve.set_position(1)
        self.wait(1.0)

        new_fill_level = self.pump.fill_level - settings.fill_level_delta
        self.pump.set_fill_level(new_fill_level)
        self.pump.generate_flow(settings.flush_flowrate)

        completed = self.wait_for_pump(settings.timeout_s)
        if not completed:
            return False

        self.valve.set_position(2)
        self.wait(settings.wait_after_flush_s)
        self.pump.set_fill_level(new_fill_level)
        self.fire_status_event("FlushComplete")
        return True

    def run_experiment2(self) -> bool:
        experiment, timed_out = self.experiment_series.dequeue_experiment()
        if timed_out or experiment is None:
            self.fire_status_event("NoExperiment")
            return False

        self.fire_status_event("Initializing Experiment")
        experiment_folder = experiment.create_folder_and_tdms()
        experiment.save_settings()

        self.ad2.config_wfg(experiment.wfg_config)
        self.ad2.config_do_clock_special(experiment.do_clock_settings)

        self.camera.configure(exposure_ms=experiment.global_exposure_ms)
        self.camera.configure_sequence(experiment.sequence_settings)
        self.camera.start_capture()
        self.ad2.pc_trigger()

        self.fire_status_event("Running Experiment Frame")
        frame_count = 0
        if experiment.sequence_settings:
            frame_count = int(experiment.sequence_settings.get("frames", 0) or 0)
        image_data = self.camera.image_sequence(frame_count=frame_count)

        aborted = self.listen_abort()
        self.camera.stop_capture()

        if aborted:
            self.fire_status_event("ExperimentAborted")
            experiment.cleanup()
            return False

        self.flush(experiment.flush_settings)
        self.camera.save_sequence(image_data, experiment_folder)
        experiment.save_image_data(image_data)
        experiment.save_camera_settings(
            {
                "buffer_size": self.camera.get_camera_buffer_size(),
                "sub_region": self.camera.get_sub_region(),
                "readout_time": self.camera.read_readout_time(),
            }
        )
        experiment.cleanup()
        self.fire_status_event("ExperimentComplete")
        return True

    def handle_message(self, message: Message) -> None:
        name = MessageName(message.name) if message.name in MessageName._value2member_map_ else message.name

        if name == MessageName.INITIALIZE:
            self.initialize()
        elif name == MessageName.CONFIGURE_CAMERA:
            self.fire_status_event("Configuring Camera")
            exposure_ms = message.data.get("exposure_ms") if isinstance(message.data, dict) else None
            self.camera.configure(exposure_ms=exposure_ms)
            self.enqueue_main(Message(MessageName.CAMERA_CONFIGURED))
        elif name == MessageName.CAMERA_CONFIGURED:
            self.fire_status_event("CameraConfigured")
        elif name == MessageName.PUMP_INIT:
            self.pump.initialize()
        elif name == MessageName.CETONI_REFILL:
            self.pump.refill()
        elif name == MessageName.CETONI_EMPTY:
            self.pump.empty()
        elif name == MessageName.CETONI_STOP_DOSING:
            self.pump.stop()
        elif name == MessageName.CETONI_GENERATE_FLOW:
            flow_rate = float(message.data or 0.0)
            self.pump.generate_flow(flow_rate)
        elif name == MessageName.CETONI_SET_FILL_LEVEL:
            self.pump.set_fill_level(float(message.data or 0.0))
        elif name == MessageName.VALVE_POS_1:
            self.valve.set_position(1)
        elif name == MessageName.VALVE_POS_2:
            self.valve.set_position(2)
        elif name == MessageName.FLUSH:
            if not isinstance(message.data, FlushSettings):
                raise TypeError("Flush message requires FlushSettings data")
            self.flush(message.data)
        elif name == MessageName.RUN_EXPERIMENT2:
            self.run_experiment2()
        elif name in (MessageName.EXIT, MessageName.ABORT):
            self.fire_stop_event()
        else:
            raise ValueError(f"Unhandled message: {message.name}")

    def run_until_idle(self) -> None:
        self._running = True
        while self._running and len(self.main_queue):
            result = self.dequeue_main()
            if result.message is not None:
                self.handle_message(result.message)
