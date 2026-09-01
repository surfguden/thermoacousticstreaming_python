# Lessons learned — thermoacousticstreaming_python

Project: `C:\git\thermoacousticstreaming_python` (`junjiebranch`). This is
project-specific institutional memory for the Python conversion of the
thermoacoustic streaming experiment, including its AD2/WFG, Hamamatsu DCAM,
Qmix, valve, TEC, and v1/v2/v3 UI paths. It is not a replacement for
`AGENTS.md`, `docs/project_control.md`, the hardware truth records, or the
known-open-items register.

Each entry records the current enforcement location. A classification of
`HISTORICAL_ONLY` means the lesson is retained for judgment and is not itself
an automated control.

## Lessons from this repository

### Fresh repository truth outranks stale conversation

Several maintenance passes found that earlier conversational claims no longer
matched the checkout. In particular, v3's role changed during the tracked
history: it became an opt-in tracked UI while v1 remained the default and v2 a
rollback/reference surface. The repository reconciled this in commit `da4a790`
and `docs/v1_downgrade_assessment.md`. Current branch state, tests, CI, and
retained evidence must therefore be re-read before acting on an old task
summary.

Enforcement: `PROJECT_CONTROL` (`docs/project_control.md`) and
`HISTORICAL_ONLY` (the assessment/history).

### Injected fake WaveForms objects must exercise the vendor-loader boundary

Commit `ba25e27` fixed a real offline-test defect: `WaveFormsBackend(dwf=fake)`
still resolved/loaded `dwf.dll` before the injected object was useful. The
failure was exposed by clean GitHub offline CI rather than by a local test that
only asserted the fake's later calls. Constructor injection is only a complete
offline seam when vendor-library discovery is bypassed and that behavior is
tested directly.

Enforcement: `TEST` (`tests/test_application.py`) and `CI`
(`.github/workflows/offline-ci.yml`).

### Deterministic behavior is stronger than wall-clock scheduling assertions

The serial regression once relied on a timeout-duration/wall-clock assertion.
That produced a false CI failure because scheduler timing was not the behavior
under test. Commit `525894f` replaced it with a fake port that raises exactly
when the old implementation enters the blocking branch, proving the protocol
terminator is consumed without waiting. Time budgets remain useful evidence;
they are not a substitute for a deterministic behavioral seam in offline CI.

Enforcement: `TEST` and `CI`.

### Protocol success is not physical verification

The valve status handshake and Qmix open/start/stop/close lifecycle provide
protocol or transport evidence, not proof of tubing routing, fluid movement,
fault-free readiness, or safe motion. The 2026-08-28 Qmix record showed three
clean no-motion lifecycle trials while `fault=True` remained in all three.
Likewise, a valid TEC response is not evidence that a target was applied.

Enforcement: `PROJECT_CONTROL` and retained hardware truth records; final
classification of a physical claim requires `HUMAN_JUDGMENT` at the bench.

### Camera visibility does not establish camera timing

On 2026-08-28, Windows PnP, the vendor sample, and the repository backend all
identified camera `C15440-20UP`, S/N `500478`, and a read-only open/close
succeeded. A separate read-only query found `TIMING 1/2/3` fixed LOW. This
removed the visibility blocker but did not establish exposure timing or DIO1
relationship. Scope wiring, load/grounding, and any temporary exposure-output
configuration remain operator-confirmed prerequisites.

Enforcement: `PROJECT_CONTROL`, `HUMAN_JUDGMENT`, and manual-only
`hardware_tests/` gates.

### TEC read-only state and Static OFF are different evidence classes

The earlier read-only TEC observation found both channels already OFF. The
later authorized 2026-08-28 Static-OFF check used the shared path to write only
parameter 2010 = 0, read both channels back OFF, and close cleanly. The first
is observation; the second is a narrowly authorized applied-operation result.
Do not merge these into a broad claim about target, PID, calibration, or
persistence behavior.

Enforcement: `PROJECT_CONTROL`, `TEST`, and retained TEC truth records.

### Shared UI inheritance makes small changes cross-surface changes

v2 and v3 inherit shared widget state and WFG builders but replace layout
builders and selectively override panels. The v3 history records a real loss of
the Qmix fault-clear affordance when a panel was rebuilt. The current v1/v2/v3
tests and `tools/audit_change_surface.py` exist because a change that looks like
presentation in v1 can bypass or remove behavior in v2/v3.

Enforcement: `TEST`, `TOOL`, and `HUMAN_JUDGMENT` for shared-boundary review.

### Dynamic project facts belong in project control, not durable agent rules

Commit `da4a790` moved current milestone, UI roles, CI state, and hardware
status out of `AGENTS.md` into `docs/project_control.md`. Durable repository
working boundaries remain in `AGENTS.md`; facts that change as evidence arrives
belong in the project-control dashboard and truth records.

Enforcement: `RULE` and `PROJECT_CONTROL`.

### Diagnostic configuration is not automatically scientific production

The prepared timing procedure uses the production orchestration path but a
small diagnostic configuration (for example, a low-amplitude bounded waveform,
limited frames, and explicit scope traces). That distinction must remain in the
record: execution can be `PRODUCTION` while configuration basis is
`DIAGNOSTIC`. A diagnostic result must not be reported as validation of the
normal scientific configuration.

Enforcement: `PROJECT_CONTROL` and retained evidence metadata.

### A single bounded timing capture proves only that capture's relationship

One safe scope capture can establish the observed ordering and timing
relationship among the configured signals for that capture. It cannot by itself
characterize repeatability, jitter, or population-level performance. Those are
separate follow-up questions and must not be silently added to the first
closure claim.

Enforcement: `PROJECT_CONTROL` and `HUMAN_JUDGMENT`.

### WFG parameters have presentation, stored, and effective-output states

The September 2026 offline WFG milestone confirmed that the six exposed
functions are DC, Sine, Square, Triangle, RampUp, and RampDown. Digilent DC
semantics make Offset the DC level; frequency, amplitude, symmetry, and phase
are irrelevant. The shared policy now disables and labels those controls,
preserves their stored values for Sine → DC → Sine switching, prevents
frequency-derived scan/sweep use for DC, and makes backend writes conditional.
The effective metadata is recorded separately from retained requested fields.

Enforcement: `TEST` and `CI`; policy in `src/thermo_acoustic/ad2.py` and
backend boundary in `src/thermo_acoustic/waveforms.py`.

### Wheel safety must be enforced at the widget event boundary

The repeated mouse-wheel regression was not fixed by focus policy: Qt delivers
wheel input to the widget under the pointer, and the old app-wide guard allowed
focused numeric controls through to native `stepUp`/`stepDown` handling. The
shared numeric factories now create wheel-safe spinbox subclasses, and the
existing intent for parameter selectors is applied to combo boxes too. Direct
wheel-event tests cover focused/unfocused controls, keyboard editing, v1/v2/v3
surfaces, and dynamically built fields.

Enforcement: `TEST`, `CI`, and shared implementation in `qt_ui.py`.

## Deliberately not adopted

No lesson was copied from a sibling repository, and no sibling-project naming,
hardware assumptions, timing thresholds, or governance convention was adopted
without local evidence. This document does not promote generic best practices,
add another rule taxonomy, or treat another project's camera, pump, valve, or
WFG semantics as applicable here.
