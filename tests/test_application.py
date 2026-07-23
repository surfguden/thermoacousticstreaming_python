from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

from thermo_acoustic.application import Application
from thermo_acoustic.ad2 import (
    CarrierSettings,
    DigitalOutIdleState,
    DigitalOutType,
    DoConfig,
    DoSingleChannelConfig,
    TriggerSettings,
    TriggerSource,
    WaveformFunction,
    WfgChannelConfig,
    WfgConfig,
    coerce_do_config,
    coerce_wfg_config,
)
from thermo_acoustic.camera import MinMaxInc, SubRegion, SubRegionLimits
from thermo_acoustic.filetypes import FT_FILE_TYPES, LVFileType, get_exported_file_list, get_file_type, is_file_an_llb
from thermo_acoustic.imaq import (
    ImageType,
    hamamatsu_show_sequence,
    imaq_array_to_image,
    imaq_copy,
    imaq_create,
    imaq_dispose,
    imaq_wind_close,
    imaq_wind_display_mapping,
    imaq_wind_draw,
    imaq_wind_zoom_2,
    imaq_write_bmp_file_2,
    imaq_write_png_file_2,
)
from thermo_acoustic.instruments import AD2Sdk, CetoniPump, HamamatsuCamera, PriorZMotor, RegloPumpControl, SimulatedAD2Sdk, Valve
from thermo_acoustic.messages import Message, MessageName
from thermo_acoustic.qmix_backend import QmixPumpBackend, SYRINGE_PRESETS
from thermo_acoustic.serial_config import (
    visa_configure_serial_port,
    visa_configure_serial_port_instr,
    visa_configure_serial_port_serial_instr,
)
from thermo_acoustic.utilities import (
    DialogType,
    DialogTypeEnum,
    EventVKey,
    LVBounds,
    LVMinMaxInc,
    LVRect,
    TagReturnType,
    WHITESPACE,
    application_directory,
    check_if_file_or_folder_exists,
    build_help_path,
    check_special_tags,
    clear_errors,
    convert_property_node_font_to_graphics_font,
    correct_error_chain,
    details_display_dialog,
    error_converter,
    error_cluster_from_error_code,
    error_code_database,
    find_tag,
    format_message_string,
    format_time_string,
    general_error_handler,
    general_error_handler_core,
    get_help_dir,
    get_rt_host_connected_prop,
    get_string_text_bounds,
    get_text_rect,
    longest_line_length_in_pixels,
    not_found_dialog,
    search_and_replace_pattern,
    set_bold_text,
    set_string_value,
    simple_error_handler,
    sub_elapsed_time,
    sub_file_dialog,
    three_button_dialog,
    three_button_dialog_core,
    trim_whitespace,
    trim_whitespace_one_sided,
)
from thermo_acoustic.waveforms import WaveFormsBackend
from thermo_acoustic.workflows import Experiment2, ExperimentSeries2, FlushSettings


def install_fake_nptdms(monkeypatch):
    writes = {}

    class FakeRootObject:
        def __init__(self, properties=None):
            self.kind = "root"
            self.properties = properties or {}

    class FakeGroupObject:
        def __init__(self, name, properties=None):
            self.kind = "group"
            self.name = name
            self.properties = properties or {}

    class FakeChannelObject:
        def __init__(self, group, name, data):
            self.kind = "channel"
            self.group = group
            self.name = name
            self.data = list(data)

    class FakeTdmsWriter:
        def __init__(self, path):
            self.path = Path(path)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def write_segment(self, objects):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(b"fake tdms")
            writes[str(self.path)] = objects

    monkeypatch.setitem(
        sys.modules,
        "nptdms",
        SimpleNamespace(
            ChannelObject=FakeChannelObject,
            GroupObject=FakeGroupObject,
            RootObject=FakeRootObject,
            TdmsWriter=FakeTdmsWriter,
        ),
    )
    return writes


def test_initialize_updates_status():
    app = Application(ad2=SimulatedAD2Sdk())
    app.enqueue_main(Message(MessageName.INITIALIZE))

    app.run_until_idle()

    assert app.status == "System Initialized"
    assert "System Initialized" in app.status_events


def test_priority_message_is_dequeued_first():
    app = Application()
    app.enqueue_main(Message("normal"))
    app.enqueue_main(Message("priority", priority=True))

    result = app.dequeue_main()

    assert result.message is not None
    assert result.message.name == "priority"


def test_top_level_utility_ports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello", encoding="utf-8")

    assert application_directory() == tmp_path
    assert check_if_file_or_folder_exists(file_path)
    assert not check_if_file_or_folder_exists(tmp_path / "missing.txt")
    assert sub_elapsed_time(10.0, now_s=12.5) == 2.5
    assert format_time_string(3661.25) == "01:01:01.25"
    assert trim_whitespace("  abc\t") == "abc"
    assert trim_whitespace_one_sided("  abc  ", left=True, right=False) == "abc  "
    assert trim_whitespace_one_sided("  abc  ", left=False, right=True) == "  abc"
    assert search_and_replace_pattern("a-b-a", "a", "x") == "x-b-x"
    assert search_and_replace_pattern("a11b22", r"\d+", "#", regex=True) == "a#b#"
    assert find_tag("prefix <tag> suffix", "<tag>") == 7
    assert format_message_string("{name}: {value}", name="pump", value=4) == "pump: 4"

    error = error_cluster_from_error_code(7, "source")
    assert error.status
    assert error.code == 7
    assert error_converter(0, status=True, source="forced").status
    assert clear_errors(error).status is False


def test_ni_filetype_ports(tmp_path):
    vi = tmp_path / "main.vi"
    vi.write_text("", encoding="utf-8")
    llb = tmp_path / "bundle.llb"
    llb.write_text("", encoding="utf-8")
    packed = tmp_path / "runtime.lvlibp"
    packed.write_text("", encoding="utf-8")
    nested = tmp_path / "folder"
    nested.mkdir()
    exported = nested / "export.vi"
    exported.write_text("", encoding="utf-8")

    assert LVFileType.VI.value in FT_FILE_TYPES
    assert get_file_type(vi) == LVFileType.VI
    assert get_file_type(tmp_path / "control.ctl") == LVFileType.CONTROL
    assert get_file_type(packed) == LVFileType.PACKED_LIBRARY
    assert is_file_an_llb(llb)
    assert not is_file_an_llb(vi)
    assert get_exported_file_list(vi) == [vi]
    assert get_exported_file_list(nested) == [exported]


def test_dialog_error_and_text_utility_ports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    primary = error_cluster_from_error_code(0, "primary")
    secondary = error_cluster_from_error_code(9, "secondary")

    assert correct_error_chain(primary, secondary) is secondary
    assert simple_error_handler(secondary) == "9: secondary"
    assert general_error_handler(RuntimeError("boom")) == "boom"
    assert general_error_handler_core(secondary) == (True, "9: secondary")
    assert not_found_dialog("camera") == "Not found: camera"
    assert three_button_dialog("question", default=1) == "No"
    assert three_button_dialog_core("question", default=2) == "Cancel"
    assert details_display_dialog("message", "details") == {"message": "message", "details": "details"}
    assert sub_file_dialog(default="file.txt") == Path("file.txt")

    assert get_help_dir() == tmp_path / "help"
    assert build_help_path("topic.html") == tmp_path / "help" / "topic.html"
    assert longest_line_length_in_pixels("abc\nabcdef", font_size=10) == 36
    assert get_text_rect("abc", font_size=10).height == 10
    assert get_string_text_bounds("abc", font_size=10).width == 18
    assert convert_property_node_font_to_graphics_font({"name": "Arial"}) == {"name": "Arial"}
    assert set_bold_text("hello") == {"text": "hello", "bold": True}
    assert set_string_value({"old": True}, "new") == {"old": True, "value": "new"}
    assert check_special_tags("a <b> c <d>") == ["<b>", "<d>"]
    assert error_code_database(0) == "No error"
    assert error_code_database(5) == "Error 5"
    assert get_rt_host_connected_prop()


def test_serial_imaq_and_typedef_ports(tmp_path):
    serial = visa_configure_serial_port("COM4", baud_rate=115200, timeout_ms=500)
    assert serial.resource_name == "COM4"
    assert serial.baud_rate == 115200
    assert serial.timeout_ms == 500
    assert visa_configure_serial_port_instr("COM5").resource_name == "COM5"
    assert visa_configure_serial_port_serial_instr("COM6").resource_name == "COM6"

    assert LVRect(1, 2, 3, 4).right == 3
    assert LVBounds(10, 20).height == 20
    assert LVMinMaxInc(0, 10, 2).increment == 2
    assert DialogType.ERROR.value == "error"
    assert DialogTypeEnum.OK.value == "ok"
    assert EventVKey.ENTER.value == "enter"
    assert TagReturnType.FOUND.value == "found"
    assert "\n" in WHITESPACE
    assert RegloPumpControl(running=True, speed=2.5).running

    image = imaq_create("test", ImageType.U8)
    image = imaq_array_to_image([[0, 64], [128, 255]], image)
    assert image.image is not None
    copied = imaq_copy(image)
    assert copied.image is not image.image
    assert imaq_wind_display_mapping(copied, {"min": 0, "max": 255}) == {"min": 0, "max": 255}
    assert imaq_wind_zoom_2(copied, 2.0) == 2.0
    imaq_wind_draw(copied, {"line": [0, 0, 1, 1]})
    assert copied.drawings == [{"line": [0, 0, 1, 1]}]
    png = imaq_write_png_file_2(copied, tmp_path / "image.png")
    bmp = imaq_write_bmp_file_2(copied, tmp_path / "image.bmp")
    assert png.exists()
    assert bmp.exists()
    assert hamamatsu_show_sequence([image, copied])["count"] == 2
    imaq_wind_close(copied)
    assert not copied.window_open
    imaq_dispose(copied)
    assert copied.disposed


def test_flush_sets_valve_and_status():
    app = Application()
    app.pump.fill_level = 1.0

    ok = app.flush(FlushSettings(flush_flowrate=10.0, flush_volume_ml=6.0, wait_after_flush_s=0.0))

    assert ok
    assert app.valve.position == 2
    assert app.pump.fill_level == 0.9
    assert app.status == "FlushComplete"


def test_application_instrument_accessors():
    app = Application(ad2=SimulatedAD2Sdk())
    ad2 = SimulatedAD2Sdk()
    camera = HamamatsuCamera()
    pump = CetoniPump()
    valve = Valve()
    z_motor = PriorZMotor()
    series = ExperimentSeries2()

    app.set_ad2_sdk(ad2)
    app.set_hamamatsu(camera)
    app.set_cetoni_pump(pump)
    app.set_valve(valve)
    app.set_prior_zmotor(z_motor)
    app.set_experiment_series_general(series)

    assert app.get_ad2_sdk() is ad2
    assert app.get_hamamatsu() is camera
    assert app.get_cetoni_pump() is pump
    assert app.get_valve() is valve
    assert app.get_prior_zmotor() is z_motor
    assert app.get_experiment_series_general() is series


def test_cleanup_times_out_blocked_device_and_continues_to_later_devices():
    calls = []
    cleanup_started = threading.Event()

    class BlockingCleanupInstrument:
        def cleanup(self):
            calls.append(("camera", "cleanup_started"))
            cleanup_started.set()
            threading.Event().wait()

    class RecordingCleanupInstrument:
        def __init__(self, name):
            self.name = name

        def cleanup(self):
            calls.append((self.name, "cleanup"))

    app = Application(
        camera=BlockingCleanupInstrument(),
        pump=RecordingCleanupInstrument("pump"),
        valve=RecordingCleanupInstrument("valve"),
        z_motor=RecordingCleanupInstrument("z_motor"),
        ad2=RecordingCleanupInstrument("ad2"),
    )
    app.cleanup_device_timeout_s = 0.05
    app.cleanup_total_timeout_s = 0.5

    started_at = time.perf_counter()
    try:
        app.cleanup()
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("blocked cleanup should be reported")
    elapsed_s = time.perf_counter() - started_at

    assert cleanup_started.is_set()
    assert elapsed_s < 0.5
    assert "camera cleanup timed out" in message
    assert ("pump", "cleanup") in calls
    assert ("valve", "cleanup") in calls
    assert ("z_motor", "cleanup") in calls
    assert ("ad2", "cleanup") in calls


def test_application_error_handlers_and_z_stack():
    app = Application(ad2=SimulatedAD2Sdk())

    assert not app.check_loop_error()
    assert app.error_handler_event_loop("camera warning")
    assert app.status == "EventLoopError"
    assert app.errors == ["camera warning"]

    assert app.error_handler_main_loop(RuntimeError("main loop failed"))
    assert app.status == "MainLoopError"
    assert app.stop_fired
    assert len(app.errors) == 2

    app = Application(ad2=SimulatedAD2Sdk())
    images = app.z_stack([0.0, 1.5, 3.0], exposure_ms=7.5)
    assert len(images) == 3
    assert app.camera.exposure_ms == 7.5
    assert app.z_motor.position == 3.0
    assert app.status == "ZStackComplete"


def test_run_experiment2_processes_one_experiment(tmp_path, monkeypatch):
    install_fake_nptdms(monkeypatch)
    app = Application(ad2=SimulatedAD2Sdk())
    app.pump.fill_level = 1.0
    experiment = Experiment2(
        experiment_folder=tmp_path / "experiment-1",
        flush_settings=FlushSettings(flush_flowrate=10.0, flush_volume_ml=6.0, wait_after_flush_s=0.0),
        global_exposure_ms=12.5,
        sequence_settings={"frames": 3},
        wfg_config={"frequency_hz": 1000},
        do_clock_settings={"secWait": 1},
    )
    app.experiment_series.enqueue_experiments([experiment])

    ok = app.run_experiment2()

    assert ok
    assert app.experiment_series.see_elements_left() == 0
    assert app.camera.exposure_ms == 12.5
    assert app.ad2.wfg_config is not None
    assert app.ad2.do_clock_settings is not None
    assert app.status == "ExperimentComplete"
    assert (tmp_path / "experiment-1").exists()


def test_stateful_instrument_methods():
    ad2 = SimulatedAD2Sdk()
    assert ad2.open_and_use_first_device() is not None
    ad2.config_do_custom({"pattern": [1, 0]})
    ad2.pc_trigger()
    assert ad2.get_phdwf() is not None
    assert ad2.triggered
    ad2.cleanup()
    assert ad2.get_phdwf() is None

    pump = CetoniPump(simulate=True)
    pump.initialize()
    pump.configure_syringe({"diameter_mm": 10})
    pump.configure_flow_unit("ul/min")
    pump.refill()
    pump.generate_flow(5)
    pump.reference_move()
    assert pump.fill_level == 1.0
    assert pump.flow_unit == "ul/min"
    assert not pump.read_status()
    pump.empty()
    assert pump.fill_level == 0.0

    valve = Valve()
    valve.initialize()
    valve.set_position(2)
    assert valve.initialized
    assert valve.position == 2
    valve.cleanup()
    assert not valve.initialized

    z_motor = PriorZMotor()
    z_motor.initialize()
    z_motor.go_to_abs_pos(12.3)
    assert z_motor.read_position() == 12.3
    assert not z_motor.read_movement()
    z_motor.zero_pos()
    assert z_motor.read_position() == 0.0

    camera = HamamatsuCamera(simulate=True)
    camera.initialize()
    camera.configure_exposure_time(4.2)
    camera.update_roi_limits(
        SubRegionLimits(
            horizontal_size=MinMaxInc(0, 100, 1),
            vertical_size=MinMaxInc(0, 80, 1),
        )
    )
    camera.configure_roi(SubRegion(horizontal_size=20, vertical_size=10))
    camera.center_roi()
    camera.start_capture()
    assert camera.get_handle_out() is not None
    roi = camera.read_subregion_limits_and_value()[1]
    assert isinstance(roi, SubRegion)
    assert roi.horizontal_offset == 40
    assert roi.vertical_offset == 35
    assert len(camera.image_sequence(2)) == 2
    assert camera.capture_snapshot() is not None
    camera.cleanup()
    assert not camera.capturing


class FakeTextBackend:
    def __init__(self, responses=None):
        self.commands = []
        self.responses = responses or {}
        self.closed = False

    def write(self, command):
        self.commands.append(("write", command))

    def query(self, command):
        self.commands.append(("query", command))
        return self.responses.get(command, "0")

    def close(self):
        self.commands.append(("close",))
        self.closed = True


def test_valve_and_prior_backend_commands():
    valve_backend = FakeTextBackend({"S": "1\r"})
    valve = Valve(backend=valve_backend, command_position_1="P1", command_position_2="P2")
    valve.initialize()
    assert valve.initialized
    assert valve.status_note == "confirmed"
    valve.set_position(2)
    valve.cleanup()
    assert valve_backend.commands == [
        ("write", "OPEN COM6"),
        ("query", "S"),
        ("write", "P2"),
        ("close",),
    ]


def test_valve_initialize_raises_on_empty_status_response():
    valve_backend = FakeTextBackend({"S": ""})
    valve = Valve(backend=valve_backend, visa_resource="COM6")

    try:
        valve.initialize()
    except Exception as exc:
        assert "COM6" in str(exc)
    else:
        raise AssertionError("expected initialize() to raise when the valve does not respond")

    assert not valve.initialized


def test_valve_initialize_flags_unparseable_status_response():
    valve_backend = FakeTextBackend({"S": "??\r"})
    valve = Valve(backend=valve_backend)

    valve.initialize()

    assert valve.initialized
    assert "unverified" in valve.status_note

    motor_backend = FakeTextBackend({"P": "12.5", "$": "IDLE"})
    motor = PriorZMotor(backend=motor_backend)
    motor.initialize()
    motor.go_to_abs_pos(12.5)
    assert motor.read_position() == 12.5
    assert not motor.read_movement()
    motor.zero_pos()
    motor.cleanup()
    assert motor_backend.commands == [
        ("write", "OPEN COM7"),
        ("write", "G 12.5"),
        ("query", "P"),
        ("query", "$"),
        ("write", "Z"),
        ("close",),
    ]


def test_serial_text_backend_has_longer_bounded_write_timeout():
    from thermo_acoustic.instruments import SerialTextCommandBackend

    backend = SerialTextCommandBackend()

    assert backend.timeout_s == 1.0
    assert backend.write_timeout_s == 5.0


class FakePumpBackend:
    def __init__(self):
        self.calls = []
        self.status = False

    def initialize(self, configuration_path):
        self.calls.append(("initialize", configuration_path))

    def refill(self):
        self.calls.append(("refill",))

    def empty(self):
        self.calls.append(("empty",))

    def stop(self):
        self.calls.append(("stop",))
        self.status = False

    def generate_flow(self, flow_rate):
        self.calls.append(("generate_flow", flow_rate))
        self.status = True

    def set_fill_level(self, fill_level, flow_rate=None):
        if flow_rate is None:
            self.calls.append(("set_fill_level", fill_level))
        else:
            self.calls.append(("set_fill_level", fill_level, flow_rate))

    def configure_syringe(self, config):
        self.calls.append(("configure_syringe", config))

    def configure_flow_unit(self, unit):
        self.calls.append(("configure_flow_unit", unit))

    def reference_move(self):
        self.calls.append(("reference_move",))

    def read_status(self):
        self.calls.append(("read_status",))
        return self.status

    def close(self):
        self.calls.append(("close",))


def test_cetoni_backend_commands():
    backend = FakePumpBackend()
    pump = CetoniPump(simulate=False, backend=backend)
    pump.initialize()
    pump.configure_syringe({"diameter_mm": 10})
    pump.configure_flow_unit("ul/min")
    pump.refill()
    pump.set_fill_level(0.5)
    pump.generate_flow(2.5)
    assert pump.read_status()
    pump.reference_move()
    pump.empty()
    pump.cleanup()

    assert backend.calls == [
        ("initialize", pump.configuration_path),
        ("configure_syringe", {"diameter_mm": 10}),
        ("configure_flow_unit", "ul/min"),
        ("refill",),
        ("set_fill_level", 0.5),
        ("generate_flow", 2.5),
        ("read_status",),
        ("reference_move",),
        ("empty",),
        ("stop",),
        ("close",),
    ]


class FakeQmixBusModule:
    class UnitPrefix:
        micro = "micro"
        milli = "milli"

    class TimeUnit:
        per_second = "per_second"
        per_minute = "per_minute"

    class Bus:
        def __init__(self):
            self.calls = []

        def open(self, configuration_path, plugin_search_path):
            self.calls.append(("open", configuration_path, plugin_search_path))

        def start(self):
            self.calls.append(("start",))

        def stop(self):
            self.calls.append(("stop",))

        def close(self):
            self.calls.append(("close",))


class FakeQmixPumpModule:
    UnitPrefix = FakeQmixBusModule.UnitPrefix
    TimeUnit = FakeQmixBusModule.TimeUnit

    class VolumeUnit:
        litres = "litres"

    class Pump:
        instances = []

        def __init__(self):
            self.calls = []
            self.fault = False
            self.enabled = False
            self.pumping = False
            self.max_flow = 5000.0
            self.max_volume = 10.0
            FakeQmixPumpModule.Pump.instances.append(self)

        def lookup_by_device_index(self, index):
            self.calls.append(("lookup_by_device_index", index))

        def lookup_by_name(self, name):
            self.calls.append(("lookup_by_name", name))

        def is_in_fault_state(self):
            self.calls.append(("is_in_fault_state",))
            return self.fault

        def clear_fault(self):
            self.calls.append(("clear_fault",))
            self.fault = False

        def is_enabled(self):
            self.calls.append(("is_enabled",))
            return self.enabled

        def enable(self, enable):
            self.calls.append(("enable", enable))
            self.enabled = enable

        def set_volume_unit(self, prefix, unit):
            self.calls.append(("set_volume_unit", prefix, unit))

        def set_flow_unit(self, prefix, unit, time_unit):
            self.calls.append(("set_flow_unit", prefix, unit, time_unit))

        def get_flow_rate_max(self):
            self.calls.append(("get_flow_rate_max",))
            return self.max_flow

        def get_volume_max(self):
            self.calls.append(("get_volume_max",))
            return self.max_volume

        def set_syringe_param(self, inner_diameter_mm, max_piston_stroke_mm):
            self.calls.append(("set_syringe_param", inner_diameter_mm, max_piston_stroke_mm))

        def set_fill_level(self, level, flow):
            self.calls.append(("set_fill_level", level, flow))
            self.pumping = True

        def generate_flow(self, flow):
            self.calls.append(("generate_flow", flow))
            self.pumping = True

        def stop_pumping(self):
            self.calls.append(("stop_pumping",))
            self.pumping = False

        def calibrate(self):
            self.calls.append(("calibrate",))

        def is_calibration_finished(self):
            self.calls.append(("is_calibration_finished",))
            return True

        def is_pumping(self):
            self.calls.append(("is_pumping",))
            return self.pumping


def test_qmix_pump_backend_initializes_and_dispatches(tmp_path):
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(
        qmixbus=FakeQmixBusModule,
        qmixpump=FakeQmixPumpModule,
        pump_name="Pump A",
    )
    config = tmp_path / "qmix-config"

    backend.initialize(config)
    backend.configure_syringe({"name": "BD 1ml"})
    backend.generate_flow(-5000.0)
    assert backend.read_status()
    backend.set_fill_level(0.5)
    backend.reference_move()
    backend.empty()
    backend.refill()
    backend.close()

    pump = FakeQmixPumpModule.Pump.instances[0]
    diameter, stroke = SYRINGE_PRESETS["BD 1ml"]
    assert ("lookup_by_name", "Pump A") in pump.calls
    assert ("enable", True) in pump.calls
    assert ("set_flow_unit", FakeQmixPumpModule.UnitPrefix.micro, FakeQmixPumpModule.VolumeUnit.litres, FakeQmixPumpModule.TimeUnit.per_minute) in pump.calls
    assert ("set_volume_unit", FakeQmixPumpModule.UnitPrefix.milli, FakeQmixPumpModule.VolumeUnit.litres) in pump.calls
    assert ("set_syringe_param", diameter, stroke) in pump.calls
    assert ("generate_flow", -5000.0) in pump.calls
    assert ("set_fill_level", 5.0, 5000.0) in pump.calls
    assert ("calibrate",) in pump.calls
    assert ("set_fill_level", 0.0, 5000.0) in pump.calls
    assert ("set_fill_level", 10.0, 5000.0) in pump.calls


class FakeCameraBackend:
    def __init__(self):
        self.calls = []
        self.handle = object()
        self.limits = SubRegionLimits(
            horizontal_size=MinMaxInc(0, 100, 1),
            vertical_size=MinMaxInc(0, 80, 1),
        )
        self.roi = SubRegion(horizontal_size=20, vertical_size=10)

    def open_camera(self):
        self.calls.append(("open_camera",))
        return self.handle

    def configure_exposure_time(self, exposure_ms):
        self.calls.append(("configure_exposure_time", exposure_ms))

    def configure_roi(self, roi):
        self.calls.append(("configure_roi", roi))
        self.roi = roi

    def configure_snapshot(self, settings=None):
        self.calls.append(("configure_snapshot", settings))

    def configure_sequence(self, settings):
        self.calls.append(("configure_sequence", settings))

    def start_capture(self):
        self.calls.append(("start_capture",))

    def stop_capture(self):
        self.calls.append(("stop_capture",))

    def capture_snapshot(self):
        self.calls.append(("capture_snapshot",))
        return "snapshot"

    def image_sequence(self, frame_count=0):
        self.calls.append(("image_sequence", frame_count))
        return [f"frame-{i}" for i in range(frame_count)]

    def save_sequence(self, image_data, folder):
        self.calls.append(("save_sequence", image_data, folder))
        folder.mkdir(parents=True, exist_ok=True)

    def get_camera_buffer_size(self):
        self.calls.append(("get_camera_buffer_size",))
        return 42

    def read_subregion_limits_and_value(self):
        self.calls.append(("read_subregion_limits_and_value",))
        return self.limits, self.roi

    def update_roi_limits(self, limits=None):
        self.calls.append(("update_roi_limits", limits))
        if limits is not None:
            self.limits = limits
        return self.limits

    def read_readout_time(self):
        self.calls.append(("read_readout_time",))
        return 0.012

    def sw_trigger(self):
        self.calls.append(("sw_trigger",))

    def close(self):
        self.calls.append(("close",))


def test_hamamatsu_backend_commands(tmp_path):
    backend = FakeCameraBackend()
    camera = HamamatsuCamera(backend=backend)
    assert camera.open_camera() is backend.handle
    camera.configure_exposure_time(3.5)
    camera.configure_roi(SubRegion(horizontal_size=20, vertical_size=10))
    camera.configure_snapshot({"mode": "snap"})
    camera.configure_sequence({"frames": 2})
    camera.start_capture()
    assert camera.capture_snapshot() == "snapshot"
    assert camera.image_sequence(2) == ["frame-0", "frame-1"]
    camera.save_sequence(["frame-0"], tmp_path / "sequence")
    assert (tmp_path / "sequence").exists()
    assert camera.get_camera_buffer_size() == 42
    limits, roi = camera.read_subregion_limits_and_value()
    assert limits is backend.limits
    assert roi is backend.roi
    assert camera.update_roi_limits().horizontal_size.maximum == 100
    assert camera.read_readout_time() == 0.012
    camera.sw_trigg()
    camera.cleanup()

    assert ("open_camera",) in backend.calls
    assert ("configure_exposure_time", 3.5) in backend.calls
    assert ("start_capture",) in backend.calls
    assert ("stop_capture",) in backend.calls
    assert ("close",) in backend.calls


def test_experiment_series_helpers(tmp_path):
    first = Experiment2(experiment_folder=tmp_path / "first")
    series = ExperimentSeries2(series_path=tmp_path)

    created = series.create_experiments([first])

    assert created == [first]
    assert series.get_series_path() == tmp_path
    assert series.see_elements_left() == 1


def test_ad2_wfg_and_do_methods():
    ad2 = SimulatedAD2Sdk()

    wfg = WfgConfig(channels=[WfgChannelConfig(0), WfgChannelConfig(1)])
    ad2.wfg_configure(wfg)
    assert ad2.wfg_check_config_valid()
    ad2.wfg_start_stop_all_ch(True)
    assert ad2.wfg_configure_read_back().running
    replacement = WfgChannelConfig(0)
    replacement.carrier.frequency_hz = 2000
    ad2.wfg_configure_single_ch(0, replacement)
    assert ad2.get_wfg_config().channels[0].carrier.frequency_hz == 2000

    do_config = DoConfig(channels=[DoSingleChannelConfig(channel_index=0)])
    ad2.do_configure(do_config)
    ad2.do_divider_config(0, 4)
    ad2.do_enable_set(0, True)
    ad2.do_config_trigger("trigsrcPC")
    bits = ad2.do_custom_pattern_build_array(2, 3)
    ad2.do_configure_custom_pattern(0, bits)
    ad2.start_stop_do(True)

    channel = ad2.get_do_config().channel(0)
    assert channel.clock_divider == 4
    assert channel.enable
    assert channel.trigger.source == "trigsrcPC"
    assert channel.custom_data.bits == [1, 1, 0, 0, 0]
    assert ad2.get_do_config().running

    ad2.do_reset()
    assert not ad2.get_do_config().channels

    ad2.mso_init(phdwf=123)
    assert ad2.get_mso_config().device_handle == 123
    assert TriggerSource.NONE.value == "trigsrcNone"


def test_ad2_nested_dict_config_coercion():
    wfg = coerce_wfg_config(
        {
            "running": True,
            "channels": [
                {
                    "channel": 0,
                    "carrier": {
                        "frequency": 321.0,
                        "amplitude": 0.25,
                        "offset": 0.01,
                        "function": "Square",
                        "symmetry": 40,
                        "phase": 10,
                    },
                    "trigger": {"source": "trigsrcPC", "secWait": 0.5, "repeatCount": 3},
                }
            ],
        }
    )
    assert wfg.running
    assert wfg.channels[0].carrier.frequency_hz == 321.0
    assert wfg.channels[0].carrier.function == WaveformFunction.SQUARE
    assert wfg.channels[0].trigger.source == TriggerSource.PC
    assert wfg.channels[0].trigger.sec_wait == 0.5
    assert wfg.channels[0].trigger.repeat_count == 3

    do_config = coerce_do_config(
        {
            "running": True,
            "channels": [
                {
                    "channel": 2,
                    "enable": True,
                    "clockDivider": 8,
                    "clockFrequencyHz": 25.0,
                    "outputType": "Custom",
                    "idleState": "High",
                    "highBits": 4,
                    "lowBits": 5,
                    "pattern": [1, 0, 1, 1],
                    "trigger": {"source": "trigsrcDigitalOut"},
                }
            ],
        }
    )
    channel = do_config.channels[0]
    assert do_config.running
    assert channel.channel_index == 2
    assert channel.enable
    assert channel.clock_divider == 8
    assert channel.clock_frequency_hz == 25.0
    assert channel.output_type == DigitalOutType.CUSTOM
    assert channel.idle_state == DigitalOutIdleState.HIGH
    assert channel.custom_data.count_of_bits == 4
    assert channel.custom_data.bits == [1, 0, 1, 1]
    assert channel.trigger.source == TriggerSource.DIGITAL_OUT


class FakeWaveFormsBackend:
    def __init__(self):
        self.calls = []

    def open_first_device(self):
        self.calls.append(("open_first_device",))
        return 777

    def close(self, handle):
        self.calls.append(("close", handle))

    def trigger_pc(self, handle):
        self.calls.append(("trigger_pc", handle))

    def configure_wfg(self, handle, config):
        self.calls.append(("configure_wfg", handle, config.running))

    def configure_do(self, handle, config):
        self.calls.append(("configure_do", handle, config.running, len(config.channels)))

    def reset_do(self, handle):
        self.calls.append(("reset_do", handle))

    def capture_analog_in_channels(
        self,
        handle,
        *,
        channel_indices,
        sample_frequency_hz,
        sample_count,
        range_v,
        offset_v,
        trigger_source,
    ):
        self.calls.append(
            (
                "capture_analog_in_channels",
                handle,
                tuple(channel_indices),
                sample_frequency_hz,
                sample_count,
                range_v,
                offset_v,
                trigger_source,
            )
        )
        return {index: [float(index), float(index) + 1.0] for index in channel_indices}


class FakeDwfFunction:
    def __init__(self, name, owner):
        self.name = name
        self.owner = owner
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.owner.calls.append((self.name, args))
        for arg in args:
            if hasattr(arg, "raw") and self.name == "FDwfGetLastErrorMsg":
                arg.value = b"ok"
                continue
            if hasattr(arg, "raw") and self.name.endswith("Name"):
                arg.value = b"Analog Discovery"
                continue
            if hasattr(arg, "raw") and self.name.endswith("SN"):
                arg.value = b"SN123"
                continue
            target = getattr(arg, "_obj", None)
            if target is None and hasattr(arg, "value") and not isinstance(arg.value, int):
                target = arg
            if target is not None and hasattr(target, "value"):
                if self.name.endswith("Name"):
                    target.value = b"Analog Discovery"
                elif self.name.endswith("SN"):
                    target.value = b"SN123"
                elif self.name.endswith("Info"):
                    target.value = 100
                elif self.name.endswith("IsOpened"):
                    target.value = 1
                elif self.name == "FDwfEnum":
                    target.value = 2
                elif self.name == "FDwfAnalogInStatus":
                    target.value = 2
                elif self.name == "FDwfDeviceOpen":
                    target.value = 123
                elif self.name.endswith("Get"):
                    target.value = 1
                elif self.name == "FDwfDigitalOutCount":
                    target.value = 16
        return 1


class FakeDwf:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        func = FakeDwfFunction(name, self)
        setattr(self, name, func)
        return func


def test_waveforms_low_level_wrappers():
    fake = FakeDwf()
    backend = WaveFormsBackend(dwf=fake)

    assert backend.open_first_device() == 123
    assert backend.open_device(0) == 123
    assert backend.get_last_error_message() == "ok"
    backend.set_auto_configure(123, False)
    backend.reset_device(123)
    backend.trigger_pc(123)
    assert backend.enum_devices() == 2
    assert backend.enum_device_is_opened(0)
    assert backend.enum_device_name(0) == "Analog Discovery"
    assert backend.enum_device_serial_number(0) == "SN123"

    backend.analog_out_node_enable_set(123, 0, 0, True)
    assert backend.analog_out_node_enable_get(123, 0, 0)
    backend.analog_out_node_frequency_set(123, 0, 0, 1000.0)
    assert backend.analog_out_node_frequency_get(123, 0, 0) == 1
    assert backend.analog_out_node_frequency_info(123, 0, 0) == (100.0, 100.0)
    backend.analog_out_run_set(123, 0, 0.5)
    assert backend.analog_out_run_get(123, 0) == 1
    backend.analog_out_trigger_source_set(123, 0, TriggerSource.PC)
    assert backend.analog_out_trigger_source_get(123, 0) == 1
    backend.analog_out_configure(123, 0, True)

    backend.digital_out_enable_set(123, 0, True)
    backend.digital_out_divider_set(123, 0, 4)
    assert backend.digital_out_divider_info(123, 0) == (100, 100)
    backend.digital_out_counter_init_set(123, 0, True, 0)
    backend.digital_out_counter_set(123, 0, 2, 3)
    backend.digital_out_type_set(123, 0, DigitalOutType.PULSE)
    backend.digital_out_idle_set(123, 0, DigitalOutIdleState.LOW)
    backend.digital_out_data_set(123, 0, [1, 0, 1])
    assert backend.digital_out_data_info(123, 0) == 100
    backend.digital_out_wait_set(123, 0.1)
    backend.digital_out_run_set(123, 0.2)
    backend.digital_out_repeat_set(123, 3)
    backend.digital_out_repeat_trigger_set(123, True)
    backend.digital_out_trigger_source_set(123, TriggerSource.PC)
    backend.digital_out_configure(123, True)
    backend.configure_do(
        123,
        DoConfig(
            running=True,
            channels=[
                DoSingleChannelConfig(
                    channel_index=1,
                    enable=True,
                    clock_frequency_hz=10.0,
                    counter_high_bits=1,
                    counter_low_bits=1,
                    trigger=TriggerSettings(sec_run=0.2, sec_wait=0.1),
                )
            ],
        ),
    )
    backend.analog_in_trigger_source_set(123, TriggerSource.ANALOG_IN)
    captures = backend.capture_analog_in_channels(
        123,
        channel_indices=[0, 1],
        sample_frequency_hz=1000,
        sample_count=4,
        range_v=2.0,
        offset_v=0.0,
        trigger_source=TriggerSource.PC,
    )
    assert set(captures) == {0, 1}
    assert backend.digital_out_count(123) == 16
    assert backend.digital_out_internal_clock_info(123) == 100.0
    backend.reset_do(123)
    backend.close(123)
    backend.close_all()

    called = {name for name, _args in fake.calls}
    assert "FDwfAnalogOutNodeEnableSet" in called
    assert "FDwfDigitalOutConfigure" in called
    divider_calls = [args for name, args in fake.calls if name == "FDwfDigitalOutDividerSet"]
    assert any(args[1].value == 1 and args[2].value == 5 for args in divider_calls)
    assert "FDwfDigitalOutRunSet" in called
    assert "FDwfDigitalOutWaitSet" in called


def test_experiment2_writes_labview_metadata_tdms(tmp_path, monkeypatch):
    writes = install_fake_nptdms(monkeypatch)

    experiment = Experiment2(
        repeat_id=2,
        experiment_folder=tmp_path / "repeat_003",
        flush_settings=FlushSettings(flush_flowrate=-5000.0, flush_volume_ml=0.2, wait_after_flush_s=1.5),
        global_exposure_ms=40.0,
        trigger_global_exposure=True,
        wfg_config=WfgConfig(
            running=True,
            channels=[
                WfgChannelConfig(
                    0,
                    carrier=CarrierSettings(frequency_hz=1_975_000.0, amplitude_v=2.0),
                    trigger=TriggerSettings(sec_run=0.5, sec_wait=0.1, repeat_count=1),
                ),
                WfgChannelConfig(
                    1,
                    carrier=CarrierSettings(frequency_hz=1000.0, amplitude_v=1.0),
                    trigger=TriggerSettings(sec_run=0.25, sec_wait=0.2, repeat_count=0),
                ),
            ],
        ),
        do_clock_settings=DoConfig(
            running=True,
            channels=[
                DoSingleChannelConfig(
                    channel_index=1,
                    enable=True,
                    clock_frequency_hz=100.0,
                    trigger=TriggerSettings(sec_run=0.2, sec_wait=0.05),
                )
            ],
        ),
    )

    experiment.create_folder_and_tdms()
    experiment.save_settings()
    experiment.save_image_data(["frame-a", "frame-b"])
    experiment.save_camera_settings(
        {
            "readout_time": 0.012,
            "sub_region": {
                "horizontal_size": 2304,
                "vertical_size": 740,
                "horizontal_offset": 0,
                "vertical_offset": 792,
            },
        }
    )

    tdms_path = tmp_path / "repeat_003" / "data.tdms"
    assert tdms_path.exists()
    objects = writes[str(tdms_path)]
    experiment_group = next(item for item in objects if getattr(item, "kind", "") == "group" and item.name == "Experiment")
    properties = experiment_group.properties
    for field in (
        "WFGFreqCh1",
        "WFGAmpCh1",
        "WFGRunCh1",
        "WFGWaitCh1",
        "RepeatCh1",
        "WFGFreqCh2",
        "WFGAmpCh2",
        "WFGRunCh2",
        "WFGWaitCh2",
        "RepeatCh2",
        "DORun",
        "DOWait",
        "DOFreq",
        "ExposureTime",
        "GlobalExposure",
        "Repeat ID",
        "Experiment started",
        "FlushFlowrate",
        "FlushVolume",
        "WaitAfterFlush",
        "ReadoutTime",
        "HorizontalSize",
        "VerticalSize",
        "HorizontalOffset",
        "VerticalOffset",
    ):
        assert field in properties
    assert properties["DOFreq"] == 100.0
    channels = {item.name: item for item in objects if getattr(item, "kind", "") == "channel"}
    assert channels["ImageName"].data == ["frame_00000.tiff", "frame_00001.tiff"]
    assert len(channels["Timestamp"].data) == 2


def test_ad2_real_class_dispatches_to_waveforms_backend():
    backend = FakeWaveFormsBackend()
    ad2 = AD2Sdk(backend=backend)

    ad2.initialize()
    ad2.config_wfg(WfgConfig(running=True))
    ad2.pc_trigger()
    ad2.do_configure(DoConfig(channels=[DoSingleChannelConfig(channel_index=0, enable=True)]))
    ad2.start_stop_do(True)
    captures = ad2.capture_scope_channels(
        channel_indices=[0, 1],
        sample_frequency_hz=1000.0,
        sample_count=2,
        range_v=1.0,
        offset_v=0.0,
        trigger_source=TriggerSource.PC,
    )
    ad2.do_reset()
    ad2.cleanup()

    assert captures == {0: [0.0, 1.0], 1: [1.0, 2.0]}
    assert backend.calls == [
        ("open_first_device",),
        ("configure_wfg", 777, True),
        ("trigger_pc", 777),
        ("configure_do", 777, False, 1),
        ("configure_do", 777, True, 1),
        ("capture_analog_in_channels", 777, (0, 1), 1000.0, 2, 1.0, 0.0, TriggerSource.PC),
        ("reset_do", 777),
        ("close", 777),
    ]


class FakeDcamApi:
    initialized = False

    @classmethod
    def init(cls):
        cls.initialized = True
        return True

    @classmethod
    def uninit(cls):
        cls.initialized = False
        return True

    @classmethod
    def lasterr(cls):
        return "ok"


class FakeDcamModule:
    Dcamapi = FakeDcamApi

    class DCAM_IDPROP:
        EXPOSURETIME = "EXPOSURETIME"
        SUBARRAYMODE = "SUBARRAYMODE"
        SUBARRAYHSIZE = "SUBARRAYHSIZE"
        SUBARRAYVSIZE = "SUBARRAYVSIZE"
        SUBARRAYHPOS = "SUBARRAYHPOS"
        SUBARRAYVPOS = "SUBARRAYVPOS"
        TRIGGERSOURCE = "TRIGGERSOURCE"
        IMAGE_WIDTH = "IMAGE_WIDTH"
        IMAGE_HEIGHT = "IMAGE_HEIGHT"
        TIMING_READOUTTIME = "TIMING_READOUTTIME"

    class DCAMPROP:
        class MODE:
            OFF = 1
            ON = 2

        class TRIGGERSOURCE:
            INTERNAL = 1
            EXTERNAL = 2
            SOFTWARE = 3

    class Dcam:
        def __init__(self, index):
            self.index = index
            self.opened = False
            self.calls = []
            self.values = {
                "IMAGE_WIDTH": 2304,
                "IMAGE_HEIGHT": 500,
                "SUBARRAYHPOS": 0,
                "SUBARRAYVPOS": 0,
                "SUBARRAYHSIZE": 2304,
                "SUBARRAYVSIZE": 500,
                "TIMING_READOUTTIME": 0.001,
            }

        def is_opened(self):
            return self.opened

        def dev_open(self):
            self.opened = True
            self.calls.append(("dev_open",))
            return True

        def dev_close(self):
            self.opened = False
            self.calls.append(("dev_close",))
            return True

        def lasterr(self):
            return "ok"

        def prop_setvalue(self, prop, value):
            self.values[prop] = value
            self.calls.append(("prop_setvalue", prop, value))
            return True

        def prop_setgetvalue(self, prop, value, option=0):
            _ = option
            self.values[prop] = value
            self.calls.append(("prop_setgetvalue", prop, value))
            return value

        def prop_getvalue(self, prop):
            return self.values.get(prop, 0)

        def prop_getattr(self, prop):
            _ = prop

            class Attr:
                valuemin = 0
                valuemax = 4096
                valuestep = 4

            return Attr()

        def buf_alloc(self, frames):
            self.calls.append(("buf_alloc", frames))
            return True

        def buf_release(self):
            self.calls.append(("buf_release",))
            return True

        def cap_snapshot(self):
            self.calls.append(("cap_snapshot",))
            return True

        def cap_start(self, sequence=True):
            self.calls.append(("cap_start", sequence))
            return True

        def cap_stop(self):
            self.calls.append(("cap_stop",))
            return True

        def wait_capevent_frameready(self, timeout):
            self.calls.append(("wait", timeout))
            return True

        def buf_getlastframedata(self):
            import numpy as np

            return np.arange(12, dtype="uint16").reshape(3, 4)

        def dev_getcapability(self):
            return False

        def cap_firetrigger(self):
            self.calls.append(("cap_firetrigger",))
            return True


def test_hamamatsu_dcam_backend_uses_sdk_wrapper(tmp_path):
    from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend

    backend = HamamatsuDcamBackend()
    backend.dcam_module = FakeDcamModule
    backend.dcamapi = FakeDcamApi

    handle = backend.open_camera()
    backend.configure_exposure_time(50)
    backend.configure_roi(SubRegion(4, 8, 100, 120))
    frame = backend.capture_snapshot()
    backend.configure_sequence({"frames": 2, "trigger_source": "software"})
    sequence = backend.image_sequence(2)
    backend.save_sequence(sequence, tmp_path)
    backend.sw_trigger()
    backend.close()

    assert handle.index == 0
    assert frame.shape == (3, 4)
    assert len(sequence) == 2
    tiff_path = tmp_path / "frame_00000.tiff"
    assert tiff_path.exists()
    from PIL import Image

    with Image.open(tiff_path) as saved:
        assert saved.format == "TIFF"
        assert saved.size == (4, 3)
    assert ("prop_setgetvalue", "EXPOSURETIME", 0.05) in handle.calls
    assert ("cap_firetrigger",) in handle.calls
    assert not handle.opened
