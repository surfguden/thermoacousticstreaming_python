# Project Knowledge Consolidation and Supersession Audit — 2026-09-03

**HISTORICAL AUDIT EVIDENCE — NOT CURRENT OPERATIONAL AUTHORITY**

Current operational and readiness truth remains in
[`project_control.md`](project_control.md). Current unresolved and deferred
work remains in [`known_open_items.md`](known_open_items.md). This report is a
reconstructable audit record: it records the repository state, search method,
classification decisions, changes made, and residual risks. It does not
authorize hardware, override current source/tests, or create another live
status register.

## 1. Starting Git state

The entry gate was checked before edits:

| Check | Result |
| --- | --- |
| Branch | `junjiebranch` |
| HEAD | `0855e411e93a5636be841375c96b540bb04c7399` |
| Expected baseline | Exact match: accepted pre-acoustic software baseline |
| Upstream | `origin/junjiebranch` at the same commit |
| Origin parity | `0/0` ahead/behind |
| Index/worktree | Clean before edits |
| Untracked files | None before edits |

The repository was therefore eligible for a documentation-only audit. No
hardware-backed command, discovery session, device open, or physical
inspection was performed.

## 2. Knowledge inventory and role classification

The inventory was based on content and links, not filenames alone. The vendor
SDK exports under `dcamsdk4/`, LabVIEW exports under `main_html/`, and the Qmix
SDK tree were treated as supporting source material, not project status.

| Artifact family | Role | Audit finding |
| --- | --- | --- |
| `README.md` | `CURRENT_AUTHORITY` for entry/navigation only | Directs a fresh reader to the current dashboard and open-item register; launcher and hardware-path summaries are useful but intentionally not the detailed truth source. |
| `docs/project_control.md` | `CURRENT_AUTHORITY` | Contains current architecture, workflow, parameter semantics, hardware/routing truth, evidence taxonomy, readiness, and next step. Two stale/contradictory statements were corrected in this audit. |
| `docs/known_open_items.md` | `CURRENT_AUTHORITY` for unresolved/deferred work | The live register is coherent and separates current physical blockers from deferred subsystems. One manual-tool hazard was added as a nonblocking follow-up. |
| `docs/lessons_learned.md` | `CURRENT_SUPPORTING_REFERENCE` | Contains project-specific durable engineering lessons and controls, not current status. Five actionable review/process lessons were added. |
| `hardware_tests/README.md` | `OPERATOR_GUIDANCE` | It accurately describes manual-only tools, but its historical preparation section could be mistaken for current authorization. A prominent current-gate banner and COM5-only wording were added. |
| `hardware_tests/*.py` | `OPERATOR_GUIDANCE` / `IMPLEMENTATION_DETAIL` / manual probe | Action-capable probes are outside CI and have confirmation gates. The full-workflow runner still exposes a historical COM6 valve option; this remains an explicit open follow-up and was not edited. |
| `src/thermo_acoustic/*.py` | `IMPLEMENTATION_DETAIL` | Current source confirms the canonical planner/runtime boundary, current routing labels, fail-closed W2/DIO behavior, and qualified evidence fields. Legacy compatibility code remains searchable by design. |
| `tests/*.py` | `TEST_ENFORCEMENT` | Offline tests encode current software contracts and also contain fake/legacy fixture values such as COM6 and COM7. They are not hardware truth and were not changed. |
| `launch_gui*.bat`, `tools/run_ui*.py` | `OPERATOR_GUIDANCE` | Launcher roles agree with the current v1-default, v2-rollback, v3-opt-in policy. |
| Dated audits, handovers, repair plans, migration references, and `docs/*_review*.md` | `HISTORICAL_EVIDENCE` or `SUPERSEDED_HISTORICAL_EVIDENCE` | Most high-risk files now carry a clear historical/current-authority preamble. Their bodies were preserved. |
| `docs/pending_feedback.md`, `docs/claude_code_change_log.md` | `HISTORICAL_EVIDENCE` | Raw issue/session history is explicitly noncanonical; detailed stale claims remain useful only with current-source rechecking. |
| `runs/*` retained records and hardware truth records | `HISTORICAL_EVIDENCE` | Point-in-time physical/protocol evidence, not portable permission or current measured state. |
| `.thermo_acoustic_ui.json`, `data.tdms`, `port_status.json` | `IMPLEMENTATION_DETAIL` / bench-specific retained state | Useful clues or artifacts, but not current authority and not a commissioning setting. |
| `dcamsdk4/`, WaveForms references, manufacturer links, Lund paper | `CURRENT_SUPPORTING_REFERENCE` at the applicable evidence layer | Exact API/device specifications and scientific method references; specifications were not promoted to measurements. |

No complete artifact was classified `UNKNOWN_ROLE`. The high-risk issue was a
subsection of `hardware_tests/README.md`, not the whole documentation tree:
its “prepared” action list had not been explicit enough that it was historical
and subordinate to the current W1 block.

## 3. Authority hierarchy assessment

The repository now follows the intended structure:

```text
README.md
  -> navigation only
docs/project_control.md
  -> current project, architecture, workflow, hardware, semantics, readiness
docs/known_open_items.md
  -> current unresolved and deferred registry
docs/lessons_learned.md
  -> durable cross-task engineering and review lessons
dated audits / handovers / reports
  -> historical reasoning and retained evidence
Git history
  -> chronological implementation and evidence history
```

The implementation nuance is important: current source and tests remain the
factual authority for implemented behavior, and exact retained physical
records remain authoritative only for the session they describe. The current
dashboard does not override source, tests, safety rules, or newer retained
evidence; it interprets them at the project/readiness level. No competing
current source of truth was created.

## 4. Fresh current-truth recovery test

A fresh reader can recover the required current truth from the dashboard,
open-item register, current source/tests, and linked retained evidence:

- Architecture is `ExperimentRequest` -> immutable `RunPlan`/`RunCondition` ->
  explicit legacy adapter -> `Experiment2`/application -> backend authority.
  V3 `BuildResult` is a presentation/audit projection and is not execution
  authority.
- The accepted real camera identity is Hamamatsu ORCA-Fusion BT
  `C15440-20UP`, S/N `500478`; camera-only Gate 2 is accepted. Normal
  acquisition is Internal/free-running, with requested and applied exposure
  separated.
- AD2 routing is W1 acoustic on project Ch1/API 0, W2 laser Analog In on
  project Ch2/API 1, DIO0 camera cable, and DIO1 laser cable. W2/DIO are
  unprogrammed in normal production. FM endpoints, total span, half deviation,
  sweep shape, and AD2 source peak-voltage semantics are explicit. Software
  effective values are not readback or measurement.
- The acoustic path is Digilent BNC Adapter -> unresolved JP4 state -> custom
  mains-powered amplifier -> lab-fabricated/currently unconfirmed transducer.
  Gain, load, output, safe drive, and a defensible starting amplitude remain
  unresolved; W1 and Gate 3/Gate 4 are blocked.
- Camera Internal cadence uses the documented overlap model,
  `max(applied_exposure, fresh_readout)`, not exposure plus readout. This is
  not generalized to external/transient modes, and host timestamps are not
  physical synchronization evidence.
- Pump truth is one-pump configuration. H2B closes stable no-motion startup
  recovery only; position sensing, motion, route, fill, delivery, and stop
  semantics remain separate gates. No automatic reference is inferred.
- Valve production truth is COM5, P01 through-chip, P02 bypass, with owner
  route truth distinct from protocol acknowledgement.
- Current Z is Thorlabs/Kinesis PPC001/PFM450E; Prior COM7 is historical only,
  and controller coordinates are not microscope displacement.
- TEC is Meerstetter TEC-1123-HV; controller stability is not sample/fluid
  equilibrium. Laser electrical commands are not optical power, and laser
  production output remains disabled.
- The intended steady workflow keeps cleaning, initial sample replacement,
  laser alignment/power, and fixed optical power manual; `WaitAfterFlush` is
  operator-set stabilization after P02; automatic refresh and transient
  synchronization remain deferred.

The two contradictions found by the fresh-reader test were corrected in the
current dashboard and operator README before this report was finalized.

## 5. Supersession register

The register was cross-checked against current source/tests, dated documents,
and Git history including `577967c`, `183ddd8`, `bf03e46`, `aa615e0`,
`09c6810`, `e7cb9ee`, `bfd1b31`, `89d09b4`, and `0855e41`.

| Old claim | Source / why reasonable then | New evidence | Current claim / authority | Retrieval risk if isolated |
| --- | --- | --- | --- | --- |
| Valve is on COM6 | Early migration/default/test fixtures; COM-style port was not yet reconciled | Owner/current application evidence and current control path identify COM5 | COM5 production valve; `project_control.md` inventory and `known_open_items.md` | A stale COM6 action can target the wrong device; the manual runner still exposes this and is open as `TOOL-VALVE-PORT-001`. |
| Valve route is unknown or inferred from command number | Protocol probes established bytes/positions before tubing observation | Owner supplied P01 through-chip and P02 bypass, with physical observation still separate | P01 through-chip/P02 bypass is owner workflow truth; route effect remains unverified | A protocol acknowledgement may be mistaken for delivered-fluid proof. |
| Two pumps are current | Historical Qmix configuration and LabVIEW migration material | Current one-pump profile and H2B retained startup-recovery evidence | One pump; motion readiness is still open | Old configuration names can make a fresh agent reopen or enable the wrong topology. |
| Prior serial COM7 is current Z | Original converted code and historical serial configuration | Thorlabs/APT/Kinesis path and candidate controller evidence | Thorlabs/Kinesis current path; Prior/COM7 compatibility only | Search results in tests/comments can be mistaken for the live actuator. |
| Generic DO Clock or DO Custom is part of normal timing | LabVIEW migration parity and old timing audit | Current production payload disables DIO; current camera mode is Internal | Legacy digital helpers are nonessential/manual; normal runtime does not program them | Detailed legacy code can look more authoritative than current routing. |
| DIO1 is camera/LED clock and DIO0 is unused | Earlier cable-purpose uncertainty | Owner routing maps DIO0/pink to camera EXT.TRIG and DIO1/green to laser Digital In | Both are physically connected, neither is programmed in normal production | A search hit can invert a future trigger plan. |
| CH1/CH2 have generic or ambiguous purposes | LabVIEW labels and API index terminology overlapped | Current four-layer routing table | Project Ch1/API 0/W1 acoustic; Project Ch2/API 1/W2 laser Analog In | “CH1” can mean a UI/API index rather than physical W1. |
| FM width was doubled in software | Commit `d30be02` through pre-correction `09c6810`; total-width UI semantics made the formula plausible | Installed WaveForms sample/manual and independent endpoint case | Total span is explicit; half deviation drives `100*half/center`; 1.909–1.959 MHz -> 50 kHz, +/-25 kHz, 1.2926577% | Historical runs may contain old API intent; no tracked run was available for automatic reinterpretation. |
| Generic “Amplitude (V)” is sufficient | LabVIEW-era labels and AD2 terminology | Digilent/API and metrology cross-checks | AD2 carrier value is source peak volts; Vpp/RMS/load/downstream quantities remain distinct | Old screenshots/defaults can be reused as unsafe commissioning values. |
| Requested WFG values are effective/applied | Earlier metadata collapsed request and post-clamp command values | Backend now retains requested and post-clamp software-effective objects | Effective is software/protocol-derived, not readback or physical measurement | “Applied” wording can overstate what the device or chain did. |
| Exposure plus readout must be added | Intuitive serial timing model and internally agreeing tests | Exact C15440-20UP Internal/free-running behavior and hard 40 ms/11.22 ms case | Supported cadence uses `max(exposure, readout)`; other modes need re-derivation | The old additive formula remains in historical audits/tests. |
| Controller position is measured Z displacement | Position readback was available | No external microscope datum, direction, or scale verification | Controller coordinate/readback only | “Measured position” search hits can be promoted to sample geometry. |
| A commercial amplifier model can be recovered from photos | Normal hardware troubleshooting often begins with model lookup | Current enclosure is home-built; blurry annotations are not evidence | Characterize the custom chain, not a nonexistent model | Old model-search narrative can yield fabricated limits. |
| Lund 3 Vpp, project 0.1 V, or screenshot 2 V is a safe first amplitude | Each value existed in a literature/project/UI context | No same-chain JP4/load/amplifier/transducer equivalence | None is a defensible current starting condition | Numeric search hits are especially likely to be copied into a live run. |
| Software/configuration/protocol success proves physical success | Offline tests and device acknowledgements were available | Evidence taxonomy and retained negative/no-motion records | Physical claims require observation/measurement at the relevant layer | A green software status can be misreported as commissioning closure. |
| V3 review/build result can define execution | V3 was being redesigned and its preview was detailed | Normal Start rebuilds canonical plan; source/tests enforce parity | V3 is presentation/preflight only | A detailed UI projection may be mistaken for a second planner. |
| Camera-only Gate 2 still needs repetition | Gate 2 evidence was once a candidate/preparation step | Fresh 2026-09-02 identity/readback/acquisition record | Gate 2 accepted; do not repeat it as current work | Historical “first camera” procedures can cause unnecessary device access. |
| Qmix startup fault means motion is ready after clear | The clear call returned success and no-motion cleanup completed | H2B delayed fault-false readback and no-motion evidence | Startup/no-motion recovery is closed; motion/fill/route remain open | A narrow recovery closure can be overgeneralized to pumping. |
| `WaitAfterFlush` is a second pump target or cleaning step | Earlier refresh sequence duplicated a target and narrative mixed manual cleaning | Current sequence has one target before P02 and one post-P02 wait | Operator-set stabilization only; cleaning/loading remain manual | Historical workflow prose can create an unintended extra action. |

## 6. Stale-term retrieval findings

Targeted searches covered the requested terms across README, current docs,
historical docs, source, tests, tools, and hardware-test documentation. Search
ranking was not treated as authority; the question was whether context would
prevent a consequential misuse.

| Search terms | What a simple search returns | Risk assessment and context decision |
| --- | --- | --- |
| `COM6`, `COM5` | Current COM5 truth, TEC COM6, old tests and smoke-runner COM6 valve fixtures | High risk. Current docs now say COM5-only for valve; stale executable option remains explicitly recorded as `TOOL-VALVE-PORT-001`. |
| `Prior`, `COM7` | Current compatibility fields/comments plus historical audit and test fixtures | Moderate risk. Current dashboard, hardware README, and historical preambles clearly identify Prior/COM7 as obsolete Z history. |
| `DIO0`, `DIO1`, `DO Clock` | Current routing and many legacy source/history references | Moderate risk. Current four-layer table and fail-closed tests are clear; old workflow audit is labeled historical. |
| `CH1`, `CH2`, `W1`, `W2` | UI/API index labels, source comments, current physical roles, historical ambiguity | Moderate risk. Current authority explicitly pairs project Ch1/API 0/W1 and Ch2/API 1/W2; do not use a bare channel label. |
| `50 kHz`, `span`, `deviation` | Current endpoint model, scientific audit, older FM reports | Low-to-moderate risk. Current registry states total span and half deviation; historical correction report preserves the old affected range. |
| `Amplitude`, `Vpp`, `RMS` | Current qualified labels plus LabVIEW screenshots, defaults, and smoke candidates | High conceptual risk. Current docs explicitly say source peak and not loaded/downstream; historical values are now called out as non-commissioning evidence. |
| `effective`, `applied`, `observed`, `physical verified` | Current evidence taxonomy and source/test field names | Low risk in current authority; compatibility fields still require their documented evidence-layer qualifiers. |
| `measured position` | Z tests/comments and current controller/readback qualification | Moderate risk. Current docs use controller coordinate/readback and explicitly deny microscope displacement. |
| `3 Vpp`, `0.1 V`, `2 V` | Lund paper, historical smoke scripts, screenshot preset/tests | High risk. No value is a current safe starting condition; the current physical W1 gate is explicit. |
| `amplifier model`, `transducer model` | Historical lookup attempts, Lund Pz26 candidate, current custom-chain closure | Moderate risk. Current docs say no commercial model is established and the Pz26 is only a prior-apparatus candidate. |
| `P01`, `P02` | Current owner route truth and historical protocol notes | Low-to-moderate risk. Current docs separate owner route truth from protocol response and require observation for refresh. |
| `two pumps`, `one pump` | Historical Qmix sections and current one-pump control path | Low risk. Current register and project dashboard make one-pump current and two-pump superseded. |

The only retrieval hazard requiring a live-register entry was the executable
COM6 valve option. The other high-risk search hits have sufficient current
context after the edits in this audit; historical content was not mass-edited.

## 7. Lesson completeness

The existing lessons were reviewed against the failures, corrections, and
course changes in Git history rather than copied. The technical set already
covered the shared-error risk, independent numerical anchors, overloaded units,
evidence layers, physical-vs-software success, routing provenance, custom
hardware characterization, timing architecture, planning authority, and
commissioning stops. Their classifications are predominantly
`DOCUMENTED_AND_ENFORCED`, with residual physical claims explicitly
`STILL_OPEN`.

The following durable process lessons were missing or too implicit and were
added to `lessons_learned.md`:

| Lesson | Classification | Why retained |
| --- | --- | --- |
| Put material methodology, mature lessons, acceptance classes, and retrospective coverage in the task brief from the start; apply later material requirements retrospectively | `DOCUMENTED_BUT_NOT_ENFORCED` | Prevents serial steering from becoming the normal way to supply known requirements. |
| Executor self-review is valuable but is not organizationally independent; PASS/VALIDATED is not enough | `DOCUMENTED_BUT_NOT_ENFORCED` | Preserves the distinction between complete self-checking and a fresh challenge. |
| Critical numerical conclusions need independent anchors and a reviewer-reconstructable evidence package | `DOCUMENTED_AND_ENFORCED` | Existing hard-case tests, source hierarchy, and historical audit artifacts provide controls. |
| Codex autonomy remains within explicit scientific, evidence, Git, and hardware boundaries; new evidence supersedes old assumptions without rewriting history | `DOCUMENTED_AND_ENFORCED` | `AGENTS.md`, current authority, safety gates, and final Git/action accounting enforce the boundary. |

No generic sibling-project lesson, new taxonomy, or unnecessary bureaucracy was
adopted.

## 8. Lesson-to-control matrix

The material lesson chains were checked as:

| Failure/risk -> root cause -> correct rule | Authoritative evidence | Prevention / independent check | Documentation / residual risk |
| --- | --- | --- | --- |
| Code and tests shared a wrong FM/timing model -> mirrored assumptions -> external anchor required | Digilent sample/manual; Hamamatsu timing relationship | Hard independent cases; reproduce expected result without production helper | `lessons_learned.md`, `project_control.md`; future formulas remain review-sensitive |
| API “amplitude” and FM percentage were confused with universal quantities -> overloaded terminology -> name both layers | Installed WaveForms SDK plus Keysight/metrology references | Explicit span/half-deviation/source-peak fields and tests | Project parameter registry; non-sinusoidal sweep is not universal beta |
| Requested/effective/configured/observed/physical states collapsed -> evidence flattening -> retain separate stages | Current TDMS/action model and retained hardware records | Fail-closed physical claims; effective status is not applied/observed | Project evidence model; downstream voltage/pressure remain unmeasured |
| Historical setting became safe commissioning value -> no same-chain equivalence -> require chain-specific closure | Lund paper, project history, current custom-chain evidence boundary | W1 hard block and six-fact minimum envelope | Open items; first amplitude remains unresolved |
| Protocol success became physical success -> acknowledgement confused with effect -> require relevant observation | Valve/Qmix/TEC retained records | Manual physical gates and evidence taxonomy | Open items/hardware truth; bench observation still required |
| Connected wire became permission to drive -> destination and software role conflated -> record both and fail closed | Owner routing plus source/tests | W2 rejection and DIO-disabled production payload | Project routing table; future laser/trigger work needs new closure |
| UI preview became execution authority -> duplicate planning model -> keep one canonical planner | Current source and V3 parity tests | Start rebuilds immutable plan; V3 projects evidence | Architecture section; presentation can still lag |
| Executor or task brief omitted known methodology -> requirements arrived by steering -> specify upfront and independently recheck | This audit and `AGENTS.md` | Explicit audit package and fresh-review request | Lessons process section; no automation guarantees organizational independence |

## 9. Current open-item classification

The live register’s existing categories were mapped to the requested audit
classes as follows:

| Item | Audit classification | Current conclusion |
| --- | --- | --- |
| `HW-AD2-BNC-001` | `CURRENT_HARD_BLOCKER` / `PHYSICAL_CHARACTERIZATION_REQUIRED` | JP4/revision and loaded W1 path remain unresolved; blocks energized W1. |
| `HW-ACOUSTIC-CHAIN-001` | `CURRENT_HARD_BLOCKER` / `PHYSICAL_CHARACTERIZATION_REQUIRED` | Custom amplifier, transducer, safe envelope, and starting amplitude remain unresolved; blocks Gate 3/Gate 4. |
| `HW-PUMP-MOTION-001` | `PHYSICAL_CHARACTERIZATION_REQUIRED`, nonblocking to immediate acoustic path | Startup/no-motion recovery is closed; motion/fill/route/stop remain open and pump is disabled. |
| `HW-VALVE-001` | `PHYSICAL_CHARACTERIZATION_REQUIRED`, nonblocking with refresh off | COM5/P01/P02 software and owner route truth are current; physical route observation remains open. |
| `HW-LASER-PATH-001` | `DEFERRED` / `PHYSICAL_CHARACTERIZATION_REQUIRED` | Feature remains disabled; no acoustic-path impact. |
| `HW-TIMING-001` | `DEFERRED` / `PHYSICAL_CHARACTERIZATION_REQUIRED` | External/transient timing only; no steady Internal-mode impact. |
| `HW-Z-001` | `DEFERRED` / `PHYSICAL_CHARACTERIZATION_REQUIRED` | Current Thorlabs identity/path is retained; physical datum and motion evidence remain open. |
| `SCI-TEC-EQUIL-001` | `DEFERRED` / `PHYSICAL_CHARACTERIZATION_REQUIRED` | Controller stability is not sample equilibrium. |
| `SCI-RHB-CAL-001` | `DEFERRED` | No active thermometry workflow. |
| `TEST-QT-LIFETIME-001` | `NONBLOCKING_FOLLOWUP` | Known intermittent PySide/Shiboken failure family; not demonstrated as a production-path defect. |
| `TOOL-VALVE-PORT-001` | `NONBLOCKING_FOLLOWUP` / `SHOULD_BE_CLOSED` by separate tool cleanup | Manual full-workflow runner still accepts historical COM6; no impact while disabled, but do not use that mode before cleanup. |
| `UI-MANUAL-INTERLOCK-001` | `OWNER_DECISION_REQUIRED` | Global manual/service acknowledgement policy is a product/safety decision, not an acoustic blocker. |
| `UI-V3-DEFAULT-001` | `OWNER_DECISION_REQUIRED` / `DEFERRED` | V3 remains opt-in and not independently hardware-verified. |

No closed software blocker was promoted back into the current backlog. Pump,
laser, Z, TEC, RhB, and transient timing remain deferred rather than being
allowed to obscure the narrow W1 physical blocker.

## 10. Historical-document safety

The dated audits and handovers were sampled for the high-risk themes. Existing
preambles are generally sufficient and preserve chronology. In particular,
`current_workflow_audit.md`, `runtime_truth_and_bench_preparation.md`,
`p0_hardware_truth_20260828.md`, `hardware_repair_plan.md`, the V3 reviews,
and the scientific-parameter audit direct readers to current authority.

No mass relabeling was performed. The only historical/operator-context edit
was the top-level safety context and COM5 correction in
`hardware_tests/README.md`, because its action checklist was the one place
where a fresh operator could reasonably mistake preparation history for a
current permission. Bodies of old evidence were not rewritten.

## 11. AI/future-reviewer retrieval assessment

The current source of truth is now findable within minutes: `README.md` says
where to start, `project_control.md` states current truth and the immediate
gate, `known_open_items.md` is the only live unresolved register, and
`lessons_learned.md` provides durable rules. Current high-risk terms are
explicitly paired with physical/API/software evidence layers.

A fresh reviewer can distinguish owner routing from vendor specification,
specification from device readback, readback from software-effective state,
and all of those from physical measurement. The W1 block and the reason for it
are explicit. The remaining weaknesses are searchable legacy implementation
details and the manual runner’s stale COM6 option; both are now visible as
context or an open follow-up rather than silently presented as current truth.

## 12. Exact documentation changes made

- `docs/project_control.md`: corrected checkpoint status to accepted pushed
  baseline `0855e41`; made the intended W1 workflow conditional on physical
  closure and authorization; removed the stale “uncheckpointed corrections”
  wording; clarified the current next step and Gate 2 non-repetition.
- `docs/known_open_items.md`: recorded `TOOL-VALVE-PORT-001` for the manual
  full-workflow runner’s historical COM6 valve option.
- `docs/lessons_learned.md`: added four durable, actionable methodology/Codex
  workflow lessons with classifications and control descriptions.
- `hardware_tests/README.md`: added a current safety-context banner, changed
  the valve preparation note to current COM5-only wording, explicitly separated
  COM6 TEC from historical valve candidates, and labeled the Z discovery text
  as retained evidence rather than motion authorization.
- `docs/project_knowledge_consolidation_audit_20260903.md`: this historical
  evidence package.

No current operational source was duplicated by the report.

## 13. Remaining knowledge risks and material defects

1. `hardware_tests/test_real_workflow_smoke.py` still accepts `COM6` in its
   full-workflow CLI and retains COM6 plan fixtures. This is a material
   manual-tool/configuration defect discovered but **not fixed** because the
   task prohibited production/test changes. It is tracked as
   `TOOL-VALVE-PORT-001`; separately authorize a tool/test cleanup before any
   full-workflow probe.
2. The same manual runner contains future action-capable W1 modes. They are
   confirmation-gated and outside CI, but the current physical W1 closure is a
   project-level stop rule rather than an executable gate in that legacy tool.
   Do not invoke those modes under this baseline; a future safety review should
   decide whether the runner needs a current physical-closure acknowledgement.
3. Legacy source/test names such as `Prior`, `COM7`, `Amplitude`, and `CH1/CH2`
   cannot all be renamed without broad compatibility churn. Current docs and
   test comments provide adequate context for now, but the terms remain a
   search-time judgment point.
4. Physical truth remains intentionally incomplete: JP4, cable/load, custom
   amplifier, transducer, safe drive, fluid delivery, optical power, physical
   timing, and sample-state measurements are not supplied by this audit.

## 14. Validation performed

Validation was documentation-focused and hardware-free:

- Entry-gate Git checks described in Section 1.
- Targeted repository searches for all requested stale terms and the additional
  supersession themes.
- Current source/test inspection for planner authority, routing, evidence
  stages, camera cadence, pump/valve/Z/TEC defaults, and manual probe gates.
- Documentation relative-link/path sanity for the edited/current authority
  documents.
- `git diff --check` after edits.
- `python tools/check_repository_hygiene.py`.
- `python tools/audit_change_surface.py` was reviewed as the repository’s
  shared-boundary mechanism; no executable files were changed, so no runtime
  change-surface audit was required for this documentation-only diff.
- No full production test suite was run because no executable content or test
  semantics changed.

## 15. Final Git state and classification

At final audit state, the pre-existing clean checkout had these deliberate
unstaged documentation changes and no staged, committed, pushed, or unrelated
untracked changes:

```text
M  docs/project_control.md
M  docs/known_open_items.md
M  docs/lessons_learned.md
M  hardware_tests/README.md
?? docs/project_knowledge_consolidation_audit_20260903.md
```

The audit was not authorized to stage, commit, or push. The recommended next
action is to have the owner review this report and the five-file documentation
diff, then separately authorize a narrow cleanup of `TOOL-VALVE-PORT-001`.
Only after the physical W1 closure package is retained and independently
reviewed should a future authorized task derive a same-chain starting
amplitude or resume Gate 3/Gate 4.

**Primary classification:**

`PROJECT_KNOWLEDGE_CONSOLIDATED_READY_FOR_FRESH_REVIEW`

Explicit safety and scope confirmations:

- NO PRODUCTION CODE MODIFIED.
- NO TEST SEMANTICS MODIFIED.
- NO REAL HARDWARE ACCESSED.
- NO HARDWARE SESSION OPENED.
- NO HARDWARE COMMAND SENT.
- NO W1/ACOUSTIC OUTPUT ENERGIZED.
- GATE 3/GATE 4 NOT RESUMED.
