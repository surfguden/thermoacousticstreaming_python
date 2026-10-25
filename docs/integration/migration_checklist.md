# Feature migration checklist

Status values: `done` (already true on this branch, no action), `planned`
(Phase 1, recorded and awaiting approval), `open` (needs investigation before
a plan can be written), `deferred` (decision owner needed, not a code task).

## Quick reference: running a simulated experiment, and where to change things

**Launching the simulated app** (verified by actually running it from this
branch's worktree, not estimated): the package is not pip-installed in
this worktree, so the `thermo-acoustic-ui` console script
(`pyproject.toml`'s `[project.scripts]`) is not on PATH unless you install
it first. The command below needs no install step and was confirmed to
print a normal `--help` usage line with no import errors:
```
cd src
python -m thermo_acoustic.main --mode simulation
```
`--mode simulation` is also the default — `python -m thermo_acoustic.main`
with no arguments launches the same way. `--mode real` is the only other
value `main.py` accepts, and is out of scope here (hardware access is not
authorized).

**Shortest path to one representative experiment, via the UI**
(`src/thermo_acoustic/ui/simple_series_panel.py`, `SimpleSeriesPanel`,
wired into `MainWindow` as `experiment_panel`). **Corrected this round
(twice)**: the steps below were originally written from reading the code,
not from an actual run — a full-`MainWindow` acceptance test
(`tests/test_simple_series.py::
test_full_main_window_operator_flow_queue_start_status_output_and_stop`)
found the first version of this sequence genuinely failed. That test
also, on its own terms, only proves two narrower things than the first
correction implied, both tightened here:

- **It used specific short values, not "the defaults."** The test sets
  `repeats=2`, `frames=2`, `fps=10`, a single fixed frequency/amplitude/
  exposure (`1`/`1`/`1`), a 16x16 ROI, `volume=0.01`, `flow=200`, sweep
  and temperature control both off. It does **not** leave every field at
  whatever the widget's own built-in default happens to be. Step 4 below
  previously said "every other group... has usable defaults; leave them"
  — that was not what the test checked, and is corrected below:
  leaving fields at their raw widget defaults (rather than the specific
  values just listed) is simply **untested** by this acceptance pass, not
  confirmed safe.
- **A programmatic click is not a human visual check.** The test drives
  real `QPushButton.click()` calls, which do run the same Qt
  signal/slot code a mouse click would — that is genuine evidence the
  button-to-manager wiring works. It is not evidence about anything a
  human would judge by looking at the running window (layout, label
  wrapping, whether a control is visible without scrolling, whether the
  right thing is focused). Nothing in this document claims a human has
  visually reviewed the window during this acceptance pass; where that
  distinction matters, it is called out explicitly below.

1. Launch as above.
2. Connect only the devices the steps you'll use actually need (device
   panels on the left, each with its own Connect button). For the
   smallest possible representative run — one flush, one acquisition, no
   temperature control — that's Pump, Valve, Camera, AD2; leave TEC
   disconnected and the Temperature group's checkbox unticked (it's
   optional and defaults off, so leaving it off doesn't require touching
   any temperature field at all).
3. **Click Refill on the Pump panel (the unit you'll flush from) before
   queuing.** The simulated pump (and a real one after a restart, per
   `known_open_items.md`) starts at 0 mL fill level; queuing a series
   with any flush volume fails immediately with "Pump unit N needs X mL
   total flush volume but currently has 0 mL" otherwise — this is the
   flush-capacity guard working correctly, not a bug, but it does mean
   Refill is a required step for this shortest path, not an optional one.
4. In the Simple Series panel, the only field that must be filled by hand
   is the series descriptor (`self.description`) — queuing without one
   raises `"Enter a series descriptor before preflight"`. **Every other
   field's raw widget default is untested by the acceptance pass above**
   (which used the specific short values listed in the correction note
   above, not those defaults); use small, deliberately-chosen values for
   a first run rather than assuming the out-of-the-box defaults are a
   sane starting point.
5. **Click "Preflight camera settings" before Start.** Skipping it doesn't
   block the run, but Start's own camera-preflight gate will instead pop
   a confirmation dialog ("Camera preflight has not passed for N queued
   series... Continue with standard Start validation?") the first time
   through `MainWindow` — clicking Preflight first avoids that surprise
   and is what a normal operator session would do anyway.
6. "Queue series", then "Start queued batch". Status/phase updates live in
   the panel and in the Status tab's dashboard; `stop_after_current`
   ("Stop after current")/abort/panic are available once running, and
   each reaches the manager through the same button a human would click
   — confirmed by a programmatic click reaching the real signal/slot
   path, per the distinction above; not confirmed by anyone looking at
   the window while it ran.
7. Output lands under the chosen experiment base folder, one
   `experiment_batch_NNNN/` per queued series, with
   `metadata/status.json` (live progress + final outcome, confirmed
   readable from disk mid-run, not only after completion),
   `metadata/manifest.json` (the plan — **corrected**: this lives inside
   `metadata/`, not loose in the batch folder root as a prior version of
   this step said), and one TIFF (or stacked TIFF) + `experiment.json`
   per completed repeat.

**Where common changes go** (verified against current code, not
estimated — full detail with file/function names in `decision_log.md`'s
2026-10-15 "day-to-day modification cost" entry):
- **Temperature strategy** (tolerance/settle/hold, which single channel is
  addressed): `application/simple_series.py` + `ui/simple_series_panel.py`'s
  Temperature group. The panel always drives exactly one TEC channel per
  point — see the table row below before assuming "locked"/"unlocked"
  terminology applies here.
- **Parameter sweeps** (new scan axis): `application/experiments.py`'s
  `_values()`/`walk()`; one coupling point — the folder-naming `labels`
  dict needs a matching entry for a new named parameter.
- **Acquisition timing**: three intentionally separate layers —
  `experiments.py`'s `_validate_experiment()` (schema), `experiment_runner.py`'s
  `_after_camera_timing()` (live-SDK sanity), `_configure_all_before_fluidics()`
  (applied-value sanity). Not redundant; don't collapse them.
- **A new experiment-step kind**: `experiments.py`'s `ACTION_RESOURCES`/
  `_action()` (schema) + `experiment_runner.py`'s `_run_action()`
  (execution) — a deliberate validation/execution split.
- **A new field to save/restore with the settings profile**: add it to
  `SimpleSeriesSettings` (`application/simple_series.py`), to the
  matching widget list in `SimpleSeriesPanel._settings()`/
  `_apply_settings()`, and — only if it's a `NumericRange` field — to
  `_NUMERIC_RANGE_FIELDS` in the same module. `simple_series_settings_to_profile()`/
  `_from_profile()` need no change for an ordinary scalar/`NumericRange`
  field; they already walk every dataclass field generically. A combo
  selection that's only populated once a device connects (like
  `flush_unit_index`/`tec_channel`) needs the pending-value pattern in
  `_apply_flush_unit_index()`/`_devices()` if it should survive a
  load-before-connect, not just a direct `setCurrentIndex()` call.
- **The pre-run preview's content**: `SimpleSeriesPanel._run_preview_text()`.
  Reads from the already-compiled `expansion.experiments` for anything
  that varies per experiment (scan parameters, repeats) and from the
  panel's own scalar widgets for anything the compiled plan has no
  reason to carry (temperature-wait strategy, output location) — never
  re-derive a scan range from the `NumericRange` widgets directly, since
  that duplicates `compile_simple_series()`'s own logic and can drift
  from what actually got compiled.

| Module | Status | Note |
|---|---|---|
| Pump driver safety logic (fault-clear, position-sensing gate) | done | Carried from junjiebranch's `qmix_backend.py` into `drivers/pump/cetoni.py`, verified near-identical |
| Pump capacity: batch-budget check | done | `experiment_runner.py:492 _check_capacity`, distinct purpose, correct as-is |
| Pump capacity: fresh-read-at-flush plausibility | done | `application/workflows.py` `FlushWorkflow._implausible_reading()`/`_unit_capacity_ml()`, called from `LEVEL_READ`; distrusts the raw reading (non-finite, or exceeds `PumpReadback.units[unit_index].max_volume_ml`), distinct from `PumpWorker.set_fill_level()`'s pre-existing target-range validation. 4 new tests in `tests/test_workflows.py`, full suite 143/143 passing |
| TEC driver (connect/setpoint/Static-OFF) | done | `drivers/tec/controller.py`, equivalent to junjiebranch's `tec.py` |
| TEC multi-point scan, single channel (operator picks the channel) | done — normal UI usable | `compile_simple_series()` always emits `"channels": [settings.tec_channel]` — exactly one channel, chosen by the panel's single `tec_channel` combo. Reachable through the real `SimpleSeriesPanel` (`temperature_control` + `temperature_wait_for_stability` checkboxes + tolerance/min-settle/max-wait spinboxes). Verified end-to-end through the actual panel widgets in `tests/test_simple_series.py::test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order` plus the three failure-injection tests added this round. **Terminology note**: this is not "locked" in junjiebranch's sense (ch2 mirroring ch1's value automatically) — there is no mirroring here, only a single addressed channel. Avoid the "locked" label for this panel. |
| TEC multi-point scan, both channels from one definition (same or independent per-point targets) | definition-file only, **not UI-usable** | **Actual use case**: an experiment where channel 1 and channel 2 must follow two *different* temperature sequences in lockstep (e.g. a controlled differential between two sample locations), or where both channels should simply move together. The engine supports both via `experiments.py`'s dict-valued sweep parameter or a plain scalar target with `channels: [1, 2]` (confirmed in `tests/test_experiments.py::test_temperature_point_series_supports_independent_per_channel_targets`), but `ui/simple_series_panel.py` exposes only **one** `tec_channel` selector — there is no UI path to author a per-point pair of ch1/ch2 targets, matching or different. An operator can only reach this by hand-authoring a JSON definition and loading/editing it outside the panel. **Implementation scope if pursued**: a second channel selector plus a per-point-pair input widget in the Temperature group, and a compiler path that emits the dict-valued (or multi-channel) sweep parameter instead of the single-channel one — not built this round, flagged per explicit instruction rather than letting the engine-level test imply UI-readiness. |
| junjiebranch's temperature-**point**-level lifecycle counters (`SeriesLifecycleManifest.tec_point_started`/`tec_point_completed`) | not yet integrated | **Actual use case**: answering "how many of the N temperature points did this series reach" independently of "how many individual experiments/repeats completed" — useful when repeats-per-point varies or when the point-level progress matters more than the repeat-level detail. ola/integration's `SeriesStorage` counts only `experiments_started`/`_completed`/`_failed` (per-experiment/per-repeat granularity); there is no separate point-level counter. **Implementation scope if pursued**: a `temperature_points_started`/`_completed` pair on `SeriesStorage`, incremented from the `tec_set`/next-point-boundary logic in `experiment_runner.py` the same way the per-experiment counters are — not built this round, distinct from the general lifecycle-manifest work above (which does not include it). |
| TEC Prepare-tab readback display (requested vs. controller) | done | Both values already shown separately; fixed `None` rendering (was literal `"None"`, now house "—" convention) plus a clarifying tooltip |
| Experiment tab (Simple Series) settings save/load | done | Extends the existing per-device settings profile (`main_window.py`'s `profile_document()`/`save_profile()`/`load_profile()`) with a sibling `"experiment"` key covering every `SimpleSeriesSettings` field. Load is input-only (no device command, no queue, no start); old files without the key still load; save works with no pump connected. Two real flush-unit-selection defects found and fixed after this landed — see the row below for the current, authoritative state; this row's own original defect notes are superseded, not repeated here. |
| Experiment tab: flush-unit selection (load-before-connect, and a unit set that never matches) | done — two real defects found and fixed | The saved unit is remembered (`_pending_flush_unit_index`) until a real match appears or the operator explicitly picks something else; no match ever means "nothing selected" (`pump_unit.setCurrentIndex(-1)` under `blockSignals`, not Qt's own first-item default), with an explicit notice naming the unavailable unit. Confirmed by reverting each fix and seeing the corresponding test fail. 3 tests in `tests/test_device_ui.py` (load-before-connect; saved unit never appears; operator reselects). |
| Experiment tab: pre-run preview | done | `SimpleSeriesPanel._run_preview_text()`, read from the already-compiled plan's own values (never re-derived), plus the temperature-wait strategy and output location, which the plan itself has no reason to carry. 1 test. |
| Real defect: a post-acquisition flush failure discarded already-saved images, including a race with the save's own callback | done — fixed, twice | First fix: `_experiment_frames_saved` flag gates `_finish_failure_when_safe()`'s discard. Codex's independent review then found a residual race: the readiness gate checked per-future `.done()`, not whether `self._file_futures` was genuinely empty — a save Future can finish on its background thread before its own poll() callback (the only code that sets the flag and empties that set) has run, and a failure landing in that exact gap still read the stale `False`. Fixed by checking set emptiness instead. 2 tests, one per ordering — the save callback already processed, and the deliberately-constructed race where it hasn't. Both reverts reproduce the corresponding deletion. |
| Real defect: `stop_after_current`/panic/abort could leave the temperature log open or disk/memory disagreeing about how a series ended | done — fixed, twice | First fix: shared `_close_temperature_recorder()` for `stop_after_current` and normal completion. Codex's independent review then found a residual race: a stale, already-scheduled completion callback (from a recorder-drain wait that started before a panic/abort/failure landed) had no way to know the batch had since been finalized elsewhere, and unconditionally wrote "completed"/"stopped_after_current" over it. Fixed with a guard at the top of both callbacks: bail out if `self._failed`/`self._abort_requested` is already true. 2 tests — recorder closes on a normal stop; a deliberately-constructed panic-during-drain race confirms disk and memory end up agreeing. Both reverts reproduce the corresponding defect. |
| Real gap: camera/AD2 timing was checked against the requested configuration, not the achieved/applied one | done — fixed, twice | First fix: `_configure_all_before_fluidics()` re-reads camera timing (`CAMERA_TIMING_READ`) after the real AD2 configuration returns, checking the achieved frame rate instead of the requested one. Codex's independent review then found the exposure side of the same check still used the requested `camera["exposure_ms"]`, not the actually-applied exposure (DCAM quantization can make these differ — confirmed once on real hardware). Fixed by also reusing `CAMERA_SETTINGS_READ`/`read_exposure_time()`; both requested and applied values are kept in any rejection message. 2 discriminating tests (AD2 divergence; exposure quantization, isolated from each other). Both reverts reproduce completing a series that should have been rejected. |
| Real defect: a malformed settings-profile field could partially apply before failing (wrong type, then out-of-range) | done — fixed, twice | First fix: every field's *type* is checked up front in `simple_series_settings_from_profile()`, before `SimpleSeriesSettings` is constructed. Codex's independent review then found a correctly-typed but out-of-range value (e.g. `frame_count` far beyond its QSpinBox's 1..100,000) still wasn't caught — `QSpinBox.setValue()` silently *clamps* a merely-too-large value (confirmed directly) rather than rejecting it, and raises a raw `OverflowError` for one beyond the C `int` range. Fixed with `SimpleSeriesPanel._validate_settings_ranges()`, checking every field against its own live widget's range, called from `load_profile()` before anything is applied. 3 tests total (the original type reproduction; the new range reproduction; a valid profile still round-trips). All reverts reproduce the corresponding half-applied or silently-accepted result. |
| Test-suite stability: `test_device_ui.py` cleanup exception-safety | done — **overstated claim corrected** | A prior round's record claimed these 5 tests "never called `shutdown()`" and leaked threads on every run. That is wrong: all 5 already called `window.close()` at their end, and `MainWindow.closeEvent()` already calls `self.controller.shutdown()` — so on any normal, passing run, cleanup already happened. The actual, narrower gap: that cleanup ran unconditionally at the tail of the test, not in a `finally`, so an assertion failure partway through *would* skip it and leave that one controller's threads running. Fixed with `try/finally` wrapping, which is a real but modest exception-safety improvement — not a fix for threads leaking on the happy path, which was never actually happening. **The native "Fatal Python error: Aborted" Codex hit remains unexplained.** Three full-suite runs by Claude and one by Codex all passed cleanly after this change, which is stability *support* evidence, not a demonstrated root cause — this round deliberately does not claim the crash's cause is known or that it is proven gone. |
| Valve driver + automated flush confirmation | done | `FlushWorkflow` already confirms `ValveReadback.ready`+`confirmed_position` with timeout+recovery; no gap |
| Valve `VALVE_WAIT_READY` return semantics (manual path only) | done (verified, no gap) | Command-level ok/fail framing conflates `ready=False` with success, but the operator-visible readback label already shows the true ready state/status note regardless — no silent failure reaches the operator |
| AD2 driver incl. FM/sweep | done | `drivers/ad2/analog_discovery.py` carries fm_mod/sweep support |
| AD2 JP4/series-source documentation | done | Organized into `docs/integration/hardware_notes.md` — the JP4/JP5 direct-vs-49.9-ohm-series-source distinction, SKU/schematic references, and what remains physically unverified. Documentation-only, no code change. |
| Camera driver | done (structurally) | Real `image_sequence` acquisition not yet exercised on this branch's real-hardware log — flagged for a future bench check, not a code gap |
| Z-stage driver + UI | done | `ui/z_stack_panel.py` is a superset of junjiebranch's Z-Scan tab fields |
| Z-stage stepping algorithm parity | done | Position-confirmation is more rigorous in ola's `z_stack.py` (real tolerance+timeout poll vs junjiebranch's fixed-delay-only). Point parameterization (step-size vs point-count) differs by design, not a gap. **Decided this round**: the closed-loop/motion two-tier operator-confirmation gate junjiebranch had will **not** be added — current single-gate design is accepted as a documented strategy difference, not a gap. See `known_open_items.md`. |
| Experiment-sequencing engine (cartesian expansion, preflight validation) | done | `experiments.py`/`experiment_runner.py`; `run_s <= 0` validated at `experiments.py:242-243`, equivalent to junjiebranch's Channel-0 preflight fix, independently arrived at |
| Series lifecycle manifest — **A: real-time persistence** | done — a real gap was found and fixed this round, corrected from a prior "already done" claim | `record_experiment_started/completed/failed()` previously only updated in-memory counters; `status.json` was not rewritten between major transitions, so a crash between experiments left stale counts on disk. Fixed: each now persists immediately via `status("running", {})`. Verified by reading `status.json` from disk **while the series is still running**, not only at the end: `test_lifecycle_counts_are_persisted_before_the_series_ends`. Never auto-marks an abandoned record as successful (no reconciliation logic exists at all — see row below). Also: `test_series_lifecycle_counts_and_outcome_on_completion`, `test_series_lifecycle_marks_in_progress_experiment_failed_and_finalizes_once`, plus three failure-injection tests confirming the record stays consistent when a series fails mid-way. |
| Series lifecycle manifest — **B: crash-state interpretation** | done (manual procedure, not code) | `status.json` is write-only in this codebase (confirmed: `grep -rl "status.json" src/` matches only `experiment_storage.py`); nothing reads it back. A step-by-step manual-inspection procedure (how to tell a genuinely-running series from an abandoned one, and what the counters mean when abandoned) is now written in `known_open_items.md` — per explicit instruction, this is the appropriate scope for this round (documentation, not a UI feature). |
| Series lifecycle manifest — **C: automatic resume/reconciliation** | explicitly out of scope this round | Not designed, not stubbed. junjiebranch did not have this either (`SeriesLifecycleManifest` is also just a persisted record, not an auto-resume mechanism) — this is genuinely new ground, not a parity gap. See `known_open_items.md` for the option list if pursued later. |
| Stop/abort/panic semantics **while a series is actively running** | done | Correction: an earlier round found zero tests for `stop_after_current()`/`abort()`/`panic_abort()` and over-generalized that into "panic is zero-coverage" — missed that `test_panic_stops_connected_outputs_without_moving_valve` already exercises `controller.panic_stop()`→`experiments.panic_abort()`, just with no series running. Added the specific in-series case for all three: `test_stop_after_current_finishes_active_experiment_then_stops_before_next_point`, `test_abort_during_a_running_series_stops_without_starting_the_next_experiment`, `test_panic_stop_during_a_running_series_ends_the_batch_without_moving_the_valve`. Each checks the next experiment/point does not start and `status.json` stays internally consistent (`experiments_completed <= experiments_started`), without re-asserting the already-covered single-device SAFE_STOP facts. |
| Parallel save/flush barrier — **direct** evidence | done | Correction: the prior test used `AD2_DIGITAL_OUTPUT_STOP` as a stand-in for "both branches done," which is wrong — that event precedes the per-experiment flush in the same branch, and says nothing about the independent save branch. Replaced with two tests that each deliberately slow one branch (a monkeypatched `save_frames` delay; a real nonzero `wait_after_s` on the flush) and measure that the wall-clock gap to the next experiment is at least that delay: `test_parallel_barrier_blocks_next_experiment_until_save_completes`, `test_parallel_barrier_blocks_next_experiment_until_flush_completes`. |
| Whole-series flush-capacity sum across placements | done | Three scenarios confirm `_check_capacity`'s rejection message cites the correct total regardless of where flush nodes sit in the tree: `test_flush_budget_sums_a_series_level_only_flush`, `test_flush_budget_sums_a_per_repeat_only_flush_across_two_repeats`, `test_flush_budget_sums_a_mixed_series_and_per_repeat_placement`. |
| Exception propagation from command-argument construction | done, kept as defensive code | Found while building the stability-wait failure test: `_run_action()` let an exception raised while *building* a command's arguments (e.g. `TecWaitStableArgs.__post_init__`) escape uncaught into the Qt callback chain — `_submit()`'s try/except only covers the submit call, not the construction one line above it. Fixed generally (wraps the whole dispatch, not just the TEC case). The specific scenario that motivated it (`max_wait_s` below the poll interval) was later fixed a different way (the poll interval now adapts — see below), so there is currently no concrete scenario reaching this path through the declarative pipeline; kept as general protection, not exercised by a dedicated test. |
| `temperature_max_wait_s` compile-time floor — reviewed again, removed | **removed** (corrected from "kept" in the prior round) | On further review the floor was exactly "a software default dressed as a device requirement" — the 1.0s came from `TecWaitStableArgs.poll_interval_s`, which has no physical meaning and isn't even user-settable. Removed entirely; the exception-propagation fix already reports an inconsistent value gracefully at run time, so no replacement restriction was added. Test: `test_temperature_max_wait_below_one_second_compiles_without_a_software_floor`. |
| Fault-reason surfacing in UI | done | `event_formatting.py:42` already includes `event.message` on every failure |
| Chronology-ordered Prepare checklist (UX principle) | deferred | `simple_series_panel.py` identified as the analogous panel; its current group order was reviewed but not changed — no real-operator evidence on this lab's actual chronology to act on, per authorization's "mark unknown, don't assume" instruction |
| Data format (TDMS vs. TIFF+JSON) | **decided this round: keep TIFF+JSON as-is** | Downstream-compatibility check performed: grepped this repo's own `docs/`/`README.md` for any documented downstream consumer requirement — none found (confirmed: no in-repo code or doc depends on TDMS). The one *plausible* external consumer named in earlier rounds, the separate LabVIEW repo's `analysis.vi` (`C:\git\thermacoustics`), was **not opened this round** (out of scope, not requested) — its actual format expectations remain genuinely unverified, not confirmed-compatible. This is a real limitation of the verification, not a finding that compatibility is fine: if that LabVIEW analysis path is still in active use, someone with access to confirm its actual input format should be consulted before treating this as fully closed. |
| Analysis | deferred | Not implemented in Python on either branch; LabVIEW-only, separate repo (`C:\git\thermacoustics`), out of this integration's scope |
| Test environment (external `--basetemp`) | **stale status corrected**: this is an established manual habit, not an in-progress task or a pytest config setting | Windows denies pytest's default tmp-directory ACLs for this project on this machine; every full-suite run this round (and every prior round) has passed `--basetemp=<path under the repo>` on the command line to work around it — confirmed not configured anywhere in `pyproject.toml`/a `conftest.py`, so a fresh clone or CI run needs the same flag, not inherited automatically. No `known_flaky`-style pytest marker exists in this codebase (withdrawn as unjustified in an earlier round — flakiness here was root-caused per-case, not papered over with a marker). The "Phase 0 test report" this row used to point to was an ephemeral artifact of an early conversation turn, not a committed file; removed that dangling reference. |
