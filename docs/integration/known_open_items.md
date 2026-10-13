# Integration known open items

No item here authorizes a code change by itself. Each item names where it
came from and what would close it. Categories borrowed loosely from
junjiebranch's own `known_open_items.md` (not copied verbatim — remapped to
this branch's actual files).

## Reserved for user+Codex decision (per authorization scope)

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

  **This is reserved, not decided here**, per the authorization's "removing
  a protection with explicit device-constraint or real-incident basis,
  without equivalent coverage" clause — discovering this gap during Z-axis
  parity verification is not the same as authorization to add or decline a
  confirmation mechanism unilaterally.

  Options for your/Codex's decision:
  1. Add a `confirm_operation` call for `Z_STAGE_CLOSED_LOOP_ENABLE`,
     mirroring the existing `PUMP_REFERENCE_MOVE` pattern exactly (same
     mechanism already in the codebase, not a new one) — would require
     updating the existing test's `assert confirmations == []` assertion,
     which should not happen without your sign-off since it's an explicit,
     currently-passing safety-relevant assertion.
  2. Add a second, independent confirmation specifically before the first
     `Z_STAGE_POSITION_SET`/`_RELATIVE` of a session (mirrors junjiebranch's
     `confirm_motion` more precisely) — more code, more faithful to the
     original two-gate design.
  3. Decide the existing single-gate design (closed-loop state alone,
     confirmed read-then-enable) is sufficient for this architecture's
     actual physical risk profile, and leave it as-is, documenting this
     explicitly as an accepted divergence rather than a gap.
  **Blocks**: any Z-axis real-hardware motion work; does not block anything
  else (Z-axis offline/simulated work, TEC work, UI work are independent).

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

- **Valve `VALVE_WAIT_READY` return semantics**: `ValveReadyResult(ready=
  False, ...)` is returned as a normal `command_succeeded` result
  (`hal/valve.py:77-84`), not a failure. Confirmed NOT used by the automated
  flush path (`FlushWorkflow` uses `valve.readback` directly, with its own
  timeout/recovery — see `decision_log.md`). No concrete caller mishandling
  this was found. Low priority; needs a targeted look at whatever manual UI
  panel calls `VALVE_WAIT_READY` directly before deciding whether anything
  needs to change.
- **TEC Prepare-tab readback display**: junjiebranch's Prepare tab shows the
  software's requested TEC target separately from the controller's own
  readback (a real protocol characteristic: controller can report ready/
  output-on with `target_temperature_c=None`). Whether ola-branch's
  `TecPanel` (`ui/device_panels.py:1847`) already separates these two values
  has not been checked. Blocks: any UI work in this area.
- **Chronology-ordered Prepare checklist**: junjiebranch's
  `lessons_learned.md` §7.1-7.2 records a UX principle (order
  preparation steps by operator chronology, not subsystem ownership). Which
  ola-branch panel plays the "Prepare" role and its current field order has
  not been checked. Blocks: any UX-ordering change.
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
