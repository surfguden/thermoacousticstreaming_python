# P0 Hardware Truth Record — 2026-08-28

This is a point-in-time evidence record for the prepared P0 procedures. It
distinguishes software, protocol, and physical evidence. It does not authorize
later motion or output and does not replace retained historical records.

Repository state during the checks: branch `junjiebranch`, HEAD
`25826cb4ab6089471c9052e09ff4117d8e5a311f`, dirty with the shared runtime
truth/preflight work under review. No stage action, pump motion, TEC write,
AD2 output, or valve command was performed.

## DIO1 / camera / AD2 timing — UNVERIFIED

Passive WaveForms enumeration found one unopened Analog Discovery 2:
`SN:210321A18CE2`. No output was configured or started.

The read-only Hamamatsu discovery then failed at `Dcamapi.init()` with signed
code `-2147483130`, hexadecimal `0x80000206`. The vendored
`dcamsdk4/inc/dcamapi4.h` identifies that code as `DCAMERR_NOCAMERA`. Therefore
the camera could not be safely armed and no camera exposure/trigger signal was
available. Physical AD2-to-scope probe wiring was also not observable from
software.

Consequences:

- no AnalogOut start edge was generated or measured;
- no DIO1 edge, frequency, or start delay was generated or measured;
- no PC-trigger marker was observed;
- no exposure output or frame timing was measured;
- no observation-based timing diagram exists yet.

It would be false to convert the programmed 10 Hz / 0.20 s / 0.50 s diagnostic
request in the preparation document into a measured diagram. The phase must be
repeated only after the camera is visible and the exact scope wiring is
operator-confirmed.

## Valve P01/P02 routing — UNVERIFIED

OS discovery retained COM5 as the valve candidate, but software could not
verify that a harmless air/fluid route was prepared, the pump was physically
isolated, or which ports an observer could see. No `P01`, `P02`, or `S` command
was sent in this pass. Protocol and physical fields therefore remain:

| Position | Requested | Protocol-confirmed | Physical route |
| --- | --- | --- | --- |
| P01 | not sent | not read | UNVERIFIED |
| P02 | not sent | not read | UNVERIFIED |

## Qmix/CAN no-motion baseline — PROTOCOL-CONFIRMED, NOT MOTION-READY

Preconditions captured before the trial:

- no Python/pytest, LabVIEW, QmixElements, or analyzer client process was
  running;
- adapter: `VCI4 USB-to-CAN compact`, bus description `USB-CAN Compact`;
- PnP location: `Port_#0002.Hub_#0005`;
- driver provider/version/date: HMS Industrial Networks, `4.0.131.0`,
  2022-07-11;
- `VciDevService` was Running with Automatic start from
  `C:\Program Files\HMS\IXXAT VCI 4.0\DeviceServer\VciDevService.exe`;
  the executable reported file version `4.1.298.0` and product version
  `4.0.277.0`;
- project:
  `C:\Users\Lab user\Desktop\Franzi\video paper 2\Paper 2 slow flow\Configurations\Cetoni_1pump_config_FM`;
- runtime DLL directory:
  `C:\Users\Lab user\AppData\Local\CETONI_SDK`.

`hardware_tests/manual_qmix_no_motion_reliability.py` ran three trials. It did
not enable, clear faults, reference, calibrate, aspirate, dispense, or move.

| Trial | UTC status timestamp | Bus start | Pump status | Last device error | Bus stop | Bus close |
| --- | --- | ---: | --- | --- | ---: | ---: |
| 1 | 06:39:57.188666 | 2.266 s | one pump, node 2; fault=True; enabled=False; pumping=False; position sensing=False | 33279 (`0x81FF`), `CAN Tx Queue Overrun` | < recorded timer resolution | 1.110 s |
| 2 | 06:40:00.986962 | 2.172 s | same | 0, prior errors reported resolved; fault latch still True | < recorded timer resolution | 1.125 s |
| 3 | 06:40:04.686363 | 2.063 s | same | 0, prior errors reported resolved; fault latch still True | < recorded timer resolution | 1.125 s |

Results:

- open/start/status/stop/close success: 3/3;
- clean stop/close: 3/3;
- fault-free status: 0/3;
- `0x319` stop/close failure: 0/3 in this sample;
- mean Bus.start duration: approximately 2.167 s;
- mean Bus.close duration: 1.120 s.

No live adapter CAN error counters or bus-state counters were exposed by the
passive OS/SDK checks used here. Obtaining them remains a separate analyzer or
QmixElements/VCI diagnostic step.

This closes only a narrow no-motion transport-cleanup sample. A zero last-error
code in trials 2–3 did not clear `fault=True`; eventual error resolution is not
pump readiness. The operator-controlled recovery trial was not run because the
physical syringe/route state could not be verified. Reference, fill truth, and
motion remain unresolved.

## TEC read-only verification — PROTOCOL-CONFIRMED

Environment:

- interpreter: `C:\Users\Lab user\.conda\envs\exp_ctrl\python.exe`;
- Python 3.11.15;
- pyMeCom 1.1, matching the `v1.1` project pin;
- `tools/check_environment.py`: all core and optional dependencies present;
- port: COM6;
- no Meerstetter control client process was detected.

The manual read-only probe called no write method. Raw decoded observations:

| UTC timestamp | Scope/channel | Parameter(s) | Value |
| --- | --- | --- | --- |
| 06:39:00.095086 | device-wide, instance 1 | 104 Device Status | 1 (`Ready`) |
| 06:39:00.126481 | CH1 | 1000 Object Temperature; 2010 Output Enable Status | 24.566940307617188 °C; 0 (`Static OFF`) |
| 06:39:00.159534 | CH2 | 1000 Object Temperature; 2010 Output Enable Status | 24.603866577148438 °C; 0 (`Static OFF`) |

Error Number 105 was correctly not read because Device Status was not Error.
The client closed at 06:39:00.275627 UTC. Device identity was not read because
the current explicitly scoped read set does not include an identity parameter.

## Static OFF and partial-application policy — SOFTWARE-CONFIRMED

The current official TEC-Family MeCom protocol defines channel-instance
parameter 2010 value 0 as Static OFF and value 1 as Static ON. The implementation
now exposes an explicit per-channel Static OFF path that:

- writes only named parameter 2010 value 0;
- bounds every channel command and the final readback;
- confirms both channels report OFF;
- attempts remaining OFF commands after an ordinary channel error;
- stops without concurrent serial commands after a timeout;
- performs no target, PID, calibration, or flash write.

The sequential dual-channel setpoint operation now records which ON commands
may have been issued. If any ON, target, no-op `write_config`, or readback step
fails, it attempts Static OFF for every potentially affected channel, never
rolls back target values, and raises `TecPartialApplicationError` preserving
both the primary error and any OFF-cleanup error. This is intentionally not
atomic.

Fake-backend and fake-MeCom tests pass. No real Static OFF command was sent in
this pass: the read-only observation already showed both channels OFF, and the
task forbids broad writes before software review.

Official source: Meerstetter's
[TEC-Family MeCom Communication Protocol download archive](https://www.meerstetter.ch/customer-center/downloads/category/17-tec-family-communication-protocols).

## Shared preflight authority decision — NO-GO

Green normalized shadow comparisons now cover:

- plain repeats and repeat-group boundaries;
- frequency substitution and FM-enabled output;
- fixed and dynamic DIO1 start values;
- flush off/on;
- locked and unlocked TEC groups;
- simulated/disabled device combinations;
- blank and explicit output paths;
- camera defaults plus Frames/Internal-trigger overrides;
- the complete normalized WFG, DO, FM, camera, flush, TEC, exposure, and path
  input representation.

No mismatch was found in those samples. Classification:

- **bug in new planner:** none observed;
- **existing legacy behavior:** blank output resolves to the working directory;
  disabled optional fluidics are omitted when flush is off;
- **intentional representation:** readiness/evidence warnings are shared
  preflight information and do not alter the legacy experiment objects;
- **unresolved semantic question:** physical DIO1/camera synchronization.

Cutover remains NO-GO because `RunPlan` still wraps objects produced by the
legacy builder, v1/v2 do not consume `BuildResult`, live camera feasibility is
still checked later in `Application.run_experiment2()`, and blocking-issue
equivalence is not yet exhaustive. Production Start remains unchanged.

## Camera-default ownership

The software classification is now explicit:

- **EXPERIMENT DEFAULT:** master-pulse mode/source/interval/burst, polarity,
  delay;
- **EXPERIMENT OVERRIDE:** experiment Frames, automated Internal trigger,
  experiment exposure;
- **MANUAL-ONLY:** ROI editor, manual trigger source, manual exposure;
- **APPLIED DEVICE STATE:** exposure returned after the real DCAM apply;
- **DISPLAY-ONLY:** timing-feasibility summary.

ROI remains excluded from the automated sequence settings and must not be
mistaken for a freshly applied experiment ROI.
