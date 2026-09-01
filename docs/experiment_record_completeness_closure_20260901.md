# Experiment Record Completeness & BuildResult Equivalence Closure

Date: 2026-09-01. Scope: bounded offline closure following Autonomous Sweep
Round 2; no hardware access or output occurred.

## Record truth contract

Each repeat that successfully creates `data.tdms` now starts as
`RecordOutcome=IN_PROGRESS` and is finalized as `COMPLETED` or `FAILED`.
`PrimaryFailure` and `CleanupFailure` are separate fields. Requested settings
remain requested evidence on failure; they are not relabelled as applied.

The initial TDMS-create failure is necessarily not represented in that TDMS
file because no durable record exists. It remains a runtime failure and is a
live-filesystem boundary, not a successful or partial saved record.

| Concern | Source/requested | Planned/effective | Applied/observed evidence | TDMS fields and timing | Partial-failure behavior |
| --- | --- | --- | --- | --- | --- |
| Series/output identity | UI `series_path` | legacy builder creates repeat/temperature folders | filesystem creation is observed only when TDMS creation succeeds | `OutputRoot`, `ExperimentFolder`, `TDMSPath`, initial settings write | Existing record remains `FAILED`; no record exists if initial creation fails |
| Repeat identity | UI repeats | `repeat_id`, planned repeat count | completed only after workflow reaches save/finalize | `RepeatIndex`, `RepeatNumber`, `RequestedRepeatCount`; finalized after execution | planned count never claims completed count |
| TEC axis | requested targets/lock state | target per temperature group | TEC protocol/stability remains runtime evidence | `TemperaturePointIndex`, `TECTarget*`, enabled/simulation snapshot | targets remain requested if failure occurs before/while applying |
| WFG/function/carrier | experiment controls | per-repeat WFG config; scan substitutes Ch1 frequency | post-config range/clamp snapshot when AD2 config returns | `WFG*` requested/effective fields; re-saved after AD2 configuration | requested fields remain; no applied claim if config raises |
| Frequency scan/FM | UI selection | scan value per repeat; FM node only when applicable | AD2 effective configuration only after config | `FrequencyScanSelectedHz`, WFG/FM fields | selected frequency is planned, not proof of output |
| DIO/camera start | FPS, frames, fixed/dynamic start | DIO1 `sec_wait`, `sec_run`, requested selected start | `DOFreqActual` after AD2 configuration | `CameraFrames`, `CameraFPS`, `CameraStartMode`, `CameraStartRequested`, `DOWait`, `DORun` | no applied camera/AD2 implication before their steps complete |
| Camera exposure/trigger | requested experiment overrides/defaults | deterministic Internal trigger and requested exposure | returned applied exposure, sequence/readout data, frame timestamps when driver supplies them | requested settings first; exposure re-saved after camera configuration; image/camera data after save step | request remains distinct; record is `FAILED` if later step fails |
| Fluidics | flush request/settings | flush selected only when enabled devices permit | `FlushCompleted` only after attempt | flush settings initial; `FlushCompleted` after flush attempt | `FAILED` with primary failure on failed flush |
| Simulation/device state | live facade enabled/simulated flags | runtime skips disabled paths | live snapshot immediately before settings write | `Sim*`, `*Enabled` | records actual runtime mode, not a physical-ready claim |
| Completion/outcome | none | workflow terminal state | finalizer after legacy workflow returns/raises | `RecordOutcome`, `RecordFinalized`, `PrimaryFailure`, `CleanupFailure` | no incomplete record can appear as completed |

## Lifecycle findings

- Normal repeat: final TDMS outcome is `COMPLETED` only after save-results
  completes.
- Graceful Abort: a started repeat completes normally; later repeats are not
  started. There is no series-manifest file for never-started repeats, so the
  planned-versus-completed series aggregate remains a follow-up item.
- Failure before or during configuration: the initial requested record is
  finalized `FAILED`; no requested setting is promoted to applied evidence.
- Capture cleanup failure: stored separately in `CleanupFailure`.
- Application-wide cleanup after a UI/session shutdown is not currently tied
  back into each completed repeat record; do not infer its success from a
  `COMPLETED` workflow record.

## Legacy / shared equivalence and validation boundary

`BuildResult` still wraps objects created by the legacy builder. Normalized
comparisons cover fixed/dynamic camera start, frequency scan, FM, flush, TEC
locked/unlocked groups, device modes, and DC. The DC case found and corrected a
shared-only false blocking condition: legacy intentionally ignores frequency
scan/FM for DC, so shared preflight now reports them as non-blocking inactive
selections rather than a frequency/repeat blocker.

| Check | Shared shadow | Legacy builder | Later runtime |
| --- | --- | --- | --- |
| Frequency/repeat mismatch | blocking when scan is effective | blocks during series build | not reached |
| DC with scan/FM selected | non-blocking inactive-selection warning | ignores scan/FM | AD2 configuration remains later |
| Camera FPS/dynamic slots | shared blocking result | builder rejects | camera timing/readout budget remains runtime |
| TEC target syntax/range | builder-derived blocking result | builder rejects | setpoint/stability is runtime/live |
| Disabled subsystem | advisory runtime-mode description | path is skipped as applicable | actual device availability/action result |
| Flush capacity/fill | advisory from planned/cached values | later flush validates | live pump/valve behavior and route remain later |
| Output path | writeability advisory | builder permits | filesystem/TDMS creation proves or fails |

## Live-feasibility boundary

Static request validation includes series shape, effective frequency/repeat
compatibility, positive FPS, dynamic start slots, and TEC text parsing.
Cached/known capability includes tracked pump fill and enabled/simulated state.
Live device feasibility includes AD2 range/divider effects, DCAM property and
readout constraints, device availability, flush execution, and TEC stability.
Physical verification includes DIO1/camera timing, valve routing, and all
hardware evidence; `HW-TIMING-001` remains deferred.

## BuildResult authority reassessment

**NO-GO.** The normalized equivalence coverage is stronger and record outcome
truth is now explicit, but shared planning still depends on legacy-created
objects, v1/v2 consume only the legacy builder, no series-level completion
manifest records unstarted repeats, and live feasibility remains outside the
offline result. The smallest next blockers are a single independently-built
plan source with rollback coverage, v1/v2 adoption, and a bounded series
outcome/manifest decision. No authority cutover was performed.
