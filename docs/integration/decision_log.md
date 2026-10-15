# Integration decision log

Append new entries at the top (newest first). Each entry should name the
SHA(s)/file(s)/function(s) the decision rests on, not just a conclusion.

---

## 2026-10-15 — Terminology correction: "locked"/"unlocked" retired for this branch's TEC panel; `max_wait_s` claim narrowed to software-only

Two imprecise claims, found while doing a documentation-accuracy pass
(no code changed):

1. **"Locked"/"unlocked" TEC phrasing (used below, in the 2026-10-15
   "Mission recalibration" entry, and in `acceptance_table.md`/
   `migration_checklist.md` before this correction) misdescribed what
   `SimpleSeriesPanel` actually does.** That vocabulary is junjiebranch's,
   for a ch1/ch2 broadcast relationship ("locked" = ch2 mirrors ch1
   automatically). This branch's panel has no such relationship at all:
   `compile_simple_series()` always emits `"channels":
   [settings.tec_channel]` — exactly one channel, chosen by the panel's
   single `tec_channel` combo box. There is no UI path that addresses
   both channels, matching or not. `acceptance_table.md` and
   `migration_checklist.md` are corrected to describe this as
   "single-channel, operator-selected" instead of "locked," and to
   describe the engine-only dict-valued/multi-channel capability as
   "both channels from one definition" instead of "unlocked." The
   historical entries below keep the old wording since they describe
   what was true/claimed at the time; this entry is the correction of
   record.
2. **A short `temperature_max_wait_s` being executable is not evidence
   that a real TEC can physically stabilize that fast.** The entry
   immediately below proved `max_wait_s=0.1` runs to completion without
   error — true, but only because `SimulatedTec` reaches its setpoint
   instantly with zero thermal lag. On real hardware a short window would
   likely (and correctly) fail the tolerance check instead of succeeding,
   since real thermal settling takes real time that hasn't been measured
   on either branch. `acceptance_table.md`'s corresponding row now states
   this explicitly, so "executable" is not read as "physically sensible to
   use."

---

## 2026-10-15 — `max_wait_s` actually fixed, superseding the prior entry's "removed, relies on graceful failure"

The prior round's fix (below, "The `temperature_max_wait_s >= 1.0` floor
was reviewed") only changed a compile-time rejection into a run-time
failure — a value under 1s still could not actually be *used*, and worse,
it would fail only after the series-level flush had already run (fluid
already moved before the bad parameter was discovered). Not acceptable as
"fixed."

**Real fix**: `experiment_runner.py`'s `_run_action()`, `"tec_wait_stable"`
branch, now computes `poll_interval_s = min(1.0, max_wait_s)` before
constructing `TecWaitStableArgs`, instead of leaving it at the fixed 1.0s
default. Any `max_wait_s` is now self-consistent by construction — there
is no longer an invalid combination reachable through the declarative
step pipeline, for any value above the existing `> 0` requirement. Proven
by actually completing a series with `max_wait_s=0.1`, not by asserting it
compiles or fails cleanly: `test_tec_wait_stable_with_a_sub_one_second_
max_wait_actually_runs` (raw definition) and
`test_ui_configured_short_max_wait_actually_completes` (real panel path).

The prior round's `test_tec_wait_stable_argument_construction_failure_
reports_cleanly` tested a scenario that can no longer occur (poll_interval_s
exceeding max_wait_s) — replaced with
`test_tec_wait_stable_with_a_sub_one_second_max_wait_actually_runs` above.
The general exception-propagation fix in `_run_action()` (catching any
command-argument construction error, not just this one) stays — it's
still correct defensive code, just no longer the *only* thing standing
between a short `max_wait_s` and a crash, because there's no longer an
error case to fall back to it for in this specific scenario.

---

## 2026-10-15 — Mission recalibration: proportionate complexity, not parity

This is a lab hardware-control algorithm project. The goal is to run
experiments correctly and stay easy to adjust — not to fully replicate
junjiebranch, clear every "unfinished" item, or cover every theoretical
case. junjiebranch's documentation, restrictions, and protections are
**material to evaluate**, not inherit by default: a lot of recorded
planning there does not by itself mean this branch must carry it. Four
things follow from that, recorded here rather than in a new file.

### Restrictions reviewed against "what does it actually prevent"

| Restriction | Prevents | Other-layer coverage | Cost on normal use | Verdict |
|---|---|---|---|---|
| `FlushWorkflow._implausible_reading()` (pump) | Computing a flush target from a stale/implausible SDK fill-level reading | None — `PumpWorker.set_fill_level()`'s target-range check is a different thing (protects the target, not the reading) | None on a legitimate reading; only engages on genuinely implausible data | **Keep** — real documented incident (`-513` SDK rejection on junjiebranch), not speculative |
| `_run_action()`'s whole-dispatch try/except | An exception while building a command's own arguments crashing uncaught into the Qt callback chain | None — `_submit()`'s try/except never covered this | None — only engages on a genuine construction error | **Keep** — general correctness fix, not a restriction on normal use at all |
| `temperature_max_wait_s` compile-time floor (removed this round) | Nothing a real device needs — the 1.0s came from `TecWaitStableArgs.poll_interval_s`, a software polling default | The propagation fix above already reports the same inconsistency gracefully at run time | Forced every operator to learn and respect an arbitrary number with no physical meaning | **Removed** — exactly the "software default dressed as a device requirement" this review was asked to find. **Superseded by the entry above this one**: "reports it gracefully" was still not the same as "actually works" — the poll interval now adapts instead, so there's no failure case left to report |
| Z-stage two-tier operator confirmation (junjiebranch had it, this branch doesn't) | A real device-constraint concern (piezo motion without explicit authorization) | None currently | Would add a second confirmation dialog to every Z move | **Not added** (decided previously) — real device constraint, but no real Z-stage work is authorized yet to need it; revisit if/when real Z motion is actually planned, not speculatively now |
| TEC `temperature_wait_for_stability` (optional, default off) | Nothing when unused — the default path compiles identically to before it existed | N/A | Zero cost unless explicitly enabled | **Keep** — proportionate: it's an opt-in capability add, not a forced complexity increase |

No restriction was found this round that needed removing beyond the
`max_wait_s` floor above. The pump/propagation items are not restrictions
on normal use at all — they only ever engage on an actual error condition.

### Day-to-day modification cost (where the common changes actually go)

Checked against current code, not estimated:

- **Temperature strategy** (tolerance, settle/hold durations, locked vs.
  unlocked): `application/simple_series.py` (`SimpleSeriesSettings` fields
  + `compile_simple_series()`'s `temperature_steps` construction) and
  `ui/simple_series_panel.py` (the Temperature group widgets). The
  underlying per-point gating mechanism itself (`tec_set`/`tec_wait_stable`
  dispatch) is `experiment_runner.py`'s `_run_action()` + `_tec_args()`;
  changing *values* never touches that file, only changing the *mechanism*
  would. One real coupling point worth knowing: UI widget ↔
  `SimpleSeriesSettings` field ↔ compiled JSON arg ↔ `TecApplySetpointsArgs`/
  `TecWaitStableArgs` field is a consistent 1:1 chain with no duplicated
  logic — changing a default means touching the UI default and the
  dataclass default together (2 files), which is the minimum necessary,
  not padding.
- **Parameter sweep** (adding a new scan axis): `application/experiments.py`'s
  `_values()` (value-list parsing) and `walk()`'s `"sweep"` handling
  (cartesian expansion). One specific coupling point: the `labels` dict
  inside `walk()` (around the sweep-parameter-name → folder-prefix mapping)
  is hardcoded to recognize specific names for `simple_series` folder
  naming — adding a new named sweep parameter through the simple-series
  compiler means updating both `simple_series.py` and this dict, or the
  new parameter's folders fall back to a generic `name=value` label. Small,
  bounded, not worth refactoring away — a lookup table is the
  proportionate solution for a handful of named parameters.
- **Acquisition timing** (frame rate, exposure, trigger windows):
  touches three places, each catching a *different* class of problem, not
  redundant layers: `experiments.py`'s `_validate_experiment()` (static
  schema/ordering correctness — can this JSON even make sense),
  `experiment_runner.py`'s `_after_camera_timing()` (series-wide sanity
  against *live* SDK-reported numbers — laser window, live minimum trigger
  interval), and `_configure_all_before_fluidics()` (the actually-applied
  value against the bounded output-timeout window). Collapsing these would
  conflate "is this JSON internally consistent" with "does the live
  hardware actually accept it," which are genuinely different questions —
  not recommended.
- **Adding a new experiment-step kind** (a new leaf action): touches
  `experiments.py`'s `ACTION_RESOURCES` dict (resource declaration, for
  `parallel`-block conflict checks) and `_action()`'s schema validation,
  plus `experiment_runner.py`'s `_run_action()` dispatch (actual
  execution), and possibly `_validate_experiment()` if the new kind has an
  ordering constraint. A genuine 2-3-file touch, but it is the intentional
  split between validation and execution this architecture was built
  around — merging them back would reproduce the kind of monolithic
  coupling junjiebranch's `qt_ui.py` had.

**No simplification was made in this pass beyond removing the
`max_wait_s` floor above.** The multi-file touch points found are
intentional separation of concerns (schema vs. live-sanity vs. applied-value
checks; validation vs. execution), not accidental duplication — forcing a
refactor to reduce file count here would trade real clarity for a
superficially smaller diff, which is the opposite of what was asked.

---

## 2026-10-15 — Corrections from Codex's review of 6a0a8a5

Five corrections accepted and acted on, not just acknowledged:

1. **Real-time persistence was not actually done.** `record_experiment_
   started/completed/failed()` only incremented in-memory counters;
   `status.json` was never rewritten between the series' "running" call and
   its terminal one. Fixed: each now calls `status("running", {})`
   immediately. Verified by reading `status.json` from disk **while the
   series is still running** (`test_lifecycle_counts_are_persisted_before_
   the_series_ends`), not only at the end — the specific thing the prior
   claim of "done" had not actually checked.
2. **Panic was not zero-coverage** — `test_panic_stops_connected_outputs_
   without_moving_valve` already exercises `controller.panic_stop()` →
   `experiments.panic_abort()`, just with no series running. Re-scoped the
   gap correctly: stop/abort/panic semantics **while a series is actively
   running** had no coverage, and still needed `stop_after_current()`/
   `abort()` added regardless. Three new tests cover all three for the
   in-series case, each checking only the series-level consequence (next
   experiment doesn't start, final counts stay consistent) without
   re-asserting the already-covered single-device SAFE_STOP facts.
3. **The parallel-barrier test was not actually evidence of the barrier.**
   It used `AD2_DIGITAL_OUTPUT_STOP` as a proxy for "both branches done,"
   but that event precedes the per-experiment flush in the same branch and
   says nothing about the independent save branch at all. Replaced with
   two tests that each deliberately slow one branch by a controlled,
   known amount and measure that the real wall-clock gap to the next
   experiment is at least that amount.
4. **The `temperature_max_wait_s >= 1.0` floor was reviewed, not just
   defended.** The 1.0s came from `TecWaitStableArgs.poll_interval_s`'s
   *software* default, not a hardware fact. Considered: keep the check
   (clearer, earlier error) vs. make `poll_interval_s` itself adapt to
   `max_wait_s` (would require widening the "tec_wait_stable" JSON schema
   to accept it, a bigger change for a narrow benefit) vs. rely solely on
   graceful runtime failure. Chose to **fix the actual safety problem
   first** (exception propagation from command-argument construction,
   `experiment_runner.py`'s `_run_action()` — general fix, not
   TEC-specific) and **keep** the compile-time check only as a secondary,
   now-honestly-labeled convenience (reads the real default via
   `TecWaitStableArgs.__dataclass_fields__`, not a second hardcoded "1.0"),
   since the propagation fix means it's no longer the only thing standing
   between a bad value and a crash.
5. **Added the explicitly-requested whole-series flush-budget tests**: 3
   placements (series-level only, per-repeat only, mixed), each confirming
   `_check_capacity`'s rejection message cites the correct total.

Also: `TEC multi-point (unlocked)`, junjiebranch's temperature-point-level
counters, and the data-format decision are kept in `migration_checklist.md`
with their actual use case and implementation scope spelled out, per
instruction not to let "keep TIFF+JSON" read as "external compatibility
resolved" — it isn't; the external LabVIEW consumer was never checked.

Full suite after all fixes: see the commit this entry ships with for the
exact pass count.

---

## 2026-10-14 — End-to-end flow verification batch

**Correction accepted**: the earlier "TEC multi-point sequencing: done"
claim was verified only via a hand-authored JSON definition in
`tests/test_experiments.py`, which proves the *executor* supports it but
not that an operator can reach it. The real UI
(`ui/simple_series_panel.py`) only ever compiled `tec_set` → fixed `wait`.
Closed by adding an *optional*, default-off `temperature_wait_for_stability`
field (`application/simple_series.py`, `SimpleSeriesSettings`) plus matching
panel widgets — every existing default-constructed series still compiles
byte-identically (verified:
`test_temperature_wait_for_stability_is_additive_and_opt_in`). This is a
genuinely additive capability, not a change to existing experimental
semantics, so it did not need to be escalated as a reserved decision.

**Full baseline trace**: `docs/integration/flow_trace.md` now documents the
actual stage-by-stage call chain (UI → compile → queue → start → per-series
preflight/validation → node execution → leaf actions → completion →
stop/abort/recover), with direct answers to the specific ordering/scope
questions raised (flush scope, temperature-stable-then-hold gating,
camera/AD2 trigger unification, frame/timestamp correspondence, parallel
save/flush barrier, per-experiment re-configuration, and the three distinct
stop/abort/recover paths) — plus a targeted (not exhaustive) comparison
against junjiebranch's `application.py`/`workflows.py`, finding one genuine
architectural difference (junjiebranch runs flush and save **sequentially**
within one fixed per-repeat step order; this branch runs them as two
**concurrent** branches with a hard barrier) and one consistency win (this
branch checks graceful-stop at one uniform point; junjiebranch checks it at
two separate layers, UI and Application).

**Test-infrastructure note, not a product defect**: the first version of
`test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order`
constructed a full `MainWindow` and took 349s, printing a transient
`faulthandler` trace ("Windows fatal exception: code 0x8001010d") from a
background file-save thread partway through — the test still passed (exit
0), but the cost and the alarming-looking trace were both real. Switching
the harness to construct only `SimpleSeriesPanel` directly (the actual
object under test) brought it to 20s with no trace. Not filed as a known
open item: this was caused by the test harness's own over-construction, not
by application code, and is resolved.

**Explicit limitation**: this session has no desktop computer-use tool
available (only a Chrome-browser automation tool, not applicable to this
PySide6 desktop app) — "UI verification" this round means real widget-level
automation (constructing the actual panel classes, setting real widget
values, reading real compiled output), which exercises the same Qt signal/
slot code paths a manual click would, but is not literal mouse/keyboard
interaction with a running window. No confirmation dialogs were clicked
through manually for the same reason — automated tests injected confirm
callback answers (`confirm_unchecked`, `confirm_batch`) as code, not via a
displayed dialog.

---

## 2026-10-13 — Branch/worktree creation (Phase 0)

**Decision**: create `codex/integration` as a new branch, in an independent
worktree at `C:\git\thermoacoustic-integration`, starting from
`origin/ola-branch` at `5014fc8f479c058904e7e69f2f67384851ab88ce`.

**Why this starting point, not junjiebranch or a from-scratch rewrite**:
junjiebranch's one clearly-scoped architectural defect (the global
`_busy_count`/`_run_action` manual-dispatch mutex) is woven through 45 call
sites across two large, mutually-inheriting UI files
(`qt_ui.py`/`qt_ui_v3.py`, 10,582 lines combined). Replacing it in place
would be a single large, hard-to-stage change with high rollback cost.
ola-branch's equivalent capability (per-device-worker dispatch) is already
correct and already landed; the remaining work is additive, module-by-module
porting of specific junjiebranch algorithm/UI capability, which is safer to
stage and revert independently. Full reasoning and the rejected alternatives
(Option B: junjiebranch as base; a from-empty rewrite) are in the prior
investigation rounds (condensed in `investigation_log.md`).

**Not decided yet, deferred to later batches**: TDMS vs. TIFF+JSON data
format (owner decision), PySide6 version reconciliation (6.8.3 vs. 6.11.1 —
not yet a live conflict since only ola-branch's side is in this worktree, but
will matter if junjiebranch UI code is ever directly referenced again), the
Prepare-tab TEC readback display comparison, the chronology-ordering UX
principle from `lessons_learned.md` §7.1-7.2.

**Explicitly not approved by this entry**: any `src/` change. This entry only
records the branch/worktree creation and the records in this `docs/
integration/` folder.

---

## 2026-10-13 — Valve-confirmation finding corrected

**Prior claim (withdrawn)**: "the automated experiment flow must add
`ValveReadyResult` consumption to avoid a junjiebranch-Bug-2-shaped silent
failure." This was based on looking at the wrong consumer.

**Corrected finding**: `application/experiment_runner.py:857-860` (the
"flush" step) builds a `WorkflowCommand`/`FlushArgs` and submits it through
`ApplicationController.submit()` (`application/controller.py:184`), which at
lines 311-318 routes any `WorkflowCommand` to `_start_flush()`
(`controller.py:348`) — the **only** instantiation site of `FlushWorkflow`
in the codebase (grep-confirmed). `FlushWorkflow._on_timer()`
(`application/workflows.py`) polls `valve.readback` every 250 ms against a
10-second deadline, proceeding only when `isinstance(readback,
ValveReadback) and readback.ready and readback.confirmed_position ==
desired`, with a `RECOVERY_STOP` -> `RECOVERY_CLOSE_COMMAND` path on
mid-flush failure. No bypass path was found: `experiment_runner.py` has no
other `VALVE_POSITION_SET`/`DeviceId.VALVE` reference.

**Action**: none. This item is closed with no code change needed.

**Separate, smaller, not-yet-actioned item**: the standalone
`VALVE_WAIT_READY` command (`hal/valve.py:77-84 wait_until_ready()`) returns
`ValveReadyResult(ready=False, ...)` as a normal `command_succeeded` result,
not a failure. This is reachable only through whatever UI path calls that
command directly (not the automated flush path, confirmed above). No
concrete caller mishandling this was identified. Tracked as open, low
priority, unconfirmed impact — see `known_open_items.md`.

---

## 2026-10-13 — Pump capacity-check location corrected

**Prior claim (withdrawn, stated inconsistently across two earlier rounds)**:
"`_check_capacity` is ola-branch's equivalent of junjiebranch's
`known_capacity_ml` guard, and it does not cover the same scenario." This
compared junjiebranch's guard against the wrong one of three distinct ola
checks.

**Corrected mapping**:
- junjiebranch: `known_capacity_ml` field (`instruments.py:845`, set at
  `instruments.py:981` from a fresh SDK readback inside
  `configure_syringe()`); the guard itself is in `application.py:1149-1156`
  inside `Application.flush()`, comparing a **cached** `self.pump.fill_level`
  against `known_capacity_ml`.
- ola-branch has three checks, not one:
  1. `drivers/pump/cetoni.py:497` `max_volume_ml`, refreshed from a fresh SDK
     call inside `configure_syringe()` — structural equivalent of
     `known_capacity_ml`.
  2. `application/workflows.py` `FlushWorkflow.on_step()`'s `LEVEL_READ`
     state — a **fresh** `PUMP_FILL_LEVEL_READ` SDK call at the moment of
     flush, checking only `target = fill_level_ml - volume_ml >= 0` (enough
     fluid for this flush). Does **not** cross-check the fresh reading
     against `max_volume_ml`.
  3. `application/experiment_runner.py:492 _check_capacity` — a pre-batch
     check using a cached `PumpReadback` snapshot, comparing total planned
     flush volume across the whole series against `fill_level_ml` (a
     batch-budget check, not a per-flush plausibility check).

**Corrected gap**: none of the three checks reproduce junjiebranch's
plausibility cross-check ("is this fill-level reading even possible given
the syringe's own just-confirmed capacity"). ola's `FlushWorkflow.LEVEL_READ`
is the right location for a narrow addition — see Phase 1 plan below,
recorded but **not approved for implementation yet**.

---

## 2026-10-13 — UI items resolved without a code gap

- Z-axis UI: `ui/z_stack_panel.py` compared field-by-field against
  junjiebranch's Z-Scan tab. ola's panel is already a superset (adds ROI,
  position tolerance/timeout, manual jog, live preview, camera-settings
  import). No gap found; no port needed.
- Fault-reason display: `application/event_formatting.py:42
  event_summary()`'s `"failed"` branch already includes `event.message`,
  always populated by `hal/base.py`'s `command_failed.emit(request_id,
  str(exc))`. The bare-"Error" bug junjiebranch fixed in `56386f1` cannot
  occur here. No gap found; no port needed.

---

## 2026-10-13 — Software restrictions reviewed this round (register)

Per the authorization's "identify and simplify unnecessary restrictions"
item, each restriction actually examined during Batches 1-6, what it limits,
its basis, and the disposition:

| Restriction | Limits | Basis | Redundant with another check? | Disposition |
|---|---|---|---|---|
| `experiments.py` `_values()` sweep elements limited to bare str/int/float | Could not express a per-point dict of independent per-channel TEC targets | Original design predates any multi-field sweep need | No | **Simplified**: relaxed to also accept a flat numeric object, generically (Batch 3) |
| `FlushWorkflow` trusted the raw `PUMP_FILL_LEVEL_READ` reading | Nothing, previously — this was a gap, not an over-restriction | — | — | **Added** a narrow check (Batch 2), not a simplification; recorded here only to confirm it was not layered on top of an already-sufficient check |
| `PumpWorker.set_fill_level()`'s target-range validation (`hal/pump.py:88-91`) | A target outside `0..max_volume_ml` | Protects the SDK call itself | Yes, but by design | **Kept distinct from Batch 2's new check** — different failure mode (untrustworthy reading vs. out-of-range target); not merged, not removed |
| `ExperimentManager.queue()` requires a non-empty `description` | Queueing a batch without a human-readable label | Operator record-keeping (keeps batches identifiable later) | No | **Kept as-is** — reasonable operator-facing policy, not incidental friction; just needed adding to test definitions this round |
| `_validate_experiment()`'s `tec_set`/`tec_wait_stable`/`stage_move` must precede camera arm (`experiments.py:433`) | Where TEC/stage nodes may appear inside an experiment block | Camera arming must not race TEC/stage positioning | No | **Kept** — a real ordering constraint, not incidental |

No restriction was found and left unexamined as "probably fine" without a stated reason; none were removed without an equivalent check taking their place.

## 2026-10-13 — Full implementation authorization granted

User authorized autonomous implementation of the integration work (not just
Phase 1's pump-capacity item): TEC multi-point sequencing, experiment
lifecycle/outcome recording, Z-axis parity verification and necessary
gap-filling, valuable junjiebranch UI/operation-flow capability, and
simplification of unnecessary restrictions found along the way — all within
this worktree/branch, committed in small batches (no push/merge without
separate approval). Reserved to user+Codex: changes to experiment scientific
meaning/units/step order, removing a protection with real incident/device
evidence without equivalent coverage, dropping a significant existing
capability, output-format/compatibility-breaking changes, large driver
rewrites or new major dependencies, and any real-hardware/push/merge action.
The Phase-1 plan below is now approved as scoped (pump plausibility check
only, not a general new restriction system) — superseding the "NOT approved"
status in the entry below. See `migration_checklist.md` for live batch
status going forward.

## Phase 1 plan — APPROVED as scoped below (pump capacity only)

**Scope** (as specified): in `application/workflows.py`'s
`FlushWorkflow.on_step()`, `LEVEL_READ` branch, add a check for raw
fill-level reading plausibility — via the application layer
(`PumpReadback.units[unit_index]`'s own capacity field), not by reaching
into the driver directly.

**Confirmed available field** (`domain/models.py`): `PumpUnitReadback` (line
172) has `fill_level_ml: float | None` (174) and `max_volume_ml: float |
None` (178); `PumpReadback` (line 187) aggregates `units` (per-unit list) plus
its own top-level `fill_level_ml`/`requested_fill_level_ml`/`max_volume_ml`.
`FlushWorkflow` has `self.args.unit_index` already, so
`statuses()[DeviceId.PUMP].readback.units[self.args.unit_index].max_volume_ml`
is the exact, already-available path to the selected unit's capacity — no
driver access needed, confirming the approval request's constraint is
directly satisfiable.

**Explicit constraints carried over from the approval request, do not
broaden**:
- `PumpWorker`'s existing target-range validation on `set_fill_level` is a
  separate, already-correct protection against an out-of-range *target*. The
  new check is about distrusting the *raw reading*, not duplicating or
  replacing that existing validation. Do not describe this as "closing all
  out-of-range protection" — it closes one specific gap (plausibility of the
  raw reading), nothing more.
- Must define, before writing any code, what happens when: capacity is
  unknown (pump not yet configured / capacity field absent or `None`); the
  reading is non-finite (`NaN`/`inf`); and what tolerance (if any) is applied
  around the capacity boundary. **None of these are decided yet** — recorded
  here as open design questions for the Phase-1 approval request, not
  resolved unilaterally.

**Required test coverage before this can be considered complete** (from the
approval request, verbatim scope):
1. An implausible reading that pushes the computed target out of range.
2. An implausible reading where the computed target still happens to fall
   in range (i.e., the new check must trigger on the reading itself, not
   only on its downstream consequence).
3. A legitimate reading, normal flush completes.
4. The selected pump unit's capacity is read from the correct unit index
   (`PumpReadback.units[unit_index]`), not a wrong/default unit.
5. The failure path: pump stop, valve recovery-close, and final failure
   state are all reached correctly when the new check trips.

**Status**: plan recorded, no code written, awaiting separate, explicit
approval before any `src/` change.
