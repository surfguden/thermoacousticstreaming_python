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

## Devices Found

- Digilent Analog Discovery / Analog Discovery 3 through the WaveForms SDK.
  The code covers wavegen, digital output, analog-in/MSO capture, device
  enumeration, PC trigger, reset, and close-all behavior.
- Hamamatsu camera through the DCAM SDK Python wrapper.
- Cetoni/Qmix pump through the Qmix SDK Python wrapper and QmixElements project
  configuration.
- MX Valve 2 through serial text commands over a COM/VISA-style resource.
- Current Z hardware through a Thorlabs PPC001/PFM450(E) precision-piezo path.
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
  tests. These actively enable wavegen and should not be used as first-contact
  tests.
- `tools/test_hamamatsu_camera.py`: existing camera open/snapshot test.
- `tools/test_qmix_pump.py`: existing Qmix pump initialization test, with an
  optional flow command.
- `README.md`, `docs/current_workflow_audit.md`, and
  `docs/known_open_items.md`: current operator-facing status and safety notes.
  `docs/HANDOVER.md` and `docs/PORTING_TBD.md` are historical/reference
  material, not current validation status.
- `labview_manifest.json`, `port_status.json`, and `main_html/`: LabVIEW export
  registry and hardware-related VI references.
- `.thermo_acoustic_ui.json`: local persisted UI state. This may contain useful
  clues but should be treated as stale or bench-specific.

## Packages, SDKs, Resources, and Config

- Python packages declared in `pyproject.toml`: `PySide6`, `Pillow`, and
  `pyserial`.
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
- Serial resources: valve default `COM5` (real-hardware-confirmed; `COM6` was
  a standing documentation error). Prior `COM7` is legacy only and is not used
  for the current PPC001 piezo.
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
  historical candidate lists are not protocol documentation; record raw bench
  responses rather than treating a successful serial write as physical-routing
  confirmation.
- `manual_ppc001_piezo_probe.py` is a manual Kinesis/pythonnet probe. It may
  move the piezo only behind its explicit confirmation gate and must never be
  represented as automated coverage. It is intentionally ignored and named
  `manual_*.py`; no historical BPC-named probe is an active project tool.

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
- The current physical setup has only one pump unit connected.
- Current active Python validation should use the one-pump QmixElements
  configuration:
  `C:\Users\Lab user\Desktop\Franzi\video paper 2\Paper 2 slow flow\Configurations\Cetoni_1pump_config_FM`
- The previous `two_pumps` configuration is not suitable for the current
  connected hardware.
