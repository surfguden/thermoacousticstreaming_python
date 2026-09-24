# Experiment definitions

The Experiments tab loads and saves portable JSON schema version 1. Use **Default
template** as a starting point. The full JSON editor supports structural edits;
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
Laser channel 2 is a PC-triggered DC window: `on_voltage_v` is its active
output level, while its idle output is disabled.
`parallel` is limited to post-acquisition saving and output-completion/fluidic
branches. A flush inside an experiment must follow `wait_outputs` in the same
branch; no pump motion is requested while enabled analog outputs remain active.
The initial flush and each post-acquisition flush (including the final one)
in the default template are editable.

Use **Validate / preview** to see the full ordered expansion and relative output
paths. Queue time chooses an output root and either individual or stacked TIFF.
Each queued series gets a new `experiment_series_<name>_<UTC>` directory with
`metadata/definition.json`, `manifest.json`, `status.json`, and `events.jsonl`.
Each experiment gets a parameter-named folder ending in `repeat_0001/` with
TIFF images and `experiment.json`. The metadata contains camera SDK timestamps
and host UTC receive timestamps as separate clock domains, requested and
applied instrument settings, device readbacks, and frame-to-file/page mapping.
Incomplete acquisitions are labelled and any copied frames are retained under
`partial_capture/`.

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
