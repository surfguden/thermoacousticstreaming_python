"""Legacy Tkinter UI retained only as a migration reference.

The supported application entry points launch the PySide6 UI in ``qt_ui.py``;
no launcher or production module imports this file. This module is not a
supported control surface and must not be used for real hardware operation.
It is intentionally kept for historical LabVIEW-to-Python traceability until a
separate removal decision is made.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from .ad2 import CarrierSettings, TriggerSettings, WaveformFunction, WfgChannelConfig, WfgConfig
from .application import Application
from .camera import SubRegion
from .instruments import AD2Sdk, CetoniPump, HamamatsuCamera, PriorZMotor, SimulatedAD2Sdk, Valve
from .workflows import Experiment2, ExperimentSeries2, FlushSettings


class MainWindow(tk.Tk):
    def __init__(self, app: Application | None = None) -> None:
        super().__init__()
        self.title("LabVIEW to Python Conversion")
        self.geometry("1280x820")
        self.minsize(1000, 680)
        self.app = app or Application(ad2=SimulatedAD2Sdk())

        self.status_var = tk.StringVar(value=self.app.status)
        self.error_status_var = tk.BooleanVar(value=False)
        self.error_code_var = tk.StringVar(value="0")
        self.error_source_var = tk.StringVar(value="")

        self._build_variables()
        self._build_layout()
        self._refresh_status()

    def _build_variables(self) -> None:
        self.ad2_enabled = tk.BooleanVar(value=True)
        self.z_stage_enabled = tk.BooleanVar(value=False)
        self.camera_enabled = tk.BooleanVar(value=True)
        self.pump_enabled = tk.BooleanVar(value=True)
        self.valve_enabled = tk.BooleanVar(value=True)
        self.sim_camera = tk.BooleanVar(value=True)
        self.sim_pump = tk.BooleanVar(value=True)
        self.sim_valve = tk.BooleanVar(value=True)
        self.prior_resource = tk.StringVar(value="COM7")
        self.valve_resource = tk.StringVar(value="COM6")
        self.cetoni_config_path = tk.StringVar(value=r"C:\Users\Public\Documents\QmixElements\Projects")

        self.wfg_running = tk.BooleanVar(value=True)
        self.wfg_sync_state = tk.StringVar(value="Independent")
        self.wfg_channels = []
        for index, frequency, amplitude in ((0, "1.9e6", "2"), (1, "1000", "1")):
            self.wfg_channels.append(
                {
                    "idx": tk.StringVar(value=str(index)),
                    "frequency": tk.StringVar(value=frequency),
                    "amplitude": tk.StringVar(value=amplitude),
                    "offset": tk.StringVar(value="0"),
                    "symmetry": tk.StringVar(value="50"),
                    "phase": tk.StringVar(value="0"),
                    "function": tk.StringVar(value="Sine"),
                    "enable": tk.BooleanVar(value=False),
                    "sec_run": tk.StringVar(value="0"),
                    "sec_wait": tk.StringVar(value="0"),
                    "repeat": tk.StringVar(value="0"),
                    "repeat_trigger": tk.BooleanVar(value=False),
                    "trigger_source": tk.StringVar(value="trigsrcNone"),
                    "fm_frequency": tk.StringVar(value="1000"),
                    "fm_amplitude": tk.StringVar(value="1"),
                    "fm_offset": tk.StringVar(value="0"),
                    "fm_symmetry": tk.StringVar(value="50"),
                    "fm_phase": tk.StringVar(value="0"),
                    "fm_function": tk.StringVar(value="Sine"),
                    "fm_enable": tk.BooleanVar(value=False),
                }
            )

        self.syringe_var = tk.StringVar(value="BD 1ml")
        self.flow_rate_var = tk.StringVar(value="-5000")
        self.level_var = tk.StringVar(value="0")
        self.flush_flowrate_var = tk.StringVar(value="0")
        self.flush_volume_var = tk.StringVar(value="0")
        self.wait_after_flush_var = tk.StringVar(value="0")
        self.flush_count_var = tk.StringVar(value="1")

        self.image_continuous = tk.BooleanVar(value=True)
        self.roi_horizontal_offset = tk.StringVar(value="0")
        self.roi_vertical_offset = tk.StringVar(value="900")
        self.roi_horizontal_size = tk.StringVar(value="2304")
        self.roi_vertical_size = tk.StringVar(value="500")
        self.exposure_ms = tk.StringVar(value="50")
        self.center_roi_var = tk.BooleanVar(value=True)
        self.sequence_path = tk.StringVar(value="")
        self.sequence_mode = tk.StringVar(value="Continuous")
        self.sequence_source = tk.StringVar(value="External")
        self.sequence_interval = tk.StringVar(value="1")
        self.sequence_burst = tk.StringVar(value="0")
        self.capture_mode = tk.StringVar(value="Snap")
        self.sequence_frames = tk.StringVar(value="0")
        self.dcam_trigger_source = tk.StringVar(value="Internal")
        self.trigger_polarity = tk.StringVar(value="Negative")
        self.trigger_delay = tk.StringVar(value="0")
        self.sequence_exposure_ms = tk.StringVar(value="0")
        self.frame_index_var = tk.StringVar(value="0")
        self.frame_count_var = tk.StringVar(value="0")

        self.elapsed_time_var = tk.StringVar(value="00:00:00")
        self.time_left_var = tk.StringVar(value="00:00:00")
        self.queue_count_var = tk.StringVar(value="0")
        self.series_path_var = tk.StringVar(value=r"C:\test\firstrunpulsed")
        self.experiment_camera_fps = tk.StringVar(value="0")
        self.experiment_camera_start = tk.StringVar(value="0")
        self.experiment_ch1_frequency = tk.StringVar(value="0")
        self.experiment_ch1_amplitude = tk.StringVar(value="0")
        self.experiment_ch1_start = tk.StringVar(value="0")
        self.experiment_ch1_run = tk.StringVar(value="0")
        self.experiment_ch2_start = tk.StringVar(value="0")
        self.experiment_ch2_run = tk.StringVar(value="0")
        self.experiment_repeats = tk.StringVar(value="1")
        self.experiment_frames = tk.StringVar(value="1")
        self.experiment_exposure = tk.StringVar(value="0")
        self.global_exposure = tk.BooleanVar(value=False)
        self.dynamic_camera_start_time = tk.BooleanVar(value=False)
        self.average_fps_var = tk.StringVar(value="0")

    def _build_layout(self) -> None:
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(outer)
        top.pack(fill=tk.X)
        ttk.Button(top, text="Exit", command=self._on_exit).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Button(top, text="Abort", command=self._on_abort).pack(side=tk.LEFT)
        status_frame = ttk.Frame(top)
        status_frame.pack(side=tk.RIGHT)
        ttk.Label(status_frame, text="Status", font=("Segoe UI", 18)).pack(anchor=tk.W)
        ttk.Entry(status_frame, textvariable=self.status_var, width=28, state="readonly").pack()

        main = ttk.Frame(outer)
        main.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = ttk.Frame(main, width=210)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        self.tabs = ttk.Notebook(left)
        self.tabs.pack(fill=tk.BOTH, expand=True)
        self._build_initialization_tab()
        self._build_wfg_tab()
        self._build_pump_valve_tab()
        self._build_camera_tab()
        self._build_experiment_tab()
        self._build_error_panel(right)

    def _build_error_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Error Out", padding=8)
        frame.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Checkbutton(frame, text="status", variable=self.error_status_var).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(frame, text="code").grid(row=0, column=1, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.error_code_var, width=10).grid(row=1, column=1, sticky=tk.EW)
        ttk.Label(frame, text="source").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Entry(frame, textvariable=self.error_source_var, width=22).grid(row=3, column=0, columnspan=2, sticky=tk.EW)

    def _build_initialization_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=24)
        self.tabs.add(tab, text="Initialization")
        left = ttk.Frame(tab)
        left.grid(row=0, column=0, sticky=tk.NW)
        right = ttk.Frame(tab)
        right.grid(row=0, column=1, sticky=tk.NW, padx=(80, 0))

        self._check_row(left, "Analog Discovery 3", self.ad2_enabled, 0)
        self._check_row(left, "Z stage", self.z_stage_enabled, 1)
        ttk.Label(left, text="Prior Visa resource name").grid(row=1, column=2, padx=(50, 5), sticky=tk.W)
        ttk.Combobox(left, textvariable=self.prior_resource, values=("COM7",), width=10).grid(row=1, column=3, sticky=tk.W)
        self._check_row(left, "Hamamatsu", self.camera_enabled, 2)
        self._check_row(left, "Cetoni Pump", self.pump_enabled, 3)
        ttk.Label(left, text="Cetoni Device Configuration Path").grid(row=3, column=2, padx=(50, 5), sticky=tk.W)
        ttk.Entry(left, textvariable=self.cetoni_config_path, width=55).grid(row=3, column=3, sticky=tk.W)
        self._check_row(left, "MX Valve 2", self.valve_enabled, 4)
        ttk.Label(left, text="Valve VISA resource name").grid(row=4, column=2, padx=(50, 5), sticky=tk.W)
        ttk.Combobox(left, textvariable=self.valve_resource, values=("COM6",), width=10).grid(row=4, column=3, sticky=tk.W)
        ttk.Label(left, text="Initialize System").grid(row=5, column=0, sticky=tk.W, pady=(24, 0))
        ttk.Button(left, text="Initialize!", command=self._initialize_system).grid(row=6, column=0, columnspan=2, sticky=tk.EW, pady=(4, 0), ipady=10)

        self._check_row(right, "Simulate Camera", self.sim_camera, 0)
        self._check_row(right, "Simulate Pump", self.sim_pump, 1)
        self._check_row(right, "Simulate Valve", self.sim_valve, 2)

    def _check_row(self, parent: ttk.Frame, label: str, variable: tk.BooleanVar, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=8)
        ttk.Checkbutton(parent, text="Off/On", variable=variable).grid(row=row, column=1, sticky=tk.W, pady=8)

    def _build_wfg_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=24)
        self.tabs.add(tab, text="WFG")
        ttk.Checkbutton(tab, text="Running Ch1", variable=self.wfg_running).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(tab, text="SynchronizeState").grid(row=0, column=2, sticky=tk.W)
        ttk.Combobox(tab, textvariable=self.wfg_sync_state, values=("Independent", "Synchronized"), width=16).grid(row=1, column=2, sticky=tk.W)

        for column, channel_vars in enumerate(self.wfg_channels):
            self._build_wfg_channel(tab, channel_vars, column)
        ttk.Button(tab, text="Apply WFG", command=self._apply_wfg).grid(row=20, column=0, sticky=tk.W, pady=(16, 0))

    def _build_wfg_channel(self, parent: ttk.Frame, values: dict[str, tk.Variable], column: int) -> None:
        frame = ttk.LabelFrame(parent, text="Ch1" if column == 0 else "Ch2", padding=8)
        frame.grid(row=1, column=column, sticky=tk.NW, padx=(0, 14))
        row = 0
        for label, key in (
            ("idxChannel", "idx"),
            ("Frequency (Hz)", "frequency"),
            ("AD2 source peak amplitude (V)", "amplitude"),
            ("Offset(V)", "offset"),
            ("Symmetry(%)", "symmetry"),
            ("Phase(Deg)", "phase"),
        ):
            ttk.Label(frame, text=label).grid(row=row, column=1, sticky=tk.W)
            ttk.Entry(frame, textvariable=values[key], width=12).grid(row=row, column=0, sticky=tk.W)
            row += 1
        ttk.Label(frame, text="Function").grid(row=row, column=1, sticky=tk.W)
        ttk.Combobox(frame, textvariable=values["function"], values=[item.value for item in WaveformFunction], width=10).grid(row=row, column=0, sticky=tk.W)
        row += 1
        ttk.Checkbutton(frame, text="Enable", variable=values["enable"]).grid(row=row, column=0, columnspan=2, sticky=tk.W)
        row += 1
        ttk.Label(frame, text="Trigger").grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        row += 1
        for label, key in (("secRun(0=Cont)", "sec_run"), ("secWait", "sec_wait"), ("cRepeat(0=inf)", "repeat")):
            ttk.Entry(frame, textvariable=values[key], width=12).grid(row=row, column=0)
            ttk.Label(frame, text=label).grid(row=row, column=1, sticky=tk.W)
            row += 1
        ttk.Checkbutton(frame, text="Repeat Trigger", variable=values["repeat_trigger"]).grid(row=row, column=0, columnspan=2, sticky=tk.W)
        row += 1
        ttk.Label(frame, text="TrigrSrc").grid(row=row, column=0, columnspan=2, sticky=tk.W)
        row += 1
        ttk.Entry(frame, textvariable=values["trigger_source"], width=28).grid(row=row, column=0, columnspan=2, sticky=tk.W)
        row += 1
        ttk.Label(frame, text="FM Mod").grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        row += 1
        for label, key in (
            ("Frequency (Hz)", "fm_frequency"),
            ("Amplitude (%)", "fm_amplitude"),
            ("Offset(V)", "fm_offset"),
            ("Symmetry(%)", "fm_symmetry"),
            ("Phase(Deg)", "fm_phase"),
        ):
            ttk.Entry(frame, textvariable=values[key], width=12).grid(row=row, column=0)
            ttk.Label(frame, text=label).grid(row=row, column=1, sticky=tk.W)
            row += 1
        ttk.Combobox(frame, textvariable=values["fm_function"], values=[item.value for item in WaveformFunction], width=10).grid(row=row, column=0, sticky=tk.W)
        ttk.Label(frame, text="Function 2").grid(row=row, column=1, sticky=tk.W)
        row += 1
        ttk.Checkbutton(frame, text="Enable", variable=values["fm_enable"]).grid(row=row, column=0, columnspan=2, sticky=tk.W)

    def _build_pump_valve_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=48)
        self.tabs.add(tab, text="Pump&Valve")
        ttk.Button(tab, text="Pos1", command=lambda: self._set_valve(1)).grid(row=1, column=0, pady=(0, 20))
        ttk.Label(tab, text="Valve Pos1").grid(row=0, column=0, sticky=tk.W)
        ttk.Button(tab, text="Pos2", command=lambda: self._set_valve(2)).grid(row=3, column=0)
        ttk.Label(tab, text="ValvePos2").grid(row=2, column=0, sticky=tk.W)

        ttk.Button(tab, text="Refill", command=self._refill_pump).grid(row=0, column=2, padx=20)
        ttk.Button(tab, text="Empty", command=self._empty_pump).grid(row=0, column=3, padx=5)
        ttk.Label(tab, text="These Go MAX flow!").grid(row=0, column=4, sticky=tk.W)
        ttk.Label(tab, text="Syringe").grid(row=1, column=2, sticky=tk.W, pady=(20, 0))
        ttk.Combobox(tab, textvariable=self.syringe_var, values=("BD 1ml", "BD 5ml", "BD 10ml"), width=20).grid(row=2, column=2, sticky=tk.W)
        ttk.Button(tab, text="Configure", command=self._configure_syringe).grid(row=2, column=4, sticky=tk.W)
        ttk.Label(tab, text="Flow Rate").grid(row=4, column=2, sticky=tk.W, pady=(40, 0))
        ttk.Entry(tab, textvariable=self.flow_rate_var, width=12).grid(row=5, column=2, sticky=tk.W)
        ttk.Button(tab, text="Generate", command=self._generate_flow).grid(row=5, column=4, sticky=tk.W)
        ttk.Label(tab, text="Level(ml)").grid(row=6, column=3, sticky=tk.W, pady=(40, 0))
        ttk.Entry(tab, textvariable=self.level_var, width=12).grid(row=7, column=3, sticky=tk.W)
        ttk.Button(tab, text="GO", command=self._go_to_level).grid(row=7, column=4, sticky=tk.W)
        ttk.Button(tab, text="STOP", command=self._stop_pump).grid(row=8, column=0, sticky=tk.EW, pady=(48, 0), ipady=24)
        ttk.Button(tab, text="Ref Move", command=self._reference_pump).grid(row=8, column=4, sticky=tk.W, pady=(48, 0))
        ttk.Label(tab, text="Number of flushes").grid(row=9, column=2, pady=(40, 0))
        ttk.Entry(tab, textvariable=self.flush_count_var, width=8).grid(row=10, column=2)
        ttk.Button(tab, text="Flush", command=self._flush).grid(row=10, column=4, sticky=tk.W)
        flush = ttk.LabelFrame(tab, text="Flush Settings", padding=8)
        flush.grid(row=8, column=5, rowspan=4, padx=(40, 0), sticky=tk.N)
        for row, (label, var) in enumerate((("Flush Flowrate", self.flush_flowrate_var), ("flush volume (ml)", self.flush_volume_var), ("WaitAfterFlush", self.wait_after_flush_var))):
            ttk.Label(flush, text=label).grid(row=row * 2, column=0, sticky=tk.W)
            ttk.Entry(flush, textvariable=var, width=10).grid(row=row * 2 + 1, column=0, sticky=tk.W)

    def _build_camera_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=24)
        self.tabs.add(tab, text="Camera")
        image = ttk.LabelFrame(tab, text="", padding=16)
        image.grid(row=0, column=0, columnspan=2, sticky=tk.EW)
        ttk.Button(image, text="Image", command=self._capture_snapshot).grid(row=0, column=0, padx=(0, 24))
        ttk.Checkbutton(image, text="Image Continous Off/On", variable=self.image_continuous).grid(row=0, column=1, sticky=tk.W)
        ttk.Label(image, text="If the button is grayed out,\npress the configure camera button").grid(row=0, column=2, padx=(40, 0))

        roi = ttk.LabelFrame(tab, text="ROI", padding=16)
        roi.grid(row=1, column=0, sticky=tk.NW, pady=16)
        for row, (label, var) in enumerate((("Horizontal Offset", self.roi_horizontal_offset), ("Vertical Offset", self.roi_vertical_offset), ("Horizontal Size", self.roi_horizontal_size), ("Vertical Size", self.roi_vertical_size))):
            ttk.Entry(roi, textvariable=var, width=10).grid(row=row, column=0)
            ttk.Label(roi, text=label).grid(row=row, column=1, sticky=tk.W)
        ttk.Label(roi, text="ExposureTime(ms)").grid(row=0, column=2, padx=(40, 5), sticky=tk.W)
        ttk.Entry(roi, textvariable=self.exposure_ms, width=10).grid(row=0, column=3)
        ttk.Button(roi, text="Configure", command=self._configure_camera).grid(row=0, column=4, padx=(30, 0))
        ttk.Checkbutton(roi, text="Center ROI Off/On", variable=self.center_roi_var).grid(row=2, column=2, columnspan=2, sticky=tk.W)
        ttk.Label(roi, text="476 is Vertical is max for 100 fps").grid(row=3, column=2, columnspan=3, sticky=tk.W, pady=(12, 0))

        conversion = ttk.LabelFrame(tab, text="Conversion Policy (Default)", padding=16)
        conversion.grid(row=1, column=1, sticky=tk.NW, padx=(24, 0), pady=16)
        ttk.Label(conversion, text="Conversion Method").grid(row=0, column=0, sticky=tk.W)
        ttk.Combobox(conversion, values=("Default",), width=18).grid(row=1, column=0)
        ttk.Button(conversion, text="Adjust", command=lambda: self._set_status("ImageIntensityAdjusted")).grid(row=5, column=0, pady=(40, 0))

        seq = ttk.LabelFrame(tab, text="", padding=16)
        seq.grid(row=2, column=0, sticky=tk.NW)
        ttk.Button(seq, text="Start", command=self._start_camera_sequence).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(seq, text="Trigg", command=self._camera_trigger).grid(row=2, column=0, sticky=tk.EW, ipady=20)
        ttk.Label(seq, text="Sequence path").grid(row=3, column=0, sticky=tk.W, pady=(20, 0))
        ttk.Entry(seq, textvariable=self.sequence_path, width=18).grid(row=4, column=0, sticky=tk.W)
        ttk.Button(seq, text="...", command=self._choose_sequence_path).grid(row=4, column=1)
        ttk.Button(seq, text="Save", command=self._save_camera_sequence).grid(row=6, column=0, sticky=tk.W, pady=(20, 0))

        settings = ttk.LabelFrame(seq, text="Sequence Settings", padding=8)
        settings.grid(row=0, column=2, rowspan=7, padx=(40, 0), sticky=tk.N)
        for row, (label, var) in enumerate((("Mode", self.sequence_mode), ("Source", self.sequence_source), ("Interval", self.sequence_interval), ("Burst", self.sequence_burst))):
            ttk.Entry(settings, textvariable=var, width=18).grid(row=row, column=0)
            ttk.Label(settings, text=label).grid(row=row, column=1, sticky=tk.W)
        ttk.Label(settings, text="Capture mode").grid(row=4, column=0, sticky=tk.W, pady=(12, 0))
        ttk.Combobox(settings, textvariable=self.capture_mode, values=("Snap", "Sequence"), width=16).grid(row=5, column=0)
        ttk.Label(settings, text="Frames").grid(row=6, column=0, sticky=tk.W)
        ttk.Entry(settings, textvariable=self.sequence_frames, width=10).grid(row=7, column=0, sticky=tk.W)
        ttk.Label(settings, text="Dcam Trigger Source").grid(row=8, column=0, sticky=tk.W)
        ttk.Entry(settings, textvariable=self.dcam_trigger_source, width=18).grid(row=9, column=0)
        ttk.Label(settings, text="External Options").grid(row=10, column=0, sticky=tk.W)
        ttk.Entry(settings, textvariable=self.trigger_polarity, width=14).grid(row=11, column=0, sticky=tk.W)
        ttk.Label(settings, text="Polarity").grid(row=11, column=1, sticky=tk.W)
        ttk.Entry(settings, textvariable=self.trigger_delay, width=14).grid(row=12, column=0, sticky=tk.W)
        ttk.Label(settings, text="Delay").grid(row=12, column=1, sticky=tk.W)
        ttk.Label(settings, text="ExposureTime(ms)").grid(row=13, column=0, sticky=tk.W)
        ttk.Entry(settings, textvariable=self.sequence_exposure_ms, width=10).grid(row=14, column=0, sticky=tk.W)
        ttk.Label(seq, text="Frame Index 2").grid(row=0, column=3, padx=(20, 0))
        ttk.Entry(seq, textvariable=self.frame_index_var, width=8, state="readonly").grid(row=1, column=3)
        ttk.Label(seq, text="Frame Count 2").grid(row=2, column=3, padx=(20, 0))
        ttk.Entry(seq, textvariable=self.frame_count_var, width=8, state="readonly").grid(row=3, column=3)

    def _build_experiment_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=36)
        self.tabs.add(tab, text="Experiment")
        for col, (label, var) in enumerate((("Elapsed Time", self.elapsed_time_var), ("Time Left", self.time_left_var), ("# elements in queue", self.queue_count_var))):
            ttk.Label(tab, text=label).grid(row=0, column=col, sticky=tk.W, padx=(0, 24))
            ttk.Entry(tab, textvariable=var, width=12, state="readonly").grid(row=1, column=col, sticky=tk.W, padx=(0, 24))
        ttk.Button(tab, text="Start exp", command=self._start_experiment).grid(row=3, column=0, sticky=tk.W, pady=(36, 0))
        ttk.Label(tab, text="SeriesPath 2").grid(row=4, column=0, sticky=tk.W, pady=(24, 0))
        ttk.Entry(tab, textvariable=self.series_path_var, width=70).grid(row=5, column=0, columnspan=4, sticky=tk.W)
        ttk.Button(tab, text="...", command=self._choose_series_path).grid(row=5, column=4, sticky=tk.W)

        settings = ttk.LabelFrame(tab, text="Analog Discovery Settings", padding=8)
        settings.grid(row=6, column=0, rowspan=10, sticky=tk.NW, pady=(24, 0))
        for row, (label, var) in enumerate((
            ("Camera FPS", self.experiment_camera_fps),
            ("Camera Start (s)", self.experiment_camera_start),
            ("Ch1 Frequency (Hz)", self.experiment_ch1_frequency),
            ("Ch1 AD2 source peak amplitude (V)", self.experiment_ch1_amplitude),
            ("Ch1 Start (s)", self.experiment_ch1_start),
            ("Ch1 Run (s) (0=Cont)", self.experiment_ch1_run),
            ("Ch2 Start(s)", self.experiment_ch2_start),
            ("Ch2 Run (s)(0=Cont)", self.experiment_ch2_run),
        )):
            ttk.Entry(settings, textvariable=var, width=10).grid(row=row, column=0)
            ttk.Label(settings, text=label).grid(row=row, column=1, sticky=tk.W)

        middle = ttk.Frame(tab)
        middle.grid(row=6, column=2, sticky=tk.NW, padx=(40, 0), pady=(24, 0))
        for row, (label, var) in enumerate((("Repeats", self.experiment_repeats), ("Frames", self.experiment_frames), ("ExposureTime(ms) 2", self.experiment_exposure))):
            ttk.Label(middle, text=label).grid(row=row * 2, column=0, sticky=tk.W)
            ttk.Entry(middle, textvariable=var, width=10).grid(row=row * 2 + 1, column=0, sticky=tk.W)
        flush = ttk.LabelFrame(middle, text="Flush Settings 2", padding=8)
        flush.grid(row=7, column=0, pady=(24, 0))
        for row, (label, var) in enumerate((("Flush Flowrate(uL)", self.flush_flowrate_var), ("flush volume (ml)", self.flush_volume_var), ("WaitAfterFlush", self.wait_after_flush_var))):
            ttk.Label(flush, text=label).grid(row=row * 2, column=0, sticky=tk.W)
            ttk.Entry(flush, textvariable=var, width=10).grid(row=row * 2 + 1, column=0, sticky=tk.W)

        camera_start = ttk.Frame(tab)
        camera_start.grid(row=6, column=3, sticky=tk.NW, padx=(60, 0), pady=(24, 0))
        ttk.Label(camera_start, text="Camera Start Array(s)").grid(row=0, column=0)
        for row in range(10):
            ttk.Entry(camera_start, width=10).grid(row=row + 1, column=0)
        ttk.Checkbutton(camera_start, text="GlobalExposure Off/On", variable=self.global_exposure).grid(row=1, column=1, padx=(30, 0), sticky=tk.W)
        ttk.Checkbutton(camera_start, text="Dynamic Camera Start Time Off/On", variable=self.dynamic_camera_start_time).grid(row=4, column=1, padx=(30, 0), sticky=tk.W)
        ttk.Label(tab, text="Average FPS").grid(row=12, column=4, sticky=tk.W)
        ttk.Entry(tab, textvariable=self.average_fps_var, width=10, state="readonly").grid(row=13, column=4, sticky=tk.W)
        graph = tk.Canvas(tab, width=760, height=145, background="black", highlightthickness=1, highlightbackground="#888")
        graph.grid(row=17, column=0, columnspan=5, sticky=tk.W, pady=(28, 0))
        self._draw_graph_grid(graph)

    def _draw_graph_grid(self, graph: tk.Canvas) -> None:
        for x in range(0, 761, 20):
            graph.create_line(x, 0, x, 145, fill="#004400")
        for y in range(0, 146, 20):
            graph.create_line(0, y, 760, y, fill="#004400")
        graph.create_text(380, 130, text="Frame", fill="white")
        graph.create_text(30, 15, text="Frame Interval (s)", fill="white", angle=90)

    def _initialize_system(self) -> None:
        self.app.ad2 = SimulatedAD2Sdk(enabled=self.ad2_enabled.get()) if self.ad2_enabled.get() else SimulatedAD2Sdk(enabled=False)
        self.app.camera = HamamatsuCamera(enabled=self.camera_enabled.get(), simulate=self.sim_camera.get())
        self.app.pump = CetoniPump(enabled=self.pump_enabled.get(), simulate=self.sim_pump.get(), configuration_path=Path(self.cetoni_config_path.get()))
        self.app.valve = Valve(enabled=self.valve_enabled.get(), simulate=self.sim_valve.get(), visa_resource=self.valve_resource.get())
        self.app.z_motor = PriorZMotor(enabled=self.z_stage_enabled.get(), visa_resource=self.prior_resource.get())
        self._safe_call(self.app.initialize)

    def _apply_wfg(self) -> None:
        config = self._build_wfg_config()
        self._safe_call(lambda: self.app.ad2.config_wfg(config), "WFGConfigured")

    def _build_wfg_config(self) -> WfgConfig:
        channels = []
        for values in self.wfg_channels:
            carrier = CarrierSettings(
                frequency_hz=self._float(values["frequency"].get()),
                amplitude_v=self._float(values["amplitude"].get()),
                offset_v=self._float(values["offset"].get()),
                symmetry_percent=self._float(values["symmetry"].get()),
                phase_deg=self._float(values["phase"].get()),
                function=WaveformFunction(values["function"].get()),
                enable=values["enable"].get(),
            )
            trigger = TriggerSettings(
                sec_run=self._float(values["sec_run"].get()),
                sec_wait=self._float(values["sec_wait"].get()),
                repeat_count=int(self._float(values["repeat"].get())),
                repeat_trigger=values["repeat_trigger"].get(),
                source=values["trigger_source"].get(),
            )
            fm_mod = CarrierSettings(
                frequency_hz=self._float(values["fm_frequency"].get()),
                amplitude_v=self._float(values["fm_amplitude"].get()),
                offset_v=self._float(values["fm_offset"].get()),
                symmetry_percent=self._float(values["fm_symmetry"].get()),
                phase_deg=self._float(values["fm_phase"].get()),
                function=WaveformFunction(values["fm_function"].get()),
                enable=values["fm_enable"].get(),
            )
            channels.append(WfgChannelConfig(channel_index=int(self._float(values["idx"].get())), carrier=carrier, trigger=trigger, fm_mod=fm_mod))
        return WfgConfig(running=self.wfg_running.get(), channels=channels, synchronize_state=self.wfg_sync_state.get())

    def _set_valve(self, position: int) -> None:
        self._safe_call(lambda: self.app.valve.set_position(position), f"ValvePos{position}")

    def _refill_pump(self) -> None:
        self._safe_call(self.app.pump.refill, "PumpRefilled")

    def _empty_pump(self) -> None:
        self._safe_call(self.app.pump.empty, "PumpEmptied")

    def _stop_pump(self) -> None:
        self._safe_call(self.app.pump.stop, "PumpStopped")

    def _configure_syringe(self) -> None:
        self._safe_call(lambda: self.app.pump.configure_syringe_bd({"name": self.syringe_var.get()}), "SyringeConfigured")

    def _generate_flow(self) -> None:
        self._safe_call(lambda: self.app.pump.generate_flow(self._float(self.flow_rate_var.get())), "FlowGenerated")

    def _go_to_level(self) -> None:
        self._safe_call(lambda: self.app.pump.set_fill_level(self._float(self.level_var.get())), "FillLevelSet")

    def _reference_pump(self) -> None:
        self._safe_call(self.app.pump.reference_move, "PumpReferenced")

    def _flush(self) -> None:
        settings = FlushSettings(self._float(self.flush_flowrate_var.get()), self._float(self.flush_volume_var.get()), self._float(self.wait_after_flush_var.get()))
        self._safe_call(lambda: self.app.flush(settings))

    def _configure_camera(self) -> None:
        roi = SubRegion(
            horizontal_offset=int(self._float(self.roi_horizontal_offset.get())),
            vertical_offset=int(self._float(self.roi_vertical_offset.get())),
            horizontal_size=int(self._float(self.roi_horizontal_size.get())),
            vertical_size=int(self._float(self.roi_vertical_size.get())),
        )
        self._safe_call(lambda: self.app.camera.configure_roi(roi))
        self._safe_call(lambda: self.app.camera.configure_exposure_time(self._float(self.exposure_ms.get())), "CameraConfigured")
        if self.center_roi_var.get():
            self._safe_call(self.app.camera.center_roi, "CameraConfigured")

    def _capture_snapshot(self) -> None:
        self._safe_call(self.app.camera.capture_snapshot, "SnapshotCaptured")

    def _start_camera_sequence(self) -> None:
        settings = {
            "mode": self.sequence_mode.get(),
            "source": self.sequence_source.get(),
            "interval": self._float(self.sequence_interval.get()),
            "burst": self._float(self.sequence_burst.get()),
            "capture_mode": self.capture_mode.get(),
            "frames": int(self._float(self.sequence_frames.get())),
            "dcam_trigger_source": self.dcam_trigger_source.get(),
            "polarity": self.trigger_polarity.get(),
            "delay": self._float(self.trigger_delay.get()),
            "exposure_ms": self._float(self.sequence_exposure_ms.get()),
        }
        self._safe_call(lambda: self.app.camera.configure_sequence(settings))
        self._safe_call(self.app.camera.start_capture, "CameraSequenceStarted")

    def _camera_trigger(self) -> None:
        self._safe_call(self.app.camera.sw_trigg, "CameraTriggered")

    def _save_camera_sequence(self) -> None:
        path = Path(self.sequence_path.get() or ".")
        self._safe_call(lambda: self.app.camera.save_sequence([], path), "CameraSequenceSaved")

    def _choose_sequence_path(self) -> None:
        chosen = filedialog.askdirectory()
        if chosen:
            self.sequence_path.set(chosen)

    def _choose_series_path(self) -> None:
        chosen = filedialog.askdirectory()
        if chosen:
            self.series_path_var.set(chosen)

    def _start_experiment(self) -> None:
        series_path = Path(self.series_path_var.get())
        experiment = Experiment2(
            experiment_folder=series_path / "experiment-1",
            flush_settings=FlushSettings(self._float(self.flush_flowrate_var.get()), self._float(self.flush_volume_var.get()), self._float(self.wait_after_flush_var.get())),
            global_exposure_ms=self._float(self.experiment_exposure.get()),
            sequence_settings={"frames": int(self._float(self.experiment_frames.get()))},
            wfg_config=self._experiment_wfg_dict(),
            do_clock_settings={},
        )
        self.app.experiment_series = ExperimentSeries2(series_path=series_path)
        self.app.experiment_series.enqueue_experiments([experiment])
        self.queue_count_var.set(str(self.app.experiment_series.see_elements_left()))
        self._safe_call(self.app.run_experiment2)
        self.queue_count_var.set(str(self.app.experiment_series.see_elements_left()))

    def _experiment_wfg_dict(self) -> dict[str, object]:
        return {
            "running": True,
            "channels": [
                {
                    "channel": 0,
                    "frequency": self._float(self.experiment_ch1_frequency.get()),
                    "amplitude": self._float(self.experiment_ch1_amplitude.get()),
                    "trigger": {"secWait": self._float(self.experiment_ch1_start.get()), "secRun": self._float(self.experiment_ch1_run.get())},
                },
                {
                    "channel": 1,
                    "trigger": {"secWait": self._float(self.experiment_ch2_start.get()), "secRun": self._float(self.experiment_ch2_run.get())},
                },
            ],
        }

    def _safe_call(self, callback, success_status: str | None = None) -> None:
        try:
            callback()
            if success_status:
                self.app.fire_status_event(success_status)
            self.error_status_var.set(False)
            self.error_code_var.set("0")
            self.error_source_var.set("")
        except Exception as exc:
            self.app.error_handler_event_loop(exc)
            self.error_status_var.set(True)
            self.error_code_var.set("-1")
            self.error_source_var.set(str(exc))
        self._refresh_status()

    def _set_status(self, status: str) -> None:
        self.app.fire_status_event(status)
        self._refresh_status()

    def _refresh_status(self) -> None:
        self.status_var.set(self.app.status)

    def _on_abort(self) -> None:
        self.app.fire_stop_event()
        self.app.fire_status_event("Aborted")
        self._refresh_status()

    def _on_exit(self) -> None:
        self._safe_call(self.app.cleanup)
        self.destroy()

    @staticmethod
    def _float(value: str) -> float:
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return 0.0


def main() -> None:
    MainWindow().mainloop()


if __name__ == "__main__":
    main()
