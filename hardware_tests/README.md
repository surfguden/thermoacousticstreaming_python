# Hardware Debugging Plan

This folder contains hardware debugging scripts isolated from the main
experiment program. They are manual tools, not normal pytest coverage:
`pyproject.toml` collects only `tests/`.

## Safety Rules

- Hardware tests must default to discovery, read-only status checks, or
  simulation.
- Any script that can enable an output, move a stage, move liquid, open a
  valve, trigger a camera, or start acoustic drive must require explicit
  operator confirmation.
- Output tests must use conservative values and must not reuse persisted UI
  settings unless the operator explicitly requests that.
- Cleanup must stop or disable the affected device before exit, including in
  exception paths.
- Tests should not modify `src/`, `tests/`, `tools/`, `UI_tabs/`,
  `dcamsdk4/`, or `qmix_sdk_for_codex/` without later approval.

## Devices Referenced by Current Code and Manual Tools

This section records code paths and local operator notes, not an independent
inventory of currently connected hardware. Confirm the physical device model,
ports, wiring, and routing before an action-capable probe.

- Digilent Analog Discovery-family hardware through the WaveForms SDK. The
  exact connected model must be confirmed at the bench; legacy text uses both
  AD2 and AD3 names.
  The code covers wavegen, digital output, analog-in/MSO capture, device
  enumeration, PC trigger, reset, and close-all behavior.
- Hamamatsu camera through the DCAM SDK Python wrapper.
- Cetoni/Qmix pump through the Qmix SDK Python wrapper and QmixElements project
  configuration.
- Rheodyne/MX valve through serial text commands over a COM-style resource.
- The current code's manual Z-scan path uses a Thorlabs PPC001/PFM450(E)
  precision-piezo backend.
  It uses the Kinesis USB API, not a generic serial-device backend. The old
  Prior COM7 implementation is retained only as migration history and is not
  the current hardware path.
- A Reglo pump control data class and LabVIEW port references exist, but there
  is no real Reglo backend comparable to the Qmix backend in the current Python
  source.

No direct Python control path was found for a laser, high-voltage amplifier,
heater, or NI-DAQmx device. The PPC001 precision-piezo path is a separate
manual Z-Scan/calibration feature, not a canonical experiment actuator path.
Acoustic drive appears to be represented indirectly through the AD2
wavegen/digital-output paths.

## Hardware-Related Files

- `src/thermo_acoustic/instruments.py`: instrument facades, simulators, serial
  backend, AD2 facade, camera facade, Qmix pump facade, valve, and the current
  PPC001 `ZStage` adapter.
- `src/thermo_acoustic/waveforms.py`: Digilent WaveForms `ctypes` backend using
  `dwf.dll`.
- `src/thermo_acoustic/hamamatsu_dcam.py`: Hamamatsu DCAM backend.
- `src/thermo_acoustic/qmix_backend.py`: Cetoni/Qmix pump backend.
- `src/thermo_acoustic/serial_config.py`: LabVIEW-style serial/VISA config
  data structure.
- `src/thermo_acoustic/application.py`: orchestration of initialize, cleanup,
  flush, Z-stack, and experiment sequence.
- `src/thermo_acoustic/qt_ui.py`: UI defaults, simulate toggles, COM resource
  fields, Qmix config path, WFG/MSO settings, camera settings, and experiment
  settings.
- `src/thermo_acoustic/ad2.py`: AD2 configuration data classes for WFG, DO,
  trigger, carrier, and MSO settings.
- `src/thermo_acoustic/camera.py`: camera ROI data structures.
- `src/thermo_acoustic/imaq.py`: retained LabVIEW-parity image helper reference;
  it is not the production DCAM/PIL camera path.
- `tools/release_ad2.py`: WaveForms device enumeration and close-all utility.
- `tools/capture_ad2_wavegen_scope.py` and
  `tools/capture_ad2_wavegen_scope_matplotlib.py`: existing AD2 output/capture
  diagnostics. These actively enable wavegen and should not be used as
  first-contact tests.
- `tools/legacy_hamamatsu_camera_probe.py`: legacy manual camera open/configure/
  snapshot diagnostic; it captures and writes a TIFF without an operator
  confirmation gate.
- `tools/legacy_qmix_pump_probe.py`: legacy manual Qmix diagnostic; initialization can
  enable the pump and its optional flow argument can move it. It has no
  confirmation gate.

The four legacy `tools/` diagnostics above are marked `__test__ = False` and
live outside `testpaths = ["tests"]`; prefer the gated scripts in
`hardware_tests/` instead.
- `README.md`, `docs/current_workflow_audit.md`, and
  `docs/known_open_items.md`: current operator-facing status and safety notes.
  `docs/HANDOVER.md` and `docs/PORTING_TBD.md` are historical/reference
  material, not current validation status.
- `labview_manifest.json`, `port_status.json`, and `main_html/`: LabVIEW export
  registry and hardware-related VI references.
- `.thermo_acoustic_ui.json`: local persisted UI state. This may contain useful
  clues but should be treated as stale or bench-specific.

## Packages, SDKs, Resources, and Config

- Core Python packages declared in `pyproject.toml`: `PySide6`, `Pillow`,
  `pyserial`, `npTDMS`, `numpy`, `pythonnet`, and the pinned `pyMeCom` git
  dependency. Vendor SDK installations remain separate from these Python
  dependencies.
- Digilent WaveForms SDK: loaded with `ctypes` from `dwf.dll`. Candidate paths
  include `C:\Windows\System32\dwf.dll`,
  `C:\Windows\SysWOW64\dwf.dll`,
  `C:\Program Files\Digilent\WaveFormsSDK\lib\x64\dwf.dll`, and
  `C:\Program Files (x86)\Digilent\WaveFormsSDK\lib\x86\dwf.dll`.
- Hamamatsu DCAM SDK: wrapper path `dcamsdk4/samples/python`; loads
  `dcamapi.dll` on Windows.
- Qmix/Cetoni SDK: wrapper path `qmix_sdk_for_codex/python`; loads DLLs such as
  `labbCAN_Bus_API.dll` and `labbCAN_Pump_API.dll`. The loader uses the
  `QMIXSDK` environment variable if set, otherwise derives a local path.
- Qmix configuration path default:
  `C:\Users\Lab user\Desktop\Franzi\video paper 2\Paper 2 slow flow\Configurations\Cetoni_1pump_config_FM`.
- Serial resources: the app default for the valve is `COM5`; physical wiring
  and the fluidic route must still be confirmed at the bench. Prior `COM7` is
  legacy only and is not used for the PPC001 path.
- Serial defaults for the current valve backend: 19200 baud, 8 data bits, no
  parity, 1 stop bit, no flow control, 1 s read timeout, 5 s write timeout,
  and bare carriage-return (`\r`) command termination.
- DCAM camera device index default: `0`.
- AD2 MSO defaults include CH1/CH2 enabled, trigger source `trigsrcNone`,
  10 kS/s, 4096 samples, 1 V range, and 0 V offset.
- No NI-DAQmx package, VISA package, or explicit NI-DAQmx physical channels
  were found in the Python code.

## Recommended First Device

Test the Hamamatsu camera first, but start with device discovery/open-close and
property readback only. It is the best first target because the persisted UI
state indicates real camera use while AD2, pump, valve, and Z-stage were
disabled or simulated; camera discovery is low risk compared with wavegen
output, pump flow, valve switching, or stage motion.

The second target should be AD2 discovery only, using enumeration and open-close
checks with all outputs disabled. Pump, valve, and Z-stage should come later
because they can move fluid or hardware and need verified bench setup, command
semantics, and operator confirmation.

## Current Script Inventory and Quarantine

- Passive/discovery-oriented scripts include `test_ad2_discovery.py`,
  `test_hamamatsu_discovery.py`, `test_qmix_discovery.py`,
  `test_serial_discovery.py`, `test_thorlabs_apt_discovery.py`, and
  `test_dcam_property_discovery.py`. Read each script's command-line safety
  gate before running it; some optional modes open a device.
- `test_real_workflow_smoke.py` is an operator-run staged smoke tool. Its
  default is plan-only; every real hardware action requires its documented
  command-line confirmation.
- `test_valve_command_probe.py` and `test_valve_command_probe_v2.py` are
  manual, action-capable valve probes despite their historical names. They are
  excluded from normal pytest collection (`testpaths = ["tests"]` and a
  module-level `__test__ = False`) and require `--confirm SEND`. Their
  lists retain historical alternatives for diagnosis, but the current
  application/LabVIEW command bytes are `P01\r` and `P02\r`. Record raw bench
  responses rather than treating a successful serial write as physical-routing
  confirmation.
- `manual_ppc001_piezo_probe.py` is a manual Kinesis/pythonnet probe. It may
  move the piezo only behind its explicit confirmation gate and must never be
  represented as automated coverage. It is intentionally ignored and named
  `manual_*.py`; no historical BPC-named probe is an active project tool.
- `manual_tec_read_only_probe.py` reads only Device Status, conditional Error
  Number, Object Temperature, and Output Enable Status. It has no write path.
- `manual_qmix_no_motion_reliability.py` requires the literal confirmation
  `NO_MOTION_CAN` and performs only bus open/start, passive pump status, stop,
  and close across three to five trials. It never enables, clears, references,
  or moves the pump and treats a retained fault flag as a failed reliability
  outcome even when the last-error code has returned to zero.

## Prepared Minimal Bench-Confirmation Group

This is a staged checklist, not evidence that the physical checks have run.
The offline AD2 plan and valve candidate-list paths were rechecked on
2026-08-05 without opening hardware. Each action step still needs its own
operator setup and observation:

1. AD2 start timing: first run
   `python -B hardware_tests\test_real_workflow_smoke.py --plan-only --ad2-timing-plan`.
   With a scope connected and the output load confirmed, the corresponding
   gated action is `--real-ad2-timing-check --pre-trigger-wait-s 2.0 --confirm
   CONFIRM_REAL_HARDWARE`. This uses the script's low-risk 1 kHz, 0.1 V
   waveform; it does not prove the full acoustic condition.
2. Valve routing: use one `P01\r` or `P02\r` action at a time through a
   `test_valve_command_probe*.py` script with `--confirm SEND`, after confirming
   COM5/COM6 and the tubing state. A recognized status response confirms the
   numeric position, not its fluidic meaning.
3. Qmix motion/stop semantics: the 2026-08-28 no-motion probe completed three
   clean bus ownership/cleanup cycles but retained the pump fault flag in all
   three. Do not run motion while that relatching CAN fault remains. Resolve
   the controller/CAN condition before any movement check.
4. TEC persistence: do not test until the reviewed real-operation boundary is
   approved. A flash-writing check is intentionally outside the current
   simulated-default workflow.
5. Vendor-call timeout behavior: a Python timeout cannot prove that a blocked
   vendor call stopped internally. Confirm this only with device-specific
   instrumentation or a disposable process after vendor review; do not infer
   cancellation from the UI becoming responsive.

## Z-Stage Discovery Result

- The old Z-stage path in the converted Python code assumes a Prior serial
  stage on `COM7`.
- That old stage is no longer the current hardware.
- The Z-axis stage has been replaced.
- The configured Prior Z-stage serial path is not valid for the currently
  connected device: `COM7` is not present.
- Windows Device Manager shows an `APT USB Device`.
- Thorlabs/Kinesis is installed under
  `C:\Program Files\Thorlabs\Kinesis`.
- `pylablib` passive enumeration found one Kinesis/APT device.
- Detected device:
  - serial: `44533854`
  - type: `APT Piezo Controller`
- No controller was opened, no motor was enabled, no polling was started, and
  no motion, home, jog, identify, or settings commands were sent.
- The current application uses a separate PPC001 precision-piezo/Z-Scan path;
  it remains a manually authorized calibration-motion path outside canonical
  experiment motion. ClosedLoop mode is a prerequisite for accuracy, not an
  authorization to move. Do not revive the old Prior `COM7` path for the new
  hardware.

## Pump Hardware History

- The pump system is still the original neMESYS/Qmix pump system.
- It was previously configured or used as a two-unit/two-pump setup.
- The two-unit setup did not work reliably.
- Current operator notes describe a one-pump setup; confirm that setup before
  enabling a real pump.
- The current code's recommended QmixElements configuration is the one-pump
  configuration:
  `C:\Users\Lab user\Desktop\Franzi\video paper 2\Paper 2 slow flow\Configurations\Cetoni_1pump_config_FM`
- The previous `two_pumps` configuration is not suitable for the current
  connected hardware.
