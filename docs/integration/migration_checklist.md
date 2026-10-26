# Feature migration checklist

Current operating reference for behaviour baseline `aa5f3d1`. Overall acceptance is in
`acceptance_table.md`; current exceptions/policies are in `known_open_items.md`. Existing hardware
evidence is reused within its scope. This guide does not require a new full hardware validation.

Status values: `done` (implemented), `planned` (specifically authorized but not yet
implemented), `open` (a concrete question), `deferred` (not scheduled). A historical
phase or a deferred item is not a standing instruction to develop it.

## Quick reference: running an experiment, and where to change things

**Launching** (no install needed from this worktree):
```
cd src
python -m thermo_acoustic.main --mode simulation
```
`--mode simulation` is the default; `--mode real` drives connected hardware and needs the
usual real-hardware precautions (not covered by this guide).

**Recipes: what each source is, and how it maps to the current controls.** Nothing here is applied
automatically (no preset manager); historical device addresses and paths are not defaults.

| Source | What it is | Values | Current controls | Gaps |
|---|---|---|---|---|
| Automated test (`test_full_main_window_operator_flow_…`) | short test values | repeats 2, frames 2, 10 fps, frequency/amplitude/exposure `1`/`1`/`1`, ROI 16×16, flush 0.01 mL @ 200 µL/min, sweep and temperature off | all expressible | not a laboratory recipe |
| junjie Sessions 31/33 | real run on real hardware (junjie's GUI, camera on *Internal* trigger) | 4 repeats, frames 5, 5 fps, 15 ms, W1 1 kHz / 0.1 V / 2.0 s; flush 0.05 mL @ 200 µL/min (real pump move 9.8 s) | all expressible | ROI not stated in the log; the integration triggers the camera *externally* from DIO0, which that run did not exercise |
| junjie Session 48 | real Z scan | 200→210 µm, step 2 (6 points), 20 ms, fixed 75 ms settle | Z stack: start 200, stop 210, points 6, exposure 20 | the integration confirms position instead of a fixed delay; tolerance/timeout were not part of the record |
| junjie `experiment_presets.py` | values read from LabVIEW screenshots, **not** run records | ROI 2304×740 at (0, 792), 40 ms, 20 fps, 1000 frames; W1 1.975 MHz, 2 V, 60 s; "CH2" 1 kHz, 1 V, 60 s; flush 0.01 mL @ 1000 µL/min, wait 2 s, two flushes; syringe BD 5 mL | ROI, exposure, fps, frames, W1 frequency/amplitude/run, flush volume/flow/wait fit the controls (amplitude limit 5 V) | (a) laser/W2 is a PC-triggered DC window checked as `run × W2 minimum frequency < 0.5`, so a 60 s window is accepted only if the AD2 reports a minimum below ~0.008 Hz, and a 1 kHz sine "CH2" has no field; (b) the memory preflight wants `frame_bytes × (3 × frames + 3)` ≈ 10 GB free RAM for 1000 frames at that ROI; (c) the screenshot lists external polarity "Negative", the series fixes Positive; why two flushes is unstated. Treat as a reference to confirm, not a verified recipe |
| Current widget defaults | defaults | frames 10, 10 fps, 1 ms, ROI 512×512 at (0, 0), 1 MHz, 1 V, sound run 1 s, laser run 0.1 s, flush 0.1 mL @ 500 µL/min, wait after flush 0, one temperature of 25 °C, hold 30 s, max wait 300 s | – | untested as a starting point |

**Reading the saved output.**
- *Which experiment:* `metadata/manifest.json` lists every planned experiment (`experiment_id`, `relative_path`, `parameters`, `repeat_index`); each `experiment.json` repeats them.
- *Mode and software:* `manifest.json` → `run.mode` and `run.software` (`git_commit`, `git_dirty`, `source`).
- *Outcome:* series — `status.json` (`state`, started/completed/failed counts, `error`). Experiment — a folder with `acquisition_status: "complete"` exists only for a complete acquisition; success has an `experiment_completed` event; a later failure has `post_acquisition.outcome: "failed"` plus `error` and an `experiment_preserved_after_later_failure` event; no folder means not acquired or an incomplete acquisition discarded (compare the counts and the `series_failed` event's `experiment_id`).
- *Timestamps:* `frames[].camera_sdk_timestamp` (camera clock) and `host_received_utc`; the clock domains are stated in the file. `physical_dio0_edges_verified: false` is written into every file: frame spacing is not proven by the software.
- *Actual settings:* `requested_settings`, `applied_settings`, `camera_settings` (DCAM property dump read at collect), `device_readbacks` (taken when the save started, right after the capture — not the end-of-batch state), and `definition.json` for the temperature tolerance/settle/hold.
- *TEC evidence:* requested targets are in `definition.json`; available channel status is in the experiment snapshot. The real client does not re-read target parameter 3000. Do not interpret a simulated target readback as a real applied-target measurement.
- *Standalone Z stack:* its `metadata.json` has no failure reason or run identity; this differs from the series manifest.

**Short test recipe for one simulated experiment** (`SimpleSeriesPanel`, tab "Experiment"; use the
first table row's values).

1. Launch. Connect only the devices the run uses (Pump, Valve, Camera, AD2 for the shortest run;
   leave TEC off and Temperature unticked).
2. **Pump fill level.** The *simulated* pump starts at 0 mL, so click Refill on the flush unit
   first, otherwise queuing fails with "Pump unit N needs X mL total flush volume but currently has
   0 mL". A *real* pump reports its fill level from the SDK; the same guard compares the planned
   flush volume with that read-back. Do not refill by reflex after a restart — prepare the syringe
   according to what it actually holds and what the experiment needs.
3. Enter a series descriptor (required). Click "Preflight camera settings" before Start, otherwise
   Start asks for confirmation.
4. "Queue series", then "Start queued batch". Stop after current / Abort / Panic are available while
   running.
5. Output: one `experiment_batch_NNNN/` per queued series with `metadata/` (`definition.json`,
   `manifest.json`, `status.json`, `events.jsonl`) and one TIFF set + `experiment.json` per
   completed experiment. `manifest.json` has a `run` block: `mode` (`simulation`/`real`) and
   `software` (`git_commit`, `git_dirty` for tracked files, `source`); a value that cannot be read
   is `"unknown"`. An incomplete acquisition is discarded; completed experiments are kept.

**What "done" means.** A command result means the driver accepted the command, not that the
physical action finished unless the step says it waits for a read-back:
- Pump Refill/Empty/flow: returns when the SDK accepted the start; progress comes from polling, and
  the flush workflow waits until the pump reads idle.
- Valve: the flush workflow confirms the position by read-back.
- TEC: the stability wait uses the read-back temperature; a set-point command alone is not stability.
- Z stage: manual Move and the `stage_move` experiment step return when the controller accepted the
  (soft-limited) target; `ZStageReadback.position_um` is the last *measured* position and
  `commanded_position_um` the last target sent. `stage_move` does **not** wait or read back, and is
  recorded as `sent_um` with `position_confirmed: false`. The independent Z stack does read the
  position and requires it within tolerance before each capture.
- Camera/AD2: arming and triggering are checked by the sequence logic (frame count, achieved AD2
  rate, applied exposure), not by the acceptance of the individual command.

**Closing the window.** A running batch is stopped through Abort (reason "Application window closed
during the run") and its save/flush drain, then the window closes by itself. Each device is then
stopped in its own thread in this order: cancel an unfinished operation → SAFE_STOP → disconnect.
If a device has not finished, or reported an error, the window stays open and says so; closing again
retries. Panic cannot interrupt a blocked SDK call, and after shutdown has started it only reports.

**How to read verification labels.** "Simulated" means exercised against simulated or fake devices.
It does not mean nothing is known about the hardware: the shared driver layer (Qmix pump, DCAM
camera, piezo stage, AD2, TEC read/OFF) has real-hardware records from junjiebranch, listed per item
in `acceptance_table.md`. What has no real run is the integration layer itself: the experiment
engine's AD2→camera trigger chain, the flush workflow, the Z stack on this branch, and the window
close/abort paths.

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
- **Acquisition timing**: three layers with different inputs —
  `experiments.py`'s `_validate_experiment()` (schema), `experiment_runner.py`'s
  `_after_camera_timing()` (static checks that do not depend on the camera's current
  configuration: exposure vs interval, laser window), and `_configure_all_before_fluidics()`
  (camera limits and exposure judged on the read-back after each configuration was applied,
  with the AD2's achieved rate, for every unique configuration, before any flush).
- **A new experiment-step kind**: `experiments.py`'s `ACTION_RESOURCES`/
  `_action()` (schema) + `experiment_runner.py`'s `_run_action()`
  (execution) — a deliberate validation/execution split.
- **A new field to save/restore with the settings profile**: add it to
  `SimpleSeriesSettings`, `_settings()`/`_apply_settings()` and the applicable
  field/type validation list in `simple_series.py` (or `_NUMERIC_RANGE_FIELDS`
  for a range). Check `_validate_settings_ranges()` against its widget limits.
  Saving uses `asdict`; loading is not a fully generic validator and must be
  kept in sync. A device-populated combo also needs a pending-value policy
  when loading before connection; reuse the pump-selection pattern where
  appropriate rather than silently choosing the first item.
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
| junjiebranch's temperature-**point**-level lifecycle counters (`SeriesLifecycleManifest.tec_point_started`/`tec_point_completed`) | optional, not scheduled | **Actual use case**: answering "how many of the N temperature points did this series reach" independently of "how many individual experiments/repeats completed" — useful when repeats-per-point varies or when the point-level progress matters more than the repeat-level detail. ola/integration's `SeriesStorage` counts only `experiments_started`/`_completed`/`_failed` (per-experiment/per-repeat granularity); there is no separate point-level counter. **Implementation scope if pursued**: a `temperature_points_started`/`_completed` pair on `SeriesStorage`, incremented from the `tec_set`/next-point-boundary logic in `experiment_runner.py` the same way the per-experiment counters are — not built this round, distinct from the general lifecycle-manifest work above (which does not include it). |
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
| Series lifecycle manifest — **C: automatic resume/reconciliation** | explicitly out of scope this round | Not designed, not stubbed. junjiebranch did not have this either (`SeriesLifecycleManifest` is also just a persisted record, not an auto-resume mechanism) — this is genuinely new ground, not a parity gap. No resume work is scheduled; see the current manual inspection procedure in `known_open_items.md`. |
| Stop/abort/panic semantics **while a series is actively running** | done | Correction: an earlier round found zero tests for `stop_after_current()`/`abort()`/`panic_abort()` and over-generalized that into "panic is zero-coverage" — missed that `test_panic_stops_connected_outputs_without_moving_valve` already exercises `controller.panic_stop()`→`experiments.panic_abort()`, just with no series running. Added the specific in-series case for all three: `test_stop_after_current_finishes_active_experiment_then_stops_before_next_point`, `test_abort_during_a_running_series_stops_without_starting_the_next_experiment`, `test_panic_stop_during_a_running_series_ends_the_batch_without_moving_the_valve`. Each checks the next experiment/point does not start and `status.json` stays internally consistent (`experiments_completed <= experiments_started`), without re-asserting the already-covered single-device SAFE_STOP facts. |
| Parallel save/flush barrier — **direct** evidence | done | Correction: the prior test used `AD2_DIGITAL_OUTPUT_STOP` as a stand-in for "both branches done," which is wrong — that event precedes the per-experiment flush in the same branch, and says nothing about the independent save branch. Replaced with two tests that each deliberately slow one branch (a monkeypatched `save_frames` delay; a real nonzero `wait_after_s` on the flush) and measure that the wall-clock gap to the next experiment is at least that delay: `test_parallel_barrier_blocks_next_experiment_until_save_completes`, `test_parallel_barrier_blocks_next_experiment_until_flush_completes`. |
| Whole-series flush-capacity sum across placements | done | Three scenarios confirm `_check_capacity`'s rejection message cites the correct total regardless of where flush nodes sit in the tree: `test_flush_budget_sums_a_series_level_only_flush`, `test_flush_budget_sums_a_per_repeat_only_flush_across_two_repeats`, `test_flush_budget_sums_a_mixed_series_and_per_repeat_placement`. |
| Exception propagation from command-argument construction | done, kept as defensive code | Found while building the stability-wait failure test: `_run_action()` let an exception raised while *building* a command's arguments (e.g. `TecWaitStableArgs.__post_init__`) escape uncaught into the Qt callback chain — `_submit()`'s try/except only covers the submit call, not the construction one line above it. Fixed generally (wraps the whole dispatch, not just the TEC case). The specific scenario that motivated it (`max_wait_s` below the poll interval) was later fixed a different way (the poll interval now adapts — see below), so there is currently no concrete scenario reaching this path through the declarative pipeline; kept as general protection, not exercised by a dedicated test. |
| `temperature_max_wait_s` compile-time floor — reviewed again, removed | **removed** (corrected from "kept" in the prior round) | The 1.0 s floor was a polling default, not a device requirement. The runner now uses `poll_interval_s = min(1.0, max_wait_s)`, so a positive sub-second timeout is executable rather than merely failing gracefully. Compile and execution tests cover it; no physical thermal response is inferred. |
| Fault-reason surfacing in UI | done | `event_formatting.py:42` already includes `event.message` on every failure |
| Chronology-ordered Prepare checklist (UX principle) | deferred | `simple_series_panel.py` identified as the analogous panel; its current group order was reviewed but not changed — no real-operator evidence on this lab's actual chronology to act on, per authorization's "mark unknown, don't assume" instruction |
| Data format (TDMS vs. TIFF+JSON) | **decided this round: keep TIFF+JSON as-is** | Downstream-compatibility check performed: grepped this repo's own `docs/`/`README.md` for any documented downstream consumer requirement — none found (confirmed: no in-repo code or doc depends on TDMS). The one *plausible* external consumer named in earlier rounds, the separate LabVIEW repo's `analysis.vi` (`C:\git\thermacoustics`), was **not opened this round** (out of scope, not requested) — its actual format expectations remain genuinely unverified, not confirmed-compatible. This is a real limitation of the verification, not a finding that compatibility is fine: if that LabVIEW analysis path is still in active use, someone with access to confirm its actual input format should be consulted before treating this as fully closed. |
| Analysis | deferred | Not implemented in Python on either branch; LabVIEW-only, separate repo (`C:\git\thermacoustics`), out of this integration's scope |
| Test environment (external `--basetemp`) | **stale status corrected**: this is an established manual habit, not an in-progress task or a pytest config setting | Windows denies pytest's default tmp-directory ACLs for this project on this machine; every full-suite run this round (and every prior round) has passed `--basetemp=<path under the repo>` on the command line to work around it — confirmed not configured anywhere in `pyproject.toml`/a `conftest.py`, so a fresh clone or CI run needs the same flag, not inherited automatically. No `known_flaky`-style pytest marker exists in this codebase (withdrawn as unjustified in an earlier round — flakiness here was root-caused per-case, not papered over with a marker). The "Phase 0 test report" this row used to point to was an ephemeral artifact of an early conversation turn, not a committed file; removed that dangling reference. |
