# Integration known open items

No item here authorizes a code change by itself. Each item names where it
came from and what would close it. Categories borrowed loosely from
junjiebranch's own `known_open_items.md` (not copied verbatim — remapped to
this branch's actual files).

## Series-lifecycle persistence — split A/B/C per explicit instruction

**A. Real-time persistence of in-progress state — done, fixed this round
(was not actually done before, despite an earlier claim that it was).**
`record_experiment_started/completed/failed()` previously only incremented
in-memory counters on `SeriesStorage` — they never called `status()`, so
`status.json` was not rewritten between the series' own `status("running")`
call (at `_begin_steps()`) and its next real transition (the final terminal
call). A crash between two experiments would have left `status.json`
showing stale, pre-increment counts, which is exactly the opposite of what
"real-time persistence" is supposed to mean. **Fixed**: each of the three
methods now calls `self.status("running", {})` immediately after
incrementing (`"running"` is correct — these are only ever called while the
series is actively running). **Verified by reading `status.json` from disk
while the series has not yet reached a terminal state**
(`tests/test_simple_series.py::test_lifecycle_counts_are_persisted_before_the_series_ends`),
not only by checking the final file, per explicit instruction. No code path
ever marks an abnormally-ended record as successful: there is no
reconciliation logic at all (see C below), so a "running" record simply
stays "running" — it is never rewritten to "completed" by anything other
than the same process's own `_complete_series()` actually finishing.

**B. Crash state interpretation — documented procedure for manual
inspection, not code, per this round's explicit instruction.** To
determine whether a given `experiment_batch_NNNN/metadata/status.json` on
disk represents a series that is *genuinely still running* or one whose
owning process *died without finishing it*:
1. Check `state`. A terminal value (`completed`, `failed`, `aborted`,
   `stopped_after_current`, `cancelled`, `removed_from_queue`) means the
   series ended and this file is the authoritative final record — nothing
   further to interpret.
2. A non-terminal value (`queued`, `preflight`, `running`) is ambiguous by
   itself: it could be a series genuinely in progress right now, or one
   whose process crashed. Compare `updated_utc` against the current time —
   a `running` record whose `updated_utc` is more than a few polling
   intervals old (this architecture polls/updates frequently during an
   active run) **and** no application process is currently attached to
   that output root is strong evidence of an abandoned run.
3. If abandoned: `experiments_started`/`experiments_completed`/
   `experiments_failed` give the exact counts reached before the process
   died — these are reliable (per A) even though no `finalized_outcome` was
   ever written. Cross-reference `manifest.json` (the planned experiment
   list) and the experiment subfolders actually present on disk (an
   experiment folder only exists once `finalize_experiment()` has written
   its `experiment.json` — see `experiment_runner.py:797-799`) to see
   exactly which repeats/points completed.
4. **Never treat an abandoned non-terminal record as evidence of success or
   failure on its own** — it is evidence only that the record is stale;
   whether the underlying hardware was left in a safe state is a separate,
   unanswered question this procedure does not address.
This procedure is manual (an operator or a support engineer reads the
file), not a UI feature — appropriate for this round's scope.

**C. Automatic resume/reconciliation — explicitly out of scope this
round**, per instruction. Not designed, not stubbed, not implemented. If
wanted later, the starting point is the same options recorded in the prior
draft of this entry: a read-only startup scan surfaced to the operator, or
something more automatic — a UI-surfacing and workflow decision for
you/Codex, not sized or chosen here.

- **Z-stage closed-loop mode switch has no operator confirmation gate; a
  separate motion-authorization gate is absent entirely.** junjiebranch's
  `piezo_zscan.py` `ZScanCalibration` requires two independent, explicit
  confirmations before any Z motion: (1) `confirm_closed_loop_switch` — a
  caller-supplied callback, required because "PiezoStage.connect() only
  ever reads the live mode, it never switches it" (Session 45/46 owner
  decision); refusing to proceed (fail-closed) if no callback is given; and
  (2) `confirm_motion` — a *separate* explicit motion authorization,
  independent of (1), because "ClosedLoop mode alone does not authorize
  piezo movement." On this branch, `hal/z_stage.py:55 enable_closed_loop()`
  calls `self.device.switch_to_closed_loop()` directly, and
  `application/controller.py:229-238`'s handling of
  `Z_STAGE_CLOSED_LOOP_ENABLE` only checks that the confirmation
  *requirement* was read first (`closed_loop_confirmation_required is not
  None`) — it never calls `self.confirm_operation(...)`, unlike
  `PUMP_REFERENCE_MOVE` (`controller.py:239-246`, which does call
  `confirm_operation` with an explicit prompt). This is confirmed
  deliberate, not an oversight: `tests/test_single_process_architecture.py
  :376 test_z_stage_mode_switch_requires_query_and_confirmation` explicitly
  asserts `confirmations == []` after a successful enable. No UI-layer
  confirmation dialog substitutes for this either (`ui/device_panels.py
  :2024-2025`'s "Enable closed loop" button has no confirm prompt). There is
  also no separate motion-authorization gate anywhere for
  `Z_STAGE_POSITION_SET`/`Z_STAGE_POSITION_RELATIVE`.

  **Decided this round: keep the current single-gate design as-is.** You
  and Codex reviewed the three options previously recorded here (add a
  `confirm_operation` call mirroring `PUMP_REFERENCE_MOVE`; add a second,
  independent motion-confirmation gate mirroring junjiebranch's
  `confirm_motion` more precisely; or accept the current design) and chose
  to accept the current design — recorded here as a **documented strategy
  difference from junjiebranch, not an open gap to close**. No code change
  made. If real Z-stage hardware work is ever authorized, this is the
  decision that was made and why (physical risk profile judged acceptable
  with the single closed-loop-state gate); revisit only on new evidence,
  not by rediscovering this same comparison again.

## Open, device/SDK-level (not closeable by software alone)

- **HW-PUMP-FILL-GEOMETRY-001** (origin: junjiebranch, `docs/
  p0_hardware_truth_20260828.md`, `known_open_items.md`): does a Qmix
  syringe-geometry change require a fresh `reference_move()` before
  `read_fill_level()`/`get_fill_level()` is trustworthy, or is this a
  Qmix SDK/driver-level inconsistency independent of reference state?
  Software cannot answer this from logs alone. Still open as of
  junjiebranch HEAD `2528c1c`; not re-investigated this round. The Phase-1
  plan (see `decision_log.md`) adds a software-side plausibility guard
  against the *symptom*, not a resolution of this underlying question.
- **HW-AD2-BNC-001** (origin: junjiebranch docs only, never in code on
  either branch): the AD2 BNC breakout's `JP4`/`JP5` jumpers select a
  49.9-ohm series-source path, not a 50-ohm shunt load — changes real
  output voltage math. Grepped `JP4`/`49.9`/`series-source`/`shunt` across
  `drivers/ad2/analog_discovery.py` and `drivers/ad2/configuration.py` in
  this worktree: zero matches. Undocumented anywhere in this branch's live
  tree. Needs either a restored doc note or a code-level comment before any
  real W1 output work.
- **UI-PUMP-STOP-THREAD-SAFETY-001** (origin: junjiebranch `430893a`): the
  fix for "Stop pump silently no-ops" used a concurrent-dispatch escape
  hatch whose thread-safety was explicitly marked unverified. Not
  applicable to this branch's architecture as-is (ola-branch's
  `execute_urgent()` is a different mechanism), but the underlying question
  — "is it safe to issue a stop command concurrently with an in-flight pump
  motion command" — has not been independently re-asked against this
  branch's `DeviceWorker.execute_urgent()` path.

## Open, software-only (closeable by review/small change)

- **Valve `VALVE_WAIT_READY` return semantics — verified, no operator-visible
  gap found.** The command itself reports `ok=True` even when
  `ValveReadyResult.ready=False` (`hal/valve.py:77-84`), confirmed. But the
  one caller (`ui/device_panels.py:1453`, the manual Valve panel's "Wait
  until ready" button) reads `readback.ready`/`readback.status_note` via
  `update_readback()` (`device_panels.py:1496-1503`), which the same HAL
  handler updates with the true `ready`/`status_note` state regardless of
  the command's own ok/fail framing — so the operator-visible label
  ("Ready: No" + status note) is correct even though the button's own
  success/fail styling would show green. No silent failure reaches the
  operator. **Closed, no change made.**
- **TEC Prepare-tab readback display — resolved, small fix applied.**
  ola-branch's `TecPanel` already separates the two values structurally:
  the input fields (`target`/`target_1`/`target_2`) show the software's
  last successfully-applied setpoint, while the status table's "Target °C"
  column shows the controller's own readback. What was missing was the
  display handling a `None` controller-reported target (a real protocol
  characteristic junjiebranch found) clearly: it rendered the literal
  string `"None"`. Fixed to use the panel's existing "—" convention (same
  as Pump/Valve panels) plus a tooltip on the column header explaining the
  characteristic. Test: `test_tec_table_shows_dash_not_literal_none_for_an_
  unreported_target`.
- **Chronology-ordered Prepare checklist — insufficient evidence to act,
  deferred.** junjiebranch's `lessons_learned.md` §7.1-7.2 records a UX
  principle (order by operator chronology, not subsystem ownership),
  arrived at from real operator feedback on their specific workflow.
  `ui/simple_series_panel.py`'s current group order is Output/acquisition →
  Hardware timing → Ultrasound → Temperature → Camera → Flush. Whether this
  matches *this* lab's actual operating chronology (e.g., should fluidics
  prep happen before temperature/camera setup?) cannot be determined from
  code alone — junjiebranch's own reordering was driven by real operator
  observation, which this round has none of. **Not reordered.** Needs an
  actual operator's input on the real workflow sequence before any change;
  marking this unknown rather than assuming either the current order or a
  reordering is correct.
- **Z-stack algorithm parity** (not UI parity, which is resolved — see
  `decision_log.md`): `application/z_stack.py`'s stepping algorithm has not
  been compared against junjiebranch's `piezo_zscan.py`
  `ZScanCalibration.run()` logic. Only the UI *fields* were compared this
  round. Blocks: any claim that Z-axis is fully at parity.
- **TEC multi-point temperature-scan sequencing**: junjiebranch's
  `TemperatureSeries` (dual-channel independent targets, tolerance/settle/
  hold) has no ola-branch equivalent. Confirmed gap, not yet designed.
  Blocks: any multi-point TEC experiment capability on this branch.

## Z-axis algorithm parity — resolved findings (not reserved)

Compared `piezo_zscan.py`'s `ZScanCalibration.run()`/`_acquire_one()` against
`application/z_stack.py`'s `ZStackRunner`:

- **Position confirmation: ola's is more rigorous, not a regression.**
  junjiebranch moves then sleeps a fixed `settle_delay_ms` with no
  position-convergence check at all ("deliberately not replaced with
  threshold-based confirmation logic," per its own comment). ola's
  `_move_accepted`/`_verify_position`/`_position_read`
  (`application/z_stack.py:216-240`) polls the real position readback
  against `tolerance_um` every 100ms up to `position_timeout_s`, only
  capturing once actually confirmed within tolerance. No action needed.
- **Point parameterization differs by design, not a gap.** junjiebranch
  takes `z_start_um`/`z_end_um`/`step_size_um` (fixed step, variable point
  count, uneven last interval to hit the exact end). ola's `ZStackSettings`
  takes `start_um`/`stop_um`/`points` (fixed point count, even spacing,
  linspace-style — `positions()` at `z_stack.py:49-51`). Both are valid;
  switching would change the scientific meaning of "step size" vs "point
  count," which is a reserved-decision category on its own merits if ever
  requested — not requested here, so left as-is.
- **UI field coverage**: already confirmed a superset in the prior round
  (`ui/z_stack_panel.py` has start/stop/points/step/exposure/ROI/tolerance/
  timeout/manual-jog/live-preview — junjiebranch's tab has start/end/step/
  exposure/output-dir only).

## Explicitly closed this round (do not reopen without new evidence)

- Automated-flow valve confirmation: closed, no gap (see `decision_log.md`).
- Z-axis UI field coverage: closed, no gap (ola's `z_stack_panel.py` is a
  superset of junjiebranch's Z-Scan tab fields).
- Fault-reason message surfacing: closed, no gap (`event_formatting.py`
  already includes `event.message` on every failure).
