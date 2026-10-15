# Integration decision log

Append new entries at the top (newest first). Each entry should name the
SHA(s)/file(s)/function(s) the decision rests on, not just a conclusion.

---

## 2026-10-15 — Codex's independent review did not pass final acceptance; five more real defects found and fixed

Per explicit instruction: continue within the same four-item scope, no
new features, no architecture changes. A fifth item (test-suite crash
stability) was also in scope this round. Summary only -- full detail in
each fix's own commit message.

1. **Save-vs-failure race, ordering B**: the prior fix for "data
   preservation on a later failure" checked `future.done()` per future,
   not whether `self._file_futures` was genuinely empty. A save Future
   can finish on its background thread before `_save_frames()`'s own
   poll() callback (the only code that sets
   `self._experiment_frames_saved` and removes the future from that set)
   has actually run. A failure injected in exactly that gap read the
   still-`False` flag and deleted real data. Fixed by checking
   `bool(self._file_futures)` instead. The previous test only exercised
   ordering A (poll already ran); a new, deterministically-constructed
   test (eager-blocking submit + a wrapped `_save_frames()` that injects
   the failure in the exact gap, not by waiting for a flag) exercises
   ordering B specifically. Reverting either check independently
   reproduces the corresponding failure.
2. **Stale completion callback after panic/abort during a temperature-log
   drain wait**: `_complete_series()`'s (and `stop_after_current`'s)
   deferred completion callback had no way to notice that
   `panic_abort()`/`abort()`/a failure had finalized the batch while its
   own recorder-drain wait was still pending -- it unconditionally wrote
   "completed"/"stopped_after_current" to disk once the recorder
   eventually drained, regardless of what had happened to the batch in
   the meantime, leaving disk and memory disagreeing. Fixed with a guard
   at the top of both callbacks: bail out if `self._failed` or
   `self._abort_requested` is already true. New test constructs the race
   deterministically (stubs `recorder.drained()` to stay `False` until
   the test says otherwise, confirms the series is stuck in its own
   drain wait, panics, then lets draining finish) -- reverting the guard
   reproduces disk showing "completed" while memory shows "aborted".
3. **Camera exposure check used the requested value, not the applied
   one**: the achieved-timing check (prior round) already used the AD2's
   real achieved frame rate, but still compared it against
   `camera["exposure_ms"]` (the request), not what the camera actually
   applied -- DCAM quantization can make those differ (confirmed once on
   real hardware: 15.0ms requested read back as 15.00025ms). Fixed by
   reusing the existing `CAMERA_SETTINGS_READ`/`read_exposure_time()`
   round-trip to read the real applied exposure before the final
   comparison; both values are kept in the error message, never silently
   reconciled. New discriminating test (simulated camera monkeypatched to
   report a quantized-up exposure, isolated from the AD2 divergence the
   sibling test already covers).
4. **Settings-profile range validation**: the type-check fix (prior
   round) only caught wrong-typed values; a correctly-typed but
   out-of-range integer (e.g. `frame_count` far beyond its QSpinBox's
   1..100,000) was not caught at all -- `QSpinBox.setValue()` silently
   *clamps* a merely-too-large value (confirmed directly: 50,000 against
   a 1..1,000 range lands at 1,000, no error) and raises a raw
   `OverflowError` for one beyond the C `int` range, reproducing the same
   half-applied-widget defect the type check was supposed to close, and
   in the clamped case accepting a value nobody asked for with no error
   at all. Fixed with `SimpleSeriesPanel._validate_settings_ranges()`,
   checking every field against its own live widget's `minimum()`/
   `maximum()` (mirroring `DevicePanel.validate_profile()`'s existing
   style), called from `load_profile()` before `_apply_settings()` ever
   runs. Extended the existing malformed-data test with this exact case.
5. **Test-suite crash stability**: Codex's own full-suite run hit a
   native "Fatal Python error: Aborted" inside this round's own new test,
   at an `app.processEvents()` call, not reproducible when that test runs
   alone. Investigated rather than suppressed: `tests/test_device_ui.py`
   had 26 `ApplicationController` constructions but only 7 `shutdown()`
   calls; 5 specific tests called `controller.start()` (which really
   starts one `QThread` per simulated device) and never stopped them,
   leaking live threads into the single shared `QApplication` for the
   rest of the pytest process -- a plausible, timing-dependent cause of
   exactly this class of native crash in a later, unrelated test. Fixed
   by adding `try/finally: ...; controller.shutdown()` to all 5 (not a
   new fixture or framework, just the same cleanup pattern already used
   by this file's newer tests). Two independent full-suite reproduction
   attempts on this machine did not trigger the crash either before or
   after the fix -- consistent with a genuinely nondeterministic,
   timing-dependent native fault, not proof either way on its own. The
   leak itself is confirmed and real regardless of whether the exact
   crash re-occurs; not treated as "fixed because unreproducible."

**Verification discipline, same as every prior fix**: each of 1-4 was
confirmed to actually reproduce its symptom with the fix reverted, then
restored. Full offline regression suite run multiple times after all
five changes.

No hardware accessed, no push, no merge, ola-branch/junjiebranch/
AGENTS.md untouched.

---

## 2026-10-15 — Four real defects found by Codex's independent review of `3adc5a7`, fixed

Full detail in each fix's own commit message and `acceptance_table.md`/
`migration_checklist.md`'s rows (not repeated here). Summary, since this
entry's job is the decision trail, not another full writeup:

1. **Data loss on a later failure**: a post-acquisition flush failing
   after `_save_frames()` had already returned used to delete the
   experiment's real, already-saved TIFFs/`experiment.json`. Fixed with
   an `_experiment_frames_saved` flag gating the discard; the failure is
   recorded on the experiment's own existing metadata file instead.
   Acquisition success and overall experiment success stay distinct
   (`record_experiment_failed()` still runs either way). Genuinely
   incomplete experiments are still discarded, unchanged.
2. **Open temperature log after a normal stop**: `stop_after_current`
   never closed `self._recorder`, so the standing
   `attach_temperature_monitor()` connection kept writing into an
   already-"stopped" series, and the next series would silently
   overwrite the still-open recorder. Fixed by extracting the
   drain/close logic `_complete_series()` already had into
   `_close_temperature_recorder()`, shared by both paths. TEC output
   untouched.
3. **Timing checked against the request, not the achieved result**: the
   AD2's own clock division can round a legal requested frame rate to a
   different achieved one; only the requested value was ever checked
   against camera limits. Fixed by re-reading camera timing (reusing the
   existing `CAMERA_TIMING_READ` round-trip) after the real AD2
   configuration returns, and checking the achieved interval. Verified
   with a deliberately discriminating case, since the simulated AD2
   driver otherwise always echoes the request verbatim.
4. **Half-applied settings-profile loads**: a wrong-typed scalar field
   (plain dataclasses don't check field types) used to reach
   `_apply_settings()`'s widget-setting loop and fail partway through as
   a raw Qt `TypeError`, after earlier fields in that loop had already
   been applied to the real widgets. Fixed with upfront per-field type
   validation in `simple_series_settings_from_profile()`, before
   `SimpleSeriesSettings` is constructed at all.

**Verification discipline, applied to all four**: each fix's own test was
confirmed to actually catch the defect (temporarily reverted, test failed
as expected, restored) before being counted as done — not just "written
and passing." Fix #1's own test also needed a second pass: its first
version raced against `_save_frames()`'s background thread pool
(deterministic locally, flaky under full-suite load) by failing the
flush unconditionally the instant it was intercepted; corrected to wait
for `_experiment_frames_saved` to actually become true first.

No hardware accessed, no push, no merge, ola-branch/junjiebranch/
AGENTS.md untouched.

---

## 2026-10-15 — Residual flush-unit defect, found independently by Codex, fixed

Per explicit instruction: close out the pump-unit fix properly, this
time with the scenario Codex's own independent simulation actually
exercised. No hardware touched; no new confirmation dialog or framework
added, per instruction.

**The residual bug, precisely.** The prior fix (same day, earlier entry)
correctly restored `flush_unit_index` once a *matching* unit appeared in
`pump_unit`, and correctly remembered it as pending otherwise. What it
missed: when `_devices()` repopulates the combo and *no* unit matches
either the previous selection or the pending one (e.g. the pump connects
but only offers unit 0, and the saved value was unit 1), the
`clear()`/`addItem()` loop still ran unguarded. `QComboBox` makes the
first added item "current" by default as soon as items exist, so this
fired a real `currentIndexChanged` event with unit 0 now genuinely
selected — and `_settings()`'s fallback-to-pending logic only kicks in
when `currentData() is None`, so that spurious, Qt-chosen value won
outright. `pump_unit_notice` still said "not matched" (correctly), but
the value `_settings()` actually returned, and what would have compiled
and queued, was unit 0 anyway — a silent, wrong substitution the notice
was supposed to prevent.

**Fix** (`ui/simple_series_panel.py`):
- `_devices()`'s whole pump `clear()`/`addItem()`/select sequence now
  runs inside `pump_unit.blockSignals(True)`/`finally: blockSignals(False)`.
  When neither the previous selection nor the pending value matches
  anything now offered, it explicitly calls `setCurrentIndex(-1)` rather
  than leaving Qt's default in place.
- `_apply_flush_unit_index()`'s own no-match branch does the same, for
  the symmetric case where the pump is *already* connected (with the
  wrong units) at load time, not only "not connected yet."
- A new `pump_unit.currentIndexChanged` → `_pump_unit_selected()`
  connection clears the pending value exactly when the operator makes a
  genuine, different choice (any event where the resulting
  `currentData()` is not `None`) -- safe precisely because the
  `blockSignals` guard above means this handler never fires for Qt's
  own default-selection noise during repopulation, only for a real
  resolution (restore-to-pending or a genuine user pick).

**Verified the new tests actually catch the regression**, same
discipline as every other finding this round: temporarily reverted the
`blockSignals`/explicit-`-1` change, reran the three flush-unit tests --
all three failed as expected (the two new ones plus the existing
load-before-connect test, which turned out to also rely on the fix
being correct, not just the earlier, narrower one); restored immediately
after and reran clean.

**2 new tests**, both using a 1-unit simulated pump bank
(`DeviceRegistry(factories={DeviceId.PUMP: lambda: SimulatedPumpBank(unit_count=1)})`,
confirming the saved unit index 1 can never become available, not "not
yet"):
`test_experiment_tab_flush_unit_stays_unselected_when_the_saved_unit_never_appears`
(connects anyway; `pump_unit.currentData()` stays `None`, the notice
stays visible, `_settings(require_pump_unit=False)` still reports the
pending value for a re-save, and `_definition()` still correctly
refuses with "Select a configured pump unit" rather than silently
compiling against unit 0) and
`..._notice_clears_once_the_user_picks_a_different_unit` (the operator
explicitly selects the one real unit; the notice clears, `_definition()`
now succeeds, and the abandoned pending value does not resurface even
if `_devices()` runs again afterward for an unrelated reason). The
existing `test_experiment_tab_flush_unit_selection_survives_a_load_before_connect`
test (the "unit appears later" happy path) is unchanged and still
passes, per explicit instruction to keep it.

---

## 2026-10-15 — Fixed a real flush-unit restore defect found right after the settings-profile feature landed; added the pre-run preview

Per explicit instruction: close out the settings-profile batch properly
before moving on, then implement the pre-run preview as its own small,
independent piece. Both done; no hardware touched.

**The defect, precisely.** `_apply_settings()` restored `flush_unit_index`
with `self.pump_unit.setCurrentIndex(self.pump_unit.findData(flush_unit_index))`.
`pump_unit` is only populated while the pump is connected (`_devices()`),
so loading a profile before connecting meant `findData()` always returned
`-1` on an empty combo — the saved value was dropped with no error and no
visible sign anything was wrong. Worse: Qt's `QComboBox` makes the first
item "current" by default as soon as items are added to an empty one, so
connecting the pump afterward could silently select unit 1 regardless of
what was actually saved. The round-trip test added for the save/load
feature itself used unit 0 for its saved value, which happens to be that
same default -- so it passed without ever exercising the failure path.
Caught by inspection, not by that test, and confirmed by a new test using
unit 1 deliberately.

**Fix** (`ui/simple_series_panel.py`): a new `_pending_flush_unit_index`
field holds the saved value when the combo can't honor it yet, set by a
new `_apply_flush_unit_index()` (called from `_apply_settings()` in place
of the old direct `setCurrentIndex` call). `_devices()` -- already run on
every device status change, including the pump actually connecting --
checks this pending value once the combo is repopulated and restores the
match if one now exists, clearing the pending state. A new
`pump_unit_notice` label (same `QLabel` + red/bold styling convention
already used for `camera_preflight_label`) names the saved-but-unavailable
unit explicitly instead of leaving the combo looking like nothing was
ever saved, or like a different unit genuinely was. `_settings(require_pump_unit=False)`
(the save path) now falls back to the pending value when the combo has
no current selection, so saving again before the pump ever connects does
not lose the value either -- confirmed directly by the new test, not
assumed. No change to `_settings(require_pump_unit=True)`'s existing
"Select a configured pump unit" requirement for actually compiling or
queuing a series.

**Pre-run preview** (same file, `_run_preview_text()`, called from the
existing `_preview()`): adds repeats-per-point, each varying scan
parameter's actual compiled range, the temperature-wait strategy in
plain words, and the chosen output location to the existing experiment/
flush/frame-count summary. Deliberately reads the values from
`expansion.experiments`' own compiled parameters rather than re-deriving
them from the `NumericRange` widgets a second time, so the preview can
never drift from what was actually compiled and validated. Caught its
own bug before shipping: `compile_simple_series()` represents a
*disabled* sweep or temperature axis as the literal string `"NaN"` (not
an absent key, not a real number) -- the first draft tried to `:g`-format
that string directly and would have crashed the preview the moment
sweep or temperature control was turned off; the new test exercises
exactly that case.

Full suite run after both fixes: all passing, zero regressions (see
`migration_checklist.md`'s corresponding rows for exact counts).

---

## 2026-10-15 — Experiment-tab settings save/load, reusing the existing device-settings profile; and a correction to the "shortest path" doc's own evidence claims

Per explicit instruction: the baseline from `1a888b5` stands; this batch
adds exactly one capability (recipe save/restore for the Simple Series
form) without adding generic protections or chasing junjiebranch feature
parity, and separately tightens two overstated claims found while
reviewing this round's own prior documentation.

**Design, reusing what already exists rather than building a new
framework**: `MainWindow` already has a per-device settings profile —
`profile_document()`/`save_profile()`/`load_profile()`, one JSON file,
one File-menu entry point, a `"devices"` key keyed by `DeviceId`. Device
panels participate via a generic `register_profile()`/`profile_values()`/
`apply_profile()` widget registry (`DevicePanel` base class). The
Experiment tab (`SimpleSeriesPanel`) is not a `DevicePanel` and already
has its own, simpler, dataclass-based round trip for this exact job —
`_settings()` (widgets → `SimpleSeriesSettings`) and `_apply_settings()`
(`SimpleSeriesSettings` → widgets, already used for queued-series
editing). Rather than retrofitting the generic per-widget registry onto
a panel that already has a cleaner dataclass-shaped one, or inventing a
third mechanism, this adds:
- `application/simple_series.py`: `simple_series_settings_to_profile()`/
  `_from_profile()`, a JSON-safe serialize/deserialize pair for
  `SimpleSeriesSettings` (handles the five `NumericRange` fields and the
  `roi` tuple; validates unknown fields and malformed shapes the same
  way `DevicePanel.validate_profile()` already does for device settings).
- `ui/main_window.py`: `profile_document()` gains a sibling
  `"experiment"` key; `load_profile()` validates it (if present) before
  applying *anything* — same atomicity guarantee the existing devices
  path already has — then calls `self.experiment_panel._apply_settings()`.
  A file without `"experiment"` (every file saved before this round)
  loads exactly as before; the key is optional, not versioned, since
  adding it is purely additive to the document, not a breaking schema
  change to the existing `"devices"` shape.
- `ui/simple_series_panel.py`: `_settings()` gains a keyword-only
  `require_pump_unit: bool = True` parameter. Every existing call site
  (`_queue()`, `_preflight()`, `_definition()`, the queued-series editor)
  keeps the default and therefore keeps raising "Select a configured
  pump unit" exactly as before — compiling or running a series still
  needs a real flush unit, unchanged. Only the new save path calls it
  with `require_pump_unit=False`, because capturing the form's current
  inputs must not require a pump to be connected (`flush_unit_index`
  simply saves as `null` in that case, same as what the combo already
  reports).

**What this does not do, matching the explicit instruction**: no new
state machine, no new confirmation dialog, no new generic config
framework, and loading never connects a device, submits a command,
queues, or starts anything — confirmed directly in the new tests by
asserting the `command_result` list gains zero entries across the
`load_profile()` call itself, not merely by the absence of an exception.

**Correction to this round's own prior entry (`1a888b5`)**: the
"shortest path" doc section said the full-`MainWindow` acceptance test
proved "every other group... has usable defaults; leave them." That
test actually configured specific short values (`repeats=2`, a single
fixed frequency/amplitude/exposure, a 16x16 ROI, etc.), not the widgets'
own untouched defaults — leaving fields at their raw defaults was never
exercised and is now documented as untested, not as verified-safe. The
same section also implied real human visual review by saying buttons
were "confirmed" to work without separating that from what a
programmatic `.click()` call actually proves (the signal/slot wiring
runs; nothing about how the window looks or reads to a person). Both are
corrected in `migration_checklist.md` directly; no code changed for
either correction.

---

## 2026-10-15 — First full-MainWindow acceptance test; found and fixed a real documentation gap in the "shortest path" steps

Per explicit instruction: final usage acceptance for this round of
integration. Added exactly one new test,
`tests/test_simple_series.py::
test_full_main_window_operator_flow_queue_start_status_output_and_stop`
— the first test in this suite to drive the real `MainWindow` through
actual widget clicks (`_buttons["connect"].click()`,
`preflight_button.click()`, `queue_button.click()`, `start_button.click()`,
`stop_button.click()`), not panel-level automation (`SimpleSeriesPanel`
constructed directly) or a direct `controller.experiments.queue()`/
`.start()` call bypassing the UI, which is what every existing test in
this file already explicitly disclaims itself as being (see the module
docstring). Confirms, through real clicks: device-panel Connect reaches
the controller and updates both the panel's own `connection_label` and
the Status tab's dashboard; the Experiment tab's Preflight/Queue/Start
buttons reach the manager; a short 2-repeat series completes with a
correct `metadata/status.json` (`finalized_outcome: "completed"`,
`experiments_completed: 2`), `metadata/manifest.json`, and the right
TIFF count on disk; and the real "Stop after current" button, clicked
mid-flight on a second queued series, genuinely halts the batch before
that series' second repeat (`finalized_outcome:
"stopped_after_current"`, `experiments_completed: 1`), with the
Stop/Abort buttons correctly disabled once terminal.

**A real problem was found, not just confirmed-working**: the
"Shortest path to one representative experiment" steps in
`migration_checklist.md` (written in a prior round from reading the
code, never actually run end-to-end) **did not work as written**. Two
concrete gaps, both fixed in `migration_checklist.md` directly (this is
a usage-affecting documentation bug, not a code defect — the underlying
behavior in both cases is correct by design):
1. The steps never mentioned clicking Refill on the Pump panel first.
   The simulated pump (and, per `known_open_items.md`, a real one after
   a restart) starts at 0 mL; queuing any series with a nonzero flush
   volume then fails immediately with "Pump unit N needs X mL total
   flush volume but currently has 0 mL" — correct guard behavior, but an
   operator following the old steps literally would hit this and not
   know why, since the steps never said it was required.
2. Step 5 said `manifest.json` lives loose in the batch folder; it
   actually lives at `metadata/manifest.json`, confirmed by listing the
   real output directory this test produced.

**No code changed.** Both gaps were documentation-only; the flush
guard, the folder layout, and the Preflight/confirmation-dialog
interaction are all working as designed, confirmed by this same test —
this round's fix is entirely in `migration_checklist.md`, per the
instruction not to add features or protections when nothing is actually
broken in the software itself.

---

## 2026-10-15 — TEC correction: a real, reviewed MeCom client exists on both branches (the prior "never implemented" claim was wrong)

Found while doing final usage acceptance on `codex/integration`, per
explicit instruction to correct this "in passing" without opening a new
protocol-implementation or hardware-reverification task. No code
changed.

**The error.** The entry below this one (same day, Z-stage/pump/AD2
evidence-reuse pass) said: *"junjiebranch's own MeCom/TEC protocol was
never implemented, by explicit design ('to avoid inventing hardware
commands without a reviewed client'), Session 54's entry."* That is a
real misread — Session 54's remark was true only at that point in
junjiebranch's own history (no reviewed client existed yet to test
COM4/COM6 against). junjiebranch's `docs/tec_verification_matrix.md`
(Sessions 75-77, dated after Session 54) shows a real, reviewed
`_PyMeComTecClient` (pyMeCom's `MeComSerial`) was built, with its own
explicit "Independent-audit status (2026-08-05)" callout distinguishing
solid retained evidence from historical self-reported claims:
**retained**: 2026-08-28 real reads (Device Status 104, Object
Temperature 1000, Output Enable Status 2010 — both channels, plausible
room temperature) plus one real write (Output Enable=0, Static OFF,
confirmed by readback, client closed cleanly); **not retained as
current evidence**: Sessions 75-77's broader claims (real setpoint
writes, "immediate thermal response") — the document itself calls these
self-reported and not independently reproducible, and leaves real TEC
*operation* (setpoint writes, Static ON) formally unauthorized pending
bench review.

**Confirmed this branch carries the same real client, not a
reinvention.** `drivers/tec/controller.py`'s `_PyMeComTecClient` has the
identical reviewed 5-parameter allow-list (104/105/1000/2010/3000), the
same "Target Object Temperature" naming fix junjiebranch's Session 76
found necessary, and the same write-restricted-to-2010/3000-by-name
discipline — confirmed by direct code read, not assumed from the class
name matching.

**What this changes, precisely**: `acceptance_table.md` gets a new row
stating a real TEC client exists on both branches, with junjiebranch's
narrow retained real-I/O precedent cited accurately (read + OFF-write
only, not setpoint writes). `known_open_items.md`'s real-hardware plan
Stage 1 TEC bullet and Stage 3 intro are updated to cite this precedent
without overclaiming it covers setpoint writes, which it doesn't.
`investigation_log.md`'s TEC paragraph is corrected in place (it isn't
an append-only history file in the same sense as this one).

**What this does not do, per explicit instruction**: this is not a
reason to build a new protocol implementation (one already exists and
was already ported correctly) or to schedule a full TEC hardware
reverification — the existing "待实机 for real setpoint operation"
status is unchanged; only the "never implemented at all" framing was
wrong and is now corrected.

---

## 2026-10-15 — Reusing historical real-hardware evidence instead of blocking on "no new log on this branch"; corrects a real overstatement about Z-stage

Per explicit instruction: this round does not treat "the integration
branch itself has no new real-hardware log" as a blocker, and does not
default to re-verifying every device from zero. It targets specific
capabilities, checks whether the implementation and conditions behind
existing evidence have materially changed, and reuses what still applies.
No hardware was touched to produce this entry — it is a documentation
correction from reading `junjiebranch`'s `docs/claude_code_change_log.md`
(via `git show`, read-only) and this branch's own tracked
`hardware_tests/wfg_dc_sine_idle_test/results/`.

**The real correction, not just an addition:** `acceptance_table.md` and
`known_open_items.md` previously said "junjiebranch's own real motion
attempt failed, neither branch has a working real [Z-stage] run." That
was wrong. `claude_code_change_log.md` Session 48 (first real PPC001 +
C15440-20UP scan — a real bug was found first, a `System.Decimal`/
`float()` incompatibility, fixed and then the scan succeeded: 6/6 frames,
measured positions within 0.05-0.18um of target) and Session 54 (the
same scan repeated through the actual UI buttons, plus a real mid-scan
abort producing the exact designed "PARTIAL" message) both succeeded.
The likely source of the error: `investigation_log.md` had cited a single
`FAIL cmd='...' error=Failed to connect` line from a broad 2-month
hardware-transactions log and read it as "Z-stage doesn't work," without
checking whether a later session in the same project fixed the problem
it represents — it did, dated after that log's window closes. This
branch was not reading its own cited evidence closely enough before this
correction; `investigation_log.md` itself has been corrected with a note
so this isn't repeated. **Consequence for `known_open_items.md`'s
real-hardware plan**: Z-stage motion stays excluded from the current
minimal plan, but for a narrower, accurate reason — this branch's own
`z_stack.py`/`hal/z_stage.py`/UI combination has never been run against
real hardware, not because real Z motion is unproven. The exact fix that
made junjiebranch's scan work (`_decimal_to_float()`) already exists in
this branch's `drivers/z_stage/thorlabs_piezo.py`, confirmed by direct
code read — carried over correctly, nothing to redo there.

**Other evidence reused this round, correctly this time:**
- **Pump motion**: Session 54 Scenario 2 real-hardware-verified the
  reject/accept shape (`target = fill_level_ml - volume_ml`; reject
  before motion if negative, real readback/valve unchanged on reject;
  real measured drop on accept) that this branch's `FlushWorkflow`
  implements with the same logic, on the same Qmix SDK family this
  branch's pump driver is already "verified near-identical" to. Cited as
  supporting precedent for the general pattern in `acceptance_table.md`;
  NOT claimed as proof of this branch's own newly-added
  `_implausible_reading()` layer, which Session 54 did not exercise and
  which stays 待实机.
- **AD2 real output**: this branch's own tracked
  `hardware_tests/wfg_dc_sine_idle_test/results/` (4 runs, 2026-09-24,
  real scope captures) already shows the production `AnalogDiscovery2`
  class — the same one `hal/registry.py` constructs for the real
  experiment path, confirmed by direct code read, not a separate probe
  copy — configuring a carrier, arming, PC-triggering a bounded run, and
  reading back correctly. Added as a new `acceptance_table.md` row,
  scoped precisely (single-channel, PC-trigger only; multi-channel and
  the DIO0 camera cross-trigger remain unverified).
- **Serial `readline()`/`\r` timing bug (junjiebranch Session 54/55)**
  and the **pump `read_fill_level()`-at-connect gap (Session 56)**:
  checked against this branch's own code, not assumed. The first is
  already fixed here — `drivers/common/serial.py`'s `query()` already
  uses `read_until(expected=self.line_ending...)`, with a comment citing
  Session 54 directly. The second doesn't apply here at all: this
  branch's `PumpWorker._refresh()` continuously polls `read_fill_level()`
  from the real device on every poll cycle (not just a one-time
  dataclass default), so the specific "stale `0.0` after a restart" gap
  Session 56 fixed was architecturally avoided from the start, not fixed
  reactively.
- **TEC**: no real-hardware evidence exists on either branch, and none
  was claimed. junjiebranch's own MeCom/TEC protocol was never
  implemented, by explicit design ("to avoid inventing hardware commands
  without a reviewed client," Session 54's entry) — there is no history
  to reuse here, only the absence correctly recorded as absence.
- **Camera**: junjiebranch's own exposure/trigger-source/FPS-budget work
  (Sessions 13, 19, 20) is explicitly self-described as "not
  hardware-verified" in every case — no real camera was exercised for any
  of it. The existing "simulated only" claim for this branch's camera
  driver was already accurate; nothing to correct there.

**What this does not do, per explicit instruction**: no new tests, no
new protections, no new hardware access, no restoration of junjiebranch's
full historical documentation set. The corrections above replace
inaccurate conclusions with accurate ones using evidence that already
existed; they do not expand what this round claims to have verified.

---

## 2026-10-15 — Terminology correction: "locked"/"unlocked" retired for this branch's TEC panel; `max_wait_s` claim narrowed to software-only

Two imprecise claims, found while doing a documentation-accuracy pass
(no code changed):

1. **"Locked"/"unlocked" TEC phrasing (used below, in the 2026-10-15
   "Mission recalibration" entry, and in `acceptance_table.md`/
   `migration_checklist.md` before this correction) misdescribed what
   `SimpleSeriesPanel` actually does.** That vocabulary is junjiebranch's,
   for a ch1/ch2 broadcast relationship ("locked" = ch2 mirrors ch1
   automatically). This branch's panel has no such relationship at all:
   `compile_simple_series()` always emits `"channels":
   [settings.tec_channel]` — exactly one channel, chosen by the panel's
   single `tec_channel` combo box. There is no UI path that addresses
   both channels, matching or not. `acceptance_table.md` and
   `migration_checklist.md` are corrected to describe this as
   "single-channel, operator-selected" instead of "locked," and to
   describe the engine-only dict-valued/multi-channel capability as
   "both channels from one definition" instead of "unlocked." The
   historical entries below keep the old wording since they describe
   what was true/claimed at the time; this entry is the correction of
   record.
2. **A short `temperature_max_wait_s` being executable is not evidence
   that a real TEC can physically stabilize that fast.** The entry
   immediately below proved `max_wait_s=0.1` runs to completion without
   error — true, but only because `SimulatedTec` reaches its setpoint
   instantly with zero thermal lag. On real hardware a short window would
   likely (and correctly) fail the tolerance check instead of succeeding,
   since real thermal settling takes real time that hasn't been measured
   on either branch. `acceptance_table.md`'s corresponding row now states
   this explicitly, so "executable" is not read as "physically sensible to
   use."

---

## 2026-10-15 — `max_wait_s` actually fixed, superseding the prior entry's "removed, relies on graceful failure"

The prior round's fix (below, "The `temperature_max_wait_s >= 1.0` floor
was reviewed") only changed a compile-time rejection into a run-time
failure — a value under 1s still could not actually be *used*, and worse,
it would fail only after the series-level flush had already run (fluid
already moved before the bad parameter was discovered). Not acceptable as
"fixed."

**Real fix**: `experiment_runner.py`'s `_run_action()`, `"tec_wait_stable"`
branch, now computes `poll_interval_s = min(1.0, max_wait_s)` before
constructing `TecWaitStableArgs`, instead of leaving it at the fixed 1.0s
default. Any `max_wait_s` is now self-consistent by construction — there
is no longer an invalid combination reachable through the declarative
step pipeline, for any value above the existing `> 0` requirement. Proven
by actually completing a series with `max_wait_s=0.1`, not by asserting it
compiles or fails cleanly: `test_tec_wait_stable_with_a_sub_one_second_
max_wait_actually_runs` (raw definition) and
`test_ui_configured_short_max_wait_actually_completes` (real panel path).

The prior round's `test_tec_wait_stable_argument_construction_failure_
reports_cleanly` tested a scenario that can no longer occur (poll_interval_s
exceeding max_wait_s) — replaced with
`test_tec_wait_stable_with_a_sub_one_second_max_wait_actually_runs` above.
The general exception-propagation fix in `_run_action()` (catching any
command-argument construction error, not just this one) stays — it's
still correct defensive code, just no longer the *only* thing standing
between a short `max_wait_s` and a crash, because there's no longer an
error case to fall back to it for in this specific scenario.

---

## 2026-10-15 — Mission recalibration: proportionate complexity, not parity

This is a lab hardware-control algorithm project. The goal is to run
experiments correctly and stay easy to adjust — not to fully replicate
junjiebranch, clear every "unfinished" item, or cover every theoretical
case. junjiebranch's documentation, restrictions, and protections are
**material to evaluate**, not inherit by default: a lot of recorded
planning there does not by itself mean this branch must carry it. Four
things follow from that, recorded here rather than in a new file.

### Restrictions reviewed against "what does it actually prevent"

| Restriction | Prevents | Other-layer coverage | Cost on normal use | Verdict |
|---|---|---|---|---|
| `FlushWorkflow._implausible_reading()` (pump) | Computing a flush target from a stale/implausible SDK fill-level reading | None — `PumpWorker.set_fill_level()`'s target-range check is a different thing (protects the target, not the reading) | None on a legitimate reading; only engages on genuinely implausible data | **Keep** — real documented incident (`-513` SDK rejection on junjiebranch), not speculative |
| `_run_action()`'s whole-dispatch try/except | An exception while building a command's own arguments crashing uncaught into the Qt callback chain | None — `_submit()`'s try/except never covered this | None — only engages on a genuine construction error | **Keep** — general correctness fix, not a restriction on normal use at all |
| `temperature_max_wait_s` compile-time floor (removed this round) | Nothing a real device needs — the 1.0s came from `TecWaitStableArgs.poll_interval_s`, a software polling default | The propagation fix above already reports the same inconsistency gracefully at run time | Forced every operator to learn and respect an arbitrary number with no physical meaning | **Removed** — exactly the "software default dressed as a device requirement" this review was asked to find. **Superseded by the entry above this one**: "reports it gracefully" was still not the same as "actually works" — the poll interval now adapts instead, so there's no failure case left to report |
| Z-stage two-tier operator confirmation (junjiebranch had it, this branch doesn't) | A real device-constraint concern (piezo motion without explicit authorization) | None currently | Would add a second confirmation dialog to every Z move | **Not added** (decided previously) — real device constraint, but no real Z-stage work is authorized yet to need it; revisit if/when real Z motion is actually planned, not speculatively now |
| TEC `temperature_wait_for_stability` (optional, default off) | Nothing when unused — the default path compiles identically to before it existed | N/A | Zero cost unless explicitly enabled | **Keep** — proportionate: it's an opt-in capability add, not a forced complexity increase |

No restriction was found this round that needed removing beyond the
`max_wait_s` floor above. The pump/propagation items are not restrictions
on normal use at all — they only ever engage on an actual error condition.

### Day-to-day modification cost (where the common changes actually go)

Checked against current code, not estimated:

- **Temperature strategy** (tolerance, settle/hold durations, locked vs.
  unlocked): `application/simple_series.py` (`SimpleSeriesSettings` fields
  + `compile_simple_series()`'s `temperature_steps` construction) and
  `ui/simple_series_panel.py` (the Temperature group widgets). The
  underlying per-point gating mechanism itself (`tec_set`/`tec_wait_stable`
  dispatch) is `experiment_runner.py`'s `_run_action()` + `_tec_args()`;
  changing *values* never touches that file, only changing the *mechanism*
  would. One real coupling point worth knowing: UI widget ↔
  `SimpleSeriesSettings` field ↔ compiled JSON arg ↔ `TecApplySetpointsArgs`/
  `TecWaitStableArgs` field is a consistent 1:1 chain with no duplicated
  logic — changing a default means touching the UI default and the
  dataclass default together (2 files), which is the minimum necessary,
  not padding.
- **Parameter sweep** (adding a new scan axis): `application/experiments.py`'s
  `_values()` (value-list parsing) and `walk()`'s `"sweep"` handling
  (cartesian expansion). One specific coupling point: the `labels` dict
  inside `walk()` (around the sweep-parameter-name → folder-prefix mapping)
  is hardcoded to recognize specific names for `simple_series` folder
  naming — adding a new named sweep parameter through the simple-series
  compiler means updating both `simple_series.py` and this dict, or the
  new parameter's folders fall back to a generic `name=value` label. Small,
  bounded, not worth refactoring away — a lookup table is the
  proportionate solution for a handful of named parameters.
- **Acquisition timing** (frame rate, exposure, trigger windows):
  touches three places, each catching a *different* class of problem, not
  redundant layers: `experiments.py`'s `_validate_experiment()` (static
  schema/ordering correctness — can this JSON even make sense),
  `experiment_runner.py`'s `_after_camera_timing()` (series-wide sanity
  against *live* SDK-reported numbers — laser window, live minimum trigger
  interval), and `_configure_all_before_fluidics()` (the actually-applied
  value against the bounded output-timeout window). Collapsing these would
  conflate "is this JSON internally consistent" with "does the live
  hardware actually accept it," which are genuinely different questions —
  not recommended.
- **Adding a new experiment-step kind** (a new leaf action): touches
  `experiments.py`'s `ACTION_RESOURCES` dict (resource declaration, for
  `parallel`-block conflict checks) and `_action()`'s schema validation,
  plus `experiment_runner.py`'s `_run_action()` dispatch (actual
  execution), and possibly `_validate_experiment()` if the new kind has an
  ordering constraint. A genuine 2-3-file touch, but it is the intentional
  split between validation and execution this architecture was built
  around — merging them back would reproduce the kind of monolithic
  coupling junjiebranch's `qt_ui.py` had.

**No simplification was made in this pass beyond removing the
`max_wait_s` floor above.** The multi-file touch points found are
intentional separation of concerns (schema vs. live-sanity vs. applied-value
checks; validation vs. execution), not accidental duplication — forcing a
refactor to reduce file count here would trade real clarity for a
superficially smaller diff, which is the opposite of what was asked.

---

## 2026-10-15 — Corrections from Codex's review of 6a0a8a5

Five corrections accepted and acted on, not just acknowledged:

1. **Real-time persistence was not actually done.** `record_experiment_
   started/completed/failed()` only incremented in-memory counters;
   `status.json` was never rewritten between the series' "running" call and
   its terminal one. Fixed: each now calls `status("running", {})`
   immediately. Verified by reading `status.json` from disk **while the
   series is still running** (`test_lifecycle_counts_are_persisted_before_
   the_series_ends`), not only at the end — the specific thing the prior
   claim of "done" had not actually checked.
2. **Panic was not zero-coverage** — `test_panic_stops_connected_outputs_
   without_moving_valve` already exercises `controller.panic_stop()` →
   `experiments.panic_abort()`, just with no series running. Re-scoped the
   gap correctly: stop/abort/panic semantics **while a series is actively
   running** had no coverage, and still needed `stop_after_current()`/
   `abort()` added regardless. Three new tests cover all three for the
   in-series case, each checking only the series-level consequence (next
   experiment doesn't start, final counts stay consistent) without
   re-asserting the already-covered single-device SAFE_STOP facts.
3. **The parallel-barrier test was not actually evidence of the barrier.**
   It used `AD2_DIGITAL_OUTPUT_STOP` as a proxy for "both branches done,"
   but that event precedes the per-experiment flush in the same branch and
   says nothing about the independent save branch at all. Replaced with
   two tests that each deliberately slow one branch by a controlled,
   known amount and measure that the real wall-clock gap to the next
   experiment is at least that amount.
4. **The `temperature_max_wait_s >= 1.0` floor was reviewed, not just
   defended.** The 1.0s came from `TecWaitStableArgs.poll_interval_s`'s
   *software* default, not a hardware fact. Considered: keep the check
   (clearer, earlier error) vs. make `poll_interval_s` itself adapt to
   `max_wait_s` (would require widening the "tec_wait_stable" JSON schema
   to accept it, a bigger change for a narrow benefit) vs. rely solely on
   graceful runtime failure. Chose to **fix the actual safety problem
   first** (exception propagation from command-argument construction,
   `experiment_runner.py`'s `_run_action()` — general fix, not
   TEC-specific) and **keep** the compile-time check only as a secondary,
   now-honestly-labeled convenience (reads the real default via
   `TecWaitStableArgs.__dataclass_fields__`, not a second hardcoded "1.0"),
   since the propagation fix means it's no longer the only thing standing
   between a bad value and a crash.
5. **Added the explicitly-requested whole-series flush-budget tests**: 3
   placements (series-level only, per-repeat only, mixed), each confirming
   `_check_capacity`'s rejection message cites the correct total.

Also: `TEC multi-point (unlocked)`, junjiebranch's temperature-point-level
counters, and the data-format decision are kept in `migration_checklist.md`
with their actual use case and implementation scope spelled out, per
instruction not to let "keep TIFF+JSON" read as "external compatibility
resolved" — it isn't; the external LabVIEW consumer was never checked.

Full suite after all fixes: see the commit this entry ships with for the
exact pass count.

---

## 2026-10-14 — End-to-end flow verification batch

**Correction accepted**: the earlier "TEC multi-point sequencing: done"
claim was verified only via a hand-authored JSON definition in
`tests/test_experiments.py`, which proves the *executor* supports it but
not that an operator can reach it. The real UI
(`ui/simple_series_panel.py`) only ever compiled `tec_set` → fixed `wait`.
Closed by adding an *optional*, default-off `temperature_wait_for_stability`
field (`application/simple_series.py`, `SimpleSeriesSettings`) plus matching
panel widgets — every existing default-constructed series still compiles
byte-identically (verified:
`test_temperature_wait_for_stability_is_additive_and_opt_in`). This is a
genuinely additive capability, not a change to existing experimental
semantics, so it did not need to be escalated as a reserved decision.

**Full baseline trace**: `docs/integration/flow_trace.md` now documents the
actual stage-by-stage call chain (UI → compile → queue → start → per-series
preflight/validation → node execution → leaf actions → completion →
stop/abort/recover), with direct answers to the specific ordering/scope
questions raised (flush scope, temperature-stable-then-hold gating,
camera/AD2 trigger unification, frame/timestamp correspondence, parallel
save/flush barrier, per-experiment re-configuration, and the three distinct
stop/abort/recover paths) — plus a targeted (not exhaustive) comparison
against junjiebranch's `application.py`/`workflows.py`, finding one genuine
architectural difference (junjiebranch runs flush and save **sequentially**
within one fixed per-repeat step order; this branch runs them as two
**concurrent** branches with a hard barrier) and one consistency win (this
branch checks graceful-stop at one uniform point; junjiebranch checks it at
two separate layers, UI and Application).

**Test-infrastructure note, not a product defect**: the first version of
`test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order`
constructed a full `MainWindow` and took 349s, printing a transient
`faulthandler` trace ("Windows fatal exception: code 0x8001010d") from a
background file-save thread partway through — the test still passed (exit
0), but the cost and the alarming-looking trace were both real. Switching
the harness to construct only `SimpleSeriesPanel` directly (the actual
object under test) brought it to 20s with no trace. Not filed as a known
open item: this was caused by the test harness's own over-construction, not
by application code, and is resolved.

**Explicit limitation**: this session has no desktop computer-use tool
available (only a Chrome-browser automation tool, not applicable to this
PySide6 desktop app) — "UI verification" this round means real widget-level
automation (constructing the actual panel classes, setting real widget
values, reading real compiled output), which exercises the same Qt signal/
slot code paths a manual click would, but is not literal mouse/keyboard
interaction with a running window. No confirmation dialogs were clicked
through manually for the same reason — automated tests injected confirm
callback answers (`confirm_unchecked`, `confirm_batch`) as code, not via a
displayed dialog.

---

## 2026-10-13 — Branch/worktree creation (Phase 0)

**Decision**: create `codex/integration` as a new branch, in an independent
worktree at `C:\git\thermoacoustic-integration`, starting from
`origin/ola-branch` at `5014fc8f479c058904e7e69f2f67384851ab88ce`.

**Why this starting point, not junjiebranch or a from-scratch rewrite**:
junjiebranch's one clearly-scoped architectural defect (the global
`_busy_count`/`_run_action` manual-dispatch mutex) is woven through 45 call
sites across two large, mutually-inheriting UI files
(`qt_ui.py`/`qt_ui_v3.py`, 10,582 lines combined). Replacing it in place
would be a single large, hard-to-stage change with high rollback cost.
ola-branch's equivalent capability (per-device-worker dispatch) is already
correct and already landed; the remaining work is additive, module-by-module
porting of specific junjiebranch algorithm/UI capability, which is safer to
stage and revert independently. Full reasoning and the rejected alternatives
(Option B: junjiebranch as base; a from-empty rewrite) are in the prior
investigation rounds (condensed in `investigation_log.md`).

**Not decided yet, deferred to later batches**: TDMS vs. TIFF+JSON data
format (owner decision), PySide6 version reconciliation (6.8.3 vs. 6.11.1 —
not yet a live conflict since only ola-branch's side is in this worktree, but
will matter if junjiebranch UI code is ever directly referenced again), the
Prepare-tab TEC readback display comparison, the chronology-ordering UX
principle from `lessons_learned.md` §7.1-7.2.

**Explicitly not approved by this entry**: any `src/` change. This entry only
records the branch/worktree creation and the records in this `docs/
integration/` folder.

---

## 2026-10-13 — Valve-confirmation finding corrected

**Prior claim (withdrawn)**: "the automated experiment flow must add
`ValveReadyResult` consumption to avoid a junjiebranch-Bug-2-shaped silent
failure." This was based on looking at the wrong consumer.

**Corrected finding**: `application/experiment_runner.py:857-860` (the
"flush" step) builds a `WorkflowCommand`/`FlushArgs` and submits it through
`ApplicationController.submit()` (`application/controller.py:184`), which at
lines 311-318 routes any `WorkflowCommand` to `_start_flush()`
(`controller.py:348`) — the **only** instantiation site of `FlushWorkflow`
in the codebase (grep-confirmed). `FlushWorkflow._on_timer()`
(`application/workflows.py`) polls `valve.readback` every 250 ms against a
10-second deadline, proceeding only when `isinstance(readback,
ValveReadback) and readback.ready and readback.confirmed_position ==
desired`, with a `RECOVERY_STOP` -> `RECOVERY_CLOSE_COMMAND` path on
mid-flush failure. No bypass path was found: `experiment_runner.py` has no
other `VALVE_POSITION_SET`/`DeviceId.VALVE` reference.

**Action**: none. This item is closed with no code change needed.

**Separate, smaller, not-yet-actioned item**: the standalone
`VALVE_WAIT_READY` command (`hal/valve.py:77-84 wait_until_ready()`) returns
`ValveReadyResult(ready=False, ...)` as a normal `command_succeeded` result,
not a failure. This is reachable only through whatever UI path calls that
command directly (not the automated flush path, confirmed above). No
concrete caller mishandling this was identified. Tracked as open, low
priority, unconfirmed impact — see `known_open_items.md`.

---

## 2026-10-13 — Pump capacity-check location corrected

**Prior claim (withdrawn, stated inconsistently across two earlier rounds)**:
"`_check_capacity` is ola-branch's equivalent of junjiebranch's
`known_capacity_ml` guard, and it does not cover the same scenario." This
compared junjiebranch's guard against the wrong one of three distinct ola
checks.

**Corrected mapping**:
- junjiebranch: `known_capacity_ml` field (`instruments.py:845`, set at
  `instruments.py:981` from a fresh SDK readback inside
  `configure_syringe()`); the guard itself is in `application.py:1149-1156`
  inside `Application.flush()`, comparing a **cached** `self.pump.fill_level`
  against `known_capacity_ml`.
- ola-branch has three checks, not one:
  1. `drivers/pump/cetoni.py:497` `max_volume_ml`, refreshed from a fresh SDK
     call inside `configure_syringe()` — structural equivalent of
     `known_capacity_ml`.
  2. `application/workflows.py` `FlushWorkflow.on_step()`'s `LEVEL_READ`
     state — a **fresh** `PUMP_FILL_LEVEL_READ` SDK call at the moment of
     flush, checking only `target = fill_level_ml - volume_ml >= 0` (enough
     fluid for this flush). Does **not** cross-check the fresh reading
     against `max_volume_ml`.
  3. `application/experiment_runner.py:492 _check_capacity` — a pre-batch
     check using a cached `PumpReadback` snapshot, comparing total planned
     flush volume across the whole series against `fill_level_ml` (a
     batch-budget check, not a per-flush plausibility check).

**Corrected gap**: none of the three checks reproduce junjiebranch's
plausibility cross-check ("is this fill-level reading even possible given
the syringe's own just-confirmed capacity"). ola's `FlushWorkflow.LEVEL_READ`
is the right location for a narrow addition — see Phase 1 plan below,
recorded but **not approved for implementation yet**.

---

## 2026-10-13 — UI items resolved without a code gap

- Z-axis UI: `ui/z_stack_panel.py` compared field-by-field against
  junjiebranch's Z-Scan tab. ola's panel is already a superset (adds ROI,
  position tolerance/timeout, manual jog, live preview, camera-settings
  import). No gap found; no port needed.
- Fault-reason display: `application/event_formatting.py:42
  event_summary()`'s `"failed"` branch already includes `event.message`,
  always populated by `hal/base.py`'s `command_failed.emit(request_id,
  str(exc))`. The bare-"Error" bug junjiebranch fixed in `56386f1` cannot
  occur here. No gap found; no port needed.

---

## 2026-10-13 — Software restrictions reviewed this round (register)

Per the authorization's "identify and simplify unnecessary restrictions"
item, each restriction actually examined during Batches 1-6, what it limits,
its basis, and the disposition:

| Restriction | Limits | Basis | Redundant with another check? | Disposition |
|---|---|---|---|---|
| `experiments.py` `_values()` sweep elements limited to bare str/int/float | Could not express a per-point dict of independent per-channel TEC targets | Original design predates any multi-field sweep need | No | **Simplified**: relaxed to also accept a flat numeric object, generically (Batch 3) |
| `FlushWorkflow` trusted the raw `PUMP_FILL_LEVEL_READ` reading | Nothing, previously — this was a gap, not an over-restriction | — | — | **Added** a narrow check (Batch 2), not a simplification; recorded here only to confirm it was not layered on top of an already-sufficient check |
| `PumpWorker.set_fill_level()`'s target-range validation (`hal/pump.py:88-91`) | A target outside `0..max_volume_ml` | Protects the SDK call itself | Yes, but by design | **Kept distinct from Batch 2's new check** — different failure mode (untrustworthy reading vs. out-of-range target); not merged, not removed |
| `ExperimentManager.queue()` requires a non-empty `description` | Queueing a batch without a human-readable label | Operator record-keeping (keeps batches identifiable later) | No | **Kept as-is** — reasonable operator-facing policy, not incidental friction; just needed adding to test definitions this round |
| `_validate_experiment()`'s `tec_set`/`tec_wait_stable`/`stage_move` must precede camera arm (`experiments.py:433`) | Where TEC/stage nodes may appear inside an experiment block | Camera arming must not race TEC/stage positioning | No | **Kept** — a real ordering constraint, not incidental |

No restriction was found and left unexamined as "probably fine" without a stated reason; none were removed without an equivalent check taking their place.

## 2026-10-13 — Full implementation authorization granted

User authorized autonomous implementation of the integration work (not just
Phase 1's pump-capacity item): TEC multi-point sequencing, experiment
lifecycle/outcome recording, Z-axis parity verification and necessary
gap-filling, valuable junjiebranch UI/operation-flow capability, and
simplification of unnecessary restrictions found along the way — all within
this worktree/branch, committed in small batches (no push/merge without
separate approval). Reserved to user+Codex: changes to experiment scientific
meaning/units/step order, removing a protection with real incident/device
evidence without equivalent coverage, dropping a significant existing
capability, output-format/compatibility-breaking changes, large driver
rewrites or new major dependencies, and any real-hardware/push/merge action.
The Phase-1 plan below is now approved as scoped (pump plausibility check
only, not a general new restriction system) — superseding the "NOT approved"
status in the entry below. See `migration_checklist.md` for live batch
status going forward.

## Phase 1 plan — APPROVED as scoped below (pump capacity only)

**Scope** (as specified): in `application/workflows.py`'s
`FlushWorkflow.on_step()`, `LEVEL_READ` branch, add a check for raw
fill-level reading plausibility — via the application layer
(`PumpReadback.units[unit_index]`'s own capacity field), not by reaching
into the driver directly.

**Confirmed available field** (`domain/models.py`): `PumpUnitReadback` (line
172) has `fill_level_ml: float | None` (174) and `max_volume_ml: float |
None` (178); `PumpReadback` (line 187) aggregates `units` (per-unit list) plus
its own top-level `fill_level_ml`/`requested_fill_level_ml`/`max_volume_ml`.
`FlushWorkflow` has `self.args.unit_index` already, so
`statuses()[DeviceId.PUMP].readback.units[self.args.unit_index].max_volume_ml`
is the exact, already-available path to the selected unit's capacity — no
driver access needed, confirming the approval request's constraint is
directly satisfiable.

**Explicit constraints carried over from the approval request, do not
broaden**:
- `PumpWorker`'s existing target-range validation on `set_fill_level` is a
  separate, already-correct protection against an out-of-range *target*. The
  new check is about distrusting the *raw reading*, not duplicating or
  replacing that existing validation. Do not describe this as "closing all
  out-of-range protection" — it closes one specific gap (plausibility of the
  raw reading), nothing more.
- Must define, before writing any code, what happens when: capacity is
  unknown (pump not yet configured / capacity field absent or `None`); the
  reading is non-finite (`NaN`/`inf`); and what tolerance (if any) is applied
  around the capacity boundary. **None of these are decided yet** — recorded
  here as open design questions for the Phase-1 approval request, not
  resolved unilaterally.

**Required test coverage before this can be considered complete** (from the
approval request, verbatim scope):
1. An implausible reading that pushes the computed target out of range.
2. An implausible reading where the computed target still happens to fall
   in range (i.e., the new check must trigger on the reading itself, not
   only on its downstream consequence).
3. A legitimate reading, normal flush completes.
4. The selected pump unit's capacity is read from the correct unit index
   (`PumpReadback.units[unit_index]`), not a wrong/default unit.
5. The failure path: pump stop, valve recovery-close, and final failure
   state are all reached correctly when the new check trips.

**Status**: plan recorded, no code written, awaiting separate, explicit
approval before any `src/` change.
