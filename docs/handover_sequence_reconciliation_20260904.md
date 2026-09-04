# Handover sequence reconciliation — 2026-09-04

**HISTORICAL / RECONCILIATION EVIDENCE — NOT CURRENT OPERATIONAL AUTHORITY.**

This record preserves the bounded reconciliation of the ingested colleague
timeline and iBEAM manual against current source and current authority. Live
authority remains `AGENTS.md`, current source/tests,
[`project_control.md`](project_control.md), and
[`known_open_items.md`](known_open_items.md).

## Current owner-supplied routing truth

| AD2 path | Current apparatus role | Evidence level |
| --- | --- | --- |
| W1 / API channel 0 | Acoustic chain | OWNER-SUPPLIED CURRENT TRUTH |
| W2 / API channel 1 | Laser Analog In/control path | OWNER-SUPPLIED CURRENT TRUTH |
| DIO0 / pink | Camera `EXT.TRIG` | OWNER-SUPPLIED CURRENT TRUTH |
| DIO1 / green | LED timing/control | OWNER-SUPPLIED CURRENT TRUTH |

The earlier retained DIO1/green -> laser Digital In mapping is superseded
historical project truth. This resolves `DIO1_DEVICE_IDENTITY` for current
authority only. It does not verify timing, latency, voltage compatibility,
optical emission, or physical synchronization.

## CURRENT_IMPLEMENTATION

- Normal production camera behavior is Internal/free-running.
- Production programs neither DIO0 nor DIO1 and clears/disables DigitalOut.
- Current W1 commonly uses `trigsrcNone`; `pc_trigger()` therefore is not a
  current W1-start claim under that trigger source.
- Current repeat execution is sequential: it waits for the programmed AD2
  completion window, performs enabled flush before normal TIFF/TDMS image
  saving, and a flush failure can prevent that normal save step.
- Current TDMS persists `FlushCompleted`; production has no save/flush
  concurrency.

## INTENDED_FUTURE_DESIGN — NOT IMPLEMENTED

The colleague timeline is intended hardware-action-sequence evidence, not a
replacement for the canonical runtime. A high-level candidate is:

```text
preflight -> initial flush if enabled -> configure/arm AD2 -> configure/arm camera
-> one software PC trigger as logical t=0 -> acquire N frames
-> required output-completion safety barrier -> authorized save + refresh-flush
concurrency -> rendezvous -> canonical final evidence/outcome -> next repeat
```

This does not finalize the output-completion barrier, authorize W1/W2 overlap
with flush/save, define a competing planner/executor, or claim physical
simultaneity. Canonical execution remains:

```text
ExperimentRequest -> build_independent_run_plan() -> RunPlan / RunCondition
-> legacy_series_from_run_plan() -> Application -> hardware backends
```

A possible future TDMS ownership shape is hardware-only flush worker ->
structured `FlushResult` -> rendezvous/finalizer writes `FlushCompleted` and
outcome evidence. It is a design candidate, not current behavior.

## PHYSICAL_VERIFICATION_PENDING

Before a synchronized path can be implemented or claimed, source changes,
offline tests, exact camera/API semantics, electrical compatibility, and
authorized physical timing validation are required. No current record proves
DIO edges, camera exposure, LED state, W1 onset, W2 behavior, or optical timing
against a common timebase.

## iBEAM vendor constraints

### VENDOR_VERIFIED_FAMILY_SEMANTICS

- Analog modulation is documented as 0...+5 V and affects channel 2.
- Channel 1 is bias and may remain active independently.
- Documented default analog-modulation configuration is `sub`; increasing
  analog input reduces optical power under that configuration.
- Therefore approximately 0 V is not a generic safe/off assumption.
- A zero-offset bipolar AD2 sine can enter negative voltage outside the
  documented analog-modulation range.
- Digital In exists only with the applicable pulse option, is inactive by
  default, and requires explicit enable semantics such as `en ext`.

### INSTALLED_UNIT_CONFIGURATION_UNKNOWN

The installed option set, modulation polarity/configuration, scaling/trim,
input impedance, and optical emission response remain unknown until directly
confirmed. Electrical command is not optical-power measurement; residual
emission can remain because of bias current. No laser-control implementation is
authorized by this record.
