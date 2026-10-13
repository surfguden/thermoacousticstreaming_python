# Feature migration checklist

Status values: `done` (already true on this branch, no action), `planned`
(Phase 1, recorded and awaiting approval), `open` (needs investigation before
a plan can be written), `deferred` (decision owner needed, not a code task).

| Module | Status | Note |
|---|---|---|
| Pump driver safety logic (fault-clear, position-sensing gate) | done | Carried from junjiebranch's `qmix_backend.py` into `drivers/pump/cetoni.py`, verified near-identical |
| Pump capacity: batch-budget check | done | `experiment_runner.py:492 _check_capacity`, distinct purpose, correct as-is |
| Pump capacity: fresh-read-at-flush plausibility | planned (Phase 1) | `application/workflows.py` `FlushWorkflow.LEVEL_READ` — see `decision_log.md` for exact scope/constraints; NOT approved yet |
| TEC driver (connect/setpoint/Static-OFF) | done | `drivers/tec/controller.py`, equivalent to junjiebranch's `tec.py` |
| TEC multi-point scan algorithm (`TemperatureSeries` equivalent) | open | Confirmed gap; no design written yet |
| TEC Prepare-tab readback display (requested vs. controller) | open | Not checked against `ui/device_panels.py:1847 TecPanel` yet |
| Valve driver + automated flush confirmation | done | `FlushWorkflow` already confirms `ValveReadback.ready`+`confirmed_position` with timeout+recovery; no gap |
| Valve `VALVE_WAIT_READY` return semantics (manual path only) | open | Low priority, unconfirmed impact — see `known_open_items.md` |
| AD2 driver incl. FM/sweep | done | `drivers/ad2/analog_discovery.py` carries fm_mod/sweep support |
| AD2 JP4/series-source documentation | open | Undocumented in code on either branch; needs a decision on where to record it |
| Camera driver | done (structurally) | Real `image_sequence` acquisition not yet exercised on this branch's real-hardware log — flagged for a future bench check, not a code gap |
| Z-stage driver + UI | done | `ui/z_stack_panel.py` is a superset of junjiebranch's Z-Scan tab fields |
| Z-stage stepping algorithm parity | open | Not compared against `ZScanCalibration.run()`'s actual algorithm, only UI fields |
| Experiment-sequencing engine (cartesian expansion, preflight validation) | done | `experiments.py`/`experiment_runner.py`; `run_s <= 0` validated at `experiments.py:242-243`, equivalent to junjiebranch's Channel-0 preflight fix, independently arrived at |
| Series lifecycle manifest (live started/completed/failed/outcome tracking) | open | junjiebranch's `SeriesLifecycleManifest` has no ola equivalent; `experiment_storage.py`'s `status()`/`event()` are generic primitives, not a purpose-built aggregate |
| Fault-reason surfacing in UI | done | `event_formatting.py:42` already includes `event.message` on every failure |
| Chronology-ordered Prepare checklist (UX principle) | open | Which panel plays this role on ola-branch not yet identified |
| Data format (TDMS vs. TIFF+JSON) | deferred | Owner decision required; not a code task until decided |
| Analysis | deferred | Not implemented in Python on either branch; LabVIEW-only, separate repo (`C:\git\thermacoustics`), out of this integration's scope |
| Test environment (external basetemp, isolated deps) | in progress (Phase 0) | See Phase 0 test report below / in the conversation; no `known_flaky` port (withdrawn as unjustified for this codebase) |
