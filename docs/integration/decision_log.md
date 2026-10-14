# Integration decision log

Append new entries at the top (newest first). Each entry should name the
SHA(s)/file(s)/function(s) the decision rests on, not just a conclusion.

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
