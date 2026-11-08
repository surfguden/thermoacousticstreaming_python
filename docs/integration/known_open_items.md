# Integration known open items

Experiment-control behaviour baseline: `aa5f3d1`; Windows launcher fix: `168cac4`. This is a current disposition list, not a development
backlog or authorization for hardware access. `acceptance_table.md` is the overall acceptance
entry; `migration_checklist.md` gives operating steps. Earlier investigations remain in
`investigation_log.md`, `hardware_notes.md`, `decision_log.md` and Git history.

## Hardware evidence: reuse first, investigate a specific gap only

The former six-stage hardware re-verification plan has been retired. It was written before
later historical evidence was fully reconciled and is not a prerequisite to integration acceptance.
Do not repeat connection, pump, TEC or Z tests merely to obtain a new branch-labelled log.

Use this chain for an actual doubt: earlier apparatus/configuration/result -> retained code ->
changed integration boundary -> a specific unanswered requirement. Prefer source, retained records
and offline checks. If a physical question remains, describe the smallest proposed check separately;
no item here authorizes executing it.

| Resource | What can be reused | Scope to preserve |
|---|---|---|
| junjie change-log Sessions 54-56 | Pump/valve motion, rejection/acceptance, serial terminator and fill-level fixes | Use the recorded units/setup; the geometry anomaly is a separate question. |
| junjie Sessions 48/54 | Real Z scan and abort precedent, Decimal conversion fix | Independent integration Z-stack confirms measured position; generic `stage_move` only sends a target. |
| junjie TEC matrix / Sessions 75-77 | Implemented client and historical setpoint/stability reports; separately retained 2026-08-28 reads/OFF | Historical reports are not absent, but the matrix distinguishes them from independently retained bench evidence. Compare the actual HAL wait, not an unused blocking helper. |
| ola tracked WFG results | Production AD2 carrier configuration, PC trigger and before/during/after captures | Does not establish every output, wiring arrangement or physical camera-edge relationship. |

## Open, device/SDK-level (not closeable by software alone)

- **HW-PUMP-FILL-GEOMETRY-001:** historical reading incompatible with the configured syringe
  capacity (`junjiebranch` `docs/p0_hardware_truth_20260828.md`, `known_open_items.md`). Current
  plausibility checks reject the symptom; the records do not settle its device/geometry cause.
  Do not prescribe a reference move as an automatic cure.
- **HW-AD2-BNC-001:** JP4/JP5's 49.9-ohm path is series-source impedance, not a shunt load.
  The note is already retained in `hardware_notes.md`; restoring a note is not still an open task.
  Installed jumper position and external load must not be guessed when interpreting voltage.
- **HW-TIMING-001:** direct DIO0-to-camera edge/spacing measurements are absent from the cited
  records. This limits a physical precision claim; it does not invalidate existing device evidence
  or impose general re-verification. A check is relevant when a stated experiment requirement
  depends on an unsupported timing quantity.
- **HW-LASER-PATH-001:** retained records describe an iBEAM polarity question and W2 use differs
  between the old planner and ola. Installed-unit/polarity details remain unreconciled. No software
  statement here resolves optical off behaviour, and no output strategy is changed.

## Current output policies (retained, not pending routine re-approval)

| Event / device | Current behaviour | Interpretation |
|---|---|---|
| TEC after completion, Stop, Abort or general failure | Regulation remains on | Allows continued temperature control; does not prove sample equilibrium. |
| TEC on Panic / exit | Requests Static OFF; exit then closes communication | Failures must be reported; a request is not independent physical confirmation. |
| Valve on Panic | No new position move | Holds the last position while stops are requested. |
| Window close during a batch | Abort, save/flush recovery drain, then shutdown | An active flush may close the valve during recovery; this is not the Panic path. |
| Generic `stage_move` | Return after acceptance of the limited target | `position_confirmed: false`; use independent Z-stack for the existing arrival-then-capture workflow. |

Real mode selects real factories; a Connect action submits access without an extra
per-device confirmation dialog. Specific pump reference moves and real batch Start
have their own confirmations. This describes current behaviour, not a request to add gates.

These policies are carried forward for current integration scope. Changes require a concrete
experimental need and an explicit decision; this document does not keep asking for the same decision.

## Open, software-only (closeable by review/small change)

| Item | Current consequence | Disposition |
|---|---|---|
| Z-stack failure metadata | `metadata.json` records failed state and saved points, but not the reason or run identity | Useful small candidate for later work. UI has the reason; not a blocker for current successful scans. Existing suite has a happy-path scan; previous timeout inspection was ad hoc, not a permanent failure/stop test. |
| S8: Panic during flush reported as failed | Error says `Cancelled by Panic`; terminal label can be failed rather than aborted | Known classification difference. No evidence it changes retained data or stop actions. Do not swap callbacks without a targeted timing test. |
| S11: valve/TEC serial-port selection | Both accept ports; OS exclusivity prevents simultaneous open, but does not identify a device on the first open | Historical COM6 prohibition is not a current universal mapping. No fixed COM-number ban or generic resource manager is planned. |
| External analysis requirements | TIFF/JSON is available, but an active consumer and its exact needs are not established | Keep format. Inspect a named consumer only when it is actually required; do not infer compatibility or mandatory TDMS support from its absence in this repo. |
| Historical screenshot recipe | Some output, trigger, flush-count and memory assumptions differ from current controls | Provenance/gaps are listed in the operating guide. Not an automatically applied or fully verified current recipe. |
| Human preview/workflow review | Offscreen tests cover behaviour, not screen readability or interaction feel. Layout was inspected on rendered offscreen screenshots only (fonts and a real display's DPI handling were not exercised) | A bounded usability check on the real display when the viewer is used; not a requirement to build an image-analysis suite. |
| Smallest supported screen | The main window can shrink to 900×560 logical pixels; 1366×768 at 150 % scaling (about 910×510 logical) is smaller than that | Reduce the scaling or maximise the window; panels scroll, but the window cannot go below its minimum. |
| Image tools scope | One rectangular analysis ROI, one profile line, no calibration, no saving of measurements; the saved-frame viewer does not follow a running series by itself | Intended minimum. Add only for a stated need. |
| Z-stage refused move or failed TEC wait | The device status becomes ERROR (connected, last operation failed) until the next successful command; the pages and summary now say "Connected, last operation failed" with the reason, but the status semantics are unchanged | Display only; status semantics not changed. |
| Z stack images in the viewer | Z stack writes `point_NNNN.tif` + `metadata.json`; the saved-frames viewer reads only `experiment.json` series | Open output folder is on the Z stack tab; a Z-stack viewer would be a new feature. |
| One base folder = one batch | Retained: a non-empty base folder is refused for a new batch (`SeriesStorage`, ola f717884, `test_experiments.py`). Relaxing it would let different batches share numbered folders with no batch identity on disk | Needs a decision on batch ownership in results; not changed. |

Optional, not default implementation tasks: a recovery button (console/reconnect already exist),
elapsed/remaining time, dual-channel temperature UI and temperature-point counters. No recipe manager, automatic resume or audit framework
is part of the current plan. Restore labelled partial captures only if a concrete experiment needs it.

## Resolved integration items (do not reopen without new evidence)

| Item | Current resolution / evidence |
|---|---|
| S1, S2, S3 | Only recovered pump-poll errors are cleared; disconnected failed Connect is retryable; valid explicit refill/empty flow is honoured, otherwise rejected. Movement calls remain start-only. `test_device_workers.py`. |
| S5 | Snapshot/preview explicitly sets internal trigger; experiment sequence sets external configuration. Fake DCAM regression in `test_driver_fakes.py`; no extra physical behaviour inferred. |
| S6 | AD2 stop attempts independent outputs/scope, with per-channel analog fallback and combined errors. `test_device_workers.py`, `test_driver_fakes.py`. |
| S7 | `stage_move` resource/closed-loop prerequisite checked before fluidics/temperature/capture; not enabled on the operator's behalf. `test_abort_and_close.py`. |
| S9 | Batch `manifest.run` records mode and cached Git identity, preserved on queued edits; missing Git records unknown. No identity is yet added to standalone Z-stack. `test_run_identity.py`. |
| S10 | Abort cancels active TEC waiting through `ABORT_ACTIVE`, releases the lane and leaves regulation on. `test_abort_and_close.py`. |
| Timing and active-batch rules | Actual camera configuration/cadence/exposure checked; one running/stopping/aborting rule used. `test_camera_timing_check.py`, `test_abort_and_close.py`. |
| Z labels | Measured `position_um` separated from `commanded_position_um`; generic move records requested/sent/unconfirmed. `test_device_workers.py`, `test_abort_and_close.py`. |
| Data and lifecycle | Saved captures survive later failure; save/flush and recorder drain guard finalization. Existing failure/race tests in `test_simple_series.py`. |
| Exit | Window drains a running batch, workers cancel/stop/disconnect, errors come from the worker result, shared wait deadline retains pending threads and their owners. Panic during shutdown reports rather than re-dispatching. `test_abort_and_close.py` includes subprocess coverage. |
| Abort stops | Ordinary Abort/failure stops connected devices including those in ERROR (connected, last operation failed), asks each device once, waits for the stop results before the end state and adds a failed stop to the end reason, saved status/events, `stop_failures` and a red monitor alert. TEC regulation is still not touched. Command success is not a measured physical stop. `test_abort_stop_results.py`. |
| Multi-pump stop | `PumpWorker.safe_stop` tries every unit and reports each failure with its unit. `test_device_workers.py`. |
| Z-stack lifecycle | Timers, late results and started saves are tied to their run; an ended run cannot send commands or rewrite its state/metadata, and cannot add to a later run. `test_z_stack.py`. |
| Z reference helpers | A reading older than a requested/accepted move is shown as old and not copied or recorded. `test_prepare_conveniences.py`. |
| S12 | Targeted fake-SDK regressions added for changed code; no requirement to migrate every old driver test. |
| Confirmation / framework choices | Current single Z confirmation strategy retained; no duplicate gate, general audit subsystem or automatic resume. |

## Series-lifecycle persistence — current manual interpretation

Counters and terminal outcomes are persisted in `metadata/status.json`. No automatic crash
reconciliation or resume is implemented or planned. To inspect a run after an abnormal exit:

1. Read `state`, `finalized_outcome`, counters and error. Terminal outcomes include `completed`,
   `failed`, `aborted`, `stopped_after_current`, `cancelled`, `removed_from_queue`.
2. A non-terminal `queued`, `preflight` or `running` file alone does not distinguish an active
   process from an abandoned run. Check whether its owning process still exists and uses this
   output root. `updated_utc` is context, not a heartbeat guarantee or a fixed abandonment timeout.
3. Counters are the latest persisted software progress, not proof of physical state or everything
   that happened at the instant of a crash. Cross-check `manifest.json`, `events.jsonl` and actual
   experiment folders. Atomic saving publishes a complete acquisition folder **before** later
   post-acquisition finalization; a folder is not proof that flush or the whole experiment succeeded.
4. `experiment.json` has `acquisition_status`, frame records and optional `post_acquisition` outcome.
   A saved acquisition can coexist with a later experiment failure. Inspect both levels.
5. Do not mark an abandoned run successful or restart hardware from the record automatically.
   This inspection neither determines nor changes the physical output state.

Source/parameter evidence and accepted differences are in `acceptance_table.md`. Previous
native Python aborts remain without a proven common root cause; later clean runs and specific
thread-lifetime fixes must not be described as proof that every native abort cause is eliminated.
