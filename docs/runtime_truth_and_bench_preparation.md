# Shared Runtime Truth and Bench Preparation

This document records the software evidence boundary introduced on 2026-08-28
and prepares the next hardware-verification work. It does not authorize a real
hardware run. The default operator UI remains v1; v2 is the rollback/reference
UI and v3 is a tracked, opt-in presentation of the same shared runtime.

The first execution of these procedures is recorded in
`docs/p0_hardware_truth_20260828.md`. The Qmix no-motion and TEC read-only
phases produced protocol evidence; timing and valve routing remain unverified.

## Shared runtime truth boundary

`runtime_truth.py` defines evidence independently of any UI:

- `REQUESTED`: an operator or experiment requested a value.
- `APPLIED`: this process completed the operation that applies the value.
- `OBSERVED`: a device/protocol readback supplied the value.
- `DERIVED`: software inferred the value from other state.
- `FRESH`: captured during the snapshot call from software state that is current
  without another hardware query.
- `CACHED`: retained from an earlier operation/readback; never equivalent to a
  live query.
- `UNKNOWN`: the age cannot be established.
- `SOFTWARE`, `PROTOCOL`, `PHYSICAL`, and `UNVERIFIED` keep the kind of
  verification distinct. In particular, a valid `P01` reply is protocol
  evidence, not proof of the connected fluid path.

`Application.runtime_evidence_snapshot()` adapts existing state for camera,
TEC, pump, valve, and experiment progress. It performs no hardware I/O. Where
the existing runtime has no observation timestamp, the timestamp remains
`None`; cached state is not relabeled as fresh. AD2 and the Z stage are not in
this first snapshot because adding them honestly would require either new
state capture or speculative interpretations.

`RuntimeEvent` is the structured companion to the established string status
API. `Application.fire_status_event()` still updates `status`, `status_events`,
and UI callbacks while also recording an informational structured event.
Selected initialization failures, Qmix refusal guidance, TEC disabled/simulated
warnings, and v3 shadow-preflight failures carry structured severity and
operator guidance. This is incremental compatibility work, not a conversion of
every historical status string.

`experiment_planning.py` defines `ExperimentRequest`, `RunPlan`,
`PreflightIssue`, `PreflightResult`, and `BuildResult`. During this milestone,
the existing `qt_ui.py` builder remains authoritative for execution. The shared
plan wraps those actual `Experiment2` objects and normalizes them for shadow
comparison. V3 renders the shared preflight and snapshot but still invokes the
inherited production Start path. It must not block or alter that path until the
shadow comparison has broader evidence.

## TEC run provenance

Every `Experiment2` TDMS record retains the backward-compatible `TECTarget`
field and records `TECRequested`, `TECEnabled`, and `SimTEC`. It now also
records `TECTargetCh1` and `TECTargetCh2`. A legacy scalar target broadcasts to
both metadata fields; an unlocked run records each channel's requested target
separately. These are requested targets. They are not applied setpoint
readbacks, measured object temperatures, or evidence that a real controller was
used. `TECEnabled` and `SimTEC` are captured from live facade state at run time,
so disabled and simulated runs remain distinguishable.

No TEC protocol read or write changed as part of this metadata extension.

## Camera defaults and experiment overrides

`ExperimentCameraDefaults` is an adapter over the existing camera widgets. It
owns the common pulse-mode, source, interval, burst, trigger-source, polarity,
delay, and ROI values used by both manual and automated sequence construction.
Experiment `Frames` and the automated `Internal` trigger source remain explicit
overrides. ROI remains a separate camera geometry value and is not conflated
with the exposure time freshly applied by `Application.run_experiment2()`.
There is still one set of editor widgets and no new applied-device-state claim.

## P0 bench procedures

The procedures below are ordered to avoid letting one unresolved subsystem
contaminate another. Preserve raw logs, screenshots, serial/adapter identities,
scope captures, timestamps, and the exact git commit for every trial.

### A. DIO1, camera exposure, and AD2 analog timing

Purpose: measure the physical relationship among the programmed DIO1 pulse
train, AnalogOut channel 0, the software PC-trigger call, and a camera exposure
indicator. The current automated camera trigger is `Internal`; therefore this
test must not assume DIO1 triggers the camera.

Provenance for the prepared bounded diagnostic: **Execution path:
PRODUCTION** (`Application.run_experiment2()` and its normal orchestration);
**Configuration basis: DIAGNOSTIC** (low-amplitude, one-repeat scope setup).
The configuration basis is not the normal scientific production configuration.

Preconditions:

1. Pump, valve, TEC, and Z stage disabled. Do not initialize them.
2. Real AD2 and camera only, with the existing action-gated hardware-test
   process reviewed by the operator. Use a non-acoustic load or disconnected
   transducer for the 0.10 V diagnostic waveform.
3. Connect all scope grounds to the same approved reference. Confirm the
   camera's exposure-active/trigger-monitor connector and voltage level from
   its model-specific manual before connecting it; do not guess a pin.

Oscilloscope prerequisite and control boundary:

The oscilloscope is an operator-controlled external measurement instrument.
The repository does not need to control it, and no VISA/SCPI/vendor scope
integration is required for this first bounded timing test. Before any output,
the operator must identify the actual scope (manufacturer, model, analog
channel count, supported waveform-export method, input impedance/termination
options, probe types, and external storage or PC-connection method). Use the
current official vendor documentation for the exact capture/export procedure;
do not infer generic front-panel menu paths.

Scope channels for the first capture:

| Scope input | Connection |
| --- | --- |
| CH1 | AD2 DIO1, the configured digital pulse train |
| CH2 | AD2 W1 / AnalogOut channel 0 through a suitable probe/attenuation |
| CH3 | Camera exposure-active or trigger-monitor output, only after the exact connector and electrical limits are verified |
| CH4 | Unused; no marker is required for this capture |

Use one common oscilloscope timebase and capture the three required signals
simultaneously. Record channel labels, coupling, probe attenuation, input
impedance/termination, volts/div, offsets, horizontal timebase, trigger source,
trigger level, trigger edge, and sample rate/record length when available.
Retain the scope's raw waveform export whenever possible, using the official
vendor PC software if that is how the scope exports data. CSV or equivalent
numeric data, native waveform format plus screenshot, and screenshot alone
(only when raw export is genuinely unavailable) are acceptable evidence.
Record the timestamp, software commit, requested settings, and the applied /
read-back Camera TIMING 1 state with the retained evidence. Physical edge
measurements must come from the retained scope data, never from source-code
reconstruction.

Use one repeat with: channel 0 enabled, sine 1.000 kHz, 0.10 V amplitude,
0 V offset, 0.50 s run; channel 1 disabled; Camera FPS 10; Camera Start
0.20 s; Frames 5; Exposure 10 ms; dynamic frequency and dynamic camera start
off; flush and TEC scan off; camera trigger source left at the automated
`Internal` override. Save to a new, explicit output directory.

Expected software order is: configure WFG, configure DIO1, apply camera
exposure, configure camera sequence, configure global exposure, start camera
capture, call `ad2.pc_trigger()`, acquire frames, stop capture, then wait for
the AD2 completion budget if required. The requested DIO1 period is 100 ms,
its requested pulse-train duration is 0.50 s, and its programmed `sec_wait` is
0.20 s. The code alone does not establish whether `sec_wait` is measured from
configuration or the later PC trigger, nor whether channel 0 waits for that
trigger.

Measure and retain:

- first/last DIO1 edges, period, pulse count, and train duration;
- first/last AnalogOut edges and duration;
- camera exposure edges and interval, if the monitor output is available;
- host timestamps immediately before/after `pc_trigger()` from an
  instrumentation-only capture if available, clearly labeled host time rather
  than scope time;
- relative deltas between the physical traces, plus scope timebase/trigger and
  probe settings.

The first bounded capture may establish the timing semantics and observed
relationship for that capture: each visible physical output can be compared
with its programmed period/duration, and the measured ordering can be recorded.
That single capture does **not** establish repeatability, jitter, or general
performance. Those require a separately planned characterization; they are not
a prerequisite for this first safe diagnostic. Equivalence between DIO1 and
camera exposure requires measured exposure edges with a defined tolerance;
DIO1 alone cannot prove it. If AnalogOut starts at
configuration rather than PC trigger, or camera exposure is unrelated to
DIO1, record that result as the actual semantics and stop—do not change timing
code in the bench session.

### B. Valve P01/P02 physical routing

Purpose: map protocol positions to the tubing without pump motion.

1. Confirm the valve is on COM5 for this bench, the pump is disabled and not
   initialized, and no pressure source can drive fluid unexpectedly.
2. Use air or a small amount of harmless visible fluid at safe ambient
   pressure. Label every physical port before switching.
3. Run the manual-only DTR/RTS-aware valve probe with `p01_cr`, explicit
   `--confirm SEND`, and `--read-response`; then run `status_query` and retain
   the raw `S\r` response. Record audible/visual movement and which ports are
   connected.
4. Repeat as a separate invocation for `p02_cr`, followed by a fresh
   `status_query`. Do not infer routing from the numeric reply alone.
5. Repeat each position once to establish reproducibility. Stop for leakage,
   unexpected pressure, unknown replies, or disagreement between the command,
   status reply, and observed path.

No pump action is part of this procedure. The result is physical only when the
observed fluid/air path is recorded; otherwise it remains protocol-only.

### C. Qmix/CAN ownership and no-motion reliability

Purpose: separate physical CAN, adapter/driver/service, stale ownership, and
controller state before any reference or motion test.

For each of three to five trials:

1. Close all Python UIs, LabVIEW, QmixElements, and other known Qmix clients.
   Record the process list and verify a single intended client.
2. Record the exact Qmix project/configuration path, adapter model/serial/USB
   location, installed driver/service versions, node ID, bitrate, heartbeat or
   life-guard settings, and available CAN error counters/event log.
3. Use `hardware_tests/test_qmix_discovery.py --start-communication` with the
   exact reviewed configuration. It may open/start, enumerate, read passive
   identity/status, stop, and close. It must not enable, clear a fault,
   reference, aspirate, dispense, or move.
4. Timestamp open/start/first status/stop/close; save all faults and counters,
   including `0x8120`, `0x8130`, and `0x81FF`, rather than treating later
   recovery as success.
5. Verify the adapter is released and QmixElements can subsequently open the
   same project without stale ownership. A trial passes only if every phase and
   release is clean; any transient fault is a failed reliability trial even if
   the bus later recovers.

Only after the CAN/ownership trials are clean and reviewed should a separate
motion plan be approved: confirm the exact syringe, geometry, safe fluid route,
and available travel; perform reference; compare reported fill/position to the
physical state; then request one bounded low-rate, small-volume motion with an
independent stop. That later plan must not be combined with the diagnostic
trials and must not add automatic reconnect/retry or fault clearing.

### D. TEC environment, read-only verification, and controlled writes

Purpose: independently reproduce the protocol evidence while preserving a
known OFF path.

1. Restore the intended `exp_ctrl` environment from
   `requirements-exp_ctrl.txt`, which pins pyMeCom to Git tag `v1.1`; run
   `tools/check_environment.py` and record the installed commit/version.
2. With output stages physically safe, connect read-only to the confirmed port
   candidate. For both instances 1 and 2, retain raw timestamped reads of
   Device Status 104 (device-wide, read once), Error Number 105 only if status
   is Error, Object Temperature 1000, and Output Enable Status 2010. Make no
   writes in this phase.
3. Commit `2da4c8d` includes a dedicated public Static OFF operation that
   writes parameter 2010 value 0 per channel and verifies readback. It is
   fake-tested; the 2026-08-28 live
   read-only probe found both channels already OFF, so no real OFF write was
   sent. Do not start the controlled write phase until this local safety
   capability and its cleanup behavior have been reviewed and approved.
4. For an approved controlled write, choose a target within the validated
   range and close to the measured object temperature. The only permitted
   writes remain parameter 2010 (OFF/ON) and parameter 3000 (target), by name,
   never raw access. Verify both channels independently and always finish with
   2010=0 read back on both channels.
5. If a partial write, exception, timeout, or disconnect occurs after either
   channel is enabled, attempt the reviewed OFF operation for both channels,
   close the client, and verify OFF/readback in the vendor service software.
   If OFF cannot be confirmed, treat the controller as requiring operator
   intervention and do not continue.

## Persistence migration design (not implemented)

Keep `.thermo_acoustic_ui.json` readable as the legacy combined settings file.
Loading it must not rewrite it. Migration occurs only when the operator selects
an explicit Save/Save As target.

The future split should be:

| Artifact | Owns | Must not own |
| --- | --- | --- |
| Hardware Profile | enabled/simulated selections, ports, SDK/config paths, device identity expectations, safe hardware limits | experiment axes, live enabled/output states, last fault/position |
| Experiment Protocol | frequency/camera/flush/TEC requested parameters and scan axes | machine-specific paths, COM ports, SDK locations, observed device state |
| UI Preferences | layout, last browsed directory, non-operational display choices | hardware action state or protocol truth |
| Run Metadata | immutable protocol/profile identity and hash, git revision, requested/applied/observed evidence, timestamps, runtime events | editable future defaults |

An explicit migration dialog should show which legacy fields go to which
artifact, write new files atomically, preserve the original, and refuse unknown
or conflicting fields instead of silently dropping them. A protocol may
reference a required hardware capability but never embed a local SDK path. Live
actions such as pump enabled, valve position, TEC output ON, or an active fault
are runtime evidence and must never become protocol defaults. Only after these
formats and canonical hashing are reviewed should profile/protocol IDs and
hashes be added to TDMS.

## Still unresolved

- DIO1/AnalogOut/PC-trigger/camera exposure timing is not physically measured.
- Valve P01/P02 protocol positions are not mapped to actual tubing routes.
- The Qmix CAN fault sequence and repeated clean open/start/stop/close
  reliability remain unresolved; eventual recovery is not resolution.
- Qmix reference, fill-level truth, and bounded real motion remain separate,
  later checks.
- TEC historical controlled-write claims are not independently reproduced.
  The 2026-08-28 independent read-only probe confirmed communication and both
  channels reporting OFF, while the new Static OFF operation and unlocked
  dual-channel operation remain fake-tested only.
- The shared plan is shadow-only; production Start still uses the established
  builder.
- The persistence split is a proposal only.
