# End-to-end experiment flow — code-derived baseline (ola/integration)

This traces the actual call chain in `application/experiment_runner.py`
(`ExperimentManager`), `application/workflows.py` (`FlushWorkflow`),
`application/controller.py` (`ApplicationController`), and
`application/simple_series.py` (the real UI compiler). Every stage below
cites the function/line it comes from. "Allowed overlap" notes where two
things genuinely run concurrently, as opposed to merely being adjacent in
the step list.

## Stages, in actual code order

1. **UI parameter entry** (`ui/simple_series_panel.py` `_settings()`) →
   **definition compilation** (`simple_series.py` `compile_simple_series()`)
   → **structural validation** (`experiments.py` `validate_definition()`,
   called both by the compiler itself and again by `queue()`).
2. **Queue** (`experiment_runner.py:110 queue()`): requires a non-empty
   description; all series in one batch must share one output root;
   allocates `experiment_batch_NNNN` via `SeriesStorage.__init__`.
3. **Optional, UI-triggered syringe preflight** (`preflight_syringe():224`):
   reads live pump status+fill level per unit that has any flush anywhere in
   the queued batch; independent of `start()`'s own gate.
4. **Start** (`start():315`): gate chain — Z-stack not running, Panic not
   stopping, count-preflight not active, nothing already running, something
   queued, syringe preflight not mid-flight; in REAL mode only, blocks if
   flush steps exist and syringe preflight isn't current; asks
   `confirm_unchecked` if camera preflight hasn't passed for some queued
   series; in REAL mode only, asks `confirm_batch`. Returns immediately;
   `_next_series()` is scheduled via `QTimer.singleShot(0, ...)` — the UI's
   `Start` click returns before any device is touched.
5. **Per-series preparation** (`_next_series():390`): pops the next queued
   series; opens the temperature-log CSV if `temperature_logging` is set
   (failure here aborts before anything else runs); `_require_devices()`
   walks the **entire** step tree once to collect every resource used
   anywhere in it (pump/valve from any `flush`, camera from any `camera_*`/
   `await_frames`, ad2 from any `ad2_*`/`pc_trigger`/`wait_outputs`, tec from
   any `tec_*`, z_stage from any `stage_move`) and requires **all** of them
   connected **before anything in the series starts** — not lazily per step.
   `temperature_logging` additionally requires TEC connected even with no
   `tec_*` steps.
6. **Pump re-sync** (`_refresh_pump_preflight():428`): re-reads
   `PUMP_STATUS_READ`+`PUMP_FILL_LEVEL_READ` for every unit index used by any
   flush in the whole series (plus, if the definition's `preflight` flag is
   set, every currently-known unit).
7. **Capacity check** (`_check_capacity():492`): disk/memory estimate across
   **all** experiments in the series; pump capacity is the sum of **every**
   flush volume found **anywhere in the whole step tree** (recursing through
   `experiment`/`parallel` nodes) **per unit index** — this is a whole-series
   sum regardless of whether the flush nodes are placed at series level,
   inside a temperature-point branch, or inside each repeat; placement does
   not change that the check is correct, since the walk is a full recursive
   tree walk, not level-specific.
8. **Timing/laser-window validation for every experiment** (via
   `_after_camera_timing():572`): the AD2 WFG2 minimum carrier frequency is
   read **once** for the whole series and cached (`self._laser_frequency_hz`)
   — not re-read per experiment. For **every** experiment in the series (not
   just the first), validates the laser window, camera-exposure-vs-interval,
   and interval-vs-live-SDK-minimum/readout-time — a bad combination
   anywhere in a multi-point/multi-repeat series is caught here, before any
   device is actually configured for real.
9. **Series-level configuration validation**
   (`_configure_all_before_fluidics():627`): collects the **unique**
   (camera, ad2) configuration pairs across all experiments (de-duplicated),
   and for each unique pair, actually applies it once via the real command
   path (`CAMERA_SEQUENCE_CONFIGURE`/`AD2_WAVEFORM_CONFIGURE`/
   `AD2_EXPERIMENT_DIGITAL_CONFIGURE`) purely to validate the achieved
   waveform/digital-out window fits the bounded output timeout. This runs
   **before any fluidics or TEC action** in the series.
10. **Optional real-hardware count preflight** (`_run_count_preflights():667`,
    REAL mode + `preflight` flag only): per unique (camera, dio) pair, a real
    camera-triggered acquisition cycle with the LED/laser path explicitly
    disabled (`led_enabled=False`), verifying exact frame/timestamp count and
    a bounded DigitalOut completion — explicitly logged
    `physical_dio0_edges_verified: False` (frame-count match is not proof of
    physical DIO0 edge count).
11. **Begin** (`_begin_steps():751`): writes `status("running")`, starts
    camera continuous preview, **then** begins walking the declarative step
    list (`_run_nodes`).
12. **Node execution** (`_run_nodes():776`): sequential walk of the
    (sweep/repeat-expanded) step list. An `experiment` node resets
    per-experiment state, emits `experiment_started`
    (+`storage.record_experiment_started()`), recurses into its own body,
    and on completion writes final per-experiment metadata, increments
    completed count, **checks `stop_after_current` only at this exact
    boundary** (never mid-experiment), then continues. A `parallel` node
    runs **all branches concurrently** and only continues once every branch
    signals done — this is a hard barrier, not an overlap into the next step.
    Any other node is a **leaf action** (`_run_action():844`).
13. **Leaf actions, in the order `_validate_experiment()` enforces inside an
    experiment block**: `camera_configure` → `ad2_configure` → `camera_arm`
    → `ad2_arm` → `pc_trigger` → `await_frames`, then a `parallel` block of
    `[save_frames]` and `[wait_outputs, flush?]`.
    - `camera_configure`/`ad2_configure` are **re-applied via the real
      command path for every single experiment node**, even when identical
      to the previous experiment's — there is no skip-if-unchanged
      optimization at execution time (only the series-level validation pass
      in step 9 is deduplicated).
    - `camera_arm` (`CAMERA_SEQUENCE_ARM`) completes **fully before**
      `ad2_arm` even starts — not concurrent. `ad2_arm` itself is two
      sequential commands: `AD2_WAVEFORM_START` then
      `AD2_DIGITAL_OUTPUT_START`.
    - `pc_trigger` (`AD2_SOFTWARE_TRIGGER`) is the **one** software trigger;
      it starts the AD2's configured waveform+digital output, and the
      digital output's DIO0 edges are what actually triggers the camera's
      hardware **external** trigger input (the camera's own trigger source
      is configured as `EXTERNAL`, not software) — one shared hardware-level
      synchronization point, not two independent software signals.
    - `await_frames` (`CAMERA_SEQUENCE_COLLECT` → `_frames_collected()`)
      requires `len(frames) == len(timestamps) == frame_count` **and** every
      per-frame SDK timestamp truthy — any single missing timestamp fails
      the whole experiment. Immediately (not waiting for anything) resumes
      continuous preview, concurrently with whatever follows.
    - `save_frames` submits to a **single-worker** `ThreadPoolExecutor`
      (`FileWorker`) — saves across different experiments are serialized
      relative to each other even though each is dispatched asynchronously.
    - `wait_outputs` polls `AD2_OUTPUT_STATUS_READ` until digital state is
      `"done"` and every enabled channel's waveform state is `"done"`,
      bounded by `triggered_at + output_timeout_s`; on completion, stops
      **both** AD2 waveform and digital output, then (if present) proceeds
      to the post-acquisition flush in the same branch.
    - **The parallel block's two branches (save + wait_outputs[+flush]) must
      both finish before `_run_nodes`'s continuation fires** — the next
      top-level step (next experiment, next temperature point's `tec_set`,
      etc.) cannot begin until both are done. Confirmed by code structure
      (`branch_done()`'s `remaining == 0` gate) and by a real,
      `monotonic()`-timed command/event trace in
      `tests/test_simple_series.py::test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order`.
14. **Series completion** (`_complete_series():755`): drains and closes the
    temperature recorder (retries every 50ms until drained before
    finalizing — so a slow temperature-log flush can delay series
    completion, but does not corrupt it); writes terminal `status("completed")`
    + `experiments_completed`/`finalized_outcome`; schedules `_next_series()`
    for the next queued series in the batch.
15. **Stop/abort/recover — three materially different paths**:
    - `stop_after_current()` (`:361`): sets a flag only, checked at the
      experiment-boundary described in step 12 — the current experiment
      (including its full parallel save/output-wait/flush) always runs to
      completion first.
    - `abort()` (`:367`, operator "stop now"): stops all internal QTimers
      immediately, **actively cancels** any in-flight `FlushWorkflow**
      (`cancel_active_workflow()`), issues `SAFE_STOP` to **AD2, Camera,
      Pump, and Valve** (all four), then fails the batch.
    - A normal command failure (`_fail():1081`, default
      `stop_outputs=True`): issues `SAFE_STOP` to **AD2 and Camera only** —
      an in-flight flush is deliberately **left alone to run its own
      internal pump-stop/valve-recovery** (`FlushWorkflow`'s own `_fail()`
      path, not forced from outside).
    - `panic_abort()` (`:383`): `stop_outputs=False` — does not even issue
      AD2/Camera `SAFE_STOP` through this path, relying on a separate panic
      mechanism elsewhere in the controller.
    - `_finish_failure_when_safe()` (`:1108`) blocks (100ms-recursive) until
      no flush is active, every file-save future is done, and the
      temperature recorder is drained — only then discards the in-progress
      experiment's incomplete folder, marks the series failed/aborted,
      **cancels every other queued series in the same batch** (a single
      series failure abandons the whole batch, not just that series), and
      emits a UI-visible notice.

## Direct answers to the specific questions raised

- **Does flush belong to the whole series, a temperature group, or a single
  repeat?** Placement in the JSON step tree determines *association*
  (series-level if outside any sweep/repeat, per-point if inside a
  temperature sweep branch, per-repeat if inside a `repeat` block) — but the
  **capacity check is always a whole-series sum**, correctly computed
  regardless of placement because it is a full recursive tree walk (step 7).
- **When is temperature considered stable, when is it held, when is
  acquisition allowed?** `tec_wait_stable` decides "stable" (continuously
  within `tolerance_c` for at least `min_settle_s`, bounded by
  `max_wait_s`); a **separate**, subsequent plain `wait` node is the
  post-stability hold (not conflated with `min_settle_s`); acquisition
  (the `experiment` block) only starts after both have completed, since
  they are earlier siblings in the same step list.
- **How do camera-armed and AD2-armed unify into one trigger?** They do not
  race: camera arms fully, then AD2 arms (waveform start, then digital-out
  start), then one `AD2_SOFTWARE_TRIGGER` starts AD2 output, whose DIO0
  edges are the camera's actual (external, hardware) trigger source.
- **How do frame count, timestamps, and the output window correspond?**
  `frame_count` must exactly equal both the collected frame count and the
  collected timestamp count, with every timestamp truthy; this is a
  software-level length/truthiness match only — there is no cross-check
  against DIO0 edge count (explicitly logged as unverified).
- **When may the next experiment start after save+flush overlap?** Only
  after both parallel branches (file save; AD2-output-wait-then-stop-then-
  optional-flush) complete — a hard barrier (step 13, last bullet).
- **Which configuration must be re-applied on parameter change?**
  `camera_configure`/`ad2_configure` are re-applied via the real command
  path for every experiment node, always — there is no per-execution
  caching; only the series-level *validation* pass is deduplicated by
  unique configuration.
- **What do "stop current experiment," "stop now," and "exception recovery"
  each mean?** Three distinct, code-confirmed behaviors — see step 15.

## junjiebranch's equivalent flow, compared point-by-point

Read directly this round from `origin/junjiebranch:src/thermo_acoustic/
application.py` (`STEP_ORDER` constant, `run_temperature_series()`) and
`workflows.py` (`Experiment2`/`ExperimentSeries2`, mostly data holders — the
actual run loop lives in `application.py`, not there).

- **Per-repeat step order is a fixed, hardcoded sequence**
  (`application.py:74 STEP_ORDER`): `InitializeExperiment → ConfigureWfg →
  ConfigureCamera → CaptureFrames → WaitForAd2Completion → Flush →
  SaveResults`. **Flush and Save are strictly sequential** in junjiebranch —
  flush must fully complete before save even starts. This is a genuine
  architectural difference from ola/integration, not a reordering: ola runs
  `save_frames` and `wait_outputs`[+flush] as **two concurrent branches**
  inside a `parallel` node, with a hard barrier before the next step (see
  the "Leaf actions" section above). junjiebranch's comment explicitly
  excludes `SetTecTarget`/`WaitTecStable` from this fixed list, confirming
  the same top-level structure as ola's "temperature point wraps N repeats
  of the acquisition sequence."
  - **Consequence of the difference**: in junjiebranch, a slow/failed flush
    delays or blocks the save that would otherwise be independent; in ola, a
    failed save does not stop an already-started flush from completing (and
    vice versa) — different failure-containment boundaries, not just
    different speed.
- **Graceful stop granularity**: junjiebranch checks `stop_fired` in *two*
  separate places at *two* layers — `run_temperature_series()`
  (`application.py`, between temperature points only) and, per its own
  comment, `qt_ui.py`'s `_run_experiment_series_body()` (between repeats,
  UI layer). ola/integration checks `stop_after_current` in exactly *one*
  place (`experiment_runner.py`'s per-experiment `finished()` callback),
  which structurally covers both repeat- and point-boundaries since every
  repeat is its own `experiment` node — one consistent mechanism instead of
  two duplicated ones at different layers.
- **Abort/stop entry points**: no `abort`/`panic` method exists on
  junjiebranch's `Application` class itself (confirmed: `grep -n "def
  abort\|def panic"` on `application.py` matches nothing) — that logic lives
  in `qt_ui.py`'s `_busy_count`/Critical-Stop UI mechanism (the
  architectural defect already documented in `investigation_log.md`).
  ola/integration's `abort()`/`panic_abort()`/`stop_after_current()` are
  dedicated, independently testable `ExperimentManager` methods with no UI
  dependency.

This is not a full line-by-line re-audit of every junjiebranch function —
it is a targeted comparison of the specific points this round's questions
raised (flush/save concurrency, stop granularity, abort entry points). A
few further points (e.g. junjiebranch's `SeriesLifecycleManifest.
tec_point_started`/`tec_point_completed` counters vs. ola's per-experiment-
only counters — junjiebranch counts at the *temperature-point* level in
addition to repeats, ola only counts experiments) were noticed but not
investigated to the same depth; flagged as a remaining gap, not silently
treated as equivalent.
