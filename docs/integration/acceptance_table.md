# Integration acceptance table

Format: **requirement → implementation entry point → verification evidence
→ status**. Status uses five categories, not a binary done/unfinished:

- **阻塞 (blocks current experiments)** — must be resolved before a normal
  experiment can run correctly.
- **需要 (capability needed now)** — not blocking, but something the lab
  actually uses today.
- **可选 (optional enhancement)** — a real capability with no demonstrated
  current need; welcome if someone asks for it, not pursued speculatively.
- **不做 (explicitly not doing)** — considered and declined, with the
  reason recorded so it isn't silently revisited.
- **待实机 (needs future real-hardware verification)** — simulated-only
  today; nothing here claims physical correctness.

Not tested against every theoretical combination, and not a full parity
copy of junjiebranch's historical planning documents — neither of those is
treated as a defect by itself (see `decision_log.md`'s 2026-10-15 entries
for why).

| Requirement | Entry point | Evidence | Status |
|---|---|---|---|
| Pump raw fill-level reading distrusted before computing a flush target | `application/workflows.py` `FlushWorkflow._implausible_reading()` | 4 tests in `tests/test_workflows.py` | 待实机 — the underlying Qmix SDK fill-level behavior this guards against (`HW-PUMP-FILL-GEOMETRY-001`) was observed once, on real hardware, on junjiebranch; not re-confirmed on this branch's driver |
| TEC multi-point, single channel (operator picks the channel) | `application/simple_series.py` (`"channels": [settings.tec_channel]`) + `ui/simple_series_panel.py` (one `tec_channel` combo) | `test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order` | satisfied. Note: `SimpleSeriesPanel` always sends exactly one channel per point — it has no path to address both channels at once, same value or different. "Locked"/"unlocked" is junjiebranch's vocabulary for a ch1/ch2 broadcast relationship this UI does not have; avoid that phrasing for this panel's behavior |
| Parameter sweep + repeats, real device dispatch | `application/experiments.py` cartesian expansion | `test_ui_configured_parameter_sweep_with_repeats_runs_every_combination` — 2 frequencies × 2 repeats via the real panel | satisfied. Note: this and the row above are **panel-level automation** (`SimpleSeriesPanel` constructed directly, not `MainWindow`) — see the test file's module docstring; not literal mouse/keyboard input into the running application |
| TEC multi-point, both channels addressed from one definition (same or independent targets) | `application/experiments.py` (dict-valued sweep parameter, or a plain scalar with `channels: [1, 2]`) | `test_temperature_point_series_supports_independent_per_channel_targets` (engine only, no UI path) | 可选 — engine-only capability, reachable only through a hand-authored JSON definition, not through `SimpleSeriesPanel`; no demonstrated current need to expose it in the UI |
| Series lifecycle — real-time persistence | `experiment_storage.py` `record_experiment_*()` | `test_lifecycle_counts_are_persisted_before_the_series_ends` | satisfied |
| Series lifecycle — crash-state interpretation | Manual procedure in `known_open_items.md` | Documentation | satisfied as a manual procedure — not automated, and not meant to be yet |
| Series lifecycle — automatic resume | — | — | 不做 — not junjiebranch's own capability either; new ground with no current request for it |
| Stop/abort/panic **during an active series** | `experiment_runner.py` `stop_after_current()`/`abort()`; `controller.py` `panic_stop()` | 3 tests, each checking only the series-level consequence | satisfied in simulation; 待实机 for real device response under an actual abort |
| Parallel save/flush barrier | `_run_nodes()`'s `parallel` handling | 2 tests with controlled, measured delays | satisfied |
| Whole-series flush-capacity sum across placements | `_check_capacity()` | 3 placement tests (series-level, per-repeat, mixed) | satisfied — 3 placements is the representative set asked for, not a partial subset of "all combinations" |
| Exception propagation from command-argument construction | `_run_action()` (whole-dispatch try/except) | Written while fixing the `max_wait_s` scenario below, which has since been fixed a different way (the poll interval now adapts, eliminating that specific error case). No concrete scenario currently reaches this path through the declarative pipeline — kept as defensive code, not exercised by a dedicated test | kept as general protection, currently untested by a concrete case — not claimed otherwise |
| `temperature_max_wait_s` below 1s is genuinely executable (software path, not physical claim) | `experiment_runner.py` `_run_action()`'s `tec_wait_stable` branch (`poll_interval_s = min(1.0, max_wait_s)`) | `test_tec_wait_stable_with_a_sub_one_second_max_wait_actually_runs` (raw definition), `test_ui_configured_short_max_wait_actually_completes` (real panel path) | satisfied for the narrow claim tested — correction from the prior round, which had only changed "rejected at compile time" into "fails at run time," not actually made the value usable. The poll interval now adapts automatically and the step runs to completion without error. **This proves only that the software path executes; it is not evidence that a real TEC and sample could physically reach thermal stability within such a short window.** Both tests run against `SimulatedTec`, which reaches its setpoint instantly with no thermal lag. A real device would need its own, separately measured settling time, and an operator choosing a short `temperature_max_wait_s` on real hardware would very likely see it fail the stability check correctly, not succeed |
| AD2 JP4/JP5 series-source documentation | `docs/integration/hardware_notes.md` | Documentation | 待实机 — physical jumper position on the installed board has never been checked, on either branch |
| Z-stage two-tier operator confirmation | — | `known_open_items.md` | 不做 — reviewed, current single-gate design kept, documented as a strategy difference |
| Z-stage algorithm (non-confirmation aspects) | `application/z_stack.py` | Compared against junjiebranch's `ZScanCalibration` | satisfied in simulation; 待实机 — junjiebranch's own real motion attempt failed, neither branch has a working real run |
| Data format (TDMS vs. TIFF+JSON) | — | In-repo check only (no internal TDMS dependency found) | 不做 (keep TIFF+JSON) for this repo's own architecture; **separately unresolved**: whether the external LabVIEW `analysis.vi` path needs TDMS was never checked — not blocking current Python-side experiments, revisit only if that external pipeline is actually needed |
| Valve `VALVE_WAIT_READY` manual-path semantics | `hal/valve.py` | Code/trace reading only | satisfied — verified no operator-visible gap, no test added since nothing to assert beyond what's already true |
| TEC target display (`None` rendering) | `ui/device_panels.py` | `test_tec_table_shows_dash_not_literal_none_for_an_unreported_target` | satisfied |
| Chronology-ordered Prepare checklist | — | — | 不做 — no real-operator evidence exists to judge what order would even be correct |
| junjiebranch's temperature-point-level lifecycle counters | — | — | 可选 — no demonstrated current need to track point-level progress separately from experiment-level |
| Camera real `image_sequence` acquisition on this branch's driver | `drivers/camera/hamamatsu.py` | Simulated only | 待实机 |

## What this means in practice

- **Nothing in this table currently blocks running a simulated experiment
  end to end** — every "阻塞" category is empty.
- **Everything marked 待实机 means the same thing**: this has only ever
  run against a simulated device. That is true of the entire control path,
  not just these rows — see the final summary for what real-hardware
  verification would actually need to cover.
- **"可选" and "不做" rows are not gaps to close later by default** — they
  are recorded so a real future request doesn't have to re-discover the
  same analysis, not as a backlog to work through.
