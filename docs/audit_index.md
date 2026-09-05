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
| Commissioning-readiness follow-ups | Bounded residue closure | Achieved-cadence External camera gate; exact-model `TRIGGERTIMES` bound; AD2-disabled Review/runtime consistency; aggregate refresh requirement in Review; V3 W2 contextual note; V3 overflow test honesty; `TIMING_MINTRIGGERINTERVAL` adjudication recorded as `INSUFFICIENT_EVIDENCE`. | Closed offline; see `known_open_items.md`. |

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
