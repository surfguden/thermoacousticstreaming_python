# Lessons learned — thermoacousticstreaming_python

Project: `C:\git\thermoacousticstreaming_python` (`junjiebranch`). This is
project-specific institutional memory for the Python conversion of the
thermoacoustic streaming experiment, including its AD2/WFG, Hamamatsu DCAM,
Qmix, valve, TEC, and v1/v2/v3 UI paths. It is not a replacement for
`AGENTS.md`, `docs/project_control.md`, the hardware truth records, or the
known-open-items register.

Each entry records the current enforcement location. A classification of
`HISTORICAL_ONLY` means the lesson is retained for judgment and is not itself
an automated control.

## Lessons from this repository

### Fresh repository truth outranks stale conversation

Several maintenance passes found that earlier conversational claims no longer
matched the checkout. In particular, v3's role changed during the tracked
history: it became an opt-in tracked UI while v1 remained the default and v2 a
rollback/reference surface. The repository reconciled this in commit `da4a790`
and `docs/v1_downgrade_assessment.md`. Current branch state, tests, CI, and
retained evidence must therefore be re-read before acting on an old task
summary.

Enforcement: `PROJECT_CONTROL` (`docs/project_control.md`) and
`HISTORICAL_ONLY` (the assessment/history).

### A live register must not double as the project archive

Before the September 2026 convergence, `project_control.md` and especially
`known_open_items.md` accumulated completed milestones, superseded wiring
assumptions, investigation narrative, and genuine current gates in the same
current-tense surface. The facts were mostly preserved, but a new engineer
could not reliably tell what to do next or which closed investigation should
stay closed. Current truth now lives in the compact project dashboard; only
genuine unresolved/deferred items remain in the open register. Point-in-time
audits, retained run evidence, Git history, and changelogs preserve the trail.

Enforcement: `PROJECT_CONTROL`, `KNOWN_OPEN_ITEMS`, and `HISTORICAL_ONLY`.

### A physical connection's software role must retain its evidence boundary

Earlier documentation alternated between treating CH2/DIO1 as unused and
treating a generic DO clock as active camera/LED timing. Current owner truth is
W2 -> laser Analog In/control, DIO0/pink -> camera `EXT.TRIG`, and DIO1/green
-> LED timing/control; the earlier DIO1 -> laser Digital In statement is
superseded historical truth. Canonical production now plans finite
PC-triggered DIO0 camera pulses and a DIO1 LED window, while W2 remains
disabled. The durable lesson is to retain both routing and evidence boundaries:
“connected,” “configured,” “commanded,” and “verified effect” are different
states, and API trigger configuration does not establish physical timing.

Enforcement: `PROJECT_CONTROL`, planner/runtime fail-closed tests, and
`HUMAN_JUDGMENT` for physical claims.

### Injected fake WaveForms objects must exercise the vendor-loader boundary

Commit `ba25e27` fixed a real offline-test defect: `WaveFormsBackend(dwf=fake)`
still resolved/loaded `dwf.dll` before the injected object was useful. The
failure was exposed by clean GitHub offline CI rather than by a local test that
only asserted the fake's later calls. Constructor injection is only a complete
offline seam when vendor-library discovery is bypassed and that behavior is
tested directly.

Enforcement: `TEST` (`tests/test_application.py`) and `CI`
(`.github/workflows/offline-ci.yml`).

### Deterministic behavior is stronger than wall-clock scheduling assertions

The serial regression once relied on a timeout-duration/wall-clock assertion.
That produced a false CI failure because scheduler timing was not the behavior
under test. Commit `525894f` replaced it with a fake port that raises exactly
when the old implementation enters the blocking branch, proving the protocol
terminator is consumed without waiting. Time budgets remain useful evidence;
they are not a substitute for a deterministic behavioral seam in offline CI.

Enforcement: `TEST` and `CI`.

### Protocol success is not physical verification

The valve status handshake and Qmix open/start/stop/close lifecycle provide
protocol or transport evidence, not proof of tubing routing, fluid movement,
fault-free readiness, or safe motion. The 2026-08-28 Qmix record showed three
clean no-motion lifecycle trials while `fault=True` remained in all three.
On 2026-09-02, five more clean cycles again retained the fault; the raw
last-error API alone was ambiguous, but the contemporaneous CETONI/Qmix log
proved fresh `0x8120 -> 0x8130 -> 0x81FF` node emergencies during trial 1.
Correlate passive status with independently timestamped retained logs before
classifying a device fault as active or merely latched. H2B then established a
different boundary: all five startup faults cleared through the accepted
vendor call and remained false during bounded no-motion observation, while
enabled and pumping stayed false. An initial startup fault is not by itself a
persistent hardware failure; a clear-command acknowledgement is not recovery;
recovery requires fault-false delayed readback without a post-clear nonzero
emergency. That evidence still does not establish pump-motion readiness.
Likewise, a valid TEC response is not evidence that a target was applied.

Enforcement: `PROJECT_CONTROL` and retained hardware truth records; final
classification of a physical claim requires `HUMAN_JUDGMENT` at the bench.

### Camera visibility does not establish camera timing

On 2026-08-28, Windows PnP, the vendor sample, and the repository backend all
identified camera `C15440-20UP`, S/N `500478`, and a read-only open/close
succeeded. A separate read-only query found `TIMING 1/2/3` fixed LOW. This
removed the visibility blocker but did not establish exposure timing or DIO1
relationship. Scope wiring, load/grounding, and any temporary exposure-output
configuration remain operator-confirmed prerequisites.

Enforcement: `PROJECT_CONTROL`, `HUMAN_JUDGMENT`, and manual-only
`hardware_tests/` gates.

### TEC read-only state and Static OFF are different evidence classes

The earlier read-only TEC observation found both channels already OFF. The
later authorized 2026-08-28 Static-OFF check used the shared path to write only
parameter 2010 = 0, read both channels back OFF, and close cleanly. The first
is observation; the second is a narrowly authorized applied-operation result.
Do not merge these into a broad claim about target, PID, calibration, or
persistence behavior.

Enforcement: `PROJECT_CONTROL`, `TEST`, and retained TEC truth records.

### Shared UI inheritance makes small changes cross-surface changes

v2 and v3 inherit shared widget state and WFG builders but replace layout
builders and selectively override panels. The v3 history records a real loss of
the Qmix fault-clear affordance when a panel was rebuilt. The current v1/v2/v3
tests and `tools/audit_change_surface.py` exist because a change that looks like
presentation in v1 can bypass or remove behavior in v2/v3.

Enforcement: `TEST`, `TOOL`, and `HUMAN_JUDGMENT` for shared-boundary review.

### Dynamic project facts belong in project control, not durable agent rules

Commit `da4a790` moved current milestone, UI roles, CI state, and hardware
status out of `AGENTS.md` into `docs/project_control.md`. Durable repository
working boundaries remain in `AGENTS.md`; facts that change as evidence arrives
belong in the project-control dashboard and truth records.

Enforcement: `RULE` and `PROJECT_CONTROL`.

### Diagnostic configuration is not automatically scientific production

The prepared timing procedure uses the production orchestration path but a
small diagnostic configuration (for example, a low-amplitude bounded waveform,
limited frames, and explicit scope traces). That distinction must remain in the
record: execution can be `PRODUCTION` while configuration basis is
`DIAGNOSTIC`. A diagnostic result must not be reported as validation of the
normal scientific configuration.

Enforcement: `PROJECT_CONTROL` and retained evidence metadata.

### A single bounded timing capture proves only that capture's relationship

One safe scope capture can establish the observed ordering and timing
relationship among the configured signals for that capture. It cannot by itself
characterize repeatability, jitter, or population-level performance. Those are
separate follow-up questions and must not be silently added to the first
closure claim.

Enforcement: `PROJECT_CONTROL` and `HUMAN_JUDGMENT`.

### WFG parameters have presentation, stored, and effective-output states

The September 2026 offline WFG milestone confirmed that the six exposed
functions are DC, Sine, Square, Triangle, RampUp, and RampDown. Digilent DC
semantics make Offset the DC level; frequency, amplitude, symmetry, and phase
are irrelevant. The shared policy now disables and labels those controls,
preserves their stored values for Sine → DC → Sine switching, prevents
frequency-derived scan/sweep use for DC, and makes backend writes conditional.
The effective metadata is recorded separately from retained requested fields.

Enforcement: `TEST` and `CI`; policy in `src/thermo_acoustic/ad2.py` and
backend boundary in `src/thermo_acoustic/waveforms.py`.

### Wheel safety must be enforced at the widget event boundary

The repeated mouse-wheel regression was not fixed by focus policy: Qt delivers
wheel input to the widget under the pointer, and the old app-wide guard allowed
focused numeric controls through to native `stepUp`/`stepDown` handling. The
shared numeric factories now create wheel-safe spinbox subclasses, and the
existing intent for parameter selectors is applied to combo boxes too. Direct
wheel-event tests cover focused/unfocused controls, keyboard editing, v1/v2/v3
surfaces, and dynamically built fields.

Enforcement: `TEST`, `CI`, and shared implementation in `qt_ui.py`.

### Numerical agreement between code and tests is not semantic validation

The original FM factor-of-two error and the camera exposure-plus-readout timing
gate were both internally coherent: tests repeated the same model as production.
A critical conversion needs an external semantic anchor and at least one hard
reference case whose expected result is not calculated by the production
helper. Vendor/API examples establish device formulas; SI/metrology and
cross-vendor checks expose overloaded terms such as amplitude and modulation
index.

Enforcement: `TEST` with cited reference cases and `PROJECT_CONTROL` parameter
semantics.

### A numeric value needs quantity, unit, reference, and evidence layer

“Amplitude (V)” hid whether the value meant peak, peak-to-peak, RMS, source, or
loaded voltage. Legacy fields without unit suffixes similarly hid seconds and
index bases. Keep compatibility names when necessary, but pair them with
explicit operator labels and additive convention/unit metadata. Requested,
post-clamp software-effective, device-configured/readback, and physically
measured values must remain separately named.

Enforcement: `PROJECT_CONTROL`, UI labels/tooltips, TDMS convention fields, and
independent persistence tests.

### Timing arithmetic must follow acquisition mode, not intuition

Exposure and readout can be serial or overlapping depending on camera and mode.
The C15440-20UP Internal/free-running case uses the slower limiting interval,
not their sum. Host UTC and monotonic timestamps describe software chronology;
they cannot validate trigger edges, exposure windows, latency, or jitter on a
shared physical timebase.

Enforcement: exact camera documentation, hard timing tests, and
`PHYSICAL_MEASUREMENT_REQUIRED` for synchronization claims.

### Custom laboratory hardware needs characterization, not a guessed identity

A mains-powered home-built amplifier cannot be closed by searching for a
commercial model number or reading blurry annotations. Establish only the
minimum chain envelope needed for the next bounded action: connector roles,
source/load termination, input impedance, gain/transfer near the operating
frequency, output/load limits, indicators, transducer identity, and comparable
same-chain history. Model limits and old voltage settings are not current safe
operating evidence.

Enforcement: `PROJECT_CONTROL`, powered-down owner/lab inspection only, and a
separately reviewed bounded characterization plan if build records are absent.

### Later owner routing truth supersedes earlier owner routing truth

Historical owner statements remain provenance, but they are not immutable
physical truth. Record the newer statement as current authority and label the
older statement superseded; do not copy the older mapping into new code or UI.
For this apparatus, DIO1/green is LED timing/control, not laser Digital In.

Enforcement: `PROJECT_CONTROL`, `KNOWN_OPEN_ITEMS`, and current implementation
reviews.

### Canonical execution outranks rollback-builder descriptions

Handover claims about “current implementation” must be checked against the
normal `ExperimentRequest -> RunPlan -> legacy adapter -> Application` Start
path. A rollback-only builder can preserve useful design provenance without
describing current production behavior.

Enforcement: current source/tests before any implementation claim.

### Hardware work and durable evidence writing have separate owners

A future flush worker may do hardware-only work and return a structured result;
the canonical rendezvous/finalizer can then persist `FlushCompleted` and outcome
evidence. This is a design candidate, not current concurrency behavior.

Enforcement: future worker lifecycle and TDMS single-writer design review.

### Laser Analog In voltage is not an optical-off claim

The iBEAM family manual documents 0...+5 V Analog modulation on channel 2 and
default `sub` polarity, where increased input reduces power. Therefore 0 V is
not generic optical off, and zero-offset bipolar AD2 drive can be out of range
without installed-unit polarity/configuration evidence.

Enforcement: vendor/manual review and bounded future laser-control design.

## Lesson-to-control matrix

This maps material repository lessons to present controls. “Enforced” includes
a production fail-closed gate, independent regression test, or explicit
commissioning stop rule; prose alone does not qualify.

| Lesson / classification | Originating failure, root cause, and correct rule | Current prevention mechanism | Independent test/reference | Documentation location | Residual risk / commissioning consequence |
| --- | --- | --- | --- | --- | --- |
| Code and tests can share a wrong scientific model — `DOCUMENTED_AND_ENFORCED` | FM width was doubled and camera timing added overlapping intervals because tests mirrored implementation. Critical equations require an external anchor and hard expected case. | Explicit endpoint model; `max(exposure, readout)` gate; review rule requires independent expectations. | `test_fm_sweep_settings_match_martens_et_al_reference_case`; `test_camera_timing_budget_uses_vendor_overlap_relationship_not_sum`; Digilent/Hamamatsu manuals. | This file; `project_control.md` parameter registry. | New formulas still require the same discipline; a newly found material defect pauses hardware continuation. |
| Universal quantities differ from device/API conventions — `DOCUMENTED_AND_ENFORCED` | Digilent FM-node “amplitude” is percent deviation, while standard sinusoidal FM beta is peak deviation/modulation frequency. Preserve both layers by name. | Separate `FMSweepModulationIndexPercent` and modulation-frequency/effective fields; no beta claim. | Endpoint/index tests; installed SDK sample; Keysight FM definition cross-check. | `project_control.md` FM row and electrical closure. | Triangle/ramp sweeps are not universal single-tone FM beta; do not relabel them. |
| Total span, half deviation, period, peak, Vpp, and RMS need conventions — `DOCUMENTED_AND_ENFORCED` | Generic width/amplitude language hid factors of two and waveform dependence. | Explicit start/stop/total/half fields; UI says source peak; tooltip forbids downstream/Vpp/RMS promotion; TDMS convention marker. | FM shape/reference tests; WFG UI and TDMS tests; NIST/Tektronix references. | `project_control.md` registry; UI/tooltips. | RMS conversion remains waveform-specific; loaded voltage remains unmeasured. |
| Post-clamp effective is not requested or physical — `DOCUMENTED_AND_ENFORCED` | Earlier records could silently replace requested values or overstate a command argument. | Immutable request plus separate backend post-clamp effective object; aggregate status stays `EFFECTIVE`; no production `PHYSICAL_VERIFIED`. | `test_run_experiment2_records_real_wfg_clamping_in_final_tdms`; effective-stage assertions. | `project_control.md` evidence model. | SDK configuration success is not terminal waveform measurement. |
| Manufacturer specifications are not measurements — `DOCUMENTED_AND_ENFORCED` | Model limits/pixel pitch were at risk of becoming present-device or sample claims. | Specification, device configured/readback, observed, and physical layers are explicitly separated in records and readiness gates. | Evidence-stage tests and absence of `PHYSICAL_VERIFIED`; exact manufacturer manuals. | `project_control.md` inventory, registry, evidence model. | Physical voltage, timing, object scale, flow, and temperature still need measurement when scientifically required. |
| Source voltage is not loaded or acoustic output — `DOCUMENTED_AND_ENFORCED` | Unknown JP4/load/amplifier chain made an AD2 number easy to mistake for transducer drive. | Qualified UI/TDMS wording; W1 commissioning hard-blocked pending chain characterization. | UI/TDMS convention tests; Digilent BNC schematic and Tektronix load-convention sanity check. | `project_control.md` routing, registry, and readiness. | `HW-AD2-BNC-001` and `HW-ACOUSTIC-CHAIN-001` remain open; no W1 output. |
| Command success is not physical success — `DOCUMENTED_AND_ENFORCED` | Valve/Qmix acknowledgements and controller state did not prove routing, delivered fluid, or recovery. | Bounded evidence taxonomy; fresh readbacks where available; physical claims remain gated. | Flush sequence/failure tests; Qmix no-motion retained evidence. | `project_control.md`; `known_open_items.md`. | Pump delivery, valve route, acoustic pressure, and optical power remain physically unverified. |
| Connected wiring does not authorize active drive — `DOCUMENTED_AND_ENFORCED` | Historical generic DIO/“unused CH2” stories conflated destination with software use. | Production DIO payload is disabled; W2 requests fail before hardware; W1 requires explicit enable. | `test_application_rejects_laser_w2_output_before_hardware`; `test_run_experiment2_does_not_program_or_record_legacy_do_clock`. | `project_control.md` four-layer routing. | Future laser/external-trigger work needs separate semantic closure and authorization. |
| Camera timing follows acquisition architecture — `DOCUMENTED_AND_ENFORCED` | Intuitive exposure+readout addition contradicted C15440-20UP overlapping free-running behavior. | Timing gate uses the slower interval; unavailable readout fails closed; UI states the relationship. | Hard 40 ms/11.22 ms/25 fps test plus boundary/failure tests; Hamamatsu manual and Andor overlap sanity check. | `project_control.md` camera cadence row; this file. | Other trigger/scan modes must be re-derived; no physical synchronization claim. |
| Historical values/defaults are not commissioning settings — `DOCUMENTED_AND_ENFORCED` | Lund 3 Vpp, prior 0.1 V, and a 2 V screenshot lack same-chain/load semantics. | Readiness gate rejects all as a present starting amplitude; UI defaults confer no hardware permission. | Literature/manual provenance comparison; preflight/output gates test software shape, not safety of a voltage. | `project_control.md` electrical closure/readiness. | Owner/lab must provide same-chain evidence or bounded characterization. |
| Custom hardware requires characterization, not model lookup — `DOCUMENTED_AND_ENFORCED` | Current amplifier is home-built; commercial-model searching and blurry labels cannot establish limits. | Minimum characterization envelope and powered-down/mains-disconnected inspection rule. | Owner photographs plus retained build evidence if found; no numeric photo inference. | `project_control.md`; `known_open_items.md` HW-ACOUSTIC-CHAIN-001. | `STILL_OPEN` physical subproblem; blocks every energized W1 action. |
| UI/preflight/status is not execution authority — `DOCUMENTED_AND_ENFORCED` | A parallel presentation model could drift into a second plan. | Normal Start rebuilds the independent immutable plan; V3 is a projection of planner/runtime/action evidence. | V3 shadow-plan parity and shared-preflight tests. | `project_control.md` architecture and V3 model. | Presentation can still lag; source/action evidence remains authoritative. |
| Owner routing truth retains provenance — `DOCUMENTED_AND_ENFORCED` | Photos/owner statements establish current routes but not electrical behavior or measured effect. | Four-layer table labels owner/photo, official, software, and unverified physical claims separately; production disables unresolved routes. | Routing/preflight tests plus official connector manuals/schematic. | `project_control.md`; hardware truth records. | Independent route/termination observation remains required where it affects commissioning. |
| Internal indices and operator counts differ — `DOCUMENTED_AND_ENFORCED` | Zero-based `repeat_id` leaked into a flush-failure operator message. | Operator logs/folders use one-based number; TDMS records both bases explicitly. | Exact repeat-1 flush failure test and TDMS identity test. | `project_control.md` condition/repeat row. | Compatibility `Repeat ID` remains zero-based and must be read with the base fields. |
| Software chronology is not physical timing — `DOCUMENTED_AND_ENFORCED` | UTC/monotonic logs could be overread as trigger/exposure synchronization. | Evidence model limits them to chronology and elapsed/timeout diagnosis. | Deterministic timing tests; physical timing remains a manual-only future gate. | `project_control.md` time/evidence rows; this file. | `HW-TIMING-001` remains deferred; no jitter/synchronization claim. |

## Lessons for future review and Codex tasks

These are retained because they change how high-risk work must be specified and
reviewed; they are not a second project-status register.

### Material task methods belong in the brief from the start — `DOCUMENTED_BUT_NOT_ENFORCED`

If a task has a material scientific, evidence, Git, or hardware boundary, its
methodology, acceptance classification, retrospective-coverage requirement,
and deliverables should be stated before execution. Known mature lessons should
be included at task start. A later-discovered requirement must be applied to
already-reviewed material when it changes the conclusion, rather than being
treated as optional because the first pass predated it.

Control: task brief plus the retrospective-coverage and drift checklists in the
historical audit evidence. Independent check: a final reviewer reruns the
required coverage against the whole knowledge family. Residual risk: a future
task may still omit a requirement or rely on serial steering; this is a process
control, not an automated gate.

### Executor self-review is not organizational independence — `DOCUMENTED_BUT_NOT_ENFORCED`

The executor should perform a complete self-review, but a material scientific,
hardware, or evidence-boundary conclusion benefits from a fresh reviewer who
did not perform the implementation. “PASS” or “VALIDATED” is not sufficient
without the evidence package and the independent challenge opportunity.

Control: explicit independent-review request and reviewer-reconstructable
report. Independent check: a fresh agent starts from the repository checkpoint
without owner chat history. Residual risk: reviewer availability and actual
independence remain organizational matters.

### Critical numerical conclusions require an external anchor and an evidence package — `DOCUMENTED_AND_ENFORCED`

A production/test agreement is not enough when both may share one wrong model.
Important numerical transformations need a first-principles, metrology,
manufacturer/API, or peer-reviewed anchor as appropriate, plus a concise
record of the expected case, sources, checks, and limitations.

Control: cited hard-case tests, source hierarchy, and dated audit reports.
Independent check: reproduce the expected case without calling the production
helper. Residual risk: an anchor can be misapplied if its evidence layer or
acquisition mode is not named.

### Codex autonomy is bounded by explicit scientific, evidence, Git, and hardware rules — `DOCUMENTED_AND_ENFORCED`

Codex may choose implementation details within the authorized task, but must
not infer permission for hardware actions, destructive Git operations, or a
materially different scope. New physical evidence supersedes an old assumption
without rewriting the old record; the current authority must be updated and
the provenance retained.

Control: `AGENTS.md`, current-authority hierarchy, hardware gates, and the
no-stage/no-commit/no-push boundary unless separately authorized. Independent
check: final Git-state and hardware-action accounting. Residual risk: stale
implementation details and manual probes remain searchable and need context.

## Deliberately not adopted

No lesson was copied from a sibling repository, and no sibling-project naming,
hardware assumptions, timing thresholds, or governance convention was adopted
without local evidence. This document does not promote generic best practices,
add another rule taxonomy, or treat another project's camera, pump, valve, or
WFG semantics as applicable here.
