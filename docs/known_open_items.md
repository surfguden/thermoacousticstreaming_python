# Known Open Items

Canonical registry of genuinely unresolved or deliberately deferred work.
Current architecture, workflow, routing, inventory, evidence semantics, and the
single next step are in [`project_control.md`](project_control.md). Historical
audits and Git history preserve closed investigations; they are not duplicated
here as live backlog.

No item in this document authorizes hardware. An item classified
`DEFER_UNTIL_FEATURE_USED` is not a prerequisite for the minimal camera+AD2 run
while that feature remains disabled.

## Classification

- `OPEN_NOW` — current software/repository issue worth addressing independently
  of optional future capabilities.
- `REQUIRES_PHYSICAL_VALIDATION` — source is sufficiently understood, but a
  physical claim or safe action still needs a separately authorized bench step.
- `DEFER_UNTIL_FEATURE_USED` — do not spend current effort on it while the
  capability remains disabled.
- `OWNER_DECISION_REQUIRED` — evidence cannot choose the policy or product
  preference.
- `NONBLOCKING_FOLLOWUP` — real issue, but it does not block the narrow next
  experiment.

## Current registry

| ID | Classification | Current boundary | Reopen/closure condition | Minimal camera+AD2 impact |
| --- | --- | --- | --- | --- |
| HW-PUMP-MOTION-001 | REQUIRES_PHYSICAL_VALIDATION | H2B closed stable no-motion startup recovery, not motion readiness. Fresh `position_sensing_initialized=false` fails closed before enable. Installed syringe identity/geometry/loading, available travel, harmless route, fill truth, stop latency, and bounded motion remain unverified. `reference_move()` timeout-stop behavior needs review if reference is actually required. | First perform a no-command physical readiness inspection. Then obtain a fresh single-client readiness result. Only if the gate requires it, separately review/authorize reference; then validate fill truth, stop latency, and one minimal bounded move in that order. | None while pump and refresh remain disabled. |
| HW-VALVE-001 | REQUIRES_PHYSICAL_VALIDATION | Software transport is COM5 and maps position 1 -> `P01`, position 2 -> `P02`. Owner workflow truth identifies P01 as through-chip and P02 as bypass. Protocol acknowledgement and independent physical route observation remain different evidence. | If automatic refresh is to be used, separately observe each route with pump inactive before combining valve and pump actions. | None while refresh remains disabled. |
| HW-LASER-PATH-001 | DEFER_UNTIL_FEATURE_USED | Owner evidence maps Project Ch2/API 1/W2 to TOPTICA Analog In and DIO1/green to Digital In. Exact installed input ranges, impedances, transfer function, active polarity, digital-option/configuration, and mixed-input emission semantics are unresolved. Production rejects W2 and programs neither DIO line. | Retain installed-unit configuration/manual values, then design and separately verify only the fixed-level plus ON/OFF behavior actually needed. Optical power still requires independent measurement. | None while software laser control remains disabled and power/alignment remain manual. |
| HW-AD2-BNC-001 | REQUIRES_PHYSICAL_VALIDATION | Official SKU `410-263` schematic `500-263` revision C.0 establishes W1/J4/JP4 and W2/J5/JP5. JP4/JP5 select direct or 49.9-ohm **series-source** paths; they are not 50-ohm shunt loads. Installed PCB revision and jumper positions remain unverified. | During a powered-down authorized inspection, retain readable PCB/jumper evidence. Combine the installed series path with exact downstream input impedance to derive or later measure loaded voltage. | Blocks energized W1 until combined with closure of HW-ACOUSTIC-CHAIN-001. |
| HW-ACOUSTIC-CHAIN-001 | REQUIRES_PHYSICAL_VALIDATION | `CUSTOM_ACOUSTIC_AMPLIFIER_CHARACTERIZATION_REQUIRED`. Owner-supplied current photos confirm a custom/home-built mains-powered metal enclosure with IEC entry/switch, external coax/BNC-type connectors, and handwritten annotations, but no commercial identity. Blurry values are not usable gain/bandwidth/impedance/output evidence. The active external input/output roles, controls, approximate input impedance/gain near 2 MHz, output/load envelope, limiting indication, current transducer, JP4 state, and same-chain starting evidence remain unresolved. | Search retained build/schematic/PCB/component/project records, not commercial-model catalogs. If absent, design a later bounded electrical characterization sufficient to identify connector roles and justify a conservative first input. Any internal inspection is owner/lab-only, powered down and disconnected from mains. Retain JP4/load and amplitude semantics. | **Hard blocker:** stop before Gate 3/Gate 4 and before every energized W1/acoustic output. Camera-only Gate 2 remains accepted and must not be repeated. A full amplifier datasheet is not required. |
| HW-TIMING-001 | DEFER_UNTIL_FEATURE_USED | DIO0/pink is physically connected to camera `EXT.TRIG`; DIO1/green to laser Digital In. Normal production uses camera Internal trigger and programs neither line. Physical cross-device trigger/exposure timing remains unmeasured. | Reopen only for a separately authorized transient/synchronized workflow with explicit camera mode/polarity, a bounded source, and one-common-timebase observation. | None for steady Internal-trigger acquisition. No synchronization claim is allowed. |
| HW-Z-001 | DEFER_UNTIL_FEATURE_USED | Current manual Z path is Thorlabs PPC001/PFM450E through Kinesis. Candidate serial `44533854` is not fresh current identity evidence. Controller coordinate zero is not a microscope physical datum. Prior/COM7 is historical only. | Before automated/current Z use, freshly identify the controller/stage and separately verify direction, scale, travel bounds, and the required physical datum. | None while Z remains disabled. |
| SCI-TEC-EQUIL-001 | DEFER_UNTIL_FEATURE_USED | Retained TEC evidence covers communication and narrow controller operations. Controller-reported stability does not establish imaging-plane fluid equilibrium. | Before temperature-controlled scientific claims, define and validate an imaging-plane equilibration criterion or experimentally justified transfer model. | None while TEC remains disabled. |
| SCI-RHB-CAL-001 | DEFER_UNTIL_FEATURE_USED | No active Rhodamine-B thermometry workflow links measurements to calibration provenance. | Before thermometry is enabled, retain a compatible calibration identifier/date plus illumination, requested/applied exposure, camera mode/gain, filters, and condition contract. | None for non-thermometry imaging. |
| TEST-QT-LIFETIME-001 | NONBLOCKING_FOLLOWUP | PySide/Shiboken tests can nondeterministically delete C++ widgets or hang during full-window construction/teardown. Failures are visible and documented; affected tests pass in fresh isolation. | Reproduce minimally and remove/isolate the ownership fault without blanket retries, skips, or xfails. | No demonstrated production-path defect; keep monitoring offline results. |
| UI-MANUAL-INTERLOCK-001 | OWNER_DECISION_REQUIRED | V3 separates Manual & Service actions and preserves action-specific confirmations, but the GUI has no universal command-line-style real-hardware acknowledgement gate after initialization. | Owner decides whether the existing context/action gates are sufficient or a global manual/service policy is required. | None when the operator stays in Experiment and deferred devices remain disabled. |
| UI-V3-DEFAULT-001 | OWNER_DECISION_REQUIRED | V3 is tracked, opt-in, and offline UX-reviewed; v1 remains default and v2 rollback/reference. | Decide promotion only after separate operator/current-hardware evaluation. | None; launch V3 explicitly for its reviewed workflow. |

## Closed or superseded — not live backlog

These conclusions remain important but should not be reopened without new
contradictory evidence.

| ID / topic | Current disposition | Retained evidence |
| --- | --- | --- |
| ARCH-PREFLIGHT-001 | CLOSED | Normal Start uses `ExperimentRequest` -> independent immutable plan -> explicit legacy adapter. The old UI builder is rollback-only; V3 `BuildResult` is presentation/audit only. |
| ARCH-RECORD-001 | CLOSED | Atomic `series_manifest.json` records aggregate lifecycle; TDMS remains per-repeat authority and links to the action stream. |
| SW-ACTION-TRACE-001 | CLOSED OFFLINE | Correlated `action_log.jsonl`, TDMS linkage, manifest linkage, phase-aware backend diagnostics, bounded vocabulary, and separate primary/cleanup failures are implemented and tested. |
| SW-FM-SPAN-001 | CLOSED OFFLINE | Authoritative endpoints now survive request -> plan -> adapter -> experiment; AD2 FM index is `100 * half_deviation / center`; 1.909--1.959 MHz yields 50 kHz total span, +/-25 kHz, and approximately 1.2926577%. V3 and durable requested/effective evidence distinguish endpoints, total span, half deviation, and modulation index. Zero/reversed spans fail closed. Historical affected range starts at commit `d30be02`; no tracked run artifact was available for automatic reinterpretation. This software closure does not establish physical output. |
| SW-SCI-INTEGRITY-001 | CLOSED OFFLINE | Requested FPS remains planned with DIO disabled; fresh applied exposure/readout budget is checked; requested/applied exposure and one automated `WaitAfterFlush` source are retained. |
| SW-ACQ-DETERMINISM-001 | CLOSED OFFLINE | Requested ROI is applied and freshly read back; normal enabled CH0 requires Repeat=1; FM Sweep conflicts with Frequency Scan and requires explicit CH0 enable. |
| SW-AD2-ROUTING-001 | CLOSED OFFLINE | Project Ch1/API 0/W1 is acoustic. Project Ch2/API 1/W2 is laser Analog In and fails closed. Normal production programs neither DIO line. |
| SW-V3-UX-001 | CLOSED OFFLINE | V3 has compact persistent state/run controls; separate Configure and Review run phases; run-focused Monitor context; grouped Manual & Service tasks; and Diagnostics. Pre-run and requested/effective evidence use existing planning/log sources. |
| HW-QMIX-CAN-001 startup recovery | CLOSED FOR NO-MOTION STARTUP | H2A retained fresh startup events; H2B retained five stable accepted clear/fault-false/no-motion/clean-close trials. This does not close HW-PUMP-MOTION-001. |
| Generic production DO Clock | SUPERSEDED | Normal production carries an explicit disabled digital-output payload and does not call the retained legacy DO-clock helper. DIO0/DIO1 retain specific physical roles but are unprogrammed. |
| CH2 “unused” | SUPERSEDED | Owner evidence establishes W2 as laser Analog In. Exact electrical semantics remain HW-LASER-PATH-001. |
| DIO1 generic camera/LED timing | SUPERSEDED | Owner evidence establishes DIO1 as laser Digital In; DIO0 is the camera `EXT.TRIG` cable. Neither is programmed normally. |
| Two-pump profile | SUPERSEDED | Current configuration selects one pump and rejects the legacy two-pump profile. |
| Valve on COM6 | SUPERSEDED ERROR | Current valve path is COM5. COM6 belongs to the TEC path in current configuration/evidence. |
| Prior COM7 as current Z | OBSOLETE | Current Z work uses Thorlabs/Kinesis. The disabled Prior field is compatibility/migration history only. |
| ROI inherited from manual state | SUPERSEDED | Normal plan carries requested ROI; runtime applies it and performs fresh readback before saving. |
| Exposure request equals applied value | SUPERSEDED | `RequestedExposureMs` and `AppliedExposureMs` are separate; `ExposureTime` is compatibility effective/applied state. |
| Duplicate post-P02 pump target | CLOSED | Refresh now sends one target command before P02 and only waits after P02. |
| Pre-redesign V3 everything-dashboard | SUPERSEDED | Current V3 operator model is in `project_control.md` and current source/tests. |

## Retained evidence and historical navigation

- [`p0_hardware_truth_20260828.md`](p0_hardware_truth_20260828.md) — dated P0
  hardware/evidence boundary; preserve negative and read-only findings.
- [`hardware_repair_plan.md`](hardware_repair_plan.md) — detailed historical
  repair/verification procedures. Re-derive any action against this registry
  and current source before use.
- [`qt_lifetime_investigation.md`](qt_lifetime_investigation.md) — bounded Qt
  failure-family evidence.
- [`labview_migration_completeness_audit.md`](labview_migration_completeness_audit.md),
  [`labview_ui_field_reference.md`](labview_ui_field_reference.md), and
  [`PORTING_TBD.md`](PORTING_TBD.md) — migration history, not current backlog.
- [`pending_feedback.md`](pending_feedback.md) and
  [`claude_code_change_log.md`](claude_code_change_log.md) — raw issue/session
  history; resolved entries remain historical.
- `runs/qmix_h1_*`, `runs/qmix_h2a_*`, and `runs/qmix_h2b_*` — retained
  point-in-time Qmix evidence; not permission to repeat or broaden a session.

## Immediate project gate

The immediate step is the no-output evidence closure in `project_control.md`:
retain the custom-amplifier minimum characterization envelope, installed JP4,
cable route, current transducer, and a defensible same-chain starting amplitude.
SW-FM-SPAN-001 is closed offline, but that does not close the physical acoustic
chain. Do not energize W1 or resume commissioning Gate 3/Gate 4 until the
remaining physical blocker is closed and the run is separately authorized.
Camera-only Gate 2 is accepted and must not be repeated.
