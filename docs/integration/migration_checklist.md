# Feature migration checklist

Current operating reference for control behaviour `aa5f3d1` and launchers `168cac4`. Overall acceptance is in
`acceptance_table.md`; current exceptions/policies are in `known_open_items.md`. Existing hardware
evidence is reused within its scope. This guide does not require a new full hardware validation.

Status values: `done` (implemented), `planned` (specifically authorized but not yet
implemented), `open` (a concrete question), `deferred` (not scheduled). A historical
phase or a deferred item is not a standing instruction to develop it.

## Quick reference: running an experiment, and where to change things

**Launching.** Double-click `launch_ui.bat` (simulation) or `launch_ui_real.bat` (real, authorized
workstation only). They choose a validated Python (`THERMO_ACOUSTIC_PYTHON`, then the workspace
`.venv`, then `%USERPROFILE%\.conda\envs\exp_ctrl`), never search `PATH`, never install anything and
never change the mode. Real-mode Connect actions submit device access without an extra confirmation;
batch Start and pump reference moves have their own confirmation. Details in `README.md`.
From a console without the launcher:
```
cd src
python -m thermo_acoustic.main --mode simulation
```
`--mode simulation` is the default; `--mode real` drives connected hardware and needs the usual
real-hardware precautions (not covered by this guide).

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

**Where things are in the window.** A "Task" row under the title links to existing tabs
(1 Prepare devices → the Prepare tab, which lists the six devices; the device tabs stay, 2 Configure and 3 Review and start → the two pages of the
Experiments tab, 4 Monitor run → the Run monitor tab). They only switch tabs; every tab stays
reachable and nothing is required before Start. **Stop after current**, **Abort batch** and
**PANIC · Safe stop** are always visible at the top right: Stop after current lets the running
experiment finish and ends the batch before the next one; Abort cancels the running experiment and
ends the batch (an incomplete acquisition is discarded, completed experiments are kept); Panic
asks for confirmation, then urgently stops the connected AD2/pump/camera/TEC outputs (valve and Z
stage hold position). Run monitor: batch progress, the running experiment's own parameters,
series and output folder (with Open output folder), device state and TEC temperatures.
Hardware timing and the temperature stability policy are under the folded **Advanced** section of
Configure; its header repeats their values while folded.

**Looking at images.** The camera image window (Camera tab or Run monitor) and the saved-frames
viewer share the display range, Fit/100 %, zoom/pan, histogram and pixel readout, and add:
*Draw / move analysis ROI* (one rectangle; mean, population SD, min, max and pixel count of the raw
values, independent of the display range; not the camera acquisition ROI and it sends no camera
command; dropped when the image size changes) and *Intensity profile* (one raw row or column, in
pixel units; no calibration is applied, so no physical length is shown). **Review saved frames…**
(File menu or Run monitor) opens a series or experiment folder read-only, lists its experiments
and steps through the frames recorded in `experiment.json` (read from disk one at a time, a few
cached). Its banner and state line say "saved data, not live". A folder whose frame records are
missing, out of order or inconsistent is refused with the reason; nothing is guessed from file
names. Series being written can be opened: only experiments that already have an
`experiment.json` are listed.

**Short test recipe for one simulated experiment** (Experiments tab; use the first table row's
values).

1. Launch (nothing connects by itself). On *Prepare* tick the devices the run uses (Pump, Valve,
   Camera, AD2 for the shortest run; leave TEC off and Temperature unticked) and press **Connect
   selected devices**. Each device is connected in turn with the inputs shown in "Connect uses"
   (edit them on the device page via *Open page*); connected devices are skipped, a failure does
   not stop or undo the others and is not retried. A device page's own Connect/Disconnect still
   works. Choosing a device is not a connection and does not mean the experiment is ready.
2. **Pump fill level.** The *simulated* pump starts at 0 mL, so click Refill on the flush unit
   first, otherwise the series fails when it starts (Queue does not check) with "Pump unit N needs X mL
   total flush volume but currently has 0 mL"; the batch syringe preflight finds it earlier. A *real* pump reports its fill level from the SDK; the same guard compares the planned
   flush volume with that read-back. Do not refill by reflex after a restart — prepare the syringe
   according to what it actually holds and what the experiment needs.
3. On *Configure* enter a series descriptor (required) and a base folder, then "Queue series". On
   *Review and start* click "Preflight camera settings" before Start, otherwise Start asks for
   confirmation (real mode also needs the batch syringe preflight).
4. "Start queued batch". Watch it on the Run monitor; Stop after current / Abort / Panic are in the
   header. Queue edits: *Load selected for editing* and *Remove selected series* are on Review and
   start; *Update loaded series* is next to *Queue series* on Configure and changes only the series
   named in "Editing queued series: …" above the form (nothing is changed when none is loaded).
   Review shows what blocks Start and what is only a reminder. A new batch needs a new empty base
   folder (one base folder holds one batch).
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

## Migration disposition

This table states current behaviour; dated implementation stories remain in Git
and the historical investigation/decision logs. It does not schedule new work.

| Area | Current state | Implementation / limit |
|---|---|---|
| Pump/valve drivers | Retained and adapted | CETONI per-unit bank, live fill readings, fault/enable gates, CR-terminated queries, valve status handshake. Sources in `investigation_log.md`; physical questions in `hardware_notes.md`. |
| Series planning | Implemented | `experiments.py` expands definitions; `simple_series.py` compiles the form. Capacity sums all flush placements; initial flush is once per series. |
| Temperature form | Implemented, one selected channel per point | Set plus fixed wait, or stability wait plus extra hold. The runner adapts polling to short positive max-wait; no 1 s device floor is implied. |
| Two-channel temperature definitions | Engine-only, optional UI work | Definitions may address both channels or independent targets. This is not a two-channel authoring path in the normal form. |
| Point-level extra counters | Optional, not scheduled | Existing progress counts experiments/repeats, not a separate temperature-point lifecycle. |
| Settings save/load | Implemented | Existing File menu; explicit JSON profile, type/range checks, pending pump selection. Loading submits no device command. |
| Run identity | Implemented for series | `manifest.run` stores mode and cached Git identity, retained on queued edits; unavailable Git is unknown. Standalone Z-stack metadata differs. |
| Saving and finalization | Implemented | Atomic complete-acquisition publication; save/flush barrier; preserved saved data after later failure; recorder drain and late-callback guards. |
| Stop and shutdown | Implemented | Existing actions, TEC wait cancellation, worker results and pending-thread retention. A blocked SDK call cannot be forcibly interrupted. |
| Independent Z-stack | Implemented | Measured-position confirmation before capture. `stage_move` only accepts a target; no automatic arrival wait was added. Single closed-loop confirmation strategy retained. |
| Viewer | Implemented display tools | Manual/robust/fixed scaling, Fit/100%, zoom/pan and pixel/state readout. Offscreen tests do not replace human visual review. |
| Prepare order / recovery button / elapsed time | Not scheduled | Existing device/console actions remain; changes need a concrete operator use case. |
| TIFF + JSON | Retained | No active external consumer requirement has been established. Do not infer mandatory TDMS support or confirmed compatibility from this. |
| Automatic resume / audit or recipe framework | Not planned | No automatic hardware restart from stale records. Use the manual inspection procedure in `known_open_items.md`. |
| Offline test environment | Existing check method | Use a writable `--basetemp` when the host's default temp ACLs fail. This is an observed host issue, not a universal fresh-clone requirement or a pytest configuration change. |

## Connecting the selected devices (Prepare tab)

- **Behaviour.** `DeviceConnector` (application layer) takes one CONNECT command per chosen device,
  built from that device page's own inputs (`build_connect_command()`, same path as its Connect
  button), and submits them one at a time through the normal command queue. The set and commands
  are fixed when the button is pressed. Skipped: already connected, or a Connect already queued or
  running. A failure is kept per device; others stay connected; nothing is retried, disconnected or
  rolled back. Refused as a whole while an experiment batch, Z stack, count preflight, Panic or
  closing owns the instruments. If Panic or closing starts mid-group, devices not yet submitted are
  not started; a Connect already running is not interrupted. The command lane is serial, so a slow
  Connect delays the next device. No Refill, reference move, Z move, TEC setpoint/output, AD2
  output or capture is sent.
- **What a real Connect does (driver code read, not run).** AD2: opens the first device
  (`FDwfDeviceOpen`) and reads capabilities. Camera: `Dcamapi.init` + `dev_open`, reads ROI. Pump:
  opens/starts the Qmix bus from the configuration folder, **clears a latched fault** (owner-approved
  policy) and **enables the pump drive**, then reads state; no motion is commanded. Valve: opens
  the COM port and sends the status query. TEC: connects the client on the chosen port. Z-stage:
  Kinesis connect, waits for settings, starts polling, reads limits; never switches to closed loop.
  So Connect is not free of device-side effects (pump fault clear and drive enable in particular);
  the group action adds none of its own.
- **junjie.** Taken: choose the needed devices, one action, a result per device, inputs beside the
  choice. Not taken: per-device Simulate toggles (mode switching), cleanup-then-rebuild of the whole
  hardware bundle, a modal dialog, preparation checklist and gates, reference-path stubs.
- **Verified** with simulation and fake devices (`test_device_connect.py`); real drivers, real
  timing and a blocked SDK were not exercised.
