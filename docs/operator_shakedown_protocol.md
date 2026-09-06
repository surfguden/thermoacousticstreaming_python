# Operator shakedown protocol

**Not an automated hardware test script.** This is the checklist the owner/
operator follows while personally walking V3's operator journey, and the
protocol for cross-validating the first commissioning trace it produces
against what they actually did. Current architecture, workflow, and readiness
truth remain [`project_control.md`](project_control.md); unresolved software
items are [`known_open_items.md`](known_open_items.md); durable UI/product
principles are [`lessons_learned.md`](lessons_learned.md) Part 7.

This protocol does not authorize hardware initialization, enumeration,
communication, motion, output, capture, fault clearing, or persistence writes
beyond what `project_control.md` already authorizes. `HW-ACOUSTIC-CHAIN-001`
and `HW-AD2-BNC-001` still block every W1 output regardless of shakedown
progress.

## 1. Purpose

`V3_OPERATOR_WORKFLOW_PRODUCTIZATION` reached
`DESIGN_PRINCIPLE_ESTABLISHED` / `STRUCTURE_IMPLEMENTED` /
`OFFLINE_BEHAVIOR_VALIDATED`, and a fresh independent review accepted it
(`V3_PRODUCTIZATION_ACCEPTED_WITH_NONBLOCKING_FOLLOWUP`,
`docs/audit_index.md`). What remains is genuinely operator-dependent — see
[`lessons_learned.md`](lessons_learned.md) 7.20 and 7.23. This protocol is how
that remaining `OPERATOR_VALIDATION_PENDING` work gets done, and how its
findings get batched rather than trickling back into a redesign cycle.

## 2. The operator journey

The owner/operator performs each step; nothing here is scripted or automated.
For each stage, note: **expected action**, **actual action**, **navigation
friction**, **confusing wording/state**, **missing routine control**,
**unnecessary control**, **blocker**, **recovery path**, **Manual Service
sufficiency** (where relevant), and **observed hardware result** (where
appropriate). A blank sheet works; a scratch copy of this list works better.

1. Launch V3.
2. Initialize / readiness.
3. Pump Preparation — reference move, syringe specification, refill/prepare,
   working fill level.
4. Imaging — preview, ROI, routine exposure.
5. Z / Focus — readback, jog/move, focus.
6. Routine Temperature — target, Apply, controller stability; the
   sample-equilibrium checkbox stays a local confirmation, not evidence (see
   `known_open_items.md`, "V3 Prepare confirmations").
7. Configure the scientific run — run/output/repeats, Acquisition,
   Conditions/temperature program if needed, Acoustic/W1, repeat refresh,
   Advanced only where intentionally required.
8. Review.
9. Start.
10. Monitor.
11. Completion / evidence review.

## 3. Specific observations this shakedown must make

These are the open questions this checkpoint could not close from a desk
review — see `known_open_items.md` for the full boundary text of each ID.

| # | Observation | Open item / lesson |
| --- | --- | --- |
| A | Prepare's vertical-scroll burden — does the inline-preparation benefit outweigh the travel cost, especially at 1366x768? | `UI-V3-PREPARE-SCROLL-001`; `lessons_learned.md` 7.22 |
| B | Manual & Service completeness for abnormal/recovery scenarios (pump fault, valve routing, manual flush, failed sample load, camera diagnostics, Z-scan/calibration, AD2/WFG/MSO engineering, failed-experiment recovery, abnormal shutdown/restart) | `UI-V3-MANUAL-SERVICE-COMPLETENESS-001` |
| C | Execution-strip readability and usefulness of Current / Last / Next during an actual run, not just an offscreen measurement | `SW-V3-EXECUTION-STRIP-WIDTH-001` |
| D | Fixed TEC target vs. temperature-program distinction — is it clear which one Prepare vs. Configure controls? | `lessons_learned.md` 7.14 |
| E | Routine Z/focus vs. Z-scan distinction — same question for the Z panels | `lessons_learned.md` 7.14 |
| F | Pump: reference → syringe → refill → working-position coherence, as one guided sequence | `lessons_learned.md` 7.15 |
| G | Camera preparation vs. Acquisition distinction — does the operator understand which tab owns which decision? | `lessons_learned.md` 7.14 |
| H | Review: "Does this accurately tell me what Start will attempt?" | `lessons_learned.md` 7.18 |
| I | Start: "What exactly blocks or permits the run?" | Run-control gate tooltip, `lessons_learned.md` 7.8 |
| J | Monitor: "Can I understand what is happening without opening Diagnostics?" | `lessons_learned.md` 7.6/7.19 |
| K | Recovery: "If something fails, is the necessary Manual Service/recovery path available and understandable?" | `UI-V3-MANUAL-SERVICE-COMPLETENESS-001` |

Do not pre-judge any of these from static inspection alone — that is exactly
what the prior desk review already did as far as it can go (7.23).

## 4. Commissioning-trace cross-validation

The first suitable real-operator shakedown run should enable commissioning
trace recording (Configure → series identity) where practical. The trace does
**not** replace operator notes, physical observation, or instrument
measurement — it is one more evidence source to reconcile against them.

**Evidence inputs:**

- The operator's own known action chronology (notes taken live, or
  reconstructed immediately after).
- `commissioning_trace.jsonl` (if recording was enabled).
- `action_log.jsonl`.
- TDMS / `series_manifest.json` run evidence.
- Monitor / operator-event history, where applicable.

**Comparison method.** Check, across those sources together: sequence
ordering; run/condition/repeat identity; software phase; command-sent events;
completion/failure events; save; refresh; save/flush rendezvous; cleanup; and
trace completeness/degraded state (`docs/audit_index.md`'s
`SW-COMMISSIONING-TRACE-001` and `SW-TRACE-FLUSH-DUPLICATE-001` entries are
relevant background for reading the flush-bracket duplication correctly). For
a handful of specific, known physical actions, compare "what the operator
knows they did" against "what the software trace claims" — e.g. does a
recorded `pc_trigger_command_sent` line up with when the operator expected the
run to actually begin acquiring?

**Physical-evidence boundary — do not cross it.** Agreement between the
operator's chronology and the trace is evidence the *software* behaved as
expected; it is not a physical timing measurement. Do not infer electrical
edge timing, exposure onset, acoustic onset, fluid-delivery timing, or optical
emission solely from software trace timestamps — see
[`lessons_learned.md`](lessons_learned.md) 1.2b and 1.3, and
`known_open_items.md`'s `HW-TIMING-001`. This is the first opportunity to
validate the commissioning trace against a real known operator/hardware
sequence rather than fakes; treat it as validating the trace's software
accounting, not as commissioning the hardware.

**After the run.** Hand the trace/evidence package to a fresh reviewer — one
who did not perform the shakedown — for a bounded cross-validation pass,
driven by the actual operator chronology plus trace plus `action_log` plus
TDMS/run evidence plus current source/authority (`lessons_learned.md` 12.1).

## 5. Finding batching policy

Do not open a software checkpoint for every small shakedown observation.
Accumulate a coherent batch and classify each one:

| Class | Meaning |
| --- | --- |
| `MUST_FIX` | Blocks the intended workflow. |
| `HIGH_ROI` | Confusing but recoverable; worth fixing soon. |
| `OPERATOR_PREFERENCE` | Real friction, lower priority; owner/operator taste. |
| `PHYSICAL_VALIDATION` | A physical timing/measurement question, not software. |
| `SCIENCE_VALIDATION` | A scientific calibration/criterion question, not software. |
| `LOW_ROI_DEBT` | Real but low-value; record and defer. |

Perform one consolidated correction checkpoint only if the batch actually
warrants it (`lessons_learned.md` 7.23). Do not return to broad static V3
redesign without new operator or physical evidence. Examples: a blocker
preventing the intended workflow is likely `MUST_FIX`; Prepare's measured
scroll depth is judged from actual use, not static dislike; a physical timing
uncertainty is `PHYSICAL_VALIDATION`, not a software defect.
