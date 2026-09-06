# Audit and checkpoint index

**NON-AUTHORITATIVE.** This file exists for discoverability and provenance
only.

- Current source and tests are authoritative for software behavior.
- [`project_control.md`](project_control.md) is authoritative for current
  project, workflow, hardware, and readiness truth.
- [`known_open_items.md`](known_open_items.md) is authoritative for what
  remains unresolved.
- This index **does not override** any of them. If an entry here disagrees with
  current source or `project_control.md`, those win and this entry is stale.

Reviewer/tool identity below is provenance metadata, not authority. A verdict
recorded here describes what a review concluded at that time; it does not by
itself make a claim true, and it never converts software evidence into physical
evidence.

Roles across the recent window: implementation tool **Codex**; independent
review tool **Claude Code**; orchestration and all authorization by the
**owner**. Agreement between AI-generated reports is not independent evidence.

Commit hashes below were reconstructed from Git in the repository, not from
recollection.

## Anchor

| Date | Commit | Scope | Current relevance |
| --- | --- | --- | --- |
| 2026-09-03 | `023c747` | `Clarify pre-acoustic safety status and hardware authority`. End of the documentation-freeze period and the anchor the post-handover window builds on. | Historical anchor. Superseded as current truth by everything below. |

## Software checkpoints — post-handover window

Listed in ancestry order. Every entry is on `junjiebranch`.

| Commit | Checkpoint | Scope | Status |
| --- | --- | --- | --- |
| `6b779c6` | Resume authorized software-only development | Lifted the documentation freeze for software-only work. | Superseded by later status in `project_control.md`. |
| `aa3ddbe`, `019fc38`, `de92fca` | V3/V2 decoupling | Removed V3's dependency on the deprecated V2 module and restored compatibility behavior. | Closed. |
| `e0de2b8` | V2 retirement | Removed the deprecated V2 UI. | Closed; independently reviewed. |
| `83d3f59` | Deterministic AD2 AnalogOut cleanup | Explicit stop/reset of AnalogOut channels 0/1 before device close. | Closed; later **extended** to DigitalOut at `a3d226f` (see lesson on newly activated outputs). |
| `721f810` | V2 retirement review corrections | Corrections from the V2 retirement review. | Closed. |
| `7a2ef57`, `a0a2de2` | COM6-as-valve remediation | Rejected COM6 as a live valve resource; valve transport is COM5, COM6 is the TEC path. | Closed; independently reviewed. |
| `5503629` | AD2 capture-tool hardening | Hardened real AD2 capture tooling. | Closed; independently reviewed. |
| `39caf7c` | Handover evidence ingestion | Ingested the colleague's `experiment_sequence_timeline.txt` and the iBEAM `M-042 v09` manual **without merging that branch**. | Raw handover / vendor evidence. Not authority; see classification below. |
| `a9fcfa6` | Pump/Qmix tool hardening | Confirmation gate on action-capable Qmix engineering tools, upstream of backend construction and environment mutation. | Closed. |
| `7c2d237` | Authority reconciliation | Recorded owner-adjudicated routing: DIO0 = camera `EXT.TRIG`, DIO1 = LED timing; superseded the older DIO1 = laser Digital In mapping. | Closed as adjudication; its DIO wording was later corrected at `a3d226f`/`7a0b9f1` once canonical DigitalOut became active. |
| `d160961` | Canonical experiment sequence core | Sequence-level initial refresh, programmed-output completion barrier, concurrent save + hardware-only flush with explicit rendezvous, single-writer TDMS. | Closed. |
| `4cc2d25` | Trigger timing architecture | Canonical PC-triggered W1, finite shared DigitalOut for DIO0/DIO1, External-positive camera. | Closed after corrections at `a3d226f`. |
| `2122dd1` | V3 operator workflow reorganization | Prepare / Configure / Review phases, Conditions tab, plan-derived review projections. | Closed after corrections at `a3d226f`/`7a0b9f1`. |
| `a3d226f` | Integrated correction checkpoint | DigitalOut cleanup, external-trigger timing gate (`TIMING_MINTRIGGERINTERVAL`), achieved-cadence DigitalOut run window, DIO1 counter idiom, deterministic camera trigger property set, AD2-required fail-closed gate, aggregate flush-volume preflight, authority/UI wording. | Closed after `7a0b9f1`. |
| `7a0b9f1` | Narrow closure | Temperature-group refresh-volume double-count, four stale current-authority statements, three stale V3 operator strings, checkpoint status wording, AD2-disabled operator message. | Closed; the anchor the commissioning-readiness window builds on. |
| `ea77bd5` | Knowledge consolidation | Consolidated verified project knowledge into the current authority documents. | Closed. |

## Commissioning-readiness window

Three logical checkpoints, each independently coherent and rollback-capable.
Implementation and offline validation only; no hardware was accessed.

| Commit | Checkpoint | Scope | Status |
| --- | --- | --- | --- |
| `2920559` | Commissioning trace observability | Passive observer hook on the canonical `log_action()` stream; `CommissioningTraceRecorder` writing `commissioning_trace.jsonl` and a derived summary beside the run's `action_log.jsonl`; `pc_trigger_command_sent`, `save_flush_rendezvous`, and `sequence_started`/`sequence_completed` added at the Application/UI boundary. | Closed offline. |
| `86fd19f` | Live V3 execution indicator | Persistent read-only Execution line in V3's instrument strip projecting the canonical progress/event stream, plus the Configure trace-recording option. | Closed offline. |
| `62d244f` | Commissioning-readiness follow-ups | Bounded residue closure: achieved-cadence External camera gate; exact-model `TRIGGERTIMES` bound; AD2-disabled Review/runtime consistency; aggregate refresh requirement in Review; V3 W2 contextual note; V3 overflow test honesty; `TIMING_MINTRIGGERINTERVAL` adjudication recorded as `INSUFFICIENT_EVIDENCE`. | Closed offline; see `known_open_items.md`. |

Independently cross-validated 2026-09-05 at `d19f6d8`; residual gaps are tracked
in `known_open_items.md` (`SW-TRACE-IO-COST-001`, `SW-TRACE-CONCURRENCY-TEST-001`,
`SW-REVIEW-FLUID-PREDICATE-001`, `UI-V1-NO-PREFLIGHT-001`,
`SW-V3-INDICATOR-LAST-ACTION-001`, `SW-V3-SEVERITY-COLLISION-001`,
`SW-TRACE-ABORT-REQUEST-001`), not repeated here.

## Dispatched programs

Programs are instructions, not commits. A program recorded here has been
executed; re-dispatching the same instruction produces no new work.

| Dispatched | Program | Instruction revision | Authorization | Commits produced | Status |
| --- | --- | --- | --- | --- | --- |
| 2026-09-05 | `COMMISSIONING_OBSERVABILITY_AND_OPERATOR_FEEDBACK` | v1 (narrower; `CLOSED`/`OPEN`/... adjudication vocabulary, 16-section report) | Owner, bounded checkpoints A/B/C on `junjiebranch` | `2920559`, `86fd19f`, `62d244f` | Executed. Independently cross-validated 2026-09-05 (`d19f6d8`). Gap-audited against instruction v2; residual gaps in `known_open_items.md`. |
| 2026-09-05 | `BOUNDED_CROSS_VALIDATION` | Standalone verification instruction, not a revision of the program above | Owner; read-only checkpoint-by-checkpoint verification (V-1..V-5), then one documentation commit | `d19f6d8` | Executed, read-only except the one landing commit. Verdict `VERIFIED_WITH_NONBLOCKING_FOLLOWUP`. Corrected two claims in the original implementation report — the `ad2_disabled` justification and the "no timing perturbation" claim — rather than accepting them on trust; see `d19f6d8`'s commit message. |
| — | Gap audit against the broader operator-feedback instruction, referenced to this session as "v2" | Not independently visible to this session | Reported to this session as already completed | (none directly; findings landed at `5ed045e`) | **Not reconstructable from the repository alone** — this session only received its stated findings, not the instruction or activity that produced them. Findings (missing `Last` field, `TRACE DEGRADED`/`ERROR` style collision, unrecorded operator-stop moment) were re-verified from source before landing, then later closed in source by `ba85a4a`/`801f3c8`/`e6a7e0d`. |
| 2026-09-05 | `PUSH_AND_LAND_VERIFICATION_FINDINGS` | Follow-on to `BOUNDED_CROSS_VALIDATION`; lands its output alongside the gap audit's | Owner; push `d19f6d8`, then one documentation-only commit | `5ed045e` | Executed. Pushed `d19f6d8`; landed 4 cross-validation `RECORD ONLY` items, 3 gap-audit `OPEN` items, and the `TEST-QT-LIFETIME-001` measured-baseline amendment. Suite green (786 passed, 1 skipped) and hygiene clean before commit. |
| 2026-09-05 | Source closures for the three gap-audit `OPEN` items, migrated to closed-provenance | **Not reconstructable from the repository alone** — only the commits and their own messages are visible | Not visible to this session | `ba85a4a`, `801f3c8`, `e6a7e0d`, `7ad96ca` | Executed. `ba85a4a` records the operator stop request in the trace (closes `SW-TRACE-ABORT-REQUEST-001`); `801f3c8` separates `TRACE DEGRADED` styling from runtime `ERROR` (closes `SW-V3-SEVERITY-COLLISION-001`); `e6a7e0d` adds the `Last`-completed-action field (closes `SW-V3-INDICATOR-LAST-ACTION-001`); `7ad96ca` is documentation-only, moving all three to the closed-provenance table with their tests. |
| — | Read-only measurement of the persistent Execution line's horizontal budget | **Not reconstructable from the repository alone** | Not visible to this session | (none — read-only; findings folded into `519215f`'s commit message and `d749b45`'s `known_open_items.md` entry) | Found the strip needs roughly 2780 px (common case) to 2840 px (AD2 off, trace degraded) of window width to show all five fields unclipped — unreachable at any supported size, including 1920x1080. |
| 2026-09-05 | Recoverability and visibility fixes for the measured Execution-strip shortfall | **Not reconstructable from the repository alone** | Not visible to this session | `519215f`, `d749b45` | Executed. `519215f` makes the clipped tail recoverable (full text on hover); `d749b45` makes clipping visible (explicit ellipsis) and splits `SW-V3-EXECUTION-STRIP-WIDTH-001` out of `SW-V3-NARROW-WINDOW-001` in documentation. Layout reflow stays deliberately deferred; nothing was closed. |
| 2026-09-06 | `CLOSE_COMMISSIONING_SOFTWARE_PHASE` | Standalone closure instruction | Owner; two bounded commits on `junjiebranch` — one test addition, one documentation commit | `dae39b7` (test), `80f967c` (documentation) | Executed. Test: scanned the execution strip's `displayed_text()` (the painted, possibly-elided string, distinct from the already-scanned `full_text()`) for forbidden physical-claim wording at the three supported window sizes and the `minimumWidth()` floor; found nothing, changed nothing. Documentation: recorded the `COMMISSIONING_SOFTWARE_READY` criterion in `project_control.md`, completed this table, recorded the orientation/precedence procedure in `AGENTS.md`, and reclassified four items to `AWAITING_SHAKEDOWN` in `known_open_items.md` without closing or adding any. |
| 2026-09-06 | `V3_SOFTWARE_USABILITY_AND_SHAKEDOWN_UNLOCK` | Standalone usability instruction, explicitly scoped away from hardware semantics/gating | Owner; one bounded implementation checkpoint on `junjiebranch` | `0b9a6e7` | Executed. Investigated first: confirmed offline/simulated shakedown was already possible by construction (`MainWindow.__init__` defaults `self.app` to `Application(ad2=SimulatedAD2Sdk())`; camera/pump/valve default `simulate=True`; no V3 workspace is gated behind Initialize) and that the Start button's blocking-issue gate was already correct — the actual friction was messaging/navigation, not gating. Added a tooltip on the Readiness chip and Run-control gate showing the real blocking/warning message(s) instead of only a count, and a quick-open button on the two Preparation-checklist rows that already told the operator to "open the manual X panel" (Pump & Valve, Camera). Verified `test_pump_tab_reference_move_is_promoted_to_a_leading_setup_group`'s ordering was a deliberate prior fix and left it untouched. Re-checked every `AWAITING_SHAKEDOWN` item against "is this actually a usability issue" and closed none — all four remain genuinely blocked on real-hardware measurement or an operator-observation judgement during a run. No hardware semantics, trigger architecture, canonical execution authority, or fail-closed gate changed. |

## Independent reviews

Reviews are activities, not commits. Each was performed read-only against the
stated range; the resulting corrections are the commits above.

| Date | Review | Reviewed | Verdict | Resulting correction |
| --- | --- | --- | --- | --- |
| 2026-09-04 | Integrated independent post-handover review | `a9fcfa6` … `2122dd1` (five checkpoints, individually and as one system) | `POST_HANDOVER_MAINLINE_ACCEPTED_WITH_NARROW_CORRECTIONS` | `a3d226f` |
| 2026-09-04 | Focused closure review | `2122dd1` → `a3d226f` | `INTEGRATED_MAINLINE_CORRECTIONS_REQUIRE_NARROW_CORRECTION` | `7a0b9f1` |
| 2026-09-04 | Micro closure review | `a3d226f` → `7a0b9f1` | `POST_HANDOVER_MAINLINE_VALIDATED_WITH_NONBLOCKING_FOLLOWUP` | none required; this consolidation follows |

Notable outcomes worth preserving, because they explain why current code looks
the way it does:

- The integrated review found that activating production DigitalOut had made
  the previously closed AnalogOut-only cleanup checkpoint incomplete, and that
  the camera FPS feasibility gate still used the Internal/free-running model
  after acquisition moved to External trigger.
- The focused review found a temperature-group double-count in the new
  aggregate refresh-volume preflight, and an inverted V3 tooltip whose broad
  substring assertion had passed on the negated sentence.
- The micro review downgraded an earlier finding: the DIO1 `frames*2` counter
  value was inert rather than harmful, because the installed WaveForms SDK
  manual documents that a zero counter side prevents toggling. A later
  primary-source check may legitimately reduce an earlier finding's severity.

## Retained evidence records

These are point-in-time or reference records. They are **not** current
authority and their current-tense sentences may be superseded.

| Document | Class |
| --- | --- |
| [`experiment_sequence_timeline.txt`](experiment_sequence_timeline.txt) | Raw handover evidence (colleague's intended sequence). Never rewritten. |
| [`vendor_manuals/M-042_iBEAM_smart_manual_v09.pdf`](vendor_manuals/M-042_iBEAM_smart_manual_v09.pdf) | Vendor evidence (family manual, not installed-unit configuration). |
| [`handover_sequence_reconciliation_20260904.md`](handover_sequence_reconciliation_20260904.md) | Reconciliation evidence between the handover timeline and current source. Self-labelled non-authoritative. |
| [`p0_hardware_truth_20260828.md`](p0_hardware_truth_20260828.md) | Dated bench/hardware evidence with explicit limits. |
| [`qt_lifetime_investigation.md`](qt_lifetime_investigation.md) | Bounded Qt failure-family evidence for `TEST-QT-LIFETIME-001`. |
| [`hardware_repair_plan.md`](hardware_repair_plan.md), [`hardware_safety_patterns.md`](hardware_safety_patterns.md), [`tec_verification_matrix.md`](tec_verification_matrix.md), [`runtime_truth_and_bench_preparation.md`](runtime_truth_and_bench_preparation.md) | Historical procedure/design records. Re-derive against current source before use. |
| [`scientific_parameter_semantics_audit_20260903.md`](scientific_parameter_semantics_audit_20260903.md), [`project_knowledge_consolidation_audit_20260903.md`](project_knowledge_consolidation_audit_20260903.md), [`current_workflow_audit.md`](current_workflow_audit.md), [`experiment_architecture_assessment.md`](experiment_architecture_assessment.md), [`autonomous_sweep_round2_20260901.md`](autonomous_sweep_round2_20260901.md), [`v3_parameter_grouping_review.md`](v3_parameter_grouping_review.md), [`v3_information_architecture_closure_20260901.md`](v3_information_architecture_closure_20260901.md), [`buildresult_independent_plan_design_20260901.md`](buildresult_independent_plan_design_20260901.md), [`experiment_record_completeness_closure_20260901.md`](experiment_record_completeness_closure_20260901.md), [`engineering_retrospective_fact_check.md`](engineering_retrospective_fact_check.md) | Audit/review evidence. Superseded where they conflict with current authority. |
| [`labview_migration_completeness_audit.md`](labview_migration_completeness_audit.md), [`labview_ui_field_reference.md`](labview_ui_field_reference.md), [`PORTING_TBD.md`](PORTING_TBD.md), [`legacy_asset_index.md`](legacy_asset_index.md), [`legacy_unresolved_items.md`](legacy_unresolved_items.md), [`v1_downgrade_assessment.md`](v1_downgrade_assessment.md) | Migration history. Not current backlog. |
| [`pending_feedback.md`](pending_feedback.md), [`claude_code_change_log.md`](claude_code_change_log.md), [`HANDOVER.md`](HANDOVER.md) | Raw session/issue history. Resolved entries are historical. |
| MASTER recovery packages (supplied outside the repository) | Recovery package. Historical snapshot; never current operational authority. |
