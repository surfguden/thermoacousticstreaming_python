# Integration known open items

No item here authorizes a code change by itself. Each item names where it
came from and what would close it. Categories borrowed loosely from
junjiebranch's own `known_open_items.md` (not copied verbatim — remapped to
this branch's actual files).

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

## Explicitly closed this round (do not reopen without new evidence)

- Automated-flow valve confirmation: closed, no gap (see `decision_log.md`).
- Z-axis UI field coverage: closed, no gap (ola's `z_stack_panel.py` is a
  superset of junjiebranch's Z-Scan tab fields).
- Fault-reason message surfacing: closed, no gap (`event_formatting.py`
  already includes `event.message` on every failure).
