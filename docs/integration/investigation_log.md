# Integration investigation log

This branch (`codex/integration`) was created from `origin/ola-branch` at
`5014fc8f479c058904e7e69f2f67384851ab88ce` to combine ola-branch's device/
experiment-flow architecture with junjiebranch-specific algorithm and device
capability (TEC temperature-scan sequencing, Z-axis, UI affordances), where
that capability is genuinely missing or weaker on ola-branch. Both original
branches (`ola-branch`, `junjiebranch`) are left untouched; this branch lives
in an independent worktree at `C:\git\thermoacoustic-integration`.

This file condenses four rounds of read-only investigation conducted before
this branch existed. Treat it as a starting index, not the full record — the
original conversation transcripts contain the complete evidence trail,
including corrections made across rounds (see `decision_log.md` for what
changed and why).

## Branch topology (git facts)

- `origin/junjiebranch` HEAD: `2528c1c4120fd709c6ca2ee37a5ac777f03783de`
  (2026-09-07, "Operator control gate audit + documentation reduction closure").
- `origin/ola-branch` HEAD: `5014fc8f479c058904e7e69f2f67384851ab88ce`
  (2026-09-30, "Add real TEC connection, Z stack, and batch preflight controls").
- `git merge-base origin/junjiebranch origin/ola-branch` = `2528c1c` itself:
  **junjiebranch's tip is a direct ancestor of ola-branch**. ola-branch is not
  an independent rewrite from `main` — it is junjiebranch's full history,
  followed by an 88-commit rewrite (`git diff origin/junjiebranch
  origin/ola-branch --stat`: 2374 files changed, +35,113/-84,152 lines).
- `main` HEAD: `aa7b954a5432821a5191102aa161cd0c98f6e75c` (2026-06-25) — ancestor
  of both branches; not otherwise involved in this integration.

## AGENTS.md diff at the two target commits (Phase 0 deliverable — not modified)

Diffed `junjiebranch:AGENTS.md` (`2528c1c`) against `ola-branch:AGENTS.md`
(`5014fc8`); confirmed byte-identical to `ola-branch:AGENTS.md` at `f381796`
(no AGENTS.md change in the last ola-branch commit).

- junjiebranch's `AGENTS.md` (101 lines) is an elaborate "Repository Working
  Contract": authority/conflict-resolution rules, a layered session-reading
  order, a `tools/audit_change_surface.py` requirement for shared-runtime
  changes, an explicit V1/V3 UI-surface ownership map (`qt_ui.py` vs
  `qt_ui_v3.py`), and concurrent-worktree rules.
- ola-branch's `AGENTS.md` (29 lines, the file this worktree now has) is a
  short, generic "Working rules" file — the product of commit
  `c747419 "Simplify agent instructions and retire LabVIEW screenshots"`.
- **Not modified this round or any prior round.** This diff is reported, not
  acted on, per explicit instruction every round.

## Architecture summary (ola-branch, this branch's starting point)

`main.py` -> `DeviceRegistry` (one `QThread` per device: AD2/Pump/Valve/
Camera/TEC/Z-stage, `hal/registry.py`) -> `DeviceWorker.execute()`/
`execute_urgent()` (`hal/base.py`) -> `ApplicationController.submit()`
(`application/controller.py`) -> UI only ever calls
`controller.submit(command)` (`ui/main_window.py:257`); `ui/device_panels.py`
imports only `application.commands`/`domain.models`, never a driver.

Automated batch experiments: `application/experiment_runner.py`'s
`ExperimentManager` (queue/start/stop_after_current/abort/panic_abort),
built on typed commands dispatched through the same per-device workers.

Pump/valve resource-holding during a flush is a dedicated state machine,
`application/workflows.py`'s `FlushWorkflow`, not a generic mutex — see
`decision_log.md` for the corrected analysis of how it confirms valve
position (timeout + recovery) and where its pump-capacity check actually is
weak.

## junjiebranch-specific findings (condensed)

- junjiebranch's manual/service device-control dispatch
  (`qt_ui.py`/`qt_ui_v3.py`) is built around one global `_busy_count`/
  `_run_action(resource=...)` mutex (`qt_ui.py:791,5340`), with a
  resource-tag overlay added for Pump/Valve only in commit `56386f1`
  ("Real Shakedown Round 2"). Camera/Z/TEC remain globally gated; that
  commit's own text states their independence "was not investigated or
  evidenced." Confirmed still the live architecture at HEAD (`2528c1c`):
  34 call sites in `qt_ui.py`, 11 in `qt_ui_v3.py`, and `qt_ui_v3.py`'s
  `MainWindowV3Compatibility` inherits directly from `qt_ui.MainWindow`
  (`qt_ui_v3_support.py:203`).
- This defect is confined to the **manual-dispatch UI layer**. The automated
  experiment engine (`workflows.py`: `Experiment2`, `ExperimentSeries2`,
  `TemperatureSeries`, `SeriesLifecycleManifest`) has **zero references** to
  `_busy_count`/`_run_action`/`QThread` (grep-confirmed) — it is portable,
  reusable algorithm code, not coupled to the broken dispatch pattern.
- Four concrete base-flow bugs were found via real hardware shakedown and
  fixed within junjiebranch's own history, **before** HEAD `2528c1c`:
  1. Stale cached pump fill-level exceeding just-configured syringe capacity
     -> real `-513` SDK rejection (fixed `430893a`, `known_capacity_ml`
     guard in `application.py:1149-1156`, source field in
     `instruments.py:845,981`). The underlying device/SDK behavior question
     (`HW-PUMP-FILL-GEOMETRY-001`) is still open in junjiebranch's own docs.
  2. A non-exceptional flush failure (`wait_for_pump()` timeout returning
     `False` without raising) was invisible to the execution indicator
     (fixed `430893a`).
  3. "Stop pump" silently no-op'd behind the global busy guard (fixed
     `430893a`, via `_run_action(force=True)`); the fix's own thread-safety
     is explicitly marked unverified (`UI-PUMP-STOP-THREAD-SAFETY-001`,
     not found closed by any later commit through HEAD).
  4. A real AD2 Channel-0 continuous-output misconfiguration surfaced too
     late (deep inside `STEP_INITIALIZE_EXPERIMENT`) and too vaguely (fixed
     `56386f1`, moved to preflight in `experiment_planning.py`'s
     `build_independent_run_plan()`).
- Real-hardware evidence read directly off disk (gitignored, untracked,
  still physically present in the original working tree):
  `logs/hardware_transactions.log` (root, 20,173 lines, 2026-07-30 to
  2026-09-07, junjiebranch era) contains 305 non-OK lines, including real
  Hamamatsu camera faults/timeouts and a real Thorlabs piezo connect
  failure (`FAIL cmd='44533854' error=Failed to connect... Device is not
  connected`).

## ola-branch-specific findings (condensed)

- TEC and Z-stage are **not absent** from ola-branch (an earlier investigation
  round's premise was corrected after direct code review): driver, HAL
  worker, UI panel, and automated-experiment-node integration all exist —
  `drivers/tec/controller.py`, `hal/tec.py`, `ui/device_panels.py:1847
  TecPanel`, `experiment_runner.py:865-874` dispatching
  `TEC_SETPOINTS_APPLY`/`TEC_WAIT_STABLE`/`Z_STAGE_POSITION_SET` as batch
  nodes. What is genuinely missing is junjiebranch's richer
  `TemperatureSeries` multi-point scan algorithm, and any real-hardware log
  evidence of TEC output or Z-stage motion.
- Real-hardware evidence read directly off disk, ola-branch era:
  `logs/20260925T132740877811Z_real/hardware_transactions.log` (34,671
  lines, 2026-09-25, 72-minute session): pump bus open/select/enable/
  configure, 17,322 status polls, 8,661 fill-level reads (constant at
  1.068 mL throughout — no real motion exercised), valve connect + 8,657
  polls + close, camera open/close, AD2 `configure_wfg`/stop/reset/close —
  **zero FAIL lines**. A second log
  (`logs/20260925T144218712126Z_real/hardware_transactions.log`, 98 lines)
  shows a **real physical valve transition**: `write cmd='P01'` ->
  `query resp='01\r'`, and the reverse for P02. **No TEC or Z-stage
  real-hardware log entries were found anywhere.**
- `ui/z_stack_panel.py` was compared field-by-field against junjiebranch's
  Z-Scan tab this round: ola's panel already has start/stop Z, points,
  step, exposure, 4-field ROI, position tolerance, position timeout, output
  folder, manual jog, live preview, and camera-settings import — a superset
  of junjiebranch's tab fields. **No Z-axis UI gap found.**
- `application/event_formatting.py:42 event_summary()`'s `"failed"` branch
  already renders `f"{subject} — failed: {event.message}"`, with
  `event.message` always populated from `command_failed.emit(request_id,
  str(exc))` (`hal/base.py`) — the bare-"Error" bug junjiebranch fixed in
  `56386f1` cannot occur here by construction. **No fault-message gap
  found.**

See `decision_log.md` for what to actually do about the remaining,
precisely-scoped gaps, and `migration_checklist.md` for the per-module
tracking table.
