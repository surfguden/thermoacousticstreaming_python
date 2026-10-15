# Integration acceptance table

Format per explicit instruction: **requirement → implementation entry
point → verification evidence → unfinished items**. Not a completion
declaration by test count or code structure alone — see the "unfinished"
column for what each row does *not* cover.

| Requirement | Implementation entry point | Verification evidence | Unfinished |
|---|---|---|---|
| Pump raw fill-level reading distrusted before computing a flush target | `application/workflows.py` `FlushWorkflow._implausible_reading()`/`_unit_capacity_ml()` | 4 tests in `tests/test_workflows.py` (implausible-but-negative, implausible-but-in-range, legitimate reading, correct per-unit capacity lookup), each confirming stop/valve-recovery/failure-state | Real-hardware confirmation of the underlying SDK fill-level behavior (`HW-PUMP-FILL-GEOMETRY-001`) remains open on both branches |
| TEC multi-point, **locked** (shared target per point) | `application/simple_series.py` `compile_simple_series()` + `ui/simple_series_panel.py` (`temperature_wait_for_stability` checkbox + spinboxes) | `tests/test_simple_series.py::test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order` — driven through real panel widgets, asserts command order including tec_wait_stable→hold→arm sequencing and the hold's real elapsed time | None open for this specific capability |
| TEC multi-point, **unlocked** (independent per-channel targets) | `application/experiments.py` (dict-valued sweep parameter) | `tests/test_experiments.py::test_temperature_point_series_supports_independent_per_channel_targets` (engine only) | **Not UI-usable** — no panel path exists; definition-file-only (see `migration_checklist.md` for scope if pursued) |
| Series lifecycle — real-time persistence | `application/experiment_storage.py` `SeriesStorage.record_experiment_started/completed/failed()` | `tests/test_simple_series.py::test_lifecycle_counts_are_persisted_before_the_series_ends` — reads `status.json` from disk mid-series, not only after completion | None open for persistence itself |
| Series lifecycle — crash-state interpretation | Manual procedure, `docs/integration/known_open_items.md` | Documentation only, by instruction — no test applicable | No code-level detection of an abandoned run; relies on a human reading the file |
| Series lifecycle — automatic resume | Not implemented | N/A | Explicitly out of scope this round |
| Stop/abort/panic **during an active series** | `application/experiment_runner.py` `stop_after_current()`/`abort()`; `application/controller.py` `panic_stop()`→`experiments.panic_abort()` | `test_stop_after_current_finishes_active_experiment_then_stops_before_next_point`, `test_abort_during_a_running_series_stops_without_starting_the_next_experiment`, `test_panic_stop_during_a_running_series_ends_the_batch_without_moving_the_valve` — each confirms the next experiment/point does not start and `status.json` stays internally consistent | Device-level SAFE_STOP correctness for the no-series-running case rests on pre-existing tests, not re-verified here; no real-hardware test of any of the three |
| Parallel save/flush barrier before the next experiment | `experiment_runner.py` `_run_nodes()`'s `parallel` node handling | `test_parallel_barrier_blocks_next_experiment_until_save_completes`, `test_parallel_barrier_blocks_next_experiment_until_flush_completes` — each measures a real wall-clock lower bound, not an indirect event proxy | None open for this specific barrier claim |
| Whole-series flush-capacity sum across tree placements | `experiment_runner.py` `_check_capacity()` | `test_flush_budget_sums_a_series_level_only_flush`, `..._per_repeat_only_flush_across_two_repeats`, `..._mixed_series_and_per_repeat_placement` | Only 3 placements checked (series-level, per-repeat, mixed) — not every theoretically possible nesting, by instruction ("少量参数化场景") |
| Exception propagation from command-argument construction | `experiment_runner.py` `_run_action()` (whole-dispatch try/except) | `tests/test_experiments.py::test_tec_wait_stable_argument_construction_failure_reports_cleanly` | Only the TEC wait-stable case was reproduced; the fix is general (wraps every action kind) but not separately tested per kind |
| `temperature_max_wait_s` vs. the fixed TEC poll interval | `application/simple_series.py` (reads `TecWaitStableArgs.__dataclass_fields__["poll_interval_s"].default`) | `test_temperature_wait_for_stability_rejects_invalid_bounds` (compile-time) + the argument-construction test above (runtime) | None open — both layers now tested |
| AD2 JP4/JP5 series-source documentation | `docs/integration/hardware_notes.md` | Documentation only | Physical jumper position on the actual installed board remains unverified (always was, on both branches) |
| Z-stage two-tier confirmation | Decision: kept as-is | `docs/integration/known_open_items.md` records the decision and rationale | None — decided, not open |
| Z-stage algorithm parity (non-confirmation aspects) | `application/z_stack.py` | Compared against junjiebranch's `ZScanCalibration`; position-confirmation found more rigorous here | Z-stage real-hardware motion remains untested on both branches (junjiebranch's own real attempt failed) |
| Data format (TDMS vs. TIFF+JSON) | Decision: keep TIFF+JSON | In-repo downstream check (no dependency found) | **External LabVIEW `analysis.vi` consumer was never opened** — compatibility with it is unverified, not confirmed fine; stated as a real limitation, not swept into "decided" |
| Valve `VALVE_WAIT_READY` manual-path semantics | `hal/valve.py` | Verified by code/UI-trace reading (readback label shows true state regardless of command ok/fail framing) | No dedicated test added — judged low priority, unconfirmed impact in practice |
| TEC target display (`None` rendering) | `ui/device_panels.py` `TecPanel._set_channels()` | `test_tec_table_shows_dash_not_literal_none_for_an_unreported_target` | None open |
| Chronology-ordered Prepare checklist | Not implemented | N/A | Deferred — no real-operator evidence to act on, by instruction |
| junjiebranch's temperature-point-level lifecycle counters | Not implemented | N/A | Not yet integrated — see `migration_checklist.md` for scope if pursued |
| Camera real `image_sequence` acquisition under this branch's rewritten driver | `drivers/camera/hamamatsu.py` | Offline/simulated only | No real-hardware log exists for this specific driver on this branch |
| junjiebranch comparison (flush/save concurrency, stop granularity, abort entry points) | N/A (comparative analysis) | `docs/integration/flow_trace.md`'s junjiebranch section, read directly from `origin/junjiebranch` source this round | Targeted, not a full line-by-line re-audit of either branch |

## How to use this table

Every "Unfinished" cell is a real gap, not a formality. In particular:
- The data-format row's unfinished item (external LabVIEW consumer never
  checked) means **"keep TIFF+JSON" is a decision about this repo's own
  architecture, not a statement that external compatibility is solved.**
- The crash-state-interpretation row is intentionally documentation-only;
  it does not mean the underlying risk (an abandoned run going unnoticed)
  is closed, only that the *procedure to notice it* now exists.
- Rows marked "definition-file only" or "not yet integrated" are real
  capabilities that exist in the engine but cannot be reached by an
  operator through the shipped UI — do not read the engine-level test as
  proof of operator-reachability.
