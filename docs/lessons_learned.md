# Engineering handbook — thermoacousticstreaming_python

Durable engineering principles for this project, organized by principle rather
than by incident. Read the relevant part **before** modifying the area it
covers.

This is not a status page and not an incident diary. Current project state is
[`project_control.md`](project_control.md); unresolved work is
[`known_open_items.md`](known_open_items.md); review provenance is
[`audit_index.md`](audit_index.md); durable working boundaries are `AGENTS.md`.

Each principle carries an **enforcement** marker:

| Marker | Meaning |
| --- | --- |
| `ENFORCED` | A production fail-closed gate or an independent regression test exists. |
| `DOCUMENTED` | A stated rule with no automated gate; relies on review discipline. |
| `JUDGMENT` | Requires a human decision; no software control can settle it. |

Concrete examples are kept because they make the rule actionable. Where a lesson
is project-specific rather than generally reusable, it is marked
**project-specific**.

---

## Part 1 — Authority and evidence

### 1.1 One authoritative scientific state, many views — `ENFORCED`

Several UI surfaces may exist, but scientific configuration must have exactly
one authority. The canonical chain is:

```text
ExperimentRequest -> build_independent_run_plan() -> RunPlan / RunCondition
-> legacy_series_from_run_plan() -> Experiment2 / Application -> backends
```

V3 is a presentation/preparation/review layer. There is no second planner, no
second executor, and no shadow scientific state.

### 1.2 UI projections must derive from canonical state, not re-implement it — `ENFORCED`

A presentation layer that recomputes a scientific formula will drift from the
runtime that actually executes it. When V3's timing table computed DIO timing
from widget values instead of the plan, it silently stopped surfacing the
W2-blocked condition that the canonical call had previously exposed. Projections
now read the plan's frozen configuration.

### 1.2b One canonical software event stream, projected many ways — `ENFORCED`

The same rule as 1.1, applied to observability. A live indicator and a durable
trace must consume the **same** event records, not each interpret runtime state
independently — otherwise the screen and the retained evidence can disagree
about what a run did, with no way to adjudicate afterwards. `log_action()` is
that single stream; additional consumers subscribe to it as passive observers.
An observer performs no hardware I/O, never calls back into the stream, and an
observer that fails is swallowed exactly like a failed evidence write.

**Commissioning trace is software evidence and does not establish physical
timing.** Its `monotonic_ns` orders software events and measures software
intervals on one host clock; its wall-clock timestamp is provenance. Neither is
a common-timebase measurement, and no trace event establishes an electrical
edge, optical emission, acoustic pressure, delivered fluid, or cross-instrument
simultaneity.

### 1.3 Evidence classes are not interchangeable — `ENFORCED`

```text
REQUESTED -> PLANNED -> SOFTWARE-EFFECTIVE -> COMMAND_SENT
-> PROTOCOL_ACKNOWLEDGED -> OBSERVED -> PHYSICAL_VERIFIED
```

Never promote a value across a boundary without evidence of that class.
Production action logging currently emits **no** `PHYSICAL_VERIFIED` stage.

Concrete separations that must survive every refactor:

- requested AD2 amplitude ≠ downstream amplifier input voltage;
- downstream voltage ≠ transducer drive ≠ acoustic pressure;
- API trigger configuration ≠ physical edge simultaneity;
- DIO1 electrical state ≠ LED optical emission;
- External-trigger configuration ≠ measured camera exposure timing;
- TEC controller "stable" ≠ sample or imaging-plane equilibrium;
- pump tracked fill ≠ physically delivered volume;
- Z controller readback ≠ calibrated microscope displacement;
- software cleanup calls ≠ physical BNC/DIO pin voltage.

### 1.4 A label may only promise what the software actually does — `ENFORCED`

Operator confirmation counts as preparation evidence **only if it is persisted
as such**. V3's Preparation checkboxes are local presentation state, so the tab
is named "Preparation checklist" and the banner says the confirmations are not
persisted run evidence and not physical verification. Renaming a control is
cheaper than implying an evidence class that does not exist.

### 1.5 Document classes must not be conflated — `DOCUMENTED`

Current authority, current guidance, historical evidence, raw handover
evidence, vendor evidence, audit evidence, quarantined legacy, and recovery
packages each carry different weight. A recovery package or an old audit may
contain confident current-tense sentences that are simply superseded. Preserve
history; do not let it govern.

### 1.6 Later owner truth supersedes earlier owner truth — `DOCUMENTED`

Owner statements are authoritative as workflow truth but are not immutable
physical truth. Record the newer statement as current, label the older
superseded, and do not copy the older mapping into new code or UI. **Project
example:** DIO1/green is LED timing/control, not laser Digital In.

### 1.7 A numeric value needs quantity, unit, reference, and evidence layer — `ENFORCED`

"Amplitude (V)" hid whether the value meant peak, peak-to-peak, RMS, source or
loaded voltage. Keep compatibility field names where readers depend on them,
but pair them with explicit operator labels and additive unit/convention
metadata. **Project example:** internal `repeat_id` is zero-based while operator
messages and folders are one-based; TDMS records both bases explicitly after a
zero-based index leaked into a flush-failure operator message.

---

## Part 2 — Requested versus effective

### 2.1 Keep the request; record the effective value separately — `ENFORCED`

Never overwrite a scientific request with what the device accepted. A 10 V
request clamped to 5 V is retained as requested 10 V **and** software-effective
5 V, with action status `EFFECTIVE` — not `APPLIED`, not `OBSERVED`.

### 2.2 Quantized clocks mean requested ≠ achieved — `ENFORCED`

WaveForms uses an integer DigitalOut divider, so the achieved cadence is always
≥ the requested cadence. This is not a rounding curiosity; it changes counts.

### 2.3 A finite hardware window must be computed from the achieved quantity — `ENFORCED`

**Project example, and the clearest instance of this class.** The canonical
DigitalOut run window was originally `frames / requested_fps`. Because the
achieved frequency is slightly higher, that window spans slightly *more* than N
periods — e.g. 1000 frames at a requested 30 fps spans 1000.0004 periods, so the
run could contain an extra rising edge. The run is now derived from the achieved
DIO0 frequency, which spans exactly N periods. The requested cadence remains the
scientific request; the achieved cadence drives the hardware window.

### 2.4 The same discipline applies beyond DigitalOut — `DOCUMENTED`

Amplitude clamping, WFG frequency clamping, camera exposure quantization,
camera cadence, TEC target versus readback, and Z command versus readback are
all requested-versus-effective pairs. Treat them the same way.

### 2.5 A feasibility gate must protect the achieved quantity, not the request — `ENFORCED`

**Project example.** The External-trigger camera gate compared the *requested*
frame period against `TIMING_MINTRIGGERINTERVAL`, while the camera is actually
paced by the divider-quantized DIO0 cadence, which is faster. A request could
therefore pass a gate that the spacing really programmed would fail. The gate
now uses the software-effective achieved DIO0 spacing whenever a real
`configure_do()` produced one, and falls back to the request rather than
inventing a cadence. This is 2.3 applied to validation instead of to
programming: whatever the device is actually configured to do is the thing a
safety gate must be checked against.

---

## Part 3 — Hardware output lifecycle

### 3.1 Activating a new output surface requires a full lifecycle review — `DOCUMENTED`

Whenever an output becomes part of canonical production, walk the whole
lifecycle before shipping it:

```text
configure -> arm -> trigger -> running -> completion
-> pre-trigger failure -> mid-run failure
-> normal cleanup -> exceptional cleanup -> device close
```

### 3.2 A closed cleanup checkpoint can become incomplete later — `ENFORCED`

**This is the most important process lesson in the project.** Deterministic AD2
AnalogOut cleanup was implemented and independently closed while AnalogOut was
the only production output. A later checkpoint made DigitalOut canonical, which
silently invalidated that closure's premise: the new output had no deterministic
stop/reset. The gap was found only by an integrated review that deliberately
looked *across* checkpoints.

When a checkpoint activates a new capability, re-examine previously closed
checkpoints whose assumptions it changes — a clean per-commit diff will not
reveal this.

### 3.3 Do not rely on device close or default `OnClose` state — `ENFORCED`

The installed WaveForms header documents `DwfParamOnClose` as
`0 continue, 1 stop, 2 shutdown`, and the project never sets it. Explicit
stop/reset before close is therefore required for both AnalogOut and DigitalOut.

### 3.4 API cleanup is commanded behavior, not pin voltage — `DOCUMENTED`

Cleanup tests prove the calls were issued and their failures recorded. Physical
post-close BNC/DIO state remains unverified.

---

## Part 4 — Vendor API fidelity

### 4.1 Model the real API shape, not a convenient one — `ENFORCED`

WaveForms DigitalOut has **instrument-global** Wait/Run/Repeat/TriggerSource
(no channel index in `dwf.h`) and **per-channel** divider/counter/type/idle
state. The SDK manual states the state machine "controls all digital out
channels".

Consequences that must be preserved: DIO0 and DIO1 share one wait/run/repeat/
trigger signature while retaining independent divider and counter settings; the
backend refuses divergent per-channel trigger signatures rather than silently
applying the last one; and planners must not invent independently clocked DIO
channels.

### 4.2 Do not add configuration a fake accepts but the device ignores — `ENFORCED`

The SDK manual documents that when one counter side is zero the level is not
toggled. DIO1's finite high window is therefore the simple `High=1 / Low=0`
idiom. An earlier `High = frames*2` value was inert — the device never consumes
it — while adding an unnecessary counter-range failure mode. A fake backend
accepting a value is not evidence the device uses it.

### 4.3 One PC trigger is a logical origin, not physical simultaneity — `ENFORCED`

`FDwfDeviceTriggerPC` "generates one pulse on the PC trigger line"; every
instrument armed on `trigsrcPC` responds. That establishes a single software
logical t=0 for the prepared API paths. It establishes nothing about physical
edge alignment.

### 4.4 External-trigger acquisition is a complete device state — `ENFORCED`

Setting `TRIGGERSOURCE` alone is not "external triggering". For the installed
ORCA-Fusion BT `C15440-20UP`, canonical acquisition explicitly establishes
**source, polarity, active mode, trigger mode, trigger count, and trigger
delay**. Two of the required values are non-default on this model
(`TRIGGERSOURCE` defaults to INTERNAL, `TRIGGERPOLARITY` to NEGATIVE), so the
settings are load-bearing.

### 4.5 Persistent device state may have been set by other software — `ENFORCED`

Vendor applications and manual tools can leave a camera in a mode the canonical
run depends on. A canonical run must establish every property whose value it
relies on, not inherit it.

### 4.6 Timing validation must match the active operating mode — `ENFORCED`

The `max(exposure, readout)` overlap model is the C15440-20UP **free-running /
Internal** relationship. It cannot simply be carried over after acquisition
moves to External trigger. The vendor exposes purpose-built read-only
properties — `TIMING_MINTRIGGERINTERVAL`, `TIMING_MINTRIGGERBLANKING`,
`TIMING_READOUTTIME` — and the External path now gates on the minimum trigger
interval while the Internal path keeps the overlap model.

### 4.7 Prefer vendor readback properties over guessed constants — `DOCUMENTED`

If the device will tell you its own limit, ask it. An unreadable limit must fail
closed, exactly as an unreadable readout time already does.

---

## Part 5 — Concurrency and data ownership

### 5.1 Start from ownership, not from threads — `ENFORCED`

Decide who owns each piece of state before deciding what runs concurrently.

### 5.2 A hardware worker must not own scientific evidence state — `ENFORCED`

The repeat-refresh worker owns fluidics actions and returns a structured
result. It never touches `Experiment2` or TDMS. The main thread is the **sole
TDMS writer**, which matters because `_write_tdms()` is a whole-file rewrite: a
second writer would cause lost updates, not merely interleaving.

### 5.3 Concurrent branches need an explicit rendezvous — `ENFORCED`

Save and flush may overlap, but the worker is joined in a `finally` before the
repeat's outcome is finalized and before the next repeat can start. No orphan
worker, and no next repeat while either branch is live.

### 5.4 Background hardware workers must not drive Qt callbacks — `ENFORCED`

The worker receives no progress callback. All `step_started` / `step_completed`
/ `step_failed` events are emitted on the main thread, before the worker starts
and after the join.

### 5.5 Context must be propagated into worker threads deliberately — `ENFORCED`

Python `ContextVar` state is **not** inherited by new threads. Run/condition/
repeat identity reaches the flush worker through an explicit
`copy_context()` + `ctx.run(...)`, and the action log append is lock-serialized.

### 5.6 Failure classes must remain separately representable — `ENFORCED`

Save failure and flush failure are distinct, recorded as `PrimaryFailure` and
`CleanupFailure`. A flush failure must never suppress saving acquired
scientific data.

---

## Part 6 — Sequence-level lifecycle

### 6.1 Sequence-level obligations must not be re-initialized at subgroup boundaries — `ENFORCED`

**Project example.** The one automatic initial refresh belongs to the whole
experimental sequence, not to each temperature group. When the aggregate
volume preflight was first added, each temperature group re-charged another
initial flush, so a sequence sized exactly to the correct
`TotalExperiments + 1` requirement was falsely rejected at group 2.

### 6.2 Charge a resource at the same lifecycle level that owns it — `ENFORCED`

The fix was not a special case: the preflight now charges the initial refresh
using the same predicate that *arms* it. Payment and obligation are structurally
coupled, so they cannot drift apart again.

### 6.3 A subgroup keeps its own remaining-resource check — `ENFORCED`

Removing the double charge must not remove the gate. Each temperature group
still validates its own remaining refresh volume against current tracked fill,
which also catches drift between groups.

### 6.4 Feasibility arithmetic is not physical delivery — `ENFORCED`

Tracked-fill preflight is a software feasibility gate. It says nothing about
fluid actually moving; that remains HW-PUMP-MOTION-001 and HW-VALVE-001.

---

## Part 7 — Operator UI and HMI

### 7.1 Follow experimental chronology, not subsystem ownership — `DOCUMENTED`

The operator workflow is Prepare → Configure → Review → Start → Monitor, not a
tab per software module.

### 7.2 Routine preparation belongs in the routine path — `DOCUMENTED`

Environment/temperature, sample/fluidics, imaging/focus, manual optics, and
acoustic readiness are routine. Engineering and recovery controls belong in
Manual & Service; passive detail belongs in Diagnostics.

### 7.3 Shared UI inheritance makes small changes cross-surface changes — `ENFORCED`

V3 inherits shared widget state and builders while overriding layout. A change
that looks like presentation in one surface can remove behavior in another —
this previously lost the Qmix fault-clear affordance. Use
`tools/audit_change_surface.py` for shared UI/runtime edits.

### 7.4 Wheel safety belongs at the widget event boundary — `ENFORCED`

Focus policy does not fix it: Qt delivers wheel events to the widget under the
pointer. Shared numeric factories create wheel-safe spinbox and combo
subclasses.

### 7.5 A requested waveform preview must never look measured — `ENFORCED`

Monitor's waveform is a requested/computed preview. Measured rate and physical
telemetry remain separate and are never inferred.

### 7.6 A live indicator projects the canonical event stream — `ENFORCED`

V3's persistent Execution line shows run state, condition/repeat context, the
current software action, the next known software action, and trace state. Every
one of those is read from the canonical progress/event stream the runtime
already emits. It owns no timer and never derives a phase from elapsed wall
time: a second timing state machine in Qt would eventually disagree with the
runtime, and the operator would have no way to tell which one was lying.

### 7.7 An indicator may only claim what the software observed — `ENFORCED`

"PC trigger command sent", not "W1 triggered". "Waiting for the software
output-completion barrier", not "acoustic output has ended". "DIO1 LED timing
program active in software", not "LED is illuminated". When AD2 is disabled and
no trigger is issued at all, the capture wording says so instead of reusing the
trigger phrasing. Cleanup and error states stay on the line after a run stops
rather than reverting to idle before the operator can read them.

---

## Part 8 — Test quality

### 8.1 A regression test must be able to fail — `DOCUMENTED`

Before accepting a test as evidence, establish that it fails against the
pre-correction behavior. This has repeatedly been the difference between a real
guard and a decorative one.

### 8.2 Substring assertions are dangerous when negation changes meaning — `ENFORCED`

**Project example.** A V3 tooltip was corrected by replacing its trailing
clause but left the leading "does not". The resulting sentence said the exact
opposite of the truth — and the test `assert "shared DIO wait" in tooltip`
passed on it. Direction-sensitive assertions are now used: assert the positive
claim **and** assert the negation is absent.

### 8.3 Constructor tripwires prove a gate runs before construction — `ENFORCED`

The Qmix tool tests replace the backend symbol with a tripwire that raises on
construction, so "patched the wrong thing" and "instantiated after the dangerous
point" are structurally impossible.

### 8.4 Mutual event handshakes prove real overlap — `ENFORCED`

The save/flush concurrency test uses two `threading.Event`s with mutual waits: a
serialized implementation deadlocks and fails rather than quietly passing.

### 8.5 Assert call order, not merely call presence — `ENFORCED`

Arm-before-trigger sequencing is asserted with explicit index ordering plus an
exact count of `pc_trigger` calls.

### 8.6 Test names must describe what is actually asserted — `DOCUMENTED`

If a test named `..._without_horizontal_overflow` no longer asserts overflow,
either restore the assertion or rename the test.

### 8.7 Never make an assertion tautological and still call it protection — `DOCUMENTED`

Changing a layout size policy so that a scroll area can never report overflow
makes the overflow assertion unfalsifiable. Fix the layout or change the claim;
do not neutralise the measurement.

### 8.8 Fake backends must model real vendor constraints — `ENFORCED`

A fake that accepts an API shape the device does not have converts a passing
test into false confidence. Where a fake invents vendor enum names, verify those
names against the installed SDK module — for the camera trigger property set
this was checked directly against the vendored `dcamapi4.py`.

### 8.9 Fake success is not physical evidence — `DOCUMENTED`

The simulated camera returns N frames regardless of trigger source. Offline
tests therefore provide **zero** evidence that physical DIO0 edges produce the
intended number or timing of real exposures.

---

## Part 9 — Review discipline

### 9.1 AI review output is a hypothesis, not authority — `DOCUMENTED`

Findings must be reconstructed from current source before being acted on.
Agreement between AI-generated reports is not independent evidence.

### 9.2 A material finding must answer six questions — `DOCUMENTED`

1. What current requirement does it violate?
2. Where exactly in source?
3. What independent evidence supports the requirement?
4. What concrete consequence follows?
5. Is that consequence reachable on the canonical path?
6. Is it already intentionally deferred?

If any answer is missing, classify as nonblocking or insufficient evidence
rather than inflating severity. A more sophisticated design being possible is
not a defect.

### 9.3 A primary source may legitimately downgrade an earlier finding — `DOCUMENTED`

**Project example.** An earlier review treated the DIO1 `frames*2` counter as
potentially producing a mid-window glitch. The installed SDK manual then showed
that a zero counter side prevents toggling entirely, so the value was inert. The
correction was still right; the severity was not.

### 9.4 Stop broad audits once the architecture is validated — `DOCUMENTED`

Later changes get bounded, focused reviews. Recommending another broad audit for
reassurance is a cost with no evidence attached.

### 9.5 Say `INSUFFICIENT EVIDENCE` — `DOCUMENTED`

Where primary documentation is silent, record that. Do not guess and do not
choose whichever reading supports the desired conclusion.

---

## Part 10 — Vendor research

### 10.1 Prefer exact manufacturer, model, and SDK documentation — `DOCUMENTED`

Installed official SDK headers and manuals are often stronger evidence for this
exact software environment than web search, because they match the version
actually in use. This project has used `dwf.h`, the WaveForms SDK reference
manual, the vendored `dcamapi4.py`, the model-exact
`propC15440-20UP_en.html` property document, and the iBEAM `M-042 v09` manual.

### 10.2 Investigate version drift rather than picking a convenient source — `DOCUMENTED`

If installed and current web documentation disagree, that difference is itself
the finding.

### 10.3 Family-manual facts are not installed-unit configuration — `ENFORCED`

The iBEAM manual documents 0…+5 V analog modulation on channel 2, default `sub`
polarity (increasing input reduces power, so 0 V is not optical off), and a
Digital In that exists only with the pulse option and is inactive by default. It
also documents that external analog modulation opens the microprocessor-to-driver
connection, so RS232 laser ON/OFF may be unavailable. None of this establishes
what is installed in *this* unit.

### 10.4 Do not cite resellers when manufacturer material exists — `DOCUMENTED`

### 10.5 Custom laboratory hardware needs characterization, not identity lookup — `ENFORCED`

**Project-specific.** A mains-powered home-built amplifier cannot be closed by
searching for a model number or reading blurry annotations. Establish only the
minimum envelope needed for the next bounded action: connector roles,
source/load termination, input impedance, gain near the operating frequency,
output/load limits, indicators, transducer identity, and comparable same-chain
history. Old voltage settings from a different apparatus are not current safe
operating evidence.

---

## Part 11 — Checkpoint and Git process

### 11.1 One coherent behavior checkpoint at a time — `DOCUMENTED`

Preferred lifecycle:

```text
bounded implementation -> focused offline tests -> broad offline regression
-> diff review -> commit -> push -> parity 0/0 -> clean tree
-> independent review
```

### 11.2 Keep runtime/backend changes separate from UI and documentation — `DOCUMENTED`

Clean boundaries are what let a later reviewer identify which new feature
invalidated an earlier assumption — see 3.2.

### 11.3 Verify the commit message against the actual diff — `DOCUMENTED`

Every changed file must be accounted for and no message claim may contradict the
staged diff. This rule exists because specific past commits overstated their
coverage or silently included files.

### 11.4 Do not rewrite pushed history for tidiness — `DOCUMENTED`

### 11.5 A completeness claim is itself a claim — `DOCUMENTED`

"A sweep found zero remaining instances" must be true. A narrow search pattern
that misses a differently-worded instance turns a correct fix into an overstated
report.

---

## Part 12 — Multi-agent workflow

### 12.1 Separate orchestration, implementation, and review roles — `DOCUMENTED`

Executor self-review is valuable but is not organizational independence. A
material scientific, hardware, or evidence-boundary conclusion benefits from a
reviewer who did not perform the implementation and who starts from the
repository checkpoint rather than the chat history.

### 12.2 A reviewer should not silently implement what it finds — `DOCUMENTED`

Report precisely, propose bounded corrections, and let authorization be
explicit.

### 12.3 Bounded explicit authorization limits scope expansion — `DOCUMENTED`

Low-risk documentation, UI-text and test cleanups can be delegated under a
strict whitelist. Runtime, backend and hardware-semantic corrections should be
treated conservatively and receive a focused independent closure review.

### 12.4 Disclose deviations rather than absorbing them — `DOCUMENTED`

If an authorized fix reveals an adjacent same-class defect, fixing it may be
correct — but it must be reported as a deviation with its justification, not
folded in silently.

### 12.5 Never allow simultaneous modifying agents in one worktree — `DOCUMENTED`

### 12.6 Material task methods belong in the brief from the start — `DOCUMENTED`

State methodology, acceptance classification and deliverables before execution.
A requirement discovered later must be applied to already-reviewed material when
it changes the conclusion.

---

## Part 13 — Software closure versus physical commissioning

### 13.1 Offline closure is not commissioning — `ENFORCED`

Software can establish configuration, API call ordering, planned timing,
effective divider/frequency, failure handling, and cleanup calls.

Physical commissioning must separately establish electrical levels, actual edge
timing, exposure response, optical response, acoustic output, real fluid
movement, and installed jumper/load state.

### 13.2 Passing offline tests must not hide a physical blocker — `ENFORCED`

A green suite is not progress toward an energized run. HW-ACOUSTIC-CHAIN-001 and
HW-AD2-BNC-001 still block every W1 output.

### 13.3 One bounded capture proves only that capture — `DOCUMENTED`

A single safe scope capture can establish ordering and timing for that capture.
It cannot establish repeatability, jitter, or population behavior; those are
separate questions and must not be folded into the first closure claim.

### 13.4 Diagnostic configuration is not scientific production — `DOCUMENTED`

Execution can be `PRODUCTION` while the configuration basis is `DIAGNOSTIC`. A
diagnostic result must not be reported as validation of the normal scientific
configuration.

### 13.5 Protocol success is not physical verification — `ENFORCED`

**Project example.** Qmix open/start/stop/close lifecycle trials ran cleanly
while `fault=True` persisted; the contemporaneous vendor log later proved real
node emergencies. Correlate passive status with independently timestamped logs
before classifying a fault as active or merely latched. A clear-command
acknowledgement is not recovery.

---

## Lesson-to-control matrix

Material lessons mapped to present controls. "Enforced" requires a production
fail-closed gate, an independent regression test, or an explicit commissioning
stop rule; prose alone does not qualify.

| Lesson | Originating failure and rule | Current prevention mechanism | Independent test/reference | Residual risk |
| --- | --- | --- | --- | --- |
| Code and tests can share a wrong model — `ENFORCED` | FM width was doubled and camera timing added overlapping intervals because tests mirrored implementation. Critical equations need an external anchor and a hard expected case. | Explicit endpoint model; mode-appropriate camera timing gate; review rule requiring independent expectations. | `test_fm_sweep_settings_match_martens_et_al_reference_case`; `test_camera_timing_budget_uses_vendor_overlap_relationship_not_sum`; Digilent/Hamamatsu manuals. | New formulas need the same discipline. |
| Universal quantities differ from device conventions — `ENFORCED` | Digilent FM-node "amplitude" is percent deviation, not communications-theory beta. | Separate modulation-index-percent and modulation-frequency fields; no beta claim. | Endpoint/index tests; installed SDK sample; Keysight FM definition. | Triangle/ramp sweeps are not single-tone FM beta. |
| Post-clamp effective is neither requested nor physical — `ENFORCED` | Records could silently replace requested values. | Immutable request plus separate post-clamp effective object; status stays `EFFECTIVE`. | `test_run_experiment2_records_real_wfg_clamping_in_final_tdms`. | SDK configuration success is not waveform measurement. |
| Specifications are not measurements — `ENFORCED` | Model limits and pixel pitch risked becoming present-device or sample claims. | Specification / configured / observed / physical layers separated in records and readiness gates. | Evidence-stage tests; absence of `PHYSICAL_VERIFIED`; exact manufacturer manuals. | Physical voltage, timing, scale, flow and temperature still need measurement. |
| Source voltage is not loaded or acoustic output — `ENFORCED` | Unknown JP4/load/amplifier chain made an AD2 number look like transducer drive. | Qualified UI/TDMS wording; W1 commissioning hard-blocked. | UI/TDMS convention tests; Digilent BNC schematic. | HW-AD2-BNC-001 and HW-ACOUSTIC-CHAIN-001 remain open. |
| Command success is not physical success — `ENFORCED` | Valve/Qmix acknowledgements did not prove routing, fluid, or recovery. | Bounded evidence taxonomy; fresh readbacks where available; physical claims gated. | Flush sequence/failure tests; retained Qmix evidence. | Delivery, route, pressure and optical power remain unverified. |
| Connected wiring does not authorize active drive — `ENFORCED` | Historical generic DIO and "unused CH2" stories conflated destination with software use. | Canonical production programs DIO0/DIO1 only as the bounded camera/LED trigger program; the generic legacy DO-clock configuration is cleared for non-canonical records; W2 requests fail before hardware; W1 requires explicit enable. | `test_application_rejects_laser_w2_output_before_hardware`; `test_run_experiment2_does_not_program_or_record_legacy_do_clock`. | Electrical/optical effect of either DIO line remains unverified. |
| Camera timing follows acquisition architecture — `ENFORCED` | Exposure-plus-readout addition contradicted overlapping free-running behavior; the Internal model then had to stop being reused for External trigger. | Internal path uses the overlapping limit; External path gates on fresh `TIMING_MINTRIGGERINTERVAL`; unavailable readback fails closed. | Timing-budget and External-gate tests; Hamamatsu model property document. | Other trigger/scan modes must be re-derived; no physical synchronization claim. |
| A newly activated output invalidates old cleanup closure — `ENFORCED` | DigitalOut became canonical after AnalogOut-only cleanup had been closed. | Cleanup stops and resets AnalogOut channels 0/1 **and** DigitalOut before device close, with independent per-operation error capture. | `test_ad2_cleanup_attempts_digitalout_stop_reset_and_close_after_digitalout_failures`. | Physical post-close pin state remains unverified. |
| Sequence-level obligations are not subgroup obligations — `ENFORCED` | Temperature groups re-charged the sequence's single initial refresh. | The initial-refresh charge uses the same predicate that arms it; subgroups still validate their own remaining volume. | `test_temperature_group_setup_does_not_recharge_the_consumed_sequence_initial_flush`. | Tracked fill is not delivered volume. |
| Historical values are not commissioning settings — `ENFORCED` | Lund 3 Vpp, prior 0.1 V and a 2 V screenshot lack same-chain/load semantics. | Readiness gate rejects all as a present starting amplitude; UI defaults confer no permission. | Literature/manual provenance comparison; preflight/output gates. | Owner must provide same-chain evidence or bounded characterization. |
| UI/preflight is not execution authority — `ENFORCED` | A parallel presentation model could drift into a second plan. | Start rebuilds the independent immutable plan; V3 projects planner/runtime/action evidence. | V3 shadow-plan and shared-preflight tests. | Presentation can lag; source and action evidence remain authoritative. |
| Internal indices and operator counts differ — `ENFORCED` | Zero-based `repeat_id` leaked into an operator message. | Operator logs/folders use one-based numbers; TDMS records both bases. | Repeat-1 flush-failure test; TDMS identity test. | Compatibility `Repeat ID` stays zero-based. |
| Software chronology is not physical timing — `ENFORCED` | UTC/monotonic logs could be overread as synchronization. | Evidence model limits them to chronology and timeout diagnosis. | Deterministic timing tests. | HW-TIMING-001 remains open; no jitter or synchronization claim. |

---

## Deliberately not adopted

No lesson was imported from a sibling repository. No external naming, hardware
assumption, timing threshold, or governance convention was adopted without local
evidence. This handbook does not add a generic best-practice catalogue or a
second rule taxonomy.
