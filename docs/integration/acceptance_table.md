# Integration acceptance table

Experiment-control behaviour baseline: `codex/integration @ aa5f3d1` (2026-10-26).
Windows launchers were subsequently fixed in `168cac4`; text-only revisions do not
change the experiment-control behaviour. The branch starts at
`origin/ola-branch @ 5014fc8f`; `junjiebranch @ 2528c1c4` is an ancestor of that
start point. Acceptance concerns retained behaviour and integration changes,
not whether Git history contains both branch names.

## Reading the evidence

- **Implemented and checked:** a reachable behaviour with named code/tests or a recorded probe.
- **Inherited hardware evidence:** an earlier physical result, with its apparatus, configuration
  and scope retained. No new integration-branch log is required just to reuse applicable evidence.
- **Evidence boundary:** a particular physical quantity or combination not established by the
  available records. This is not automatically a code defect or a prerequisite to repeat all tests.
- **Accepted difference:** intentional behaviour retained for the current workflow.
- **Optional:** considered, but not a default backlog or a condition of acceptance.

The baseline's full offline result is **249 passed, reported by Claude**. Codex independently
ran **227 passed at `62709dd`**, then the relevant **36 tests at `aa5f3d1`**; this is not a claim
that Codex independently ran all 249. This documentation revision adds no new execution evidence.
See `investigation_log.md`, `hardware_notes.md` and `decision_log.md` for investigation sources.

## Current acceptance: operating entries

| Entry | Current execution and completion | Output / failure behaviour | Evidence and boundary |
|---|---|---|---|
| Parameter scan, repeats and flush | UI compiles a definition; all unique camera/AD2 configurations are checked before fluidics. Initial flush once per series, then configure, camera arm, waveform start, DIO start, PC trigger and collect. Save overlaps output completion/flush; both finish before the next experiment. | `metadata/{definition,manifest,status}.json`, events and per-experiment TIFF + JSON. Complete saved acquisitions survive a later failure; incomplete acquisitions are discarded. | `test_simple_series.py`, `test_experiments.py`, `test_workflows.py`, `test_camera_timing_check.py`. Do not describe accepting a command as completing motion. |
| Temperature sequence | Per point: set target; optionally wait for ready and temperature within tolerance continuously for min-settle; then the configured hold and the point's experiments. Fixed-wait mode omits stability waiting. | Optional `temperature.csv`; definition records requested targets and criteria. Experiment `device_readbacks` are snapshots at save dispatch, not end-of-batch readings. The real MeCom client does not re-read target parameter 3000; a missing target must not be presented as measured. | `test_simple_series.py`, `test_abort_and_close.py`. Actual execution is `experiment_runner` -> `TEC_WAIT_STABLE` -> `hal/tec.py`; see the comparison below. |
| Independent Z-stack | Compare the accepted limited target with the request, poll measured position until within tolerance/timeout, then capture each point. | Saved points and `metadata.json` retained on failure. Failure reason is currently UI-only; metadata has no run identity. | `test_z_stack.py` happy path; previous ad hoc simulation checked timeout. This is different from generic `stage_move`, which only accepts a target. |
| Manual preparation and preview | Device panels issue explicit application commands. Active-batch states share a rule; reads and urgent stops remain available. Snapshot/preview establishes internal trigger; sequence configuration establishes external trigger before arming. | Viewer changes display only: manual/fixed limits, one-shot robust stretch, autoscale, Fit/100%, zoom/pan, raw pixel readout and acquisition state. Manual sequence saving remains explicit. | `test_device_ui.py`, `test_device_workers.py`, `test_driver_fakes.py`. Human visual review is not recorded. Robust tail 0.2% per side is a display choice, not calibrated image analysis. |
| Stop, Abort, Panic and exit | Stop finishes the current experiment. Abort stops dispatch, cancels an active TEC wait and permits existing save/flush recovery to drain. Panic requests output stops without scheduling a valve/Z move. Window close uses Abort/drain, then worker cancellation, SAFE_STOP and disconnect. | Series outcome/counters are persisted. A timed-out thread is kept alive with its owner; the window stays open. After shutdown starts, Panic reports pending/errors rather than dispatching another stop. | `test_abort_and_close.py`, including subprocess tests. SDK calls cannot be forcibly interrupted by this mechanism. Physical stop is not inferred solely from thread termination. |

## Inheritance and actual differences

| Area | Earlier resource and usable result | Integration counterpart / accepted difference |
|---|---|---|
| Pump and valve | junjie change-log Sessions 54-56: real flush reject/accept, CR-terminated serial response fix, SDK fill-level synchronisation; Qmix fault/position-sensing gates. | `drivers/pump/cetoni.py`, `drivers/common/serial.py`, valve driver and `FlushWorkflow`. Current per-unit capacity and live fill level are used; raw plausibility guards have offline tests. A geometry/readback anomaly remains a specific SDK question, not evidence that all pump operation is unproven. |
| Acquisition and AD2 | ola supplies the configured/armed/triggered flow and output/save barrier. junjie records applied exposure quantisation and clock-division lessons. Production AD2 driver has retained real WFG captures under `hardware_tests/wfg_dc_sine_idle_test/results/`. | Applied exposure and achieved cadence checked after the corresponding configuration; stale pre-configuration timing no longer rejects a new ROI/exposure. Those WFG records do not by themselves measure DIO0-to-camera edge timing. Session 31's internal-trigger result is not external-trigger timing evidence. |
| TEC client | junjie `tec.py` and `docs/tec_verification_matrix.md`: implemented MeCom client, historical Sessions 75-77 connect/setpoint/convergence claims, separately retained 2026-08-28 read and Static OFF evidence. | Shared parameter mapping and cleanup retained in `drivers/tec/controller.py`. Keep the historical claims and independently retained records distinct; neither erase the former nor call them a new independent bench verification. Historical authorization text does not define new project policy. |
| TEC stability | junjie loop checks errors, ready, tolerance, continuous settle and timeout. | The **active** implementation is the timer/deferred operation in `hal/tec.py`, not the preserved driver's blocking `wait_until_stable()`. Core criteria are retained; scheduling, argument validation and cancellation differ. Cancellation leaves regulation on. A source-identical unused function is not proof of execution equivalence. |
| Z motion | junjie Sessions 48/54: real PPC001 + camera scans, the Decimal conversion fix, and a real abort precedent. | Fix retained; independent Z-stack uses measured-position confirmation rather than the old fixed settle delay. `stage_move` records requested/sent values and `position_confirmed: false`; measured and commanded readback fields are separate. |
| Configuration and operator workflow | Useful junjie display and configuration capabilities, with older source pointers in `investigation_log.md`. | Existing File save/load extended, not replaced by a new framework. Profiles load without device actions; pump selection is preserved across disconnected loads. The viewer selectively adopts fixed range and robust stretching. |

## Checks retained at this baseline

| Requirement | Implementation / evidence |
|---|---|
| Configuration validity and actual timing | `experiments.py` schema; `_configure_all_before_fluidics` applied checks; `test_camera_timing_check.py` plus achieved-rate/exposure regression cases. |
| Whole-series fluid budget and fresh readings | `_check_capacity`, `FlushWorkflow`; placement and implausible-reading tests. No automatic reference move is implied. |
| Saved data and final-state consistency | Save callback/failure ordering tests, parallel barrier tests, temperature-recorder stop/drain tests. |
| Profile load atomicity and unit selection | Type/range rejection and non-default round-trip tests in `test_device_ui.py`; missing pump unit is not silently replaced. |
| Run identity, including queued edits | `manifest.run` stores mode and cached Git identity; `test_run_identity.py` including `update_queued`. Missing Git records unknown and does not block queueing. |
| Stop, recovery and cleanup | TEC cancellation, pump requested flow/poll fault, failed Connect retry, snapshot trigger reset, AD2 independent stop attempts and shutdown-result tests. |
| Real pixel data remains unchanged | Viewer tests cover contrast, fixed range, hot/constant frames and zoom mapping; 100% is one image pixel per physical display pixel, independent of Fit. |

## Current decisions and evidence boundaries

No unresolved code blocker was identified by the checks listed here for the five operating
entries. This is bounded acceptance, not a claim of an exhaustive audit or every physical quantity.

- Applicable historical hardware evidence is reused. Integration additions are checked offline;
  the record does not contain a new complete physical run of this exact code baseline.
- DIO0 edge count/spacing has not been directly measured in the cited evidence. If an experiment
  requires a timing accuracy or physical relation those records do not establish, specify that
  requirement and the smallest necessary check. Do not turn it into a blanket hardware re-test gate.
- The specific laser polarity/unit question remains in `hardware_notes.md`; this revision does
  not settle it or change W2 voltage/idle behaviour. Do not equate 0 V with optical off.
- Current policies remain: TEC output stays on after normal completion/Stop/Abort/general failure;
  Panic and exit request OFF. Panic does not reposition the valve. Normal window close during a
  run instead follows Abort and its flush recovery. Do not repeatedly reopen these as undecided.
- TIFF + JSON stays. Actual external-consumer requirements are not established; an existing
  LabVIEW `analysis.vi` reference is not proof of an active TDMS dependency or of compatibility.
- Incomplete acquisitions are discarded by current policy. Do not justify this as though retaining
  explicitly labelled partial frames were inherently unsafe; changing that policy needs a use case.

## Deferred optional features (not debt)

A useful small candidate is persisting Z-stack failure reason and run identity. Other candidates
are `stage_move` arrival waiting when needed, independent dual-channel TEC UI, extra point-level
progress, recovery-button convenience, elapsed/remaining time and viewer ROI/profile/frame review.
None is required just for parity. No automatic resume, recipe manager or audit framework is planned.

## Verification scope

The preceding documentation pass reported fresh simulated traces, three saved-outcome probes
and Z-stack timeout inspection. Routine tests use simulated/fake devices. Historical hardware
sources retain their own scope. No human visual review, new physical timing measurement or
external-analysis compatibility check is claimed. For current operating steps and recipe
provenance, use `migration_checklist.md`; for remaining items and manual crash inspection,
use `known_open_items.md`.
