# End-to-end experiment flow — code-derived baseline (ola/integration)

This traces the actual call chain in `application/experiment_runner.py`
(`ExperimentManager`), `application/workflows.py` (`FlushWorkflow`),
`application/controller.py` (`ApplicationController`), and
`application/simple_series.py` (the real UI compiler).

## Evidence legend — read every claim below against this

- **[CODE]** — read directly from source; not exercised by any test written
  or re-verified this round. This is a claim about what the code *says it
  does*, not proof it behaves that way at runtime.
- **[TESTED: name]** — a named test asserts this specific behavior at
  runtime, against simulated devices, with event/command-order checks (not
  only a final "completed" state). The test name is exact and can be run.
- **[SIM ONLY]** — tested, but only against simulated device backends
  (`drivers/*/simulated.py`), which may not reproduce a real device's
  timing, failure modes, or protocol quirks. This qualifies every
  **[TESTED]** tag in this document; it is not repeated on every line.
- **[UNVERIFIED ON REAL HARDWARE]** — no real-hardware log or bench record
  exists for this behavior, on this branch. Distinct from **[SIM ONLY]**:
  some things can't even be exercised by a simulated device meaningfully
  (e.g. physical DIO0 edge timing).

A claim with only **[CODE]** should be read as "this is what the code is
structured to do," not "this has been confirmed to happen."

## Stages, in actual code order

1. **UI parameter entry** (`ui/simple_series_panel.py` `_settings()`) →
   **definition compilation** (`simple_series.py` `compile_simple_series()`)
   → **structural validation** (`experiments.py` `validate_definition()`).
   **[TESTED: test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order]**
   drives the real panel widgets through this path.
2. **Queue** (`experiment_runner.py:110 queue()`): requires a non-empty
   description; all series in one batch must share one output root.
   **[CODE]** for the shared-output-root rule specifically; the
   description requirement and basic queueing are **[TESTED]** throughout
   the existing suite (e.g. `test_start_warns_for_missing_or_stale_count_preflight`).
3. **Optional, UI-triggered syringe preflight** (`preflight_syringe():224`).
   **[TESTED: test_batch_syringe_preflight_totals_and_queue_edits]**
   (pre-existing test).
4. **Start** (`start():315`): gate chain described in code. **[CODE]** for
   the full gate chain; individual gates are spot-tested elsewhere in the
   suite (e.g. `test_start_warns_for_missing_or_stale_count_preflight` for
   the camera-preflight gate) but not all exercised together in one test.
5. **Per-series preparation** (`_next_series():390`): `_require_devices()`
   walks the **entire** step tree once, upfront. **[CODE]** — read from
   source this round; not independently re-verified by a new test. (The
   existing suite's `test_temperature_log_open_failure_stops_before_fluidics`
   does confirm one specific sub-case: a `temperature_logging` TEC-connection
   failure stops the series before any fluidics action.)
6. **Pump re-sync** (`_refresh_pump_preflight():428`). **[CODE]**.
7. **Capacity check** (`_check_capacity():492`): pump capacity is the sum of
   every flush volume **anywhere in the whole step tree**, per unit index.
   **[CODE]** — I read the recursive `visit()` walk and it does sum flush
   nodes regardless of tree position, but **no test in this round or the
   existing suite places flush nodes at different tree depths (series-level
   vs. per-point vs. per-repeat) and asserts the computed total differs
   accordingly**. The "whole-series sum" claim is a structural reading of
   the code, not a runtime-verified claim across placements.
8. **Timing/laser-window validation for every experiment**
   (`_after_camera_timing():572`), with `self._laser_frequency_hz` read
   once and cached. **[CODE]**. The "validated for every experiment, not
   just the first" claim is a reading of the `for item in
   expansion.experiments:` loop; not independently tested this round.
9. **Series-level configuration validation**
   (`_configure_all_before_fluidics():627`): de-duplicates by unique
   (camera, ad2) pair. **[TESTED, indirectly]**: in
   `test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order`,
   all 4 experiments share one configuration, and `CAMERA_SEQUENCE_CONFIGURE`
   completes exactly 5 times (1 series-level validation + 4 per-experiment)
   — consistent with de-duplication, though the test does not vary
   configurations to directly prove two *different* configs each validate
   once.
10. **Optional real-hardware count preflight** (`_run_count_preflights():667`,
    REAL mode + `preflight` flag only). **[CODE]**, and **[TESTED
    elsewhere]**: the pre-existing `test_count_preflight_uses_fake_workers_and_discards_test_images`
    exercises this path (against simulated workers, `preflight=True`,
    `OperatingMode.REAL`) — not re-verified by this round's new work.
    `physical_dio0_edges_verified: False` is a string the code writes into
    its own event log; it is not a claim this document is making on the
    code's behalf — it is the code's own documented limitation.
11. **Begin** (`_begin_steps():751`). **[CODE]**.
12. **Node execution** (`_run_nodes():776`): `stop_after_current` is
    checked only at the experiment-completion boundary. **[TESTED:
    test_stop_after_current_finishes_active_experiment_then_stops_before_next_point]**
    — correction from an earlier round, which found zero tests calling
    `ExperimentManager.stop_after_current()`/`abort()`/`panic_abort()` at
    all (a real gap at the time) and then incorrectly generalized that into
    "panic is zero-coverage," missing that
    `tests/test_application_status.py::test_panic_stops_connected_outputs_without_moving_valve`
    already exercises `controller.panic_stop()` → `experiments.panic_abort()`
    indirectly — just not with a series actually running. This round adds
    the specific case that test cannot cover (stop/abort/panic **while an
    experiment series is active**) — see step 15.
13. **Leaf actions**, in the order `_validate_experiment()` enforces:
    `camera_configure` → `ad2_configure` → `camera_arm` → `ad2_arm` →
    `pc_trigger` → `await_frames`, then a `parallel` block of
    `[save_frames]` and `[wait_outputs, flush?]`.
    - Re-application of `camera_configure`/`ad2_configure` per experiment
      node, always: **[CODE]**.
    - `camera_arm` fully before `ad2_arm` (waveform start, then digital
      output start), both before `pc_trigger`:
      **[TESTED: test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order]**
      — asserts `CAMERA_SEQUENCE_ARM` completion precedes `AD2_WAVEFORM_START`
      completion precedes `AD2_DIGITAL_OUTPUT_START` completion precedes
      `AD2_SOFTWARE_TRIGGER` completion precedes `CAMERA_SEQUENCE_COLLECT`
      completion, in that order, by command-event index.
    - One shared hardware trigger (AD2's DIO0 drives the camera's external
      trigger input, not a second software signal): **[CODE]** — read from
      `_camera_args()`'s `CameraSequenceTriggerArgs(source=EXTERNAL, ...)`
      and `_waveform_args()`'s shared `Ad2TriggerSource.PC`. **[UNVERIFIED
      ON REAL HARDWARE]**: no bench record confirms the camera's physical
      external-trigger input actually responds to AD2's DIO0 edge on real
      hardware on this branch.
    - `await_frames` requires exact frame/timestamp count and every
      timestamp truthy: **[TESTED elsewhere]**
      (`test_missing_sdk_timestamp_fails_acquisition_without_saving_frames`,
      pre-existing). No cross-check against physical DIO0 edge count:
      **[CODE]**, and explicitly **[UNVERIFIED ON REAL HARDWARE]** — the
      code's own event log says so (`physical_dio0_edges_verified: False`).
    - `save_frames` is serialized through a single-worker
      `ThreadPoolExecutor`: **[CODE]**.
    - `wait_outputs` polls to a bounded deadline, then stops both AD2
      outputs, then (if present) flushes: **[CODE]**, with a related but
      not identical pre-existing test
      (`test_file_save_and_post_output_flush_overlap_without_blocking_preview`)
      confirming save completes before `experiment_completed` for a
      single-experiment series.
    - **The parallel block's two branches must both finish before the next
      top-level step runs**: **[TESTED, directly, this round]** —
      correction from an earlier round, which only checked that
      `AD2_DIGITAL_OUTPUT_STOP` (the end of `wait_outputs` alone) precedes
      the next experiment's reconfiguration. That is **not** evidence
      either branch, let alone both, had actually finished: the
      per-experiment flush runs *after* `wait_outputs` in the same branch
      (per `_validate_experiment()`'s own ordering rule), so
      `AD2_DIGITAL_OUTPUT_STOP` is emitted *before* that branch's own flush
      even starts, and says nothing about the independent `save_frames`
      branch at all. Replaced with two tests that directly control one
      branch's duration and measure the real wall-clock gap to the next
      experiment: `test_parallel_barrier_blocks_next_experiment_until_save_completes`
      (an artificially slow `save_frames`) and
      `test_parallel_barrier_blocks_next_experiment_until_flush_completes`
      (a real, nonzero `wait_after_s` on the flush, not a monkeypatch).
      Both assert the gap between the triggering experiment's
      `AD2_SOFTWARE_TRIGGER` and the next experiment's own
      `CAMERA_SEQUENCE_CONFIGURE` is at least the deliberately-introduced
      delay — if the barrier did not hold, that gap would be far shorter.
14. **Series completion** (`_complete_series():755`). **[CODE]** for the
    temperature-recorder drain-retry detail specifically; completion itself
    is **[TESTED]** throughout the suite.
15. **Stop/abort/recover — four code paths, now each tested specifically
    for the in-series case.** `stop_after_current()` (`:361`), `abort()`
    (`:367`), a normal command failure via `_fail()` (`:1081`,
    `stop_outputs=True`), and `controller.panic_stop()` →
    `panic_abort()` (`:383`, `stop_outputs=False`) are structurally
    distinct in source. Device-level facts for `abort`/`panic` (which
    devices get `SAFE_STOP`, that the valve is never moved by panic) were
    already covered with no series running
    (`test_panic_stops_connected_outputs_without_moving_valve`, pre-existing)
    — this round adds the series-level consequence that test cannot cover:
    **[TESTED: test_stop_after_current_finishes_active_experiment_then_stops_before_next_point]**
    (lets the active experiment finish, then stops before the next point);
    **[TESTED: test_abort_during_a_running_series_stops_without_starting_the_next_experiment]**
    (the second repeat never starts; final counts stay internally
    consistent); **[TESTED: test_panic_stop_during_a_running_series_ends_the_batch_without_moving_the_valve]**
    (same, for `controller.panic_stop()`, re-confirming no `VALVE_POSITION_SET`
    reaches the device even with a real series' own valve usage in play);
    **[TESTED: the three failure-injection tests]** for the ordinary
    command-failure path specifically.

## Direct answers to the specific questions raised

- **Does flush belong to the whole series, a temperature group, or a single
  repeat?** Placement in the JSON step tree determines *association*; the
  capacity check sums flush volumes via a full recursive tree walk
  regardless of placement.
  **[TESTED: test_flush_budget_sums_a_series_level_only_flush,
  test_flush_budget_sums_a_per_repeat_only_flush_across_two_repeats,
  test_flush_budget_sums_a_mixed_series_and_per_repeat_placement]** —
  three placements, each confirming the capacity-check rejection message
  cites the correct whole-series total for that specific placement.
- **When is temperature considered stable, when is it held, when is
  acquisition allowed?** `tec_wait_stable` → separate `wait` (hold) →
  `experiment` block, in that sibling order.
  **[TESTED: test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order]**
  now asserts both the completion order (`tec_wait_stable` before
  `camera_arm`) and that the hold's wall-clock duration actually elapsed
  (via command-event timestamps), not merely that the step was present in
  the compiled definition.
- **How do camera-armed and AD2-armed unify into one trigger?**
  **[TESTED]** for completion order (see step 13); **[UNVERIFIED ON REAL
  HARDWARE]** for the physical claim that DIO0 actually drives the
  camera's external trigger input.
- **How do frame count, timestamps, and the output window correspond?**
  **[TESTED elsewhere]** for the length/truthiness match;
  **[UNVERIFIED ON REAL HARDWARE]** for DIO0 edge count, by the code's own
  admission.
- **When may the next experiment start after save+flush overlap?**
  **[TESTED, directly]** — see step 13's parallel-barrier bullet; this is
  the specific claim an earlier round's test did not actually establish
  (it used `AD2_DIGITAL_OUTPUT_STOP` as a proxy, which precedes the
  per-experiment flush, not after it).
- **Which configuration must be re-applied on parameter change?**
  **[CODE]**, with indirect supporting evidence from the configure-count
  assertion in step 9.
- **What do "stop current experiment," "stop now," and "exception
  recovery" each mean?** **[TESTED]** for all three, for the in-series
  case specifically — see step 15.

## Failure-injection coverage (this round)

Added to `tests/test_simple_series.py`, extending the same multi-point/
multi-repeat harness as the main trace test (not a new framework) —
`_connected_temperature_series_harness()` factors the shared setup.
A related general fix was found while building these: `_run_action()`
previously let an exception raised while *constructing* a command's
arguments (not just submitting it) escape uncaught into the Qt callback
chain — `_submit()`'s own try/except only wraps `controller.submit(command)`,
not building `command` as an argument to it one line above. The whole
dispatch in `_run_action()` is now wrapped in one try/except reporting any
such failure through the normal `_fail()` path, for every action kind
uniformly. The specific scenario that surfaced this
(`temperature_max_wait_s` below `TecWaitStableArgs`' fixed `poll_interval_s`)
was later fixed a different way, in a subsequent round: `_run_action()`'s
`"tec_wait_stable"` branch now computes `poll_interval_s = min(1.0,
max_wait_s)`, so that combination is never invalid in the first place —
see `decision_log.md`'s later entry correcting this one. The propagation
fix itself stays as defensive code with no concrete scenario currently
reaching it through the declarative pipeline.

- **`test_stability_wait_failure_stops_series_before_any_point_starts`**:
  forces `tec_wait_stable` to time out (simulated TEC target held
  unreachable) during the *first* temperature point, before any
  `experiment` node has started. Asserts: zero `experiment_started`
  events, the series ends `"failed"`, `status.json` shows
  `experiments_started == experiments_completed == experiments_failed == 0`
  (no experiment ever began — see the note on `record_experiment_failed()`
  below), and the second temperature point's `tec_set` never fires.
- **`test_acquisition_failure_within_a_series_stops_before_the_next_repeat`**:
  forces the simulated camera to return a missing timestamp on the
  *first* repeat of the *first* point (reusing the same fault-injection
  pattern as the pre-existing `test_missing_sdk_timestamp_fails_acquisition_without_saving_frames`,
  applied inside a multi-repeat/multi-point series instead of a
  single-experiment one). Asserts: the second repeat's `CAMERA_SEQUENCE_CONFIGURE`
  never fires, the second point's `tec_set` never fires, the failed
  experiment's incomplete folder is discarded, and `status.json` shows
  `experiments_started == 1`, `experiments_completed == 0`,
  `experiments_failed == 1`, `finalized_outcome == "failed"`.
- **`test_save_failure_within_a_series_stops_before_the_next_repeat`**:
  forces `SeriesStorage.save_frames` to raise on the first experiment's
  save, reusing the pattern from the pre-existing
  `test_save_failure_stops_later_queued_series_without_overwriting` (which
  already covers the *next-queued-series* case) but checking the
  *next-experiment-within-the-same-series* case instead, which was not
  previously covered.

Each of the three confirms: the failure is recorded (`record_experiment_failed()`
or no experiment ever started, as appropriate), the recovery actions
specific to a normal command failure run (`_fail()` → `SAFE_STOP` to
AD2/Camera, flush left to its own recovery if one was active —
**[CODE]** for the flush-left-alone detail specifically, not separately
re-verified this round since no flush was in flight in these three
scenarios), and the final `status.json`/`manifest.json` record is
internally consistent with what actually ran — never reporting more
`experiments_completed` than experiments that genuinely finished.

## junjiebranch's equivalent flow, compared point-by-point

Read directly this round from `origin/junjiebranch:src/thermo_acoustic/
application.py` (`STEP_ORDER` constant, `run_temperature_series()`) and
`workflows.py` (`Experiment2`/`ExperimentSeries2`, mostly data holders — the
actual run loop lives in `application.py`, not there). All of the following
is **[CODE]**, read from junjiebranch's source — none of it was re-run
against junjiebranch (no worktree of that branch was created this round).

- **Per-repeat step order is a fixed, hardcoded sequence**
  (`application.py:74 STEP_ORDER`): `InitializeExperiment → ConfigureWfg →
  ConfigureCamera → CaptureFrames → WaitForAd2Completion → Flush →
  SaveResults`. **Correction (2026-10-25, re-read at junjie HEAD `2528c1c`):** the
  earlier statement that flush and save are strictly sequential in
  junjiebranch was wrong. `application.py:_run_experiment2_unfinalized`
  starts the flush in a thread, saves on the main thread, then joins the
  flush thread (also described in junjie's
  `handover_sequence_reconciliation_20260904.md`). The per-repeat order
  above is the `STEP_ORDER` list; the concurrency is in how steps 6–7 run.
  ola/integration runs
  `save_frames` and `wait_outputs`[+flush] as **two concurrent branches**
  with a hard barrier before the next step (now directly tested, see
  above) — an adaptation of the same idea with explicit failure containment. junjiebranch's comment explicitly excludes `SetTecTarget`/
  `WaitTecStable` from this fixed list, confirming the same top-level
  structure as ola's "temperature point wraps N repeats."
  - **Consequence** (revised: junjie overlaps them too; the difference is
    the failure handling): in ola, a failed save
    does not stop an already-started flush from completing (and vice
    versa) — different failure-containment boundaries, not just speed.
- **Graceful stop granularity**: junjiebranch checks `stop_fired` at *two*
  layers — `run_temperature_series()` (between temperature points) and,
  per its own comment, `qt_ui.py`'s `_run_experiment_series_body()`
  (between repeats, UI layer). ola/integration checks `stop_after_current`
  in exactly *one* place, which structurally covers both boundaries.
- **Abort/stop entry points**: no `abort`/`panic` method exists on
  junjiebranch's `Application` class itself (confirmed:
  `grep -n "def abort\|def panic"` on `application.py` matches nothing) —
  that logic lives in `qt_ui.py`'s `_busy_count`/Critical-Stop UI
  mechanism. ola/integration's `abort()`/`panic_abort()`/
  `stop_after_current()` are dedicated `ExperimentManager` methods with no
  UI dependency — **but, as noted above, none of the three has a test on
  this branch either**. The architectural claim (cleaner separation) is
  still true by inspection; the behavioral claim (that they work
  correctly) is not yet tested on either branch.
- **junjiebranch counts lifecycle at the temperature-point level too**
  (`SeriesLifecycleManifest.tec_point_started`/`tec_point_completed`), not
  only per-repeat. ola/integration's `SeriesStorage` counts only
  `experiments_started`/`_completed`/`_failed` — there is no separate
  temperature-point-level counter. See `migration_checklist.md` for the
  disposition of this specific gap.

This is not a full line-by-line re-audit of every junjiebranch function —
it is a targeted comparison of the points this round's questions raised.
