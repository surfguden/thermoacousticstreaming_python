# Integration known open items

No item here authorizes a code change by itself. Each item names where it
came from and what would close it. Categories borrowed loosely from
junjiebranch's own `known_open_items.md` (not copied verbatim — remapped to
this branch's actual files).

## Minimal real-hardware verification plan — PLAN ONLY, not executed

Per explicit instruction: no hardware was connected or operated to produce
this; it names what each stage would do, so authorization and execution can
happen separately, later, with this as the starting checklist. Each stage
only proceeds once the one before it is confirmed. Every action stays
inside the existing `hardware_tests/` manual-only, confirm-token-gated
convention — nothing here proposes a new access path.

### Stage 1 — single-device necessary actions only

- **Pump**: connect, read status/fill level (no motion). Expected: a real
  fill level and fault state come back; no `-513`-style SDK rejection on a
  plain read. Stop condition: any fault or disconnect — do not proceed to
  Stage 2 until a clean connect+read is observed.
- **Valve**: connect on its real COM port, query status, command one
  position change (P01 or P02), confirm the status reply matches. Expected:
  the same `01`/`02`/`**` token sequence already observed in the pre-existing
  2026-09-25 log (see `investigation_log.md`). Stop condition: no reply, or
  a reply that doesn't match the requested position.
- **TEC**: connect, read-only status (current/target temperature, output
  enable, ready) — no setpoint write yet. Expected: plausible current
  temperature, `output_stage_static_on` matching whatever state the device
  was already in. Stop condition: any read error or an implausible reading
  (e.g. far outside a sane lab range). Note: junjiebranch's
  `docs/tec_verification_matrix.md` has independently-retained real
  evidence of exactly this read-only shape (2026-08-28: real Device
  Status/Object Temperature/Output Enable reads, both channels plausible)
  plus one real write limited to Output Enable=0 (Static OFF) — the same
  `_PyMeComTecClient` class (ported into this branch's
  `drivers/tec/controller.py`) was used for it. This stage would be this
  branch's own first real TEC I/O, not a new kind of operation —
  real setpoint writes (parameter 3000) remain unauthorized/unverified on
  both branches, which is why this stage still stops short of one.
- **Camera**: connect, read capabilities/current settings — no capture.
- **AD2**: connect, read capabilities — no output. Note: real single-channel
  WFG output (configure a carrier, arm, PC-trigger, run a bounded duration,
  read back, clean up) already has real-hardware evidence on the production
  `AnalogDiscovery2` class — see the AD2 row in `acceptance_table.md`. This
  stage stays read-only anyway so it lines up with the other single-device
  checks here; it is not re-proving something already unproven.
- **Z-stage**: connect, read the closed-loop confirmation requirement only
  — do not enable closed-loop or move. This is not pending any decision:
  the confirmation-gate design question is already decided (single-gate
  design kept as-is — see "Decided this round" below). **Z motion itself is
  not an open question** — junjiebranch's real PPC001 + C15440-20UP scan
  succeeded (Session 48: 6/6 real frames, measured positions within
  0.05-0.18um of target; Session 54: the same scan plus a real mid-scan
  abort, driven through the actual UI buttons, not just the CLI) after a
  real bug was found and fixed (`System.Decimal` not supporting Python's
  `float()` — junjiebranch's `_decimal_to_float()` helper). **That exact
  fix already exists in this branch**:
  `drivers/z_stage/thorlabs_piezo.py`'s `_decimal_to_float()`, used in
  every `Get*()` call site, confirmed by direct code read. What's actually
  unverified is narrower: this branch's own `application/z_stack.py` +
  `hal/z_stage.py` + UI driving that already-fixed, already-proven
  `PiezoStage` class has never itself been run against real hardware —
  a different integration layer around the same lower-level class, not a
  different, unproven physical-motion primitive. Excluded from this stage
  because that specific combination needs its own dedicated check, not
  because real Z motion in general is unproven.

### Stage 2 — pump motion alone, bounded, in isolation (nothing else running)

This branch's own worktree has no recorded real pump motion — the only
real-hardware pump log on file here (`investigation_log.md`'s 2026-09-25
session) is read-only: 8,661 fill-level reads, constant at 1.068 mL, zero
motion commands. **junjiebranch does have real pump motion on record**
(`docs/claude_code_change_log.md` Session 54, Scenario 2, same Qmix SDK
family this branch's `drivers/pump/cetoni.py` is "verified near-identical"
to per `migration_checklist.md`): a real syringe confirmed at `~0.10`ml via
the SDK's own `get_fill_level()`, a request for `0.15`ml correctly
rejected before reaching the SDK (`ValueError`, real readback and real
valve position both unchanged before/after — proving the reject happens
before any real motion, not just that an exception fired), and a request
for `0.05`ml correctly succeeded with a real, measured fill-level drop.
This is the same reject/accept shape this branch's own
`FlushWorkflow` (`target = fill_level_ml - volume_ml; if target < 0:
reject`) implements — so the **general pattern** (trust the real SDK
readback, reject before motion when insufficient, leave device state
untouched on reject) has real-hardware precedent on the same device
family. What is still genuinely new and untested here: this branch's
own `_implausible_reading()` layer (non-finite / exceeds-configured-capacity
checks, added this integration round, not present in junjiebranch's
version) and `HW-PUMP-FILL-GEOMETRY-001`'s underlying SDK question —
neither was exercised by the Session 54 run above. This stage exists to
produce this branch's own first real pump-motion record and to exercise
those two untested pieces specifically, not to re-establish that pump
motion in general works. It is separated from Stage 5's combined
experiment so a motion problem is isolated to the pump alone, not
entangled with TEC/camera/AD2 timing.

**Must be confirmed before running, not assumed:**
- Which physical syringe/unit is addressed by the `unit_index` this
  branch's driver will use, and that unit's actual mounted syringe
  capacity (`max_volume_ml`) as installed right now — not whatever value
  happens to be cached from a prior session.
- That the pump's outlet is either disconnected from the fluidic path or
  connected to a safe-to-discard reservoir for this stage, so a motion
  command cannot push or pull against the real experiment chamber.
- The valve's current physical position (confirmed via its own status
  reply, per Stage 1), since pump motion direction/effect depends on it.

**What to run**: a single, small, reference-move-anchored motion command
(e.g. `PUMP_REFERENCE_MOVE` then one bounded `set_fill_level()` step) —
**no specific volume or flow-rate value is given here**, because no
evidence on file establishes a safe one for the currently-mounted syringe;
whoever runs this stage must set a value from the syringe's actual rated
capacity and the lab's own judgment, not from this document.

**Observation method**: watch `hardware_transactions.log` for the command
round-trip (request → SDK ack, the same log format the 2026-09-25 session
used) *and* visually confirm the plunger/syringe actually moved by the
commanded amount — a successful SDK transaction log is not, by itself,
evidence of real physical motion (this is the same distinction the
`-513` SDK-rejection incident already showed matters: log success and
device truth aren't guaranteed to agree without a direct look).

**Stop condition**: any SDK fault, any visible motion that doesn't match
the commanded direction/amount, or any sign of resistance (binding,
unexpected pressure) — treat as a reason to stop and investigate, not to
retry with a larger command.

### Stage 3 — TEC output alone, bounded, in isolation (nothing else running)

Symmetric reasoning to Stage 2: no real TEC *setpoint* (parameter 3000)
write exists in any log on either branch — junjiebranch's retained
2026-08-28 evidence (cited in Stage 1 above) goes as far as a real
Output Enable=0 (Static OFF) write, not a target-temperature write or
Static ON. This stage produces the first real setpoint write, isolated
from everything else.

**Must be confirmed before running, not assumed:**
- Which physical channel index (1 or 2, per `hal/tec.py`'s `channels`
  parameter) corresponds to which physical TEC/sample location on the
  bench right now — this mapping is not recorded anywhere in the repo and
  must be confirmed by inspection/wiring trace, not guessed.
- The TEC's current actual temperature and `output_stage_static_on` state
  (read in Stage 1) — a setpoint should move from a known, sane starting
  point, not an unknown one.
- Whatever the device/sample's real thermal limits are (safe min/max for
  whatever is mounted) — **not stated here**, because no evidence on file
  establishes them; this must come from the device's own documentation or
  the lab's existing safe-operating knowledge, not from this plan.

**What to run**: one bounded `tec_set` to a single channel, followed by
`tec_wait_stable` with a conservative (not aggressively short)
`max_wait_s` — the point of this stage is to observe a *real* settling
time for the first time, which is exactly the number this plan cannot
supply in advance (see "no invented values" above). **No specific target
temperature or wait duration is given here** for the same reason as
Stage 2's volume.

**Observation method**: an independent temperature reading if one is
available (e.g. a secondary probe or the TEC's own separate sense
channel if it has one) compared against what the driver reports — the
goal is to confirm the driver's reported "stable" actually corresponds to
a real settled temperature, not just that the polling loop returned.
Absent an independent probe, at minimum visually/physically confirm the
TEC feels like it is actively heating/cooling in the expected direction.

**Stop condition**: implausible reading, output enable not reflecting
the commanded state, or no observable physical effect within a
generous multiple of whatever wait was chosen.

### Stage 4 — synchronized acquisition, no fluidics or temperature control

- Configure camera (small ROI, few frames) + AD2 (one channel, short,
  bounded run) exactly as `_configure_all_before_fluidics()` would for a
  minimal experiment. Arm camera, arm AD2, one software trigger, collect.
  Expected: exact requested frame count with every SDK timestamp present
  (the same check `await_frames` already enforces in simulation).
  Observe, if physically accessible: the camera's external-trigger input
  actually responds to AD2's DIO0 edge — this is the one claim in
  `flow_trace.md` marked `[UNVERIFIED ON REAL HARDWARE]`. Stop condition:
  frame/timestamp mismatch, or no observable trigger response.

### Stage 5 — minimal complete experiment (single point, single repeat)

Only after Stages 2 and 3 have each independently produced a clean,
observed result — this stage is the first time pump motion, TEC output,
and acquisition run together, and a problem here should already be
distinguishable from a single-device problem because each device was
separately cleared first.

- One flush (volume/flow rate carried over from whatever Stage 2 showed
  was safe on the actually-mounted syringe — not a new guessed value) →
  one TEC setpoint (channel confirmed in Stage 3, target informed by
  Stage 3's observed real settling behavior) → `tec_wait_stable` with a
  `max_wait_s` consistent with what Stage 3 actually observed (now
  genuinely executable at any value, not just a long one — see this
  file's TEC section) → one acquisition (as Stage 4) → save +
  post-acquisition flush, in parallel, as the engine already does.
  Expected: the same ordering already proven in simulation
  (`flow_trace.md`'s "Leaf actions" section) now holds with one real
  device at each step. Stop condition: any step's device-level result
  disagrees with its simulated counterpart's contract (e.g. the pump
  capacity guard firing on a real implausible reading — confirm it fires
  correctly rather than hoping it doesn't need to).

### Stage 6 — expand to sweep and repeats, only after Stage 5 is clean

- Two repeats of Stage 5's experiment, then (separately) two points of a
  temperature sweep, each still minimal in scope (small volumes, short
  waits, few frames, values carried over from what earlier stages showed
  was safe). Expected: the same whole-series flush-capacity sum,
  parallel-barrier, and stop/abort/panic behaviors already proven in
  simulation, now against real devices for the first time. This is where
  the real device-level consequence of `abort()`/`panic_stop()` (SAFE_STOP
  reaching real hardware, not just a simulated worker) gets its first real
  check.

### What this plan deliberately does not include

Z-stage motion (excluded because this branch's own `z_stack.py`/
`hal/z_stage.py`/UI combination has never itself been run against real
hardware — not because real Z motion is unproven in general: junjiebranch
already has a working real scan, and this branch already carries the exact
fix that made it work; see Stage 1's Z-stage bullet above. Also not
because the confirmation-gate design is undecided; that was already
decided, see below), the
acoustic-chain/AD2-JP4 electrical characterization (`hardware_notes.md` —
needs a powered-down physical inspection first, not a software action), and
anything resembling the original "count preflight" dry-run at larger
scale — this plan stays deliberately smaller than that existing mechanism
until Stage 5 is clean.

## Series-lifecycle persistence — split A/B/C per explicit instruction

**A. Real-time persistence of in-progress state — done, fixed this round
(was not actually done before, despite an earlier claim that it was).**
`record_experiment_started/completed/failed()` previously only incremented
in-memory counters on `SeriesStorage` — they never called `status()`, so
`status.json` was not rewritten between the series' own `status("running")`
call (at `_begin_steps()`) and its next real transition (the final terminal
call). A crash between two experiments would have left `status.json`
showing stale, pre-increment counts, which is exactly the opposite of what
"real-time persistence" is supposed to mean. **Fixed**: each of the three
methods now calls `self.status("running", {})` immediately after
incrementing (`"running"` is correct — these are only ever called while the
series is actively running). **Verified by reading `status.json` from disk
while the series has not yet reached a terminal state**
(`tests/test_simple_series.py::test_lifecycle_counts_are_persisted_before_the_series_ends`),
not only by checking the final file, per explicit instruction. No code path
ever marks an abnormally-ended record as successful: there is no
reconciliation logic at all (see C below), so a "running" record simply
stays "running" — it is never rewritten to "completed" by anything other
than the same process's own `_complete_series()` actually finishing.

**B. Crash state interpretation — documented procedure for manual
inspection, not code, per this round's explicit instruction.** To
determine whether a given `experiment_batch_NNNN/metadata/status.json` on
disk represents a series that is *genuinely still running* or one whose
owning process *died without finishing it*:
1. Check `state`. A terminal value (`completed`, `failed`, `aborted`,
   `stopped_after_current`, `cancelled`, `removed_from_queue`) means the
   series ended and this file is the authoritative final record — nothing
   further to interpret.
2. A non-terminal value (`queued`, `preflight`, `running`) is ambiguous by
   itself: it could be a series genuinely in progress right now, or one
   whose process crashed. Compare `updated_utc` against the current time —
   a `running` record whose `updated_utc` is more than a few polling
   intervals old (this architecture polls/updates frequently during an
   active run) **and** no application process is currently attached to
   that output root is strong evidence of an abandoned run.
3. If abandoned: `experiments_started`/`experiments_completed`/
   `experiments_failed` give the exact counts reached before the process
   died — these are reliable (per A) even though no `finalized_outcome` was
   ever written. Cross-reference `manifest.json` (the planned experiment
   list) and the experiment subfolders actually present on disk (an
   experiment folder only exists once `finalize_experiment()` has written
   its `experiment.json` — see `experiment_runner.py:797-799`) to see
   exactly which repeats/points completed.
4. **Never treat an abandoned non-terminal record as evidence of success or
   failure on its own** — it is evidence only that the record is stale;
   whether the underlying hardware was left in a safe state is a separate,
   unanswered question this procedure does not address.
This procedure is manual (an operator or a support engineer reads the
file), not a UI feature — appropriate for this round's scope.

**C. Automatic resume/reconciliation — explicitly out of scope this
round**, per instruction. Not designed, not stubbed, not implemented. If
wanted later, the starting point is the same options recorded in the prior
draft of this entry: a read-only startup scan surfaced to the operator, or
something more automatic — a UI-surfacing and workflow decision for
you/Codex, not sized or chosen here.

- **Z-stage closed-loop mode switch has no operator confirmation gate; a
  separate motion-authorization gate is absent entirely.** junjiebranch's
  `piezo_zscan.py` `ZScanCalibration` requires two independent, explicit
  confirmations before any Z motion: (1) `confirm_closed_loop_switch` — a
  caller-supplied callback, required because "PiezoStage.connect() only
  ever reads the live mode, it never switches it" (Session 45/46 owner
  decision); refusing to proceed (fail-closed) if no callback is given; and
  (2) `confirm_motion` — a *separate* explicit motion authorization,
  independent of (1), because "ClosedLoop mode alone does not authorize
  piezo movement." On this branch, `hal/z_stage.py:55 enable_closed_loop()`
  calls `self.device.switch_to_closed_loop()` directly, and
  `application/controller.py:229-238`'s handling of
  `Z_STAGE_CLOSED_LOOP_ENABLE` only checks that the confirmation
  *requirement* was read first (`closed_loop_confirmation_required is not
  None`) — it never calls `self.confirm_operation(...)`, unlike
  `PUMP_REFERENCE_MOVE` (`controller.py:239-246`, which does call
  `confirm_operation` with an explicit prompt). This is confirmed
  deliberate, not an oversight: `tests/test_single_process_architecture.py
  :376 test_z_stage_mode_switch_requires_query_and_confirmation` explicitly
  asserts `confirmations == []` after a successful enable. No UI-layer
  confirmation dialog substitutes for this either (`ui/device_panels.py
  :2024-2025`'s "Enable closed loop" button has no confirm prompt). There is
  also no separate motion-authorization gate anywhere for
  `Z_STAGE_POSITION_SET`/`Z_STAGE_POSITION_RELATIVE`.

  **Decided this round: keep the current single-gate design as-is.** You
  and Codex reviewed the three options previously recorded here (add a
  `confirm_operation` call mirroring `PUMP_REFERENCE_MOVE`; add a second,
  independent motion-confirmation gate mirroring junjiebranch's
  `confirm_motion` more precisely; or accept the current design) and chose
  to accept the current design — recorded here as a **documented strategy
  difference from junjiebranch, not an open gap to close**. No code change
  made. If real Z-stage hardware work is ever authorized, this is the
  decision that was made and why (physical risk profile judged acceptable
  with the single closed-loop-state gate); revisit only on new evidence,
  not by rediscovering this same comparison again.

## Open, device/SDK-level (not closeable by software alone)

- **HW-PUMP-FILL-GEOMETRY-001** (origin: junjiebranch, `docs/
  p0_hardware_truth_20260828.md`, `known_open_items.md`): does a Qmix
  syringe-geometry change require a fresh `reference_move()` before
  `read_fill_level()`/`get_fill_level()` is trustworthy, or is this a
  Qmix SDK/driver-level inconsistency independent of reference state?
  Software cannot answer this from logs alone. Still open as of
  junjiebranch HEAD `2528c1c`; not re-investigated this round. The Phase-1
  plan (see `decision_log.md`) adds a software-side plausibility guard
  against the *symptom*, not a resolution of this underlying question.
- **HW-AD2-BNC-001** (origin: junjiebranch docs only, never in code on
  either branch): the AD2 BNC breakout's `JP4`/`JP5` jumpers select a
  49.9-ohm series-source path, not a 50-ohm shunt load — changes real
  output voltage math. Grepped `JP4`/`49.9`/`series-source`/`shunt` across
  `drivers/ad2/analog_discovery.py` and `drivers/ad2/configuration.py` in
  this worktree: zero matches. Undocumented anywhere in this branch's live
  tree. Needs either a restored doc note or a code-level comment before any
  real W1 output work.
- **UI-PUMP-STOP-THREAD-SAFETY-001** (origin: junjiebranch `430893a`): the
  fix for "Stop pump silently no-ops" used a concurrent-dispatch escape
  hatch whose thread-safety was explicitly marked unverified. Not
  applicable to this branch's architecture as-is (ola-branch's
  `execute_urgent()` is a different mechanism), but the underlying question
  — "is it safe to issue a stop command concurrently with an in-flight pump
  motion command" — has not been independently re-asked against this
  branch's `DeviceWorker.execute_urgent()` path.

## Open, software-only (closeable by review/small change)

- **Valve `VALVE_WAIT_READY` return semantics — verified, no operator-visible
  gap found.** The command itself reports `ok=True` even when
  `ValveReadyResult.ready=False` (`hal/valve.py:77-84`), confirmed. But the
  one caller (`ui/device_panels.py:1453`, the manual Valve panel's "Wait
  until ready" button) reads `readback.ready`/`readback.status_note` via
  `update_readback()` (`device_panels.py:1496-1503`), which the same HAL
  handler updates with the true `ready`/`status_note` state regardless of
  the command's own ok/fail framing — so the operator-visible label
  ("Ready: No" + status note) is correct even though the button's own
  success/fail styling would show green. No silent failure reaches the
  operator. **Closed, no change made.**
- **TEC Prepare-tab readback display — resolved, small fix applied.**
  ola-branch's `TecPanel` already separates the two values structurally:
  the input fields (`target`/`target_1`/`target_2`) show the software's
  last successfully-applied setpoint, while the status table's "Target °C"
  column shows the controller's own readback. What was missing was the
  display handling a `None` controller-reported target (a real protocol
  characteristic junjiebranch found) clearly: it rendered the literal
  string `"None"`. Fixed to use the panel's existing "—" convention (same
  as Pump/Valve panels) plus a tooltip on the column header explaining the
  characteristic. Test: `test_tec_table_shows_dash_not_literal_none_for_an_
  unreported_target`.
- **Chronology-ordered Prepare checklist — insufficient evidence to act,
  deferred.** junjiebranch's `lessons_learned.md` §7.1-7.2 records a UX
  principle (order by operator chronology, not subsystem ownership),
  arrived at from real operator feedback on their specific workflow.
  `ui/simple_series_panel.py`'s current group order is Output/acquisition →
  Hardware timing → Ultrasound → Temperature → Camera → Flush. Whether this
  matches *this* lab's actual operating chronology (e.g., should fluidics
  prep happen before temperature/camera setup?) cannot be determined from
  code alone — junjiebranch's own reordering was driven by real operator
  observation, which this round has none of. **Not reordered.** Needs an
  actual operator's input on the real workflow sequence before any change;
  marking this unknown rather than assuming either the current order or a
  reordering is correct.
- **Z-stack algorithm parity** (not UI parity, which is resolved — see
  `decision_log.md`): `application/z_stack.py`'s stepping algorithm has not
  been compared against junjiebranch's `piezo_zscan.py`
  `ZScanCalibration.run()` logic. Only the UI *fields* were compared this
  round. Blocks: any claim that Z-axis is fully at parity.
- **TEC multi-point temperature-scan sequencing** — stale entry, superseded:
  this originally claimed junjiebranch's `TemperatureSeries` (independent
  per-channel targets, tolerance/settle/hold) had no ola-branch equivalent
  and blocked any multi-point TEC capability. That is no longer true.
  Single-channel multi-point scanning (tolerance/settle/hold included) is
  now UI-usable through `SimpleSeriesPanel` — see `migration_checklist.md`.
  What remains genuinely missing is only the UI path for addressing both
  channels from one definition (same or independent per-point targets);
  the engine already supports it, see `acceptance_table.md`'s
  corresponding row. Not a blocker for any current experiment.
- **Post-stability thermal hold — checked, already equivalent, not a
  gap.** junjiebranch's `workflows.py` `TemperatureSeries.post_stable_hold_s`
  is a deliberate extra wait *after* the sensor is confirmed stable (distinct
  from settle time, meant to let the real sample — not just the sensor —
  thermally equilibrate). `application/simple_series.py`'s
  `temperature_wait_s`, applied via a `wait` step placed immediately after
  `tec_wait_stable` in the compiled plan (`compile_simple_series()`, the
  `temperature_wait_for_stability` branch), is the same thing under a
  different name — confirmed by reading both: same position in the
  sequence (after stability confirmation, not instead of it), same stated
  purpose in the surrounding comment. No code change needed.
- **Commissioning-trace / evidence-freshness subsystem — reviewed,
  explicitly not adopted this round.** junjiebranch has a real, UI-wired
  pair of modules (`runtime_truth.py`'s `EvidenceBasis`/`VerificationScope`/
  `RuntimeEvidenceSnapshot` taxonomy, `commissioning_trace.py`'s
  `CommissioningTraceRecorder`, a toggle in `qt_ui_v3.py`) that labels
  preflight findings by how fresh/verified their evidence is and can write
  an optional `commissioning_trace.jsonl` audit file per series. This is a
  real capability, not an abandoned experiment — but it is, in substance,
  an audit/evidence-tracking framework, which this round's own standing
  instruction says not to add ("不新增通用框架、自动恢复、审计体系或推测性保护").
  Not ported. If a real commissioning need for this kind of evidence
  trail comes up later, this is where to look, not a gap to close by
  default.
- **Exit/shutdown runs synchronously on the UI thread — known design
  difference, evidence gathered, not changed.** Simulated-delay run
  (no hardware; each worker's `disconnect_device` patched):
  normal 0.00 s; one worker taking 1.0 s → 1.01 s, no error; one taking
  3.0 s → 2.01 s, `errors=['pump: thread did not terminate']`, thread
  still running afterwards; all six taking 3.0 s → 12.0 s total (the
  loop signals a worker then waits up to 2 s for it before signalling
  the next); a `disconnect_device` that raises → traceback on stderr
  only, `errors=[]` (reported as clean). Also: `MainWindow.closeEvent`
  ignores `shutdown()`'s returned error list and always accepts, so a
  timeout is audited but never shown. Ordering is sound (SAFE_STOP is
  emitted before the shutdown request), so on the normal path hardware is
  stopped first. **Implemented 2026-10-26** (parallel signalling with one shared
  deadline, worker shutdown errors returned, hung workers kept alive and
  reported, `closeEvent` keeps the window open and retries, running batch
  stopped through Abort first): see the "Exit" and "Close" rows of the
  system survey table below.
- **Automated camera runs overwrite the MasterPulse widgets on the manual
  Camera tab — known difference, evidence gathered, not changed.**
  `_camera_args()` builds `CameraSequenceTriggerArgs` without MasterPulse
  fields, so the dataclass defaults (`CONTINUOUS`/`SOFTWARE`/`0.01`/`1`)
  are sent. Correction to the earlier wording ("silently"): `MainWindow`
  forwards every successful command, whatever its source, to
  `panel.apply_successful_command`, so the manual panel *visibly mirrors
  the last-applied values*. Simulated run: manual `burst/external/0.5/7`
  → after one automated series the widgets show `continuous/software/
  0.01/1` and the device holds those; a manual re-acquire would then send
  those defaults. `CameraReadback` has no MasterPulse/trigger fields (the
  per-capture DCAM property dump in `experiment_storage.py:219` does
  record trigger/MasterPulse state in `experiment.json`). Automated
  triggering uses EXTERNAL and is unaffected. Practical impact: an operator
  who tuned MasterPulse for a manual test and then ran a series must
  re-enter it; the panel shows what was applied, so nothing is hidden.
  **Recommendation: keep as is** (do not bind the automated run to manual
  widgets, no new series parameters); the only addition worth making is a
  one-line panel note that a series resets MasterPulse to defaults.

## Z-axis algorithm parity — resolved findings (not reserved)

Compared `piezo_zscan.py`'s `ZScanCalibration.run()`/`_acquire_one()` against
`application/z_stack.py`'s `ZStackRunner`:

- **Position confirmation: ola's is more rigorous, not a regression.**
  junjiebranch moves then sleeps a fixed `settle_delay_ms` with no
  position-convergence check at all ("deliberately not replaced with
  threshold-based confirmation logic," per its own comment). ola's
  `_move_accepted`/`_verify_position`/`_position_read`
  (`application/z_stack.py:216-240`) polls the real position readback
  against `tolerance_um` every 100ms up to `position_timeout_s`, only
  capturing once actually confirmed within tolerance. No action needed.
- **Point parameterization differs by design, not a gap.** junjiebranch
  takes `z_start_um`/`z_end_um`/`step_size_um` (fixed step, variable point
  count, uneven last interval to hit the exact end). ola's `ZStackSettings`
  takes `start_um`/`stop_um`/`points` (fixed point count, even spacing,
  linspace-style — `positions()` at `z_stack.py:49-51`). Both are valid;
  switching would change the scientific meaning of "step size" vs "point
  count," which is a reserved-decision category on its own merits if ever
  requested — not requested here, so left as-is.
- **UI field coverage**: already confirmed a superset in the prior round
  (`ui/z_stack_panel.py` has start/stop/points/step/exposure/ROI/tolerance/
  timeout/manual-jog/live-preview — junjiebranch's tab has start/end/step/
  exposure/output-dir only).

## Explicitly closed this round (do not reopen without new evidence)

- Automated-flow valve confirmation: closed, no gap (see `decision_log.md`).
- Z-axis UI field coverage: closed, no gap (ola's `z_stack_panel.py` is a
  superset of junjiebranch's Z-Scan tab fields).
- Fault-reason message surfacing: closed, no gap (`event_formatting.py`
  already includes `event.message` on every failure).

## System survey 2026-10-25 — status (updated 2026-10-26)

Status: **repro** = reproduced before the change; **fixed** = changed; **verified** = a test
that fails without the change and passes with it (simulation or fake devices only);
**decision** = waiting for you. Evidence tags: [CODE] read in source, [SIM] simulated run /
fake device, [JUNJIE-HW] historical junjie hardware record (not proof for this path).
Nothing here was run on hardware, so none of it is physical verification.

| ID | Finding | Change | Tests | Status |
|---|---|---|---|---|
| S1 | A fault set only by a failed pump poll stayed after polling recovered | `PumpWorker.poll_once` keeps the text of a poll-produced fault and clears it after a successful poll **only if** the fault was not replaced by a command error and no unit reports `is_faulted`. Evidence limit: a healthy read-back proves the same reads work again, not that an underlying device fault is gone; a device-reported fault or a failed command is never cleared by polling | `test_device_workers.py` (3 pump-fault tests) | repro, fixed, verified |
| S2 | After a failed Connect the panel showed ERROR and kept Connect disabled | `DeviceWorker.status()` reports ERROR only for an open device. A failed Connect discards the device object (drivers roll back in `initialize`; a driver whose rollback itself fails says so in the message) and stays DISCONNECTED with the reason in `fault`, so Connect is offered again. Open-but-faulted devices stay ERROR (Disconnect only) | 2 connect tests | repro, fixed, verified |
| S3 | `PumpWorker._move` ignored `flow_rate_ul_min` (always max/2) | A valid explicit flow (0 < flow ≤ unit maximum) reaches the device; 0, negative or above-maximum is refused with a message instead of being clamped by the driver; no flow keeps max/2. `timeout_s`/`poll_interval_s` do not apply: the call returns when the SDK accepted the start (progress comes from polling); not changed to wait for motion | 5 pump-move tests | repro, fixed, verified |
| S4 | No "Recover fault" button on the active pump panel | none | – | decision (deferred) |
| S5 | Snapshot / live preview could wait for an external trigger after a series | `configure_snapshot` writes `TRIGGERSOURCE=INTERNAL` and nothing else (vendor property list gives no evidence that polarity/active/delay/times matter for internal triggering; global exposure is rewritten by each sequence configure). The automated series is unchanged: each experiment's `configure_sequence` still writes EXTERNAL. The same path serves the in-run preview (`CAMERA_CONTINUOUS_CAPTURE`), which therefore becomes truly free-running. Whether the real camera needs more than this is unverified | fake-DCAM `test_driver_fakes.py` (3) | repro (fake DCAM), fixed, verified; **hardware effect not verified** |
| S6 | AD2 safe stop stopped W1/W2, digital and scope in sequence; one failure skipped the rest | `AD2Worker.safe_stop` tries each independently; if the all-channel stop fails it falls back to a new direct `stop_analog_outputs()` (W1/W2 one by one); read-back claims only what stopped; all failures are returned in one error; levels/polarity untouched | 3 tests | repro, fixed, verified |
| S7 | A `stage_move` series with open-loop/unconnected Z ran flush and heating, then failed | `_require_devices` checks connected + closed loop first; never enables closed loop or moves the stage. Before: 17 experiment commands ran before the failure; after: only the failure path's own SAFE_STOP | 2 tests | repro, fixed, verified |
| S8 | Panic during a flush is recorded "failed / Cancelled by Panic" instead of "aborted" | **Investigated, not changed.** Cause [CODE]+[SIM]: `panic_stop` cancels the flush and emits its failed result synchronously, so `ExperimentManager._fail` runs before `panic_abort()`, whose `or self._failed` guard then returns. Effect: the label only (`status.json` says failed with error "Cancelled by Panic"; devices, kept data and Panic's own SAFE_STOPs are the same; the runner also sends AD2/camera SAFE_STOP a second time, harmless). Swapping the calls would change when `_finish_failure_when_safe` sees `controller._flush`, so it needs its own timing test first | – | repro, decision (optional) |
| S9 | Saved data has no software commit, simulated/real mode or TEC applied values | none | – | decision (deferred) |
| S10 | Abort did not cancel a TEC stability wait; lane busy until `max_wait_s` | `ExperimentManager._fail` ends an active TEC wait through the existing `ABORT_ACTIVE` path (the worker's cancel hook leaves regulation on). Before: after abort the TEC command stayed active and an ordinary command waited 6.5 s of a 6 s wait (default 300 s); after: lane free at once, TEC output still on, final state `aborted`, no experiment started, late result ignored (`_command_result` guard) | 1 test | repro, fixed, verified |
| S11 | Valve and TEC ports are not checked against each other | **Reported only.** Both panels list the same `serial.tools.list_ports` devices (canonical names such as `COM5`); the console accepts any text (`connect valve --port COM3`); no COM number is hard-coded in `src`. A second open of an already-open port fails at the OS (pySerial opens exclusively), so a clash fails closed once the first device holds the port. Real risk is selecting the *other* device's port for the first connection: the valve driver then sends `S\r` at 19200 baud and the TEC client sends MeCom frames to a non-TEC device (effect on the foreign device unknown). junjie hard-rejected COM6 for the valve (`7a2ef57`, `a0a2de2`; COM6 = TEC at that time, still current? UNCONFIRMED). If wanted: a "valve port ≠ TEC port" comparison at connect time, no resource manager | – | decision |
| S12 | Driver-level tests were not ported | Added only what this round changed or relies on: fake DCAM (trigger source, failure order), pump worker (flow, faults, connect), AD2 safe stop. Existing tests are not duplicated; junjie's ~150 driver tests were not bulk-ported | `test_device_workers.py`, `test_driver_fakes.py` | partly done |
| S13 | Elapsed / remaining time display | none | – | decision (deferred) |
| Z-stack | Experiment vs Z-stack exclusion | **Existing exclusion works** [SIM]: with a batch running, `z_stack.start` was refused and Z commands were rejected by `controller.submit`; with the stack running, batch start and manual camera/Z commands were refused. Gaps fixed: entry points looked only at runner state `running`, so during `stopping`/`aborting` (flush/save drain) they left the stack in a stray `failed` state (and `start` wrote `metadata.json`). They now refuse up front using the runner's existing active states (`ExperimentManager.batch_active`). Unchanged: starting a batch while a Z live preview is on is allowed and leaves the stack's `preview` label stale (cosmetic) | 2 tests | repro, fixed, verified |
| Close | Closing the real window mid-run | Closing a running batch now reuses Abort ("Application window closed during the run") and its save/flush drain, keeps the window open until the batch has stopped, then closes by itself; `begin_close()` blocks new batch/Z-stack starts. Before (real `MainWindow`, [SIM]): `window.close()` returned in 0.00–0.07 s, devices were disconnected and `status.json` stayed `running` forever in all of capture, save, flush and TEC-wait phases | 3 phases + idle | repro, fixed, verified |
| Exit | Shutdown waits, errors, hung workers | `shutdown()` signals every worker first and waits against one shared deadline (`SHUTDOWN_WAIT_S`, 2 s; before: sequential, 12 s for six hung workers). A `disconnect_device` or cancel exception is kept on the worker and returned as an error (before: traceback on stderr, `errors=[]`). A worker whose thread has not finished is listed in `shutdown_pending_devices()`; it is never terminated and its owner is not destroyed; a later `shutdown()` waits again and the resources (`experiments.close()`, Z stack) close once all threads are done. `closeEvent` shows pending devices / errors in the status bar and the log and stays open (closing again retries; with finished threads and unchanged errors the second attempt is accepted). Before, a worker still running at process exit aborted the process (exit `0xC0000409`); now the window stays open instead (checked in a subprocess). No forced quit, no per-device dialog. Residual: SAFE_STOP failures during shutdown arrive as queued signals and are reported on the next `shutdown()` attempt; if the stop never finishes the window stays open and Panic remains the operator's route | 5 tests incl. subprocess | repro, fixed, verified |

**Current behaviour — original basis — practical effect — recommended policy (unchanged this round; yours to decide, not inferred from software):**

| Item | Current behaviour | Original basis | Practical effect | Recommendation |
|---|---|---|---|---|
| TEC after a run | Output stays on after completion, Stop, Abort and plain failure; Panic and exit switch it off | junjie Checkpoint S (`c58e092`): TEC kept regulating after the app closed, so cleanup now sets Static OFF; `TEC-AFTER-RUN-POLICY-001` records the implicit "keep after run" as an owner decision; `SCI-TEC-EQUIL-001`: controller-stable ≠ imaging-plane equilibrium | Sample stays at temperature for follow-up imaging; nobody is told it is still heating/cooling | Keep; if you want it visible, show "TEC output on" in the run-finished message rather than switching it off |
| Valve on Panic / exit during a flush | Valve holds its position (open if mid-flush); Abort closes it via flush recovery | ola `controller.panic_stop` comment: moving the valve while flow stops may be unsafe | Valve may stay open after Panic until the operator closes it | Keep; the status panel should say the valve position, no automatic move |
| Laser path | W2 driven at a fixed 5 V square, idle at offset | junjie `HW-LASER-PATH-001`: W2 feeds the iBEAM analog input (0…+5 V, default polarity `sub`, 0 V is not optical off); junjie's planner rejects W2 | Installed unit/polarity unconfirmed | No code change; confirm the unit before any real laser run |
| Abort during a TEC wait | Cancels the wait only | `TEC_WAIT_STABLE` cancel hook documents "does not turn regulation off"; `TEC_OUTPUTS_OFF` is the separate action | – | Keep |
