# Hardware Debugging Plan

This folder is reserved for hardware debugging code that is isolated from the
main experiment program. No scripts have been created yet.

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
- Prior Z motor/stage through serial text commands over a COM/VISA-style
  resource.
- A Reglo pump control data class and LabVIEW port references exist, but there
  is no real Reglo backend comparable to the Qmix backend in the current Python
  source.

No direct Python control path was found for a laser, high-voltage amplifier,
heater, NI-DAQmx device, or separate piezo/acoustic driver. Acoustic drive
appears to be represented indirectly through the AD2 wavegen/digital-output
paths.

## Hardware-Related Files

- `src/thermo_acoustic/instruments.py`: instrument facades, simulators, serial
  backend, AD2 facade, camera facade, Qmix pump facade, valve, and Prior
  Z-stage.
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
- `src/thermo_acoustic/camera.py` and `src/thermo_acoustic/imaq.py`: camera ROI,
  image display, and image helper structures.
- `tools/release_ad2.py`: WaveForms device enumeration and close-all utility.
- `tools/capture_ad2_wavegen_scope.py` and
  `tools/capture_ad2_wavegen_scope_matplotlib.py`: existing AD2 output/capture
  tests. These actively enable wavegen and should not be used as first-contact
  tests.
- `tools/test_hamamatsu_camera.py`: existing camera open/snapshot test.
- `tools/test_qmix_pump.py`: existing Qmix pump initialization test, with an
  optional flow command.
- `README.md`, `docs/HANDOVER.md`, and `docs/PORTING_TBD.md`: current hardware
  status and validation notes.
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
  `C:\Users\Public\Documents\QmixElements\Projects`.
- Serial resources: valve default `COM6`, Prior Z-stage default `COM7`.
- Serial defaults: 9600 baud, 8 data bits, no parity, 1 stop bit, no flow
  control, 10 s config timeout, and `\r\n` line ending in the serial backend.
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

## Proposed Files To Create Later

- `hardware_tests/common.py`: shared confirmation prompts, logging, timeout,
  cleanup helpers, and safe defaults.
- `hardware_tests/inventory.py`: import/package/SDK availability checks and
  non-actuating hardware discovery.
- `hardware_tests/test_hamamatsu_discovery.py`: DCAM import, init, camera
  count/open-close, model/property readback; no capture by default.
- `hardware_tests/test_ad2_discovery.py`: WaveForms DLL resolution, device
  enumeration, serial/name/opened state, optional open-close with outputs
  disabled.
- `hardware_tests/test_qmix_discovery.py`: Qmix DLL loading, bus open/close,
  pump count/name/status readback; no enable, reference move, flow, or fill
  command by default.
- `hardware_tests/test_serial_ports.py`: list/validate configured COM resources
  and optional query-only checks; no valve switching or stage movement by
  default.
- `hardware_tests/test_valve_confirmed.py`: later confirmed valve position test
  with explicit operator acknowledgement.
- `hardware_tests/test_prior_z_readonly.py`: later Z-stage read-position/status
  check, with movement tests separated and explicitly confirmed.
- `hardware_tests/test_ad2_low_output_confirmed.py`: later low-amplitude AD2
  loopback test requiring confirmation and guaranteed output shutdown.

## Z-Stage Discovery Result

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
- Future Z-stage integration should use a Thorlabs/APT/Kinesis path, not the
  current Prior serial `COM7` implementation.
