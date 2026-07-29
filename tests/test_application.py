from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from thermo_acoustic.application import Application
from thermo_acoustic.ad2 import (
    CarrierSettings,
    DigitalOutIdleState,
    DigitalOutType,
    DoConfig,
    DoSingleChannelConfig,
    FmSweepSettings,
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
from thermo_acoustic.qmix_backend import (
    MAX_SYRINGE_INNER_DIAMETER_MM,
    MAX_SYRINGE_STROKE_MM,
    MIN_SYRINGE_INNER_DIAMETER_MM,
    MIN_SYRINGE_STROKE_MM,
    QmixPumpBackend,
    QmixPumpError,
    SYRINGE_PRESETS,
)
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
            # Padded well above _MIN_TDMS_FILE_SIZE_BYTES so the write-verification
            # size check doesn't spuriously fail against this stand-in file.
            self.path.write_bytes(b"fake tdms" + b"\x00" * 512)
            writes[str(self.path)] = objects

    class FakeTdmsChannel:
        def __init__(self, channel_object):
            self._data = list(channel_object.data)

        def __len__(self):
            return len(self._data)

        def __iter__(self):
            return iter(self._data)

    class FakeTdmsGroup:
        def __init__(self, properties):
            self.properties = dict(properties)
            self._channels: dict[str, FakeTdmsChannel] = {}

        def __getitem__(self, name):
            return self._channels[name]

    class FakeTdmsFile:
        def __init__(self, objects):
            self._groups: dict[str, FakeTdmsGroup] = {}
            for item in objects:
                if getattr(item, "kind", "") == "group":
                    self._groups[item.name] = FakeTdmsGroup(item.properties)
            for item in objects:
                if getattr(item, "kind", "") == "channel":
                    group = self._groups.setdefault(item.group, FakeTdmsGroup({}))
                    group._channels[item.name] = FakeTdmsChannel(item)

        def __getitem__(self, name):
            return self._groups[name]

    class FakeTdmsFileReader:
        @staticmethod
        def read(path):
            objects = writes.get(str(path))
            if objects is None:
                raise FileNotFoundError(f"No fake TDMS data recorded for {path}")
            return FakeTdmsFile(objects)

    monkeypatch.setitem(
        sys.modules,
        "nptdms",
        SimpleNamespace(
            ChannelObject=FakeChannelObject,
            GroupObject=FakeGroupObject,
            RootObject=FakeRootObject,
            TdmsWriter=FakeTdmsWriter,
            TdmsFile=FakeTdmsFileReader,
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


def test_fm_sweep_settings_match_martens_et_al_reference_case():
    # Martens et al., PhysRevApplied.23.024043: "actuation frequency centered
    # at 1.934 MHz with a sweep of 50 kHz and a sweep time of 1 ms."
    sweep = FmSweepSettings(center_hz=1_934_000.0, width_hz=50_000.0, sweep_time_ms=1.0)

    assert sweep.fm_amplitude_pct == pytest.approx(2.585, abs=1e-3)
    assert sweep.fm_frequency_hz == 1000.0
    assert sweep.top_hz == pytest.approx(1_959_000.0)
    assert sweep.bottom_hz == pytest.approx(1_909_000.0)

    fm_mod = sweep.fm_mod_settings()
    assert fm_mod.frequency_hz == 1000.0
    assert fm_mod.amplitude_v == pytest.approx(2.585, abs=1e-3)
    assert fm_mod.function == WaveformFunction.TRIANGLE
    assert fm_mod.enable is True


def test_fm_sweep_settings_rejects_non_positive_sweep_time():
    try:
        FmSweepSettings(center_hz=1_934_000.0, width_hz=50_000.0, sweep_time_ms=0.0)
    except ValueError as exc:
        assert "Sweep Time" in str(exc)
    else:
        raise AssertionError("expected a clear ValueError, not a silent division by zero")

    try:
        FmSweepSettings(center_hz=1_934_000.0, width_hz=50_000.0, sweep_time_ms=-1.0)
    except ValueError as exc:
        assert "Sweep Time" in str(exc)
    else:
        raise AssertionError("expected a clear ValueError for negative sweep time too")


def test_flush_sets_valve_and_status():
    app = Application()
    app.pump.fill_level = 60.0

    ok = app.flush(FlushSettings(flush_flowrate=10.0, flush_volume_ml=6.0, wait_after_flush_s=0.0))

    assert ok
    assert app.valve.position == 2
    assert app.pump.fill_level == 54.0
    assert app.status == "FlushComplete"


def test_flush_rejects_volume_exceeding_current_fill_level():
    # Regression test found by an end-to-end simulated dry-run verification
    # pass (not a unit test written against a hand-primed happy-path state):
    # every existing flush test pre-sets pump.fill_level to a comfortably
    # large value before calling flush() -- CetoniPump.fill_level's own
    # dataclass default is 0.0, and the automated path never calls
    # refill()/reference_move() (confirmed manual-only, Session 21), so a
    # real operator who starts a series before refilling would previously
    # get a silent negative fill_level with no error at all. Deliberately
    # starts from the *default* fill_level (0.0), not a pre-set one, to
    # exercise exactly the state a fresh Application actually starts in.
    app = Application()
    assert app.pump.fill_level == 0.0, "sanity check: this test must start from the real default, not a pre-set value"

    with pytest.raises(ValueError, match="exceeds the syringe's current fill level"):
        app.flush(FlushSettings(flush_flowrate=200.0, flush_volume_ml=0.05, wait_after_flush_s=0.0))

    assert app.pump.fill_level == 0.0, "fill_level must be unchanged -- rejected before any pump/valve call, not after"
    assert app.valve.position == 1, "must not even move the valve once the volume is rejected"
    assert app.status != "FlushComplete"


def test_flush_accepts_volume_exactly_at_current_fill_level():
    # Inclusive boundary, matching this project's established convention
    # (e.g. the syringe-geometry bounds in qmix_backend.py) -- flushing
    # exactly what's currently loaded (down to 0.0 remaining) is physically
    # valid and must not be rejected.
    app = Application()
    app.pump.fill_level = 0.05

    ok = app.flush(FlushSettings(flush_flowrate=200.0, flush_volume_ml=0.05, wait_after_flush_s=0.0))

    assert ok
    assert app.pump.fill_level == pytest.approx(0.0)


def test_flush_settings_timeout_converts_ul_per_minute_to_seconds():
    # Real-hardware regression: this exact combination (0.05 ml / 200 uL/min)
    # was declared a flush failure after ~5.25s on a real Qmix pump that was
    # still genuinely mid-move -- the real move needs ~15s at that flow rate
    # ((0.05 ml -> 50 uL) / 200 uL/min = 0.25 min = 15 s). The formula was
    # missing the minutes-to-seconds x60 conversion.
    settings = FlushSettings(flush_flowrate=200.0, flush_volume_ml=0.05, wait_after_flush_s=0.0)

    assert settings.timeout_s == pytest.approx(20.0)
    real_move_duration_s = (settings.flush_volume_ml * 1000.0 / settings.flush_flowrate) * 60.0
    assert settings.timeout_s > real_move_duration_s, "computed timeout must exceed the real move duration"


def test_flush_settings_timeout_is_zero_for_nonpositive_flowrate():
    assert FlushSettings(flush_flowrate=0.0, flush_volume_ml=1.0, wait_after_flush_s=0.0).timeout_s == 0.0
    assert FlushSettings(flush_flowrate=-1.0, flush_volume_ml=1.0, wait_after_flush_s=0.0).timeout_s == 0.0


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


def test_run_experiment2_records_real_wfg_clamping_in_final_tdms(tmp_path, monkeypatch):
    # Finding A regression test: drives the REAL run_experiment2() call
    # order end-to-end (not configure_wfg()/save_settings() in isolation --
    # those were already independently tested and both passed while this
    # bug shipped, because save_settings() ran before config_wfg() had a
    # chance to set out_of_range). Uses a real AD2Sdk + WaveFormsBackend
    # against a fake dwf that reports a narrow device amplitude range, so
    # the requested 10.0V carrier amplitude genuinely gets clamped by the
    # same code path a real device would clamp it through.
    writes = install_fake_nptdms(monkeypatch)
    fake_dwf = FakeAD2ConfigureDwf(frequency_range=(10.0, 1_000_000.0), amplitude_range=(-5.0, 5.0))
    ad2 = AD2Sdk(backend=WaveFormsBackend(dwf=fake_dwf), device_handle=123)
    app = Application(ad2=ad2)
    app.pump.fill_level = 1.0
    channel = WfgChannelConfig(0, carrier=CarrierSettings(frequency_hz=1000.0, amplitude_v=10.0))
    experiment = Experiment2(
        experiment_folder=tmp_path / "experiment-clamped",
        wfg_config=WfgConfig(channels=[channel]),
    )
    app.experiment_series.enqueue_experiments([experiment])

    ok = app.run_experiment2()

    assert ok
    assert channel.out_of_range is True, "sanity check: the fake device range must actually force a clamp"
    tdms_path = tmp_path / "experiment-clamped" / "data.tdms"
    objects = writes[str(tdms_path)]
    experiment_group = next(item for item in objects if getattr(item, "kind", "") == "group" and item.name == "Experiment")
    assert experiment_group.properties["WFGOutOfRangeCh1"] is True, (
        "the FINAL data.tdms written for this repeat must reflect the real clamping that just "
        "happened during config_wfg() -- not the pre-configure default captured by the first, "
        "early save_settings() call"
    )


def test_run_experiment2_records_simulated_vs_real_instruments_in_final_tdms(tmp_path, monkeypatch):
    # Finding B regression test: without this fix, data.tdms carried no
    # SimAD2/SimCamera/SimPump/SimValve fields at all -- a simulated dry-run
    # and a real experiment were structurally indistinguishable after the
    # fact. Uses a genuinely mixed configuration (AD2 the real, non-simulated
    # class -- just disabled, so no hardware is actually touched -- against
    # every other instrument left at its default simulate=True) so a bug
    # that collapsed all four flags to the same hardcoded value, or read the
    # wrong instrument for one of them, would be caught, not just "the key
    # exists".
    writes = install_fake_nptdms(monkeypatch)
    app = Application(ad2=AD2Sdk(enabled=False))
    experiment = Experiment2(experiment_folder=tmp_path / "experiment-sim-flags")
    app.experiment_series.enqueue_experiments([experiment])

    ok = app.run_experiment2()

    assert ok
    tdms_path = tmp_path / "experiment-sim-flags" / "data.tdms"
    objects = writes[str(tdms_path)]
    experiment_group = next(item for item in objects if getattr(item, "kind", "") == "group" and item.name == "Experiment")
    properties = experiment_group.properties
    assert properties["SimAD2"] is False, "AD2Sdk (not SimulatedAD2Sdk) was used -- must not be reported as simulated"
    assert properties["SimCamera"] is True
    assert properties["SimPump"] is True
    assert properties["SimValve"] is True


def test_run_experiment2_records_flush_failure_in_final_tdms(tmp_path, monkeypatch):
    # Finding D regression test, failure path: before this fix, a failed
    # flush surfaced loudly at the process level (status event, log,
    # Application.errors -- Session 7) but the repeat's own data.tdms carried
    # no record of it at all. Inspecting data.tdms in isolation (without
    # cross-referencing the live app log, which isn't persisted
    # per-experiment) gave no way to tell the flush ever failed for that
    # specific repeat.
    writes = install_fake_nptdms(monkeypatch)
    app = Application(ad2=SimulatedAD2Sdk())
    monkeypatch.setattr(Application, "flush", lambda self, settings: False)
    experiment = Experiment2(
        experiment_folder=tmp_path / "experiment-flush-failed",
        flush_enabled=True,
        flush_settings=FlushSettings(flush_flowrate=10.0, flush_volume_ml=6.0, wait_after_flush_s=0.0),
    )
    app.experiment_series.enqueue_experiments([experiment])

    ok = app.run_experiment2()

    assert ok is False
    assert app.status == "ExperimentFlushFailed"
    tdms_path = tmp_path / "experiment-flush-failed" / "data.tdms"
    objects = writes[str(tdms_path)]
    experiment_group = next(item for item in objects if getattr(item, "kind", "") == "group" and item.name == "Experiment")
    assert experiment_group.properties["FlushCompleted"] is False, (
        "the failed flush must be recorded in this repeat's own data.tdms, not just surfaced "
        "transiently via status/logging"
    )


def test_run_experiment2_records_flush_success_in_final_tdms(tmp_path, monkeypatch):
    # Finding D regression test, success path (the counterpart to the
    # failure test above -- confirms the field isn't hardcoded False/absent,
    # and that a genuinely successful flush is distinguishable from one that
    # never ran at all).
    writes = install_fake_nptdms(monkeypatch)
    app = Application(ad2=SimulatedAD2Sdk())
    app.pump.fill_level = 60.0  # comfortably >= flush_volume_ml, so the flush itself succeeds
    experiment = Experiment2(
        experiment_folder=tmp_path / "experiment-flush-ok",
        flush_enabled=True,
        flush_settings=FlushSettings(flush_flowrate=10.0, flush_volume_ml=6.0, wait_after_flush_s=0.0),
    )
    app.experiment_series.enqueue_experiments([experiment])

    ok = app.run_experiment2()

    assert ok is True
    tdms_path = tmp_path / "experiment-flush-ok" / "data.tdms"
    objects = writes[str(tdms_path)]
    experiment_group = next(item for item in objects if getattr(item, "kind", "") == "group" and item.name == "Experiment")
    assert experiment_group.properties["FlushCompleted"] is True


def test_experiment2_flush_completed_defaults_to_empty_string_when_flush_never_runs(tmp_path, monkeypatch):
    writes = install_fake_nptdms(monkeypatch)
    experiment = Experiment2(experiment_folder=tmp_path / "no-flush")

    experiment.create_folder_and_tdms()
    experiment.save_settings()

    tdms_path = tmp_path / "no-flush" / "data.tdms"
    properties = next(
        item for item in writes[str(tdms_path)] if getattr(item, "kind", "") == "group" and item.name == "Experiment"
    ).properties
    assert properties["FlushCompleted"] == ""


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
        ("write", "OPEN COM5"),  # Valve.visa_resource's real-hardware-confirmed default
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


def test_valve_initialize_accepts_explicit_valid_status_response():
    valve_backend = FakeTextBackend({"S": "2\r"})
    valve = Valve(backend=valve_backend, visa_resource="COM6")

    valve.initialize()

    assert valve.initialized
    assert valve.position == 2
    assert valve.status_note == "confirmed"


def test_valve_initialize_accepts_busy_status_response_as_busy():
    valve_backend = FakeTextBackend({"S": "*\r"})
    valve = Valve(backend=valve_backend, visa_resource="COM6")

    valve.initialize()

    assert valve.initialized
    assert valve.status_note == "busy"


def test_valve_initialize_rejects_unparseable_status_response():
    valve_backend = FakeTextBackend({"S": "??\r"})
    valve = Valve(backend=valve_backend)

    try:
        valve.initialize()
    except Exception as exc:
        assert "unrecognized status" in str(exc)
        assert "unverified position response" in str(exc)
    else:
        raise AssertionError("expected initialize() to reject an unrecognized valve response")

    assert not valve.initialized
    assert "unverified" in valve.status_note


def test_valve_wait_until_ready_polls_until_confirmed_and_is_bounded_when_busy():
    ready_valve = Valve(backend=FakeTextBackend({"S": "1\r"}))
    assert ready_valve.wait_until_ready(timeout_s=1.0, poll_interval_s=0.01) is True

    busy_valve = Valve(backend=FakeTextBackend({"S": "*\r"}))
    started_at = time.monotonic()
    result = busy_valve.wait_until_ready(timeout_s=0.2, poll_interval_s=0.02)
    elapsed_s = time.monotonic() - started_at

    assert result is False
    assert elapsed_s < 0.5, "a persistently busy valve must not hang past roughly its timeout"

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


def test_prior_zmotor_read_position_logs_and_keeps_last_known_on_unparseable_response(caplog):
    # Finding G regression test: a garbled/partial serial response was
    # previously indistinguishable from "position unchanged" -- the
    # ValueError from float() was silently swallowed with a bare `pass`,
    # with no way for anyone to know the read actually failed. Confirms
    # both halves: the stale value really is what's returned (existing,
    # correct fallback behavior, unchanged), AND the failure is now logged
    # (the actual gap this finding closes).
    motor = PriorZMotor(backend=FakeTextBackend({"P": "not-a-number"}), visa_resource="COM9")
    motor.position = 3.5  # simulates a real prior successful read

    with caplog.at_level("ERROR", logger="thermo_acoustic.instruments"):
        result = motor.read_position()

    assert result == 3.5, "must still return the last-known position, not crash or silently reset to 0"
    assert any(
        "could not parse position" in record.message and "not-a-number" in record.message and "COM9" in record.message
        for record in caplog.records
    ), caplog.records


def test_serial_text_backend_has_longer_bounded_write_timeout():
    from thermo_acoustic.instruments import SerialTextCommandBackend

    backend = SerialTextCommandBackend()

    assert backend.timeout_s == 1.0
    assert backend.write_timeout_s == 5.0


class FakePumpBackend:
    def __init__(self, fill_level=0.0):
        self.calls = []
        self.status = False
        self.fill_level = fill_level

    def initialize(self, configuration_path):
        self.calls.append(("initialize", configuration_path))

    def read_fill_level(self):
        self.calls.append(("read_fill_level",))
        return self.fill_level

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
        ("read_fill_level",),
        ("configure_syringe", {"diameter_mm": 10}),
        ("configure_flow_unit", "ul/min"),
        ("refill",),
        ("read_fill_level",),
        ("set_fill_level", 0.5),
        ("generate_flow", 2.5),
        ("read_status",),
        ("reference_move",),
        ("empty",),
        ("stop",),
        ("close",),
    ]


def test_cetoni_pump_initialize_syncs_fill_level_from_real_backend():
    # Regression guard for the real-hardware dry-run finding (Session 54):
    # fill_level previously stayed at CetoniPump's own Python-side dataclass
    # default (0.0) after initialize(), regardless of what the real syringe
    # actually held -- a fresh process disagreed with reality until this
    # sync. 0.73 (not 0.0, not any prior default) so this can't pass by
    # coincidence.
    backend = FakePumpBackend(fill_level=0.73)
    pump = CetoniPump(simulate=False, backend=backend)
    assert pump.fill_level == 0.0

    pump.initialize()

    assert pump.fill_level == pytest.approx(0.73)


def test_cetoni_pump_initialize_without_backend_leaves_fill_level_untouched():
    pump = CetoniPump(simulate=True, backend=None)
    pump.initialize()
    assert pump.fill_level == 0.0


def test_cetoni_pump_refill_syncs_fill_level_from_real_backend_not_hardcoded_1ml():
    # Code-health audit finding 5a: refill() used to hardcode
    # self.fill_level = 1.0 regardless of the real syringe's true
    # capacity. A BD 5ml syringe (real inner diameter 12.07 mm) refilled
    # to its real 5.0 ml capacity on the actual device, but the old code
    # would have left pump.fill_level reading 1.0 -- wrong for every
    # syringe except a coincidental 1 mL one. 5.0 (not 1.0, not 0.0) so
    # this can't pass by coincidence with the old hardcoded default.
    backend = FakePumpBackend(fill_level=5.0)
    pump = CetoniPump(simulate=False, backend=backend)
    pump.configure_syringe({"name": "BD 5ml", "inner_diameter_mm": 12.07, "max_piston_stroke_mm": 43.75})

    pump.refill()

    assert pump.fill_level == pytest.approx(5.0)


def test_cetoni_pump_refill_without_backend_uses_configured_max_volume():
    pump = CetoniPump(simulate=True, backend=None, max_volume_ml=5.0)
    pump.refill()
    assert pump.fill_level == pytest.approx(5.0)


def test_cetoni_pump_refill_without_backend_defaults_to_1ml_when_unconfigured():
    # Backward-compatible default for existing simulated-mode callers that
    # never set max_volume_ml -- unchanged from the old hardcoded behavior.
    pump = CetoniPump(simulate=True, backend=None)
    pump.refill()
    assert pump.fill_level == 1.0


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
            self.fill_level = 0.0
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

        def get_fill_level(self):
            self.calls.append(("get_fill_level",))
            return self.fill_level

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


def test_syringe_presets_match_authoritative_bd_inner_diameters():
    # Confirmed real BD syringe inner diameters (mm): 1mL=4.78, 5mL=12.07, 10mL=14.5.
    # These feed set_syringe_param() on the real Qmix SDK pump object directly
    # (qmixsdk/qmixpump.py:149-158, LCP_SetSyringeParam) -- there is no
    # internal model database on the SDK side, so a wrong diameter here
    # silently miscalibrates flow-rate/volume conversion on real hardware.
    expected_diameters_mm = {
        "BD 1ml": 4.78,
        "BD 5ml": 12.07,
        "BD 10ml": 14.5,
    }
    expected_volumes_ml = {
        "BD 1ml": 1.0,
        "BD 5ml": 5.0,
        "BD 10ml": 10.0,
    }
    for name, expected_diameter_mm in expected_diameters_mm.items():
        diameter_mm, stroke_mm = SYRINGE_PRESETS[name]
        assert diameter_mm == pytest.approx(expected_diameter_mm)

        # Stroke length is not an independently-sourced BD spec value; it is
        # derived assuming the nominal volume fills the full piston travel
        # in a cylindrical bore. Re-derive independently here (not via the
        # module's own helper) to confirm the preset is internally consistent.
        area_mm2 = 3.141592653589793 * (diameter_mm / 2.0) ** 2
        expected_stroke_mm = expected_volumes_ml[name] * 1000.0 / area_mm2
        assert stroke_mm == pytest.approx(expected_stroke_mm)


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
    assert ("set_fill_level", 0.5, 5000.0) in pump.calls
    assert ("calibrate",) in pump.calls
    assert ("set_fill_level", 0.0, 5000.0) in pump.calls
    assert ("set_fill_level", 10.0, 5000.0) in pump.calls


def test_qmix_pump_backend_reads_real_fill_level_from_sdk(tmp_path):
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(qmixbus=FakeQmixBusModule, qmixpump=FakeQmixPumpModule)
    backend.initialize(tmp_path / "qmix-config")

    pump = FakeQmixPumpModule.Pump.instances[0]
    # Simulates a real syringe that still has partial volume loaded from a
    # prior session -- not 0.0, so this test can't pass by coincidence.
    pump.fill_level = 0.73

    assert backend.read_fill_level() == pytest.approx(0.73)
    assert ("get_fill_level",) in pump.calls


def test_qmix_set_fill_level_treats_value_as_absolute_ml_not_fraction(tmp_path):
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(
        qmixbus=FakeQmixBusModule,
        qmixpump=FakeQmixPumpModule,
        pump_name="Pump B",
    )
    backend.initialize(tmp_path / "qmix-config")
    backend.configure_syringe({"name": "BD 5ml"})

    backend.set_fill_level(0.5, flow_rate=1000.0)

    pump = FakeQmixPumpModule.Pump.instances[0]
    assert ("set_fill_level", 0.5, 1000.0) in pump.calls, (
        "0.5 mL must be sent as-is, not scaled by syringe capacity as if it were a 50% fraction"
    )


# -- Custom syringe geometry bounds (Session 51): no live device readback
# exists for inner_diameter_mm/max_piston_stroke_mm (unlike max_flow_rate_ul_min/
# max_volume_ml, read back from the pump right after set_syringe_param()
# succeeds), so configure_syringe() rejects implausible values itself before
# ever calling into the SDK -- these tests confirm that rejection, not just
# document it.

def test_configure_syringe_rejects_inner_diameter_below_minimum(tmp_path):
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(qmixbus=FakeQmixBusModule, qmixpump=FakeQmixPumpModule)
    backend.initialize(tmp_path / "qmix-config")

    with pytest.raises(QmixPumpError, match="inner_diameter_mm"):
        backend.configure_syringe(
            {"inner_diameter_mm": MIN_SYRINGE_INNER_DIAMETER_MM - 0.1, "max_piston_stroke_mm": 55.0}
        )

    pump = FakeQmixPumpModule.Pump.instances[0]
    assert not any(call[0] == "set_syringe_param" for call in pump.calls)


def test_configure_syringe_rejects_inner_diameter_above_maximum(tmp_path):
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(qmixbus=FakeQmixBusModule, qmixpump=FakeQmixPumpModule)
    backend.initialize(tmp_path / "qmix-config")

    with pytest.raises(QmixPumpError, match="inner_diameter_mm"):
        backend.configure_syringe(
            {"inner_diameter_mm": MAX_SYRINGE_INNER_DIAMETER_MM + 0.1, "max_piston_stroke_mm": 55.0}
        )

    pump = FakeQmixPumpModule.Pump.instances[0]
    assert not any(call[0] == "set_syringe_param" for call in pump.calls)


def test_configure_syringe_rejects_stroke_below_minimum(tmp_path):
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(qmixbus=FakeQmixBusModule, qmixpump=FakeQmixPumpModule)
    backend.initialize(tmp_path / "qmix-config")

    with pytest.raises(QmixPumpError, match="max_piston_stroke_mm"):
        backend.configure_syringe(
            {"inner_diameter_mm": 10.0, "max_piston_stroke_mm": MIN_SYRINGE_STROKE_MM - 0.1}
        )

    pump = FakeQmixPumpModule.Pump.instances[0]
    assert not any(call[0] == "set_syringe_param" for call in pump.calls)


def test_configure_syringe_rejects_stroke_above_maximum(tmp_path):
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(qmixbus=FakeQmixBusModule, qmixpump=FakeQmixPumpModule)
    backend.initialize(tmp_path / "qmix-config")

    with pytest.raises(QmixPumpError, match="max_piston_stroke_mm"):
        backend.configure_syringe(
            {"inner_diameter_mm": 10.0, "max_piston_stroke_mm": MAX_SYRINGE_STROKE_MM + 0.1}
        )

    pump = FakeQmixPumpModule.Pump.instances[0]
    assert not any(call[0] == "set_syringe_param" for call in pump.calls)


def test_configure_syringe_rejects_stroke_between_real_ceiling_and_old_padded_bound(tmp_path):
    # Regression guard for the exact gap a prior version of MAX_SYRINGE_STROKE_MM
    # left open: that constant was originally set to 200.0 (a BD-volume-range
    # -derived padding estimate), which silently accepted anything up to
    # 200mm even though this pump module's own real mechanical piston-travel
    # ceiling is 65mm (CETONI Low Pressure Hardware Manual Section 5.1,
    # NEM-B101-02 E) -- a value in (65, 200) would have been accepted and
    # forwarded to set_syringe_param() before the fix, risking exactly the
    # over-travel damage that manual's own ATTENTION warning describes.
    # 100.0mm sits squarely in that now-closed gap.
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(qmixbus=FakeQmixBusModule, qmixpump=FakeQmixPumpModule)
    backend.initialize(tmp_path / "qmix-config")
    assert MAX_SYRINGE_STROKE_MM < 100.0 < 200.0, "this test only proves what it claims if 100.0 is still inside the closed gap"

    with pytest.raises(QmixPumpError, match="max_piston_stroke_mm"):
        backend.configure_syringe({"inner_diameter_mm": 10.0, "max_piston_stroke_mm": 100.0})

    pump = FakeQmixPumpModule.Pump.instances[0]
    assert not any(call[0] == "set_syringe_param" for call in pump.calls)


def test_configure_syringe_accepts_values_exactly_at_bounds(tmp_path):
    # Bounds are inclusive -- a value exactly at MIN/MAX must not be rejected.
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(qmixbus=FakeQmixBusModule, qmixpump=FakeQmixPumpModule)
    backend.initialize(tmp_path / "qmix-config")

    backend.configure_syringe(
        {"inner_diameter_mm": MIN_SYRINGE_INNER_DIAMETER_MM, "max_piston_stroke_mm": MIN_SYRINGE_STROKE_MM}
    )
    backend.configure_syringe(
        {"inner_diameter_mm": MAX_SYRINGE_INNER_DIAMETER_MM, "max_piston_stroke_mm": MAX_SYRINGE_STROKE_MM}
    )

    pump = FakeQmixPumpModule.Pump.instances[0]
    assert ("set_syringe_param", MIN_SYRINGE_INNER_DIAMETER_MM, MIN_SYRINGE_STROKE_MM) in pump.calls
    assert ("set_syringe_param", MAX_SYRINGE_INNER_DIAMETER_MM, MAX_SYRINGE_STROKE_MM) in pump.calls


def test_configure_syringe_named_bd_presets_still_pass_the_new_bounds():
    # All three named presets must remain valid under the new bounds --
    # confirms the bounds were derived to comfortably include the existing,
    # already-hardware-confirmed presets, not accidentally narrower than them.
    for diameter_mm, stroke_mm in SYRINGE_PRESETS.values():
        assert MIN_SYRINGE_INNER_DIAMETER_MM <= diameter_mm <= MAX_SYRINGE_INNER_DIAMETER_MM
        assert MIN_SYRINGE_STROKE_MM <= stroke_mm <= MAX_SYRINGE_STROKE_MM


# -- Pump flow rate vs. the pump's own reported max_flow_rate_ul_min
# (Session 51): the value was already being read back from the device
# (initialize()/configure_syringe()/configure_flow_unit() all populate it),
# but generate_flow() never actually compared against it -- these tests
# confirm the new rejection, in both directions (dispense/aspirate).

def test_generate_flow_rejects_dispense_rate_above_max(tmp_path):
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(qmixbus=FakeQmixBusModule, qmixpump=FakeQmixPumpModule)
    backend.initialize(tmp_path / "qmix-config")
    assert backend.max_flow_rate_ul_min == 5000.0

    with pytest.raises(QmixPumpError, match="max_flow_rate_ul_min"):
        backend.generate_flow(5000.1)

    pump = FakeQmixPumpModule.Pump.instances[0]
    assert not any(call[0] == "generate_flow" for call in pump.calls)


def test_generate_flow_rejects_aspirate_rate_above_max_magnitude(tmp_path):
    # Negative flow_rate means aspirate (generate_flow()'s own docstring) --
    # the magnitude must still be checked, not just the raw signed value.
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(qmixbus=FakeQmixBusModule, qmixpump=FakeQmixPumpModule)
    backend.initialize(tmp_path / "qmix-config")

    with pytest.raises(QmixPumpError, match="max_flow_rate_ul_min"):
        backend.generate_flow(-5000.1)

    pump = FakeQmixPumpModule.Pump.instances[0]
    assert not any(call[0] == "generate_flow" for call in pump.calls)


def test_generate_flow_accepts_rate_exactly_at_max(tmp_path):
    # Inclusive bound -- exactly at max_flow_rate_ul_min must not be rejected.
    FakeQmixPumpModule.Pump.instances = []
    backend = QmixPumpBackend(qmixbus=FakeQmixBusModule, qmixpump=FakeQmixPumpModule)
    backend.initialize(tmp_path / "qmix-config")

    backend.generate_flow(-5000.0)

    pump = FakeQmixPumpModule.Pump.instances[0]
    assert ("generate_flow", -5000.0) in pump.calls


def test_generate_flow_passes_through_when_max_flow_rate_not_yet_known():
    # No live max_flow_rate_ul_min at all (e.g. configure_syringe()/
    # initialize() never populated it) -- nothing to validate against, so
    # this must behave exactly as before the Session 51 change: pass through
    # unchanged, not silently invent a limit.
    FakeQmixPumpModule.Pump.instances = []
    pump_instance = FakeQmixPumpModule.Pump()
    backend = QmixPumpBackend(qmixbus=FakeQmixBusModule, qmixpump=FakeQmixPumpModule, pump=pump_instance)
    assert backend.max_flow_rate_ul_min is None

    backend.generate_flow(999999.0)

    assert ("generate_flow", 999999.0) in pump_instance.calls


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
        return exposure_ms

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

    def image_sequence(self, frame_count=0, partial_capture_folder=None):
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


def test_center_roi_reapplies_centered_coordinates_to_real_backend():
    backend = FakeCameraBackend()
    camera = HamamatsuCamera(backend=backend)
    camera.update_roi_limits(
        SubRegionLimits(
            horizontal_size=MinMaxInc(0, 100, 1),
            vertical_size=MinMaxInc(0, 80, 1),
        )
    )
    camera.configure_roi(SubRegion(horizontal_size=20, vertical_size=10))
    backend.calls.clear()

    camera.center_roi()

    configure_roi_calls = [call for call in backend.calls if call[0] == "configure_roi"]
    assert len(configure_roi_calls) == 1, "center_roi() must re-apply the centered ROI via a real configure_roi() call"
    applied_roi = configure_roi_calls[0][1]
    assert (applied_roi.horizontal_offset, applied_roi.vertical_offset) == (40, 35)
    assert (applied_roi.horizontal_size, applied_roi.vertical_size) == (20, 10)
    assert camera.roi is applied_roi


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


def test_configure_do_records_achieved_frequency_after_integer_divider_rounding():
    # Finding E regression test: clock_divider is an integer, so the real
    # achieved DO-clock frequency can differ substantially from the
    # requested clock_frequency_hz -- previously never recorded anywhere at
    # all. FakeDwf's internal clock is fixed at 100.0 Hz (confirmed by the
    # test above); 33.0 Hz requested truncates the divider to 1, giving a
    # genuinely different achieved frequency (50.0 Hz), not a rounding-noise
    # -level gap that could pass by coincidence.
    fake = FakeDwf()
    backend = WaveFormsBackend(dwf=fake)
    channel = DoSingleChannelConfig(channel_index=0, enable=True, clock_frequency_hz=33.0)
    config = DoConfig(channels=[channel])

    backend.configure_do(123, config)

    assert channel.achieved_clock_frequency_hz == pytest.approx(50.0)
    assert channel.achieved_clock_frequency_hz != channel.clock_frequency_hz


def test_configure_do_leaves_achieved_frequency_none_when_no_clock_requested():
    fake = FakeDwf()
    backend = WaveFormsBackend(dwf=fake)
    channel = DoSingleChannelConfig(channel_index=0, enable=True)
    config = DoConfig(channels=[channel])

    backend.configure_do(123, config)

    assert channel.achieved_clock_frequency_hz is None


def test_run_experiment2_records_do_clock_achieved_frequency_in_final_tdms(tmp_path, monkeypatch):
    # Finding E regression test, end-to-end: drives the real run_experiment2()
    # call order (config_do_clock_special() mutates the same DoConfig object
    # experiment.do_clock_settings references, then Finding A's existing
    # second save_settings() call captures the result -- no new ordering fix
    # needed here, but confirming that combination actually works end-to-end
    # is the point, same discipline as Finding A's own test).
    writes = install_fake_nptdms(monkeypatch)
    fake_dwf = FakeDwf()
    ad2 = AD2Sdk(backend=WaveFormsBackend(dwf=fake_dwf), device_handle=123)
    app = Application(ad2=ad2)
    do_channel = DoSingleChannelConfig(
        channel_index=0,
        enable=True,
        clock_frequency_hz=33.0,
        trigger=TriggerSettings(sec_run=0.0, sec_wait=0.0),
    )
    experiment = Experiment2(
        experiment_folder=tmp_path / "experiment-do-freq",
        do_clock_settings=DoConfig(channels=[do_channel]),
    )
    app.experiment_series.enqueue_experiments([experiment])

    ok = app.run_experiment2()

    assert ok
    assert do_channel.achieved_clock_frequency_hz == pytest.approx(50.0)
    tdms_path = tmp_path / "experiment-do-freq" / "data.tdms"
    properties = next(
        item for item in writes[str(tdms_path)] if getattr(item, "kind", "") == "group" and item.name == "Experiment"
    ).properties
    assert properties["DOFreq"] == 33.0
    assert properties["DOFreqActual"] == pytest.approx(50.0), (
        "the FINAL data.tdms must record the real achieved DO-clock frequency, not just the requested one"
    )


# -- AD2 amplitude/frequency clamping against the device's own live
# AnalogOutNode*Info() range (Session 51). Purpose-built fake, not the
# generic FakeDwf above -- FakeDwf's blanket "*Info" handling returns a
# degenerate (100.0, 100.0) for every Info call (frequency and amplitude
# indistinguishable), which can't exercise clamping in a meaningful,
# unambiguous direction.
class FakeAD2ConfigureDwf:
    def __init__(self, frequency_range=(10.0, 1_000_000.0), amplitude_range=(-5.0, 5.0)):
        self.frequency_range = frequency_range
        self.amplitude_range = amplitude_range
        self.calls = []

    def __getattr__(self, name):
        def func(*args):
            self.calls.append((name, args))
            if name == "FDwfAnalogOutNodeFrequencyInfo":
                self._assign(args[3], self.frequency_range[0])
                self._assign(args[4], self.frequency_range[1])
            elif name == "FDwfAnalogOutNodeAmplitudeInfo":
                self._assign(args[3], self.amplitude_range[0])
                self._assign(args[4], self.amplitude_range[1])
            return 1
        return func

    @staticmethod
    def _assign(byref_arg, value):
        target = getattr(byref_arg, "_obj", byref_arg)
        target.value = value


def test_configure_wfg_clamps_out_of_range_amplitude_and_frequency_and_flags_channel():
    fake = FakeAD2ConfigureDwf(frequency_range=(10.0, 1_000_000.0), amplitude_range=(-5.0, 5.0))
    backend = WaveFormsBackend(dwf=fake)
    channel = WfgChannelConfig(0)
    channel.carrier.frequency_hz = 2_000_000.0  # above the fake device's max
    channel.carrier.amplitude_v = 10.0  # above the fake device's max
    config = WfgConfig(channels=[channel])

    backend.configure_wfg(123, config)

    assert channel.out_of_range is True
    assert config.check_valid() is False
    frequency_set_calls = [args for name, args in fake.calls if name == "FDwfAnalogOutNodeFrequencySet"]
    amplitude_set_calls = [args for name, args in fake.calls if name == "FDwfAnalogOutNodeAmplitudeSet"]
    assert frequency_set_calls[0][3].value == 1_000_000.0, "must clamp to the device's real max, not send the requested value unchanged"
    assert amplitude_set_calls[0][3].value == 5.0, "must clamp to the device's real max, not send the requested value unchanged"


def test_configure_wfg_leaves_in_range_values_unclamped_and_not_out_of_range():
    fake = FakeAD2ConfigureDwf(frequency_range=(10.0, 1_000_000.0), amplitude_range=(-5.0, 5.0))
    backend = WaveFormsBackend(dwf=fake)
    channel = WfgChannelConfig(0)
    channel.carrier.frequency_hz = 1000.0
    channel.carrier.amplitude_v = 1.0
    config = WfgConfig(channels=[channel])

    backend.configure_wfg(123, config)

    assert channel.out_of_range is False
    assert config.check_valid() is True
    frequency_set_calls = [args for name, args in fake.calls if name == "FDwfAnalogOutNodeFrequencySet"]
    amplitude_set_calls = [args for name, args in fake.calls if name == "FDwfAnalogOutNodeAmplitudeSet"]
    assert frequency_set_calls[0][3].value == 1000.0
    assert amplitude_set_calls[0][3].value == 1.0


def test_configure_wfg_checks_fm_mod_node_too_when_enabled():
    fake = FakeAD2ConfigureDwf(frequency_range=(10.0, 1_000_000.0), amplitude_range=(-5.0, 5.0))
    backend = WaveFormsBackend(dwf=fake)
    channel = WfgChannelConfig(0)
    channel.carrier.frequency_hz = 1000.0
    channel.carrier.amplitude_v = 1.0
    channel.fm_mod.enable = True
    channel.fm_mod.amplitude_v = 999.0  # above the fake device's max
    config = WfgConfig(channels=[channel])

    backend.configure_wfg(123, config)

    assert channel.out_of_range is True, "an out-of-range FM Mod node must flag the channel too, not just Carrier"


def test_write_tdms_verification_catches_truncated_write(tmp_path, monkeypatch):
    class TruncatingTdmsWriter:
        def __init__(self, path):
            self.path = Path(path)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def write_segment(self, objects):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Far below _MIN_TDMS_FILE_SIZE_BYTES -- simulates a truncated/corrupted write.
            self.path.write_bytes(b"x")

    monkeypatch.setitem(
        sys.modules,
        "nptdms",
        SimpleNamespace(
            ChannelObject=lambda group, name, data: SimpleNamespace(kind="channel", group=group, name=name, data=list(data)),
            GroupObject=lambda name, properties=None: SimpleNamespace(kind="group", name=name, properties=properties or {}),
            RootObject=lambda properties=None: SimpleNamespace(kind="root", properties=properties or {}),
            TdmsWriter=TruncatingTdmsWriter,
            TdmsFile=SimpleNamespace(read=lambda path: (_ for _ in ()).throw(RuntimeError("should not be reached"))),
        ),
    )

    experiment = Experiment2(experiment_folder=tmp_path / "truncated")
    tdms_path = tmp_path / "truncated" / "data.tdms"

    with pytest.raises(RuntimeError, match="write verification failed"):
        experiment.create_folder_and_tdms()

    # The bad file is left on disk (not silently accepted as a valid experiment) --
    # but the RuntimeError above is what actually protects the caller.
    assert tdms_path.exists()
    assert tdms_path.stat().st_size < 128


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
        "WFGOutOfRangeCh1",
        "WFGFreqCh2",
        "WFGAmpCh2",
        "WFGRunCh2",
        "WFGWaitCh2",
        "RepeatCh2",
        "WFGOutOfRangeCh2",
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
    assert properties["WFGOutOfRangeCh1"] is False
    assert properties["WFGOutOfRangeCh2"] is False
    channels = {item.name: item for item in objects if getattr(item, "kind", "") == "channel"}
    assert channels["ImageName"].data == ["frame_00000.tiff", "frame_00001.tiff"]
    assert len(channels["Timestamp"].data) == 2


def test_experiment2_writes_camera_sequence_cluster_to_tdms(tmp_path, monkeypatch):
    # Finding C regression test: Session 22 made this whole cluster
    # (masterpulse mode/source/interval/burst + trigger source/polarity/
    # delay) genuinely load-bearing for automated runs, but until this fix
    # none of it ever reached data.tdms -- a repeat's actual DCAM trigger
    # configuration was unrecoverable after the fact. Uses distinguishable,
    # non-default values for every field (not just "present") so a bug that
    # read the wrong key or hardcoded a default would be caught, matching
    # the exact keys hamamatsu_dcam.py's configure_sequence() itself reads.
    writes = install_fake_nptdms(monkeypatch)
    experiment = Experiment2(
        experiment_folder=tmp_path / "repeat_seq",
        sequence_settings={
            "frames": 5,
            "trigger_source": "external",
            "masterpulse_mode": "normal",
            "masterpulse_source": "internal",
            "masterpulse_interval_s": 0.002,
            "masterpulse_burst_times": 3,
            "trigger_polarity": "negative",
            "trigger_delay_s": 0.0005,
        },
    )

    experiment.create_folder_and_tdms()
    experiment.save_settings()

    tdms_path = tmp_path / "repeat_seq" / "data.tdms"
    properties = next(
        item for item in writes[str(tdms_path)] if getattr(item, "kind", "") == "group" and item.name == "Experiment"
    ).properties
    assert properties["TriggerSource"] == "external"
    assert properties["MasterPulseMode"] == "normal"
    assert properties["MasterPulseSource"] == "internal"
    assert properties["MasterPulseInterval"] == 0.002
    assert properties["MasterPulseBurstTimes"] == 3
    assert properties["TriggerPolarity"] == "negative"
    assert properties["TriggerDelay"] == 0.0005


def test_experiment2_sequence_properties_default_to_empty_string_when_unset(tmp_path):
    experiment = Experiment2(experiment_folder=tmp_path / "repeat_no_seq", sequence_settings=None)

    properties = experiment._settings_properties()

    for field in (
        "TriggerSource",
        "MasterPulseMode",
        "MasterPulseSource",
        "MasterPulseInterval",
        "MasterPulseBurstTimes",
        "TriggerPolarity",
        "TriggerDelay",
    ):
        assert properties[field] == ""


def test_experiment_settings_properties_include_git_commit_hash(monkeypatch, tmp_path):
    monkeypatch.setattr("thermo_acoustic.workflows._git_commit_hash", lambda: "deadbeef-dirty")

    experiment = Experiment2(experiment_folder=tmp_path / "repeat_001")
    properties = experiment._settings_properties()

    assert properties["GitCommitHash"] == "deadbeef-dirty"


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


def test_hamamatsu_close_logs_swallowed_cleanup_errors_instead_of_silently_passing(caplog, monkeypatch):
    # Finding F regression test: close()'s two cleanup steps (stop capture,
    # release buffer) were previously wrapped in a bare `except Exception:
    # pass` -- no logging at all, unlike every other cleanup path in this
    # codebase. If the camera genuinely failed to stop capture or release its
    # buffer, Application.cleanup() would see a clean success with zero
    # indication anything went wrong. Forces both cleanup steps to raise
    # independently and confirms both errors are logged (not just one, and
    # not silently swallowed), and that close() itself still completes
    # without raising (cleanup remains intentionally best-effort -- only the
    # silence is fixed, not the "don't propagate cleanup failures" behavior).
    from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend, HamamatsuDcamError

    backend = HamamatsuDcamBackend()
    backend.dcam_module = FakeDcamModule
    backend.dcamapi = FakeDcamApi
    backend.dcam = FakeDcamModule.Dcam(0)
    backend.dcam.opened = True
    backend.initialized = False

    def raise_stop_capture_failure(self):
        raise HamamatsuDcamError("stop capture failed")

    def raise_buffer_release_failure():
        raise RuntimeError("buffer release failed")

    monkeypatch.setattr(HamamatsuDcamBackend, "_stop_capture_if_active", raise_stop_capture_failure)
    backend.dcam.buf_release = raise_buffer_release_failure

    with caplog.at_level("ERROR", logger="thermo_acoustic.hamamatsu_dcam"):
        backend.close()  # must not raise -- cleanup stays best-effort

    messages = [record.message for record in caplog.records]
    assert any("failed to stop capture" in m and "stop capture failed" in m for m in messages), messages
    assert any("failed to release buffer" in m and "buffer release failed" in m for m in messages), messages
    assert backend.dcam is None, "cleanup must still complete despite both logged failures"


def test_configure_exposure_time_returns_real_applied_value_not_requested(tmp_path):
    # Finding E regression test: prop_setgetvalue() (per DCAM's own
    # documented "set and get" contract) returns the real value the device
    # applied, which can differ from the request due to DCAM's own internal
    # exposure quantization -- previously discarded, so configure_exposure_time()
    # had no way to report anything but the raw request back to its caller.
    # A quantizing fake (applied = requested + 0.1ms, not an exact echo)
    # would fail this test if the return value were ever silently dropped
    # again.
    from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend

    backend = HamamatsuDcamBackend()
    backend.dcam_module = FakeDcamModule
    backend.dcamapi = FakeDcamApi
    handle = backend.open_camera()

    def quantizing_prop_setgetvalue(prop, value, option=0):
        if prop == "EXPOSURETIME":
            applied = value + 0.0001  # +0.1ms, simulating real DCAM quantization
            handle.values[prop] = applied
            handle.calls.append(("prop_setgetvalue", prop, value))
            return applied
        return FakeDcamModule.Dcam.prop_setgetvalue(handle, prop, value, option)

    handle.prop_setgetvalue = quantizing_prop_setgetvalue

    applied_ms = backend.configure_exposure_time(50.0)

    assert applied_ms == pytest.approx(50.1), (
        "must return the real applied exposure (with quantization), not echo back the 50.0ms request"
    )


def test_run_experiment2_records_real_applied_exposure_in_final_tdms(tmp_path, monkeypatch):
    # Finding E regression test, end-to-end: confirms both HamamatsuCamera's
    # facade (uses the backend's real return value, not the request) and
    # Application.run_experiment2()'s wiring (re-snapshots data.tdms's
    # ExposureTime with that real value) together, the same way Finding A's
    # test drives the real call order rather than testing either layer in
    # isolation.
    writes = install_fake_nptdms(monkeypatch)

    class QuantizingCameraBackend:
        def __init__(self):
            self.calls = []

        def configure_exposure_time(self, exposure_ms):
            self.calls.append(exposure_ms)
            return exposure_ms + 0.25  # simulates real DCAM quantization

        def configure_sequence(self, settings):
            pass

        def configure_trigger_global_exposure(self, enabled):
            pass

        def start_capture(self):
            pass

        def stop_capture(self):
            pass

        def image_sequence(self, frame_count=0, partial_capture_folder=None):
            return []

        def read_frame_timestamps(self):
            return []

        def save_sequence(self, image_data, folder):
            folder.mkdir(parents=True, exist_ok=True)

        def get_camera_buffer_size(self):
            return 0

        def get_sub_region(self):
            return {}

        def read_readout_time(self):
            return 0.0

    app = Application(ad2=SimulatedAD2Sdk(), camera=HamamatsuCamera(backend=QuantizingCameraBackend()))
    experiment = Experiment2(
        experiment_folder=tmp_path / "experiment-exposure-quantized",
        global_exposure_ms=40.0,
    )
    app.experiment_series.enqueue_experiments([experiment])

    ok = app.run_experiment2()

    assert ok
    assert app.camera.exposure_ms == pytest.approx(40.25), "the facade must track the real applied value, not the request"
    tdms_path = tmp_path / "experiment-exposure-quantized" / "data.tdms"
    properties = next(
        item for item in writes[str(tdms_path)] if getattr(item, "kind", "") == "group" and item.name == "Experiment"
    ).properties
    assert properties["ExposureTime"] == pytest.approx(40.25), (
        "the FINAL data.tdms must record the real applied exposure, not the original 40.0ms request"
    )


# -- Camera ROI pre-flight validation (Session 51): DCAM's own SUBARRAY
# properties already reject an invalid combination via the existing
# _check()/prop_setgetvalue() calls (confirmed by reading the vendored DCAM
# error enum: INVALIDSUBARRAY = "SUBARRAYHPOS + SUBARRAYHSIZE is greater
# than the number of horizontal pixel of sensor") -- these tests confirm
# the new pre-flight check catches the same condition earlier, with a
# clearer message, and before any SDK write happens at all.

def test_validate_roi_against_limits_accepts_in_range_roi():
    from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend

    backend = HamamatsuDcamBackend()
    limits = SubRegionLimits(
        horizontal_offset=MinMaxInc(0, 2304, 1),
        vertical_offset=MinMaxInc(0, 2304, 1),
        horizontal_size=MinMaxInc(1, 2304, 1),
        vertical_size=MinMaxInc(1, 2304, 1),
    )
    current_roi = SubRegion(0, 0, 2304, 2304)

    backend._validate_roi_against_limits(SubRegion(0, 0, 100, 120), limits, current_roi)


def test_validate_roi_against_limits_rejects_size_above_sensor_max():
    from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend, HamamatsuDcamError

    backend = HamamatsuDcamBackend()
    limits = SubRegionLimits(
        horizontal_offset=MinMaxInc(0, 2304, 1),
        vertical_offset=MinMaxInc(0, 2304, 1),
        horizontal_size=MinMaxInc(1, 2304, 1),
        vertical_size=MinMaxInc(1, 2304, 1),
    )
    current_roi = SubRegion(0, 0, 2304, 2304)

    with pytest.raises(HamamatsuDcamError, match="horizontal_size"):
        backend._validate_roi_against_limits(SubRegion(0, 0, 5000, 120), limits, current_roi)


def test_validate_roi_against_limits_rejects_offset_plus_size_exceeding_sensor():
    # Mirrors DCAM's own INVALIDSUBARRAY condition: each of offset/size is
    # individually in range, but their sum exceeds the sensor's real pixel
    # count -- must still be rejected.
    from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend, HamamatsuDcamError

    backend = HamamatsuDcamBackend()
    limits = SubRegionLimits(
        horizontal_offset=MinMaxInc(0, 2304, 1),
        vertical_offset=MinMaxInc(0, 2304, 1),
        horizontal_size=MinMaxInc(1, 2304, 1),
        vertical_size=MinMaxInc(1, 2304, 1),
    )
    current_roi = SubRegion(0, 0, 2304, 2304)

    with pytest.raises(HamamatsuDcamError, match="exceeds the sensor's real horizontal pixel count"):
        backend._validate_roi_against_limits(SubRegion(2000, 0, 2000, 120), limits, current_roi)


def test_validate_roi_against_limits_uses_current_size_when_size_not_being_changed():
    # horizontal_size=0 means configure_roi() won't call SUBARRAYHSIZE's Set
    # this time -- the offset+size check must fall back to the *current*
    # size (already in effect), not silently skip the combined check.
    from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend, HamamatsuDcamError

    backend = HamamatsuDcamBackend()
    limits = SubRegionLimits(
        horizontal_offset=MinMaxInc(0, 2304, 1),
        vertical_offset=MinMaxInc(0, 2304, 1),
        horizontal_size=MinMaxInc(1, 2304, 1),
        vertical_size=MinMaxInc(1, 2304, 1),
    )
    current_roi = SubRegion(0, 0, 2304, 2304)  # full-width, already in effect

    with pytest.raises(HamamatsuDcamError, match="exceeds the sensor's real horizontal pixel count"):
        backend._validate_roi_against_limits(SubRegion(100, 0, 0, 0), limits, current_roi)


def test_configure_roi_rejects_out_of_range_roi_before_any_sdk_write():
    from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend, HamamatsuDcamError

    backend = HamamatsuDcamBackend()
    backend.dcam_module = FakeDcamModule
    backend.dcamapi = FakeDcamApi
    handle = backend.open_camera()

    with pytest.raises(HamamatsuDcamError, match="horizontal_size"):
        backend.configure_roi(SubRegion(0, 0, 5000, 120))

    assert not any(call[0] == "prop_setgetvalue" and call[1] == "SUBARRAYHSIZE" for call in handle.calls), (
        "an out-of-range ROI must be rejected before any SUBARRAY property is actually written"
    )
