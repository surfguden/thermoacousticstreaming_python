# Project Control

Authoritative current-state dashboard for `junjiebranch`. Read this first.
Current unresolved work is in [`known_open_items.md`](known_open_items.md);
durable engineering judgment is in [`lessons_learned.md`](lessons_learned.md).
Historical audits and evidence records preserve how conclusions were reached,
but they do not override this page, current source, tests, Git state, or newer
retained evidence.

Last current-truth convergence: 2026-09-02, based on clean pushed documentation
checkpoint `86b03500af36c1b7d61c30c1f583641b709760ab`.

## Authority hierarchy

Use the narrowest applicable authority:

1. `AGENTS.md` — durable work, safety, evidence, validation, and Git boundaries.
2. Current source and tests — implemented software behavior.
3. This document — current project, workflow, hardware, and readiness truth.
4. `known_open_items.md` — only genuinely unresolved or deferred work.
5. Point-in-time hardware records — retained physical/protocol evidence for the
   exact session described.
6. Historical audits, migration references, handovers, and changelogs — context
   only. Their current-tense statements may have been superseded.

Owner-supplied physical routing is authoritative as owner workflow truth when
identified as such; it remains distinct from protocol acknowledgement and
independent physical observation.

## Current software architecture

Normal Qt Start has one planning authority:

```text
V3/V2/V1 controls
  -> ExperimentRequest
  -> build_independent_run_plan()
  -> immutable RunPlan / RunCondition
  -> legacy_series_from_run_plan()
  -> retained ExperimentSeries2 / Experiment2
  -> Application.run_experiment2()
  -> instrument facades and hardware backends
```

`ExperimentRequest` is normalized software-request truth. `RunPlan` and
`RunCondition` are immutable planning truth. The legacy adapter is an explicit
compatibility boundary into the mature runtime, not a second planner. The old
UI-based series builder remains rollback-only. V3 `BuildResult` is a
presentation/audit projection used for pre-run explanation; valid Start rebuilds
and executes the authoritative independent plan.

This boundary is closed for ordinary maintenance. Do not reopen it without a
concrete contradictory defect supported by current source/tests.

## Current normal experimental workflow

The primary experiment is steady/quasi-steady thermoacoustic acquisition.
Transient/onset synchronization is deferred and must not dominate the normal
path.

Manual preparation:

1. Clean the system manually.
2. Load the initial sample manually.
3. Align the laser spatially by the established manual procedure.
4. Establish fixed optical power experimentally and independently of AD2
   command voltage. Software laser control remains disabled.

Software experiment:

1. Select an explicit series/output directory.
2. Configure camera frames, FPS, exposure, and ROI.
3. Configure Acoustic / W1, normally with intentional fast FM sweep. The
   scientific intent is `T_sweep << T_exposure`; this does not turn host or
   camera timestamps into a physical synchronization measurement.
4. Keep Laser/W2, DIO0, DIO1, pump refresh, TEC, and Z disabled unless a later
   separately authorized workflow explicitly requires them.
5. Review V3's “Start will run” summary and resolve all blocking preflight
   issues.
6. Run Internal-trigger camera acquisition with finite Acoustic/W1 behavior.
7. Monitor run progress and operator events.
8. Retain TDMS, action, manifest, and diagnostic evidence.
9. Enable the bounded repeat-to-repeat refresh sequence only after its separate
   physical readiness gates are satisfied. Cleaning and initial loading remain
   manual, not automated refresh steps.

For the next minimal camera+AD2 run: enable Acoustic/W1 explicitly, use
`Repeat=1`, keep Frequency Scan off when FM Sweep is on, choose a finite run
duration covering acquisition, verify the requested ROI/exposure/amplitude, and
leave every deferred subsystem disabled.

## V3 operator model

V3 is the tracked opt-in instrument-control surface launched by
`launch_gui_v3.bat` or `python tools/run_ui_v3.py`. It shares the same
`Application` and hardware backends as v1/v2; it is not a simulator and opening
it does not authorize hardware. V1 remains the default launcher and v2 remains
the transitional rollback/reference surface until the owner separately changes
that policy.

| Surface | Purpose and evidence boundary |
| --- | --- |
| Persistent instrument state | Compact Readiness, Run, Alerts, Acoustic/W1, Camera, and Output state needed across workspaces. Software/backend state only unless explicitly labeled otherwise. |
| Experiment — Configure | Series identity plus Acquisition, Acoustic, Sample Refresh, and Advanced/Deferred configuration, with explicit units on high-frequency numeric inputs. |
| Experiment — Review run | Full-width canonical-request-derived run scope, sequence, camera, Acoustic/W1, unavailable laser control, refresh, output, required devices, blockers, warnings, and requested/latest-applied evidence. |
| Monitor | Run progress and operator events plus requested run context. Its waveform is a requested/computed preview; measured camera rate remains distinct and no physical telemetry is inferred. |
| Manual & Service | Existing immediate-action panels grouped as routine camera/fluidics tasks versus engineering/calibration AD2 and Z tasks, clearly outside the experiment plan. Opening a panel is inert; actions retain their established gates and use `MANUAL_SERVICE` logging context. |
| Diagnostics | Detailed cached/device state, action-evidence location, and diagnostic history. |
| Persistent run controls | Open Review run, Start after the shared software gate passes, or request graceful stop. Graceful stop finishes the current unit; it is not an emergency hardware stop. |

Requested settings remain primary during configuration. V3 surfaces a latest
applied/effective discrepancy only when the existing durable action record
contains it. Missing evidence is `UNKNOWN`, never inferred. Deferred
camera-start metadata, trigger details, TEC engineering controls, raw channel
indices, and other uncommon options remain available without dominating normal
operation.

## Current hardware and routing truth

### Four-layer AD2 routing

| Software | AD2 | Digilent BNC Adapter | External route | Current classification |
| --- | --- | --- | --- | --- |
| Project Ch1 / `exp_ad2_channels[0]` / WaveForms API index 0 | W1 | W1 BNC `J4`; `JP4` selects direct or 49.9-ohm series path | Custom laboratory acoustic amplifier -> transducer | Software mapping, official connector semantics, owner wiring, and current custom-amplifier enclosure are owner/photo confirmed. Installed JP4 position, exact external connector roles, amplifier input impedance/gain/output envelope, current transducer identity, and downstream voltage are unverified; W1 commissioning is blocked. |
| Project Ch2 / `exp_ad2_channels[1]` / WaveForms API index 1 | W2 | W2 BNC `J5`; `JP5` selects direct or approximately 49.9-ohm series path | TOPTICA laser Analog In | Physical route confirmed by owner evidence; exact input range, impedance, transfer function, polarity, and enable semantics unresolved. Normal production fails closed if W2 is enabled. |
| No normal-production digital-output request | DIO0, pink | `J6` pass-through; no BNC or AWG jumper | Camera `EXT.TRIG` | Physically connected but unused in normal Internal-trigger acquisition. External/transient timing deferred. |
| Explicit disabled normal-production digital-output payload | DIO1, green | `J6` pass-through; no BNC or AWG jumper | TOPTICA laser Digital In | Physically connected but unprogrammed. Installed digital-option/configuration and active semantics unresolved. |

The green adapter is the official Digilent BNC Adapter family, SKU `410-263`,
not a generic/custom breakout. W1/W2 are routed to BNC connectors; DIO and T1/T2
remain on the flywire/header pass-through. The board provides passive routing,
grounding, selectable scope coupling, and selectable AWG series termination; it
does not actively process signals. Exact installed PCB revision and JP4/JP5
positions remain unverified. A programmed AD2 voltage therefore is not the
downstream acoustic-amplifier or laser-control voltage unless the loaded circuit
is derived or measured.

### Current inventory

| Subsystem | Current identity/path | What remains unproven |
| --- | --- | --- |
| Camera | Hamamatsu ORCA-Fusion BT `C15440-20UP`, S/N `500478`; photograph, Windows enumeration, and fresh 2026-09-02 USB3 identity plus bounded camera-only acquisition evidence | Physical trigger/exposure timing; normal mode remains Internal |
| AD2 | Analog Discovery 2, freshly enumerated 2026-09-02 as `SN:210321A18CE2`; W1 acoustic route; official BNC Adapter family | JP4/JP5 positions, loaded downstream voltage, acoustic pressure, physical timing |
| Acoustic amplifier | Custom/home-built mains-powered laboratory unit. Owner-supplied current photographs show a metal enclosure with IEC entry/switch, external coax/BNC-type connectors, and handwritten engineering annotations; no commercial manufacturer/model label is visible. | `CUSTOM_ACOUSTIC_AMPLIFIER_CHARACTERIZATION_REQUIRED`: external input/output connector roles, controls, approximate input impedance and gain near 1.9-2.0 MHz, plausible output range/load, limiting/clipping indication, and same-chain history/build evidence needed before energized W1. Blurry annotation values are not evidence. |
| Acoustic transducer | Lund apparatus used Ferroperm/Meggitt Pz26, `30 x 4.0 x 1.0 mm`, bonded to the chip glass lid; this is a prior-apparatus candidate, not current physical identity | Owner confirmation that the installed element is that part; assembled impedance/resonance and safe-drive evidence |
| Laser | TOPTICA `iBEAM-SMART-785-S-HP`, nominal 785-nm family, Class 3B; exact model string is owner-label evidence | Exact installed rated power/options, Analog/Digital electrical input semantics, and actual optical power; safety/model label is not power-at-sample evidence |
| Pump | One CETONI Low-pressure module 14:1: `NEM-B101-02 E 5`, `CET-003455-1505`; logical node `neMESYS_Low_Pressure_1_Pump`, node 2 | Exact base/interface identity, installed syringe/loading/travel, harmless route, fill truth, stop latency, bounded motion |
| Valve | `COM5`, 19200 baud, IDEX/Rheodyne MX Series II protocol family; software position 1 -> `P01`, position 2 -> `P02`; owner route truth: P01 through-chip, P02 bypass | `MODEL_IDENTITY_REQUIRED`: readable manufacturer/model/part/serial label; independent physical observation of each route |
| Z | Current manual path is Thorlabs `PPC001`/`PFM450E` through Kinesis; candidate controller serial `44533854` | Fresh identity, direction, scale, travel, and microscope physical datum. Prior/COM7 is historical compatibility only. |
| TEC | Meerstetter `TEC-1123-HV`, retained photo-confirmed identity with SDK-reported type 1123/serial beginning `509...`, firmware 5.10, on `COM6`; read-only status and narrowly authorized dual-channel Static OFF evidence retained | Any active target behavior beyond retained scope; controller stability is not imaging-plane equilibrium |

Do not reinterpret device label strings as serial/article numbers unless the
retained evidence explicitly establishes that meaning.

### 2026-09-02 minimal-commissioning electrical closure

Camera-only Gate 2 is accepted and must not be repeated. The bounded run used
the real USB3 camera with simulated AD2, Internal trigger, one repeat, three
frames at requested 10 FPS, requested ROI `x=0, y=792, 2304 x 740`, and requested
40 ms exposure. Fresh readback retained the requested ROI and an applied
exposure of approximately 40.0005 ms; the run completed with three TIFFs and no
primary or cleanup failure. This proves bounded acquisition/save behavior, not
sample visibility, synchronization, or acoustic streaming.

The following exact-model facts are established from official manufacturer
documentation:

- The ORCA-Fusion BT `C15440-20UP` is a 2304 x 2304, 6.5-micrometre-pixel,
  C-mount camera. In Normal Area Mode with DCAM-API, horizontal and vertical ROI
  size and position have four-pixel/four-line minimum steps. USB3 full-frame
  Fast scan is limited by the documented transfer modes; this does not replace
  fresh requested/applied timing evidence.
- Camera power is 12 VDC at the camera; the supplied AC adapter accepts
  100-240 VAC, 50/60 Hz. USB3 and CoaXPress must not be connected
  simultaneously, and changing between them requires closing the application
  and powering the camera off. `EXT.TRIG` accepts TTL or 3.3 V LVCMOS into
  10 kohm and supports selectable rising/falling polarity. Normal Area Mode
  supports edge, level, global-reset edge/level, synchronous-readout, and start
  triggering as documented; current production intentionally uses Internal.
  `TIMING 1/2/3` are 3.3 V LVCMOS outputs with 33-ohm output impedance and
  cable-dependent termination. Exposure ranges are 17 microseconds-10 seconds
  Fast, 65 microseconds-10 seconds Standard, and 280 microseconds-10 seconds
  Ultra Quiet; actual exposure is quantized upward, which agrees with the
  requested/applied distinction already retained by production. Initialization
  is indicated by blinking orange before steady green. DCAM device strings
  provide bus/model/camera ID; current fresh evidence resolves USB3,
  `C15440-20UP`, and S/N `500478` without relying on device index alone.
- Analog Discovery 2 W1/W2 are single-ended 14-bit, 100 MS/s waveform outputs.
  The recommended operating range is within approximately +/-5 V, with
  approximately 10 mA recommended output current and 4 MHz 0.5 dB bandwidth.
  Absolute limits are not commissioning targets. A near-2 MHz carrier is
  inside the nominal bandwidth but its delivered voltage remains load- and
  frequency-dependent.
- Native W1/W2 output impedance is nominally zero ohm. Disabled/closed output
  is near 0 V, not high impedance. Carrier amplitude is peak amplitude (the
  official 1 V sample is 2 V peak-to-peak); offset plus instantaneous amplitude
  must remain inside the available output range. DIO is 3.3 V LVCMOS with 4 mA
  drive, 220-ohm series PTC protection, and push-pull/open-drain/open-source/
  tri-state modes; protection ratings are not normal operating levels. The SDK
  exposes device name and a unique serial through `FDwfEnumDeviceName` and
  `FDwfEnumSN`, matching the repository enumeration path. The AD2 carrier
  buffer is up to 16 KiS and its two-channel AM/FM buffer is 2 KiS.
- The official Digilent BNC Adapter is SKU `410-263`; the published schematic
  is document/assembly `500-263`, circuit revision `C.0`. `J4` is W1, `J5` is
  W2, and `J1`/`J3` are Scope Ch1/Ch2. The 30-pin header passes through DIO,
  trigger, supply, and remaining ground signals. The board is passive:
  scope jumpers select coupling, while `JP4` and `JP5` select a direct path or
  a path through `R1`/`R2 = 49.9 ohm` in series with W1/W2. It does not provide
  gain, isolation, or a 50-ohm shunt load.

Official SDK reconciliation found and the current offline correction closes a
pre-output software blocker. The
installed Digilent WaveForms/SDK 3.22.1 manual confirms carrier amplitude is in
volts while FM-node amplitude is modulation index in percent; the installed
official `analogout_sweep.cpp` computes a start-to-stop sweep index as:

```text
100 * (stop_hz - start_hz) / (start_hz + stop_hz)
= 100 * total_width_hz / (2 * center_hz)
```

The corrected production model now carries authoritative start/stop endpoints
through `ExperimentRequest`, immutable `RunCondition`, the compatibility
adapter, and `Experiment2`. `FmSweepSettings` names total span and half
deviation explicitly and computes `100 * half_deviation_hz / center_hz`.
For 1.909--1.959 MHz this is a 50 kHz total span, +/-25 kHz deviation, and
approximately 1.2926577 percent AD2 FM index. V3 presents all four quantities;
planned/action and TDMS evidence preserve endpoints, total span, half
deviation, and index. Backend effective evidence derives post-clamp endpoints
from the SDK parameters and labels them software/protocol-derived, not measured.
Zero or reversed endpoint spans fail closed. Triangle/RampUp/RampDown enum
values and FM node 1 remain confirmed against official installed `dwf.h`.

Historical impact: the factor-of-two formula entered production source in
commit `d30be02dfd45d9a0f1c79ecb53bc27ed274160d9` (2026-07-23) and remained
through pre-correction HEAD `09c6810719badb472304faab050820987c31f540`.
Any FM-enabled run made by that code requested an SDK modulation index twice
the intended index under the project's total-span UI semantics, subject to
device clamping and whether hardware output was actually enabled. Existing
metadata may preserve the nominal 50 kHz width while the configured API intent
was approximately 100 kHz total span; it must not be treated as proof of a
measured acoustic sweep. No tracked TDMS/action-log run artifact was found to
reclassify automatically.

For a sinusoidal source command represented by open/high-impedance amplitude
`V_source`, the simple downstream amplifier-input model is:

```text
V_amplifier_input = V_source * Z_input / (R_source + Z_input)
R_source = approximately 0 ohm or 49.9 ohm according to installed JP4
```

`Z_input` is generally complex and frequency-dependent. A high-impedance input
receives nearly the commanded voltage in either jumper position; a nominal
50-ohm input receives approximately half the source voltage through the 49.9-ohm
path. Amplifier gain and output/load interaction are then required to estimate
transducer voltage. Acoustic pressure additionally requires a calibrated
electro-acoustic model or measurement. None of those downstream quantities may
be inferred from the AD2 command alone.

The 2025 Lund apparatus paper identifies a Ferroperm/Meggitt Pz26 element,
`30 x 4.0 x 1.0 mm`, bonded to the glass lid and reports a function-generator
setting of 3 Vpp near 2 MHz. It does not identify or describe an amplifier.
Therefore 3 Vpp is `PRIOR_LUND_APPARATUS`, not evidence for the present
W1 -> BNC Adapter -> amplifier -> transducer chain. The historical project
0.1 V bounded AD2 output is `PRIOR_PROJECT_HARDWARE_OUTPUT`, but retained
evidence does not establish the same amplifier settings, load, JP4 state, or
transducer. The historical 2 V configuration is software/screenshot evidence
only and was explicitly marked do-not-run. None of these values establishes a
defensible first energized amplitude for the current chain.

Commissioning remains stopped before Gate 3/Gate 4 and before any W1 output.
The current photographs are `OWNER_SUPPLIED / PHOTO_CONFIRMED_CURRENT_UNIT`
evidence for the custom enclosure and visible external construction only. No
blurry handwritten number is promoted to gain, bandwidth, impedance, or output
limit. Do not continue looking for a nonexistent commercial model unless a
repository/build record independently names one.

First-run closure requires only the minimum useful engineering envelope:

1. powered-down external cable trace identifying the AD2/J4 input connector and
   the transducer output connector, including cable/termination details;
2. visible gain/range/termination controls and limiting/clipping/current-limit
   indicators, or explicit confirmation that none exists;
3. approximate input impedance and gain/transfer near 1.9-2.0 MHz, plausible
   output-voltage/load range, and any limiting behavior, supported by a
   schematic, PCB/build note, component marking, old Lund/project note, or a
   later bounded electrical characterization;
4. readable installed `JP4` position relative to PCB silkscreen and adapter
   revision;
5. current bonded-transducer identity or the best retained build evidence,
   including whether it is the Lund Pz26 `30 x 4.0 x 1.0 mm` element; and
6. same-chain historical input amplitude or an electrically justified safe
   starting input, stated unambiguously as AD2 peak, peak-to-peak, or RMS with
   frequency/sweep, duration, amplifier controls, JP4/termination, and load.

A full commercial datasheet is not required. If build documentation is absent,
use a separately reviewed bounded electrical-characterization plan. Because
the custom enclosure is mains powered, any internal photograph, PCB inspection,
or component-marking check must be performed by owner/lab personnel only while
powered down and disconnected from mains; opening it energized is prohibited.

Primary sources: [Hamamatsu C15440-20UP/-20UP01 instruction manual](https://camera.hamamatsu.com/content/dam/hamamatsu-photonics/sites/static/sys/en/manual/C15440-20UP,-20UP01_IM_En.pdf),
[Digilent Analog Discovery 2 reference manual](https://digilent.com/reference/_media/reference/test-and-measurement/analog-discovery-2/ad2_rm.pdf),
[Digilent Analog Discovery 2 getting-started specifications](https://files.digilent.com/manuals/WaveForms/3.25.1/start3.html),
[Digilent BNC Adapter product page](https://digilent.com/shop/bnc-adapter-for-analog-discovery/),
[Digilent Discovery BNC schematic](https://digilent.com/reference/_media/reference/test-and-measurement/bnc-adapter-board/discovery_bnc_sch.pdf),
[Ferroperm Pz26 datasheet](https://www.ferropermpiezoceramics.com/wp-content/uploads/2021/10/Datasheet-hard-pz26.pdf), and
[Lund/APS apparatus paper](https://journals.aps.org/prapplied/pdf/10.1103/PhysRevApplied.23.024043).
The exact FM formula and enum evidence also comes from the locally installed
official Digilent WaveForms SDK 3.22.1 reference manual, `dwf.h`, and
`samples/c/analogout_sweep.cpp`; no device was opened to inspect them.

### Deferred-device remote closure

- TOPTICA's current official iBeam smart family documentation establishes
  nominal 785 nm family availability, analog modulation on all family units up
  to 1 MHz, user-configurable high/low-active behavior, mixed analog/digital
  modulation capability, electronic-shutter complete-off behavior, RS232 up to
  115200 baud, and 12 VDC supply. Digital modulation is explicitly optional;
  family capability does not prove it is installed. Public material does not
  establish the exact Analog In range/impedance or the installed unit's option
  set. Resolve those later without emission through a serial-specific manual or
  configuration record, TOPAS/RS232 read-only option/configuration query, or
  TOPTICA support. Laser remains disabled and is not an acoustic-run blocker.
- The exact retained CETONI pump label is `NEM-B101-02 E 5`,
  `CET-003455-1505`, 14:1. The official Low Pressure manual covers
  `NEM-B101-02 E`, specifies 24 VDC/0.3 A/7 W, CAN at 1 Mbit/s, optional RS232
  at 115200 8-N-1 with no flow control, 6-30 mm syringe outside diameter, and
  piston travel up to 65 mm. These model limits support existing software
  bounds but do not establish installed syringe, position, fill, or harmless
  route. H2B is not reopened.
- The external COM5 MX Series II valve's protocol family and commands are
  retained, but no exact SKU is present in repository evidence; its label is
  still `MODEL_IDENTITY_REQUIRED`. This does not block a run with refresh off.
- Thorlabs documentation identifies the `PFM450E` as a matched 450-micrometre
  objective focus mount/controller set using `PPC001`; retained serial
  `44533854` remains historical identity evidence. Direction, scale, travel,
  and microscope datum remain physical-only and deferred with Z disabled.
- Retained photo/SDK evidence already closes the TEC model as
  Meerstetter `TEC-1123-HV`, not merely a candidate. Official specifications
  identify dual +/-16 A, 0-30 V channels, 12-36 VDC input, USB/RS485, and
  supported temperature-probe families. These are model limits, not measured
  present output. TEC remains disabled and imaging-plane equilibrium remains
  unresolved.

Deferred-device sources: [TOPTICA iBeam smart official specifications](https://www.toptica.com/fileadmin/Editors_English/11_brochures_datasheets/01_brochures/toptica_iBeam_smart_sp.pdf),
[CETONI neMESYS Low Pressure hardware manual](https://cetoni.com/downloads/manuals/Manual_Hardware_Nemesys_LowPressure_EN.pdf),
[Thorlabs PFM450E/PPC001 manual](https://media.thorlabs.com/contentassets/e92d618c92c94cea9096b3f231859611/etn018233-d02.pdf), and
[Meerstetter TEC-1123-HV specifications](https://www.meerstetter.ch/products/tec-controllers/tec-1123-hv).

### Pump and refresh boundary

The current Qmix configuration intentionally selects one pump and rejects the
legacy two-pump profile. H2B established five stable no-motion startup-recovery
trials: one accepted clear-fault call, immediate and delayed fault-false
readback, no post-clear nonzero emergency, enabled/pumping false, and clean
stop/close. This closes startup/no-motion recovery only.

Production initialization reads `position_sensing_initialized` freshly after
fault recovery and before enable. `false` fails closed without enable,
reference, fill, flow, or motion. A historical `true` is not portable across an
unknown power cycle. The automated refresh sequence is exactly:

```text
confirmed P01 -> one target pump command -> bounded completion wait
-> confirmed P02 -> WaitAfterFlush
```

`WaitAfterFlush` is the operator-selected post-P02 stabilization delay for that
automated request. It is not cleaning, initial loading, an imaging-plane mixing
proof, or a duplicate pump command. The manual Pump & Valve delay is a separate
manual setting.

## Camera and acoustic scientific truth

- Normal camera acquisition uses Internal trigger and configures neither DIO0
  nor DIO1.
- Requested ROI is planned, explicitly applied before sequence setup, freshly
  read back, and saved as applied ROI.
- `RequestedExposureMs` preserves the request;
  `AppliedExposureMs` preserves fresh effective DCAM exposure when available;
  compatibility field `ExposureTime` is the effective/applied value after
  configuration.
- Requested FPS remains planning truth even with production DIO disabled. Run
  start checks applied exposure plus fresh readout time against the requested
  frame interval.
- Acoustic uses Project Ch1 / API 0 / W1. Enabled normal CH0 requires
  `Repeat=1`; infinite and unsupported finite repeats fail preflight.
- FM Sweep requires explicit Acoustic/W1 enable and cannot coexist with
  Frequency Scan.
- AD2 range clamping is retained as effective electrical-output metadata. It
  does not establish loaded amplifier voltage, transducer drive, acoustic
  pressure, streaming strength, or physical synchronization.

## Laser boundary

Owner evidence supersedes the historical “CH2 unused” and generic DIO1 stories:
W2 reaches laser Analog In and DIO1 reaches laser Digital In. That routing does
not resolve the installed unit's electrical semantics. Normal production
therefore rejects W2 carrier/FM before hardware configuration and programs
neither digital line. Laser alignment and optical power remain manual/fixed for
the current experiment.

Electrical command, protocol/readback, laser emission, and in-channel optical
power are separate claims. Reopen software laser control only after exact
installed Analog/Digital semantics are retained and a bounded verification is
separately authorized.

## Evidence and record model

| Record | Authority |
| --- | --- |
| `<series>/action_log.jsonl` | Append-only, low-frequency correlated action stream with UTC, host-monotonic elapsed time, run/condition/repeat/phase, subsystem/operation, stage/scope, status, and bounded useful fields. |
| `<repeat>/data.tdms` | Authoritative per-repeat scientific data/settings, requested/applied camera and effective WFG state, enabled/simulated state, output metadata, refresh outcome, and separate primary/cleanup failure. |
| `<series>/series_manifest.json` | Atomic aggregate lifecycle: requested/started/completed/failed counts, abort/final outcome, timestamps, optional TEC counts, and action-log link. It does not duplicate full configuration. |
| `logs/hardware_transactions.log` | Rotating global backend/API/transport diagnostic timeline with `SETUP`, `RUN`, `CLEANUP`, or `MANUAL_SERVICE` context. |
| `Application.runtime_events` / UI event stream | Transient operator chronology, not durable scientific authority. |
| `runs/` retained records | Point-in-time manual hardware evidence, not normal production output or permission for another run. |

Evidence stages are non-interchangeable:

```text
REQUESTED -> PLANNED -> EFFECTIVE -> COMMAND_SENT
-> PROTOCOL_ACKNOWLEDGED -> OBSERVED -> PHYSICAL_VERIFIED
```

Not every action reaches every stage. Current production action logging emits
no `PHYSICAL_VERIFIED` stage. API success, serial acknowledgement, cached state,
camera timestamps, controller stability, and host chronology do not by
themselves prove pressure, emission, route, physical zero, imaging-plane
equilibrium, or synchronization. `timestamp_utc` supplies wall-clock chronology;
monotonic `elapsed_s` supports duration/timeout diagnosis. Neither is a
high-resolution physical timing measurement. JSONL persistence failure is
fail-open with respect to control behavior and cannot initiate hardware or
change the plan.

## Closed and superseded decisions

Do not reopen these without new contradictory evidence:

- The independent request/plan authority and explicit legacy adapter are the
  normal Start architecture.
- Normal production DO output is disabled; generic DO Clock is not part of the
  current steady experiment.
- W2 is a real laser route, not an unused generic channel, and remains
  production-disabled pending semantics.
- DIO0 is the connected camera trigger and DIO1 the connected laser trigger;
  neither is used by normal production.
- The current pump profile is one-pump; old two-pump assumptions are migration
  history.
- Valve transport is COM5; COM6-as-valve was a documentation error.
- Current Z work uses Thorlabs/Kinesis; Prior COM7 is historical only.
- ROI is no longer manual-state-only; normal runs apply and freshly read it.
- Requested and applied exposure are now separate retained fields.
- `WaitAfterFlush` is consumed once after P02; the duplicate target command was
  removed.
- V3 is no longer the migration-era everything-dashboard; its current operator
  model is documented above.
- Qmix startup/no-motion recovery is closed by H2B; pump motion readiness is a
  different, still-open boundary.

## Current readiness and next step

Camera-only Gate 2 is accepted. Acoustic commissioning is not ready for two
independent reasons: exact amplifier/load/termination/current-transducer
evidence is insufficient to select a defensible first W1 amplitude, and the
current FM total-width translation is twice the official SDK formula. No W1
output is allowed until both are closed.

### Next real project step

Obtain and retain the six amplifier/transducer/JP4 facts listed in the
2026-09-02 electrical-closure section, and separately authorize correction and
offline validation of the FM factor-of-two defect. Then derive and
independently review a first-run AD2 amplitude against the exact chain. Do not
energize W1 or resume Gate 3/Gate 4 until both closures are explicit and the
hardware run is separately authorized.

### Deferred capabilities

- Software laser Analog/Digital control.
- External camera trigger and transient/onset synchronization.
- Automated sample refresh and pump motion until physical readiness closes.
- Automated Z motion until current identity/direction/scale/datum are verified.
- Active TEC scientific use until imaging-plane equilibration is justified.
- Rhodamine-B thermometry until calibration provenance is defined.
- V3 promotion to the default launcher until separate owner evaluation.

Historical closed work and detailed remaining closure criteria are linked from
[`known_open_items.md`](known_open_items.md). Deferred capabilities are not
preconditions for the minimal camera+AD2 run while they remain disabled.
