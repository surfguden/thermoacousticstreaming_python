# LabVIEW UI Field Reference

Non-destructive text transcription of the five `UI_tabs/*.png` screenshots
(the original LabVIEW `Main.vi` front panel, one image per tab). The PNGs
remain the source of visual record and are not touched, moved, or deleted by
this document -- see `docs/legacy_asset_index.md`. Purpose: make the field
labels and LabVIEW-era default values searchable as text, and surface where
a transcribed LabVIEW-era default has since drifted from this project's
current real Python default. A row is flagged **DRIFT** only when a real,
checkable current-code value was found and differs from the screenshot; a
row is left unflagged when the value still matches or no current-code
equivalent was checked.

## `UI_tabs/01-main-startup.png` -- Initialization tab

| Field | LabVIEW-era default | Current Python default | Status |
| --- | --- | --- | --- |
| Tab Control | Initialization, WFG, Pump&Valve, Camera, DOCustom, DOClock, Experiment, Zstack | same seven-tab layout (`qt_ui.py`) | match |
| Analog Discovery 3 (Off/On) | On (checked) | `ad2_enabled` defaults `True` (`qt_ui.py:757-759`) | match |
| Z stage (Off/On) | Off (unchecked, greyed) | no single equivalent toggle; current Z-stage path is the separate PPC001/Kinesis backend, not gated the same way | not directly comparable |
| Prior Visa resource name | `COM7` | **Not used at all.** Code comments explicitly call this "the legacy Prior-serial/COM7 path this used to build" (`qt_ui.py:766-770`) and "Not wired to a real backend" (`qt_ui.py:815-817`). The real Z-stage today is a Thorlabs PPC001 over Kinesis/pythonnet, serial `44533854` -- a different vendor/protocol entirely, not just a different port. | **DRIFT** -- whole hardware target replaced, not merely a superseded port number |
| Hamamatsu (Off/On) | On (checked) | `camera_enabled` defaults `True` (`qt_ui.py:773-775`) | match |
| Cetoni Pump (Off/On) | On (checked) | `pump_enabled` defaults `True` (`qt_ui.py:776-778`) | match |
| Cetoni Device Configuration Path | `C:\Users\Public\Documents\QmixElements\Projects\` | `C:\Users\Lab user\Desktop\Franzi\video paper 2\Paper 2 slow flow\Configurations\Cetoni_1pump_config_FM` (`ONE_PUMP_QMIX_CONFIG_PATH`, `hardware_config.py:8-10`, wired into the UI field at `qt_ui.py:845-848`) | **DRIFT** -- generic install-projects folder replaced by a specific named one-pump project config; expected evolution, but the literal string no longer matches |
| MX Valve 2 (Off/On) | On (checked) | `valve_enabled` defaults `True` (`qt_ui.py:779-781`) | match |
| Valve VISA resource name | `COM6` | `COM5` (`qt_ui.py:831`, comment: "Current application default; confirm physical wiring at the bench.") | **DRIFT** (previously found) |
| Simulate Camera (Off/On) | On (checked) | `sim_camera` defaults `True` (`qt_ui.py:791-793`) | match |
| Simulate Pump (Off/On) | On (checked) | `sim_pump` defaults `True` (`qt_ui.py:794-796`) | match |
| Simulate Valve (Off/On) | On (checked) | `sim_valve` defaults `True` (`qt_ui.py:797-799`) | match |
| (no TEC control exists in this LabVIEW panel) | -- | `tec_enabled` defaults `False`, `sim_tec` defaults `True` (`qt_ui.py:782-784,803-805`) | **new in Python** -- TEC has no LabVIEW-era equivalent at all, not a drifted value |
| Status | "System Not Initialized" | same startup string used | match |
| Error Out (status/code/source) | green / `0` / empty | same cluster shape reused in Python's own status/error display | match |

## `UI_tabs/02-WFG.png` -- WFG tab

| Field | LabVIEW-era default | Current Python default | Status |
| --- | --- | --- | --- |
| Running (Ch1) | On (green) | not independently checked against a Python default | not checked |
| Ch1 idxChannel | 0 | -- | not checked |
| Ch1 Frequency (Hz) | `1,9E+6` (1.9 MHz, comma-decimal LabVIEW locale) | not independently checked against a Python default | not checked |
| Ch1 Amplitude (V) | 2 | not checked | not checked |
| Ch1 Offset (V) | 0 | not checked | not checked |
| Ch1 Symmetry (%) | 50 | not checked | not checked |
| Ch1 Phase (Deg) | 0 | not checked | not checked |
| Ch1 Function | Sine | not checked | not checked |
| Ch1 Enable | Off (red) | not checked | not checked |
| Ch2 idxChannel | 1 | -- | not checked |
| Ch2 Frequency (Hz) | 1000 | not checked | not checked |
| Ch2 Amplitude (V) | 1 | not checked | not checked |
| Ch2 Offset/Symmetry/Phase/Function/Enable | 0 / 50 / 0 / Sine / Off | not checked | not checked |
| SyncronizeState | Independent | not checked | not checked |
| Trigger (Ch1 & Ch2): secRun(0=Cont) | 0 | not checked | not checked |
| Trigger: secWait | 0 | not checked | not checked |
| Trigger: cRepeat(0=inf) | 0 | not checked | not checked |
| Trigger: Repeat Trigger | Off (red) | not checked | not checked |
| Trigger: TrigrSrc | `trigrsrcNone` | `exp_ch1_trigger_source` default is `"trigsrcNone"` (`qt_ui.py:1237-1238`, Experiment-tab field, not this WFG-tab field directly) | consistent naming, not a confirmed same-field comparison |
| FM Mod (Ch1 & Ch2) Frequency (Hz) | 1000 | not checked | not checked |
| FM Mod Amplitude (%) | 1 | not checked | not checked |
| FM Mod Offset(V) / Symmetry(%) / Phase(Deg) | 0 / 50 / 0 | not checked | not checked |
| FM Mod Function 2 | Sine | not checked | not checked |
| FM Mod Enable | Off (red) | not checked | not checked |
| Error Out | green / `0` | same cluster shape reused | match |

This tab's numeric defaults were not individually cross-checked against
`qt_ui.py`'s WFG-tab spin-box constructors (a larger effort than the
other four tabs, since this project's own live WFG defaults are driven by
`experiment_presets.py` presets rather than fixed literals in most cases) --
listed here as the transcription only. A follow-up pass should check
`self.wfg_*`/`self.ch1_*`/`self.ch2_*` construction in `qt_ui.py` field by
field before treating any of these as confirmed current values.

## `UI_tabs/03-PumpValve.png` -- Pump&Valve tab

| Field | LabVIEW-era default | Current Python default | Status |
| --- | --- | --- | --- |
| Valve Pos1 / ValvePos2 buttons | labelled "Pos1" / "Pos2" | current buttons send the protocol-confirmed `P01`/`P02` commands (`qt_ui.py:2305,2308` tooltips) | consistent (button labels differ cosmetically; underlying protocol tokens match project's confirmed `P01`/`P02`) |
| Refill / Empty | buttons present, "These Go MAX flow!" label | `refill()`/`empty()` still exist; the "MAX flow" behavior is documented in `qmix_backend.py`'s flow-rate clamp comments | consistent, not independently re-verified value-for-value |
| Syringe | `BD 1ml` (dropdown default) | `self.syringe = _combo(["BD 1ml", "BD 5ml", "BD 10ml", "Custom"], "BD 1ml")` (`qt_ui.py:913`) | match on the UI dropdown's own default text. Separate note: the pump's real, currently-configured device-side syringe geometry (`nemesys.xml`'s own default, reported live as `inner_diameter_mm=5.0, volume_max≈1.18 mL`) is recorded elsewhere as `"1 ml Glass"` -- a CETONI-library name, not the same naming scheme as this UI dropdown's BD presets. Not a code drift, just two different naming conventions for a similar-sized syringe; do not conflate the two. |
| ConfigureSyringe button | "Configure" | `configure_syringe()` exists, gated behind this same explicit button per `known_open_items.md`'s documented "dropdown looks live-selected but has no real effect until Configure is clicked" trap | match (and the trap itself is already tracked as a separate open item, not new) |
| Flow Rate | `-5000` | not independently checked against a Python spin-box default | not checked |
| Generate Flow button | "Generate" | present | match |
| Level (ml) | 0 | not checked | not checked |
| Go to Level button | "GO" | present | match |
| Stop Syringe button | "STOP" | present | match |
| Number of flushes | 1 | `flush_count = _int_spin(1, minimum=1)` (`qt_ui.py:1048`) | match |
| Reference move button | "Ref Move" | present | match |
| Flush button | "Flush" | present | match |
| Flush Settings: Flush Flowrate | 0 | not checked | not checked |
| Flush Settings: flush volume (ml) | 0 | not checked | not checked |
| Flush Settings: WaitAfterFlush | 0 | not checked | not checked |
| Command / "Stop Reglo Digital" / Send Pump Command / second Flush button | all greyed/disabled in the screenshot | **no real Reglo backend exists in current Python at all** -- `hardware_tests/README.md` confirms "A Reglo pump control data class and LabVIEW port references exist, but there is no real Reglo backend comparable to the Qmix backend." | consistent -- LabVIEW already showed this control cluster disabled/inactive, and Python never implemented it either; not a regression |

## `UI_tabs/04-Camera.png` -- Camera tab

| Field | LabVIEW-era default | Current Python default | Status |
| --- | --- | --- | --- |
| Image / Image Continuous (Off/On) | On (checked) | `self.image_continuous.setChecked(False)` (`qt_ui.py:1079-1080`, also reset to `False` at two other call sites) | **DRIFT** -- LabVIEW defaulted this On, current Python defaults it Off |
| Hint: "If the button is grayed out, press the configure camera button" | present | not independently checked whether an equivalent hint string still exists | not checked |
| ROI Horizontal Offset | 0 | `roi_h_offset = _int_spin(0, minimum=0)` (`qt_ui.py:1050`) | match |
| ROI Vertical Offset | 900 | `roi_v_offset = _int_spin(792, minimum=0)` (`qt_ui.py:1051`) | **drift, but deliberate/resolved** -- see note below |
| ROI Horizontal Size | 2304 | `roi_h_size = _int_spin(2304, minimum=0)` (`qt_ui.py:1061`) | match |
| ROI Vertical Size | 500 | `roi_v_size = _int_spin(740, minimum=0)` (`qt_ui.py:1062`) | **drift, but deliberate/resolved** -- see note below |
| ExposureTime (ms) | 50 | `exposure_ms = _spin(40.0, decimals=3, minimum=0.0)` (`qt_ui.py:1064`) | **drift, but deliberate/resolved** -- see note below |
| Configure Camera button | "Configure" | present | match |
| Center ROI (Off/On) | On (checked) | `self.center_roi.setChecked(True)` (`qt_ui.py:1072-1074`) | match |
| Static hint: "476 is Vertical is max for 100 fps" | present | **explicitly removed.** Code comment: "Removed (Session 36): a static '476 is Vertical is max for 100 fps'..." (`qt_ui.py:2593`) -- this was found and documented as hardcoded LabVIEW-screenshot text never wired to a real computation (`claude_code_change_log.md` Session-36-area entry) | **DRIFT (deliberate removal)** -- confirmed via code comment and prior session's own finding, not new here |
| Conversion Policy: Conversion Method | Default | not checked | not checked |
| Conversion Policy: Minimum/Maximum Value, # Shifts | 0 / 0 / 0 | not checked | not checked |
| Adjust Intensity in image button | "Adjust" | present | match |
| StartSequence button | "Start" | present | match |
| Trigg button | "Trigg" | present | match |
| Sequence path | empty | not checked | not checked |
| SaveSequence button | "Save" | present | match |
| Master Pulse Settings: Mode | Continuous | not checked | not checked |
| Master Pulse Settings: Source | External | `self.sequence_source = _combo(["External", "Software"], "External")` (`qt_ui.py:1116`) | match (same "External" default), though this is the AD2 master-pulse trigger source, a different field from "Dcam Trigger Source" below -- do not conflate the two |
| Master Pulse Settings: Interval / Burst | 1 / 0 | not checked | not checked |
| Capture mode | Snap | not checked | not checked |
| Frames | 0 | not checked | not checked |
| Dcam Trigger Source | Internal | `self.dcam_source = _combo([...], "Internal")` (`qt_ui.py:1143-1144`) -- deliberately hardcoded, per comment, "to remove undefined leftover-state risk" | match |
| External Options: Polarity | Negative | not checked | not checked |
| External Options: Delay | 0 | not checked | not checked |
| ExposureTime (ms) [sequence block] | 0 | `sequence_exposure_ms = _spin(0.0, ...)` (`qt_ui.py:1175`) | match |
| Frame Index 2 / Frame Count 2 | 0 / 0 | not checked | not checked |

**The ROI/exposure block's apparent discrepancy is resolved, not open.**
`qt_ui.py:1052-1060`'s tooltip says these defaults "follow the retained
LabVIEW screenshot candidate (vertical_offset=792, vertical_size=740,
exposure=40.0ms...)" -- confusingly worded, since the values actually
visible in `UI_tabs/04-Camera.png` are `900`/`500`/`50.0ms`. Traced via
`git log -S"roi_v_offset = _int_spin(792"`: the live UI default was
originally `900`/`500`/`50.0` (matching this screenshot exactly) and was
deliberately changed to `792`/`740`/`40.0` in commit `17f24dd`. That
commit's replacement values are not arbitrary -- `docs/current_workflow_audit.md`
("Historically Reported Hardware Milestones") records "LabVIEW camera
preset passed with exposure `40 ms`, ROI ... `vertical_offset=792` ...
`vertical_size=740`" as a separately real-hardware-verified configuration.
So this is a confirmed, deliberate, git-recorded supersession -- the raw
front-panel screenshot default was intentionally replaced by a
hardware-tested "LabVIEW camera preset" value once that testing existed,
not an accidental drift. The tooltip's own wording ("LabVIEW screenshot
candidate") is the only remaining loose end: it should really say
"hardware-validated LabVIEW camera preset," not "screenshot candidate,"
since those are two different retained values and only the latter was
kept.

## `UI_tabs/05-Experiment.png` -- Experiment tab

| Field | LabVIEW-era default | Current Python default | Status |
| --- | --- | --- | --- |
| Elapsed Time / Time Left | `00:00:00` / `00:00:00` | not checked (runtime display fields, not meaningfully "defaulted") | not applicable |
| # elements in queue | 0 | not checked | not applicable |
| Start Experiment series button | "Start exp" | present | match |
| SeriesPath 2 | `C:\test\firstrunpulsed` | `self.series_path = QLineEdit(r"C:\test\firstrunpulsed")` (`qt_ui.py:1185`) | **exact match** -- deliberately preserved placeholder path |
| Camera FPS | 0 | not checked | not checked |
| Camera Start (s) | 0 | not checked | not checked |
| Ch1 Frequency (Hz) | 0 | not checked | not checked |
| Ch1.Carrier.Amplitude (V) | 0 | not checked | not checked |
| Ch1 Start (s) | 0 | not checked | not checked |
| Ch1 Run (s) (0=Cont) | 0 | not checked | not checked |
| Ch2 Start (s) / Ch2 Run (s) (0=Cont) | 0 / 0 | not checked | not checked |
| Repeats | 1 | not checked | not checked |
| Frames | 1 | not checked | not checked |
| ExposureTime(ms) 2 | 0 | `exp_exposure_ms = _spin(0.0, decimals=3, minimum=0.0)` (`qt_ui.py:1365`) | match |
| Camera Start Array(s) | ten `0` entries | not checked | not checked |
| GlobalExposure (Off/On) | Off (unchecked) | `self.global_exposure = QCheckBox("Off/On")` with no explicit `setChecked()` call (`qt_ui.py:1402`), so it defaults to Qt's own unchecked state | match |
| Dyamic Camera Start Time (Off/On) | Off (unchecked) | not checked | not checked |
| Flush Settings 2: Flush Flowrate(uL) / flush volume(ml) / WaitAfterFlush | 0 / 0 / 0 | not checked | not checked |
| Average FPS | 0 | not checked (runtime display field) | not applicable |
| Waveform Graph | empty, `Frame Interval(s)` vs `Frame` axes, -10..10 / 0..100 | not checked (runtime display) | not applicable |

## Summary of confirmed drift

Three classes of finding, in order of how much they matter:

1. **Hardware target genuinely replaced, not just a stale value:** Z-stage
   Prior/COM7 -> Thorlabs PPC001/Kinesis (Initialization tab).
2. **A real current default no longer matches the LabVIEW-era one:** valve
   `COM6` -> `COM5`; Cetoni config path (generic QmixElements folder ->
   specific one-pump project path); Image Continuous default `On` -> `Off`.
   Not in this bucket, despite looking like it at first: camera ROI
   vertical offset `900` -> `792`, ROI vertical size `500` -> `740`, and
   exposure `50ms` -> `40ms` -- traced to commit `17f24dd`, a deliberate
   replacement with a separately real-hardware-validated "LabVIEW camera
   preset" (`docs/current_workflow_audit.md`), not unexplained drift.
3. **A deliberate, already-documented removal, re-confirmed here:** the
   static "476 is Vertical is max for 100 fps" hint text, removed in
   Session 36 because it was hardcoded and never wired to a real
   computation.

None of these are being changed by this document -- this is a read/report
pass only, per the file/structure audit's original scope.
