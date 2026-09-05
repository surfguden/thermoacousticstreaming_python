# Known Open Items

This register answers one question: **what is still unresolved?**

Current architecture, workflow, routing, inventory, evidence semantics, and the
next project step are in [`project_control.md`](project_control.md). Durable
engineering principles are in [`lessons_learned.md`](lessons_learned.md).
Review/checkpoint provenance is in [`audit_index.md`](audit_index.md).

No item in this document authorizes hardware. Closed software work is not
repeated here as live backlog; the closed-provenance table at the end exists
only to stop settled questions being reopened by accident.

## Categories

| Category | Meaning |
| --- | --- |
| `BLOCKING_BEFORE_HARDWARE` | Must be closed before the relevant energized/physical action. Stops commissioning now. |
| `PHYSICAL_VALIDATION_PENDING` | Software is sufficiently understood; a physical/electrical claim still needs a separately authorized bench step. |
| `NONBLOCKING_SOFTWARE` | Real software debt that does not block the next experiment. |
| `OWNER_DECISION_REQUIRED` | Evidence cannot choose the policy or product preference. |
| `SCIENCE_VALIDATION` | A scientific method/criterion must be defined before the measurement means anything. |

An item marked "deferred while disabled" is not a prerequisite for the minimal
camera+AD2 run while that capability stays off.

## BLOCKING_BEFORE_HARDWARE

| ID | Boundary | Closure condition |
| --- | --- | --- |
| **HW-ACOUSTIC-CHAIN-001** | `CUSTOM_ACOUSTIC_AMPLIFIER_CHARACTERIZATION_REQUIRED`. Owner photographs confirm a custom/home-built mains-powered enclosure with IEC entry/switch and external coax/BNC-type connectors, but no commercial identity. Blurry annotations are not gain/bandwidth/impedance evidence. External connector roles, controls, approximate input impedance and gain near 1.9–2.0 MHz, output/load envelope, limiting indication, current transducer identity, installed JP4 state, and same-chain starting evidence are all unresolved. | Search retained build/schematic/PCB/component records — not commercial catalogs. If absent, design a separately reviewed bounded electrical characterization. Any internal inspection is owner/lab-only, powered down and disconnected from mains. **Hard blocker: stop before every energized W1 output.** |
| **HW-AD2-BNC-001** | Official SKU `410-263`, schematic `500-263` rev `C.0`, establishes W1/`J4`/`JP4` and W2/`J5`/`JP5`. `JP4`/`JP5` select a direct path or a 49.9-ohm **series-source** path; they are not 50-ohm shunt loads. Installed PCB revision and jumper positions are unverified. | During a powered-down authorized inspection, retain readable PCB/jumper evidence. Combine the installed series path with the exact downstream input impedance to derive or later measure loaded voltage. Blocks energized W1 together with HW-ACOUSTIC-CHAIN-001. |

## PHYSICAL_VALIDATION_PENDING

| ID | Boundary | Closure condition |
| --- | --- | --- |
| **HW-TIMING-001** | Canonical runtime plans W1/DIO0/DIO1/camera around one PC-triggered software logical t=0, derives the finite DigitalOut run from the achieved DIO0 cadence, and applies External-trigger camera property and timing gates. **The software corrections are closed.** Unmeasured: electrical levels, actual DIO0 edge timing and edge count at the run boundary, first-edge phase, DIO1 electrical window, camera trigger recognition and exposure latency/jitter, LED optical latency, cross-signal alignment on a common timebase, and post-cleanup pin state. | Separately authorized electrical/timing validation with explicit camera mode/polarity and one common-timebase observation. No physical synchronization, exposure-onset, LED-emission, or BNC-onset claim is permitted until then. |
| **HW-PUMP-MOTION-001** | H2B closed stable no-motion startup recovery, not motion readiness. Fresh `position_sensing_initialized=false` fails closed before enable. Installed syringe identity/geometry/loading, available travel, harmless route, fill truth, stop latency, and bounded motion remain unverified. `reference_move()` timeout-stop behavior needs review if reference is actually required. | No-command physical readiness inspection, then a fresh single-client readiness result. Only if the gate requires it, separately review/authorize reference; then validate fill truth, stop latency, and one minimal bounded move, in that order. None of this is implied by tracked fill arithmetic. |
| **HW-VALVE-001** | Software transport is COM5; position 1 → `P01`, position 2 → `P02`. Owner workflow truth identifies P01 as through-chip and P02 as bypass. Protocol acknowledgement and independent physical route observation are different evidence. Valve label is still `MODEL_IDENTITY_REQUIRED`. | If automatic refresh is to be used, separately observe each route with the pump inactive before combining valve and pump actions. |
| **HW-LASER-PATH-001** | Owner truth maps Project Ch2 / API 1 / W2 to iBEAM Analog In/control; DIO1/green is LED timing/control, not laser Digital In. Vendor-family manual: analog modulation is 0…+5 V on channel 2; documented default `sub` polarity reduces power as input rises, so 0 V is not generic optical off and bipolar zero-offset drive may be out of range. Under documented external analog modulation, RS232 Laser ON/OFF and FINE ON/OFF may be unavailable because modulation opens the microprocessor-to-driver connection. Installed option set, polarity, scaling/trim, impedance, and emission behavior are unknown. Production rejects W2; canonical DIO0/DIO1 serve camera/LED only. | Retain installed-unit configuration, then separately design and verify only the bounded control behavior actually required. Never infer optical power from a command voltage. Deferred while software laser control stays disabled. |
| **HW-Z-001** | Current manual Z path is Thorlabs `PPC001`/`PFM450E` through Kinesis. Candidate serial `44533854` is not fresh identity evidence. Controller coordinate zero is not a microscope physical datum. Prior/COM7 is historical only. | Before automated Z use, freshly identify the controller/stage and separately verify direction, scale, travel bounds, and the required physical datum. Deferred while Z stays disabled. |

## NONBLOCKING_SOFTWARE

| ID | Boundary | Closure condition |
| --- | --- | --- |
| **TEST-QT-LIFETIME-001** | PySide/Shiboken tests can nondeterministically delete C++ widgets **or hang** during full-window construction/teardown. Observed across several different tests and exception types, and reproduced at the parent commit in an isolated export, so it is not attributable to any recent checkpoint. Affected tests pass in isolation; the full `tests/` suite passes. Retained reproduction: `tests/test_qt_ui_v3.py::test_v3_constructs_on_first_attempt_without_retry`. | Reproduce minimally and remove/isolate the ownership fault. **No blanket retries, skips, or xfails** — the failure must stay visible. |
| **SW-V3-NARROW-WINDOW-001** | **Layout behavior, not test honesty.** Three V3 pages are horizontally clipped at narrow window widths. Measured offscreen at `62d244f`: V3's `minimumWidth()` is 980 px, so any smaller request clamps to 980 px. At that narrowest attainable width the content minimum-size hint exceeds the viewport on Configure → Acquisition `v3CameraSetupScroll` (needs 996 px, viewport 916 px, short 80 px), Configure → Repeat Sample Refresh `v3FluidicsSetupScroll` (needs 972 px, viewport 916 px, short 56 px), and Review → Timing `v3TimingReviewScroll` (needs 1104 px, viewport 914 px, short 190 px). Clipping persists to 1160 px window width; the binding Timing page first fits between 1160 and 1170 px, and all three fit at 1200 px and above. Because `_v3_scroll_page()` gives its content `QSizePolicy.Ignored`, `horizontalScrollBar().maximum()` reads 0 in every clipped case, so the clipping is silent. The **test-honesty half is already closed**: `tests/test_qt_ui_v3.py` now asserts `minimumSizeHint().width() <= viewport().width()`, which does detect this. Containment is asserted at the supported sizes 1366x768, 1440x900 and 1920x1080, and holds there. | **Layout redesign is deliberately deferred.** Closing this needs the Timing table and Acquisition/Refresh forms to reflow below ~1000 px, which is an operator-layout change, not an assertion change. Do not change V3 geometry merely to reduce an issue count. |
| **SW-TRACE-FLUSH-DUPLICATE-001** | The `Flush` step is bracketed **twice** per repeat when automatic refresh runs. Site A is the outer worker bracket in `application.py` `Application._run_experiment2_unfinalized`, which calls `log_action("run", STEP_FLUSH, ... status="STARTED")` before starting the worker thread and `status="COMPLETED"`/`"FAILED"` after the rendezvous. Site B is `application.py` `Application.flush()`, whose body opens `with _report_step(progress, STEP_FLUSH)`; `_report_step` calls `log_action` unconditionally, so the inner bracket fires even though the worker passes `progress=None`. Both emit `subsystem="run"`, `operation="Flush"`, identical statuses. The **only** discriminator is the projected `source` field (`application._run_experiment2_unfinalized` versus `application._report_step`), which is a free-form optional string in `log_action` with no schema constraint or enum — an implicit convention, not an enforced one. The sequence-level initial refresh emits only the inner bracket, so the pattern is also inconsistent between the two refresh kinds. Consequence: any downstream interval analysis over `commissioning_trace.jsonl` or `action_log.jsonl` that pairs `Flush` STARTED to COMPLETED on `(operation, status)` alone will nest or double-count the refresh and compute a wrong duration; it must key on `source`. **Pre-existing runtime behavior, not introduced by the trace layer** — both sites are byte-identical at `ea77bd5` and the commissioning-readiness window's diff touches neither. The trace layer only made it visible. | Either give the two brackets distinct operation names, or constrain `source` to a documented vocabulary, or remove one bracket. Do not change the flush control flow to fix a logging shape. |
| **SW-NONBLOCKING-FOLLOWUP-001** | Reduced to its one unresolved part. Whether `DCAM_IDPROP_TIMING_MINTRIGGERINTERVAL` already accounts for the currently applied exposure and ROI is **`INSUFFICIENT_EVIDENCE`** from primary vendor documentation. The installed DCAM property reference defines it only as "the period from receiving input trigger to trigger ready", and the exact-model property document's Information column says only "return seconds required minimum trigger interval" with no dependency note — while the same document does carry explicit "Depends on ..." notes for other properties, an absent note is not a statement of independence. Production already reads the property fresh, after the requested ROI and exposure have been applied and read back. Parts (a), (c), (d), (e), (f) and (g) of the original aggregate are closed; see the closed-provenance table. | Resolve only from model-exact Hamamatsu documentation or a vendor statement. **Do not invent a formula and do not change runtime to make the question disappear.** The physical half stays with `HW-TIMING-001`. |

## OWNER_DECISION_REQUIRED

| ID | Boundary | Decision needed |
| --- | --- | --- |
| **UI-V3-DEFAULT-001** | V3 is tracked, opt-in, and offline UX-reviewed; V1 remains the default launcher. V2 is retired. V3 has not had an operator-journey evaluation on current hardware. | Decide promotion only after a separate operator/current-hardware evaluation. Until then launch V3 explicitly. |
| **UI-MANUAL-INTERLOCK-001** | V3 separates Manual & Service actions and preserves action-specific confirmations, but the GUI has no universal command-line-style real-hardware acknowledgement gate after initialization. | Owner decides whether existing context/action gates suffice or a global manual/service policy is required. |
| **V3 Prepare confirmations** | The Preparation checklist's confirmations are local presentation state. They are correctly labelled as not persisted run evidence and not `PHYSICAL_VERIFIED`. | Owner decides whether operator preparation confirmations should become durable run evidence; if so it becomes a scoped software item, not a label change. |

## SCIENCE_VALIDATION

| ID | Boundary | Closure condition |
| --- | --- | --- |
| **SCI-TEC-EQUIL-001** | Retained TEC evidence covers communication and narrow controller operations. Controller-reported stability does not establish imaging-plane fluid equilibrium. | Before temperature-controlled scientific claims, define and validate an imaging-plane equilibration criterion or an experimentally justified transfer model. Deferred while TEC stays disabled. |
| **SCI-RHB-CAL-001** | No active Rhodamine-B thermometry workflow links measurements to calibration provenance. | Before thermometry is enabled, retain a compatible calibration identifier/date plus illumination, requested/applied exposure, camera mode/gain, filters, and condition contract. |

## Closed — provenance only, do not reopen without contradictory evidence

| Topic | Disposition |
| --- | --- |
| ARCH-PREFLIGHT-001 | CLOSED. Normal Start is `ExperimentRequest` → independent immutable plan → explicit legacy adapter. The old UI builder is rollback-only; V3 `BuildResult` is presentation/audit only. |
| ARCH-RECORD-001 | CLOSED. Atomic `series_manifest.json` records aggregate lifecycle; TDMS remains per-repeat authority and links to the action stream. |
| SW-ACTION-TRACE-001 | CLOSED OFFLINE. Correlated `action_log.jsonl`, TDMS/manifest linkage, phase-aware diagnostics, bounded vocabulary, and separate primary/cleanup failures. |
| SW-FM-SPAN-001 | CLOSED OFFLINE. AD2 FM index is `100 * half_deviation / center`; 1.909–1.959 MHz gives 50 kHz total span, ±25 kHz, ≈1.2926577 %. Zero/reversed spans fail closed. Historical affected range starts at `d30be02`; no tracked run artifact was available for automatic reinterpretation. Not physical output. |
| SW-FM-SHAPE-001 | CLOSED OFFLINE at `bfd1b31`. Symmetric → Triangle/50 %/bidirectional; RampUp → RampUp/100 %; RampDown → RampDown/100 %. |
| SW-WFG-EVIDENCE-001 | CLOSED OFFLINE at `bfd1b31`. Requested carrier/FM unchanged; post-clamp software-effective SDK arguments stored separately; status is `EFFECTIVE`, never `APPLIED`/`OBSERVED`. |
| SW-SCI-INTEGRITY-001 | CLOSED OFFLINE. Requested FPS is request truth; achieved DIO0 cadence defines the finite DigitalOut run. External acquisition uses fresh minimum-trigger-interval validation; Internal paths keep the documented overlapping `max(exposure, readout)` limit. |
| SW-ACQ-DETERMINISM-001 | CLOSED OFFLINE. Requested ROI applied and freshly read back; enabled CH0 requires `Repeat=1`; FM Sweep conflicts with Frequency Scan. |
| SW-AD2-ROUTING-001 | CLOSED OFFLINE. W1 acoustic with PC trigger; W2 laser Analog In and fails closed; DIO0 camera frame trigger; DIO1 LED timing, never laser Digital In. |
| SW-HANDOVER-SEQUENCE-001 | CLOSED OFFLINE as implemented software policy. One sequence-level initial refresh when enabled; programmed-output completion barrier; concurrent save + hardware-only flush worker; explicit rendezvous; main-thread single-writer TDMS; `FlushCompleted` persisted after rendezvous; separate `PrimaryFailure`/`CleanupFailure`; aggregate `TotalExperiments + 1` tracked-fill preflight before the initial refresh; temperature subgroups do not recharge it. Conservative software timing policy, **not** physical output or fluid proof. Physical prerequisites remain HW-PUMP-MOTION-001 and HW-VALVE-001. |
| SW-V3-UX-001 | CLOSED OFFLINE. Compact persistent state/run controls; Preparation checklist / Configure / Review phases; run-focused Monitor; grouped Manual & Service; Diagnostics. |
| SW-COMMISSIONING-TRACE-001 | CLOSED OFFLINE. `log_action()` is the single canonical software event stream; passive observers project it to the durable commissioning trace and the live indicator. Recording is `OFF`/`RECORDING`/`DEGRADED` over the normal canonical experiment, never a second execution mode; it adds no device call, sleep, barrier, or rendezvous, and a write failure degrades recording without touching control flow. Software evidence only; it establishes no physical timing. |
| SW-V3-EXECUTION-INDICATOR-001 | CLOSED OFFLINE. Persistent read-only Execution line in V3's instrument strip, projecting the canonical progress/event stream with no local timer and no elapsed-time phase inference. Wording is restricted to software facts; cleanup and error remain visible after a run stops. |
| SW-NONBLOCKING-FOLLOWUP-001 (a) achieved-cadence camera gate | CLOSED OFFLINE. The External-trigger feasibility gate validates the software-effective achieved DIO0 spacing when a real `configure_do()` produced one, and falls back to the request otherwise. Requested FPS remains the separate scientific request. Internal/free-running timing is unchanged. Regression uses a real non-exact divider (100 MHz / 30 fps → divider 1 666 666 → 30.000006 Hz). |
| SW-NONBLOCKING-FOLLOWUP-001 (c) TRIGGERTIMES bound | CLOSED OFFLINE. The backend bound is `1..10000`, matching the exact `C15440-20UP` property document. The former `65535` belonged to `MASTERPULSE_BURSTTIMES`, which keeps its own documented range. Canonical value remains 1. |
| SW-NONBLOCKING-FOLLOWUP-001 (d) V3 W2 contextual note | CLOSED OFFLINE. The authoritative blocked-plan note names Laser / W2 (Project Ch2) and stays visible whether or not Acoustic/W1 is enabled. Presentation only; W2 planner and runtime semantics are unchanged and W2 remains blocked. |
| SW-NONBLOCKING-FOLLOWUP-001 (e) V3 overflow assertions | CLOSED OFFLINE as a test-honesty correction, with no layout change. `horizontalScrollBar().maximum()` is structurally 0 on pages whose content carries `QSizePolicy.Ignored`, so it cannot detect clipping there; those pages now assert that the content's `minimumSizeHint().width()` fits the viewport, which the Ignored policy does not suppress. The Review page keeps a real horizontal policy and retains the scrollbar-extent assertion as well. |
| SW-NONBLOCKING-FOLLOWUP-001 (f) AD2-disabled consistency | CLOSED OFFLINE. With the canonical trigger architecture in the plan, `ad2_disabled` is a blocking preflight issue and the V3 readiness chip reports that the subsystem is required and the runtime fails closed. The runtime AD2-required hardware gate itself is unchanged. |
| SW-NONBLOCKING-FOLLOWUP-001 (g) aggregate refresh in Review | CLOSED OFFLINE. Review derives the aggregate requirement from the plan — one refresh per flush-enabled condition plus one sequence-level initial refresh, counted once across temperature groups — and compares it to cached tracked fill. It stays a warning because the evidence is cached; the runtime applies the same gate against live tracked state at Start. No new pump read. |
| TOOL-VALVE-PORT-001 | CLOSED OFFLINE. The manual full-workflow plan/CLI and the shared hardware factory accept only valve resource `COM5`; `COM6` is hard-rejected as the TEC path. Physical routing remains HW-VALVE-001. |
| HW-QMIX-CAN-001 startup recovery | CLOSED FOR NO-MOTION STARTUP. H2A/H2B evidence. Does not close HW-PUMP-MOTION-001. |
| Generic production DO Clock | SUPERSEDED. The legacy DO-clock helper and its generic configuration are unused by normal production. Canonical production programs one finite shared PC-triggered DigitalOut program: DIO0 the camera `EXT.TRIG` train, DIO1 the LED timing window. Neither is laser Digital In; neither is physical timing verification. |
| CH2 "unused" | SUPERSEDED. W2 is laser Analog In. Electrical semantics remain HW-LASER-PATH-001. |
| DIO1 laser-vs-LED identity conflict | SUPERSEDED / OWNER_ADJUDICATED. DIO1/green is LED timing/control; DIO0/pink is camera `EXT.TRIG`. Canonical production programs both for camera/LED timing; neither carries laser control. |
| Two-pump profile | SUPERSEDED. One-pump configuration; the legacy two-pump profile is rejected. |
| Valve on COM6 | SUPERSEDED ERROR. Valve is COM5; COM6 is the TEC path. |
| Prior COM7 as current Z | OBSOLETE. Current Z uses Thorlabs/Kinesis. |
| ROI inherited from manual state | SUPERSEDED. Normal plan carries requested ROI; runtime applies it and reads it back. |
| Exposure request equals applied value | SUPERSEDED. `RequestedExposureMs` and `AppliedExposureMs` are separate. |
| Duplicate post-P02 pump target | CLOSED. One target command before P02; wait only after P02. |
| AnalogOut-only deterministic cleanup | SUPERSEDED BY EXTENSION. Cleanup now also stops and resets DigitalOut before device close, because canonical production programs DIO0/DIO1. |
| Pre-redesign V3 everything-dashboard | SUPERSEDED. Current V3 operator model is in `project_control.md` and current source/tests. |

## Retained evidence navigation

Point-in-time and historical material is indexed in
[`audit_index.md`](audit_index.md). The records most often needed alongside this
register are [`p0_hardware_truth_20260828.md`](p0_hardware_truth_20260828.md),
[`hardware_repair_plan.md`](hardware_repair_plan.md),
[`qt_lifetime_investigation.md`](qt_lifetime_investigation.md), and the retained
`runs/qmix_h1_*`, `runs/qmix_h2a_*`, `runs/qmix_h2b_*` evidence. Retained
evidence is not permission to repeat or broaden a hardware session.

## Immediate project gate

Close HW-ACOUSTIC-CHAIN-001 and HW-AD2-BNC-001: retain the custom-amplifier
minimum characterization envelope, installed JP4 position, cable route, current
transducer identity, and a defensible same-chain starting amplitude. Offline
software closure does **not** close the physical acoustic chain. Do not energize
W1 or resume commissioning Gate 3/Gate 4 until that closure is explicit and the
run is separately authorized. Camera-only Gate 2 is accepted and must not be
repeated.
