# BuildResult Independent Plan and Rollback Boundary

Date: 2026-09-01. This is a design checkpoint only. `BuildResult` remains
shadow-only; Start, runtime workflows, hardware access, and metadata formats
are unchanged.

## Current dependency inventory

`MainWindowV3._v3_shadow_build_result()` first creates an `ExperimentRequest`,
then calls the inherited legacy `_build_experiment_series()` or
`_build_temperature_experiment_groups()`. It wraps their `Experiment2` objects
with `run_plan_from_existing_series()` and adds shared preflight afterward.

| Current dependency | Classification | Independent-plan disposition |
| --- | --- | --- |
| Qt widgets and `Application` enabled/simulated flags | UI-owned state | UI adapters must extract them into one shared request DTO |
| `Experiment2`, `ExperimentSeries2`, `TemperatureSeries` | legacy compatibility / derived planning | Must not be constructed inside `BuildResult`; adapter creates them later |
| `WfgConfig`, `DoConfig`, `FlushSettings`, sequence dictionary | pure configuration / derived planning | Independent plan must own immutable semantic equivalents |
| `Path` repeat and temperature folder rules | derived planning | Independent plan owns the identity/condition derivation |
| AD2/camera/TEC/pump/valve instances and runtime evidence snapshot | runtime/backend object | Excluded from plan; snapshot contributes advisory preflight only |
| `Application.run_experiment2()` / `run_temperature_series()` | legacy execution workflow | Retained behind an explicit temporary adapter |

## Minimum independent plan model

`ExperimentPlanRequest` should carry only user-selected static data: output
target, repeats, waveform/channel settings, scan/FM selection, camera request
and starts, flush settings, TEC target matrix, and enabled/simulated modes.

`IndependentRunPlan` should contain:

- `series_identity`: output target, requested groups/repeats, schema version;
- `conditions`: one immutable per-repeat condition with temperature index and
  targets, selected carrier frequency, WFG/FM parameters, DIO request, camera
  request/start, flush request, and subsystem modes;
- static validation results and explicit advisory/live/physical boundaries.

It must not contain device handles, backend instances, mutable camera buffers,
live capability reads, cleanup ownership, or runtime-applied values.

## Temporary adapter and UI migration

Stage A (current): v1/v2 legacy builder executes; v3 observes legacy objects.

Stage B: v1/v2/v3 each use a thin UI-to-`ExperimentPlanRequest` extractor.
One independent constructor returns `BuildResult`; an explicit
`legacy_series_from_independent_plan()` adapter converts conditions to current
`Experiment2`/`ExperimentSeries2` objects. The adapter remains authoritative
for execution while normalized comparisons run in CI.

Stage C (separate milestone): the same adapter output becomes Start input only
after equivalence and rollback criteria are met. No stage in this checkpoint
implements Stage B or C because the current request lacks the complete WFG,
DIO, sequence, and TEC semantic DTO required to avoid a second UI builder.

## Rollback boundary

The future cutover is one authority selection at the Start-to-series boundary:
legacy builder versus `legacy_series_from_independent_plan()`. Runtime,
hardware configuration, TDMS keys, and cleanup remain unchanged. Reverting is
selecting the legacy builder and does not rewrite history, migrate data, or
reconfigure hardware. Required proof: both branches produce the same normalized
conditions, static-blocking result, and legacy-compatible objects for every
covered request.

## Series manifest recommendation

Use a small JSON file beside the output root: `series_manifest.json`. JSON is
already used for repository settings, is readable without TDMS tooling, and
does not duplicate per-repeat configuration. It should contain schema version,
output/series identity, requested/started/completed/failed repeat counts,
requested/started/completed TEC-point counts, graceful-abort flag, final
outcome, and start/end timestamps. Write it at series start and finalization;
leave a crash-interrupted file explicitly `IN_PROGRESS`. This is a separate
checkpoint because current UI series loops own lifecycle and must not be
entangled with planning authority.

## Semantic-equivalence contract before cutover

For the same request, independent and legacy paths must have identical group
and repeat counts, TEC targets/indexes, selected per-repeat frequency, camera
start, WFG effective parameters, FM behavior, DIO request, camera request,
flush request, output/repeat identity, and enabled/simulated modes. Static
blocking validation must agree. Acceptable differences are later live-device
feasibility, applied/clamped values, driver timestamps, physical timing, and
runtime cleanup results, because they cannot be known offline.

## Prototype decision and GO/NO-GO

No constructor prototype was added. A partial constructor would either call the
legacy builders again (not independent) or duplicate incomplete UI semantics;
neither satisfies the stated goal safely. The existing normalized shadow tests
remain the baseline contract.

**NO-GO** for an authority-cutover milestone. The smallest blockers are a
complete immutable request/condition DTO, one independent constructor,
v1/v2 request extractors, adapter equivalence/rollback tests, and the separate
series-manifest lifecycle decision. Live feasibility correctly remains later.
