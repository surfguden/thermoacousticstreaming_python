# Experiment definitions

The **Experiment builder** (opened from its menu) loads and saves portable JSON
schema version 1. Use **Default template** as a starting point. The normal
fixed-form Experiment tab compiles its controls into the same schema. The builder's
full JSON editor supports structural edits;
the step tree supports selecting, editing, adding, removing, and moving ordered
steps. A `sweep` has an ordered `parameters` object. Each parameter is either an
explicit list or `{ "start": 1, "stop": 5, "step": 1 }`. Values are inserted only
through `{ "$param": "parameter_name" }` references. Sweeps form a Cartesian
product in listed parameter order. `repeat` executes its child steps for each
one-based repeat index. `experiment` contains one acquisition and one save.

Allowed actions are `flush`, `wait`, `tec_set`, `tec_wait_stable`, `stage_move`,
`camera_configure`, `ad2_configure`, `camera_arm`, `ad2_arm`, `pc_trigger`,
`await_frames`, `wait_outputs`, and `save_frames`. Action arguments use explicit
units in their names (for example `volume_ml`, `flow_ul_min`, `exposure_ms`,
`frame_rate_hz`, `camera_delay_s`). JSON never executes Python or shell text.
The experiment's W2/laser window uses a PC-triggered square waveform at the
reported minimum W2 frequency; the runner requires `run_s * frequency < 0.5` so
the active window does not reach the low half-cycle. `on_voltage_v` is the
requested active level; the selected idle state is OFFSET with offset 0 V.
This describes SDK configuration, not a measured pin voltage or optical-off state.
The retained laser polarity question is recorded in `integration/hardware_notes.md`.
`parallel` is limited to post-acquisition saving and output-completion/fluidic
branches. A flush inside an experiment must follow `wait_outputs` in the same
branch; no pump motion is requested while enabled analog outputs remain active.
The initial flush and each post-acquisition flush (including the final one)
in the default template are editable.

Use **Validate / preview** to see the full ordered expansion and relative output
paths. Queue time chooses an output root and either individual or stacked TIFF.
Each queued series gets a new `experiment_batch_NNNN` directory (inside an empty output root) with
`metadata/definition.json`, `metadata/manifest.json`, `metadata/status.json`, and
`metadata/events.jsonl`.
Each experiment gets a parameter-named folder ending in `repeat_0001/` with
TIFF images and `experiment.json`. The metadata contains camera SDK timestamps
and host UTC receive timestamps as separate clock domains, requested and
applied instrument settings, device readbacks, and frame-to-file/page mapping.
The batch manifest includes `run.mode` and `run.software` (Git identity or
unknown); editing a queued definition preserves that identity. `stage_move`
accepts a soft-limited target without waiting for arrival; its record separates
requested/sent values from measured Z position. Use the independent Z-stack
entry for the existing position-confirmed-then-capture workflow.

An incomplete acquisition is discarded by current policy (commit `f717884`). A
complete acquisition folder is published atomically. A later output/flush failure
keeps its TIFFs and records `post_acquisition.outcome: failed`; folder presence
alone is not proof that the whole experiment completed successfully.

Terminal commands accepted by the running application:

```text
experiment validate definition.json
experiment queue definition.json --output-root C:\data --format frames
experiment start
experiment status
experiment stop-after-current
experiment abort
```

Definitions are machine-independent: no output directory or COM-port path is
stored in them. Required devices must already be connected. Real-mode Start
asks once for the series currently queued; series queued afterward require a
new Start approval. The optional real-mode count preflight runs before the
first flush with ultrasound, laser, LED and pump inactive. It verifies receipt
of N triggered frames and discards test images. Without an external loopback it
does **not** prove exact physical DIO0 edge count or frame-interval accuracy.
Bench timing checks belong in manual-only `hardware_tests/`, never CI.
