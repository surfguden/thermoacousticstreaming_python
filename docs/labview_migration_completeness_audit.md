# LabVIEW Migration Completeness Audit

This is a read-only migration audit. It does not authorize hardware testing or
new hardware actions.

## Document Status

This audit is historical and point-in-time. It remains useful for the
LabVIEW-to-Python reasoning trail, but several gaps it identified were later
implemented in the current working tree. Current code now includes the AD2
DO-clock/DIO1 LED timing derivation, an AD2 completion wait that includes the
DO term, LabVIEW-style `data.tdms` metadata writing, corrected valve command
strings, and a combined fill-level/flow-rate pump call in `flush()`. Treat
the tables below as an audit trail plus remaining-gap list, not as a live-state
substitute for current source inspection and `docs/claude_code_change_log.md`.
The live conservative holding list for unresolved or legacy items is
`docs/known_open_items.md`; `docs/legacy_unresolved_items.md` is the focused
high-risk safety summary.

**Evidence boundary:** references below to a passing smoke test or hardware
milestone are retained historical records, not an independent rerun in this
audit. They support migration investigation but do not authorize real hardware.

## Executive Summary

The current Python program is structurally migrated from the exported LabVIEW
project: `port_status.json` reports 305 documented VI sections and 305 Python
implementations. The active Python workflow also preserves the broad LabVIEW
experiment shape: initialize instruments, configure AD2, configure camera,
start capture, trigger, read frames, optionally flush, save, and clean up.

However, the full working LabVIEW experiment is not yet proven completely and
equivalently migrated. The camera path is strongly validated, low-risk AD2
output is validated, and later sessions filled several migration gaps
identified by this audit. Remaining equivalence/risk areas still include AD2
trigger timing against the physical setup, DO Custom relevance, CH2/index 1
purpose, real Qmix pump behavior, valve status-handshake confidence, flush
behavior with real pump/valve, the obsolete Prior COM7 Z-stage path, and exact
TDMS/metadata parity with LabVIEW.

Recommendation: do not proceed directly to full LabVIEW acoustic output. A
short AD2-only acoustic candidate can be considered only after confirming the
AD2 WFG start timing relative to `pc_trigger()`, or while keeping the existing
explicit confirmation plus `--acknowledge-timing-uncertain` interlock.

## Sources Inspected

- `labview_manifest.json`
- `port_status.json`
- `main_html/` and `UI_tabs/` image exports
- `docs/`
- `README.md`
- `src/thermo_acoustic/application.py`
- `src/thermo_acoustic/workflows.py`
- `src/thermo_acoustic/qt_ui.py`
- `src/thermo_acoustic/ad2.py`
- `src/thermo_acoustic/instruments.py`
- `src/thermo_acoustic/qmix_backend.py`
- `src/thermo_acoustic/hamamatsu_dcam.py`
- `src/thermo_acoustic/hardware_factory.py`
- `tests/test_application.py`
- `tests/test_full_flow_dry_run.py`
- `docs/current_workflow_audit.md`
- `hardware_tests/`

Note: `main_html/` and `UI_tabs/` are exported PNG/front-panel artifacts rather
than textual LabVIEW source. The reconstruction below therefore relies on the
manifest/status VI names, exported image inventories, current Python code,
tests, prior audit notes, and validated hardware milestones.

## A. Reconstructed LabVIEW Full Experiment Flow

Most likely original flow:

1. Main UI/event loop starts and builds application state.
2. Initialization creates queues/events and selected hardware objects.
3. AD2 is opened through `AD2_SDK_Init` / `OpenAndUseFirstDevice`.
4. Hamamatsu camera is initialized/opened.
5. Qmix/Cetoni pump is initialized if enabled.
6. Valve serial resource is initialized if enabled.
7. The original LabVIEW flow initialized a Prior Z motor serial resource when
   enabled. This is historical reference only; it is not the current Python
   factory path for the PPC001 hardware.
8. Experiment series is created/enqueued.
9. `RunExperiment2` dequeues one experiment.
10. Experiment folder/TDMS/settings are created or saved.
11. AD2 WFG is configured from experiment settings.
12. AD2 DO Custom and/or DO Clock special settings are available in the
    LabVIEW export and may be configured in some versions.
13. Camera exposure and sequence settings are configured.
14. Camera capture is started.
15. AD2 PC trigger is fired.
16. Camera image sequence is read.
17. Camera capture is stopped.
18. Abort state is checked.
19. Flush may run: valve position 1, wait, pump fill-level/flow, wait for pump,
    valve position 2, wait after flush, update fill level.
20. Image sequence and camera/settings metadata are saved.
21. Experiment cleanup runs.
22. Application cleanup closes camera, pump, valve, Z motor, and AD2.

Separate LabVIEW-side capabilities also existed:

- Camera snapshot, ROI, center ROI, software trigger, buffer size, readout time.
- AD2 WFG carrier/trigger/FM/dynamic configuration, start/stop, readback.
- AD2 DO custom pattern and DO clock special configuration.
- AD2 MSO/analog-in functions.
- Pump refill, empty, stop, generate flow, set fill level, syringe config, flow
  unit config, reference move, status readback.
- Valve position 1 and position 2.
- Prior Z read position, zero position, go to absolute position, read movement.

## B. Python Migration Coverage

The table classifies status in the current Python program, not just the raw
`port_status.json` implementation flag.

| LabVIEW VI/class area | Python mapping | Status |
| --- | --- | --- |
| `Main.vi` | `qt_ui.py`, `main.py`, event/action methods | Migrated and active |
| `Application_Init`, queues, events, status | `Application.initialize()`, queue/event helpers | Migrated and active |
| `Application_RunExperiment2` | `Application.run_experiment2()` | Migrated and active |
| `Application_CleanUp` | `Application.cleanup()` | Migrated and active |
| `ExperimentSeries2` queue operations | `ExperimentSeries2` dataclass methods | Migrated and active |
| `Experiment2` settings/folder/save hooks | `Experiment2` dataclass methods | Migrated and active for `data.tdms`; exact LabVIEW parity still not fully proven |
| Hamamatsu init/open/exposure/ROI/sequence/capture/save | `HamamatsuCamera`, `HamamatsuDcamBackend` | Migrated and active |
| Hamamatsu software trigger/snapshot/readout/buffer helpers | Camera facade/backend methods | Migrated, some paths not central to current experiment |
| AD2 init/open/cleanup/PC trigger | `AD2Sdk`, `WaveFormsBackend` | Migrated and active |
| AD2 WFG config/start/stop/readback helpers | `AD2Sdk`, `WfgConfig`, `WaveFormsBackend.configure_wfg()` | Migrated and active, timing uncertain |
| AD2 DO Custom | `DoConfig`, `config_do_custom()`, `configure_do()` | Migrated but legacy/nonessential unless separately justified |
| AD2 DO Clock Special | `config_do_clock_special()`, `configure_do()` | Migrated and active for DIO1 LED timing; still safety-gated |
| AD2 MSO | `capture_scope*()` and Qt MSO tab | Migrated, outside canonical experiment path |
| Cetoni/Qmix pump init | `CetoniPump`, `QmixPumpBackend.initialize()` | Migrated but unsafe with current main workflow |
| Pump flow/fill/refill/empty/reference/status | `CetoniPump` and `QmixPumpBackend` methods | Migrated but gated/unsafe until validated |
| Valve init/position/cleanup | `Valve`, `SerialTextCommandBackend` | Migrated with `P01`/`P02`; COM5 status-query handshake is confirmed, fluidic position meaning remains unresolved |
| Application flush | `Application.flush()` | Migrated but gated; unsafe with real pump/valve |
| Prior Z motor | `PriorZMotor` | Migrated but obsolete for current hardware |
| Z-stack | `Application.z_stack()` | Migrated but unsafe/obsolete with current Z hardware |
| Thorlabs/APT Z discovery | `thorlabs_apt.py` | New Python discovery-only support, not LabVIEW equivalent |
| PPC001 manual Z-scan calibration | `thorlabs_piezo.py`, `piezo_zscan.py`, Qt Z-Scan tab | New Python manual PPC001/Kinesis calibration-motion feature. It requires a dedicated motion authorization, is outside LabVIEW `RunExperiment2` equivalence, and is distinct from passive APT discovery. |
| TEC temperature-series scaffold | `tec.py`, `TemperatureSeries`, Qt TEC controls | New Python scaffold; not proven LabVIEW-equivalent and real MeCom mapping remains unresolved |

## C. Semantic Equivalence Assessment

| Area | Equivalence assessment |
| --- | --- |
| Initialization order | Broadly equivalent for AD2, camera, pump, and valve. Current Python uses a `ZStage`/PPC001 adapter rather than the historical Prior serial path. Risk: if real pump is enabled, Qmix initialization is active and enabling, not passive. |
| Hardware construction | Moved to `hardware_factory.py` with same prior semantics. Equivalent to current Python behavior, but not proof of LabVIEW equivalence. |
| Camera exposure/ROI | Strongly equivalent for validated LabVIEW preset values: exposure `40 ms`, ROI `0,792,2304,740`, up to `1000` frames passed. |
| Camera sequence lifecycle | Current Python order is configure sequence, allocate DCAM buffer before capture, start capture, read frames, stop capture. Validated after DCAM lifecycle fix. |
| Camera trigger source | Camera-only smoke uses internal trigger. Full LabVIEW screenshot references sequence source/external concepts, so trigger-source equivalence for acoustic workflow is not fully proven. |
| AD2 WFG call order | Python configures WFG before camera capture and PC trigger. It calls `FDwfAnalogOutConfigure(..., running)` during WFG config. With `trigsrcNone`, output may start at config time rather than PC trigger. Not proven equivalent. |
| AD2 PC trigger | Present in `Application.run_experiment2()` immediately after `camera.start_capture()`. Semantics depend on WFG trigger source; uncertain for `trigsrcNone`. |
| AD2 CH1/CH2 mapping | Python UI has two WFG channels. LabVIEW screenshot candidate has CH0 at `1.975 MHz`, `2 V` and CH1/index 1 at `1000 Hz`, `1 V`; CH2 purpose is unknown. Current staged acoustic mode is CH0-only. |
| DO Custom / DO Clock | DO Clock Special is now active in the experiment path for DIO1 LED timing; DO Custom remains legacy/nonessential unless separately justified. |
| Pump/Qmix init | Python backend opens bus, starts communication, refuses a pre-existing fault without clearing it, then enables pump and configures units. This is active behavior and may differ from the exact LabVIEW operational state. It is not safe as passive main-workflow init. |
| Pump flow | Python has refill/empty/generate flow/set fill level/reference. Not validated for current one-pump hardware beyond discovery/readback. |
| Flush order | Python now uses the LabVIEW-style combined `set_fill_level(level, flow_rate)` call for the first pump move, then waits, switches valve, waits, and updates the final fill level. Real semantics remain hardware-sensitive. |
| Valve commands | Python opens COM5 and writes `P01`/`P02` with CR termination through `SerialTextCommandBackend`. The `S` status-query handshake is hardware-confirmed; the physical fluidic meaning of positions 1/2 remains unresolved. |
| Z-stage | Prior COM7 implementation maps LabVIEW Prior VIs, but current hardware is a Thorlabs/PPC001 piezo controller using Kinesis. The migrated Prior path is not equivalent to current hardware. A separate manually authorized PPC001 Z-Scan calibration path exists in Python, but it is not part of the canonical `RunExperiment2` workflow or the passive APT discovery path. |
| TEC | New Python scaffold only: one target per experiment group, disabled/simulated by default. There is no confirmed LabVIEW-equivalence claim and no reviewed real MeCom register mapping in this repo. |
| Save/metadata | Python saves TIFF frames and writes `data.tdms` with experiment/camera/image metadata. Exact field-by-field LabVIEW parity still requires review against real LabVIEW output files. |
| Cleanup order | Python cleanup order is camera, pump, valve, Z motor, AD2. LabVIEW cleanup included these classes. Equivalence is broad, but pump cleanup calls stop and Qmix bus stop/close if real. |

## D. Current Canonical Active Workflow vs Original LabVIEW

| LabVIEW step | Python step | Active in current Python workflow? | Validated? | Risk | Comment |
| --- | --- | --- | --- | --- | --- |
| Main initialize | `MainWindow._start_initialize()` | Yes | Sim/fake tested | Medium | Real pump init remains dangerous if enabled. |
| Build selected hardware | `build_hardware_bundle()` | Yes | Unit tested | Medium | Preserves Python behavior; not all real paths validated. |
| Application init | `Application.initialize()` | Yes | Fake tested | Medium | Calls all enabled instrument initializers. |
| AD2 open | `AD2Sdk.initialize()` | Yes if enabled | AD2 open-close passed | Low/medium | Safe only in open-close or gated paths. |
| Camera open | `HamamatsuCamera.initialize()` | Yes if enabled | Passed | Low | Real camera validated. |
| Pump init | `CetoniPump.initialize()` | Yes if enabled | Discovery only outside main workflow | High | Qmix backend starts bus and enables pump. |
| Valve init | `Valve.initialize()` | Yes if enabled | COM5 status-query handshake passed | High | Position 1/2 fluidic mapping unresolved. |
| PPC001 Z init | `ZStage.initialize()` -> `PiezoStage.connect()` | Yes if enabled | Manual/Z-scan path only | High | Kinesis connection only; ClosedLoop is not motion authorization, and this is not canonical experiment motion. |
| Dequeue experiment | `ExperimentSeries2.dequeue_experiment()` | Yes | Unit/fake tested | Low | Structural match. |
| Create folder/TDMS | `create_folder_and_tdms()` | Yes | Unit/fake tested | Medium | Creates `data.tdms`; exact LabVIEW parity still needs review. |
| Save settings | `save_settings()` | Yes | Unit/fake tested | Medium | Writes `data.tdms`; exact LabVIEW parity still needs review. |
| Configure WFG | `ad2.config_wfg()` | Yes | Low-risk output passed | High for acoustic | Start timing uncertain. |
| Configure DO custom | `ad2.config_do_custom()` | Not in canonical run | Not validated | High | Migrated but not active. |
| Configure DO clock special | `ad2.config_do_clock_special()` | Yes | Fake tested only | Medium/high | DIO1 LED timing derived from Camera FPS / Camera Start / Frames. |
| Configure camera exposure | `camera.configure()` | Yes | Passed | Low | Wrapper stores exposure; backend sequence can set exposure. |
| Configure camera sequence | `camera.configure_sequence()` | Yes | Passed | Low/medium | Trigger-source equivalence still needs acoustic workflow check. |
| Start camera capture | `camera.start_capture()` | Yes | Passed | Low | DCAM buffer lifecycle fixed. |
| Fire PC trigger | `ad2.pc_trigger()` | Yes | Fake/low-risk indirectly | Medium/high | Depends on AD2 trigger source. |
| Read sequence | `camera.image_sequence()` | Yes | Passed | Low | 1000-frame ROI run passed. |
| Stop capture | `camera.stop_capture()` | Yes | Passed | Low | Cleanup path exists. |
| Flush | `if experiment.flush_enabled: flush()` | Gated, default false | Fake tested | High | Real pump/valve not validated. |
| Save sequence | `camera.save_sequence()` | Yes | Passed for TIFF | Medium | Downstream metadata parity unknown. |
| Save image/settings metadata | `save_image_data()`, `save_camera_settings()` | Yes | Fake/unit only | Medium | Writes `data.tdms`; exact LabVIEW parity still needs review. |
| Experiment cleanup | `experiment.cleanup()` | Yes | Fake/unit | Low/medium | Placeholder. |
| Application cleanup | `Application.cleanup()` | Yes | Fake/unit plus standalone smokes | Medium | Real pump/valve/Z cleanup not fully validated. |

## E. Missing or Uncertain Migration Items

Priority items:

1. AD2 timing and trigger semantics.
   - Python configures WFG before camera capture/PC trigger.
   - `WaveFormsBackend.configure_wfg()` calls `FDwfAnalogOutConfigure` with
     `config.running`.
   - If trigger source is `trigsrcNone`, output may begin during `config_wfg()`
     rather than at `pc_trigger()`.

2. DO clock/custom relevance.
   - DO Clock Special is now implemented as the DIO1 LED timing path.
   - DO Custom remains legacy/nonessential unless proven required.
   - **Caveat (do not conflate these two facts, Session 43):** "implemented
     as the DIO1 LED timing path" means `config_do_clock_special()` is
     called with a real, UI-populated `DoConfig` (already true before
     this session) -- it does **not** mean DIO0/DIO1 relative timing has
     been checked against the physical setup. That remains unverified
     against an oscilloscope and is a separate, still-open item.

3. CH2/index 1 purpose.
   - LabVIEW screenshot candidate includes index 1 at `1000 Hz`, `1 V`.
   - Its role in the working experiment is unknown.
   - Current staged acoustic mode correctly keeps CH2/index 1 disabled.

4. Pump/Qmix initialization and enable semantics.
   - Python real Qmix init opens bus, starts communication, refuses an existing
     fault without clearing it, and otherwise enables the pump.
   - That is not passive and is not yet safe for main workflow initialization.
   - Current hardware uses one pump and the current one-pump QmixElements config.

5. Valve COM/position mapping.
   - Resolved: Python's default is now COM5, confirmed against real hardware
     (the valve responds correctly to the documented status-query protocol on
     COM5, not the previously-documented COM6 -- corroborated by an earlier
     session too, so this was a standing documentation error, not a transient
     reassignment). This also matches the LabVIEW screenshot candidate this
     entry originally flagged, which named COM5, not COM6.
   - Position 1/2 fluidic meaning is unresolved.

6. Flush semantics.
   - Python sequence matches the apparent LabVIEW structure, but real pump/valve
     behavior is unvalidated.
   - `flush_enabled=False` is the correct default.

7. Z-stage replacement issue.
   - LabVIEW/Python Prior COM7 migration exists.
   - Current hardware is Thorlabs/PPC001 USB, serial `44533854`.
   - Manual PPC001 Z-scan calibration exists in Python as a separate Kinesis
     GUI/CLI path. It requires explicit motion authorization even when already
     ClosedLoop, and is not a LabVIEW `RunExperiment2` replacement or passive
     discovery helper.
   - Future canonical experiment motion work still needs a deliberate design
     decision; do not route it through obsolete Prior COM7.

8. Save/metadata equivalence.
   - TIFF frame saving works.
   - Full LabVIEW TDMS/settings/image metadata parity is not proven.

## F. Recommendation

1. Is Python close enough to LabVIEW to proceed with acoustic short testing?
   - Close enough for a gated AD2-only short acoustic smoke only if the operator
     accepts that AD2 timing is not fully confirmed.
   - Not close enough for full 60 s LabVIEW acoustic output or combined camera
     plus full acoustic output.

2. Verify first.
   - Confirm whether `config_wfg()` starts output immediately for
     `trigsrcNone`, or whether output waits for `pc_trigger()`.
   - Confirm whether the LabVIEW working condition used `trigsrcNone` or PC
     trigger for the acoustic channel in the actual run.
   - Confirm whether CH2/index 1 and DO clock/custom were physically connected
     or required.

3. Mark legacy/hide later.
   - Prior COM7 Z-stage.
   - DO Custom / DO Clock UI actions unless proven required.
   - Old two-pump Qmix assumptions.
   - Reglo pump fragments unless a real Reglo path is needed again.

4. Promote to explicit presets.
   - LabVIEW camera preset: exposure `40 ms`, ROI `0,792,2304,740`, frames
     `1000`.
   - AD2 LabVIEW acoustic candidate: CH0, `1.975 MHz`, `2 V`, `0 V`, sine,
     original `60 s`, candidate-only until timing is proven.
   - AD2 low-risk smoke preset: CH0, `1000 Hz`, `0.1 V`, `0 V`, `0.5 s`.
   - Current one-pump Qmix config path.
   - Current Thorlabs/PPC001 discovery identity: serial `44533854`.

5. Safety-gate workflow steps.
   - AD2 LabVIEW acoustic short: require hardware confirmation and timing
     uncertainty acknowledgement.
   - Full LabVIEW acoustic: separate gate, blocked until timing verified.
   - Pump/Qmix real initialization: separate gate, one-pump config only.
   - Pump flow and flush: separate gate with low-volume/low-flow limits.
   - Valve switching: separate gate after COM and position mapping.
   - PPC001 motion in the canonical experiment workflow: separate gate after
     API, movement-size, and scientific-sequence review. The existing Z-Scan tab
     is a manual calibration feature, not automatic experiment Z motion.

## Bottom Line

The migration is broad and structurally complete, and later sessions filled
several gaps this audit originally identified. The full working LabVIEW
experiment is still not completely proven semantically equivalent in Python.
Before treating Python as a drop-in LabVIEW replacement, keep verifying AD2
timing, DIO/LED alignment, pump/valve behavior, Qmix behavior, and TDMS
metadata parity against the real instrument setup and real LabVIEW output.
