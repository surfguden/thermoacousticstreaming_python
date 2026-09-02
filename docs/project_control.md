# Project Control

Authoritative current-state dashboard for `junjiebranch`. Read this first.
Current unresolved work is in [`known_open_items.md`](known_open_items.md);
durable engineering judgment is in [`lessons_learned.md`](lessons_learned.md).
Historical audits and evidence records preserve how conclusions were reached,
but they do not override this page, current source, tests, Git state, or newer
retained evidence.

Last current-truth convergence: 2026-09-02, based on clean pushed V3 checkpoint
`9a899d753d279f16b57c0065a9c8285f475aaec1`.

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
| Persistent instrument state | Readiness, run state, alerts, Acoustic/W1, camera, laser-control, sample-refresh, and output state. Software/backend state only unless explicitly labeled otherwise. |
| Experiment | Series identity plus Acquisition, Acoustic, Sample Refresh, and Advanced configuration. |
| Start will run | Canonical-request-derived run scope, sequence, camera, Acoustic/W1, disabled laser control, refresh, output, required devices, blockers, and warnings. |
| Monitor | Progress, live display surfaces, and concise existing runtime events. |
| Manual & Service | Existing immediate-action camera, pump/valve, AD2, Z, and diagnostic panels, clearly outside the experiment plan. Opening a panel is inert; actions retain their established gates and use `MANUAL_SERVICE` logging context. |
| Diagnostics | Detailed cached/device state, action-evidence location, and diagnostic history. |
| Persistent run controls | Start the reviewed plan or request graceful stop. Graceful stop finishes the current unit; it is not an emergency hardware stop. |

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
| Project Ch1 / `exp_ad2_channels[0]` / WaveForms API index 0 | W1 | W1 BNC `J4`; `JP4` selects direct or approximately 49.9-ohm series path | Acoustic amplifier -> transducer | Software mapping, official connector semantics, owner wiring, and physical connector confirmed. Installed termination and downstream loaded voltage unverified. |
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
| Camera | Hamamatsu ORCA-Fusion BT `C15440-20UP`, S/N `500478`; photograph, Windows enumeration, and bounded read-only open/close evidence | Physical trigger/exposure timing; normal mode remains Internal |
| AD2 | Analog Discovery 2, retained enumeration `SN:210321A18CE2`; W1 acoustic route; official BNC Adapter family | Current USB route, JP4/JP5 positions, loaded downstream voltage, acoustic pressure, physical timing |
| Laser | TOPTICA `iBEAM-SMART-785-S-HP`, approximately 785/787-nm class, Class 3B | Exact Analog/Digital input semantics and actual optical power; safety label is not power evidence |
| Pump | One CETONI Low-pressure module 14:1: `NEM-B101-02 E 5`, `CET-003455-1505`; logical node `neMESYS_Low_Pressure_1_Pump`, node 2 | Exact base/interface identity, installed syringe/loading/travel, harmless route, fill truth, stop latency, bounded motion |
| Valve | `COM5`, 19200 baud, MX Series II protocol; software position 1 -> `P01`, position 2 -> `P02`; owner route truth: P01 through-chip, P02 bypass | Exact SKU and independent physical observation of each route |
| Z | Current manual path is Thorlabs `PPC001`/`PFM450E` through Kinesis; candidate controller serial `44533854` | Fresh identity, direction, scale, travel, and microscope physical datum. Prior/COM7 is historical compatibility only. |
| TEC | Meerstetter `TEC 1123-HV` candidate identity on `COM6`; read-only status and narrowly authorized dual-channel Static OFF evidence retained | Fresh exact identity and any active target behavior beyond the retained scope; controller stability is not imaging-plane equilibrium |

Do not reinterpret device label strings as serial/article numbers unless the
retained evidence explicitly establishes that meaning.

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

Offline software status: the camera+AD2 steady/quasi-steady path is ready for an
independent pre-hardware readiness review. This statement is not hardware
authorization and does not claim physical calibration.

### Next real project step

Perform the separately requested **PRE-HARDWARE READINESS REVIEW** against the
clean pushed Documentation Convergence checkpoint. Its only gate question is
whether a concrete software defect makes one minimal real Internal-trigger
camera + finite Acoustic/W1 fast-FM run unsafe, uninterpretable, or
undiagnosable. Do not start hardware as part of that review.

If that review returns ready, the next action is a separately authorized minimal
real camera+AD2 run with laser software control, DIO, pump/refresh, TEC, and Z
disabled.

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
