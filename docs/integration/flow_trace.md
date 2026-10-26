# End-to-end experiment flow

Current control behaviour: `aa5f3d1`. This is a source-derived map of the active
call paths, with selected existing test pointers. It does not claim that every
line has a separate test or that software event order measures physical timing.
See `acceptance_table.md` for inherited hardware evidence and current acceptance.

## Definition and dispatch

1. Fixed-form controls compile through `compile_simple_series()`; the builder/console
   can load a schema-v1 definition. `validate_definition()` checks structure, resource
   combinations and deterministic expansion.
2. `ExperimentManager.queue()` allocates a series folder and records the definition,
   planned experiment manifest and run identity. `update_queued()` edits the plan while
   retaining identity. Existing profile loading changes inputs, not devices.
3. Operator-requested camera-count and batch-syringe preflights are separate checks.
   Start's current real-mode confirmation/capacity rules are in `start()`; neither a
   count result nor a green UI indicator measures physical DIO0 edge accuracy.
4. Normal device requests share the controller's active lane. A flush has its own
   pump/valve ownership; unrelated work may proceed. Urgent requests bypass the normal
   queue but cannot interrupt a blocking call in the worker. TEC observations have
   a separate request path. Do not call this unrestricted parallel device dispatch.

## Before the first fluidic action

5. `_require_devices()` checks resources across the expanded tree, including closed
   loop for a requested Z move. It does not enable closed loop on the operator's behalf.
6. Pump status/fill is refreshed and `_check_capacity()` sums all flush nodes per unit.
   It also estimates disk and memory. Simulated initial fill is not a real-pump default.
7. `_after_camera_timing()` records the pre-series camera state and applies only checks
   independent of that old configuration. It must not reject a new ROI/exposure based
   on the old ROI's minimum interval.
8. `_configure_all_before_fluidics()` applies every unique camera/AD2 configuration,
   then checks the camera's corresponding timing and applied exposure against AD2's
   achieved cadence, plus output bounds. This happens before the initial flush.
9. Where requested, the real-mode count preflight arms the camera and DIO, triggers,
   collects the requested timestamped frames and discards the test images. Analog
   waveform outputs are stopped and LED timing is disabled for this count-only check.

## Series and each experiment

10. The fixed-form compiler emits one initial flush, then temperature/parameter/repeat
    nesting. With temperature enabled it emits a setpoint and either a fixed wait,
    or a stability wait followed by an extra hold. Stability means ready, no reported
    fault, and temperature inside tolerance continuously for the settle time; it does
    not measure the sample's equilibrium. The active wait is `hal/tec.py`, not the
    blocking helper retained in `drivers/tec/controller.py`.
11. Each experiment configures camera ROI/sequence and AD2 waveform/DIO; arms the
    camera, starts waveform then DIO, sends the PC trigger, and collects frames.
    SDK timestamps and host receipt times remain separate clock domains.
12. After collection, preview is requested. Host saving overlaps a branch that waits
    for outputs to report done, stops them and flushes. The next experiment requires
    both branches to finish. A configuration result or software trigger does not by
    itself establish an electrical or optical waveform.

## Flush and failure

`FlushWorkflow` commands valve open, waits for the requested ready/position state,
reads fill level, validates the reading/target, starts the pump, polls for completion,
then closes/confirms the valve and performs the configured waits. Recovery requests
pump stop, confirms idle and attempts valve close. This ordering matters: a rejected
pump target is not a promise that no valve command was issued earlier in that flush.

`save_frames()` publishes a complete acquisition folder by rename. The experiment
is finalized after its remaining steps. A later failure preserves already-saved
images and adds the failure outcome; an incomplete acquisition remains discarded.
Failure completion waits for save callbacks, active flush recovery and temperature
record draining. This is different from automatic retry or crash recovery, neither
of which is implemented.

## Stop and exit

- Stop-after-current completes the current experiment, including save/flush, then stops.
- Abort stops later dispatch, cancels a TEC stability wait, requests output stops and
  drains existing save/flush recovery. Cancelling the TEC wait leaves regulation on.
- Panic requests connected output stops and cancels dispatch; it does not command a
  valve or Z position move. During a flush the current terminal label can be failed
  with `Cancelled by Panic` rather than aborted (known classification difference).
- Window close drains a running batch through Abort, then each worker cancels its
  deferred operation, attempts SAFE_STOP and disconnects. All workers are signalled
  before waiting against the shared deadline. Stop/cancel/cleanup errors are read
  from the worker result after its thread ends.
- Pending threads retain their owner and keep the window open; after shutdown starts,
  Panic reports pending/errors rather than queuing another stop. No thread is forcibly
  terminated. The mechanism cannot interrupt a blocked SDK call.

## Selected verification pointers

| Claim | Existing evidence |
|---|---|
| Panel temperature ordering / hold | `test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order` |
| Flush sum at different placements | `test_flush_budget_sums_a_series_level_only_flush`, `test_flush_budget_sums_a_per_repeat_only_flush_across_two_repeats`, `test_flush_budget_sums_a_mixed_series_and_per_repeat_placement` |
| Every applied scan configuration checked | `tests/test_camera_timing_check.py` |
| Save/flush rendezvous | `test_parallel_barrier_blocks_next_experiment_until_save_completes`, `test_parallel_barrier_blocks_next_experiment_until_flush_completes` |
| Saved data survives later failure, both callback orders | `test_images_already_saved_survive_a_later_flush_failure` and its racing-save-callback case |
| Active abort, exit errors and pending workers | `tests/test_abort_and_close.py` (including subprocess cases) |
| Identity survives queued edits | `test_editing_a_queued_series_keeps_its_run_identity_and_applies_the_edit` |

These are pointers to prior offline tests, not a report of a new execution in this
text revision. Retained hardware records have their own scope and must not be
silently equated with either no hardware evidence or a new full integration bench run.
