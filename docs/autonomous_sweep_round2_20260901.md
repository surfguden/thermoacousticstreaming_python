# Autonomous Sweep Round 2 — Experiment Truth Audit

> **Historical audit baseline.** Later checkpoints completed the independent
> planner cutover, deterministic camera/acoustic hardening, action logging, and
> V3 redesign. Preserve this audit's evidence and decision trail, but use
> [`project_control.md`](project_control.md) and
> [`known_open_items.md`](known_open_items.md) for current truth and gates.

Date: 2026-09-01
Scope: offline semantic/reproducibility audit only
Starting commit: `183ddd881404bf58e72a7da319529143d412ea75`
No real hardware was accessed. No AD2 output, camera acquisition or live
camera-property write, TEC action, Qmix action, pump, valve, or Z-stage action
was issued.

## Control-state decision

`HW-TIMING-001` is **DEFERRED / READY FOR PHYSICAL VERIFICATION**. Its
software paths are prepared, but physical AD2/DIO1/camera timing remains
unverified. This does not block ordinary software development; it blocks any
claim that those signals are physically synchronized. The eventual measurement
uses an operator-controlled external oscilloscope and does not require
repository-controlled scope acquisition.

## Truth-chain matrix

The current authoritative execution chain is:

`operator UI → legacy builder → Experiment2/ExperimentSeries2 → Application.run_experiment2()`
` → backend calls → applied/runtime state → data.tdms`.

`ExperimentRequest`/`RunPlan`/`BuildResult` currently observe and normalize the
legacy-built objects. They do not replace that builder.

| Area | Stored/requested source | Planned/effective execution | Applied/observed or saved truth |
| --- | --- | --- | --- |
| Series | `series_path`, repeats, optional TEC points | folders are created per temperature and `repeat_###` | folder path plus repeat ID; series name is primarily filesystem identity |
| WFG | per-channel function, frequency, amplitude, offset, symmetry, phase, run/wait/repeat/trigger | `config_wfg()` applies carrier and optional FM node; frequency scan substitutes CH0 per repeat | requested fields, out-of-range flag, and effective fields are saved; disabled carriers now have blank effective fields |
| Frequency scan | start/stop/count or Python step-size alternative | one CH0 frequency per repeat; list length must equal repeats | each repeat's WFG frequency is saved |
| FM | sweep enable and center/width/time/type | CH0 FM node runs within a repeat; FM forces CH0 carrier enabled | FM fields and FM-node fields are saved |
| DIO/camera start | camera FPS, fixed or dynamic start, frames | enabled DIO1 uses FPS, `sec_wait`, and `frames/FPS`; camera remains automated `Internal` trigger | `DORun`, `DOWait`, `DOFreq`, `DOFreqActual`, and camera trigger fields are saved; camera frame count/FPS are now explicit metadata |
| Camera | experiment exposure, frames, trigger/default sequence fields | Application applies exposure, sequence, global exposure, starts capture, reads frames, stops capture | `ExposureTime` is the applied exposure returned by the backend; sequence and ROI/readout fields are saved; preview/display state remains separate |
| TEC | locked scalar or unlocked channel targets | outer temperature series applies targets through Application before each group | requested targets, enabled/simulated flags, and runtime status are distinguishable; physical temperature remains separate |
| Fluidics | flush volume/rate/wait and syringe capacity | Application validates capacity/fill and performs flush only when enabled devices permit | requested flush fields and final `FlushCompleted`; physical valve route remains unverified |
| Devices | enabled/simulated selections | Application snapshots live facade state and skips disabled device actions | `Sim*` and `*Enabled` fields distinguish simulation from disabled state |
| Z | Manual Focus fields and separate Z-Scan fields | Manual Focus/Z-Scan use the Application-owned stage; automated Experiment2 has no Z motion field | no Manual Focus state is placed in Experiment2 metadata |

## Blocking and live-feasibility boundary

Shared preflight currently checks frequency-list/repeat compatibility, positive
camera FPS, dynamic camera-start slot count, and reports output-path,
simulation, fluidics, and timing warnings. The legacy builder performs the
same blocking frequency-list and dynamic-slot checks before creating the plan.
The shared result is not authoritative and does not attempt to fake live
device capability.

Later Application checks remain authoritative for live/applied feasibility,
including camera ROI/property writes, readout/FPS budget, backend range
clamping, device availability, flush capacity/fill, cleanup, and TEC/device
state. This asymmetry is intentional and is a reason not to cut over
`BuildResult` yet.

| Check class | Offline/shared result | Later runtime |
| --- | --- | --- |
| Static request shape | repeats, frequency-list mapping, positive FPS, dynamic slot count | repeated defensively where required by UI builder |
| Device capability | not fabricated offline | DCAM ROI/exposure/readout and AD2 live ranges |
| Applied feasibility | warning or unknown where appropriate | actual backend return/readback, clamping, cleanup, and failure status |
| Physical truth | explicitly unverified, especially DIO1/camera timing and valve route | never inferred from software timestamps or protocol alone |

## TDMS and partial-run audit

`Experiment2.create_folder_and_tdms()` writes an initial requested record before
configuration. Subsequent saves capture WFG effective/clamping state, applied
camera exposure, DO achieved frequency, camera sequence data, flush result,
and image/timestamp data. Simulation and enabled state are captured from live
facades at run time.

Round-2 identified missing explicit run identity and terminal outcome truth as
**RECOMMEND** items. The subsequent bounded Experiment Record Completeness
closure added per-repeat identity and `IN_PROGRESS`/`COMPLETED`/`FAILED` TDMS
outcomes with separate primary/cleanup failure fields. A series-level manifest
for never-started repeats remains a separate recommendation; see
`experiment_record_completeness_closure_20260901.md`.

## Abort and ownership findings

Abort remains graceful: the current repeat completes, plain series stop between
repeats, and TEC series stop before the next temperature point. It is not an
emergency stop. Manual Camera preview conversion/reprocess is display-only and
does not alter saved raw experiment frames. Manual Focus state is not included
in automated experiment configuration; Z-Scan remains separate and uses the
configured Application-owned stage.

## Findings and actions

### AUTO_FIX — P1 metadata truthfulness

- Added explicit `CameraFrames` and `CameraFPS` TDMS properties.
- Effective WFG carrier fields are now blank when the carrier is disabled,
  preventing retained inactive values from being labeled effective.
- Added deterministic regression coverage for both cases.

### RECOMMEND

- Decide whether a series-level manifest should record requested versus
  completed repeat counts when graceful Abort or a failure leaves later repeats
  unstarted.
- Broaden semantic comparison coverage before any planning-authority change.

### OWNER_DECISION — BuildResult authority

**NO-GO.** BuildResult still wraps legacy-produced objects; v1/v2 execute the
legacy path; live camera/device feasibility remains later; metadata is not yet
generated from one shared semantic plan; and rollback/cutover evidence is not
complete. A separate owner decision is required for any authority change.

### HARDWARE_EVIDENCE_REQUIRED

Physical DIO1/W1/camera TIMING 1 relationship, camera exposure causality, and
repeatability remain unverified. No physical claim may be made from host or
camera timestamps alone. Valve routing and other existing hardware blockers
remain unchanged.

### NO_ACTION

No P3 cleanup, architecture redesign, VISA/SCPI integration, BuildResult
cutover, timing-code change, or hardware work was performed.

## INDEPENDENT REVIEW DISPOSITION

The independent Claude Code v3 report was treated as a candidate-finding set.
Its severity labels were not adopted without checking current code and final
rendered state.

| Finding | Verified? | Current impact | Correct classification | Action taken | Reason |
| --- | --- | --- | --- | --- | --- |
| `_experiment_temperature_group()` is an omitted no-super v3 override | Yes — current AST/change-surface evidence confirms it | Future v1 TEC-builder additions do not propagate automatically | AUTO_FIX | Corrected the stale completeness note in `docs/known_open_items.md` | The method is a live v3 replacement and must remain an explicit review boundary |
| `exp_tec_scan_enable` bypasses shared tooltip wrapping | Yes — it was added directly to the v3 layout while other tooltip-bearing fields use the shared wrapper/helper | Native Windows hover can show the long tooltip without the established forced-wrap convention | AUTO_FIX | Wrapped the checkbox with `_wrap_with_tooltip_icon()` | Restores the repository-wide convention without one-off formatting |
| `_refresh_v3_relationships()` warning text is overwritten by shared rendering | Yes — the local `setText`/style call is followed immediately by `_render_v3_shared_preflight()` | The local warning presentation is dead; final text/style come from shared preflight | NO_ACTION | Preserved the local relationship calculation and recorded the final-render fact | Shared preflight covers the same blocking relationships and additional checks; deleting presentation logic is not needed to keep BuildResult shadow-only |
| Start presentation implies shared validation gates execution | Yes — prior tooltip said “after shared validation,” while the handler always calls inherited Start | UI wording falsely implied shared-preflight authority | AUTO_FIX | Tooltip now explicitly says shared preflight is shadow-only and inherited Start remains authoritative | Corrects presentation without changing execution authority |
| Fresh/default construction shows blocking red state because Camera FPS is zero | Yes — the default is `0.0`, shared preflight reports `camera_fps` as blocking, and final rendering colors the review red | The request is semantically invalid if started immediately, but “not configured yet” is not separately modeled | RECOMMEND | Recorded; no touched/dirty-state framework or severity redesign added | Red accurately reflects the invalid attempted request; fresh-form presentation needs an owner decision if changed |
| Final blocking/advisory severity is inconsistent for conditions that reject Start | Partly — final rendered severity is determined by `_render_v3_shared_preflight()`, while legacy Start remains authoritative | Shared red/orange severity describes the shadow result, not an execution gate | OWNER_DECISION | No color/alarm architecture change | Normalizing severity would conflate shadow analysis with current legacy authority |
| Review rendering can duplicate terminal punctuation | Yes — shared issue messages already end in periods and the renderer appended another period | Final review could display `..` | AUTO_FIX | Renderer now strips trailing periods before joining and appending one terminal period | Pure presentation correction with no semantic change |
| Z-Scan reassurance wording differs from v1 | Yes — wording differs; behavior uses the Application-owned configured stage contract | No remaining concrete safety ambiguity after the stage-identity fix | NO_ACTION | None | P3 wording difference only; no hardware or stage behavior was changed |
