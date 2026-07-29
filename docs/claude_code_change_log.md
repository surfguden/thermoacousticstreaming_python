# Claude Code Change Log

This is a historical record of the LabVIEW-to-Python migration and the
Claude Code sessions that worked on it. It is intentionally useful, but it
is not the live source of truth for the current repository state. For the
current state, always check `git log`, `git status`, `git diff`, and the
code itself.

**Current repo-state note, refreshed after independent audit.** The old
top-level caveat in this document said the branch history ended at
`5419043` and that none of the work below had been committed. That is no
longer true. As of the refresh that added this note, branch `junjiebranch`
has commits through `8149bc1` (`Harden valve initialize() to reject
unrecognized status responses`), with `4105fa8` as the preceding Session
39 UI-audit commit. The working tree is still not clean: `qt_ui.py`,
`qt_ui_v2.py`, tooltip/layout-related tests, this changelog, and untracked
helper/probe files contain additional post-commit work. Current code/tests
also contain explicit **Session 41**, **Session 42**, and **Session 44**
references, so Session 40 is not the latest documented edit state in the
working tree.

**Caveat on methodology -- read this before treating the document as
authoritative.** Earlier sections were compiled from a mix of git
evidence, working-tree diffs, and conversation history. Those sources are
not equally verifiable:

1. **Git evidence.** Commit IDs and file contents that exist in the
   repository can be independently reproduced by anyone with repo access.
2. **Working-tree evidence.** Uncommitted changes can be checked with
   `git status` and `git diff`, but they have no commit timestamp and can
   change again without leaving durable history unless committed.
3. **Conversation history.** Sequencing claims about work that was made
   and then fully reverted are not recoverable from git alone. In
   particular, the qt_ui_v2 default-entry-point swap and later revert are
   conversation-derived because the net git diff is zero. Concretely:
   - `tools/run_ui.py`'s two edits (swap, then revert) net to a diff of
     zero against the last commit -- `git diff` alone shows no evidence
     this file was ever touched.
   - `launch_gui.bat` is untracked the entire time; git has never
     recorded any state for it other than "it currently exists," so there
     is no diff/log showing it ever pointed at `qt_ui_v2`.
   - `README.md` is tracked, but `git diff` only shows current-vs-last-
     commit (the final, reverted state) -- the intermediate rewritten
     state is invisible to git.

   A reader starting only from `git log`/`git diff`/`git stash list`/
   `git reflog`, with no access to the conversation, would have no way to
   know this swap-and-revert happened.

   A direct consequence: if any *other* change was made and then fully
   reverted without being recorded here, it would be invisible both to git
   and to this document. This log's completeness for "things done and
   later undone" is bounded by what was recalled while compiling it, not
   by anything independently checkable in git.

Also note: this log covers work from **two different sources**:

- A prior coding session (per the user's own account at the start of this
  Claude Code engagement, referred to there as "a prior coding session
  using Codex") that had already made substantial changes before Claude
  Code's involvement began. These are described in the "Pre-existing
  baseline" section below, reconstructed from the diff itself. That
  attribution (baseline vs. Claude Code session) is also sourced from the
  user's own account in conversation, not from any git marker distinguishing
  the two.
- The Claude Code sessions that followed, covered turn-by-turn in the
  "Claude Code sessions" section, sequenced from conversation history as
  described above.

## How to use the docs together

- This file is the historical change log: use it to understand when and
  why changes were made, but verify live behavior against the current code.
- `docs/current_workflow_audit.md` is the operational safety map for the
  current Python workflow and staged hardware boundaries. It is a
  point-in-time workflow document, not an authorization to run hardware.
- `docs/labview_migration_completeness_audit.md` is the migration-parity
  audit against LabVIEW. It records equivalence gaps and historical
  uncertainty; later code may have closed some gaps, so cross-check this
  changelog and current source before using it as an implementation spec.

---

## Pre-existing baseline (before Claude Code's involvement)

At the start of the first Claude Code turn, `git status` already showed
the same set of modified/untracked files listed in this document's source
data, and the user's own briefing at that time stated that Category A
hardware-safety work, DO clock derivation, and the valve write-timeout fix
were "DONE and merged" (i.e. already present in the working tree, not
merged as a separate commit). The following is what the diff itself shows
for that pre-existing portion:

### Hardware safety / cleanup (Category A)

- **DCAM frame-wait bounded timeout.** [hamamatsu_dcam.py:31](src/thermo_acoustic/hamamatsu_dcam.py:31) (`frame_total_timeout_s: float = 30.0`) and the wait loop around [hamamatsu_dcam.py:338-351](src/thermo_acoustic/hamamatsu_dcam.py:338) bound how long `wait_capevent_frameready` is retried, calling `_stop_and_release_after_wait_timeout` ([hamamatsu_dcam.py:380](src/thermo_acoustic/hamamatsu_dcam.py:380)) on timeout, which stops capture and releases the buffer instead of looping forever.
  - Verification: tested (`tests/test_hamamatsu_dcam_lifecycle.py` covers the timeout/cleanup path with a fake DCAM module). Not hardware-verified.
- **Abort runs independent of a busy worker.** [qt_ui.py:1514-1522](src/thermo_acoustic/qt_ui.py:1514) `_abort()` calls `_run_action(..., force=True, ...)`, bypassing the busy-worker guard so Abort isn't queued behind a running experiment.
  - Verification: not covered by an automated test found in this pass; relies on Qt threading behavior. Not hardware-verified.
- **Bounded shutdown on window close / Exit.** [qt_ui.py:363-370](src/thermo_acoustic/qt_ui.py:363) sets up `_shutdown_thread`, `_shutdown_poll_timer`, and a 30s `_shutdown_timeout_s`; [qt_ui.py:1564-1581](src/thermo_acoustic/qt_ui.py:1564) runs cleanup on a background thread and forces the window closed if it exceeds the timeout.
  - Verification: tested (`tests/test_qt_ui_hardware_settings.py::test_window_close_times_out_blocked_cleanup_without_freezing`). Not hardware-verified.
- **Partial-initialization rollback.** [application.py:147-163](src/thermo_acoustic/application.py:147) `Application.initialize()` tracks which devices succeeded and calls `_cleanup_instruments(initialized)` on any later failure, rolling back only what was actually initialized.
  - Verification: tested (`tests/test_application.py`, `tests/test_qt_ui_v2.py::test_v2_initialization_progress_uses_existing_instrument_order`). Not hardware-verified.
- **Qmix bus close on init failure.** [qmix_backend.py:65-89](src/thermo_acoustic/qmix_backend.py:65) wraps the whole bus-open/pump-lookup/enable sequence in try/except, calling `self.close()` (which stops and closes the bus, [qmix_backend.py:206-217](src/thermo_acoustic/qmix_backend.py:206)) on any exception before re-raising.
  - Verification: not covered by an automated test found in this pass. Not hardware-verified.
- **Serial read + write timeouts.** [instruments.py:37-40](src/thermo_acoustic/instruments.py:37) `SerialTextCommandBackend` sets both `timeout_s=1.0` (read) and `write_timeout_s=5.0` (write, increased from an original shorter value per the user's own account) on `serial.Serial(...)`, shared by both `Valve` and `PriorZMotor`.
  - Verification: not covered by an automated test found in this pass (real serial hardware needed). Not hardware-verified. The user's own account states the original short write-timeout was checked and confirmed *not* to be the cause of a valve-not-switching incident (that was traced to COM port drift instead).

### LabVIEW migration gaps (partially pre-existing)

- **DO clock / LED timing derivation.** [qt_ui.py:1434-1462](src/thermo_acoustic/qt_ui.py:1434) `_experiment_do_clock_config()` builds a real `DoConfig` from Camera FPS, Frames, and Camera Start (static or per-repeat dynamic array), replacing what the user's briefing described as a prior `{}` placeholder.
- **AD2 SDK wiring for the DO clock frequency.** [ad2.py:93-96](src/thermo_acoustic/ad2.py:93) adds a `clock_frequency_hz` field to `DoSingleChannelConfig`; [waveforms.py:453-536](src/thermo_acoustic/waveforms.py:453) `configure_do()` converts that Hz value into a hardware clock divider via `digital_out_internal_clock_info()` and wires the DO trigger's `sec_wait`/`sec_run`/`repeat_count`/`repeat_trigger` to the real `FDwfDigitalOut*` SDK calls.
  - Verification: not covered by an automated test found in this pass for the real SDK path (`waveforms.py` talks to the Digilent WaveForms DLL). Not hardware-verified.
- **AD2 completion wait including the DO term.** [application.py:247-266](src/thermo_acoustic/application.py:247) `_ad2_completion_wait_seconds()` takes the `max()` across both WFG channels and DO clock channels, not just WFG.
  - Verification: tested (exercised indirectly via `tests/test_full_flow_dry_run.py`). Not hardware-verified.
- **data.tdms metadata writing via npTDMS.** [pyproject.toml](pyproject.toml:6) adds `npTDMS>=1.10` as a dependency; [workflows.py:81-165](src/thermo_acoustic/workflows.py:81) (`Experiment2._settings_properties`, `_camera_properties`, `_write_tdms`) writes Repeat ID, ExposureTime, GlobalExposure, flush settings, WFG Freq/Amp/Run/Wait/Repeat for both channels, DORun/DOWait/DOFreq, and camera readout/ROI fields into `data.tdms` via `RootObject`/`GroupObject`/`ChannelObject` + `TdmsWriter`.
  - Verification: tested (`tests/test_application.py::test_experiment2_writes_labview_metadata_tdms` and related). Not hardware-verified (no real npTDMS-reading LabVIEW comparison performed).

### Valve protocol discovery (hardware-confirmed for command format, not for baud/query)

- **Command byte format and baud rate.** [instruments.py:688-689](src/thermo_acoustic/instruments.py:688) `Valve.command_position_1/2 = "P01"/"P02"`; [instruments.py:38](src/thermo_acoustic/instruments.py:38) `SerialTextCommandBackend.baud_rate = 19200`, `line_ending = "\r"`.
  - Verification: **hardware-confirmed.** [hardware_tests/test_valve_command_probe.py](hardware_tests/test_valve_command_probe.py:41-46) and [test_valve_command_probe_v2.py:27](hardware_tests/test_valve_command_probe_v2.py:27) are standalone single-shot probe scripts (independent of `src/`) used to test candidate byte sequences against the real Rheodyne MX valve; the scripts' own comments record `P01\r`/`P02\r` at 19200 baud as "confirmed LabVIEW format."

### Other pre-existing baseline items

- **FocusWheelGuard** (mouse wheel over unfocused spin/combo boxes doesn't change values) was already implemented at [qt_ui.py:101-124](src/thermo_acoustic/qt_ui.py:101) and installed at [qt_ui.py:353](src/thermo_acoustic/qt_ui.py:353) before Claude Code's involvement.
- **qt_ui_v2.py skeleton** ([qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py)) already existed as a new file with `MainWindowV2`, `InitializationDialog`, and a sidebar with WFG/MSO/PumpValve/Camera buttons -- but at that point the buttons only called a placeholder (`_show_placeholder`) that set a "not yet implemented" status message; they did not open real panels.
- **Additional manual smoke-test tooling** in [hardware_tests/test_real_workflow_smoke.py](hardware_tests/test_real_workflow_smoke.py) (e.g. a "LED trigger check" staged verification mode, `real_camera_led_trigger_check_plan`/`run_real_camera_led_trigger_check`) and corresponding coverage in `tests/test_real_workflow_smoke_plan.py` -- these are manual, explicit-flag-gated hardware verification scripts, separate from `src/` and from the pytest-collected automated suite's assertions about application logic.

---

## Claude Code sessions

### Session 1 -- Investigation (no code changes)

Read-only investigation of repo state at the start of this Claude Code
engagement. Confirmed via `git status`/`git diff` that two tasks from a
prior session's final instruction were **not yet done**:
- `Valve.initialize()` still reported "Connected" on port-open alone, with
  no handshake confirmation.
- `qt_ui_v2.py`'s four sidebar buttons (WFG/MSO/PumpValve/Camera) still
  called the placeholder (`_show_placeholder`), not real panels.

Also confirmed the probe scripts ([hardware_tests/test_valve_command_probe.py](hardware_tests/test_valve_command_probe.py), `_v2.py`) existed and had established `P01`/`P02` at 19200 baud, but had **no** LabVIEW-confirmed status/query command yet -- their only query candidate at that point was a speculative `*\r`.

### Session 2 -- Valve handshake + sidebar panel wiring

**What changed:**
- `Valve.initialize()` ([instruments.py:678-716](src/thermo_acoustic/instruments.py:678)) now sends a status query (`"S"`) after opening the port and interprets the response per a protocol described by the user as sourced from the IDEX MX Series II driver documentation (via the linnarsson-lab/MXII-valve reference driver): empty response -> raises `ValveError` (does not report Connected); a parsed port digit -> `status_note="confirmed"` and updates `position`; a lone `"\r"` or `"*"`/`"**"` -> `status_note="ready"`/`"busy"`; anything else -> `status_note="unverified position response: ..."` without failing outright. The old speculative `*\r` candidate was removed from the probe scripts and replaced with `status_query` (`S\r`).
- `qt_ui_v2.py`'s sidebar buttons ([qt_ui_v2.py:159-175](src/thermo_acoustic/qt_ui_v2.py:159), `_open_manual_panel`/`_ensure_manual_panel` at [qt_ui_v2.py:390-406](src/thermo_acoustic/qt_ui_v2.py:390)) now open lazily-created, cached, non-modal `QDialog`s wrapping `qt_ui.py`'s existing `_wfg_tab()`/`_mso_tab()`/`_pump_tab()`/`_camera_tab()` builders, reusing them as-is rather than reimplementing.
- `qt_ui_v2.py`'s valve status label surfaces `status_note` (e.g. "Connected (busy)") via `_valve_connection_text()`.

**Why:** Closes the two outstanding tasks from the prior session: giving the valve a real handshake instead of assuming success from a successful port-open, and making the new UI's manual-test buttons functional instead of placeholders.

**Files touched:** [instruments.py](src/thermo_acoustic/instruments.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [hardware_tests/test_valve_command_probe.py](hardware_tests/test_valve_command_probe.py), [hardware_tests/test_valve_command_probe_v2.py](hardware_tests/test_valve_command_probe_v2.py), [tests/test_application.py](tests/test_application.py) (new/updated valve tests), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py) (new panel-opening/status tests).

**Verification:** tested (full pytest suite passing at each step). The `"S"` query handshake itself is **protocol-derived but not hardware-confirmed** -- the user's own instruction at the time explicitly said "the 'S' command should be tried directly against real hardware to confirm before relying on it in initialize()," and nothing in the repo (no probe-script output, no hardware_tests/output/ entry) indicates that run happened. `P01`/`P02`/19200 baud remain hardware-confirmed from the earlier baseline.

### Session 3 -- Entry-point default swap + Init dialog fixes

**What changed:**
- (a) `launch_gui.bat`, `tools/run_ui.py`, and `README.md`'s "Application Status" section were changed to launch/describe `qt_ui_v2` (`MainWindowV2`) as the default day-to-day entry point instead of `qt_ui` (`MainWindow`).
- (b) `qt_ui.py`'s `main()` got a comment marking it a legacy standalone entry point for debugging manual panels in isolation.
- (c) In `qt_ui_v2.py`'s `InitializationDialog._hardware_details_group()` ([qt_ui_v2.py:86-113](src/thermo_acoustic/qt_ui_v2.py:86)): six confirmed-stub fields (Z stage backend, Thorlabs/APT serial/backend/discovery-only, Qmix SDK Python Path, Qmix QMIXSDK Path) were disabled with tooltip "Not wired to a real backend" via a new `_mark_unwired_stub()` helper -- confirmed against `hardware_factory.build_hardware_bundle()` which never reads those fields. `Cetoni config path` was left enabled since it *is* read by `CetoniPump`.
- (d) The three path fields (Qmix SDK Python Path, Qmix QMIXSDK Path, Cetoni config path) were widened via a new `_widen_for_content()` helper that measures each field's actual current text with `QFontMetrics` rather than a guessed constant.

**Why:** To make `qt_ui_v2` (which by that point had working sidebar panels from Session 2) the official day-to-day launch target, and to fix two small but real usability issues in its Initialize Hardware dialog: fields that look editable but do nothing, and path fields too narrow to show real values.

**Files touched:** [launch_gui.bat](launch_gui.bat), [tools/run_ui.py](tools/run_ui.py), [README.md](README.md), [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py).

**Verification:** tested (offscreen Qt render checks confirmed disabled state, tooltips, and computed minimum widths against actual measured text width; full suite passing). Not hardware-verified -- this entire session was superseded by Session 4 below.

### Session 4 -- Entry-point revert

**What changed:** `launch_gui.bat`, `tools/run_ui.py`, and `README.md`'s "Application Status" section were changed back to `qt_ui`/`MainWindow` as the default entry point, with `qt_ui_v2`/`MainWindowV2` described as an in-development preview, not the default, until approved.

**Why:** Explicit user instruction: "The new UI (qt_ui_v2) is not yet hardware-verified and must not be the default entry point until the user explicitly approves it." This was a deliberate reversal of Session 3's part (a)/(b), not a bug fix.

**Files touched:** same three files as Session 3's (a).

**Verification:** tested (full suite passing; `tools/run_ui.py`'s net diff against the last commit is now empty, i.e. it reverted to exactly its original committed content). The Init dialog fixes from Session 3 (c)/(d) were explicitly **not** reverted and remain in `qt_ui_v2.py` regardless of which UI is the default launch target.

*(Note: the stale-comment fix from Session 3 (b) became inconsistent after this revert -- see Session 5.)*

### Session 5 -- Display-layer fixes: mojibake, AD2 table layout, stale comment

**What changed:**
- **Mojibake fix.** [qt_ui_v2.py:169](src/thermo_acoustic/qt_ui_v2.py:169) and [qt_ui_v2.py:481](src/thermo_acoustic/qt_ui_v2.py:481): the connection-status bullet character `"●"` (U+25CF) was replaced with ASCII `"*"`. Investigation found the source file's bytes were already valid UTF-8, but this Windows environment's default text codec is cp1252, which cannot encode U+25CF at all (reproduced a live `UnicodeEncodeError` when attempting to print it) -- a real, reproducible fragility class, not a one-off. This was the only place in the codebase using that character.
- **AD2 Output Parameters table layout fix.** [qt_ui_v2.py:239-275](src/thermo_acoustic/qt_ui_v2.py:239) (`_v2_ad2_output_group`, new `_size_ad2_output_columns` helper): the 10-column `QGridLayout` was moved into its own content widget inside a group-local `QScrollArea(setWidgetResizable=False)`, with per-column minimum widths computed from each header's/widget's actual `fontMetrics`/`sizeHint` rather than left unconstrained. Root cause: the *outer* experiment-area scroll area used `setWidgetResizable(True)`, which shrinks all its children (including this table) to fit the window, with no per-column minimums and no independent scroll fallback -- hence compression/truncation at moderate widths.
- **Stale comment fix.** [qt_ui.py:2043-2046](src/thermo_acoustic/qt_ui.py:2043): the comment above `main()` (added in Session 3, saying "for normal use, launch qt_ui_v2 instead") was corrected to reflect the Session 4 revert -- it now says `qt_ui.py` is the day-to-day entry point and `qt_ui_v2` is the in-development preview, not yet default.

**Why:** Two independently-reported display bugs (garbled status text, compressing table) plus a documentation-consistency fix left over from the entry-point revert.

**Files touched:** [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [qt_ui.py](src/thermo_acoustic/qt_ui.py), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py).

**Verification:** tested (offscreen render check confirmed pure-ASCII button text in both states; content widget's natural sizeHint measured at 2112x88px with per-column minimums like 264px for Frequency, 276px for Amplitude, 246px for Trigger Source, confirmed to persist -- i.e. produce a horizontal scrollbar rather than shrink -- even when the containing group box was resized to 300px). Not hardware-verified (display-only change, no hardware interaction).

Mid-way through this session, a mid-turn message requested a full repo-wide status audit (items 1-28 covering hardware safety, LabVIEW migration, valve, UI, data integrity, and logging). That audit was answered inline and made **no code changes**; it flagged several items as "NOT RE-VERIFIED THIS TURN" pending a dedicated pass, addressed next.

### Session 6 -- Read-only re-verification pass (no code changes)

Re-verified, with fresh file/line evidence (not memory), the items flagged as unverified in Session 5's audit: capture-start/stop try/finally, partial-init rollback, Qmix bus close, serial timeouts, DO clock derivation, AD2 wait including DO term, tdms metadata fields, frame timestamp status, pump flow-rate sign convention, FocusWheelGuard call sites, label cleanup, SynchronizeState disable, flush-failure handling, aborted-repeat handling, and logging usage. Findings from this pass are folded into this document's other entries. Two items were newly confirmed as genuinely still open at that point (addressed in Session 7): flush-failure return value ignored, and aborted/failed repeat not stopping the queue. The pump-flow-rate sign convention was found to be **unverifiable from current code** -- no sign-inversion logic exists anywhere in the pipeline, but no documented LabVIEW reference convention exists in-repo to compare against either.

### Session 7 -- Data-integrity fixes: flush failure, aborted repeat, logging

**What changed:**
- **Flush failure now surfaces as a real failure.** [application.py:369-382](src/thermo_acoustic/application.py:369): `run_experiment2()` now captures `flush()`'s return value; on `False` it logs via the new module logger, appends to `Application.errors`, fires status `"ExperimentFlushFailed"`, calls `experiment.cleanup()`, and returns `False` -- it no longer silently continues to `save_sequence`/`"ExperimentComplete"`.
- **Aborted/failed repeat now stops the series.** [qt_ui.py:1479-1489](src/thermo_acoustic/qt_ui.py:1479): `_run_experiment_series()`'s while loop now captures `run_experiment2()`'s return value; on `False` it logs the repeat index and last status, then raises `RuntimeError`, which propagates through the existing `ActionWorker`/`_handle_worker_finished` mechanism to set the Error Out UI fields and status, rather than continuing to drain the queue as if every repeat had succeeded.
- **Logging additions.** Module-level `logger = logging.getLogger(__name__)` added to `application.py` ([application.py:17](src/thermo_acoustic/application.py:17)) and `qt_ui.py` ([qt_ui.py:60](src/thermo_acoustic/qt_ui.py:60)), following the existing pattern already used in `hamamatsu_dcam.py`. `logger.error(...)` calls added at the two existing `self.errors`-only sites in `_cleanup_instruments()` ([application.py:190,197](src/thermo_acoustic/application.py:190)), plus at the two new failure points above. Scope was deliberately limited to failure paths, not a full instrumentation pass.
- **`ui.py` flagged, not removed.** Confirmed dead (592 lines, no importers anywhere in the repo, a separate Tkinter `MainWindow(tk.Tk)` unrelated to the live PySide6 UI), reported to the user for a removal decision but left in place.

**Why:** Two silent-failure gaps identified in Session 6's audit: a failed flush was invisible to the operator, and one repeat aborting/failing didn't stop the rest of an experiment series from running as if nothing had gone wrong.

**Files touched:** [application.py](src/thermo_acoustic/application.py), [qt_ui.py](src/thermo_acoustic/qt_ui.py), [tests/test_full_flow_dry_run.py](tests/test_full_flow_dry_run.py) (new flush-failure test), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (new series-stops-on-failure test).

**Verification:** tested (139 passing, including the 2 new tests added this session). Not hardware-verified (all exercised via fakes/monkeypatched `Application`/`flush`).

### Session 8 -- Frame timestamp investigation and implementation

**What changed:**
- **Investigation** established that the Hamamatsu DCAM SDK wrapper already bundled in this repo (`dcamsdk4/samples/python/dcam.py`/`dcamapi4.py`) exposes a real per-frame timestamp (`DCAMBUF_FRAME.timestamp`, a `DCAM_TIMESTAMP{sec, microsec}` struct filled by `dcambuf_copyframe`), retrievable via `Dcam.buf_getframe(iFrame)`. The existing code path (`_last_frame_copy()` at [hamamatsu_dcam.py:413](src/thermo_acoustic/hamamatsu_dcam.py:413), pre-change) called `buf_getlastframedata()` instead, which internally uses the same underlying call but discards the timestamp, returning only the pixel buffer. No new SDK linkage was required to fix this.
- Clock domain was found to be **unverifiable from this repo**: DCAM's `TIMESTAMP_PRODUCER` property can indicate camera-internal vs. host-driver clock, but the bundled Python wrapper doesn't expose the more detailed metadata-block API (`dcambuf_copymetadata`/`DCAM_TIMESTAMPBLOCK.timestampkind`, present only in the bundled C# sample) that would disambiguate which producer generated a given value, and no official Hamamatsu SDK documentation is present in this repo to resolve the `sec` field's epoch.
- **Implementation:** `_last_frame_copy()` ([hamamatsu_dcam.py:413-431](src/thermo_acoustic/hamamatsu_dcam.py:413)) now checks a cached `_timestamp_capability()` (via `dev_getcapability().is_support_timestamp()`) and, when supported, uses `buf_getframe(-1)` to retrieve both pixel data and timestamp, formatted as `"dcam_clock:{sec}.{microsec:06d}"` (deliberately *not* reformatted as a UTC datetime, to avoid asserting an unverified epoch). `image_sequence()` ([hamamatsu_dcam.py:212-235](src/thermo_acoustic/hamamatsu_dcam.py:212)) collects one such value per frame, all-or-nothing. A new `read_frame_timestamps()` method was added to `HamamatsuDcamBackend`, the `CameraBackend` Protocol, and the `HamamatsuCamera` facade ([instruments.py](src/thermo_acoustic/instruments.py)). `Application.run_experiment2()` ([application.py:350-351,385](src/thermo_acoustic/application.py:350)) now reads these and passes them to `Experiment2.save_image_data(image_data, frame_timestamps=...)` ([workflows.py:65-79](src/thermo_acoustic/workflows.py:65)), which uses them only when the count matches the frame count; **the original write-time fallback and its original explanatory comment are unchanged** for cameras/sessions where real timestamps aren't available.

**Why:** Closes the previously-flagged "frame Timestamp records write-time, not true acquisition time" gap -- but only where genuinely supported by the connected camera/driver, without fabricating a plausible-looking value where the epoch can't be confirmed.

**Files touched:** [hamamatsu_dcam.py](src/thermo_acoustic/hamamatsu_dcam.py), [instruments.py](src/thermo_acoustic/instruments.py), [application.py](src/thermo_acoustic/application.py), [workflows.py](src/thermo_acoustic/workflows.py), [tests/test_hamamatsu_dcam_lifecycle.py](tests/test_hamamatsu_dcam_lifecycle.py) (new fake DCAM module + test), [tests/test_application.py](tests/test_application.py), [tests/test_full_flow_dry_run.py](tests/test_full_flow_dry_run.py) (fake camera/Dcam updated to implement the new methods so existing tests keep exercising the write-time fallback).

**Verification:** tested (140 passing, including a new test confirming 3 captured frames produce 3 distinct `dcam_clock:`-prefixed values rather than one shared write-time value). **Not hardware-verified** -- built entirely against fake DCAM modules in this pass; whether a real connected camera reports `is_support_timestamp() == True`, and what its `TIMESTAMP_PRODUCER`/epoch actually are, has not been checked against real hardware.

### Session 9 -- Research-software risk audit (no code changes)

Read-only audit of five classic research-instrument-software risk classes, independent of any LabVIEW comparison. Findings, each confirmed by tracing the actual call path at the time:
- **SeriesPath overwrite protection: confirmed real gap.** `create_folder_and_tdms()`'s `mkdir(parents=True, exist_ok=True)` and `_write_tdms()`'s default-mode `TdmsWriter` both proceed silently over existing data; no pre-flight check existed anywhere in `_start_experiment()`.
- **Physical parameter bounds checking: confirmed real gap** beyond the already-known Camera-FPS>0 check -- WFG amplitude/frequency spin boxes used the shared `_spin()` factory's generic `-1e12..1e12` bounds with no physically-meaningful ceiling, and the flush-volume-vs-syringe-capacity relationship was unchecked at the time (this pass identified `FlushSettings.syringe_volume_ml` was hardcoded to 60.0 regardless of the actual UI-selected syringe -- fixed in Session 10 below).
- **Mid-acquisition disconnect: mostly handled, one real gap.** Camera faults during `image_sequence()` already raised clear errors with cleanup (not silent, not a hang), but already-captured frames from before the fault were discarded rather than saved -- fixed in Session 10. Valve/pump disconnect handling relies on the underlying pyserial/Qmix SDK raising on its own; not verified against real hardware.
- **TDMS write verification: confirmed real gap, explicitly deferred.** `_write_tdms()`'s only "verification" is that `TdmsWriter.write_segment()` didn't raise -- no re-open, size check, or field-count assertion exists. Flagged but intentionally not fixed in any subsequent session (out of scope by explicit instruction each time it came up again).
- **Git commit history: found a commit had been made.** A fresh check at the time of this audit found commit `3474232` ("Migrate hardware safety, DO-clock/LED timing, valve protocol, and data-integrity fixes from LabVIEW port", 2026-07-23) now sitting on top of the previously-observed `5419043` HEAD -- made outside this conversation (not by any `git commit` run here). Confirmed `data.tdms` metadata did not record a git commit hash at that time (fixed in Session 10).

**Verification:** read-only, no tests changed.

### Session 10 -- Data-safety/validity fixes: SeriesPath overwrite, partial-capture preservation, syringe volume wiring, git commit hash

**What changed:**
- **SeriesPath overwrite confirmation.** [qt_ui.py:1492-1518](src/thermo_acoustic/qt_ui.py:1492) `_start_experiment()` now calls `_series_path_has_existing_data()` (recursive `rglob` for `data.tdms`/`frame_*.tiff`) before building the series; if found, a `QMessageBox.question(Yes|No, default No)` (same pattern as the pre-existing pump reference-move confirmation) must be confirmed before proceeding. Declining causes zero side effects -- checked before any folder is created.
- **Partial-capture preservation.** [hamamatsu_dcam.py:213-252](src/thermo_acoustic/hamamatsu_dcam.py:213): `image_sequence()` gained an `except Exception:` clause that, when frames were already captured before a mid-sequence fault and a `partial_capture_folder` was supplied, saves them via the existing `save_sequence()` TIFF path into a `partial_{captured}_of_{total}` subfolder and logs via `logger.error`, then bare-`raise`s -- the original failure still propagates unsuppressed, only the already-good data is rescued. `CameraBackend.image_sequence()`'s signature and `Application.run_experiment2()`'s call site were threaded through to pass the already-created `experiment_folder`.
- **Syringe volume wiring.** [qt_ui.py:1176-1195](src/thermo_acoustic/qt_ui.py:1176): added a "Custom Volume (ml)" field ([qt_ui.py:440](src/thermo_acoustic/qt_ui.py:440)) and `_syringe_volume_ml()`/`_flush_settings()` now map "BD 1ml"/"BD 5ml"/"BD 10ml" to 1.0/5.0/10.0 mL (previously always a hardcoded 60.0 regardless of selection). `Application.flush()` ([application.py:300-305](src/thermo_acoustic/application.py:300)) now raises `ValueError` immediately, before touching valve/pump, if `flush_volume_ml > syringe_volume_ml`.
- **Git commit hash in metadata.** [workflows.py:16-43](src/thermo_acoustic/workflows.py:16): `_git_commit_hash()` (subprocess `git rev-parse HEAD` + `-dirty` suffix from `git status --porcelain`, `lru_cache`d, falls back to `"unknown"` on any failure) added to `_settings_properties()`'s `"GitCommitHash"` field ([workflows.py:133](src/thermo_acoustic/workflows.py:133)).

**Why:** Closes three of the five gaps identified in Session 9's audit, plus adds dataset provenance tracking.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [hamamatsu_dcam.py](src/thermo_acoustic/hamamatsu_dcam.py), [instruments.py](src/thermo_acoustic/instruments.py) (`CameraBackend` Protocol / `HamamatsuCamera` facade signature threading), [application.py](src/thermo_acoustic/application.py), [workflows.py](src/thermo_acoustic/workflows.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (`test_start_experiment_blocks_on_existing_data_until_confirmed`, `test_syringe_selection_and_custom_volume_flow_into_flush_settings`), [tests/test_hamamatsu_dcam_lifecycle.py](tests/test_hamamatsu_dcam_lifecycle.py) (`test_image_sequence_saves_partial_capture_on_mid_sequence_fault`), [tests/test_application.py](tests/test_application.py) (git-commit-hash test), [tests/test_full_flow_dry_run.py](tests/test_full_flow_dry_run.py) (fake signature updates).

**Verification:** tested. Not hardware-verified (all exercised via fakes/offscreen Qt).

### Session 11 -- Exhaustive LabVIEW-to-Python migration completeness audit (no code changes)

Read-only, using `labview_ports.py`'s VI registry as the starting inventory per the requested method, but the audit's most significant finding was that **the registry itself is materially incomplete** relative to the actual LabVIEW project at `C:\git\thermacoustics` (a separate git repo with real `.vi`/`.lvproj` files, distinct from the static HTML export that seeded `labview_ports.py`/`labview_manifest.json` at this repo's very first commit and was never regenerated since):
- `AD2_MSO_SDK_class` has 17 real VIs; the registry documents only 1 (`AD2_MSO_SDK_Init.vi`).
- `AD2_SDK_class`, `AD2_WFG_SDK_class`, `AD2_DO_SDK_class` are each missing several member VIs from the registry (including a WFG frequency-sweep VI present in the LabVIEW project since 2025-01-16 -- see Session 15).
- Entire classes are undocumented: `TDMSlogg_class` (dedicated TDMS logging), `REGLO Digital` (a peristaltic pump driver -- confirmed referenced directly in `Main.vi`'s own front-panel image list), `Application.lvclass:SaveData.vi`.
- `AFG3022B_class` and `Experiment_class` (non-"2") were confirmed genuinely orphaned (absent from `ThermoAcousticStreaming.lvproj` entirely, not just from the registry) -- correctly out of scope, not a gap.
- Two confirmed dead Python widgets found via the reverse (Python-UI-consumption) check: `capture_mode` combo ([qt_ui.py:468,939](src/thermo_acoustic/qt_ui.py:468)) and the Sequence group's `sequence_exposure_ms` field ([qt_ui.py:473,944](src/thermo_acoustic/qt_ui.py:473)) are both constructed and displayed but never read by `_camera_sequence_settings()` -- the same class of bug as the syringe-volume/Camera-FPS cases, still unfixed as of this writing.

**Verification:** read-only, no tests changed. No fixes applied in this session for any of the above; `RegloPumpControl` ([instruments.py:142-146](src/thermo_acoustic/instruments.py:142)) remains a bare 4-field dataclass with zero methods/wiring.

### Session 12 -- Domain-knowledge sanity review (no code changes)

Read-only review of current Python logic against known manufacturer/SDK conventions (Hamamatsu DCAM, Digilent WaveForms, Cetoni/Qmix, Rheodyne/IDEX MX valve), independent of LabVIEW comparison. Findings:
1. **Camera trigger source: confirmed HIGH-risk gap.** `run_experiment2()`'s experiment path never set DCAM `TRIGGERSOURCE` at all -- `configure_sequence()` only sets it `if "trigger_source" in self.sequence_settings`, and the experiment-path `sequence_settings` dict never included that key. The camera would run in whatever trigger-source state a prior manual-tab session happened to leave it in. Fixed in Session 13.
2. **Exposure vs. readout timing: confirmed gap, not yet fixed.** Nothing checks `exposure_ms/1000 + readout_time <= 1/camera_fps`; an invalid combination is silently accepted and would produce a different actual frame rate than the one used to derive the LED/DO clock. Still open.
3. **AD2/WaveForms trigger ordering: matches SDK convention, no gap.** `config_wfg()`/`config_do_clock_special()` (both arming via `Configure(..., start=1)`) run before `pc_trigger()`/`FDwfDeviceTriggerPC`, matching the documented "arm all channels via `trigsrcPC`, then fire one shared trigger" pattern.
4. **Qmix fill-level semantics: confirmed HIGH-risk gap.** `QmixPumpBackend._coerce_fill_level_ml()`'s `0.0-1.0` range heuristic (guess fraction vs. absolute mL) directly conflicted with the manual Pump&Valve tab's "Level(ml)" control, which is explicitly absolute mL -- any legitimate small absolute value under 1.0 mL was silently misread as a percentage. Fixed in Session 13.
5. **Valve timing before flush: confirmed HIGH-risk gap.** `Application.flush()` used a fixed `self.wait(1.0)` sleep after `valve.set_position(1)` rather than the already-implemented `"S\r"` ready-query handshake (which existed only at `Valve.initialize()` time). Fixed in Session 13.

**Verification:** read-only, no tests changed.

### Session 13 -- Camera trigger source, Qmix fill-level, valve ready-check fixes

**What changed:**
- **Camera trigger source made explicit.** [qt_ui.py:1536-1547](src/thermo_acoustic/qt_ui.py:1536): the experiment-path `sequence_settings` dict now always includes `"trigger_source": "Internal"`, with a comment explicitly stating that whether this *should* be `"External"` (paced by the AD2 DIO pulse train, matching the DIO0/DIO1-triggered transducer/LED) is still open pending oscilloscope verification -- this only removes the undefined-leftover-state risk, it does not resolve internal-vs-external.
- **Qmix fill-level unit ambiguity removed.** `QmixPumpBackend._coerce_fill_level_ml()` was deleted entirely; `set_fill_level()` ([qmix_backend.py:137-146](src/thermo_acoustic/qmix_backend.py:137)) now passes `float(fill_level)` straight through, always absolute mL. `FlushSettings.fill_level_delta` (the fraction-producing property) was removed as now-dead code rather than left as a misleading no-op; `Application.flush()` ([application.py:310-313](src/thermo_acoustic/application.py:310)) was converted from fraction-ratio math to plain absolute-mL subtraction (`self.pump.fill_level - settings.flush_volume_ml`). Every caller of `set_fill_level`/`.fill_level` was traced: the manual "Go to Level" button and the dead `ui.py` Tkinter equivalent already intended absolute mL (now correctly so instead of accidentally-sometimes-correct); `Application.flush()` was the only caller that needed converting.
- **Valve ready-check reused during flush.** New `Valve.wait_until_ready(timeout_s=1.0, poll_interval_s=0.05)` ([instruments.py:734-752](src/thermo_acoustic/instruments.py:734)) reuses the existing `_apply_status_response` parsing to poll the `"S\r"` handshake; a real disconnect (empty response) still raises `ValveError` immediately, only a persistently "busy" result is tolerated up to the timeout (matching the old fixed-sleep's ceiling, so no new hang risk). `Application.flush()` ([application.py:307-320](src/thermo_acoustic/application.py:307)) now calls it after **both** `set_position(1)` and `set_position(2)`, replacing the fixed `self.wait(1.0)`.

**Why:** Three confirmed HIGH-risk data-validity/safety gaps from Session 12's domain review.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qmix_backend.py](src/thermo_acoustic/qmix_backend.py), [workflows.py](src/thermo_acoustic/workflows.py), [instruments.py](src/thermo_acoustic/instruments.py), [application.py](src/thermo_acoustic/application.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (`test_experiment_sequence_settings_set_explicit_deterministic_trigger_source`), [tests/test_application.py](tests/test_application.py) (`test_qmix_set_fill_level_treats_value_as_absolute_ml_not_fraction`, `test_valve_wait_until_ready_polls_until_confirmed_and_is_bounded_when_busy`, updated `test_flush_sets_valve_and_status` and one assertion in the existing Qmix backend test that had locked in the old scaling behavior).

**Verification:** tested. Not hardware-verified (no real DCAM/Qmix/valve hardware exercised).

### Session 14 -- Frequency Scanning / Dynamic Frequency investigation (no code changes, NOT implemented)

Read-only investigation of `FrequencyHelper.vi` and the updated `ExperimentSeries2:CreateExperiments.vi` (commit `8f8e255`, "Updated with Frequency Scanning", 2026-06-18, in `C:\git\thermacoustics`), using zlib-stream decompression of the front-panel/connector-pane data blocks (the block-diagram wiring logic itself is compiled and not readable this way). Findings: `FrequencyHelper.vi` generates a linear array of frequencies from Start/Stop/Number-of-Frequencies inputs; `CreateExperiments.vi` gained matching `Dynamic Frequency` (bool) and `Frequency List` (array) inputs, architecturally parallel to the already-ported `Dynamic Camera Start Time`/`Camera Start Array(s)` mechanism -- i.e. per-repeat substitution of Channel 1's carrier frequency from `Frequency List[repeat]`, not a new experiment-count expansion. The Python gap identified: `_build_experiment_series()` builds its `WfgConfig` once, outside the per-repeat loop, and reuses the same object for every repeat -- unlike the DO clock, which is already rebuilt per-repeat.

**This was investigation only, explicitly framed as "the spec for the actual port, do not implement anything yet."** A fresh check of the current code at the time of writing this log confirms it still hasn't been implemented: `_build_experiment_series()` ([qt_ui.py:1520-1522](src/thermo_acoustic/qt_ui.py:1520)) still builds `config` once, outside the loop, and passes the same object to every repeat's `Experiment2`. There is no `dynamic_frequency`/`frequency_list` state anywhere in `qt_ui.py`. (The unrelated `dynamic_frequency: bool = False` field in `experiment_presets.py:49`'s `LabviewExperimentPreset` is a recorded LabVIEW-screenshot value in a separate preset-transcription dataclass, not a functioning implementation of this feature.)

**Verification:** read-only, no code changes, no tests.

### Session 15 -- FM Sweep (millisecond-scale continuous sweep) investigation (no code changes)

Read-only investigation of `AD2_WFG_SDK.lvclass:WfgConfigureSweepCh1.vi`/`BasicSweepSettings.ctl` -- a second, distinct feature from Session 14's Frequency Scanning (this one sweeps continuously within a single acoustic drive at ~1ms timescale, rather than running one discrete experiment per frequency point). Same zlib-decompression method. Findings: `BasicSweepSettings.ctl` defines per-channel Enable Sweep / Function / Carrier Amplitude / Sweep Type (Symmetric/RampUp/RampDown) / Sweep Repetition Rate (Hz) / Sweep Width (% of Center Freq) / Center Frequency controls; `WfgConfigureSweepCh1.vi` calls the same `WFGConfigure.vi` already ported as `waveforms.py`'s `configure_wfg()`, and its own data contains the `FM Mod` sub-cluster -- confirming this maps to the AD2's existing FM modulation node (node=1), not a separate SDK mechanism. Confirmed via a sanity-checked grep of `RunExperiment2.vi`'s full sub-VI call list, `Main.vi`'s event table, and all 14 `AD2_SDK.lvclass` member VIs that **this sweep mechanism is not reachable from the real LabVIEW experiment path either** -- though it *is* a registered member of `AD2_WFG_SDK.lvclass` in `ThermoAcousticStreaming.lvproj` (unlike the confirmed-orphaned `AFG3022B_class`), so it's a real but experiment-path-unreachable calibration tool in the original LabVIEW project too. Also confirmed the Python "FM Mod" UI group ([qt_ui.py](src/thermo_acoustic/qt_ui.py), manual WFG tab) was *not* fully dead as initially assumed -- it was already wired end-to-end to real `FDwfAnalogOutNode*` SDK calls via the manual "Apply WFG" path, just hardcoded off (`enable=False`) on the Experiment-tab path.

**Verification:** read-only, no code changes, no tests.

### Session 16 -- FM Sweep calibration feature implementation

**What changed:**
- **Shared translation logic.** New `FmSweepSettings` dataclass ([ad2.py:85-163](src/thermo_acoustic/ad2.py:85)): `center_hz`/`width_hz`/`sweep_time_ms`/`sweep_type`, with `__post_init__` rejecting `sweep_time_ms <= 0` before any division, and computed properties `top_hz`/`bottom_hz` (`center +- width/2`), `fm_frequency_hz` (`1000/sweep_time_ms`), `fm_amplitude_pct` (`width_hz/center_hz*100`), `fm_function` (Symmetric->Triangle, RampUp->RampUp, RampDown->RampDown), and `fm_mod_settings()` producing the actual `CarrierSettings` for the FM node. Reference test case documented directly in the docstring: Martens et al. (PhysRevApplied.23.024043) -- "actuation frequency centered at 1.934 MHz with a sweep of 50 kHz and a sweep time of 1 ms."
- **Manual WFG tab (Task 1).** Per-channel Enable Sweep / Center Frequency (MHz) / Sweep Width (kHz) / Sweep Time (ms) / Sweep Type controls added to `_make_wfg_channel_state()`/`_wfg_channel_group()` ([qt_ui.py:560-566,715-733](src/thermo_acoustic/qt_ui.py:560)), plus live-refreshing Top/Bottom Frequency sanity-check labels. `_channel_config()` ([qt_ui.py:1054-1086](src/thermo_acoustic/qt_ui.py:1054)) applies the override -- when Enable Sweep is checked, `carrier.frequency_hz`/`carrier.enable`/`fm_mod` are all overridden via `FmSweepSettings`; when unchecked, behaves exactly as before. Reuses the existing "Apply WFG" -> `config_wfg()` path unchanged.
- **Experiment tab, operator toggle (Task 2).** New `exp_sweep_enable` ("Enable Frequency Sweep During Experiment", off by default) plus matching Center/Width/Time/Type widgets ([qt_ui.py:487-491,1011-1015](src/thermo_acoustic/qt_ui.py:487)). `_experiment_channel_config()` ([qt_ui.py:1128-1163](src/thermo_acoustic/qt_ui.py:1128)) applies the same `FmSweepSettings` override **only to Channel 0 (index 0)**, matching `WfgConfigureSweepCh1.vi`'s own Ch1-hardcoded scope found in Session 15. Toggle off is bit-for-bit identical to the pre-existing hardcoded `fm_mod` values.
- **Metadata (Task 3).** `Experiment2.fm_sweep: FmSweepSettings | None = None` field ([workflows.py:71](src/thermo_acoustic/workflows.py:71)) and `_fm_sweep_properties()` ([workflows.py:144,147-162](src/thermo_acoustic/workflows.py:144)) write `FMSweepEnabled`/`FMSweepCenterHz`/`FMSweepWidthKHz`/`FMSweepTimeMs`/`FMSweepType` into `data.tdms`, following the existing empty-string-when-inactive pattern already used for DO/WFG channel properties.

**Why:** Implements the feature spec'd in Session 15, for both standalone calibration use and as an operator-controlled option during real automated experiments.

**Files touched:** [ad2.py](src/thermo_acoustic/ad2.py), [qt_ui.py](src/thermo_acoustic/qt_ui.py), [workflows.py](src/thermo_acoustic/workflows.py), [tests/test_application.py](tests/test_application.py) (`test_fm_sweep_settings_match_martens_et_al_reference_case`, `test_fm_sweep_settings_rejects_non_positive_sweep_time`), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (`test_fm_sweep_toggle_off_preserves_existing_experiment_behavior`, `test_fm_sweep_toggle_on_carries_settings_into_experiment_wfg_config`).

**Important distinction from the rest of this log:** unlike every other LabVIEW-parity item recorded above, **the underlying LabVIEW mechanism this mirrors (`WfgConfigureSweepCh1.vi`) was itself never reachable from `RunExperiment2.vi`/`Main.vi` in the original LabVIEW project** (Session 15). This session's Experiment-tab integration (Task 2) is therefore a **Python-only integration into the automated experiment path** -- there is no real, reachable LabVIEW code path being mirrored for that specific piece, unlike the rest of this log where Python mirrors an actual reachable LabVIEW mechanism. The manual-tab piece (Task 1) does mirror a real (if experiment-path-unreachable) LabVIEW VI.

**Verification:** tested. Not hardware-verified. Three assumptions explicitly flagged as unverifiable from LabVIEW's binary or the literature (carried into both the code's own docstring/comments and this log):
1. **Sweep-Type -> Function enum mapping** (Symmetric->Triangle, RampUp->RampUp, RampDown->RampDown) is the most architecturally plausible correspondence given the shared `Function 2` enum, not a confirmed one.
2. **Dual-enable semantics** (Enable Sweep forcing both `Carrier.enable=True` and `fm_mod.enable=True`) is this feature's own designed convention, not confirmed against `WfgConfigureSweepCh1.vi`'s actual wiring.
3. **Width interpreted as total span** (`Top = Center + Width/2`) was an explicit user unit decision, not independently re-derived from the Martens et al. paper (which states "a sweep of 50 kHz" without specifying half- vs. full-span convention).

### Session 17 -- Syringe inner-diameter correction

**What changed:** Investigated exactly what `SYRINGE_PRESETS` feeds into: traced `configure_syringe()` ([qmix_backend.py:141-168](src/thermo_acoustic/qmix_backend.py:141)) to `pump.set_syringe_param(float(inner_diameter), float(stroke))`, where `pump` is a genuine instance of the vendor Qmix SDK's `Pump` class -- confirmed against the actual bundled SDK source (`qmix_sdk_for_codex/python/qmixsdk/qmixpump.py:149-158`, `LCP_SetSyringeParam`), which has **no internal model/name database**; Python must supply correct raw geometry. Compared against authoritative BD syringe inner diameters (1mL=4.78mm, 5mL=12.07mm, 10mL=14.5mm): found `"BD 5ml"` was `12.06mm` (off by 0.01mm, a ~0.33% volume/flow-rate calibration error), corrected to `12.07mm` ([qmix_backend.py:25-34](src/thermo_acoustic/qmix_backend.py:25)); `"BD 1ml"` (4.78) and `"BD 10ml"` (14.50) were already correct. Confirmed no other logic depended on the old value: the earlier syringe-volume-vs-flush-capacity fix (Session 10) uses only nominal capacity in mL (`_SYRINGE_VOLUMES_ML`), entirely independent of `SYRINGE_PRESETS`'s diameter values.

**Why:** Confirmed data-accuracy issue found by request, comparing against BD's own published spec values.

**Files touched:** [qmix_backend.py](src/thermo_acoustic/qmix_backend.py), [tests/test_application.py](tests/test_application.py) (`test_syringe_presets_match_authoritative_bd_inner_diameters`).

**Verification:** tested (152 passing as of this writing). Not hardware-verified. Stroke length (the second `set_syringe_param` argument) remains a *derived* value (`volume / cross-sectional area`, assuming the full nominal volume fills the entire piston travel in a cylindrical bore) rather than an independently-sourced BD spec figure -- flagged in a code comment as unresolved since no authoritative real stroke-length value was available to verify against.

### Session 18 -- Hardcoded physical/hardware constants audit (no code changes)

Read-only, repo-wide sweep for embedded numeric constants that represent a real-world value -- the same bug class as Session 17's syringe-diameter fix (logically correct, tests pass, but one embedded number silently doesn't match reality) -- but broader in scope: clock frequencies, baud rates, response-time timeouts, and default WFG/DO/MSO parameter values. This audit had never been run before under this scope (confirmed by grepping this document, `git log --all`, and every other markdown file in the repo before starting -- see the prior turn's absence check). Covered `ad2.py`, `waveforms.py`, `instruments.py`, `qmix_backend.py`, `hamamatsu_dcam.py`, `qt_ui.py`, `application.py`, `experiment_presets.py`. Full classification (CONFIRMED-CORRECT / SUSPECTED-PLACEHOLDER / UNCONFIRMED) of every constant examined:

| Constant / value | Location | Represents | Classification |
|---|---|---|---|
| `roi_v_offset=900`, `roi_v_size=500`, `exposure_ms=50.0` (live UI startup defaults) | [qt_ui.py:449-452](src/thermo_acoustic/qt_ui.py:449) | Camera sub-array ROI vertical offset/size and exposure at app startup | **SUSPECTED-PLACEHOLDER** -- diverges from this repo's own validated-on-real-hardware combination (`vertical_offset=792`, `vertical_size=740`, `exposure_ms=40.0`; C15440-20UP; see `docs/current_workflow_audit.md`'s "Validated Hardware Milestones" and `experiment_presets.py`'s `LabviewCameraPreset`). `experiment_presets.py` is never imported by `qt_ui.py` (confirmed via grep) so nothing wires the validated numbers into the live defaults. |
| `SerialTextCommandBackend.baud_rate = 19200` as used for `PriorZMotor` | [hardware_factory.py:59](src/thermo_acoustic/hardware_factory.py:59), default from [instruments.py:39](src/thermo_acoustic/instruments.py:39) | Serial baud rate for the Prior Z-motor controller | **UNCONFIRMED** -- this default is hardware-confirmed for the Rheodyne MX *valve* only (Session 2/baseline); the Prior Z-motor backend is built with the same class default with no independent check against the Prior controller's protocol. Low current risk only because the Prior COM7 Z-stage path is separately documented as legacy/obsolete (`docs/current_workflow_audit.md`, `docs/labview_migration_completeness_audit.md`) -- current Z hardware is Thorlabs/APT. |
| `range_v=1.0` (V) default | [instruments.py:317,345](src/thermo_acoustic/instruments.py:317), [waveforms.py:651,695](src/thermo_acoustic/waveforms.py:651), `qt_ui.py`'s `mso_range` | MSO/scope analog-in voltage range | **SUSPECTED-PLACEHOLDER** -- `docs/current_workflow_audit.md` records the real acoustic drive signal at up to `2 V` (CH0); the 1 V default would clip that channel if scoped without first widening the range. User-editable, not enforced or warned. |
| `QmixPumpBackend.reference_move_timeout_s=60.0` | [qmix_backend.py:45](src/thermo_acoustic/qmix_backend.py:45) | Max wait for a real syringe-pump calibration/homing move | **UNCONFIRMED** -- no cited Qmix/neMESYS spec value found anywhere in this repo; plausible engineering guess, tested only via fakes. |
| `QmixPumpBackend.close_timeout_s=5.0` | [qmix_backend.py:53](src/thermo_acoustic/qmix_backend.py:53) | Max wait for real Qmix bus/pump close | **UNCONFIRMED** -- same basis as above. |
| `Application.cleanup_device_timeout_s=5.0` / `cleanup_total_timeout_s=15.0` | [application.py:35-36](src/thermo_acoustic/application.py:35) | Max wait for each/all real instrument cleanup calls | **UNCONFIRMED** -- not tied to any manufacturer-documented response time in this repo. |
| `HamamatsuDcamBackend.frame_total_timeout_s=30.0` | [hamamatsu_dcam.py:31](src/thermo_acoustic/hamamatsu_dcam.py:31) | Max total wait for a real DCAM frame-ready event | **UNCONFIRMED** -- already known not-hardware-verified (Category A baseline); not classified against a real timing basis until now. |
| `HamamatsuDcamBackend.timeout_ms=1000` | [hamamatsu_dcam.py:30](src/thermo_acoustic/hamamatsu_dcam.py:30) | Per-iteration DCAM frame-ready poll timeout | **UNCONFIRMED** -- common DCAM-sample default, not verified against this camera's real worst-case frame period (compounds the already-flagged missing exposure-vs-readout check). |
| `Valve.wait_until_ready(timeout_s=1.0, poll_interval_s=0.05)` as used in `Application.flush()` | [instruments.py:734](src/thermo_acoustic/instruments.py:734), [application.py:308,320](src/thermo_acoustic/application.py:308) | Max wait for the real valve to report ready between flush steps | **UNCONFIRMED** -- chosen in Session 13 only to match the old fixed-sleep's ceiling ("no new hang risk"), not calibrated against the valve's real switching time. |
| `CarrierSettings.frequency_hz=1000.0`/`amplitude_v=1.0` dataclass defaults, and the identical disabled-fm_mod defaults in `qt_ui.py` | [ad2.py:55-56](src/thermo_acoustic/ad2.py:55), [qt_ui.py:553-554,1138-1140](src/thermo_acoustic/qt_ui.py:1138) | WFG FM-modulation node fallback carrier | **CONFIRMED-CORRECT (inert)** -- traced `waveforms.py:394` (`if channel.fm_mod.enable:`): the node is never written to hardware while disabled, and `fm_enable`/`enable=False` is the default everywhere these values appear, so they are genuinely dead numbers. |
| Same `1000.0`/`1.0` pair as `coerce_carrier_settings()`'s fallback for an *enabled* channel built from an incomplete dict | [ad2.py:256-257](src/thermo_acoustic/ad2.py:256) | WFG carrier frequency/amplitude when config data is missing | **SUSPECTED-PLACEHOLDER (latent)** -- not reachable from the live UI (which always supplies real widget values) but reachable from any future code path that loads a WFG config from a partial dict/JSON; would silently drive 1000 Hz/1 V instead of erroring. |
| `exp_ch2_freq=1000.0`, `exp_ch2_amp=1.0` startup defaults | [qt_ui.py:492-493](src/thermo_acoustic/qt_ui.py:492) | Channel-2 WFG starting values (channel disabled by default) | **CONFIRMED-CORRECT** -- matches `experiment_presets.py`'s own `LabviewWfgChannelPreset(index=1, frequency_hz=1000.0, amplitude_v=1.0)`, i.e. the in-repo LabVIEW-screenshot reference agrees with the live default here (unlike the ROI/exposure case above). |
| DCAM `masterpulse_interval_s` bounds `(0.000005, 10.0)` and `trigger_delay_s` bounds `(0.0, 10.000002)` | [hamamatsu_dcam.py:144,176](src/thermo_acoustic/hamamatsu_dcam.py:144), mirrored in `qt_ui.py`'s `sequence_interval`/`external_delay` spin boxes | DCAM property valid ranges | **CONFIRMED-CORRECT** -- precise, non-round values consistent with a real DCAM property-range query against the C15440-20UP rather than a guessed constant. |
| AD2 internal digital-out clock frequency | [waveforms.py:551-554](src/thermo_acoustic/waveforms.py:551), used by `configure_do()` | Hz value used to derive the DO clock divider | **CONFIRMED-CORRECT (not hardcoded)** -- queried live via `FDwfDigitalOutInternalClockInfo` every time, in both the DO-clock and FM-sweep paths; noted here to confirm no hardcoded divider/clock-frequency default exists outside the already-verified DO-clock path. |
| `mso_sample_frequency` max bound `100_000_000.0` (100 MS/s) | `qt_ui.py`'s `mso_sample_frequency` spin box | AD2 analog-in max sample rate | **UNCONFIRMED** -- plausible match to Digilent's published Analog Discovery 2 scope spec, but not independently re-verified against this device in this pass; treat as a reasonable default, not a confirmed one. |
| Syringe stroke length (`_syringe_stroke_mm()`) | [qmix_backend.py:20-22,25-36](src/thermo_acoustic/qmix_backend.py:20) | Qmix `set_syringe_param()`'s second (stroke) argument | **UNCONFIRMED** -- already tracked from Session 17, not re-derived here; listed only for completeness of this pass's scope. |
| `Valve.baud_rate=19200`, `command_position_1/2="P01"/"P02"`, `line_ending="\r"` | [instruments.py:39,688-689](src/thermo_acoustic/instruments.py:39) | Valve serial protocol | **CONFIRMED-CORRECT** -- hardware-confirmed against the real Rheodyne MX valve (baseline/Session 2); re-listed here only for completeness, not re-derived. |

**Why:** Closes the scope gap identified when the user asked whether this class of audit had ever been run -- it had not (confirmed absent from this log, `git log --all`, and every other repo doc before this session started).

**Verification:** read-only, no code changes, no tests.

### Session 19 -- Camera trigger source re-investigation (LabVIEW diagram trace, still unresolved) + DCAM readout-timing bounds check implemented

Two corrections to Session 18's write-up, requested explicitly by the user: (1) Session 18 had not actually traced `RunExperiment2.vi`'s real call path for camera trigger source -- it only had the front-panel screenshot's "Internal" as context, which is a snapshot of one manual-panel state and must not be used as a tiebreaker; (2) the "476 is Vertical is max for 100 fps" text was mischaracterized -- it is DCAM's own live-computed readback for the *current* ROI/fps combination, not a static constant, and Python's equivalent (or lack of one) needed to be checked.

**(1) Camera trigger source -- traced in `C:\git\thermacoustics` via the same zlib-decompression method as Sessions 14-15.** Confirmed real call chain: `RunExperiment2.vi` calls `Experiment2.lvclass:GetSequenceSettings.vi` (a plain property-getter for a `SequenceSettings` cluster -- which includes a `Dcam Trigger Source` field, a 4-way enum: Internal/External/Software/Master Pulse) and passes the result into `Hamamatsu_class:ConfigureSequence.vi`, which in turn calls `tm_inputtriggersource_40.vi` (the real Hamamatsu DCAM DLL call that writes `DCAM_IDPROP.TRIGGERSOURCE`), `tm_setmasterpulse_40.vi`, and `tm_setoutputtrigger_40.vi` -- confirming this is architecturally the same mechanism Python's `configure_sequence()`/`"trigger_source"` mapping mirrors. There is no separate `SetSequenceSettings.vi`; the `SequenceSettings` cluster (including `Dcam Trigger Source`) is populated once, at experiment-creation time, inside `ExperimentSeries2_class:CreateExperiments.vi`, which calls `Experiment2_class:Experiment2_Init.vi` as the object's constructor. **What value `CreateExperiments.vi` actually wires into that field could not be determined from the exported diagrams**: decompressing all three VIs (`RunExperiment2.vi`, `CreateExperiments.vi`, `Experiment2_Init.vi`) recovers only the `SequenceSettings` cluster's typedef structure and its enum item strings (`Internal`/`External`/`Software`/`Master Pulse`) -- never which one is wired to the field on the block diagram, because that wiring is compiled binary, not text, exactly the same limitation already hit in Sessions 14-15 for Frequency Scanning and FM Sweep. **Per the user's explicit instruction, the front-panel screenshot's "Internal" value is not used as a tiebreaker and is discarded from evidence entirely.** Net result: this question remains genuinely unresolved -- Session 13's Python-side hardcoded `"Internal"` (`qt_ui.py:1546`) is unchanged and is still only a leftover-state-risk removal, not a confirmed-correct value, exactly as Session 13 already stated.

**(2) DCAM readout-timing bounds check -- gap confirmed and now implemented.**
- **(a) Gap confirmed.** Grepped `hamamatsu_dcam.py`, `instruments.py`, and `qt_ui.py` for any existing max-ROI-at-current-fps computation: none existed. The "476 is Vertical is max for 100 fps" text turned out to be **hardcoded static UI label text** in Python itself ([qt_ui.py:901](src/thermo_acoustic/qt_ui.py:901), and identically in the dead `ui.py:298`), copied from the LabVIEW screenshot as a hint, not wired to any computation -- i.e. Python was reproducing LabVIEW's *displayed number* without reproducing the *live readback* that produced it. The real DCAM property this LabVIEW readback is derived from is `DCAM_IDPROP_TIMING_READOUTTIME` (confirmed via the bundled `dcamsdk4/doc/camera_properties/propC15440-20UP_en.html` -- our exact camera model -- a read-only property returning "seconds how long takes to reading out a frame," which depends on the currently configured vertical ROI size and readout speed). Python already reads this exact property -- `HamamatsuDcamBackend.read_readout_time()` / `HamamatsuCamera.read_readout_time()` ([hamamatsu_dcam.py:303](src/thermo_acoustic/hamamatsu_dcam.py:303), [instruments.py:588](src/thermo_acoustic/instruments.py:588)) -- but nothing previously used its result to validate anything; it was only ever recorded into `data.tdms` metadata after the fact.
- **(b) Implemented.** This is the concrete implementation of Session 12's deferred "exposure vs. readout timing" item. Added `Application._check_camera_timing_budget()` and `Application._configured_camera_fps()` ([application.py:278-306](src/thermo_acoustic/application.py:278), called from `run_experiment2()` at [application.py:347](src/thermo_acoustic/application.py:347), right before `camera.start_capture()`): reads the target camera FPS from the enabled DO-clock channel's `clock_frequency_hz` (the only place that value is recorded on `Experiment2`), queries the real `camera.read_readout_time()` for whatever ROI is currently configured, computes `achievable_fps = 1 / (exposure_s + readout_s)`, and raises `ValueError` before capture starts if the configured FPS exceeds it -- following the same clear-error-not-silent-acceptance convention as the existing Camera-FPS<=0 and flush-volume-exceeds-capacity checks. No hardcoded "476" or any other static number is involved; the bound is recomputed live from the real SDK-backed readout time every run.

**Files touched:** [application.py](src/thermo_acoustic/application.py), [tests/test_full_flow_dry_run.py](tests/test_full_flow_dry_run.py) (`test_run_experiment2_rejects_camera_fps_exceeding_readout_budget`, `test_run_experiment2_allows_camera_fps_within_readout_budget`, `test_run_experiment2_ignores_disabled_do_clock_channel_for_fps_budget`).

**Verification:** tested (155 passing as of this writing). Not hardware-verified -- the bound is computed from the real `read_readout_time()` SDK call when a real DCAM backend is attached, but no real camera was exercised in this pass; also note `run_experiment2()`'s existing `self.camera.configure(exposure_ms=experiment.global_exposure_ms)` call ([application.py:341](src/thermo_acoustic/application.py:341)) only updates the Python-side tracking attribute and does **not** write `DCAM_IDPROP.EXPOSURETIME` to real hardware (that only happens via `configure_exposure_time()`, called from the manual Camera tab's `_configure_camera()`, not from the automated experiment path) -- a separate, not-yet-fixed gap noticed in passing while implementing this check, flagged here but out of scope for this session.

### Session 20 -- Experiment-path exposure time now actually applied to real DCAM hardware

**What changed:** Session 19's noticed-in-passing gap is the same bug class as Session 13's camera-trigger-source fix: an automated `run_experiment2()` call site was writing to a Python-side bookkeeping field instead of the real DCAM property, silently leaving the physical camera at whatever exposure a prior manual Camera-tab session had set.
- **Real hardware call confirmed.** Traced the manual Camera tab's `_configure_camera()` ([qt_ui.py:1365-1366](src/thermo_acoustic/qt_ui.py:1365)): it calls `self.app.camera.configure_exposure_time(exposure_ms)`, which is `HamamatsuCamera.configure_exposure_time()` ([instruments.py:501-504](src/thermo_acoustic/instruments.py:501)) -> `HamamatsuDcamBackend.configure_exposure_time()` ([hamamatsu_dcam.py:79-84](src/thermo_acoustic/hamamatsu_dcam.py:79)) -> the real `dcam.prop_setgetvalue(DCAM_IDPROP.EXPOSURETIME, ...)` SDK call. Confirmed this path already worked correctly and needed no changes.
- **Root cause confirmed.** `run_experiment2()` called `self.camera.configure(exposure_ms=experiment.global_exposure_ms)` instead -- `HamamatsuCamera.configure()` ([instruments.py:497-499](src/thermo_acoustic/instruments.py:497)) only does `self.exposure_ms = exposure_ms`, no backend call at all, no matter which backend is attached. There is no reason this call site used the non-hardware-writing method; it was simply the wrong one of the two.
- **Fix.** [application.py:369-374](src/thermo_acoustic/application.py:369): `run_experiment2()` now calls `self.camera.configure_exposure_time(experiment.global_exposure_ms)` in place of `self.camera.configure(...)` -- the same real hardware-writing call the manual tab uses, applied explicitly every run rather than leaving the camera at its last state, matching how Session 13 made trigger source explicit instead of inherited.
- **`_check_camera_timing_budget()` (Session 19) updated to verify the applied value, not the intended one.** [application.py:292-298](src/thermo_acoustic/application.py:292): now reads `self.camera.exposure_ms` (the attribute `configure_exposure_time()` just set, moments earlier in the same call) instead of `experiment.global_exposure_ms` directly. Functionally identical after the fix above (the two values are now always equal at that point), but grounds the check in what was actually pushed to the camera object rather than trusting the experiment dict to match -- consistent with the user's explicit instruction not to let the two silently diverge again.

**Files touched:** [application.py](src/thermo_acoustic/application.py), [tests/test_full_flow_dry_run.py](tests/test_full_flow_dry_run.py) (`FakeCamera.configure_exposure_time()` added; new `test_run_experiment2_applies_experiment_tab_exposure_to_real_dcam_call`, which sets the fake camera to a manual-tab-style exposure first, then confirms `run_experiment2()` overwrites it via `configure_exposure_time` with the Experiment tab's own distinctive value, and that the non-hardware-writing `configure()` call no longer appears at all in `run_experiment2()`'s call trace).

**Verification:** tested (156 passing as of this writing). Not hardware-verified -- `configure_exposure_time()`'s real-hardware path itself was already covered by existing DCAM lifecycle tests; this session's new test confirms the *call site*, exercised only against the fake camera.

## Recurring audit: manual-tab / automated-path hardware-apply parity

**This is a named, reusable audit methodology, not a one-off findings list.** Four bugs were found *separately*, one at a time, over Sessions 12-20 (Camera FPS/Frames -> DO clock, syringe volume -> flush capacity, camera trigger source, camera exposure time) before it was recognized they were all the same underlying bug class: **a hardware-apply call exists and works from a manual UI tab, but the automated `run_experiment2()` path either never calls it, calls a similarly-named function that doesn't actually reach hardware, or calls the real function with a stale/default value instead of the current Experiment-tab configuration.** Session 21 below is the first full mechanical sweep for this category; re-run this same method (not ad hoc grepping) whenever new Experiment-tab controls are added, rather than waiting to notice a gap by accident.

**Method:**
1. Enumerate every real hardware `configure`/`apply`/`set` call reachable from any manual-tab button handler in `qt_ui.py`. Trace each all the way to the actual SDK/hardware write -- confirm it's genuinely hardware-writing, not a bookkeeping/setter method with a similar name (this exact confusion -- `configure()` vs `configure_exposure_time()` -- was the Session 20 bug). Record the manual-tab widget(s) that feed it.
2. For each call from step 1, check whether `run_experiment2()` (or anything it calls) reaches the *same* underlying function -- not a similarly-named one -- during an automated run, and whether the value passed comes from *live* Experiment-tab widget state at call time, not a hardcoded default, a stale captured value, or the manual tab's separate widget.
3. Classify each call: **COVERED** (automated path reaches the same verified call with live Experiment-tab values), **GAP-MISSING** (automated path never reaches an equivalent call at all), **GAP-WRONG-FUNCTION** (automated path calls a similarly-named function that doesn't reach the same hardware write), **GAP-STALE** (automated path reaches the correct call but with a default/hardcoded/wrong-source value), or **N/A** (manual-tab-only debug/calibration tool by design -- confirm this is genuinely intentional, not another instance of the same gap, before excluding it).
4. Cross-check every GAP against `RunExperiment2.vi`'s real LabVIEW call tree (`C:\git\thermacoustics`, via the zlib-decompression method established in Sessions 14-15/19) -- does LabVIEW's own automated path apply this parameter, or does LabVIEW have the same gap (a pre-existing LabVIEW limitation, not a migration error)? Report this distinction per gap, and be explicit about confidence when a VI's sub-call block isn't as cleanly recoverable as others.

### Session 21 -- First full pass of the manual-tab/automated-path parity audit

Enumerated every `.clicked`/`.toggled` handler in `qt_ui.py`, traced each to its real SDK call, cross-checked against `run_experiment2()`, and cross-checked every gap against a fresh full dump of `RunExperiment2.vi`'s sub-VI call tree (not the partial trace from Session 19 -- the complete list this time: `GetExperimentSeriesGeneral.vi`, `Deque experiment.vi`, `ConfigDOClockSpezial.vi`, `GetGlobalExposure.vi`, `Wait.vi`, `GetFlushSettings.vi`, `GetSubRegion.vi`, `ReadReadoutTime.vi`, `SaveCameraSettings.vi`, `GetClockSettings.vi`, `GetSreiesPath.vi`, `CreatefolderandTDMS.vi`, `CleanUp.vi`, `SaveImageData.vi`, `GetExperimentFolder.vi`, `saveSequence.vi`, `Flush.vi`, `GetHamamatsu.vi`, `PCTrig.vi`, `SetAD2_SDK.vi`, `SetHamamatsu.vi`, `GetSequenceSettings.vi`, `GetWFGConfig.vi`, `SaveSettings.vi`, `StartCapture.vi`, `StopCapture.vi`, `ConfigureSequence.vi`, `ConfigWFG.vi`, `GetAD2_SDK.vi`, `FireStatusEvent.vi`, `PeekQueueMain.vi`, `GetCameraBufferSize.vi`, `ImageSequence.vi`).

**Two confirmed genuine migration regressions** (LabVIEW's own automated path structurally carries the parameter; Python's doesn't):
- **DCAM sequence cluster (GAP-MISSING).** `_camera_sequence_settings()` ([qt_ui.py:1353](src/thermo_acoustic/qt_ui.py:1353)) sends `masterpulse_mode`/`masterpulse_source`/`masterpulse_interval_s`/`masterpulse_burst_times`/`trigger_polarity`/`trigger_delay_s` to `configure_sequence()` from the manual Camera tab. `_build_experiment_series()`'s automated `sequence_settings` dict ([qt_ui.py:1536-1547](src/thermo_acoustic/qt_ui.py:1536)) contains only `{frames, camera_start_s, trigger_source}` -- the other 6 keys are simply absent, so `HamamatsuDcamBackend.configure_sequence()`'s `if "key" in settings` guards ([hamamatsu_dcam.py:114-177](src/thermo_acoustic/hamamatsu_dcam.py:114)) silently skip every one of them every automated run. `RunExperiment2.vi` reads the *whole* `SequenceSettings` cluster via `GetSequenceSettings.vi` and passes it whole to `ConfigureSequence.vi` -- LabVIEW structurally carries Master Pulse/Polarity/Delay every run regardless of value; Python's automated path structurally cannot.
- **WFG symmetry/phase/repeat_trigger/synchronize_state (GAP-STALE).** `_experiment_channel_config()` ([qt_ui.py:1128-1166](src/thermo_acoustic/qt_ui.py:1128)) hardcodes `symmetry_percent=50.0`, `phase_deg=0.0`, `repeat_trigger=False`; `_experiment_wfg_config()` ([qt_ui.py:1620-1628](src/thermo_acoustic/qt_ui.py:1620)) hardcodes `synchronize_state="Independent"`. `self.exp_ad2_channels` ([qt_ui.py:501-524](src/thermo_acoustic/qt_ui.py:501)) has no widgets for any of these four fields at all -- structurally can't be anything but the constant, unlike the manual WFG tab's fully user-controlled equivalents. `CreateExperiments.vi`'s own Carrier/WFGConfig cluster dump includes `Symmetry(%)`, `Phase(Deg)`, `Repeat Trigger`, `SyncronizeState` as real fields feeding the same `ConfigWFG.vi` -- the wired *value* is unrecoverable (same opacity as trigger source, Session 19), but the field structurally travels through LabVIEW's automated path; Python's does not.

**Confirmed pre-existing LabVIEW limitations, not Python regressions** (both codebases skip these in the automated path):
- **DCAM ROI (GAP-MISSING).** `configure_roi()` never appears anywhere in `application.py`/`workflows.py` (grep-confirmed, zero hits) -- the automated path relies entirely on whatever ROI a manual Camera-tab session last configured. `RunExperiment2.vi` calls `GetSubRegion.vi` (read-back for TDMS metadata only, matching Python's own `SaveCameraSettings` usage) but has no `ConfigureROI.vi` call anywhere in its tree.
- **Qmix syringe geometry (GAP-MISSING).** `configure_syringe()` never appears in `application.py`/`workflows.py` -- the physical `inner_diameter_mm`/`stroke_mm` pushed to the Qmix pump SDK is whatever a manual "Configure" click last set; the automated `flush()` path only ever does mL-level bookkeeping (`FlushSettings.syringe_volume_ml`, Session 10), never the real geometry SDK call. `RunExperiment2.vi`'s call tree has no `ConfigureSyringe.vi`/`ConfigureSyringeBD.vi` call. (Lower confidence than the ROI cross-check: `Flush.vi`'s own sub-VI-call resource block wasn't as cleanly recoverable via the zlib-scan method as `RunExperiment2.vi`'s was, so this can't fully rule out an indirect call inside `Flush.vi` itself.)
- **Qmix `generate_flow`/`reference_move` (N/A).** Neither `GenerateFlow.vi` nor `ReferenceMove.vi` appears in `RunExperiment2.vi`'s call tree despite both VIs existing in `CetoniPump_class` -- confirmed manual-only/one-time-calibration tools in LabVIEW too, not gaps.

**Confirmed COVERED (no action needed):** WFG carrier core (frequency/amplitude/offset/function/enable) and trigger (sec_run/sec_wait/repeat/trigger_source) -- `ConfigWFG.vi` reached every run with live Experiment-tab values; WFG FM-sweep calibration (Session 16); DCAM exposure time (Session 20); Qmix fill-level during flush (Session 13); valve position during flush (baseline).

**Confirmed N/A (genuinely no automated equivalent needed):** AD2 MSO capture -- `RunExperiment2.vi`'s full call tree contains no `AD2_MSO_SDK` capture call either, confirming this is a standalone calibration tool in both codebases, not a gap.

**One related anomaly noticed but excluded from the table** (fails the audit's own step-1 qualifying test -- "ends in a real SDK call"): the manual "Center ROI" checkbox's `HamamatsuCamera.center_roi()` ([instruments.py:550-556](src/thermo_acoustic/instruments.py:550)) only rewrites the local `self.roi` Python-side tracking value and never re-issues a `configure_roi()` write -- so even the *manual* path doesn't push centered coordinates to hardware. This is a different, structurally distinct bug from the audit's target category and was not investigated further.

**Files touched:** none -- read-only audit, no code changes per explicit instruction.

**Verification:** read-only, no tests changed.

### Session 22 -- Fixed three of Session 21's confirmed gaps: DCAM sequence cluster, WFG symmetry/phase/repeat_trigger, center_roi()

**What changed:**
- **DCAM sequence cluster now carried into the automated path.** [qt_ui.py:1536-1554](src/thermo_acoustic/qt_ui.py:1536): `_build_experiment_series()`'s `sequence_settings` dict now starts from `**self._camera_sequence_settings()` (the manual Camera tab's own builder) before overriding `frames`/`camera_start_s`/`trigger_source` with experiment-specific values -- matching `RunExperiment2.vi`'s behavior of always carrying the whole `SequenceSettings` cluster. Per field, since the Experiment tab has no separate controls for any of the six previously-missing keys: `masterpulse_mode`, `masterpulse_source`, `masterpulse_interval_s`, `masterpulse_burst_times`, `trigger_polarity`, `trigger_delay_s` are now all sourced from the manual Camera tab's own live widgets (`self.sequence_mode`/`self.sequence_source`/`self.sequence_interval`/`self.sequence_burst`/`self.external_polarity`/`self.external_delay`) -- the same shared-widget pattern already used for ROI and the syringe combo, not a new hardcoded default. (Note: the user's task description referred to this field as `masterpulse_interval`; the actual dict/DCAM-facing key, matched exactly, is `masterpulse_interval_s`.)
- **WFG symmetry/phase/repeat_trigger now settable from the Experiment tab.** Added `exp_ch1_symmetry`/`exp_ch1_phase`/`exp_ch1_repeat_trigger` and `exp_ch2_symmetry`/`exp_ch2_phase`/`exp_ch2_repeat_trigger` widgets ([qt_ui.py:481-490,499-502](src/thermo_acoustic/qt_ui.py:481), matching the manual WFG tab's own widget types: `_spin(50.0, ..., maximum=100.0)` for symmetry, `_spin(0.0, ...)` for phase, `QCheckBox("Repeat Trigger")`), added as visible rows in `_ad_settings_group()` ([qt_ui.py:1014-1017,1035-1038](src/thermo_acoustic/qt_ui.py:1014)), added to the `self.exp_ad2_channels` state dicts, seeded once from the manual WFG tab alongside the other seeded fields in `_seed_experiment_ad2_from_wfg_once()`, and wired into `_experiment_channel_config()` in place of the previous `symmetry_percent=50.0`/`phase_deg=0.0`/`repeat_trigger=False` hardcodes ([qt_ui.py:1146-1150,1176](src/thermo_acoustic/qt_ui.py:1146)). Also added to the save/load settings dict for persistence, matching the existing pattern for every other `exp_ch1_*`/`exp_ch2_*` field.
  - **`synchronize_state` deliberately NOT given an Experiment-tab control.** Investigated first: the manual WFG tab's own `self.wfg_sync` widget is explicitly disabled with tooltip "Not implemented: SynchronizeState is currently a non-functional stub" ([qt_ui.py:421](src/thermo_acoustic/qt_ui.py:421), [qt_ui.py:663-665](src/thermo_acoustic/qt_ui.py:663), confirmed by the existing `test_wfg_synchronize_state_is_visibly_disabled_stub`), and `WaveFormsBackend.configure_wfg()` never calls `analog_out_master_set()`/`FDwfAnalogOutMasterSet` anywhere -- `synchronize_state` has no real hardware effect anywhere in this codebase, manual or automated. Adding a working Experiment-tab control for a value that reaches no real SDK call in either path would misrepresent a non-functional stub as a real feature. `_experiment_wfg_config()`'s `synchronize_state="Independent"` is left hardcoded, now with a comment explaining why, matching the manual tab's own default.
- **`center_roi()` now re-applies to real hardware.** [instruments.py:550-557](src/thermo_acoustic/instruments.py:550): `HamamatsuCamera.center_roi()` now calls `self.configure_roi(centered)` after computing the centered value in each branch, instead of only mutating `self.roi` locally -- so clicking "Center ROI" (or calling `center_roi()` programmatically) now genuinely pushes the centered coordinates to the backend, matching what the button already implied it did.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [instruments.py](src/thermo_acoustic/instruments.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (`test_experiment_sequence_settings_carry_manual_tab_sequence_cluster_fields`, `test_experiment_wfg_config_carries_symmetry_phase_and_repeat_trigger`), [tests/test_application.py](tests/test_application.py) (`test_center_roi_reapplies_centered_coordinates_to_real_backend`).

**Verification:** tested (159 passing as of this writing, up from 156; all pre-existing tests pass unmodified). Not hardware-verified -- exercised only against fakes/offscreen Qt, no real DCAM/AD2 hardware.

### Session 23 -- Verifying Session 21's audit enumeration for interruption-caused gaps (no code changes)

Session 21 was interrupted mid-task by the user (right after the syringe-geometry gap was found, before the cross-check pass finished) and resumed via a re-sent, expanded version of the same request. The handler enumeration (step 1 of the audit method) was not re-run after resuming -- it continued from in-context state. This session re-derived the enumeration from scratch, independent of that context, to check whether the interruption caused a silent gap.

**Fresh count:** 28 total `.clicked.connect(...)`/`.toggled.connect(...)` sites in `qt_ui.py` (26 + 2). **Session 21's delivered table covered only 11 of the 28 raw handler lines explicitly** (mapped into 15 table rows via one-to-many/many-to-one grouping -- e.g. the WFG `apply` handler produced 3 rows, the camera `configure` handler produced 4). The remaining 17 handler lines (`exit`, `abort`, save/load settings, `initialize`, pump `refill`/`empty`/`stop`, manual camera `image` snapshot + its `image_continuous` toggle, `adjust`, manual `start` capture, `trig` (`sw_trigg`), `save` sequence, both folder-browse buttons, and the automated `start experiment` entry point itself) were never explicitly written down as COVERED/GAP/N/A -- a genuine completeness gap in the audit's *documentation*, though not necessarily in its *conclusions*.

**Investigated all 17 individually this session.** Result: zero new gaps. Each is either not a hardware-apply call at all (`save`/`load settings`, folder browsers, `exit`, `adjust` -- confirmed no SDK call reached; `save sequence` confirmed to be a PIL/TIFF disk write, not a DCAM property write, via [hamamatsu_dcam.py:266-276](src/thermo_acoustic/hamamatsu_dcam.py:266)), or a real hardware call that is stateless/parameterless with nothing that could go stale (`abort`, `initialize` -- confirmed to be a single call site shared by both manual and automated use, not two divergent ones -- pump `refill`/`empty`/`stop`, manual snapshot capture and its continuous-preview toggle, `sw_trigg`), or trivially COVERED (manual "start capture" reaches the identical `camera.start_capture()` call used by `run_experiment2()`, and it takes no arguments so no staleness is possible). `refill`/`empty`/`stop` were also cross-checked against the same fresh `RunExperiment2.vi` call tree from Session 21 -- no `Refill.vi`/`Empty.vi`/`Stop.vi` call exists there either.

**Verdict: Session 21's findings stand unchanged.** The five findings from that session (WFG symmetry/phase/repeat_trigger/sync, DCAM sequence cluster, DCAM ROI, Qmix syringe geometry, plus the `center_roi()` anomaly -- three fixed in Session 22, two still open) remain the complete set. The interruption caused a documentation gap, not a substantive miss.

**Files touched:** none -- read-only verification, no code changes.

**Verification:** read-only, no tests changed.

### Session 24 -- Fresh layout/display audit of qt_ui.py and qt_ui_v2.py, then fixed the two HIGH findings

A read-only layout audit (requested mid-session, not separately logged at the time) re-verified `qt_ui.py` and `qt_ui_v2.py` against current code -- not prior conclusions -- given the Session 22 additions (WFG symmetry/phase/repeat_trigger, DCAM sequence cluster wiring) had landed without dedicated layout polish. Method: offscreen Qt instantiation of both windows, measuring real `sizeHint()`/laid-out geometry/font-metrics rather than trusting screenshots (the offscreen QPA platform in this environment renders glyphs as blank boxes, making pixel screenshots unreadable for text -- a headless-font-backend limitation, not an app bug). Findings, prioritized:

- **[HIGH, fixed this session] The manual Camera tab's Sequence cluster is load-bearing for automated runs (since Session 22) with zero on-tab indication**, while the WFG tab carries a disclaimer claiming manual settings are isolated -- a user could wrongly assume the same isolation applies to Camera.
- **[HIGH, fixed this session] `qt_ui_v2.py`'s own "AD2 Output Parameters" table never displays Symmetry/Phase/Repeat Trigger** -- the three fields added in Session 22 are fully functional through v2 (same underlying `self.exp_ad2_channels` state) but completely invisible and unreachable in v2's UI, since `_v2_ad2_output_group()`'s `headers` tuple and `_add_experiment_ad2_row()` were never updated when v1's `_ad_settings_group()` was extended.
- **[MEDIUM, fixed this session]** Pre-existing "Mode" (real, now automated-relevant `masterpulse_mode`) vs. "Capture mode" (confirmed dead since Session 11) label collision on the same Camera-tab form -- higher-stakes now that "Mode" drives automated runs.
- [LOW, not fixed, no action needed] New symmetry/phase controls integrate reasonably into their channel's existing field cluster in `qt_ui.py` rather than reading as appended afterthoughts; labels have correct units and match sibling conventions; no new truncation was introduced (the ~125px column compression measured for `symmetry`/`phase` is a pre-existing `QFormLayout` characteristic already present for `frequency`/`amplitude`, not something the new fields caused). No new mojibake anywhere (byte-level scan of both files: zero non-ASCII characters).
- [LOW, not fixed, no action needed] `qt_ui_v2.py`'s "Acquisition Parameters" group no longer mixes real and stub fields (all confirmed functional); "Hardware Details" (Initialize dialog) still does, but each stub is explicitly disabled with a "Not wired to a real backend" tooltip (Session 3's convention), so it doesn't read as silent mixing.
- [LOW, informational] FM Sweep (Session 16) is also absent from `qt_ui_v2.py`'s main experiment area, same root cause as the AD2 Output Parameters gap above -- noted for context, not fixed (predates this session, not requested).

**What changed (the two HIGH findings + the MEDIUM one, fixed together since they're in the same code area):**
- **`qt_ui_v2.py`'s AD2 Output Parameters table now includes Symmetry/Phase/Repeat Trigger.** [qt_ui_v2.py:246-250](src/thermo_acoustic/qt_ui_v2.py:246): `headers` extended to 12 entries; [qt_ui_v2.py:281-293](src/thermo_acoustic/qt_ui_v2.py:281): `_add_experiment_ad2_row()`'s `widgets` tuple now includes `state["symmetry"]`, `state["phase"]`, `state["repeat_trigger"]` -- bound to the exact same widget instances `qt_ui.py`'s Experiment tab uses (confirmed by test, not copies), so no new state to keep in sync.
- **Camera manual tab's Sequence group now carries an accurate live-use indicator**, the opposite framing from WFG's static isolation claim: [qt_ui.py:957-964](src/thermo_acoustic/qt_ui.py:957) adds `sequence_note` ("These Sequence Settings (Mode/Source/Interval/Burst/Polarity/Delay) are applied to every automated Experiment run -- unlike the WFG tab, changes made here DO affect experiment runs.") directly above the Sequence Settings form.
- **Dead "Capture mode" row marked as a stub, matching the Session 3 convention.** [qt_ui.py:468-470](src/thermo_acoustic/qt_ui.py:468): `self.capture_mode` is now `setEnabled(False)` with tooltip "Not wired to a real backend: never read by `_camera_sequence_settings()` or any capture path (confirmed dead, Session 11)."; [qt_ui.py:951](src/thermo_acoustic/qt_ui.py:951): form row label renamed `"Capture mode"` -> `"Capture mode (unused)"`.
- **WFG-panel disclaimer convention updated: documented as an intentional asymmetry, not a bug.** The WFG tab's "independent from Experiment tab" disclaimer ([qt_ui.py:667](src/thermo_acoustic/qt_ui.py:667)) and MSO's lack of one remain correct as-is (both are genuinely isolated from automated runs); Camera's new note ([qt_ui.py:957-961](src/thermo_acoustic/qt_ui.py:957)) says the opposite on purpose, because Camera's Sequence cluster genuinely is live for automated runs as of Session 22 while WFG/MSO genuinely are not. **A future pass must not "fix" this into false consistency** (e.g. copying WFG's isolation wording onto the Camera tab, or removing Camera's live-use note to "match" WFG) -- the asymmetry reflects a real underlying difference in each panel's relationship to the automated path, not an oversight.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (`test_camera_sequence_group_flags_live_automated_use_and_dead_capture_mode`), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py) (`test_v2_ad2_output_table_exposes_symmetry_phase_and_repeat_trigger`).

**Verification:** tested (161 passing as of this writing, up from 159; all pre-existing tests pass unmodified). Not hardware-verified -- display-only changes, exercised via offscreen Qt and fakes only.

### Session 25 -- Experiment tab Carrier/Trigger/Sweep sub-headers (layout-only); v2 AD2 table density investigated, not changed

**Task 1 -- fixed.** `_ad_settings_group()` ([qt_ui.py:1015-1077](src/thermo_acoustic/qt_ui.py:1015)) restructured from one flat 30-row `QFormLayout` per the whole group into a `QVBoxLayout` containing, per channel: a bare `QLabel("Carrier")` + form (Enable/Function/Frequency/Amplitude/Offset/Symmetry/Phase), a bare `QLabel("Trigger")` + form (Start/Run/cRepeat/Trigger Source/Repeat Trigger), and for CH0 only, the existing `QLabel("Sweep (FM modulation calibration -- distinct from Frequency Scanning)")` header + form -- reusing the manual WFG tab's own `_wfg_channel_group()` convention verbatim (same header style, same bare-QLabel-then-QFormLayout structure). New helper `_add_experiment_channel_sections()` ([qt_ui.py:1030-1076](src/thermo_acoustic/qt_ui.py:1030)) builds both channels' sections from one shared implementation.
- **Ordering rule used to resolve "do not reorder" against "create clean sections":** fields were not naturally contiguous by category in the old flat form (e.g. Symmetry/Phase sat after Trigger Source, separated from the other Carrier fields). Resolved by keeping each field's relative order *within its assigned section* exactly as it already appeared in the old flat list (skipping over fields destined for other sections) -- e.g. Carrier's existing relative order was Enable, Function, Frequency, Amplitude, Offset, Symmetry, Phase, so that is the new Carrier section's order, verbatim. No field's label text was changed; the pre-existing CH0-vs-CH1 "Run (s) (0=Cont)" vs. "Run (s)(0=Cont)" spacing inconsistency was preserved as-is (not "fixed" -- out of scope for a layout-only pass).
- All 28 row labels confirmed present and textually unchanged via an offscreen instantiation (script-verified, not just read); confirmed setting `exp_ch1_symmetry`/`exp_ch1_phase`/`exp_ch1_repeat_trigger` through the now-relocated widgets still flows correctly into `_build_experiment_series()`'s output -- zero behavior change, purely layout.
- **Noted, not fixed (out of the requested scope):** "Carrier" and "Trigger" now appear as bare headers twice in the same group box (once per channel) with no channel-level divider beyond each row's own "CH0 "/"CH1 " label prefix. Task 1 only asked for the three named sub-headers, not a channel boundary; flagging this in case a future pass wants one.

**Task 2 -- investigated, NOT implemented (per explicit instruction to confirm first).** Measured `_v2_ad2_output_group()`'s real column layout offscreen: the table grew from 9 to 12 data columns this addition, and its natural width grew from ~2064px to ~2724px (about 32%). The horizontal-scroll mechanism itself (`QScrollArea` with `setWidgetResizable(False)` + `ScrollBarAsNeeded`, originally added in Session 5, not Session 24) continues to function correctly at 12 columns -- it doesn't break or degrade structurally. However: at the default 1440px window width (~990px estimated viewport for this group), **the table already required horizontal scrolling past roughly the "Amplitude" column (5th of 9) before this addition** -- so the pre-existing baseline was already well past "at-a-glance" for about half its columns. The 3 new columns compound an already-present problem rather than introducing a new category of one. Recommendation (not implemented): if this is worth addressing, the most consistent fix would mirror Task 1's own solution -- visually group the table's columns (e.g. a thin separator or sub-header spanning Symmetry/Phase/Repeat Trigger as a "detail" cluster distinct from the core Carrier/Trigger columns) rather than changing the scroll mechanism, which is not the part that's degraded. Left as a reported finding pending confirmation, per instruction.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py) only (Task 1). No test changes required beyond the offscreen build/render check described above (per instruction: "no new tests needed beyond confirming the UI still builds/renders correctly offscreen").

**Verification:** tested (161 passing, unchanged from Session 24 -- no test file was touched this session). Offscreen instantiation of `qt_ui.MainWindow()` confirmed the Experiment tab builds without exceptions and all row labels/values are intact. Not hardware-verified (layout-only, no hardware interaction).

### Session 25 follow-up -- Task 2 implemented: v2 AD2 Output Parameters table now visually groups Symmetry/Phase/Repeat Trigger

Went ahead with Session 25's own Task 2 recommendation (visual sub-grouping, not touching the scroll mechanism), after explicit confirmation.

**What changed:** [qt_ui_v2.py:239-284](src/thermo_acoustic/qt_ui_v2.py:239): `_v2_ad2_output_group()`'s `QGridLayout` gained a new row 0 with a single `QLabel("Detail")` spanning the three rightmost data columns (`grid.addWidget(detail_label, 0, core_column_count + 1, 1, len(headers) - core_column_count)`, `core_column_count = 9`) -- Symmetry, Phase, and Repeat Trigger now read as a visually distinct cluster, mirroring Session 25's own Carrier/Trigger/Sweep sub-header pattern in `qt_ui.py`, without inventing a new visual language for this table. The existing per-column header row, CH0 row, and CH1 row all shifted down by one grid row (0->1, 1->2, 2->3 respectively); `_size_ad2_output_columns()` ([qt_ui_v2.py:286-293](src/thermo_acoustic/qt_ui_v2.py:286)) was updated to read from the new row indices (row 1 for headers, row 2 for CH0 as the sizing reference) so per-column width computation is unaffected. No new grid column was added (rejected the "vertical divider" alternative from Session 25's write-up, since a `QFrame` divider would need its own column and force renumbering every widget placement for no real benefit over the simpler spanning label) -- widget bindings, column count (12 data + 1 label column, unchanged), and the `QScrollArea`'s `setWidgetResizable(False)`/`ScrollBarAsNeeded` scroll mechanism (Session 5) are all untouched.

**Files touched:** [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py) (updated `test_v2_ad2_output_table_exposes_symmetry_phase_and_repeat_trigger`'s row indices for the shifted grid, plus one added assertion confirming the new "Detail" sub-header exists; widget-identity assertions unchanged in substance, still confirm `qt_ui_v2.py` binds the exact same widget instances as `qt_ui.py`).

**Verification:** tested (161 passing, same count as before -- one existing test updated in place, no test added or removed). Offscreen instantiation confirmed: the grid builds without exceptions, all 12 column headers and the new "Detail" spanning label render at their expected positions, CH0/CH1 rows still bind the identical `exp_ch1_*`/`exp_ch2_*` widget instances, and the scroll area's `widgetResizable` flag remains `False` (mechanism untouched). Not hardware-verified (layout-only).

### Session 26 -- data.tdms write verification added (closes a long-deferred open item)

**What changed:** `Experiment2._write_tdms()` ([workflows.py:201-219](src/thermo_acoustic/workflows.py:201)) now calls a new `_verify_tdms_write()` ([workflows.py:221-270](src/thermo_acoustic/workflows.py:221)) immediately after `TdmsWriter.write_segment()` returns, instead of treating "didn't raise" as sufficient proof of a good write:
1. **Size sanity check.** `self.tdms_path.stat().st_size` must be at least `_MIN_TDMS_FILE_SIZE_BYTES = 128` ([workflows.py:16-19](src/thermo_acoustic/workflows.py:16)) -- an explicitly cheap, non-rigorous floor, just enough to catch a silently-empty or header-only write.
2. **Reopen via npTDMS's own reader.** `TdmsFile.read(str(self.tdms_path))` (imported alongside the existing `ChannelObject`/`GroupObject`/`RootObject`/`TdmsWriter` import so the existing `ModuleNotFoundError` guard covers it too) -- any exception here (corrupted/truncated binary) is caught and re-raised as a `RuntimeError` describing the failure, matching this project's established error-surfacing convention (clear error, not silent pass -- same pattern as the Camera-FPS<=0 and flush-volume-exceeds-capacity checks).
3. **Structure check, not full round-trip equality.** Confirms the `"Experiment"` group exists in the reopened file, and that every key just written (`properties`, the same scalar-converted dict passed to `GroupObject`) is present in the reopened group's `.properties` -- a set-difference check on keys, not a value-by-value comparison (deliberately lightweight, per instruction, to avoid duplicating the existing write-path tests). If `self._tdms_image_names` was written, also confirms the `"ImageData"` group's `"ImageName"`/`"Timestamp"` channels exist and their lengths match what was written.
- **Test infrastructure updated to support this.** `install_fake_nptdms()` in [tests/test_application.py:95-172](tests/test_application.py:95) gained a `FakeTdmsFile`/`FakeTdmsGroup`/`FakeTdmsChannel` reader stack (reconstructing a read-back view from the same `objects` list the fake writer already recorded) so `TdmsFile.read()` works against the fake, and `FakeTdmsWriter.write_segment()` now pads its stand-in file to 521 bytes (was 9 bytes -- `b"fake tdms"` alone would have failed the new size check). This is a test-only change; the real npTDMS package (not installed in this dev environment, confirmed via a direct import attempt) provides the genuine `TdmsFile.read()` API this code calls against in a real deployment.

**Files touched:** [workflows.py](src/thermo_acoustic/workflows.py), [tests/test_application.py](tests/test_application.py) (`install_fake_nptdms()` extended; new `test_write_tdms_verification_catches_truncated_write`, which forces a 1-byte truncated write via a dedicated fake writer and confirms `create_folder_and_tdms()` raises `RuntimeError` matching "write verification failed" instead of completing silently).

**Verification:** tested (162 passing, up from 161). Not hardware-verified -- exercised entirely against the fake `nptdms` stand-in described above (the real package isn't installed in this dev environment); the verification logic itself calls the standard, documented npTDMS `TdmsFile.read()` / `TdmsGroup.properties` / channel-indexing API, so it should behave identically once the real package is present, but that hasn't been independently confirmed against a real npTDMS install in this pass. **Update (Session 27, 2026-07-24): this caveat is resolved -- the real package was installed on this machine and this code path was independently verified against it. See Session 27 below.**

### Session 27 -- Real npTDMS installed and independently verified against Session 26's write-verification code (2026-07-24)

The real `nptdms` package was not present in this dev environment as of Session 26 (confirmed there by a direct `import nptdms` attempt, which raised `ModuleNotFoundError`). Re-checking today, the same import now succeeds: `nptdms` 1.11.0 is installed (`...\AppData\Roaming\Python\Python313\site-packages\nptdms\__init__.py`) -- installed on this machine at some point between Session 26 and now, outside this conversation (no `pip install` was run here to add it).

**What was verified, and how:** re-running the existing pytest suite alone would **not** have exercised the real package -- every TDMS-touching test installs the fake via `monkeypatch.setitem(sys.modules, "nptdms", ...)`, which overrides `sys.modules["nptdms"]` regardless of what is genuinely installed. To actually exercise the real dependency, a standalone script (outside pytest, no monkeypatching) built a real `Experiment2` and called `create_folder_and_tdms()` -> `save_settings()` -> `save_image_data()` -> `save_camera_settings()` against the genuinely-imported `nptdms` package:
- All four calls completed without error, meaning `_write_tdms()`'s new `_verify_tdms_write()` ([workflows.py:221-270](src/thermo_acoustic/workflows.py:221)) passed its size check, its `TdmsFile.read()` reopen, and its property/channel-key checks against a **real** npTDMS-written `data.tdms` file (1184 bytes), not the fake.
- Independently re-reading that same file afterward (a second, separate `TdmsFile.read()` call, outside `_verify_tdms_write()`) confirmed the `"Experiment"` group has all 31 expected properties (spot-checked values, e.g. `Repeat ID=1`, `ExposureTime=40.0`, `GlobalExposure=True`) and the `"ImageData"` group's `ImageName`/`Timestamp` channels contain the expected 2 entries each.
- The full pytest suite (162 tests) was then re-run with the real package now importable in the environment -- **all 162 passed**, confirming the real package being present doesn't change anything about what the (still fake-based) test suite exercises, and doesn't introduce any import-shadowing or other conflict elsewhere in the codebase.
- **No behavior differences were found between the fake and the real library** for this code path.

**Separately, an environment note worth keeping on record for future sessions on this machine (unrelated to TDMS, not previously documented):** `pytest`'s default `tmp_path` fixture and its own cache directory both fail with `PermissionError: [WinError 5] Access is denied` on this machine -- `tmp_path` because `os.scandir()` on `C:\Users\Lab user\AppData\Local\Temp\pytest-of-Lab user` is denied, and `.pytest_cache/v/cache/*` similarly. This has been worked around throughout this project's sessions by always passing `--basetemp=<some project-relative dir>` explicitly (e.g. `--basetemp=.pytest_tmp_session27`) rather than relying on pytest's default temp-directory resolution; the leftover `--basetemp` directories from many past sessions (`.pytest_tmp_conversion/`, `.pytest_tmp_v2/`, etc., visible in `git status` as permission-denied warnings) are a visible trace of this. Not a code issue -- purely a local machine/account permissions quirk, resolved operationally rather than fixed.

**Files touched:** none -- verification and environment note only, no code changes.

**Verification:** tested (162 passing, same count as Session 26 -- confirmed against both the fake, as before, and now independently against the real npTDMS 1.11.0 package via the standalone script described above, which is not part of the committed test suite).

### Session 28 -- Fixed the Experiment tab's collapsed "Analog Discovery Settings" group; exhaustive FocusWheelGuard re-audit (no coverage gap found)

**Task 1 + 2 -- root cause found and fixed together (same code, same fix).** The "Analog Discovery Settings" group on `qt_ui.py`'s own Experiment tab (**not** `qt_ui_v2.py` -- confirmed by direct check that `_ad_settings_group` has exactly one call site in the whole codebase, [qt_ui.py:1015](src/thermo_acoustic/qt_ui.py:1015)/[qt_ui.py:999](src/thermo_acoustic/qt_ui.py:999), and is never referenced anywhere in `qt_ui_v2.py`'s own layout methods) was measured offscreen: its `QVBoxLayout`'s natural content needs `sizeHint=852x1019`/`minimumSizeHint=852x1005` (grown substantially by Session 25's Carrier/Trigger/Sweep sub-headers), but the surrounding grid/tab only ever gave it `423px`-`243px` of actual height depending on window size -- far below its own minimum. Under that much space pressure, Qt's layout engine compresses individual `QFormLayout` rows down toward 0px, which is exactly what was observed: header `QLabel`s ("Carrier", "Trigger", "Sweep...") still got a small nonzero height and rendered, while the actual value widgets (spin boxes, combos, checkboxes) were measured at `height=0` or `height=1` -- present and "visible" per Qt (`isVisible()==True`) but with no rendered pixels, exactly matching the reported "labels stacked with no visible field values beneath them."
- **Fix:** [qt_ui.py:1015-1044](src/thermo_acoustic/qt_ui.py:1015): `_ad_settings_group()` now builds its Carrier/Trigger/Sweep content into a separate `content` widget, wrapped in a `QScrollArea` (`setWidgetResizable(True)`, `setMaximumHeight(360)`, horizontal scrollbar off, vertical as-needed) instead of laying that content directly into the group's own layout. The content widget now gets to lay out at its full natural size internally (confirmed offscreen: every previously-collapsed field now renders at its normal height, e.g. 23px for spin boxes, 17px for checkboxes) and scrolls instead of being compressed.
- **FocusWheelGuard interaction (the specific risk flagged in Task 2): confirmed working correctly, no changes needed to the guard itself.** `FocusWheelGuard.eventFilter()` ([qt_ui.py:102-119](src/thermo_acoustic/qt_ui.py:102)) already walks `obj.parentWidget()` up to the nearest ancestor `QScrollArea` and forwards intercepted wheel events to its `viewport()` -- this is generic and required no changes for the new scroll area to work. Verified offscreen, three ways: (1) wheel over an *unfocused* spin box inside the new area scrolls the area and leaves the value unchanged; (2) wheel over a *focused* spin box still changes only that box's value (existing, unchanged behavior); (3) wheel directly over empty viewport space scrolls normally. (One test-methodology dead end worth recording: an early manual check of case (3) appeared to fail because the synthetic scroll direction was already pinned at the scrollbar's minimum -- not a real bug, just a boundary-clamped test in the wrong direction; corrected and re-verified.)

**Task 3 -- exhaustive re-audit performed; no systemic FocusWheelGuard coverage gap found.** This is the important, evidence-based finding, not a guess:
- **(a) Mechanism re-confirmed accurate and complete.** `install_focus_wheel_guard()` ([qt_ui.py:122-127](src/thermo_acoustic/qt_ui.py:122)) installs a *single* `QObject.eventFilter` on the `QApplication` instance itself (`app.installEventFilter(guard)`), not a per-widget filter -- this is a genuinely install-once, application-wide mechanism in Qt (event filters on `QApplication` see every event dispatched to any object in the process, including widgets created after installation; this is standard, documented Qt behavior, not creation-order-sensitive). The guard checks `isinstance(obj, (QSpinBox, QDoubleSpinBox, QComboBox))` ([qt_ui.py:108](src/thermo_acoustic/qt_ui.py:108)). Grepped the entire codebase for direct instantiation of these three classes: **exactly 3 call sites exist, total, in both `qt_ui.py` and `qt_ui_v2.py` combined** -- all three are the `_spin()`/`_int_spin()`/`_combo()` factory functions themselves ([qt_ui.py:68,78,87](src/thermo_acoustic/qt_ui.py:68)). Every spin/combo widget in the entire app is constructed through exactly one of these three factories; there is no other construction path, no custom subclass, and no widget type used for value-editing that falls outside the guard's isinstance check.
- **(b) WaitAfterFlush investigated specifically -- could not reproduce a coverage gap.** Traced both `WaitAfterFlush` fields (`self.wait_after_flush`, manual Pump&Valve tab, [qt_ui.py:445](src/thermo_acoustic/qt_ui.py:445); `self.exp_wait_after_flush`, Experiment tab, [qt_ui.py:545](src/thermo_acoustic/qt_ui.py:545)) -- both built via the same guarded `_spin()` factory, nothing custom. Offscreen testing at the app's real default window size (1280x820) found `exp_wait_after_flush` renders at a completely normal, uncollapsed height (23px) -- **it is not affected by the Task 1 layout bug**, ruling out an early hypothesis that the two symptoms shared a root cause. Direct synthetic-wheel-event testing (both via `QApplication.sendEvent()` targeting the spin box directly, and targeting its internal `QLineEdit` child specifically -- to test whether Qt might deliver real wheel events to a child widget not covered by the guard's isinstance check) found the guard correctly blocks the value change in every case when the widget is unfocused, and correctly allows it when focused. A stray `.thermo_acoustic_ui.json` settings file on this machine (gitignored, dated the same day) was found to already persist `wait_after_flush=5.0`, confirming the value change happened in a real prior interactive session -- but every mechanism tested here to explain an *unfocused* wheel event changing that value came back negative.
- **(c)/(d) Enumeration and fix.** Enumerated every `QSpinBox`/`QDoubleSpinBox`/`QComboBox` in the live, fully-constructed app via `findChildren()`: **118 widgets** in `qt_ui.MainWindow` (all tabs, since `QTabWidget` keeps inactive tabs' widgets as children too). Sent a synthetic unfocused wheel event to every single one and compared before/after value: **zero widgets changed value -- 0 of 118 failures.** Separately confirmed `qt_ui_v2.MainWindowV2` creates no `QSpinBox`/`QDoubleSpinBox`/`QComboBox` instances of its own (grepped, zero matches in `qt_ui_v2.py`) and only ever reuses the exact same widget instances from `qt_ui.py` (identity-confirmed for a sample widget) -- so the 118-widget, zero-failure result already covers the entire app, both UIs. Given no coverage defect was found to fix, "the fix" for this task is the completeness test itself (below), which locks in this confirmed-correct state as a structural, self-updating guarantee against *future* regressions -- there was no hardcoded list of fields to patch, because no field was found to be missing.
- **Most likely real-world explanation for the original WaitAfterFlush report, consistent with all evidence gathered:** the field most likely received actual focus via an inadvertent/stray click (a normal, easy mistake in a dense form) before the observed scroll -- which is the guard's own explicitly-designed "existing behavior" (wheel edits a *focused* spin box's value), not a bypass of it. This is a discoverability/affordance observation, not a code defect.

**New tests (all in [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)):**
- `test_ad_settings_group_fields_render_at_visible_heights` -- confirms the new `QScrollArea` exists with a bounded `maximumHeight`, and that every previously-collapsed field now renders with real height.
- `test_ad_settings_scroll_area_wheel_guard_interaction` -- confirms the three-way interaction: unfocused wheel scrolls the area without changing value; focused wheel still changes value.
- `test_focus_wheel_guard_covers_every_spin_and_combo_widget` -- the completeness test: enumerates every `QSpinBox`/`QDoubleSpinBox`/`QComboBox` via `findChildren()` (no hardcoded list) and asserts none of them change value from an unfocused synthetic wheel event. Stays valid automatically as new fields are added, per instruction.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py).

**Verification:** tested (165 passing, up from 162 -- 3 new tests, all pre-existing tests pass unmodified). Not hardware-verified -- all offscreen/synthetic-event testing; no real mouse hardware was exercised, so a genuinely hardware-specific wheel-delivery quirk (e.g. a high-resolution/precision touchpad sending pixel-delta events with unusual properties) cannot be fully ruled out as a contributing factor to the original report, though nothing in this investigation supports it as the mechanism.

### Session 29 -- kHz unification, WFG live-use labeling, full group-box collapse re-audit, independent v1/v2 wheel-guard re-verification

**Task A -- kHz unification, done.** Enumeration (reported before converting, per instruction): **IN-SCOPE** -- Carrier "Frequency (Hz)" (manual WFG tab [qt_ui.py:701](src/thermo_acoustic/qt_ui.py:701), Experiment tab [qt_ui.py:1100](src/thermo_acoustic/qt_ui.py:1100), v2's AD2 Output Parameters table [qt_ui_v2.py:247](src/thermo_acoustic/qt_ui_v2.py:247)); FM Mod "Frequency (Hz)" ([qt_ui.py:724](src/thermo_acoustic/qt_ui.py:724)); Sweep "Center Frequency (MHz)" on both tabs (correcting Session 16's choice, [qt_ui.py:737](src/thermo_acoustic/qt_ui.py:737), [qt_ui.py:1121](src/thermo_acoustic/qt_ui.py:1121)); and, **added to the task's own bracket list after independent enumeration** (flagged, not silently assumed): the Experiment tab's own Frequency (Hz) fields and the Sweep "Top/Bottom Frequency (Hz)" readouts -- included because Task B's own "overrides WFG tab" framing treats the Experiment-tab Carrier Frequency as the same parameter as the WFG-tab one, and leaving one in Hz while the other converts to kHz would defeat the stated purpose (SeriesPath naming consistency). **OUT-OF-SCOPE, confirmed and left untouched:** MSO "Sample Frequency (Hz)" ([qt_ui.py:782](src/thermo_acoustic/qt_ui.py:782)); AD2 internal digital-out clock (queried live via SDK, no UI label exists for it); `test_real_workflow_smoke_plan.py`'s "frequency=1975000.0 Hz" assertions (confirmed a separate, non-UI code path -- `experiment_presets.py`'s LabVIEW-preset constants printed by a standalone smoke-test script, not `qt_ui.py`'s widgets). "Sweep Width (kHz)" was already correct, no change needed.
- **What changed:** all in-scope widget defaults now store/display kHz (`_make_wfg_channel_state()` [qt_ui.py:552-582](src/thermo_acoustic/qt_ui.py:552), `exp_ch2_freq`/`exp_sweep_center_khz` [qt_ui.py:497,493](src/thermo_acoustic/qt_ui.py:497)); every consumer that previously read `.value()` as Hz now multiplies by 1000 at the UI boundary (`_channel_config()` [qt_ui.py:1152,1163](src/thermo_acoustic/qt_ui.py:1152), `_experiment_channel_config()` [qt_ui.py:1224](src/thermo_acoustic/qt_ui.py:1224), `_fm_sweep_settings_from_state()`/`_experiment_fm_sweep_settings()` [qt_ui.py:768-769,1264-1265](src/thermo_acoustic/qt_ui.py:768)); `sweep_center_mhz`/`exp_sweep_center_mhz` renamed to `sweep_center_khz`/`exp_sweep_center_khz` throughout (dict key and attribute name only -- confirmed not serialized under the old name in `_settings_dict()`/`_load_settings()`, so no migration key collision); decimals kept at 3 (0.001 kHz = 1 Hz, matching the prior 6-decimals-in-MHz and 3-decimals-in-Hz precision exactly, confirmed not a precision loss). `_seed_experiment_ad2_from_wfg_once()` needed no change -- both sides are kHz now, so the existing unscaled copy is still correct. `CarrierSettings.frequency_hz`/`FmSweepSettings.center_hz`/`width_hz` and all hardware-writing calls remain Hz internally, unchanged, per instruction.
- **Known, accepted breaking change (flagged, not fixed):** any pre-existing `.thermo_acoustic_ui.json` saved before this session with Hz-scale frequency values (e.g. `1975000.0`) will load into the now-kHz-labeled fields as-is, displaying as `1,975,000` kHz (=1.975 GHz) -- silently 1000x wrong. No settings-format migration was implemented (not requested, and out of scope for "keep tests minimal"); a user upgrading across this change needs to re-enter frequency values once.
- **Test:** `test_frequency_fields_display_khz_but_round_trip_to_correct_hz_hardware_value` -- confirms `1900.000` kHz on both tabs, both Carrier and Sweep Center Frequency, produces exactly `1_900_000.0`/`1_934_000.0` Hz in the resulting `CarrierSettings`/`FmSweepSettings`, matching what the old Hz/MHz fields produced for the same physical value.

**Task B -- WFG live-use labeling, done, with one corrected premise (flagged explicitly, not silently substituted).** Traced `_experiment_channel_config()` field-by-field before labeling anything. The Experiment-tab-side request ("CH0 frequency/amplitude/secRun/secWait, CH1 secRun/secWait -- '(overrides WFG tab)'") was accurate and implemented as asked, [qt_ui.py:1097-1119](src/thermo_acoustic/qt_ui.py:1097). **The WFG-tab "remains active" claim (channel Enable, Function, CH1 Frequency/Amplitude, Symmetry, Phase, FM Mod, Trigger source) did not hold up under tracing:** every one of those fields -- including CH1 (task's naming; the UI's "Ch2") Frequency/Amplitude -- has its own independent Experiment-tab widget that `_experiment_channel_config()` reads instead of the WFG tab's, exactly like the 4 fields the task already knew were overridden. The only field genuinely untouched by the Experiment tab is FM Mod -- but it isn't "active" either: `_experiment_channel_config()` always either hardcodes it disabled or replaces it entirely with FM-Sweep-derived settings, so the manual FM Mod widgets can never affect an automated run at all. Labeled accordingly instead of per the original claim: every Carrier/Trigger field on both Ch1 and Ch2 now reads `"... (overridden during experiment run)"` ([qt_ui.py:708-782](src/thermo_acoustic/qt_ui.py:708)), and FM Mod fields read `"... (not used by automated experiment runs)"` ([qt_ui.py:742](src/thermo_acoustic/qt_ui.py:742)) -- mirrored by the matching `"(overrides WFG tab)"` labels on the Experiment tab's own equivalents, extended to the same full field set for consistency ([qt_ui.py:1097-1119](src/thermo_acoustic/qt_ui.py:1097)).
- **Test:** `test_wfg_tab_and_experiment_tab_carry_live_use_labels` -- spot-checks representative labels/checkbox text on both tabs.

**Task C -- systematic collapse re-audit, one new (self-inflicted) finding, fixed.** Measured every `QGroupBox` (24 total: 15 in `qt_ui.py`, 9 in `qt_ui_v2.py`, across every `MainWindow` tab, `MainWindowV2`'s main window, its `InitializationDialog`, and all four manual-panel dialogs) offscreen, comparing actual laid-out height against `minimumSizeHint()`. Found one real case: the WFG tab's **"Ch1"/"Ch2" groups**, squeezed to `541x626` actual against a `1092x820` required minimum inside `qt_ui.MainWindow`'s fixed-size tab page -- **directly caused by this same session's Task B**, whose longer live-use labels pushed the group's required width well past what fit. (`_ad_settings_group()`, fixed in Session 28, remains correctly fixed -- its `minimumSizeHint` dropped from 1005px to 109px once wrapped, confirmed still holding.) All other 22 group boxes checked clean -- a few have minor *width*-only compression (e.g. Experiment tab's "Experiment"/"Flush settings" groups, `qt_ui_v2`'s "Global Status" panel, both intentionally width-capped) which does not cause the 0-1px row-collapse failure mode and was not treated as the same bug class.
- **Fix:** `_wfg_channel_group()` ([qt_ui.py:695-790](src/thermo_acoustic/qt_ui.py:695)) wraps its Carrier/Trigger/FM Mod/Sweep content in a `QScrollArea` (`setWidgetResizable(False)`, `maximumHeight(500)`, both scrollbars as-needed) -- `False` rather than `True` here specifically, unlike `_ad_settings_group()`'s fix, because this group was short in *both* width and height, and `True` would still try to compress the width; matches the pattern already proven for `qt_ui_v2.py`'s AD2 Output Parameters table instead. Re-measured offscreen: `minimumSizeHint` dropped to `94x109`, actual `456x327` -- no longer squeezed, in both `qt_ui.MainWindow`'s tab and `qt_ui_v2`'s manual WFG dialog (same builder function, both surfaces confirmed fixed together).
- **Test:** `test_no_group_box_is_squeezed_below_its_minimum_size_hint` -- generic, `findChildren(QGroupBox)`-driven across every tab, no hardcoded list.

**Task D -- independent re-verification, zero gaps found in either window; nothing to fix.** Constructed `qt_ui.MainWindow` and `qt_ui_v2.MainWindowV2` as two separate live objects in the same process (the second built *after* the first already existed, to specifically test whether a second window type has its own installation path) and ran the `findChildren()` sweep on each independently: **`qt_ui.MainWindow`: 118 widgets, 0 failures. `qt_ui_v2.MainWindowV2`: 38 widgets, 0 failures.** Additionally swept `qt_ui_v2`'s manual WFG panel `QDialog` specifically (43 widgets, 0 failures) and directly re-tested the exact two fields named in the report (`exp_ch1_freq`/`exp_wait_after_flush`) through the v2 window object -- both correctly blocked an unfocused wheel change. Confirmed the installation mechanism itself is single-point and instance-independent: `install_focus_wheel_guard()` runs inside `MainWindow.__init__()` ([qt_ui.py:354](src/thermo_acoustic/qt_ui.py:354)), which `MainWindowV2.__init__()` reaches via `super().__init__()` -- every window of either type gets the same one `QApplication`-level filter automatically, confirmed empirically (`app._thermo_acoustic_focus_wheel_guard` is `None` before the first window and set immediately after). **No installation-mechanism gap was found to fix.** Consistent with Session 28's finding: could not reproduce the reported live value-change via any automated means, on either window, tested independently this time as explicitly requested.
- **Test:** `test_wheel_guard_completeness_on_both_window_types_independently` -- sweeps both window types as separate objects, reports counts for each, plus the two specifically-named fields.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py).

**Verification:** tested (169 passing, up from 165 -- 4 new tests; 2 pre-existing tests updated in place for the kHz unit change, e.g. `.setValue(1_975_000.0)` -> `.setValue(1975.0)`, both now-current line-by-line). Not hardware-verified -- all offscreen/synthetic. As with Session 28, a genuinely hardware/OS-specific wheel-delivery quirk remains formally unruled-out for Task D's original report, though two independent, thorough investigation passes now find nothing in this codebase that would produce it.

### Session 30 -- settings.json Hz->kHz migration fix (Session 29's self-flagged breaking change)

**Investigated per user priority flag, confirmed the gap was real, then fixed it.** Read `_settings_dict()`/`_load_settings()` ([qt_ui.py:2081-2308](src/thermo_acoustic/qt_ui.py:2081)) directly: no version key, no unit marker, and no plausible-range heuristic was available either -- `exp_ch1_freq`/`exp_ch2_freq`/the WFG channel `frequency` spin boxes all have no configured upper bound, so a "value looks too large to be kHz" check would have no reliable threshold. Confirmed via `grep` that exactly two persisted-field groups are affected by Session 29's Hz->kHz switch: `wfg[i]["frequency"]` (WFG-tab Carrier Frequency) and `experiment.ch1_frequency`/`ch2_frequency` (Experiment-tab Carrier Frequency). Two things Session 29 could have made worse but didn't: the FM-sweep `sweep_center_khz`/`sweep_width_khz` fields were never added to `_settings_dict()`'s output at all (nothing to migrate, confirmed by absence), and `mso_sample_frequency` was correctly left alone in Session 29 (its dict key was already `sample_frequency_hz` and its label still reads "Sample Frequency (Hz)").
- **Fix:** added `"schema_version": 2` to `_settings_dict()`'s output. `_load_settings()` now checks `data.get("schema_version", 1) < 2`; if true (i.e. the file predates this session, including the user's own real `.thermo_acoustic_ui.json`, confirmed present on disk with no `schema_version` key), it divides the two affected field groups by 1000 in-memory *before* the existing load logic applies them to the now-kHz widgets, and the post-load status message changes from `"Settings loaded"` to an explicit `"Settings loaded (legacy file: WFG/Experiment carrier frequencies auto-converted from Hz to kHz -- verify values before running)"` -- satisfying the user's "at minimum warn on load" bar, on top of doing the actual auto-convert. Saving after a legacy load writes `schema_version: 2`, so a file is converted exactly once, not on every subsequent load.
- **Test:** `test_qt_ui_load_settings_auto_converts_legacy_hz_scale_frequencies` -- loads a synthetic pre-Session-29 file (`1975000.0`, no `schema_version` key), asserts the WFG/Experiment widgets read back `1975.0` kHz and the status text flags the conversion; then re-saves and reloads via a fresh `MainWindow`, asserting the now-`schema_version: 2` file is *not* converted a second time (would otherwise silently divide an already-correct kHz value by 1000 again).

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py).

**Verification:** tested (52/52 passing across `test_qt_ui_hardware_settings.py` + `test_qt_ui_v2.py`, 1 new test, all pre-existing tests pass unmodified). Not hardware-verified -- offscreen/synthetic only; the user's real on-disk `.thermo_acoustic_ui.json` was confirmed to exist and lack `schema_version`, so it will exercise the conversion path on next real launch, but that real launch itself was not performed here.

### Session 31 -- First real-hardware, single-continuous-run verification of the full experiment lifecycle (no code changes)

**This is the first time in this project's history that Initialize -> configure Experiment tab -> Start exp -> Abort -> a clean Flush-enabled run -> data.tdms/TIFF inspection -> settings.json migration -> `qt_ui_v2` was run as one continuous session against real hardware, through the actual GUI widgets** (real AD2 via the WaveForms DLL, real Hamamatsu camera, real Qmix pump, real Rheodyne valve on COM5) -- not the standalone `hardware_tests/test_real_workflow_smoke.py` script (which bypasses the GUI and drives `Application`/`Experiment2` directly), and not module-level fakes. Every prior verification in this log, including the "manual-tab/automated-path parity" audits (Sessions 21-23) and every "tested" line elsewhere in this document, was either offscreen/fake-based or a standalone hardware script exercising one narrow slice at a time. This is why the three bugs below were never caught by the existing suite: two of them (Abort, `FlushSettings.timeout_s`) only manifest under real elapsed wall-clock time and real concurrent-thread hardware behavior, which fakes complete instantly and synchronously; the third (`QMIXSDK`) only manifests when the real `qmixsdk` package is actually imported, which the fake-backed test suite never does.

**Three confirmed real-hardware-only bugs** (fixed in Session 32 below):
1. **Abort does not stop a running experiment series.** Started a real 4-repeat series, fired Abort ~0.9s in (mid-capture, `queue_count` still `4`). The abort worker itself finished cleanly at 0.94s (`status='Aborted'`), but `_run_experiment_series()`'s while loop ([qt_ui.py:1735](src/thermo_acoustic/qt_ui.py:1735), pre-fix) kept running regardless and completed **all 4 repeats** with real data at 5.86s (`status='ExperimentComplete'`). Root cause: `_abort()` ([qt_ui.py:1788](src/thermo_acoustic/qt_ui.py:1788)) only calls `app.fire_stop_event()`, which nothing in the while-loop or `Application.listen_abort()` ([application.py:236](src/thermo_acoustic/application.py:236), checked at [application.py:402](src/thermo_acoustic/application.py:402)) ever reads.
2. **`FlushSettings.timeout_s`** ([workflows.py:58-62](src/thermo_acoustic/workflows.py:58), pre-fix) **is wrong by a factor of ~60.** `(flush_volume_ml / flush_flowrate) * 1000.0 + 5.0` omits the minutes-to-seconds conversion (the real Qmix device's flow unit is configured as uL/min by `QmixPumpBackend.initialize()`). A real 0.05 ml / 200 uL/min flush needs ~15s but the formula computed ~5.25s; the still-successfully-moving real pump was declared failed by Session 7's (independently correct) "surface flush failures loudly" logic, which then hard-stopped the whole series (`ExperimentFlushFailed`). A retry at 3000 uL/min (same 0.05 ml volume, comfortably inside the same buggy window) completed cleanly, confirming the rest of the flush path (real valve `wait_until_ready` poll, real pump move) works correctly once given enough time.
3. **The real Qmix pump cannot initialize via `qt_ui.py`'s Initialize button on a clean environment.** `hardware_factory.build_hardware_bundle()` (pre-fix) never set the `QMIXSDK` environment variable or called `os.add_dll_directory()` before `qmixsdk` is first imported. Confirmed via direct traceback: `ctypes.windll.LoadLibrary("labbCAN_Bus_API")` -> `FileNotFoundError`, because `QMIXSDK` was unset at User/Machine/Process scope on this machine (verified via `[Environment]::GetEnvironmentVariable`). `hardware_tests/test_real_workflow_smoke.py` already knows to set this (its own line 1178) but that fix was never carried into the main app's real Initialize path. Worked around in the verification harness's own process (not a code change) to continue testing the rest of the pipeline against real pump/valve hardware.

**Also empirically reinforces an already-known open item, with new hard evidence:** camera trigger source `"Internal"` (hardcoded since Session 13) is confirmed via real per-frame `dcam_clock:` timestamp deltas (~0.0316s, matching the camera's own readout time) to **not** be paced by the DO clock's configured frame period (0.2s at 5 fps) at all -- frames are captured back-to-back at the camera's own free-run rate. Per explicit instruction this finding is tracked but not touched (needs oscilloscope verification, not fixable from software alone).

**Positive confirmations** (things this pass hardware-verified as working correctly for the first time, or reconfirmed against real hardware): the real valve `"S"` status-query handshake (flagged unverified since Session 2) returned `status_note="confirmed"`; partial-initialization rollback correctly cleaned up AD2/camera when pump failed first; the DO clock is genuinely configured with real values end to end (`DORun`/`DOWait`/`DOFreq` in the real `data.tdms`, not the old `{}` placeholder state); the kHz-labeled Experiment-tab fields (Session 29) correctly convert to Hz for both the real WFG hardware call and the TDMS metadata (`WFGFreqCh1=1000.0` from a `1.0` kHz field); real per-frame DCAM timestamps are captured (Session 8, not previously hardware-verified); `GitCommitHash` in `data.tdms` matches real `git rev-parse HEAD` plus the correct `-dirty` suffix; TDMS write-verification (Session 26) passed against the real `nptdms` 1.11.0 package on genuinely-written files; the settings.json legacy Hz-scale migration (Session 30) correctly converts and warns on a real `MainWindow()` construction; `qt_ui_v2.MainWindowV2` was confirmed to share the identical `Application`/state layer via a real completed run (not just structural inspection).

**Side effects from this verification pass, disclosed and partially corrected:** `MainWindow.closeEvent()` auto-saves settings on close; since real-hardware mode (`sim_*` unchecked) was used for testing and the window was closed via script, the user's real, git-untracked `.thermo_acoustic_ui.json` had real-hardware mode persisted as its default-next-launch state. `sim_ad2`/`sim_camera`/`sim_pump`/`sim_valve` were explicitly restored to checked (the safe default) as the final action of the verification session; other Experiment-tab fields in that file (frequencies, frames, flush settings, series path) still reflect test values, with no backup of the originals available (the file has no git history). Separately, `COM4` became access-denied where it was freely openable before the session started; no process from the verification session was found holding it (confirmed via `Get-Process`), cause unconfirmed.

**Files touched:** none -- verification only, per explicit instruction not to fix anything found until reported. Real hardware run artifacts (data.tdms + TIFFs from the abort-run and both flush-run attempts) left under `hardware_tests/output/qt_ui_e2e_verification/` (gitignored), matching this project's existing convention for real-hardware smoke output.

**Verification:** real hardware throughout (see above); this is the verification itself. Findings fixed in Session 32.

### Session 32 -- Fixes for the three real-hardware-only bugs found in Session 31

**Task 1 (highest priority) -- Abort now stops further repeats from starting.** [qt_ui.py:1735-1770](src/thermo_acoustic/qt_ui.py:1735): `_run_experiment_series()` now calls `self.app.create_stop_event()` before its loop (clearing any abort flag left over from a previous run, so a fresh "Start exp" click isn't immediately treated as pre-aborted), and checks `self.app.stop_fired` at the top of each iteration before starting the next repeat. **Design choice: the in-progress repeat is allowed to finish (or be disrupted by `_abort_hardware()`'s existing concurrent hardware stop) rather than being forcibly interrupted mid-flight** -- cutting off a repeat partway through a real camera capture or, worse, mid-flush (mid pump-motion) risks leaving hardware in an ambiguous state; only *further, not-yet-started* repeats are guaranteed not to run. On abort, the loop now returns `"ExperimentSeriesAborted"` (a new, distinct status from both `"ExperimentComplete"` and the per-repeat `"ExperimentAborted"`) instead of continuing to drain the queue.
- **Test:** `test_run_experiment_series_stops_queuing_further_repeats_after_abort` ([tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)) -- a fake `Application.run_experiment2()` genuinely dequeues from a real 3-repeat `ExperimentSeries2` (matching real queue semantics, not just a call counter) and fires `self.fire_stop_event()` after the first repeat, exactly mirroring what `_abort()` does; asserts only 1 of 3 repeats ran, the returned status is `"ExperimentSeriesAborted"`, and `series.see_elements_left() == 2` (the queue does not drain to completion).

**Task 2 -- `FlushSettings.timeout_s` minutes-to-seconds conversion fixed.** [workflows.py:58-67](src/thermo_acoustic/workflows.py:58): now computes `(flush_volume_ml * 1000.0 / flush_flowrate) * 60.0 + 5.0` (convert ml->uL, divide by the real uL/min flow rate for minutes, x60 for seconds, plus the existing 5s margin) in place of the old `(flush_volume_ml / flush_flowrate) * 1000.0 + 5.0`, which was short by exactly that factor of 60.
- **Test:** `test_flush_settings_timeout_converts_ul_per_minute_to_seconds` ([tests/test_application.py](tests/test_application.py)) -- the exact real-hardware-failing case (0.05 ml / 200 uL/min) now computes `20.0s`, and asserts this exceeds the real move duration (`15.0s`) it needs to cover. `test_flush_settings_timeout_is_zero_for_nonpositive_flowrate` preserves the existing zero-flowrate guard behavior.

**Task 3 -- `QMIXSDK` environment variable now set by `build_hardware_bundle()`.** [hardware_factory.py](src/thermo_acoustic/hardware_factory.py): new `_ensure_qmixsdk_env()` calls `os.environ.setdefault("QMIXSDK", str(default_hardware_config().qmix.qmixsdk_path))`, called from `build_hardware_bundle()` whenever `not config.sim_pump` (i.e. only when a real pump backend is about to be built), mirroring exactly what `hardware_tests/test_real_workflow_smoke.py` already does at its own line 1178. `setdefault` (not unconditional assignment) so an operator or CI environment that has already pointed `QMIXSDK` somewhere specific is not overridden. This does not touch the separately-tracked, still-disabled "Qmix SDK Python Path"/"Qmix QMIXSDK Path" Initialize-dialog stub fields (Session 3) -- it only ports the environment-variable precondition those fields' absence was blocking, using the same `default_hardware_config()` default the rest of the app already relies on.
- **Test:** three tests in [tests/test_hardware_factory.py](tests/test_hardware_factory.py) -- `test_build_hardware_bundle_sets_qmixsdk_env_for_real_pump` (sets the expected default when unset), `test_build_hardware_bundle_does_not_override_existing_qmixsdk_env` (`setdefault` semantics preserved), `test_build_hardware_bundle_leaves_qmixsdk_env_unset_for_simulated_pump` (no-op when `sim_pump=True`).

**Camera trigger source finding: deliberately not touched**, per explicit instruction -- already tracked (Session 13/19), needs oscilloscope verification against real hardware to resolve Internal-vs-External correctness, not fixable from software alone.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [workflows.py](src/thermo_acoustic/workflows.py), [hardware_factory.py](src/thermo_acoustic/hardware_factory.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py), [tests/test_application.py](tests/test_application.py), [tests/test_hardware_factory.py](tests/test_hardware_factory.py).

**Verification:** tested (176 passing, full suite, 6 new tests this session, all pre-existing tests pass unmodified). **Not yet re-verified against real hardware** -- all three fixes are covered by fake/offscreen tests only; the bugs they fix were only ever catchable via the real-hardware run in Session 31 (see that session's note on why the existing fake-based suite could not have caught them), and a follow-up real-hardware run specifically re-exercising Abort-mid-series and the 0.05 ml/200 uL/min flush case has not been performed since these fixes landed.

### Session 33 -- Real-hardware re-verification of the three Session 32 fixes (no code changes)

Targeted follow-up to Session 32's note that its fixes were untested against real hardware -- explicitly authorized by the user to actuate real AD2/camera/pump/valve again, scoped to just re-exercising the three specific fixes (not a full repeat of Session 31's seven-step walkthrough). All three fixes **hold up against real hardware.** No new bugs found.

**Pre-check: COM4.** Access-denied at the end of Session 31 (cause unconfirmed there). Still access-denied at the start of this session (`PermissionError(13, 'Access is denied.')`), with no python process alive at any point before or during this session (`Get-Process python*` empty both times) and `Win32_PnPEntity` reporting the underlying `USB Serial Port (COM4)` device status as `OK` -- confirming some other process/service on this machine holds it, not this project's code. **By the end of this session it was free again** (`serial.Serial('COM4')` opened/closed cleanly), with nothing in this session having touched COM4 directly. Transient, external, self-resolved; not investigated further as it's outside the three fixes' scope.

**Task 1 -- Abort mid-repeat-2: PASS, all four sub-criteria.** Real 4-repeat series (frames=5, fps=5, exposure=15ms, CH0 1 kHz/0.1V/2.0s run -- same conservative parameters as Session 31, not the full acoustic drive). Instrumented both the `queue_count` progress signal and `_handle_worker_finished` with real timestamps:
- `queue_count` reached `3` (repeat 1 done, repeat 2 beginning) at **2.413s**.
- Abort fired at **3.334s** -- 0.913s into repeat 2, deliberately mid-capture, not at a repeat boundary.
- **(a) Repeat 2 was allowed to finish, not cut off:** the abort worker itself (hardware force-stop) finished cleanly at 3.353s (`status='Aborted'`), but repeat 2 continued and genuinely completed -- `queue_count` dropped to `2` at **4.578s**, and `repeat_002/` contains a real `data.tdms` and 5 real TIFF frames (not truncated/corrupt).
- **(b) Repeats 3 and 4 never started:** `repeat folders actually created under series_path: ['repeat_001', 'repeat_002']` -- no `repeat_003`/`repeat_004` directory exists at all.
- **(c) Status confirmed `'ExperimentSeriesAborted'`**, not `'ExperimentComplete'` -- both `win.status.text()` and `app.status` matched.
- **(d) Re-Initialize after abort succeeded:** `System Initialized`, `error_status: OK`, no errors -- hardware recovered cleanly.
- Total: series settled 1.249s after Abort was fired (4.583s total from Start exp), matching "repeat 2 finishes, nothing further starts," not an instant or a full-queue-drain.

**Task 2 -- Flush timeout fix, exact Session-31-failing parameters: PASS.** `flush_volume_ml=0.05`, `flush_flowrate=200.0` uL/min (identical to the failing run). Corrected `FlushSettings.timeout_s` computed to **20.000s** (vs. the old buggy ~5.25s). Real status timeline: `Flushing` @ 2.277s -> `Waiting for Pump` @ 3.376s -> `FlushComplete` @ 13.219s -- the real pump move took **9.843s**, comfortably inside the new 20s window and nowhere near either the old 5.25s ceiling or the new one. Full run completed: `ExperimentComplete`, `error_status: OK`, real `data.tdms` (1332 bytes) + 5 real TIFF frames, `pump.fill_level` correctly updated `1.0 -> 0.95`.

**Task 3 -- QMIXSDK auto-set, zero manual environment setup: PASS.** Confirmed `QMIXSDK` unset in a fresh Python process (`os.environ.get('QMIXSDK') is None`) before launching. Real `qt_ui.py` Initialize (exactly the operator path, no environment workaround by the test harness this time -- Session 31's own harness-level `os.environ.setdefault("QMIXSDK", ...)` workaround was removed from the verification script for this session) succeeded fully: all four devices connected (`app.pump.backend` is a real `QmixPumpBackend`, not simulated), `status: System Initialized`, valve `status_note: confirmed`. Separately isolated the mechanism itself in a single process: `QMIXSDK` was `None` before calling `build_hardware_bundle(sim_pump=False)`, and `'C:\\Users\\Lab user\\AppData\\Local\\CETONI_SDK'` (matching `default_hardware_config().qmix.qmixsdk_path` exactly) immediately after -- direct proof `_ensure_qmixsdk_env()` is what did it, not an artifact of the test setup.

**Side-effect discipline.** `.thermo_acoustic_ui.json` was backed up before any hardware interaction and restored **byte-for-byte identical** afterward (`diff` confirmed no differences), an improvement over Session 31 where only the `sim_*` checkboxes were restored and other fields were left at test values. No lingering python processes at any point (`Get-Process python*` empty before and after).

**Files touched:** none -- verification only, per explicit instruction. Real hardware run artifacts left under `hardware_tests/output/qt_ui_e2e_verification/` (`abort_mid_repeat2/`, `session33_flush_retry/`), gitignored, alongside Session 31's existing output.

**Verification:** real hardware throughout (see above). All three Session 32 fixes now hardware-confirmed, not just fake/offscreen-tested. No new bugs found in this pass.

### Session 34 -- Frequency Scanning / Dynamic Frequency implemented; .pytest_tmp* gitignore housekeeping

**Task 1 -- Frequency Scanning implemented.**

**(a) Re-check performed before changing anything, per instruction.** Confirmed `_build_experiment_series()` ([qt_ui.py:1712](src/thermo_acoustic/qt_ui.py:1712), pre-change) still called `config = self._experiment_wfg_config()` exactly once, outside the `for repeat in range(...)` loop, and passed the same `config` object to every `Experiment2` -- unchanged since the original Session 14 investigation despite kHz unification (Session 29), WFG live-use labeling (Session 29), and the Abort-stops-series fix (Session 32) all having touched this same function in between. The task was exactly as large as the original investigation implied, not smaller.

**(b) Restructured to build WFG config fresh per repeat.** [qt_ui.py:1712-1770](src/thermo_acoustic/qt_ui.py:1712): `_build_experiment_series()` now calls `self._experiment_wfg_config(frequency_override_hz=...)` *inside* the loop -- architecturally parallel to the existing `self._experiment_do_clock_config(repeat)` call right next to it, which was already built fresh per repeat. Regression-tested first: `test_frequency_scanning_off_keeps_wfg_config_identical_across_repeats` confirms Ch1/Ch2 carrier frequencies are identical across all repeats when the new feature is off, before any new behavior was layered on.

**(c) Feature implemented per LabVIEW's spec, with the kHz unit update.** New Experiment-tab group "Frequency Scanning (Dynamic Frequency, Ch1 only)" ([qt_ui.py](src/thermo_acoustic/qt_ui.py), `_experiment_frequency_scan_group()`): `exp_freq_scan_enable` (Dynamic Frequency toggle), `exp_freq_scan_start_khz`/`exp_freq_scan_stop_khz` (**kHz**, not Hz -- the original Session 14 investigation predates the Session 29 kHz unification and would have used Hz; this implementation uses kHz throughout, consistent with every other WFG Carrier frequency field on this tab), `exp_freq_scan_count` (Number of Frequencies). `_experiment_frequency_scan_list_hz()` generates the linear-spaced Hz list; `_experiment_channel_config()` ([qt_ui.py:1264](src/thermo_acoustic/qt_ui.py:1264)) gained a `frequency_override_hz` keyword-only parameter applied **only when `index == 0`** (Channel 1) -- Channel 2's own config path never receives it, matching the LabVIEW spec's Ch1-only scope.

**(d) Inference explicitly flagged as inference, not fact.** Two places in the new code carry an explicit comment distinguishing "this is what was implemented" from "this is confirmed LabVIEW behavior": `_experiment_frequency_scan_list_hz()`'s linear-spacing assumption, and the substitution mechanism's framing as "architecturally parallel to Dynamic Camera Start Time" rather than independently re-derived from `CreateExperiments.vi`'s compiled block-diagram wiring (which the original investigation could not read past the cluster's typedef structure, the same opacity already hit for trigger source and WFG symmetry/phase in earlier sessions).

**(e) Repeats/frequency-count mismatch raises `ValueError` before starting.** [qt_ui.py:1712-1720](src/thermo_acoustic/qt_ui.py:1712): when Dynamic Frequency is enabled, `_build_experiment_series()` compares `len(frequency_scan_hz)` against `Repeats` and raises immediately -- before any folder is created or hardware is touched -- matching the existing Camera-FPS<=0 and flush-volume-exceeds-capacity convention rather than a silent LabVIEW-style fallback. `test_frequency_scanning_repeats_mismatch_raises_before_starting` confirms both the raise and that no series-path folder is created as a side effect of the attempt.

**(f) Confirmed no changes needed elsewhere; end-to-end test added.** `DoConfig`/LED-clock derivation, `data.tdms` field definitions, and `ExperimentSeries2` needed zero changes -- `Application.run_experiment2()` already reads `experiment.wfg_config` per-`Experiment2` instance (not a shared series-level object), so once (a)/(b) made that object genuinely differ per repeat, the existing `WFGFreqCh1` TDMS property pipeline picked up the swept value automatically. `test_frequency_scanning_swept_value_reaches_real_tdms_metadata` confirms this concretely: builds a real 3-repeat series with Frequency Scanning enabled (1900-1975 kHz, 3 points), calls the real `Experiment2.create_folder_and_tdms()`/`save_settings()` for each repeat against the existing fake-`nptdms` test harness (imported from `test_application.install_fake_nptdms`, reused rather than duplicated), and asserts each repeat's `WFGFreqCh1` property matches its swept frequency (1,900,000 / 1,937,500 / 1,975,000 Hz) exactly.

**Incidental layout fix required.** Adding the new group as a third box stacked in the Experiment tab's already-tight middle column (alongside the existing "Experiment" and "Flush settings" groups) tripped the generic `test_no_group_box_is_squeezed_below_its_minimum_size_hint` regression guard (Session 29) -- not just the new group but the two pre-existing ones in that column collapsed below their `minimumSizeHint` too, once the same 0-1px row-collapse failure mode Session 28 fixed for the "Analog Discovery Settings" group recurred here. Fixed the same way: new `_experiment_settings_column()` wraps all three group boxes in one `QScrollArea` (`setWidgetResizable(True)`, `maximumHeight(360)`), replacing the two separate direct `grid.addWidget(...)` calls for the numbers/flush groups.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (4 new tests: `test_frequency_scanning_off_keeps_wfg_config_identical_across_repeats`, `test_frequency_scanning_substitutes_ch1_only_per_repeat`, `test_frequency_scanning_repeats_mismatch_raises_before_starting`, `test_frequency_scanning_swept_value_reaches_real_tdms_metadata`).

**Deliberate scope decision, not an oversight:** the new `exp_freq_scan_*` fields are **not** added to `_settings_dict()`/`_load_settings()` (settings.json persistence) -- the task's explicit (a)-(f) checklist did not include this, and "keep tests minimal" was an explicit instruction. Every other `exp_ch1_*`/`exp_ch2_*` field is persisted (Session 22's own convention); a future session wiring persistence for this group should follow that exact pattern.

**Verification:** tested (180 passing, full suite, 4 new tests this session, all pre-existing tests pass unmodified including the layout regression guard once the scroll-area fix landed). Not hardware-verified -- this feature has never been exercised against real AD2 hardware; unlike FM Sweep (Session 16), which reused an already real-hardware-verified `configure_wfg()` call path unchanged, Frequency Scanning's only new runtime behavior is which Hz value gets written into the same `CarrierSettings.frequency_hz` field per repeat, so the real-hardware risk surface is small, but a dedicated real run (multi-repeat, Dynamic Frequency on, confirming each repeat's actual AD2 output frequency differs as expected) has not been done.

**Task 2 -- .pytest_tmp* gitignore housekeeping.** Added `.pytest_tmp*/` and `_pytest_tmp/` to [.gitignore](.gitignore) (the latter for the one differently-named `_pytest_tmp` directory found alongside the dot-prefixed family -- same throwaway-scratch category, added for completeness beyond the literal instruction). Confirmed via `git check-ignore -v` that both patterns now match. Attempted removal of every leftover `.pytest_tmp_*`/`_pytest_tmp` directory from prior sessions (20 directories, dated 2026-07-20 through 2026-07-23): all 20 remain `Permission denied` on this machine, including to `Get-Acl` itself (`UnauthorizedAccessException`) -- consistent with this machine's already-documented (Session 27) `tmp_path`-adjacent permission quirk, not something introduced or fixable in this session. Per instruction, not blocked on; reported and moved on. Five new `.pytest_tmp_freqscan_*` directories created by this session's own test runs *were* successfully removed, confirming the permission issue is specific to those 20 pre-existing directories (likely an ACL/ownership artifact from whatever process originally created them) rather than a blanket inability to delete anything matching this naming pattern.

**Files touched:** [.gitignore](.gitignore).

**Verification:** `git check-ignore -v` confirms both new patterns match; `git status` confirms no `.pytest_tmp*`/`_pytest_tmp` content appears in the working-tree diff. No test suite impact (housekeeping only).

### Session 35 -- FM Sweep Start/Stop Frequency UI conversion; calibration relabel; Frequency Scanning Step Size option

**Frequency Scanning and FM Sweep remain two distinct features, per explicit instruction -- nothing below merges or conflates them.**

**Task 1 -- FM Sweep: Center+Width -> Start+Stop Frequency (pure UI-layer conversion).** Session 16 exposed the FM-node hardware math's own Center+Width parameterization directly to the user (a paper-narrative framing, from the Martens et al. reference case). Replaced with Start/Stop Frequency inputs on both tabs, matching Digilent's own WaveForms sweep tool convention and general function-generator practice -- the FM-node math itself (`FmSweepSettings`, `fm_mod_settings()`, the actual hardware-writing calls in `waveforms.py`) is **completely unchanged** from Session 16; only the conversion point moved one layer earlier.
- **Manual WFG tab** ([qt_ui.py:565-566](src/thermo_acoustic/qt_ui.py:565), state dict renamed `sweep_center_khz`/`sweep_width_khz` -> `sweep_start_khz`/`sweep_stop_khz`): `_fm_sweep_settings_from_state()` now computes `center_hz=(start_hz+stop_hz)/2.0`, `width_hz=abs(stop_hz-start_hz)` before constructing `FmSweepSettings` -- everything after that point is byte-for-byte the same code as Session 16.
- **Experiment tab** ([qt_ui.py](src/thermo_acoustic/qt_ui.py), `exp_sweep_center_khz`/`exp_sweep_width_khz` -> `exp_sweep_start_khz`/`exp_sweep_stop_khz`): `_experiment_fm_sweep_settings()` converted identically.
- **Reference test updated, not the physics.** The Martens et al. reference case (center 1.934 MHz, width 50 kHz) is now expressed as Start=1909.0/Stop=1959.0 kHz -- confirmed exactly: `(1909+1959)/2 = 1934`, `|1959-1909| = 50`. `test_fm_sweep_settings_match_martens_et_al_reference_case` (ad2.py-level, constructs `FmSweepSettings` directly) needed **no change** since that dataclass's own `center_hz`/`width_hz` API is untouched; only the qt_ui.py-level tests that drive the now-renamed widgets were updated (`test_frequency_fields_display_khz_but_round_trip_to_correct_hz_hardware_value`, `test_fm_sweep_toggle_on_carries_settings_into_experiment_wfg_config`), and all assert the exact same resulting `center_hz=1_934_000.0`/`width_hz=50_000.0` as before -- **confirmed via passing tests that the actual hardware-facing frequency/amplitude values sent to the FM node are numerically identical to Session 16; only the input UI changed.**
- **Top/Bottom Frequency live-readout labels removed, not kept.** These existed on the manual WFG tab only (the Experiment tab's Sweep section never had them) to turn Center+Width into a range a human could sanity-check at a glance. With Start/Stop now the *direct* inputs, Top and Bottom would be identical to Stop and Start respectively -- pure redundancy with zero added information, unlike before. Removed `sweep_top_khz`/`sweep_bottom_khz` state entries and the `_connect_sweep_bounds_refresh()`/`_refresh_sweep_bounds()` machinery that computed them.

**Task 2a -- misleading "calibration" header text fixed on both tabs, differently, because the two tabs genuinely behave differently.** The identical copy-pasted header ("Sweep (FM modulation calibration -- distinct from Frequency Scanning)") was ambiguous about whether "calibration" meant "manual/independent" or "not real hardware" -- and on the Experiment tab specifically it was actively misleading, since Session 16's own note already established that tab's FM Sweep integration **is** applied to real automated Experiment runs when enabled (unlike the underlying LabVIEW `WfgConfigureSweepCh1.vi`, which is itself unreachable from any real LabVIEW experiment path). Fixed per-tab, matching the existing Session 29 WFG live-use-labeling convention rather than inventing new wording:
  - Manual WFG tab ([qt_ui.py:807-810](src/thermo_acoustic/qt_ui.py:807)): *"Sweep (FM modulation, manual tab only -- independent from the Experiment tab, distinct from Frequency Scanning)"*.
  - Experiment tab ([qt_ui.py:1177-1180](src/thermo_acoustic/qt_ui.py:1177)): *"Sweep (FM modulation, applied to real automated Experiment runs when enabled -- distinct from Frequency Scanning)"*.

**Task 2b -- Step Size added as an alternative to Number of Frequencies for Frequency Scanning.** New `exp_freq_scan_step_khz` field ([qt_ui.py](src/thermo_acoustic/qt_ui.py), default `0.0`) in the "Frequency Scanning" group, labeled "Step Size (kHz) (0 = use Number of Frequencies)". **Design decision:** 0 means "not used" (matching this codebase's existing zero-means-disabled convention, e.g. `custom_syringe_volume_ml` only applying when "Custom" is selected); when set above 0, Step Size takes precedence over the Number of Frequencies widget, with the point count derived as `round(abs(stop_hz-start_hz)/step_hz) + 1` (minimum 1) rather than both fields being independently authoritative and potentially disagreeing. This is a Python-only convenience addition, not part of the original LabVIEW `FrequencyHelper.vi` spec (which only exposes Start/Stop/Number-of-Frequencies) -- noted as such in the code comment. The existing Repeats-vs-frequency-count `ValueError` check is unaffected: it compares against the actual computed list length regardless of which input method produced it.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (`test_frequency_fields_display_khz_but_round_trip_to_correct_hz_hardware_value` and `test_fm_sweep_toggle_on_carries_settings_into_experiment_wfg_config` updated to the new Start/Stop values; new `test_frequency_scanning_step_size_overrides_count_when_nonzero`).

**Verification:** tested (181 passing, full suite, 1 new test this session, all pre-existing tests -- including the two updated FM Sweep tests and the group-box layout-squeeze regression guard -- pass with the new widgets). Not hardware-verified -- same as Session 16 and Session 34, no real AD2 output has been used to confirm this UI-layer change; the numerical-equivalence claim above is verified by the passing unit tests asserting identical `center_hz`/`width_hz`/`fm_mod_settings()` output, not by a real hardware run.

### Session 36 -- Fresh screenshot review: WFG label verbosity, stale Camera ROI text, Experiment-tab regrouping, PumpValve/Initialization layout, "MX Valve 2" cleanup

Label/layout-only fixes from a fresh screenshot review of both UIs (Initialization, WFG, MSO, PumpValve, Camera, Experiment tabs). No functional or value changes -- confirmed by the full existing test suite passing unmodified except where a test asserted the literal old label text.

**Task 1 -- WFG tab label verbosity, fixed via option (a).** Every Carrier/Trigger field repeated " (overridden during experiment run)" (30-35 chars) and every FM Mod field repeated " (not used by automated experiment runs)" (41 chars) on its own row ([qt_ui.py:742](src/thermo_acoustic/qt_ui.py:742), [qt_ui.py:800](src/thermo_acoustic/qt_ui.py:800) pre-change). **Chose option (a)** (shorten the suffix itself) over option (b) (single sentence + compact marker): the tab already has a top-level note stating the general rule, but "overridden" (an active Experiment-tab analog exists) and "unused" (no analog exists at all) are genuinely different reasons worth keeping distinguishable per field -- a single generic marker/icon would lose that distinction, and Qt has no cheaper built-in compact form-row annotation. Shortened to `" (overridden)"` (13 chars) and `" (unused)"` (9 chars).
- **Measured before/after, offscreen.** The `_spin()`/`_int_spin()` factories hard-cap every spin box at `setMaximumWidth(125)` ([qt_ui.py:74](src/thermo_acoustic/qt_ui.py:74), pre-existing, unrelated to this task) -- so the value fields' own absolute pixel width does not change (125px either way; there was no available-space-based compression happening at the widget level). What genuinely was causing the cramped appearance, confirmed by measuring the actual row `QLabel`s: the longest row label dropped from **840px** ("Run duration...(overridden during experiment run)") to **576px** for the identical row, and every other row shrank 30-45% similarly -- reducing how much of each row's width the label claims relative to the field, and shrinking the group's internal content width (reducing how much horizontal scrolling the existing `QScrollArea(setWidgetResizable=False)` needs to show, per Session 29).
- **Incidental finding, not fixed (out of this task's explicit scope):** the Session 35 sub-header `QLabel("Sweep (FM modulation, manual tab only...)")` on this same tab is actually the single widest element in the group (1332px, no `setWordWrap`), wider than any of the row labels this task shortened. Noted here for a future pass, not touched -- Task 1 was scoped to the specific repeated per-row phrase, not every long label on the tab.
- **Test updated:** `test_wfg_tab_and_experiment_tab_carry_live_use_labels` ([tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)) now asserts the shortened text.
- **qt_ui_v2.py:** no separate change needed -- its manual WFG panel opens `qt_ui.py`'s own `_wfg_tab()` unchanged (`_MANUAL_PANEL_BUILDERS`), so the fix applies automatically.

**Task 2 -- stale "476 is Vertical is max for 100 fps" label removed.** [qt_ui.py:1004](src/thermo_acoustic/qt_ui.py:1004) (pre-change) deleted outright, per instruction, with no hardcoded replacement. **No live-computed hint added in its place**: the manual Camera tab has no "Camera FPS" field of its own to compare an achievable-FPS figure against (that's an Experiment-tab-only concept, read by `Application._check_camera_timing_budget()`), and this tab can be shown before a camera is connected, so a live query here isn't reliably available without risking exactly the kind of new hardcoded/placeholder fallback the instruction said to avoid.

**Task 3 -- GlobalExposure and Dynamic Camera Start Time regrouped, in both UIs.**
- `qt_ui.py`: `GlobalExposure` moved into `_experiment_numbers_group()` ([qt_ui.py:1232](src/thermo_acoustic/qt_ui.py:1232), directly below "Exposure time (ms)"); `Dynamic Camera Start Time` moved into `_camera_start_group()` ([qt_ui.py:1252](src/thermo_acoustic/qt_ui.py:1252), as the first row above the array it toggles). The two isolated `grid.addWidget(...)` pairs removed from `_experiment_tab()`'s own grid.
- `qt_ui_v2.py`: **needed its own separate fix** -- `_v2_acquisition_group()` does not call the shared `_camera_start_group()`; it builds its own local "Camera Start Array(s)" `QGroupBox`. `GlobalExposure` was already correctly adjacent to Exposure time there (no change needed), but `Dynamic Camera Start Time` was grouped with the unrelated acquisition params on the opposite side from the array group -- moved into that local group's own layout ([qt_ui_v2.py:309](src/thermo_acoustic/qt_ui_v2.py:309)), mirroring the same regroup.
- **Test added:** `test_experiment_tab_regroups_global_exposure_and_dynamic_camera_start` confirms both checkboxes are now children of the group boxes they logically belong to, not merely present somewhere on the tab.

**Task 4 -- PumpValve tab restructured into balanced columns.** [qt_ui.py:895](src/thermo_acoustic/qt_ui.py:895) (`_pump_tab()`, pre-change) was a sparse `QGridLayout` with individual widgets hand-placed at specific row/col coordinates spanning 13 rows and 7 columns, with entire rows/columns (e.g. column 1, rows 4 and 7) left empty -- there was no oversized group box to simply cap (only one group box existed, "Flush Settings," already naturally sized), so **chose the "reorganize into balanced columns" option**, not the "reduce allocated space" option. Restructured into 4 `QGroupBox`-per-column layout: Valve + Stop, Pump + Syringe, Flow Control, Flush (count/button + the existing Flush Settings group). Measured offscreen: natural `sizeHint` dropped from an implied ~13-row-tall sparse grid to **1559x232** -- wide and short, matching the actual content instead of a tall sparse grid with dead space below and to the right. `qt_ui_v2.py`'s manual PumpValve panel reuses `_pump_tab()` directly, so no separate v2 change needed.

**Task 5 -- Initialization tab: fixed the fixable part, documented the rest as a Qt architectural constraint.** Two distinct causes were found, only one of which is a per-tab layout defect:
1. **Fixed:** `_init_tab()`'s `QGridLayout` ([qt_ui.py:661](src/thermo_acoustic/qt_ui.py:661)) placed "Hardware" (395px natural height, 12 real fields) and "Simulation" (125px natural height, 4 checkboxes) in the same row with no per-cell alignment -- Qt's default behavior stretches a cell's widget to fill the row height when no alignment is given, so Simulation was being inflated to 395px, leaving ~270px of dead space inside its own box. Fixed by adding `Qt.AlignmentFlag.AlignTop` to that specific `addWidget()` call; confirmed offscreen that Simulation's geometry now matches its own 306x125 sizeHint.
2. **Not fixed, documented as out of scope:** the tab's own natural content height (~457px) vs. its actual rendered height inside the running app (~730px) gap is a `QTabWidget` characteristic -- every tab page shares one viewport sized to the tallest tab (Experiment), so a much sparser tab is stretched to match regardless of its own internal layout. Eliminating this fully would require resizing the whole window on every tab switch, which is worse UX than the current dead space and a materially bigger, riskier change than a label/layout pass -- not attempted.

**Task 6 -- "MX Valve 2" investigated and confirmed to be the same stray-artifact class as "SeriesPath 2"/"ExposureTime(ms) 2"/"Flush Settings 2" (already fixed in earlier sessions), not a distinct device.** Confirmed via `grep`: "MX Valve 2" ([qt_ui.py:704](src/thermo_acoustic/qt_ui.py:704), pre-change) was the *only* occurrence of "MX Valve" anywhere in the codebase (including the dead `ui.py:175`) -- no "MX Valve 1" or unsuffixed "MX Valve" exists to make "2" a real index, and there is exactly one `Valve` class/instance in the entire system (`self.valve_enabled`/`self.valve_resource` are both singular, never indexed, confirmed extensively in prior hardware-parity audits). Cross-checked against `git log -S"SeriesPath 2"`, which confirmed that exact same fix pattern (drop the stray LabVIEW front-panel disambiguation suffix, keep the label otherwise unchanged) was already applied for "SeriesPath 2" in commit `3474232`. Renamed to plain "MX Valve" in `qt_ui.py` only -- **deliberately not touched in `ui.py`**, which still has all three of the un-cleaned equivalents (`ui.py:294,331,345,366,369`), consistent with this project's established convention of flagging but not selectively editing pieces of that confirmed-dead file. **Test added:** `test_init_tab_hardware_group_uses_clean_mx_valve_label`.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (1 test updated for the shortened labels, 2 new tests added).

**Verification:** tested (183 passing, full suite, 2 new tests this session, 1 existing test updated for the new shortened label text, all other pre-existing tests -- including the group-box layout-squeeze regression guard, re-run against every group touched this session -- pass unmodified). No functional/value changes: every fix in this session is label text, widget parent/position, or layout structure only; no widget's read value, signal wiring, or downstream config-building logic changed. Not hardware-verified -- purely cosmetic/layout, no hardware interaction possible to verify against.

### Session 37 -- Valve Open/Closed labeling; MSO tab dead-space fix; WFG QScrollArea re-verified as still needed

**Task 1 -- valve positions labeled with confirmed Open/Closed semantics, in both UIs and at the source.** Position 1 = Open, Position 2 = Closed is a confirmed physical fact previously invisible in the UI (buttons/labels only showed "Pos1"/"Pos2").
- [instruments.py:691-694](src/thermo_acoustic/instruments.py:691) (`Valve` class): added a class-level comment documenting the mapping next to `command_position_1`/`command_position_2`, plus a one-line note at [instruments.py:728](src/thermo_acoustic/instruments.py:728) (`set_position()`) -- so the semantics are documented in code, not only in the UI.
- `qt_ui.py`'s `_pump_tab()` ([qt_ui.py:922-947](src/thermo_acoustic/qt_ui.py:922)): button text `"Pos1"`/`"Pos2"` -> `"Pos1 (Open)"`/`"Pos2 (Closed)"`; row labels `"Valve Pos1"`/`"ValvePos2"` -> `"Valve Pos1 (Open)"`/`"ValvePos2 (Closed)"`; the transient action-status message shown while the click is processed updated to match. `qt_ui_v2.py`'s manual PumpValve panel reuses `_pump_tab()` directly, so no separate edit needed there.
- **Additional place found and fixed, beyond the buttons/labels literally named in the task:** `qt_ui_v2.py`'s Global Status panel has a live "Valve position" readout ([qt_ui_v2.py:391](src/thermo_acoustic/qt_ui_v2.py:391)) that displayed the raw numeric `self.app.valve.position` (`"1"`/`"2"`) with no Open/Closed indication -- the same safety-relevant gap this task is about, just in a status display rather than a button. New `_valve_position_text()` ([qt_ui_v2.py:525](src/thermo_acoustic/qt_ui_v2.py:525)) maps `1 -> "1 (Open)"`, `2 -> "2 (Closed)"`, anything else -> `"Unknown"`.
- **Test added:** `test_pump_tab_valve_position_buttons_show_open_closed_semantics`.

**Task 2 -- MSO tab dead space fixed, same bug class as the Initialization tab's Simulation group (last round), same architectural limit documented again.** Measured offscreen: `_mso_tab()`'s ([qt_ui.py:870](src/thermo_acoustic/qt_ui.py:870)) `QHBoxLayout` placed "MSO Configuration" (270px natural height) and "Waveform" (305px natural height) side by side with no per-widget alignment -- Qt's default behavior stretched *both* to 356px (taller than either's own sizeHint), the identical mechanism already fixed for the Init tab's Simulation group. Fixed by adding `Qt.AlignmentFlag.AlignTop` to both `content.addWidget(...)` calls ([qt_ui.py:903-906](src/thermo_acoustic/qt_ui.py:903)); confirmed offscreen both group boxes now render at their own natural height (270px / 305px). **The remaining gap is the same `QTabWidget` shared-viewport limit documented for the Initialization tab in Session 36, not a new or differently-solved issue**: this tab's own natural sizeHint is 904x323, but it renders at 1106x730 inside the running app because every tab page shares one viewport sized to the tallest tab (Experiment) -- reported here explicitly rather than attempting a different, tab-specific workaround, per instruction. `qt_ui_v2.py`'s manual MSO panel reuses `_mso_tab()` directly, so no separate edit needed.

**Task 3 -- WFG tab's `QScrollArea` (Session 29) re-verified as still necessary; not removed.** Measured offscreen, after last round's Task 1 label-shortening fix landed: the Ch1 group's inner content widget (Carrier+Trigger+FM Mod+Sweep, ~25 rows) has a natural `sizeHint` of **1350x763**, while the group's actual allocated space in the running tab is **456x327** -- content still needs **~3x the width and ~2.3x the height** available. **Verdict: still clearly needed, not a borderline case.** The width figure is now dominated less by the per-row labels (which did shrink significantly last round) and more by the still-unwrapped Session 35 Sweep sub-header (`"Sweep (FM modulation, manual tab only..."`, 1332px, flagged as an incidental out-of-scope finding in Session 36 and still not fixed) -- but even setting that aside, the height alone (763 vs. 327) confirms real per-field content still exceeds the group's available space. No code change made for this task, as instructed when the answer is "still needed."

**Files touched:** [instruments.py](src/thermo_acoustic/instruments.py), [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (1 new test, `QPushButton` added to the file's imports).

**Verification:** tested (184 passing, full suite, 1 new test this session, all pre-existing tests -- including the group-box layout-squeeze regression guard, re-run against the MSO and Pump&Valve groups touched this session -- pass unmodified). No functional/value changes: Task 1 is label text (plus one new but equivalent status-text helper in v2); Task 2 is a layout-alignment-only fix; Task 3 made no code change at all. Not hardware-verified -- label/layout-only, no hardware interaction possible to verify against.

### Session 38 -- FM Sweep dual-mode correction, systematic truncation sweep, grounded tooltips, Custom Volume investigation

**Task 1 -- FM Sweep dual-mode input corrected.** Session 37 replaced Center+Width with Start+Stop instead of adding Start+Stop *alongside* Center+Width -- the exact "offer both, replace neither" principle already established for Frequency Scanning's Number of Frequencies vs. Step Size (Session 35), violated here. Fixed: Center Frequency (kHz) and Width (kHz) restored on both the manual WFG tab's per-channel state (`sweep_center_khz`/`sweep_width_khz`, [qt_ui.py:787-788](src/thermo_acoustic/qt_ui.py:787)) and the Experiment tab (`exp_sweep_center_khz`/`exp_sweep_width_khz`, [qt_ui.py:622-623](src/thermo_acoustic/qt_ui.py:622)). New `_connect_sweep_dual_mode_refresh(start, stop, center, width)` ([qt_ui.py:879](src/thermo_acoustic/qt_ui.py:879)) wires `valueChanged` both directions with a reentrancy guard: editing Start/Stop recomputes and updates Center/Width, and vice versa -- neither pair is ever hidden. `FmSweepSettings`/`fm_mod_settings()`/every hardware-writing call are untouched. `qt_ui_v2.py` needs no separate change: its manual WFG panel reuses `_wfg_tab()` directly, and its Experiment-tab AD2 table has never shown FM Sweep controls at all (a separate, pre-existing gap noted since Session 25, out of scope here). **Reference test re-verified both directions:** `test_fm_sweep_dual_mode_start_stop_and_center_width_stay_in_sync` confirms Start=1909/Stop=1959 -> Center=1934/Width=50 and the reverse, on both tabs, plus a round-trip through an unrelated intermediate value (Center=2000/Width=100 -> Start=1950/Stop=2050) to confirm the sync isn't a one-shot coincidence.

**Task 2 -- systematic offscreen truncation sweep across every tab, not just the three reported instances.** Wrote a standalone sweep script comparing every `QLabel`'s actual rendered width/height against its required text width (or wrapped-height) and every spin box's `sizeHint()` against its actual/capped width, across all six tabs at the app's real default size.
- **(a) Start Frequency field ("1900." instead of "1900.000").** Root cause was systemic, not field-specific: `_spin()`/`_int_spin()` ([qt_ui.py:74](src/thermo_acoustic/qt_ui.py:74)) capped **every** `QDoubleSpinBox`/`QSpinBox` in the app at `setMaximumWidth(125)`, while real `sizeHint()` values measured up to 252px across nearly every spin box in every tab -- not an isolated bug. Raised the shared cap to `_SPIN_MAX_WIDTH = 260`, comfortably covering every sizeHint measured. This alone cleared every spin-box finding on the Initialization/WFG/MSO/Experiment tabs; a handful of narrower residual cases remained on PumpValve/Camera where the field shares a column with a long label (fixed alongside, see below).
- **(b) "Waveform Graph" label ("aveform Graph").** Not reproducible as outright clipping in this offscreen environment at the app's default size, but only a ~5px safety margin existed between required (168px) and actual (173px) width at the app's own **minimum** window size (980x680) -- fragile enough to explain a screenshot at a slightly narrower real window. `setMinimumWidth(200)` added ([qt_ui.py:1258](src/thermo_acoustic/qt_ui.py:1258)) for real headroom.
- **(c) Sweep group header ("no visible closing context").** Confirmed: both Sweep headers ([qt_ui.py:860](src/thermo_acoustic/qt_ui.py:860) manual tab, [qt_ui.py:1380](src/thermo_acoustic/qt_ui.py:1380) Experiment tab) had `wordWrap=False` and rendered at their full unwrapped width (1332px / 1356px) inside a horizontally-scrollable `QScrollArea` whose visible viewport is much narrower (~432px) -- since scrolling starts at the left edge, the closing words were never visible without scrolling right. Fixed with `setWordWrap(True)` + `setMaximumWidth(450)` on both. **Side effect, measured:** this was the single widest element in the WFG Ch1 group -- wrapping it dropped the group's own content `sizeHint` from 1350px to 840px (38% narrower), reinforcing (not overturning) Session 37's "still needed" verdict on the group's `QScrollArea`.
- **Other truncations found and fixed by the same sweep** (not among the three named): several `QFormLayout` row labels on the Pump&Valve tab ("Number of flushes" at 60px actual vs. 204px required, "Flow Rate (-=aspirate, +=dispense)" at 132px vs. 408px, plus four others) and the Camera tab ("Conversion Method", "Minimum/Maximum Value") -- fixed generically via `form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)` on every affected `QFormLayout`, wrapping a label onto its own line instead of clipping it, rather than manually shortening each label's wording. The Camera tab's "If the button is grayed out..." instructional label (not in a `QFormLayout`, so `WrapLongRows` didn't apply) got `setWordWrap(True)` + a bounded width directly. The Camera tab's "Sequence" group's own wrapped note then needed more row-height than a single grid row gave it (48px actual vs. 68px required) -- spanning more rows fixed the wrap but pushed the *group's* own `minimumSizeHint` past its allocated space, tripping the Session 28 collapse guard; fixed the same way as `_ad_settings_group()`: the grid moved onto its own content widget inside a `QScrollArea`.
- **Tests:** `test_frequency_scanning_start_field_fits_full_precision`, `test_waveform_graph_label_has_safety_margin`, `test_sweep_headers_wrap_instead_of_needing_full_single_line_width` (the three named findings); the layout-squeeze regression guard and one existing grid-position-dependent test (`test_camera_sequence_group_flags_live_automated_use_and_dead_capture_mode`, updated for the Sequence group's new scroll-wrapped structure) cover the rest.

**Task 3 -- grounded tooltips added across all six tabs, sourced only from this repo's own established documentation.** Every tooltip cites a specific prior session, a real code path/function name, or an explicit changelog caveat (UNCONFIRMED/SUSPECTED-PLACEHOLDER classifications from the Session 18 hardcoded-constants audit, "unverifiable" from Session 6, "not wired to a real backend" from Session 3) -- none invented. Representative coverage, not exhaustive:
- **Initialization:** the same six fields v2's `InitializationDialog` already disables (Session 3) -- `z_backend`, `thorlabs_apt_serial`/`thorlabs_apt_backend`/`thorlabs_apt_discovery_only`, `qmix_sdk_python_path`/`qmix_qmixsdk_path` -- were **not** disabled on this tab in `qt_ui.py` itself, a real inconsistency between the two UIs for the exact same stub fields. New `MainWindow._mark_unwired_stub()` ([qt_ui.py:750](src/thermo_acoustic/qt_ui.py:750)) applies the identical disable+tooltip treatment here too.
- **WFG/Experiment tabs:** Symmetry/Phase (waveform shape effect), secRun/secWait/Repeat/Trigger source semantics, Sweep Type's unconfirmed enum mapping, the Start/Stop<->Center/Width dual-mode relationship, Step Size's "0 = use Number of Frequencies" convention, Frequency Scanning's linear-spacing-inferred-not-confirmed caveat.
- **MSO:** Sample Frequency's 100 MS/s AD2 spec (UNCONFIRMED against this device), Range's 1V-default-vs-2V-real-signal clipping risk (SUSPECTED-PLACEHOLDER).
- **Pump&Valve:** valve Open/Closed (redundant with the Session 37 label, reinforced on hover), Custom Volume's real relationship (Task 4, below), Flow Rate's unverifiable sign convention (Session 6), WaitAfterFlush's purpose, syringe preset BD-spec provenance (Session 17).
- **Camera:** DCAM Trigger Source's unresolved Internal/External status (Sessions 13/19), ROI defaults' divergence from the validated-hardware combination (Session 18), the Sequence cluster's live-automated-use status (Session 22).
- **Test:** `test_representative_fields_have_grounded_tooltips` spot-checks one or two fields per tab.

**Task 4 -- Custom Volume traced: inert for named presets, and has zero effect on `ConfigureSyringe`'s real geometry call either way.** Traced `_syringe_volume_ml()` ([qt_ui.py:1663](src/thermo_acoustic/qt_ui.py:1663)): `custom_syringe_volume_ml` is read only as a fallback when `Syringe="Custom"` (ignored for the three named BD presets, which have their own known volumes) -- and it feeds *only* the flush-volume-vs-syringe-capacity safety check (`FlushSettings.syringe_volume_ml`), never the real syringe geometry. Traced further: `_configure_syringe()` ([qt_ui.py](src/thermo_acoustic/qt_ui.py)) sends `{"name": syringe}` to `CetoniPump.configure_syringe()` and nothing else -- **incidental finding, not fixed:** selecting "Custom" and clicking Configure Syringe will always fail with a real `QmixPumpError`, since "Custom" isn't in `SYRINGE_PRESETS` and no `inner_diameter_mm`/`stroke_mm` is ever supplied for it by this UI. Fixed per option (a): `custom_syringe_volume_ml` is now disabled whenever `Syringe != "Custom"` (`_update_custom_syringe_volume_enabled()`, [qt_ui.py](src/thermo_acoustic/qt_ui.py), wired to `syringe.currentTextChanged`), matching the established stub-marking convention, plus a tooltip explaining the real relationship. `qt_ui_v2.py` needs no separate change (reuses `_pump_tab()` directly). **Test:** `test_custom_syringe_volume_disabled_unless_syringe_is_custom` confirms the enable/disable toggling and that a disabled widget's value is still read correctly (just not user-editable).

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py) (Waveform Graph label was v1-only; the earlier session's PumpValve/MSO fixes are the only v2-shared surface touched this session, unaffected), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (7 new tests, 1 existing test updated for the Sequence group's new structure).

**Verification:** tested (190 passing, full suite, 7 new tests this session, all pre-existing tests -- including the layout-squeeze regression guard re-run against every group touched -- pass with one updated for a structural change it depended on). No functional/value changes beyond Task 4's intentional enable/disable toggle (which doesn't change what value is read, only whether it's editable) and Task 1's dual-mode sync (which keeps the *same* physical value expressible two ways, verified identical downstream). Not hardware-verified -- label/tooltip/layout-only, no hardware interaction possible to verify against.

### Session 39 -- Full self-directed audit-and-fix pass across qt_ui.py and qt_ui_v2.py, all 8 categories

A comprehensive, user-authorized audit reusing this project's own established methodologies (Session 21's manual-tab/automated-path parity trace, Session 28's offscreen sizeHint layout-collapse check, Session 28/29/33's `findChildren()`-based completeness sweep) across all 8 recurring issue classes that have surfaced repeatedly in this project's history. Worked category-by-category, one at a time, with a changelog checkpoint and full green test run after each. This entry covers **Category 1 (Functional Correctness)**; later categories are appended as their own dated sub-entries below as the pass proceeds.

**Category 1 -- Functional Correctness.** Traced every button/checkbox/field in both `qt_ui.py` and `qt_ui_v2.py` to whether it actually reaches the real behavior its label claims, following the same "trace to the real call, don't trust the name" method as the Session 21 parity audit. Re-read the entire 2963-line `qt_ui.py` and 558-line `qt_ui_v2.py` top to bottom (not a keyword search) to catch anything a targeted grep would miss.

**Confirmed and fixed:**
- **`sequence_exposure_ms` was still dead, despite being flagged since Session 11.** [qt_ui.py:573](src/thermo_acoustic/qt_ui.py:573) (the Camera tab's Sequence group "ExposureTime(ms)" field): Session 11's audit named this field, alongside `capture_mode`, as "constructed and displayed but never read." `capture_mode` was fixed in Session 24 (disabled + tooltip + "(unused)" label suffix) but `sequence_exposure_ms` was never actually touched -- confirmed by grep: it appears only at its own construction and its own `addRow()` call, never inside `_camera_sequence_settings()` ([qt_ui.py:2039](src/thermo_acoustic/qt_ui.py:2039)) or any other reader. Worse than `capture_mode`'s case: this field's row label, "ExposureTime(ms)", is byte-for-byte identical to the real, live `self.exposure_ms` field's label in the same tab's ROI group -- a user has no way to tell from the UI alone which of the two identically-labeled fields actually reaches `configure_exposure_time()`. Fixed the same way as `capture_mode`: `setEnabled(False)` + a tooltip explaining it's dead and pointing at the real field, and the row label changed to `"ExposureTime(ms) (unused)"` ([qt_ui.py:1432](src/thermo_acoustic/qt_ui.py:1432)).
  - **Test:** extended `test_camera_sequence_group_flags_live_automated_use_and_dead_capture_mode` ([tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)) with assertions that `sequence_exposure_ms` is disabled, carries the "Not wired to a real backend" tooltip, its row label reads `"ExposureTime(ms) (unused)"`, and `"exposure_ms"` is absent from `_camera_sequence_settings()`'s output.

**Investigated and confirmed NOT a bug (no action needed):** the WFG tab's shared `Flow Rate` field feeding both "Generate Flow" and "Go to Level" (intentional dual-use of one physical parameter, not two controls silently fighting); `conversion_min`/`conversion_max` (correctly read-only display-only readouts of the last conversion's range, never meant to be inputs); the "MasterPulse" dropdown value's mapping into DCAM's `TRIGGERSOURCE` enum (traced `_mapped_value()`'s lowercasing -- `"MasterPulse"` correctly resolves, no case-sensitivity bug); `wfg_sync`/`Custom Volume`/`Custom` syringe geometry (already correctly disabled/documented from prior sessions, re-confirmed still accurate).

**Flagged for the user's decision, not fixed (genuine design-scope fork, not a confirmed bug):** Save Settings/Load Settings persistence is incomplete for a large fraction of this app's fields -- the manual WFG tab's Trigger/FM Mod/Sweep sub-fields (only Carrier's idx/frequency/amplitude/offset/symmetry/phase/function/enable are saved), the entire Pump&Valve tab (syringe selection, Custom Volume, Flow Rate, Level, manual Flush settings), the entire Camera tab (ROI, exposure, conversion policy, and -- notably -- the Sequence cluster fields that Session 22 made load-bearing for automated runs: Mode/Source/Interval/Burst/Trigger Source/Polarity/Delay), and several Experiment-tab fields added after the original save/load implementation (Camera FPS, Camera Start, Camera Start Array, Dynamic Camera Start Time, GlobalExposure, FM Sweep, Frequency Scanning -- the last of which Session 34 already noted as a deliberate scope decision, not an oversight). This predates all 38 prior sessions -- it is baseline behavior, not a regression introduced recently. Whether Save/Load Settings was ever intended to comprehensively snapshot the entire app (in which case this is a real, if long-standing, gap) or was always meant to cover only hardware-connection + core experiment-repeat parameters (in which case the current partial scope is by design) cannot be determined from the code or this project's history -- a genuine fork in what the "correct" design is, per this pass's own instruction to stop and flag rather than guess. **Not implemented.** If comprehensive persistence is wanted, the fix is mechanical (extend `_settings_dict()`/`_load_settings()` following the exact tolerant `if key in data` pattern already used everywhere else) but touches a large surface area across every tab, so it's flagged here for an explicit decision rather than unilaterally expanded.

**Files touched this category:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (1 existing test extended, no new test function).

**Verification:** tested (190 passing, same count as Session 38 -- one existing test extended with new assertions, no test added or removed; full suite green). Not hardware-verified -- label/enable-state-only change, no hardware interaction possible to verify against.

**Category 2 -- Label Accuracy.** Re-verified every "(overridden)" / "(overrides WFG tab)" / "(unused)" / "(not used by automated experiment runs)" style annotation across both files by tracing the actual code path each one claims, not by trusting the existing text -- the same method used to write these labels in Sessions 24/29/36 in the first place, re-run fresh.

**Re-traced and confirmed still accurate (no change needed):** every WFG-tab "(overridden)" label against `_experiment_channel_config()`'s field-by-field reads from `self.exp_ad2_channels`, not `self.wfg_channels` ([qt_ui.py:1764](src/thermo_acoustic/qt_ui.py:1764)); every WFG-tab FM Mod "(unused)" label against the confirmed-hardcoded/sweep-replaced `fm_mod` in the same function; every Experiment-tab "(overrides WFG tab)" label (the converse claim); the Camera tab Sequence group's live-use note, verified field-by-field against `_camera_sequence_settings()` and `_build_experiment_series()`'s override of `"frames"`/`"trigger_source"` -- the note's own field list (Mode/Source/Interval/Burst/Polarity/Delay) precisely excludes exactly the two fields (Frames, Dcam Trigger Source) that are actually overridden, confirmed correct down to that level of detail; the `_instrument_group()`/`InitializationDialog` "Not wired to a real backend" stub tooltips, re-checked against a fresh `grep` of `hardware_factory.py` (still zero references to `z_backend`/`thorlabs_apt_*`/`qmix_sdk_python_path`/`qmix_qmixsdk_path`); `cetoni_config_path`'s and `valve_resource`'s "genuinely used" tooltips (both still flow through `HardwareRuntimeConfig` into real SDK calls); `dcam_source`'s tooltip against the still-current `"Internal"` hardcode in `_build_experiment_series()`; `exp_camera_fps`/`exp_ch1_run` tooltips against `Application._check_camera_timing_budget()`/`_ad2_trigger_completion_seconds()`, both confirmed to still exist and behave as described.

**Confirmed and fixed -- a real, if narrow-window, accuracy bug:** `qt_ui_v2.py`'s Global Status "Experiment running" indicator ([qt_ui_v2.py:514](src/thermo_acoustic/qt_ui_v2.py:514), pre-change) derived its Yes/No from `self._busy_count and "experiment" in self.app.status.lower()`. Traced every status string `Application`/`qt_ui.py` fire during a real series run: this heuristic happens to hold up for the normal per-repeat boundary refresh (every terminal status `run_experiment2()` can end on -- `ExperimentComplete`/`ExperimentFlushFailed`/`ExperimentAborted` -- contains "experiment"), but breaks the instant **Abort** is clicked mid-series: `_abort()`'s own `_run_action(..., "Aborting...", ...)` immediately overwrites `self.app.status` to `"Aborting..."` (no "experiment" substring) via `_set_status()`, while the series' current repeat -- per Session 32's own explicit design choice -- is allowed to keep running to completion rather than being cut off. During that window, the indicator would report "Experiment running: No" while a repeat could genuinely still be mid-flush or mid-capture -- misleading for exactly the safety-relevant purpose this indicator exists for.
- **Fix:** [qt_ui.py:2330](src/thermo_acoustic/qt_ui.py:2330): `_run_experiment_series()` is now a thin wrapper that emits a new `"experiment_series_active"` progress kind (`True` before, `False` in a `finally` block covering every exit path -- normal completion, `ExperimentSeriesAborted`, or a raised `RuntimeError`) around the renamed `_run_experiment_series_body()`, which is otherwise byte-for-byte the original method. `_handle_worker_progress()` ([qt_ui.py:2617](src/thermo_acoustic/qt_ui.py:2617)) sets `self._experiment_series_active` from this progress kind -- marshaled through the existing `progress.emit()` Qt signal mechanism (the method runs on a background `QThread` via `ActionWorker`), not set directly from the worker thread. `qt_ui_v2.py`'s indicator ([qt_ui_v2.py:517](src/thermo_acoustic/qt_ui_v2.py:517)) now reads this explicit flag instead of the status-text heuristic.
- **Tests:** `test_run_experiment_series_brackets_experiment_series_active_progress` ([tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)) confirms the `True`/`False` bracketing on both the successful path and the raised-`RuntimeError` path (flag must clear even when a repeat fails); `test_v2_experiment_running_indicator_reads_explicit_flag_not_status_text` ([tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py)) reproduces the exact stale-status scenario (`status="Aborting..."`, flag `True`) and confirms the indicator now correctly reads "Yes".

**Files touched this category:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (1 new test), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py) (1 new test).

**Verification:** tested (192 passing, up from 190 -- 2 new tests, all pre-existing tests pass unmodified). Not hardware-verified -- the underlying progress-signal mechanism is the same one already used for `queue_count`/`status`/`waveform` throughout this codebase, but this specific flag has only been exercised via fakes/offscreen Qt, not a real hardware Abort-mid-series run.

**Category 3 -- Layout.** Reused the Session 28 offscreen `sizeHint`-vs-allocated-space method, but pointed it at two places the existing generic regression guard (`test_no_group_box_is_squeezed_below_its_minimum_size_hint`, Session 29) structurally cannot reach: (1) `qt_ui_v2.MainWindowV2`'s own groups and manual-panel dialogs, since that guard only walks `window.tabs.currentWidget()` and v2 has no `QTabWidget`; (2) the app's documented *minimum* window size (980x680, `self.setMinimumSize()`), since the existing guard only ever checked the 1280x820 default.

**Confirmed and fixed -- two real, previously-uncovered squeeze/truncation bugs:**
- **`qt_ui_v2.py`'s "Global Status" panel truncated nearly every value label.** [qt_ui_v2.py:361](src/thermo_acoustic/qt_ui_v2.py:361) (`_global_status_panel()`, pre-change): the group's own `minimumSizeHint()` measured 534x269 against a hardcoded `setMaximumWidth(280)` -- every value `QLabel` in its `QFormLayout` (AD2/Camera/Pump/Valve connection status, "Pump state / fill level", etc.) was rendering at a fixed 34px regardless of its own required width (e.g. "Not connected" needing 156px, "idle, fill 0.000 ml" needing 228px) -- clipped in the running app the entire time this panel has existed, on every window size, never caught because no test ever measured it. **Fix:** applied `QFormLayout.RowWrapPolicy.WrapLongRows` (the same established pattern already used for the Pump&Valve tab's narrow-column truncation, Session 38) -- confirmed offscreen this alone resolves every `QLabel` truncation without widening the panel; `setMaximumWidth` bumped from 280 to 300 to match the (now much smaller, post-wrap) `minimumSizeHint` exactly, removing a min>max inconsistency. The four connection-status labels (which can carry real long dynamic text, e.g. the valve's `"Connected (unverified position response: '...')"` passthrough from Session 2) additionally got `setWordWrap(True)` as a second layer of protection beyond the extra row width WrapLongRows provides.
- **`qt_ui.py`'s "Camera Start Array(s)" group collapses at the app's own minimum window size.** [qt_ui.py:1685](src/thermo_acoustic/qt_ui.py:1685) (`_camera_start_group()`, pre-change): invisible at the 1280x820 default the existing guard checked, but at 980x680 (the app's own `setMinimumSize()` -- a size any user can resize down to) this group's 11 rows (Dynamic Camera Start Time + 10 array fields) measured 252px actual against a 346px `minimumSizeHint`, the same 0-1px row-collapse failure mode fixed for "Analog Discovery Settings" (Session 28), the WFG tab's Ch1/Ch2 groups (Session 29), and the Experiment tab's numbers/flush/frequency-scan column (Session 34). **Fix:** same pattern as all three of those -- content moved onto its own `QScrollArea` (`setWidgetResizable(True)`, `setMaximumHeight(360)`) instead of laying directly into the group. `qt_ui_v2.py`'s own separately-built "Camera Start Array(s)" group (`_v2_acquisition_group()` builds its own copy rather than calling `_camera_start_group()`, confirmed by re-checking the call graph) was independently re-measured at both sizes and found not to exhibit this failure -- no change needed there.

**Test coverage extended to close the gaps that let both bugs go undetected:** `test_no_group_box_is_squeezed_below_its_minimum_size_hint` ([tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)) now checks both the 1280x820 default and the 980x680 minimum, not just the default. Two new v2-specific tests in [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py): `test_v2_no_group_box_is_squeezed_below_its_minimum_size_hint` (the same generic `findChildren()`-based sweep, extended to `MainWindowV2` itself and all four manual-panel `QDialog`s, at both 1440x860 and 980x680) and `test_v2_global_status_panel_does_not_truncate_value_labels` (reproduces the specific truncation with both a short-text and a real long-text case, confirming word-wrap now applies).

**Files touched this category:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (1 existing test extended), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py) (2 new tests).

**Verification:** tested (194 passing, up from 192 -- 2 new tests, 1 existing test extended, all pre-existing tests pass unmodified). Not hardware-verified -- layout-only, no hardware interaction possible to verify against.

**Category 4 -- Stale/Dead Text.** Looked for hardcoded static text that was superseded by a real dynamic check elsewhere but never cleaned up (the "476 is Vertical is max for 100 fps" precedent, Session 36) -- and separately, for static text presenting itself as a live value that was never wired to anything at all.

**Confirmed and fixed -- a live-looking display that has been 100% static since this UI's inception:** the Experiment tab's (and `qt_ui_v2.py`'s "Status / Progress" group's) "Elapsed Time" and "Time Left" readouts ([qt_ui.py:1497](src/thermo_acoustic/qt_ui.py:1497), [qt_ui_v2.py:211](src/thermo_acoustic/qt_ui_v2.py:211), pre-change) were both constructed as bare `QLabel("00:00:00")` -- not even assigned to a `self.` attribute, meaning no code anywhere in this project's history could ever have updated them even if it tried. They render exactly like a live stopwatch/countdown (mirroring LabVIEW's own Elapsed Time/Time Left front-panel indicators, per this project's `Application Status` LabVIEW-parity framing) but have been frozen placeholders for the display's entire history -- never once flagged in any of the 38 prior sessions' audits, including the multiple dedicated layout/label sweeps (Sessions 24/28/29/36/38) that walked every widget in both files. Implementing a real elapsed/remaining-time tracker is a new feature (out of this pass's scope, per its own boundaries), so this was fixed the same way every other confirmed-dead widget in this codebase has been (`capture_mode`, Session 24; `sequence_exposure_ms`, this session's Category 1): marked as a non-functional stub via a new shared `_stale_static_display()` helper (disabled + tooltip explaining it's never updated), reached through new `_elapsed_time_label()`/`_time_left_label()` methods both `qt_ui.py`'s `_experiment_tab()` and `qt_ui_v2.py`'s `_v2_status_progress_group()` now call instead of constructing their own separate bare labels.
- **Tests:** `test_experiment_tab_elapsed_time_and_time_left_are_marked_as_stale_stubs` ([tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)) and `test_v2_elapsed_time_and_time_left_are_marked_as_stale_stubs` ([tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py)) confirm both labels in both windows are disabled and tooltipped.

**Flagged for the user's decision, not fixed (evidence points both ways):** the Initialization tab's "Analog Discovery 3" row label ([qt_ui.py:942](src/thermo_acoustic/qt_ui.py:942)) is the *only* place in the entire live codebase that calls this device generation "3" -- every other reference (the WFG/MSO tooltips, the "Analog Discovery Settings" group title, the `SimulatedAD2Sdk`/`AD2_SDK` class names used pervasively, and "the Analog Discovery 2's published spec" in `mso_sample_frequency`'s own tooltip) calls it "Analog Discovery 2"/"AD2" -- which initially looked like the same class of stray-number bug already fixed for "MX Valve 2" (Session 36, confirmed via the identical method: `grep` found the "3" has no sibling "Analog Discovery 1/2" row to justify it). **However**, `docs/PORTING_TBD.md:26` separately lists a real, still-open validation task -- "Exercise all MSO trigger source options on the real **AD2/AD3** hardware" -- implying this lab may genuinely have access to both an Analog Discovery 2 and a newer Analog Discovery 3 unit. That single reference is enough to make "was this row deliberately generic/AD3-inclusive, or is it a typo for '2'" a genuine fork this pass cannot resolve from the code or this project's own documentation alone -- exactly the kind of ambiguous question the boundaries say to flag rather than guess on. **Not changed.** The label's twin at `ui.py:167` (the confirmed-dead Tkinter UI) carries the identical "Analog Discovery 3" text, for what it's worth as corroborating context, not as evidence either way -- it was most likely copied from the same original source as `qt_ui.py`'s row, not independently authored.

**Files touched this category:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (1 new test), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py) (1 new test).

**Verification:** tested (196 passing, up from 194 -- 2 new tests, all pre-existing tests pass unmodified). Not hardware-verified -- both labels are inert placeholders with no hardware interaction to verify against.

**Category 5 -- Multi-Convention Fields.** Enumerated every parameter in both files offered through more than one legitimate input convention. Two exist: FM Sweep's Start/Stop Frequency vs. Center/Width Frequency (both tabs), and Frequency Scanning's Number of Frequencies vs. Step Size. FM Sweep was re-checked against Session 38's own fix and confirmed still genuinely bidirectional and in sync via `_connect_sweep_dual_mode_refresh()` on all four call sites (manual WFG tab x2 channels, Experiment tab) -- no regression. No other dual-representation field was found anywhere in either file (amplitude/exposure/ROI/trigger timing etc. are each offered through exactly one convention, so there is nothing to keep in sync there).

**Confirmed and fixed -- Frequency Scanning's "offer both" was real but not "kept in sync":** unlike FM Sweep, Step Size (when set above 0) silently overrode the actual point count `_experiment_frequency_scan_list_hz()` used ([qt_ui.py:1899](src/thermo_acoustic/qt_ui.py:1899)) without ever updating what the "Number of Frequencies" field displayed -- an operator relying on that field alone would see a stale, wrong count the moment Step Size took over. The Repeats-mismatch error message ([qt_ui.py:2289](src/thermo_acoustic/qt_ui.py:2289), pre-change) compounded this: it always said `"(Number of Frequencies)"` regardless of which field actually produced the mismatched count.
- **Fix (display sync).** New `_connect_frequency_scan_count_display_refresh()` ([qt_ui.py:1757](src/thermo_acoustic/qt_ui.py:1757)): whenever Start/Stop/Step change and Step Size is actively driving (`> 0`), "Number of Frequencies" is updated to show the real resulting count, using the identical rounding formula `_experiment_frequency_scan_list_hz()` uses. **Deliberately one-directional, not fully bidirectional like FM Sweep's fix:** auto-deriving a nonzero Step Size from an edited Count would silently flip Step Size from "0 = not used" to "active," changing which field drives future edits without the user asking for that -- a real behavior change, not just a display fix, and out of this pass's scope (changing what data reaches a hardware call, even indirectly through a mode-switch nobody requested, is exactly what the boundaries said not to do without flagging first). Editing "Number of Frequencies" directly continues to work exactly as before whenever Step Size is 0.
- **Fix (error attribution).** [qt_ui.py:2294](src/thermo_acoustic/qt_ui.py:2294): the mismatch error now names whichever field actually produced the count (`"Step Size"` when `> 0`, else `"Number of Frequencies"`), traced from the same precedence rule `_experiment_frequency_scan_list_hz()` itself uses.
- **Tests:** `test_frequency_scanning_number_of_frequencies_display_tracks_step_size` confirms the display updates live as Start/Stop/Step change, and that direct Count edits still work once Step Size returns to 0; `test_frequency_scanning_repeats_mismatch_error_names_the_true_count_source` confirms both branches of the error message.

**Files touched this category:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (2 new tests).

**Verification:** tested (198 passing, up from 196 -- 2 new tests, all pre-existing tests pass unmodified). Not hardware-verified -- this only changes which value a display widget shows and the wording of a pre-flight validation error; the actual Hz value reaching `CarrierSettings.frequency_hz` per repeat is unchanged (still computed by the same, untouched `_experiment_frequency_scan_list_hz()`).

**Category 6 -- Tooltip Grounding.** Scripted an enumeration of every `self.<name> = _spin/_int_spin/_combo/QCheckBox/QLineEdit(...)` construction in `qt_ui.py` (108 widgets) and cross-checked each against every `setToolTip(...)` call in the file (including indirect application via a shared tip variable/loop and the `_mark_unwired_stub()` helper, both of which produced false positives in a naive text search and were manually reconciled). Of the widgets with no tooltip, the large majority are genuinely self-evident given their row label alone (on/off hardware-enable checkboxes, plain counts, plain read-only status fields, Carrier fields already covered by the adjacent "(overridden)"/"(overrides WFG tab)" annotation) -- consistent with this category's own scope ("does every *non-self-evident* field have a tooltip"), so left untouched rather than tooltipped for the sake of it.

**Confirmed and fixed -- five fields with a real, traceable fact worth surfacing, each grounded in code checked this session (not invented):**
- **`prior_resource`** ([qt_ui.py:427](src/thermo_acoustic/qt_ui.py:427)) had no tooltip at all despite its sibling `valve_resource` having one for the identical "genuinely used" reason. Tracing `hardware_factory.build_hardware_bundle()` while writing this tooltip surfaced a fact not previously stated anywhere in this codebase or changelog: the Z-motor is *always* built as `PriorZMotor` + `SerialTextCommandBackend()` whenever "Z stage" is enabled -- `config.z_backend`/the UI's own Z stage backend combo is never read at all, not even to choose between Prior-serial and Thorlabs/APT. Selecting `"thorlabs_apt"` in that (already-disabled) combo has always had zero effect on which backend is actually built, a stronger claim than the existing "Not wired to a real backend" stub tooltip on that combo makes. Both facts are now in `prior_resource`'s tooltip.
- **`flush_flowrate`** (manual Pump&Valve tab, [qt_ui.py:519](src/thermo_acoustic/qt_ui.py:519)) had no tooltip and no unit in its row label (`"Flush Flowrate"`), unlike its Experiment-tab twin `exp_flush_flowrate` (`"Flush Flowrate(uL)"`). Grounded in the exact uL/min fact `FlushSettings.timeout_s`'s own docstring already establishes (Session 31/32): added a tooltip citing it, and brought the row label in line with its twin's unit suffix.
- **`conversion_method`/`conversion_shifts`/`conversion_min`/`conversion_max`** ([qt_ui.py:560](src/thermo_acoustic/qt_ui.py:560)) had no tooltips at all -- traced `ImagePreviewWindow`'s own three display methods (`_display_full_dynamic`/`_display_90_percent_dynamic`/`_display_downshift`) directly to ground exactly what each conversion mode does (linear min/max stretch; middle-90th-percentile stretch; right-bit-shift-and-clip) and that it's preview-display-only, not applied to the saved TIFF data. `conversion_min`/`conversion_max` (read-only) now note they're an *output* of the last Adjust, not an input.
- **`sequence_frames`** ([qt_ui.py:603](src/thermo_acoustic/qt_ui.py:603)) sits directly among the six Sequence-cluster fields Session 22 made load-bearing for automated runs, with no visual distinction of its own -- but tracing `_build_experiment_series()` (already done this session, Category 2) confirms it is the one field in that group *not* carried through (always overridden by the Experiment tab's own Frames count). New tooltip states this explicitly, grounded in that trace, rather than leaving it to look like the other six.
- **`exp_sweep_time_ms`** and its manual-WFG-tab twin `sweep_time_ms` ([qt_ui.py:693](src/thermo_acoustic/qt_ui.py:693), [qt_ui.py:876](src/thermo_acoustic/qt_ui.py:876)) had no tooltip despite every other FM Sweep field having one -- grounded in `FmSweepSettings.fm_frequency_hz`'s real formula (`ad2.py:136`, `1000.0 / self.sweep_time_ms`), stating the field's actual physical meaning (FM node modulation rate) instead of leaving it as a bare "Sweep Time (ms)" label.

**Test:** `test_category_6_grounded_tooltips_added_this_session` ([tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)) spot-checks the grounded content of all five, plus the `flush_flowrate` label fix.

**Files touched this category:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (1 new test).

**Verification:** tested (199 passing, up from 198 -- 1 new test, all pre-existing tests pass unmodified). Not hardware-verified -- tooltip/label text and one row-label unit suffix only; no widget's read value, signal wiring, or downstream config-building logic changed.

**Category 7 -- v1/v2 Parity.** Enumerated every widget referenced by `qt_ui.py`'s `_experiment_tab()` and everything it calls (`_ad_settings_group()`, `_add_experiment_channel_sections()`, `_experiment_settings_column()`, `_experiment_numbers_group()`, `_experiment_flush_group()`, `_camera_start_group()`, `_experiment_frequency_scan_group()`), then cross-checked each against `qt_ui_v2.py`'s own separately-built `_center_experiment_area()` and everything *it* calls -- not assuming v2 inherits coverage just because some widgets are shared, per this category's own instruction. Elapsed Time/Time Left, series path/Start button, Camera FPS/Start, all CH0/CH1 Carrier+Trigger+Symmetry/Phase/Repeat Trigger fields, Repeats/Frames/Exposure/GlobalExposure, Flush settings, and Camera Start Array(s)/Dynamic Camera Start Time were all confirmed present in v2 (several already fixed by name in Sessions 24/25 for exactly this reason).

**Confirmed and fixed -- two real, fully-wired Experiment-tab features had zero reachable control anywhere in `qt_ui_v2.py`:**
- **FM Sweep** ([qt_ui.py:1699](src/thermo_acoustic/qt_ui.py:1699)'s CH0 inline section) -- a known gap, flagged as far back as Session 25 ("FM Sweep is also absent from `qt_ui_v2.py`'s main experiment area... noted for context, not fixed") and reiterated in Session 38, but never actually fixed in any of the 13 intervening sessions.
- **Frequency Scanning** ([qt_ui.py:1798](src/thermo_acoustic/qt_ui.py:1798), `_experiment_frequency_scan_group()`) -- added in Session 34, *after* `qt_ui_v2.py`'s AD2 Output Parameters table was last touched (Session 25 follow-up); its absence from v2 was never flagged by any session, including Session 34 itself.

**Fix.** `_experiment_frequency_scan_group()` is already a standalone, self-contained `QGroupBox` builder with no external layout dependencies (same pattern already proven for `_experiment_flush_group()`, reused by v2 since the feature was first added) -- `qt_ui_v2.py`'s `_center_experiment_area()` now calls it directly, no new code needed beyond the call site. FM Sweep had no equivalent standalone builder to reuse (its `qt_ui.py` form lives inline inside `_add_experiment_channel_sections()`, a method v2 never calls at all) -- **v1's existing, tested inline section was left completely untouched** (no refactor, no risk to its layout) and a new, independent `_experiment_fm_sweep_group()` ([qt_ui.py:1809](src/thermo_acoustic/qt_ui.py:1809)) was added instead, binding the *exact same* `self.exp_sweep_*` widget instances (not copies, not new state -- confirmed by identity assertion in the new test below) into its own `QGroupBox`, with its own independent call to `_connect_sweep_dual_mode_refresh()` (v1's own call, inside the method v2 never reaches, would never have wired these signals for a v2 instance otherwise). Both new groups added as a new row in `_center_experiment_area()`'s grid ([qt_ui_v2.py:191](src/thermo_acoustic/qt_ui_v2.py:191)); re-measured offscreen at both 1440x860 and 980x680 -- no squeeze or truncation introduced.
- **Test:** `test_v2_experiment_area_exposes_fm_sweep_and_frequency_scanning` ([tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py)) confirms both new groups bind the identical widget instances `qt_ui.py`'s own Experiment tab uses, and that a value set through v2's new FM Sweep group (Start/Stop Frequency) reaches the real `_build_experiment_series()` output exactly as it would from `qt_ui.py` -- `config.channels[0].carrier.frequency_hz == 1_050_000.0` for Start=1000/Stop=1100 kHz.

**Files touched this category:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py) (1 new test).

**Verification:** tested (200 passing, up from 199 -- 1 new test, all pre-existing tests -- including both group-box layout-squeeze regression guards, re-run against the new groups -- pass unmodified). Not hardware-verified -- this exposes existing, already-implemented functionality through a new UI surface; the underlying FM Sweep/Frequency Scanning hardware-writing logic itself is completely unchanged (same caveats as Sessions 16/34/35/38: no real AD2 run has confirmed either feature's actual output).

**Category 8 -- Internal Naming Leakage.** Grepped both files for underscore-containing (`snake_case`) text inside every `addRow(...)`/`QLabel(...)`/`setWindowTitle(...)` string literal (zero hits -- no internal Python identifier has ever leaked into a row label or window title), then separately reviewed every `QPushButton(...)` literal and every window title for anything reading like a smashed-together identifier rather than a real label, and grepped for literal `TODO`/`FIXME`/`HACK`/`XXX`/`DEBUG` inside any string literal (zero hits).

**Confirmed and fixed:** `qt_ui_v2.py`'s sidebar loop (`_left_navigation()`, [qt_ui_v2.py:189](src/thermo_acoustic/qt_ui_v2.py:189)) renders `_MANUAL_PANEL_BUILDERS`' own dict keys verbatim as both the button text and the manual-panel dialog's window title. Three of the four keys ("WFG", "MSO", "Camera") are already correct, real display text -- but the fourth, `"PumpValve"` (smashed together with no separator, since it also has to work as a Python dict key/identifier), rendered on the sidebar button and in the dialog title (`"PumpValve (Manual Test)"`) exactly as the raw key, the only one of the four that reads like an internal identifier rather than a label. **Fix:** new `_PANEL_DISPLAY_NAMES`/`_panel_display_name()` ([qt_ui_v2.py:135](src/thermo_acoustic/qt_ui_v2.py:135)) map `"PumpValve"` to `"Pump&Valve"` -- matching `qt_ui.py`'s own tab bar name for the identical feature exactly (`self.tabs.addTab(self._pump_tab(), "Pump&Valve")`), not invented wording -- applied to the sidebar button text, the manual-panel dialog's window title, and (for consistency, found in the same code area while fixing this) the dead-in-production-but-still-tested `_show_placeholder()`'s status message. The internal dict key itself is untouched -- `_MANUAL_PANEL_BUILDERS`/`_manual_panels` lookups still use `"PumpValve"`, only the *displayed* text changed.
- **Test:** `test_v2_sidebar_shows_friendly_name_not_internal_panel_key` ([tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py)) confirms `"Pump&Valve"` appears as a real button's text and `"PumpValve"` does not, and that `_show_placeholder("PumpValve")` produces a status message using the friendly name. `test_v2_sidebar_buttons_open_existing_manual_test_panels`'s existing dialog-title assertion updated to go through the same `_panel_display_name()` mapping instead of asserting the raw key.

**Considered and deliberately not touched (far larger in scope, not what this category targets):** `Application`'s own status-string vocabulary (`"ExperimentComplete"`, `"ExperimentSeriesAborted"`, `"NoExperiment"`, `"ZStackAborted"`, `"EventLoopError"`, etc.) is rendered verbatim in both UIs' main status line, and several of those values *are* PascalCase words concatenated with no spaces -- superficially the same pattern as `"PumpValve"`. Unlike that one dict key, this is this application's own long-established, deeply-embedded status-code vocabulary (used consistently since before any of these 39 sessions, asserted on by name in dozens of existing tests across the whole suite, and plausibly mirroring LabVIEW's own original status/typedef string values rather than being an accidental Python-side leak). Relabeling it would be a large, high-risk, cross-cutting rewrite far outside a single-session UI audit's proportionate scope, not a confirmed naming-leakage bug of the kind this category targets -- noted here for completeness, not flagged as an open question (there is no real ambiguity about what it *is*, only about whether it would be worth eventually cleaning up, which is a product decision, not a bug).

**Files touched this category:** [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py) (1 new test, 1 existing test updated).

**Verification:** tested (201 passing, up from 200 -- 1 new test, 1 existing test updated for the new display-name mapping, all other pre-existing tests pass unmodified). Not hardware-verified -- button/dialog-title text only, no functional or hardware-facing change.

### Session 39 -- Final summary

All 8 categories complete, worked strictly in order, one at a time, with a changelog checkpoint and a full green test run after each (verified against fresh `git status`/file reads at each step, not assumed from memory). Test suite grew from **190 passing (Session 38 baseline) to 201 passing** -- 12 new tests, 4 existing tests extended/updated in place, zero tests removed, zero regressions at any checkpoint. `git diff --stat` against the Session 38 working tree: 6 files changed (`qt_ui.py`, `qt_ui_v2.py`, `tests/test_qt_ui_hardware_settings.py`, `tests/test_qt_ui_v2.py`, plus this changelog and `instruments.py`'s pre-existing uncommitted diff from before this session), ~1775 insertions / 143 deletions, no stray or untracked files left behind (`git status` clean beyond the expected modified set).

| # | Category | Outcome | Summary |
|---|---|---|---|
| 1 | Functional Correctness | **Fixed** | `sequence_exposure_ms` (Camera tab Sequence group) confirmed dead since Session 11, never actually fixed -- disabled + tooltipped, row label collision with the real `exposure_ms` field resolved. |
| 1 | Functional Correctness | **Flagged, not fixed** | Save/Load Settings persistence is incomplete for most manual-tab-only fields (WFG Trigger/FM Mod/Sweep, Pump&Valve, Camera ROI/Sequence, several later-added Experiment-tab fields) -- long-standing baseline behavior, genuine design-scope ambiguity (was full persistence ever intended?), not a per-field defect. |
| 2 | Label Accuracy | **Fixed** | `qt_ui_v2.py`'s "Experiment running" indicator used a fragile `"experiment" in status.lower()` heuristic that misreported "No" for a real window right after Abort is clicked mid-series -- now reads an explicit `_experiment_series_active` flag bracketing `_run_experiment_series()`'s real execution span. |
| 2 | Label Accuracy | Re-verified, no change | ~10 other "(overridden)"/"(overrides WFG tab)"/stub-tooltip claims re-traced against current code and confirmed still accurate. |
| 3 | Layout | **Fixed** | `qt_ui_v2.py`'s "Global Status" panel truncated nearly every value label to a fixed 34px regardless of content (WrapLongRows + word-wrap fix); `qt_ui.py`'s "Camera Start Array(s)" group collapsed at the app's own 980x680 minimum window size, invisible at the 1280x820 default the existing guard checked (QScrollArea fix, same established pattern as four prior sessions). Both gaps existed because the generic squeeze guard only ever checked v1's tabs at the default size -- test coverage extended to v2 (own window + all 4 manual dialogs) and the minimum size, both windows. |
| 4 | Stale/Dead Text | **Fixed** | "Elapsed Time"/"Time Left" in both UIs were bare `QLabel("00:00:00")` never assigned to any attribute -- 100% static for this display's entire history, never flagged in 38 prior sessions -- marked as non-functional stubs (implementing a real timer is a new feature, out of scope). |
| 4 | Stale/Dead Text | **Flagged, not fixed** | "Analog Discovery 3" row label is the only "3" anywhere in the live codebase (everywhere else says "2") -- looked like the same stray-suffix bug as "MX Valve 2" (Session 36), but `docs/PORTING_TBD.md` separately mentions real "AD2/AD3" validation hardware, making this a genuine, unresolved fork rather than a confirmed typo. |
| 5 | Multi-Convention Fields | **Fixed** | Frequency Scanning's Step Size silently overrode the real point count without ever updating what "Number of Frequencies" displayed (unlike FM Sweep's genuinely bidirectional Session 38 fix) -- added one-directional display sync (Step Size -> Count display, not the reverse, to avoid silently flipping Step Size from "0=unused" to "active") and fixed the mismatch error's field-attribution. FM Sweep's own dual-mode sync re-verified still correct. |
| 6 | Tooltip Grounding | **Fixed** | 5 previously-untooltipped, non-self-evident fields given tooltips grounded in code traced this session (`prior_resource`, `flush_flowrate` + label unit fix, `conversion_method`/`shifts`/`min`/`max`, `sequence_frames`, `exp_sweep_time_ms` + its manual-tab twin). Incidentally discovered while grounding `prior_resource`'s tooltip: the Z stage backend combo is *never* read by `build_hardware_bundle()` at all -- selecting "Thorlabs APT" there has always had zero effect on which backend is built. |
| 7 | v1/v2 Parity | **Fixed** | FM Sweep (flagged as a gap since Session 25, never fixed) and Frequency Scanning (gap never even flagged, feature added Session 34) had zero reachable control anywhere in `qt_ui_v2.py` -- both now exposed via new/reused standalone group builders binding the identical widget instances `qt_ui.py`'s Experiment tab uses, not copies. |
| 8 | Internal Naming Leakage | **Fixed** | `qt_ui_v2.py`'s sidebar rendered the internal dict key `"PumpValve"` verbatim as both button text and dialog title -- the only one of four panel names reading like an identifier rather than a label. Mapped to `"Pump&Valve"`, matching `qt_ui.py`'s own tab name for the identical feature. |
| 8 | Internal Naming Leakage | Considered, excluded | `Application`'s PascalCase status-code vocabulary (`ExperimentComplete`, etc.) is superficially similar but is this app's own long-established, deeply-embedded status system, not an accidental leak -- relabeling it is out of proportion for this pass. |

**Two items explicitly flagged for the user's decision, not guessed at:** (1) whether Save/Load Settings was ever meant to comprehensively snapshot every tab, or only hardware-connection + core experiment parameters (Category 1); (2) whether "Analog Discovery 3" is a typo for "2" or deliberately covers a second, newer AD3 unit this lab may also have (Category 4). Both are genuine forks in what the *correct* answer is, not bugs with an obvious fix -- resolving either wrongly (in either direction) risks doing real damage (silently expanding a settings-file format, or silently mislabeling real hardware), so both were left exactly as found, with the evidence for and against laid out in their respective category entries above.

**Repo state:** working tree matches this document's description exactly (re-verified via fresh `git status`/`git diff --stat` immediately before writing this summary, not from memory of earlier steps in this session). Full test suite green (201/201). No hardware exercised this session -- every fix is layout/label/tooltip/display-logic-only, or (Category 7) exposes already-hardware-caveat-carrying features through a new UI surface without touching their underlying hardware-writing code at all. Ready to commit.

### Session 40 -- Comprehensive tooltip coverage: every field, cross-parameter dependencies, and a visible tooltip marker

**Superseded by Session 41 in the current working tree.** This section is
kept as a historical account of the Session 40 pass. Current code/tests no
longer match the exact implementation/counts described here: Session 41
replaced the style-based marker with an icon-wrapper marker and narrowed
tooltip coverage to the subset judged non-obvious or safety-relevant.

Explicit revision of Session 39's Category 6 pass, which the user judged far too shallow (5 tooltips added, treating most fields as "self-evident"). This session re-scoped to three explicit requirements and worked them in order: (A) tooltip *every* control, not just ones judged non-obvious; (B) make cross-parameter dependencies visible in the tooltip text itself, not just describe each field in isolation; (C) add a visible marker so a tooltip's existence is discoverable without hovering.

**Enumeration first, per the requested method.** Live `findChildren()` sweep (offscreen, against real `qt_ui.MainWindow()`/`qt_ui_v2.MainWindowV2()` instances, not a static grep) over every `QDoubleSpinBox`/`QSpinBox`/`QComboBox`/`QCheckBox`/`QLineEdit` -- internal spin-box/combo text-editor children excluded (Qt gives every `QAbstractSpinBox` its own internal `QLineEdit`, which is not a separate control; an early version of the sweep script over-counted by ~100 before this was caught). Result, reported to the user before any code was written: **172 real value-bearing widgets** in `qt_ui.MainWindow`, of which **81 had no tooltip at all** (Initialization 9, WFG 25, MSO 5, Pump&Valve 1, Camera 4, Experiment 33, plus 4 status/path fields), and **2 tooltips existed but never reached `qt_ui_v2.py` users** (`valve_resource`/`cetoni_config_path`, set inside `_instrument_group()`, a v1-tab-only method `qt_ui_v2.py`'s `InitializationDialog` never calls -- the same class of "tooltip that only works for one of the two UIs" gap this session's own broader sweep was specifically designed to catch). Cross-referencing `_experiment_do_clock_config()`, `Application.flush()`/`FlushSettings.timeout_s`, `_check_camera_timing_budget()`, `hardware_factory.build_hardware_bundle()`, and `_set_mso_stats()` alongside the 7 dependencies named in the task surfaced **15 total cross-parameter dependency relationships** (the 7 given, plus 8 more: Repeats↔Frequency-Scanning-count, Repeats↔Camera-Start-Array-length, Exposure-Time↔Camera-FPS bidirectionally, Flush-Volume↔Syringe/Custom-Volume, Flush-Flowrate↔Flush-Volume, Sample-Count↔Sample-Frequency, Range↔Offset, Enable↔Simulate pairing for all 4 instruments, Sequence-Mode↔Interval/Burst, Trigger-Source↔Polarity/Delay).

**Requirement A -- every gap filled, grounded in code traced this session (not invented).** All 81 missing tooltips written; the 2 misplaced ones relocated into `_build_state()` (the pattern every other tooltip already follows, guaranteeing it applies regardless of which UI's layout method runs) rather than left in `_instrument_group()`. Every WFG-tab and Experiment-tab Carrier field (Frequency/Amplitude/Offset/Function/Enable/channel index) that Session 39 had judged "self-evident enough to skip" now has its own tooltip -- per the user's explicit instruction to be broad, not conservative, about what counts as obvious to an outside operator. A genuinely new fact surfaced while grounding `prior_resource`'s tooltip: tracing `hardware_factory.build_hardware_bundle()` confirmed the Z stage backend combo (`z_backend`) is *never read at all* -- enabling "Z stage" always builds a Prior-serial backend regardless of whether the combo shows `"prior_serial"` or `"thorlabs_apt"`, a stronger claim than the pre-existing "Not wired to a real backend" stub tooltip made. Folded into `prior_resource`'s tooltip and the new open-items entry below.

**Requirement B -- dependency relationships woven directly into tooltip text, both sides.** Rather than a separate annotation mechanism, each dependency's two (or more) fields were written to name each other explicitly and state the relationship -- e.g. `exp_camera_fps`'s tooltip states both "combines with Frames below: the DO clock's run duration = Frames / this value" and the exposure-timing-budget relationship with `exp_exposure_ms`, while `exp_exposure_ms`'s own tooltip states the same relationship back. `exp_repeats` now states both hard constraints tying it to other fields (Frequency Scanning's count must match; Camera Start Array's 10-slot ceiling when Dynamic Camera Start Time is checked) rather than describing "number of repeats" in isolation. `flush_flowrate`/`flush_volume` (and their Experiment-tab twins) now state the real `FlushSettings.timeout_s` formula connecting them, not just "this affects a timeout" vaguely. Roughly 33 tooltip strings carry explicit cross-reference language across the ~50 fields the 15 relationships touch (some strings are shared across multiple widgets, e.g. the Enable/Simulate pairing templates, so the field count exceeds the string count).

**Requirement C -- a visible marker, chosen to avoid breaking the dozens of tests that assert exact row-label text.** Considered appending a literal glyph (e.g. `" ⓘ"`) to row-label strings, but rejected it: many existing tests assert exact label text (e.g. `"Capture mode (unused)"`), and a text-based marker would have broken every one of them for no functional reason. Instead: a new `MainWindow._TOOLTIP_MARK_STYLE = "text-decoration: underline; color: palette(link);"` applied via a new `_mark_tooltip_widget()`/`_mark_tooltip_pair()`/`_mark_tooltip_rows()` helper family ([qt_ui.py:1395](src/thermo_acoustic/qt_ui.py:1395)) -- a *style-only* change (label text itself never changes, so every existing text assertion stays valid) that mirrors the tooltip onto the row's own label widget (not just the field) so hovering either shows the explanation, both styled to look hoverable. `_mark_tooltip_rows(form)` is a generic, no-hardcoded-list sweep over a `QFormLayout`'s own rows (handles both the common `(label, field)` shape and single-widget spanning rows like `form.addRow(checkbox)`), called once at the end of every group-builder method that constructs one (26 call sites across both files); the handful of raw `QGridLayout`/`QHBoxLayout` label+field pairs outside any `QFormLayout` (e.g. the ROI group's ExposureTime(ms) row, the WFG tab's header controls, `qt_ui_v2.py`'s Acquisition Parameters grid) were marked individually via `_mark_tooltip_pair()`/`_mark_tooltip_widget()`. Confirmed empirically offscreen that Qt's stylesheet engine does not support the CSS `text-decoration-style: dotted` variant (renders as a solid underline regardless) -- reported honestly rather than claimed as literally dotted.
- **Note on Camera Start Array(s):** the 10 per-repeat slots have no adjacent label in either UI (bare `QFormLayout.addRow(widget)`/grid rows) -- each slot's own tooltip is set directly per Requirement A, and the marker is applied to the field widget itself since there is no separate label to decorate.

**Completeness test.** `test_every_value_widget_has_a_tooltip_and_visible_marker` ([tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)) and `test_v2_every_value_widget_has_a_tooltip_and_visible_marker` ([tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py)) -- same generic `findChildren()` method as the wheel-guard completeness sweep (Session 28/29/33), run as two independent live instances per this project's own established discipline ("never assume v2 inherits v1's coverage just because widgets are shared"); v2's version additionally opens the Initialization dialog and all four manual panels to confirm the reuse genuinely carries tooltips/markers through, not just structurally.

**Final counts (before -> after, this session):**
- Widgets with a tooltip at all: **91/172 (53%) -> 172/172 (100%)** in `qt_ui.MainWindow`; **~90/173 -> 173/173 (100%)** in `qt_ui_v2.MainWindowV2` (including the Initialization dialog and all 4 manual panels).
- Widgets with the visible marker: **0 -> 172/172 (100%)** and **0 -> 173/173 (100%)** respectively (the marker mechanism itself is new this session).
- Of the 172 total, roughly **50 fields carry explicit cross-parameter dependency language** (Requirement B, 15 relationships) and the remaining **~122 carry purely explanatory text** (Requirement A) -- these categories overlap in practice (a field can have both an explanation and a dependency clause in the same tooltip string) rather than being cleanly partitioned.
- Tests: **203 passing, up from 201** -- 2 new completeness tests, all pre-existing tests pass unmodified (zero row-label text changed anywhere, confirmed by the fact that no existing exact-label-text assertion needed updating).

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py), [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py) (1 new test), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py) (1 new test).

**Verification:** tested (203 passing). Not hardware-verified -- tooltip text, label styling, and one tooltip relocation (`_instrument_group()` -> `_build_state()`) only; no widget's read value, signal wiring, or downstream config-building logic changed. The one behavior-adjacent change (Frequency Scanning's `_experiment_frequency_scan_group()`/`_connect_frequency_scan_count_display_refresh()`, already live since Session 39) is untouched by this session.

**Environment note, not a code issue (same category as Session 27's pytest `tmp_path` note):** repeatedly re-running `tests/test_qt_ui_v2.py` alone (10-20x in a loop, to stress-test the new completeness tests) intermittently hit `SystemError: <class 'PySide6.QtWidgets.QLineEdit'> returned NULL without setting an exception` during `MainWindowV2.__init__()` -> `_build_state()`, always at the same line (`self.series_path = QLineEdit(...)`, roughly 30-40 widget constructions into that method). Confirmed this is **not caused by this session's changes**: the identical crash, at the identical line, was reproduced in `test_v2_global_status_panel_does_not_truncate_value_labels` -- an unmodified Session-39 test this session never touched. This is a PySide6/shiboken-level binding flakiness from constructing many `MainWindow`/`MainWindowV2` instances (172+ widgets each) in one process, not a logic bug reachable by adjusting tooltip/label content -- observed at roughly a 1-in-8 to 1-in-15 rate when hammering this one file repeatedly, never observed in the many full-suite runs performed throughout this session (which interleave other test files and so construct fewer consecutive windows per unit time). Reported here for the record; not fixed (out of scope -- an environment/binding characteristic, not application code).

### Session 41 -- Correcting Session 40's overshoot: narrower tooltip coverage, icon-based marker

Explicit two-part correction of Session 40, requested by the user after
reviewing that session's result: Session 40 tooltipped and marked *all*
172 fields uniformly, but the actual requirement was always "necessary
ones only" (fields an outsider can't understand from the label alone), not
blanket coverage. This session did not touch any tooltip *text* Session 40
wrote (verified/grounded, left alone) -- only (a) how many fields carry a
tooltip+marker at all, and (b) what the marker looks like and how it
triggers.

**Part 1 -- re-classified all 172 fields, reported the split before
implementing.** Live `findChildren()` sweep (same method as Session 40's
own enumeration) confirms the final counts precisely: **127 kept, 45
removed** in `qt_ui.MainWindow` (v2 reuses the same underlying widget
instances via its manual-panel dialogs, so the same split applies there).
The 45 removed (tooltip and marker both taken off, label/widget itself
untouched) are the WFG tab's per-channel Carrier cluster on both channels
(`idx`, `frequency`, `amplitude`, `offset`, `function`, `enable`,
`sec_run`, `repeat`) and FM Mod cluster (`fm_frequency`, `fm_amplitude`,
`fm_offset`, `fm_function` -- `fm_symmetry`/`fm_phase` were judged
non-obvious and kept), plus `mso_ch1_enabled`/`mso_ch2_enabled`/`mso_offset`,
`flush_count`, `roi_h_offset`/`roi_h_size`, `image_continuous`,
`conversion_min`/`conversion_max`, `sequence_path`, the top-bar `status`
readout, `error_source`, `exp_flush_enabled`, and the Experiment tab's
per-channel `amplitude`/`offset`/`function`/`repeat` (both channels --
`frequency`/`enable`/`run` were judged non-obvious on the Experiment tab
specifically, see below, and kept). Kept fields are the ones actually
tied to non-obvious semantics, hidden behavior, unverified/stub status, or
one of Session 40's 15 cross-parameter dependencies -- e.g. Custom Volume,
WaitAfterFlush, Step Size's override behavior, DCAM Trigger Source's
unverified status, the Z-stage backend dead-control finding, the
DO-clock/Camera-FPS relationship.

Three fields were reconsidered mid-pass after actually reading their
tooltip content, rather than removed by blanket category as first
planned: `series_path` (states data-overwrite-protection behavior, not
obvious from the label), and the Experiment tab's (not WFG tab's)
`exp_ch1_freq`/`exp_ch2_freq` (states the Frequency-Scanning/Sweep
override relationship), `exp_ch1_enable`/`exp_ch2_enable` (states the
both-disabled-means-WFG-never-starts dependency), and
`exp_ch1_run`/`exp_ch2_run` (states a raises-if-zero validation gotcha the
WFG tab's plain `sec_run` field doesn't have) -- these look identical to
already-removed self-evident siblings by label alone, but their specific
tooltip text carries a real dependency or gotcha the label doesn't, so
they stayed. This is the intended judgment calibration: closer to an
experienced instrument operator's baseline than Session 39's original
5-field list, without repeating Session 40's "everything" overshoot.

**Part 2 -- replaced the label-underline marker with a separate click-triggered
icon widget.** Session 40's marker was a stylesheet change
(`text-decoration: underline; color: palette(link);`) applied to the row's
own label widget. Removed entirely, along with its
`_mark_tooltip_widget()`/`_mark_tooltip_pair()`/`_mark_tooltip_rows()`
helper family. Replaced with a small "ⓘ" `_TooltipIconButton` (an
18x18px `QToolButton`) placed in a `_TooltipIconWrapper` container next to
the field -- never touching the label's own text or style, so no test
asserting exact label text needed to change. `MainWindow._add_tooltip_icons(form)`
walks a `QFormLayout`'s rows generically (same no-hardcoded-list method
Session 40 used) and swaps a row's field widget for `[field, icon]` via
`QFormLayout.setWidget()` wherever the field already carries a tooltip;
`_wrap_with_tooltip_icon()` is the same building block, called directly at
the handful of raw grid/hbox call sites outside any `QFormLayout` (the ROI
group's ExposureTime(ms)/Center ROI cells, the WFG tab's header controls,
`series_path`, and `qt_ui_v2.py`'s Acquisition Parameters grid and
Enable/Simulate pairs). `qt_ui_v2.py`'s dense AD2 Output Parameters table
(`_v2_ad2_output_group()`, Session 24/25) deliberately got **no** icons at
all: its cells are the *same shared widget instances* the Experiment tab's
own labeled rows use, and wrapping either a header or a data cell there
would change what `grid.itemAtPosition(row, col).widget()` returns,
breaking that table's own pre-existing identity tests -- the explanation
stays reachable via the icon on the Experiment tab's own row for the same
field.

**Trigger mechanism: click, not hover -- confirmed with the user, not
assumed.** The task flagged this as genuinely ambiguous ("点了才出现" could
mean either) and asked before implementing; the user answered **Click**
via the tool's own confirmation prompt. Implemented literally: no native
`.setToolTip()` is set on the icon button itself (hovering it alone shows
nothing), and its `clicked` signal calls `QToolTip.showText(pos, text,
self)` manually, reusing Qt's own tooltip rendering (auto-wrap, native
look, dismisses when the mouse leaves) rather than a bespoke popup widget.

**Tooltip text auto-wrap confirmed, not just assumed.** `QToolTip.showText()`
wraps Qt's standard tooltip rendering, which auto-wraps long text at a
reasonable pixel width by default; the multi-line strings Session 40 wrote
were left exactly as-is (this session did not touch tooltip text) and
render as multiple wrapped lines under this new click-triggered display,
not one unbroken line.

**A real Qt layout bug found and fixed while wiring the icon marker in.**
`QFormLayout.addLayout()`/`QLayout.addLayout()`, called on a *still-detached*
(parentless) `QFormLayout` whose row field was already replaced via
`setWidget()`, silently "unwraps" that replacement -- it reparents the
inner field widget directly onto the new parent and discards the wrapper
container, with no error. Confirmed via an isolated repro (build a
`QFormLayout()`, replace a row via `setWidget()`, then call
`someLayout.addLayout(form)` -- the wrapper's child widget's `.parent()`
silently changes from the wrapper to the new parent). This does **not**
happen when the `QFormLayout` already has a parent widget from
construction (`QFormLayout(some_widget)`, the pattern used almost
everywhere else in this file) -- only for the ~11 `QFormLayout()` sites in
`qt_ui.py` that get attached to an outer layout via `addLayout()` after
being built (`_wfg_channel_group()`'s `form`/`trigger`/`fm`/`sweep`,
`_roi_group()`, `_conversion_group()`, `_sequence_group()`'s `settings`,
`_ad_settings_group()`'s `top`, and `_add_experiment_channel_sections()`'s
`carrier`/`trigger`/`sweep`). Fixed by reordering each site so
`_add_tooltip_icons(form)` runs *after* the corresponding
`layout.addLayout(form)` call, not before.

**Completeness tests rewritten for the narrower coverage and the new
marker.** `test_every_value_widget_has_a_tooltip_and_visible_marker`
([tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py))
now checks coherence generically instead of asserting every widget has a
tooltip: every tooltipped widget must have the icon marker
(`isinstance(widget.parentWidget(), qt_ui._TooltipIconWrapper)`), every
non-tooltipped widget must *not* have one either (confirming the
narrowing actually removed the marker, not just the tooltip text), and the
overall split is pinned at `kept == 127` since that split was a reviewed
judgment call worth protecting from silent drift. `test_v2_...`'s
equivalent ([tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py)) was still
checking for Session 40's old `"text-decoration"` stylesheet string and
still asserting every widget must have a tooltip -- both stale after this
session's changes, both rewritten to the same coherence pattern (with an
explicit, commented exclusion for the AD2 table's 24 shared field widgets,
matching the production-code rationale above).

**Test-suite flakiness found and mitigated, confirmed environment-specific
(not a production issue).** Extending tooltip coverage to 127 fields adds
a wrapper `QWidget` + `QToolButton` next to each one (~250 extra native
widgets per built `MainWindow`, ~800 to ~1050). Running the full test
suite intermittently hit `SystemError: <class 'PySide6.QtWidgets.Xxx'>
returned NULL without setting an exception` from inside PySide6/Shiboken,
for an essentially random widget class each time. Investigated properly
rather than guessed at: bisected out cumulative test-session leakage as
the cause (a single, first-ever `MainWindow()` build in a fresh process
fails too, ~30-40% of the time) and confirmed it does not reproduce at all
under the real "windows" Qt platform (5/5 clean) -- only under the
`QT_QPA_PLATFORM=offscreen` backend this whole test suite forces, meaning
production use of the actual app is not affected by this at all, only
this test suite's offscreen rendering. A second construction attempt
reliably succeeds. Added `tests/conftest.py` (new, previously untracked --
now part of this session's change set): a `build_with_retry()` helper
wrapping every `MainWindow()`/`MainWindowV2()`/manual-panel-dialog
construction call site in both test files with up to 8 retries, plus an
autouse fixture that forces each test's top-level widgets through
`deleteLater()` + a manual `QEvent.DeferredDelete` replay (plain
`processEvents()` alone did not drain that queue for a widget tree this
size, confirmed empirically) so they don't accumulate across the run.
Residual flakiness after this mitigation: 0 failures in the large majority
of full-suite runs performed while verifying this session's work, with an
occasional single, different-test-each-time failure in roughly 1 in 4-5
runs of the complete `tests/` suite (205 tests) -- consistent with
genuine, low-probability native instability in this specific offscreen-Qt/
Shiboken combination under heavy widget churn (occasionally severe enough
that even 8 retries in a row all fail), not a logic bug in this session's
code. Not chased further: full process isolation per test (e.g.
`pytest-forked`) would likely close this remaining gap but is a
test-infrastructure change beyond this session's scope; flagged here for
visibility rather than silently worked around.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py),
[qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py),
[tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py),
[tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py), new
[tests/conftest.py](tests/conftest.py).

**Verification:** full `tests/` suite green (205/205) across the large
majority of repeated runs during verification, modulo the documented
residual offscreen-platform flakiness above. Not hardware-verified --
tooltip coverage, marker mechanism, and test infrastructure only; no
widget's read value, signal wiring, or downstream config-building logic
changed.

### Session 42 -- Pump&Valve layout width fix; qt_ui_v2 tooltip-marker tests re-verified against the current mechanism

**Audit-trail note, written deliberately, not for polish: this entry did
not exist when the session it describes was worked.** A separate handoff
check (a fresh read of this changelog cross-checked against live
`git status`/`git log`) caught that this session's work had landed in the
working tree with no corresponding changelog entry -- a real process gap,
not a stylistic one. This entry was reconstructed afterward, from the
diff and the session's own tool-call history, at the point the gap was
caught. It is being logged now, after the fact, with that fact stated
plainly here rather than backdated or folded silently into Session 41's
entry to look as if it had been written at the time. Future audits of
this log should treat this paragraph as authoritative on that point.

**Task 1 -- qt_ui_v2 tooltip-marker tests: verified already current, no
edit needed.** Re-checked `tests/test_qt_ui_v2.py`'s tooltip-coverage
helpers against the request to "make tooltip-related assertions match the
current icon-wrapper marker approach" and "do not keep tests that rely on
the old `styleSheet()`/`"text-decoration"` implementation detail." Grepped
both `tests/test_qt_ui_v2.py` and `tests/test_qt_ui_hardware_settings.py`
for `text-decoration`/`styleSheet()`: zero matches in either file.
`_has_tooltip_icon()` in `tests/test_qt_ui_v2.py` already asserts
`isinstance(widget.parentWidget(), qt_ui._TooltipIconWrapper)` -- the
current icon-wrapper mechanism, not the Session 40 stylesheet marker this
task was worried about. This was already corrected as part of Session 41's
own completeness-test rewrite (see that entry's "Completeness tests
rewritten" paragraph); no further change was needed or made.

**Task 2 -- Pump&Valve tab's oversized natural width, fixed.** Measured
`_pump_tab()` offscreen: `sizeHint` **2194x232**, `minimumSizeHint`
**1516x232** -- wider than both the app's default window width (1280px)
and its own documented minimum (980px), guaranteeing forced compression
or clipping at every normal window size.
- **First attempt, tried and reverted.** `_flush_group()` (the tab's
  fourth column's second group) was the one group in this tab missing
  `QFormLayout.RowWrapPolicy.WrapLongRows`, which its four siblings
  (Valve/Pump/Syringe/Flow Control/Flush) already use. Adding it dropped
  the tab's `minimumSizeHint` from 1516px to 1300px, but caused a genuine
  regression: `test_v2_no_group_box_is_squeezed_below_its_minimum_size_hint`
  caught "Flush Settings" squeezed to 104px against its own 120px
  `minimumSizeHint` inside the v2 PumpValve manual-panel dialog at
  1440x860 -- narrowing one column's width via row-wrapping increased that
  group's row-height needs just enough to squeeze a sibling elsewhere in
  the same reused layout. Reverted rather than accepted, per this
  project's own standing rule that a fix causing a new regression is not
  an acceptable trade.
- **Fix actually applied.** Same pattern already established in this file
  for exactly this situation (`_wfg_channel_group()`, `_sequence_group()`,
  `_ad_settings_group()`): wrapped `_pump_tab()`'s four-column content in
  its own `QScrollArea` (`setWidgetResizable(False)`, both scrollbars
  `ScrollBarAsNeeded`) instead of force-compressing it. No group's
  internal layout was touched, so this carries none of the row-height-vs-
  width-tradeoff risk the first attempt hit. Re-measured offscreen: the
  tab's own `minimumSizeHint` drops from 1516px to **88px** (just the
  scroll viewport); the full 2194x232 content is unchanged and reachable
  by scrolling instead of forced compression.
- **Remaining rough edge, left intentionally:** the tab's *natural*
  content width (2194px) itself was not reduced -- an operator on a
  narrower screen still needs to scroll horizontally to reach the
  rightmost column (Flush/Flush Settings). Reflowing the four columns
  into two rows would meaningfully shrink the natural width but is a
  broader redesign than this task's "minimal, local fix" scope called for.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py) only. No test
file needed a change (Task 1 required none; Task 2's fix is covered by
the existing generic `test_v2_no_group_box_is_squeezed_below_its_minimum_size_hint`
regression guard, which caught the reverted first attempt and passed
against the final fix -- no new test was written specifically for this
task).

**Verification:** tested -- `pytest tests/test_qt_ui_v2.py
tests/test_qt_ui_hardware_settings.py` 80/80 across 3 consecutive clean
runs; full `tests/` suite 205/205. Not hardware-verified -- layout-only,
no hardware interaction possible to verify against.

### Session 43 -- Docs-inconsistency fix (DO clock caution lists); valve-handshake hardening investigated, still uncommitted and undecided

**Mixed-status entry, deliberately not blurred together.** This session
covers two genuinely different things: (1) a docs fix that is **done**,
and (2) an investigation into pre-existing uncommitted code (the
valve-handshake hardening in `instruments.py`) that is **not** this
session's work, is **not yet accepted**, and remains exactly as
uncommitted as it was before this session started. Read the two parts
separately; neither implies the other's status.

**Part 1 -- docs-inconsistency fix, done.** A prior handoff-check pass
(commit-provenance/docs-accuracy review, same session that caught the
missing Session 42 entry) had refreshed `docs/current_workflow_audit.md`
and `docs/labview_migration_completeness_audit.md` to correct a real
stale claim (both files previously said the automated experiment path
"passes `{}`"/"empty config" into `config_do_clock_special()`, which is
false -- confirmed by reading `qt_ui.py`'s `_experiment_do_clock_config()`,
which builds a real `DoConfig` from live `exp_camera_fps`/`exp_frames`/
`exp_camera_start` values, unconditionally passed in at
`application.py:374`). That correction was accurate. But the same refresh
pass also **silently dropped "DO Clock" out of both files' caution/
restriction lists** while fixing the `{}` claim -- `current_workflow_audit.md`'s
"## Do Not Run Yet" list went from `"AD2 DO Custom / DO Clock output."` to
just `"AD2 DO Custom output."`, and `labview_migration_completeness_audit.md`'s
"Mark legacy/hide later" list went from `"DO Custom / DO Clock UI actions
unless proven required."` to just `"DO Custom UI actions unless proven
required."` -- both inconsistent with those same files' own Risk Table
rows, which still (correctly) said DO clock timing "should still be
checked against the physical setup before broad use" and remained "Fake
tested only." No file claimed oscilloscope verification outright, but the
omission functionally implied the open item was closed when it wasn't.
- **Fix:** both list entries restored verbatim (`"AD2 DO Custom / DO Clock
  output."` / `"DO Custom / DO Clock UI actions unless proven required."`),
  plus an explicit caveat paragraph added at both sites distinguishing the
  two facts that must not be conflated: DO Clock Special being
  **populated/active from real UI values** (true, and true since before
  this session -- a structural/wiring fact) versus **DIO0 (acoustic)/DIO1
  (LED) relative timing being oscilloscope-verified against the physical
  setup** (still not true -- the same open item this project has carried
  since the DO-clock derivation was first migrated, unchanged by this
  session).
- **Files touched:** [docs/current_workflow_audit.md](docs/current_workflow_audit.md),
  [docs/labview_migration_completeness_audit.md](docs/labview_migration_completeness_audit.md).

**Part 2 -- valve-handshake hardening: investigated, provenance
established, still uncommitted, still undecided.** `instruments.py`'s
`Valve.initialize()`/`_apply_status_response()` currently contain a
change not written by this session and not attributable to any prior
session in this log: `_apply_status_response()` now returns `bool`
instead of `None`, and `initialize()` raises `ValveError` when it returns
`False` (an unrecognized/unparseable status response), instead of the
previous behavior of logging `status_note` and continuing as if
connected.
- **Provenance, established via `git blame`/`git log -p --follow`, not
  assumed.** `git blame` on the added lines (the `if not
  self._apply_status_response(...): raise ValveError(...)` guard, the
  `-> bool` signature, all three `return True`/`return False` statements)
  shows every one of them as `Not Committed Yet`. `git log --oneline --all
  -- src/thermo_acoustic/instruments.py` lists exactly 6 commits that have
  ever touched this file; `git log -p --follow` through all 6 confirms
  every prior committed version of `initialize()` called
  `self._apply_status_response(raw_response)` and discarded the result --
  never a bool return, never a raise. The surrounding `status_note`-setting
  logic itself (busy/ready/confirmed/unverified) *is* committed, in
  `3474232` ("Migrate hardware safety, DO-clock/LED timing, valve
  protocol, and data-integrity fixes...", the Session 2/13 baseline) --
  only the hardening (return-bool-and-raise) is new and uncommitted, with
  no associated commit or session anywhere in this log.
- **Test coverage verified empirically, not just read.** Temporarily
  reverted the fix (removed the `if not ...: raise ValveError(...)` guard,
  restored the old discard-the-result call) and ran
  `test_valve_initialize_rejects_unparseable_status_response`: it
  **failed** (`AssertionError: expected initialize() to reject an
  unrecognized valve response`), confirming the test genuinely exercises
  the raise path rather than trivially passing regardless. Restored the
  fix immediately after; `git diff` on `instruments.py` afterward matched
  the pre-check state exactly (byte-for-byte, confirmed via `git diff`
  before and after).
- **Status: still uncommitted, still pending a decision.** This
  investigation did not change, accept, revert, or commit anything in
  `instruments.py` -- it is reported here as findings only, exactly as
  requested. Whether to keep, commit, or discard this hardening remains
  an open decision, not something this entry should be read as resolving.

**Files touched (Part 2):** none -- read-only investigation, `instruments.py`
was temporarily modified and restored during the empirical check described
above, with the restoration confirmed byte-identical to the pre-check
working-tree state.

**Verification:** Part 1 is a docs-only change (no test suite impact).
Part 2 made no lasting code change; the temporary revert-and-restore was
verified via `git diff` equality, not via a test run against a persisted
change.

### Session 44 -- FM Sweep v1/v2 parity (already resolved -- verified, not redone), Custom syringe geometry wired, Frequency Scanning persisted

Three previously-flagged open items, addressed in order 1->2->3 as
instructed, each logged separately below since they are genuinely
independent pieces of work.

**Item 1 -- FM Sweep v1/v2 parity: investigated first, found already
fixed, explicitly not redone.** The task's premise was that "v2's
Experiment tab has no FM Sweep controls at all." Read `qt_ui.py`'s FM
Sweep implementation in full before touching anything, per instruction,
and in the process found `qt_ui_v2.py:233` already calls
`self._experiment_fm_sweep_group()` (defined at `qt_ui.py:2166`) from
`_center_experiment_area()`'s grid -- a real, standalone `QGroupBox`
binding the *identical* `self.exp_sweep_*` widget instances v1's own
inline CH0 Sweep section uses, already using the Session 41 click-icon
tooltip marker (`self._add_tooltip_icons(form)`), already committed as
part of Session 39 Category 7 (`4105fa8`, predates every UI session this
conversation has done). Confirmed, not assumed: ran
`test_v2_experiment_area_exposes_fm_sweep_and_frequency_scanning`, which
passed -- it drives Start/Stop Frequency through v2's own widget
instances and asserts the resulting `config.channels[0].carrier.frequency_hz`
from the real `_build_experiment_series()` call matches the expected
midpoint, i.e. the same hardware-config-building path v1 uses, not just
matching widget names. **No code was changed for this item** -- doing so
would have duplicated already-working, already-tested functionality.
Reported to the user before proceeding, per this project's own
established discipline of verifying task premises against live code
rather than trusting a stated gap list.

**Item 2 -- Custom syringe geometry wired to a real hardware call.**
Confirmed the premise held (unlike item 1): `_configure_syringe()`
(`qt_ui.py`, pre-change) still only ever sent `{"name": syringe}`; Qmix's
real `configure_syringe()` (`qmix_backend.py:148`) needs
`inner_diameter_mm`/`max_piston_stroke_mm` or a `SYRINGE_PRESETS` name
match, and "Custom" is in neither -- selecting it and clicking Configure
Syringe genuinely still raised `QmixPumpError`, exactly as Session 38
Task 4 found and left unfixed.
- **Genuine design ambiguity found and flagged, per instruction, rather
  than guessed at.** Custom Volume (`custom_syringe_volume_ml`, mL) is
  the only Custom-related field in the UI, but `configure_syringe()`
  needs two *different* physical dimensions (inner diameter, stroke
  length) that volume alone cannot determine -- an infinite family of
  diameter/stroke pairs share the same total volume. Stopped and asked
  the user via the tool's own confirmation prompt which parameterization
  to expose: (a) two new explicit fields (Inner Diameter mm + Max Piston
  Stroke mm), matching `configure_syringe()`'s real API literally with no
  derivation/assumption, or (b) one new field (Inner Diameter mm) with
  stroke derived from Custom Volume via the same formula the three BD
  presets already use (which Session 17 already flagged as an unconfirmed
  assumption even for BD's own known hardware). **The user chose (a).**
- **Implemented.** Two new fields, `custom_syringe_inner_diameter_mm`/
  `custom_syringe_stroke_mm` (`qt_ui.py`, next to `custom_syringe_volume_ml`
  in `_build_state()` and the Syringe group in `_pump_tab()`), enabled/
  disabled together with Custom Volume via the same
  `_update_custom_syringe_volume_enabled()` toggle (extended, not
  duplicated). `_start_configure_syringe()` now reads the syringe name and
  -- only when it's "Custom" -- both new field values on the main/UI
  thread (before handing off to `_run_action()`'s background `QThread`,
  matching every other widget-value-capture site in this file), and
  `_configure_syringe()` now takes the whole `config` dict instead of a
  bare `syringe: str`, sending `inner_diameter_mm`/`max_piston_stroke_mm`
  for Custom and unchanged `{"name": syringe}` for the three named
  presets -- confirmed via a new test that BD presets still send nothing
  extra (preset lookup in `configure_syringe()` untouched) while Custom
  sends the exact real field values, and that Custom Volume itself is
  never read by this call (stays flush-safety-check-only, per the chosen
  option). Tooltips on `self.syringe`/`custom_syringe_volume_ml` updated
  (previously said Configure Syringe "will fail" for Custom -- no longer
  true); the two new fields' own tooltips explain they are real,
  independent SDK parameters, not derived from Custom Volume.
- **Test:** `test_configure_syringe_sends_real_geometry_for_custom_not_presets`
  (new) drives `_start_configure_syringe()` against a fake pump and
  asserts the exact `configure_syringe()` call for both a BD preset and
  Custom. `test_custom_syringe_volume_disabled_unless_syringe_is_custom`
  extended to cover the two new fields' enable/disable toggling alongside
  Custom Volume's existing coverage.
- **Completeness-test count updated, not silently.**
  `test_every_value_widget_has_a_tooltip_and_visible_marker`'s pinned
  `kept == 127` (Session 41) bumped to `kept == 129` -- the two new fields
  are genuinely non-obvious (real SDK geometry parameters with no
  UI-visible relationship to Custom Volume), so both got tooltips per the
  same Session 41 classification criteria, not added blanket.

**Item 3 -- Frequency Scanning's fields now persisted in settings.json.**
Confirmed the premise held: `_settings_dict()`/`_load_settings()`
(pre-change) had no `freq_scan_*` keys anywhere, exactly matching Session
34's own explicit, flagged scope decision to leave this unpersisted and
Session 39's restatement of the same gap.
- **No schema-version bump needed, and none added.** These are purely
  new, additive keys under the existing `"experiment"` dict every other
  Experiment-tab field already lives in -- the tolerant `if key in data`
  pattern already used throughout `_load_settings()` means an old file
  without them simply leaves the fields at their `_build_state()`
  construction defaults, no migration required. This matches how
  Symmetry/Phase/Repeat Trigger were added in Session 22 without touching
  `schema_version` -- confirmed by checking that the version-2 bump
  (Session 29/30) was specifically for the Hz->kHz *meaning* change of an
  *existing* key, not for adding new ones, so the same reasoning applies
  here.
- **`freq_scan_enable` added alongside the four named fields (Start/
  Stop/Number of Frequencies/Step Size), not silently, flagged here for
  visibility.** The task named exactly four fields; a fifth,
  `exp_freq_scan_enable` (the feature's on/off toggle), was added too so
  the persisted Start/Stop/Count/Step values don't sit unused behind a
  toggle that silently resets to off every restart -- matching the
  established convention that every other toggle+values group in this
  dict persists both together (`wfg` `enable`, `mso` `ch1_enabled`,
  `experiment` `ch1_enable`). Not treated as a design ambiguity requiring
  a stop (low-stakes, easily reversible, consistent with precedent) but
  called out explicitly rather than folded in silently.
- **Test:** `test_qt_ui_save_and_restore_frequency_scanning_settings`
  (new) confirms all five fields round-trip through a real save/load
  cycle (Step Size deliberately left at 0/"not used" in the setup, so the
  test exercises persistence rather than the already-covered Step-Size-
  overrides-Count precedence logic from Session 35/39).
  `test_qt_ui_load_settings_without_frequency_scanning_keys_loads_without_error`
  (new) confirms a legacy-style file with no `freq_scan_*` keys at all
  loads without error, leaving every Frequency Scanning field at its
  construction default.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py),
[tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py).
No files touched for Item 1 (verified already correct, nothing to fix).

**Verification:** tested -- full `tests/` suite green (208/208) across
2 of 3 consecutive runs during verification, with 1 run hitting a single
instance of the same already-documented (Session 41/42) offscreen-Qt
flakiness in an unrelated test
(`test_v2_no_group_box_is_squeezed_below_its_minimum_size_hint`), not
this session's code. Not hardware-verified -- Custom syringe geometry
values now genuinely reach `QmixPumpBackend.configure_syringe()`'s real
`set_syringe_param()` call when a real (non-simulated) pump backend is
attached, but no real Qmix pump was exercised with a real Custom syringe
in this session; Frequency Scanning's persistence is settings-file-only
and does not touch the hardware-writing per-repeat substitution logic
already in place since Session 34.

### Session 45 -- New hardware, Phase 1: objective Z-piezo controller standalone verification (real model correction found)

**New feature integration, not an audit/fix pass -- explicitly
commissioned, per the user's own framing.** Phase 1 only: standalone
hardware verification via a probe script
([hardware_tests/test_bpc_piezo_probe.py](hardware_tests/test_bpc_piezo_probe.py)),
following this project's established pattern
(`hardware_tests/test_valve_command_probe_v2.py`). **`qt_ui.py`/
`qt_ui_v2.py` were not touched at all this session** -- integration into
the app itself is explicitly a later phase, not started.

**Environment setup.** `pythonnet` 3.1.0 installed into the `exp_ctrl`
conda environment (not previously present). Kinesis confirmed installed
at `C:\Program Files\Thorlabs\Kinesis`.

**Major finding: the connected device is not a BPC301/BPC303 at all.**
The task's own starting assumption (Benchtop Piezo Controller, BPC301
single-channel or BPC303 3-channel) turned out to be wrong, inherited
from old project history -- this project has referred to this device as
a generic "APT Piezo Controller" (pylablib's own non-model-specific
label) since a much earlier session, and that label was never
previously cross-checked against Thorlabs' actual model-specific classes.
`BenchtopPiezo.Connect("44533854")`
(`Thorlabs.MotionControl.Benchtop.PiezoCLI.dll`, the class matching
Thorlabs' own official GitHub example at
`Thorlabs/Motion_Control_Examples/Python/Kinesis/Benchtop/BPCXXX/BPC3XX_pythonnet.py`)
consistently raised `DeviceNotReadyException: Device is not connected`
on every attempt -- reproduced identically via raw PowerShell .NET
reflection (bypassing Python/pythonnet entirely), with and without an
explicit `DeviceManagerCLI.Initialize()` call, and through the actual
probe script via pythonnet.
- **Three hypotheses investigated and cleanly ruled out first, each with
  real evidence, not assumed:**
  1. **Device exclusivity** (Kinesis GUI holding the connection). Ruled
     out: user confirmed Kinesis GUI was fully closed (not just
     disconnected) before a retry, which failed identically.
  2. **Missing elevation.** Not reached as a live test (UAC prompts
     require interactive consent this automation shell can't provide),
     but superseded by the finding below before it became necessary.
  3. **Channel-selection-before-`Connect()`, sourced from a real NI
     Knowledge Base article** (`kA00Z0000019RKySAM`, "Control a
     Thorlabs BPC303 Using .NET and Thorlabs' Kinesis Software") and a
     related NI Community forum thread -- the KB article's embedded
     LabVIEW block-diagram image (downloaded and read directly, not
     just its surrounding text) showed setting a `ChannelNumber`
     property before `CreateDevice()`, but on the entirely different
     `Thorlabs.MotionControl.Controls.BenchtopPiezoControl` class (a
     WinForms/WPF-hybrid ActiveX-style control, not the modern
     `BenchtopPiezoCLI.BenchtopPiezo` class). Attempting to instantiate
     that control class standalone failed at construction
     (`ResourceDictionary.Source` exception) -- it needs a real hosting
     WPF/WinForms application (Kinesis's own GUI, or LabVIEW's runtime),
     not usable headless. Ruled out as inapplicable to this script's
     architecture, not disproven in general.
- **Real root cause, found via .NET reflection, not guessed:**
  `DeviceManagerCLI.GetDeviceTypesList()` reports this device's actual
  type ID as **44**. `BenchtopPiezo`'s own `DevicePrefix41`/
  `DevicePrefix71` static constants (reflected directly from the DLL)
  do not include 44 -- meaning the modern BPC-specific class genuinely
  does not recognize this device's type at all, independent of call
  sequence. `Thorlabs.MotionControl.Benchtop.PrecisionPiezoCLI.dll`'s
  `BenchtopPrecisionPiezo` class has a `DevicePrefix44` constant that
  matches exactly. Confirmed by connecting: `BenchtopPrecisionPiezo
  .Connect("44533854")` succeeds with no exception, where
  `BenchtopPiezo.Connect(...)` never did. **This was a wrong-.NET-class
  problem, not a missing-initialization-step or channel-selection
  problem** -- both of the latter were live theories with real
  supporting evidence at the time, and were abandoned in favor of this
  one only once it was independently confirmed to actually work.
- **Definitive model confirmation, read live from the device's own
  `GetDeviceInfo()` (not inferred from any external source):**
  **Name: `PPC001`**, **Description: "PPC001 1 Ch Precision Piezo
  Unit"**, FirmwareVersion `2.1.4`, HardwareVersion `2`. This is a
  Thorlabs **PPC001** (1-Channel Precision Piezo Controller) -- a
  distinct product line from the BPC series entirely, purpose-built for
  closed-loop strain-gauge-feedback actuators (which is exactly the
  PFM450(E) mount's own feedback mechanism, per the user's confirmation
  of the actual connected actuator). An earlier in-session note claiming
  `ChannelCount=3` (implying BPC303) was **spurious** -- read from a
  `BenchtopPiezo` object that had never actually connected; the real,
  live-connected value is `ChannelCount=1`, consistent with "1 Ch" in
  the device's own description.
- **`hardware_tests/test_bpc_piezo_probe.py` updated to the correct
  class** (`BenchtopPrecisionPiezo`/`PrecisionPiezoCLI.dll` in place of
  `BenchtopPiezo`/`PiezoCLI.dll`; channel-level API surface --
  `GetPosition()`/`SetPosition()`/`GetOutputVoltage()`/
  `SetOutputVoltage()`/`GetPositionControlMode()`/`StartPolling()`/
  `StopPolling()` -- is identical between `PiezoChannel` and
  `PrecisionPiezoChannel`, both sharing the same `ThorlabsGenericPiezoCLI`
  base, so the rest of the script's structure needed no change). Module
  docstring rewritten to record the actual root cause and model, not the
  original (incorrect) assumption.
- **`--identify` and `--read` both run for real** (not simulated) via
  the corrected script, through `exp_ctrl`'s pythonnet:
  ```
  ChannelCount: 1
  PositionControlMode: OpenLoop
  Position: 0
  MaxTravel: 450
  OutputVoltage: 0
  MaxOutputVoltage: 150
  MinOutputVoltage: -25
  ```
  `MaxTravel=450` is presumed to be micrometers (matching "PFM450" in
  the mount's own product name) but this was not independently
  cross-checked against a units property or the PFM450(E) datasheet in
  this session -- flagged for confirmation before being relied on for
  real Z soft-limit values. **`--move` was never attempted**, per
  explicit instruction -- gated behind `--confirm SEND`, same as the
  established valve-probe convention, and correctly never reached since
  Phase 1's scope is read-only verification.

**Design decision recorded for the eventual driver-wrapper/acquisition
layer (Phase 2+, not implemented yet):** the device was found live in
`OpenLoop` mode, not `ClosedLoop` -- the mode this project's own Z-scan
use case requires for position accuracy with the PFM450(E)'s strain-gauge
feedback. Per explicit instruction, the future driver class must **never
auto-switch this silently**. The required pattern, to be implemented
wherever device initialization for the Z-scan feature ends up living
(the Phase-1 driver wrapper class, not the probe script, since this must
run every time the scan feature starts, not just during hardware
bring-up):
1. On connect, read `PositionControlMode`.
2. If already `ClosedLoop`: proceed normally, no prompt.
3. If `OpenLoop` (or anything else unexpected): stop and surface an
   explicit confirmation requirement before switching -- CLI/probe
   context: a `[y/n]`-style prompt; eventual UI context: a confirmation
   dialog, same "explicit acknowledgment before a hardware-mode change"
   pattern already established elsewhere in this project (e.g. the
   SeriesPath overwrite-confirmation `QMessageBox`, Session 10).
4. `ClosedLoop` is the correct *default expectation* for this
   application, but is never assumed or force-set without that
   acknowledgment.
Not implemented this session -- Phase 1 is still probe-script/driver-
wrapper-design stage, per instruction; this is recorded here so it
carries forward accurately into that later work rather than needing to
be rediscovered.

**Files touched:**
[hardware_tests/test_bpc_piezo_probe.py](hardware_tests/test_bpc_piezo_probe.py)
(new). No `src/thermo_acoustic/` files touched.

**Verification:** real hardware throughout this session's Phase 1 work
(list/identify/read all run against the genuine physical device, not
fakes/offscreen) -- this *is* the verification. No automated pytest
suite impact (new file lives under `hardware_tests/`, this project's
existing convention for real-hardware-only scripts, not the
`tests/`-collected fake-backed suite). Not yet integrated into
`qt_ui.py`/`qt_ui_v2.py` or `Application` -- Phase 1 scope only, per
explicit instruction not to proceed further until reviewed.

### Session 46 -- New hardware, Phase 2: PiezoStage driver wrapper class for the PPC001

**Still no UI/scan-loop work -- explicit instruction respected.**
`qt_ui.py`/`qt_ui_v2.py` untouched; no acquisition/scan logic added.
This is purely a clean, reusable, testable Python interface to the
device confirmed working in Session 45's Phase 1 probe script.

**New module: [src/thermo_acoustic/thorlabs_piezo.py](src/thermo_acoustic/thorlabs_piezo.py),
class `PiezoStage`, error class `PiezoStageError`.** Follows this
project's existing SDK-backend convention (`QmixPumpBackend` in
`qmix_backend.py`, structurally the closest precedent -- also a vendor
SDK wrapped in a `@dataclass(slots=True)`, with the SDK's own
classes/modules held as injectable fields rather than imported at
module scope, so tests can supply fakes with no real SDK installed):
- **`connect()`/`disconnect()`** use the exact sequence confirmed
  working in Session 45's probe script --
  `BenchtopPrecisionPiezo.CreateBenchtopPiezo()` -> `.Connect()` ->
  `.GetChannel()` -> `WaitForSettingsInitialized()` -> `StartPolling()`
  -- **not** `BenchtopPiezo` (the BPC301/BPC303 class this device's
  type ID doesn't match, per Session 45's root-cause finding).
  `connect()` rolls back (`ShutDown()`) and raises `PiezoStageError` on
  any failure partway through, matching `QmixPumpBackend.initialize()`'s
  own rollback-on-failure pattern; `disconnect()` accumulates errors
  across both cleanup steps (`StopPolling()`, `ShutDown()`) rather than
  stopping at the first, matching `QmixPumpBackend.close()`'s
  `_run_close_step()` pattern.
- **`max_travel_um`/`max_output_voltage_v`/`min_output_voltage_v` are
  read from the device at `connect()` time**, via `GetMaxTravel()`/
  `GetMaxOutputVoltage()`/`GetMinOutputVoltage()`, never hardcoded --
  per explicit instruction, in case this class is ever pointed at a
  different unit than this specific PPC001.
- **`set_position(target_um)` soft-clamps against the live
  `max_travel_um`** (and 0 as the lower bound) before calling
  `SetPosition()`, returning the clamped value actually sent so a
  caller can detect a request that got clamped.
- **ClosedLoop confirmation pattern (the Session 45 design decision)
  implemented exactly as specified, not simplified or skipped:**
  `connect()` only ever *reads* `PositionControlMode` into
  `self.position_control_mode` -- it never switches it.
  `needs_closed_loop_confirmation()` reports whether the live mode
  differs from `CloseLoop`; `switch_to_closed_loop()` is a separate,
  explicit method a caller may only invoke after obtaining real user
  confirmation (documented in its own docstring, not just the class
  docstring, so this constraint is visible at the call site too).
  `get_position()`/`set_position()` both raise `PiezoStageError` if
  called while not in `CloseLoop` mode, rather than silently returning
  a meaningless open-loop value or auto-switching to make the call
  succeed.
- **One real, non-obvious bug avoided by verifying against the DLL
  directly rather than assuming:** the Kinesis enum member is
  `CloseLoop`, not `ClosedLoop` -- confirmed via a dedicated .NET
  reflection check (`[System.Enum]::GetNames(...)` against
  `PiezoControlModeTypes` in `Thorlabs.MotionControl.GenericPiezoCLI.dll`)
  before writing any comparison logic, specifically because getting
  this string wrong would have made `needs_closed_loop_confirmation()`
  always report `True` (comparing against a name that never matches),
  defeating the entire confirmation pattern silently.
- **Testability:** `device_manager_cli`, `benchtop_precision_piezo_cls`,
  `closed_loop_mode`, and `decimal_type` are all injectable dataclass
  fields (default `None`, lazily populated by `_load_kinesis()` via
  pythonnet on first real `connect()`) -- including `decimal_type`
  (`System.Decimal`, required by the real `SetPosition()` call), which
  needed the same injectable treatment as the rest once it became clear
  a bare `from System import Decimal` inside `set_position()` would
  otherwise require pythonnet to even import the test module.

**Tests: [tests/test_thorlabs_piezo.py](tests/test_thorlabs_piezo.py)
(new), 12 tests, all passing, no live hardware or pythonnet required.**
Fakes (`FakeDeviceManagerCLI`/`FakeBenchtopPrecisionPiezo`/`FakeDevice`/
`FakeChannel`) mirror the real .NET method names exactly (PascalCase --
`Connect`/`GetChannel`/`WaitForSettingsInitialized`/`StartPolling`/
`GetMaxTravel`/etc.), matching this project's existing fake-SDK
convention (`FakeQmixBusModule`/`FakeQmixPumpModule` in
`test_application.py`). Coverage: connect reads real limits/mode without
hardcoding; connect is idempotent (a second `connect()` call does not
re-issue `Connect()`); connect failure raises `PiezoStageError` and
leaves the stage disconnected (not half-connected); disconnect calls
both `StopPolling()` and `ShutDown()`; every mode-dependent method
raises before connection; the ClosedLoop confirmation pattern is
exercised end-to-end (`OpenLoop` -> `needs_closed_loop_confirmation()`
is `True`, `SetPositionControlMode` never called until
`switch_to_closed_loop()` is invoked explicitly -> then `True`
afterward); `get_position()`/`set_position()` reject non-ClosedLoop
mode; `set_position()` clamps above-range, below-range (negative), and
in-range targets against the fake's own reported `max_travel_um`
(confirming the clamp uses the live-read value, not a hardcoded 450).

**Probe script preserved, not replaced, per explicit instruction.**
[hardware_tests/test_bpc_piezo_probe.py](hardware_tests/test_bpc_piezo_probe.py)
is untouched from Session 45's final state -- still the live-hardware
verification tool, `PiezoStage` is a separate, independent class built
from the same confirmed-working call sequence, not a wrapper around the
probe script or a replacement for it. Noted in passing, not something
this session needed to fix: that file is covered by a pre-existing
`.gitignore` rule (`hardware_tests/test_bpc_piezo_probe.py`, added in
an earlier commit not part of this conversation's own work, with an
explicit "local manual hardware probes that can issue real Thorlabs/BPC
actions -- keep out of the tracked automated test tree unless reviewed
and renamed" comment) -- consistent with, not contrary to, this
project's established hardware-safety caution.

**Files touched:** [src/thermo_acoustic/thorlabs_piezo.py](src/thermo_acoustic/thorlabs_piezo.py)
(new), [tests/test_thorlabs_piezo.py](tests/test_thorlabs_piezo.py) (new).
No `qt_ui.py`/`qt_ui_v2.py`/`Application` changes.

**Verification:** tested -- `tests/test_thorlabs_piezo.py` 12/12 passing
in isolation; full `tests/` suite green (229/229) across 2 consecutive
runs. Not hardware-verified in this session -- `PiezoStage` reuses the
exact call sequence Session 45 already confirmed against the real
PPC001, but this specific class (as opposed to the probe script's
procedural version of the same calls) has not itself been run against
the physical device yet.

### Session 47 -- New hardware, Phase 3: Z-scan calibration acquisition module

**Premise correction, confirmed by the user before any code was
written, not guessed past.** The original task described the camera as
a "Hamamatsu Orca Fusion BT via existing Micro-Manager integration."
Checking first (grepped the whole `src/`/`hardware_tests/`/`tests/`
tree for `micro-manager`/`micromanager`/`pymmcore`/`MMCore`: zero
matches anywhere) found no Micro-Manager layer exists in this codebase
at all -- the only camera integration is `hamamatsu_dcam.py`'s direct
DCAM SDK wrapper, fronting the C15440-20UP this project has used and
hardware-verified throughout its entire history. Reported this
discrepancy rather than inventing a Micro-Manager path or silently
substituting DCAM without asking. **User confirmed:** "Orca Fusion BT"
and "C15440-20UP" are the same physical camera (Hamamatsu's model
number vs. its marketed product name); the Micro-Manager phrase was the
user's own mistake, conflating a separate standalone GUI tool (used for
unrelated optical bring-up, outside this codebase) with this project's
actual camera integration. Built on the existing DCAM path, exactly as
found, per that confirmation.

**New module: [src/thermo_acoustic/piezo_zscan.py](src/thermo_acoustic/piezo_zscan.py),
class `ZScanCalibration` (+ `ZScanError`, `ZScanFrameResult`), plus a CLI
entry point (`main()`/argparse) in the same file** -- a module +
standalone-runnable script in one, per instruction, following this
project's `hardware_tests/` probe-script conventions for the CLI half
(`[piezo-zscan]`-prefixed step logging) and its production-module
conventions for the importable half (plain dataclass, no UI/Qt
dependency at all).
- **Reuses the existing single-frame capture path exactly, does not
  reinvent camera triggering:** `camera.capture_snapshot()`
  (`HamamatsuCamera`/`HamamatsuDcamBackend`, the same call
  `qt_ui.py`'s manual snapshot button already uses), returning a raw
  array saved via `PIL.Image.fromarray(...).save(path, format="TIFF")`
  -- the same library `hamamatsu_dcam.py`'s own `save_sequence()` uses
  internally, but with this task's own `z_XXXX.XXum.tif` filename
  convention instead of forcing `save_sequence()`'s unrelated
  `frame_00000.tiff` scheme to fit, per explicit instruction.
- **`exposure_ms` is an explicit, required parameter**, applied once via
  `camera.configure_exposure_time(exposure_ms)` at the start of
  `run()`, not inherited from whatever the caller left the camera
  configured to -- per the user's explicit reasoning (a calibration
  scan must be fully self-contained/reproducible from its own inputs),
  matching `PiezoStage`'s own no-hidden-state convention.
- **Fixed settle delay, not position-convergence-based**, exactly as
  specified: `time.sleep(settle_delay_ms / 1000.0)` after
  `piezo.set_position()` returns and before `capture_snapshot()`,
  default 75ms, exposed as a `settle_delay_ms` parameter (both on
  `ZScanCalibration.run()` and as a `--settle-delay-ms` CLI flag) rather
  than hardcoded to exactly 75.
- **Filenames embed the real closed-loop readback (`piezo.get_position()`),
  not the commanded target** -- `z_{measured_um:07.2f}um.tif`, e.g.
  `z_0125.30um.tif` for the task's own example. A settling residual
  (target reached imperfectly) shows up correctly in the saved filename
  because of this, confirmed by a dedicated test.
- **`ZScanFrameResult` (target_um, measured_um, filename) is collected
  as structured data during the scan itself**, not just embedded in
  filenames and left to be re-parsed later -- so a metadata/manifest
  file could be added afterward (e.g. serializing the returned list to
  JSON/CSV) without needing to rewrite how Z values are tracked
  internally, per explicit instruction. No such file is written yet --
  intentionally out of this session's scope, per "no separate metadata
  file needed for now."
- **The ClosedLoop confirmation pattern (Session 45/46's design
  decision) is threaded through exactly, not simplified.**
  `ZScanCalibration` takes a `confirm_closed_loop_switch: Callable[[],
  bool] | None` -- if the piezo is already `CloseLoop`,
  `PiezoStage.needs_closed_loop_confirmation()` short-circuits and the
  callback is never invoked (confirmed by a test whose callback raises
  `AssertionError` if it's ever called at all); if not, the callback
  runs and only a `True` result leads to `piezo.switch_to_closed_loop()`
  being called; `None`/a declined confirmation raises `ZScanError`
  *before any movement happens at all* (`set_position()` never called).
  The CLI's own default callback prints the exact wording given in the
  original design decision -- `"Device is currently in {mode} mode.
  Z-scan requires ClosedLoop for position accuracy. Switch now?
  [y/n]"` -- reading the *live* mode rather than hardcoding "OpenLoop",
  since the design decision itself said "or any other unexpected
  state."
- **Error handling: stop, don't skip, name the position and the
  completed count, flag the result as partial** -- both a mid-scan
  piezo move failure and a mid-scan capture failure (camera returns
  `None`) are caught, wrapped in a single `ZScanError` naming the
  1-based position index, the total position count, and how many
  frames completed successfully before the failure, with the literal
  word "PARTIAL" in the message so a caller can't mistake a truncated
  output directory for a complete stack. Confirmed by two dedicated
  tests (move failure, capture failure) asserting both the message
  content and that only the genuinely-completed frames exist on disk
  afterward -- no silently-skipped position, no silently-continued scan.
- **Range building is inclusive of both `z_start_um` and `z_end_um`**,
  via `round((z_end_um - z_start_um) / step_size_um)` steps -- documented
  in a code comment as the deliberate behavior when the span isn't an
  exact multiple of the step size (the *nominal* target may land
  slightly off in that case, but the *real, measured* position -- what
  actually gets recorded -- is unaffected either way).
- **Boundary -- pump/valve/AD2/laser are never touched, enforced by two
  independent tests, not just a docstring claim:**
  1. `test_module_never_imports_other_hardware_classes` walks
     `piezo_zscan.py`'s own AST and asserts none of
     `Valve`/`CetoniPump`/`QmixPumpBackend`/`AD2Sdk`/`WaveFormsBackend`/
     `PriorZMotor`/`Application` appear as an import anywhere in the
     file (including inside `main()`, where the real `PiezoStage`/
     `HamamatsuCamera`/`HamamatsuDcamBackend` imports live) -- a static
     guarantee independent of any test's mock shape.
  2. `test_scan_only_calls_piezo_and_camera_methods_no_other_hardware_touched`
     runs a full scan (including the ClosedLoop-switch path) against
     `FakePiezo`/`FakeCamera` test doubles that *only* implement the
     methods `ZScanCalibration` is supposed to call -- any accidental
     call to something else would raise `AttributeError` and fail the
     test immediately, not silently pass. Every other test in the file
     reuses these same narrow fakes, so this property holds throughout
     the suite, not just in one dedicated test.

**Tests: [tests/test_piezo_zscan.py](tests/test_piezo_zscan.py) (new),
13 tests, all passing, no live hardware/pythonnet/Qt required.** Covers:
frame count and filenames for an inclusive range; measured-vs-target
filename correctness (including a simulated settling residual);
exposure configured exactly once per scan, not per frame; settle delay
is both fixed-per-position and genuinely configurable (150ms case and
the 75ms default both asserted via a mocked `time.sleep`); input
validation (non-positive step size, inverted range, non-positive
exposure, negative settle delay); both failure-mode error-handling
tests described above; all four branches of the ClosedLoop confirmation
pattern (already-closed-loop, confirmed switch, declined switch, no
callback provided); and the two hardware-boundary tests.

**Files touched:** [src/thermo_acoustic/piezo_zscan.py](src/thermo_acoustic/piezo_zscan.py)
(new), [tests/test_piezo_zscan.py](tests/test_piezo_zscan.py) (new). No
`qt_ui.py`/`qt_ui_v2.py`/`Application` changes -- no UI, no scan-loop
wiring into the main app, per explicit instruction.

**Verification:** tested -- `tests/test_piezo_zscan.py` 13/13 passing in
isolation; full `tests/` suite green modulo the same already-documented
(Session 41/42) offscreen-Qt flakiness in unrelated `qt_ui`/`qt_ui_v2`
tests, confirmed passing in isolation both times it appeared during this
session's verification runs, together with this session's own 13 new
tests, in the same run. Not hardware-verified -- `piezo_zscan.py`'s
`main()` CLI entry point has not itself been run against the real PPC001
+ C15440-20UP yet; it reuses `PiezoStage`'s and `HamamatsuCamera`'s
already-hardware-confirmed (Session 45 for the piezo; long-standing
prior sessions for the camera) individual call sequences, but the two
combined in this specific new orchestration have not been exercised
against real hardware in this session.

### Session 48 -- Real-hardware verification of Phase 3, one real bug found and fixed

**First real end-to-end run of `piezo_zscan.py`'s CLI against the actual
PPC001 + C15440-20UP.** Parameters per explicit instruction: `z_start=200`,
`z_end=210`, `step_size=2` (6 positions, well inside the 450um travel
range, centered away from either end), `exposure_ms=20`,
`settle_delay_ms=75` (the default). The ClosedLoop-confirmation prompt
was exercised through its real code path, not bypassed -- `"y"` was
piped into the script's actual stdin (`echo y | ... python
piezo_zscan.py ...`), so the genuine `input()` call in
`_cli_confirm_closed_loop()` ran for real; it was simply never triggered
this run because the device was already `CloseLoop` at connect time (see
surprise #1 below).

**First attempt failed -- a real bug, not a hardware issue.**
`PiezoStage.connect()` raised `PiezoStageError: ... float() argument
must be a string or a real number, not 'Decimal'` inside
`channel.GetMaxTravel()`'s conversion. Root cause: pythonnet's
`System.Decimal` (the real return type of `GetMaxTravel()`/
`GetMaxOutputVoltage()`/`GetMinOutputVoltage()`/`GetPosition()`) does not
implement Python's `__float__` -- unlike Python's own stdlib
`decimal.Decimal`, which does. `float(x)` on a real `System.Decimal`
always raises; only `float(str(x))` works, since `str()` produces a
clean parseable numeral. **Why this wasn't caught by Session 46's unit
tests:** `FakeChannel`'s `Get*()` methods returned plain Python floats,
which `float()` happily accepts regardless of conversion method -- the
fakes didn't reproduce the one specific behavioral gap between
`System.Decimal` and a native Python number that this bug depended on.
This is exactly the class of gap real-hardware verification exists to
catch that mocks structurally cannot, on its own -- not a criticism of
Session 46's test design (the fakes correctly modeled every method
*call*, just not this one return-type quirk), but the reason this
session re-ran verification instead of treating Session 46/47's green
test suite as sufficient proof.
- **Fixed** in `src/thermo_acoustic/thorlabs_piezo.py`: new
  `_decimal_to_float(value)` helper (`float(str(value))`), used in place
  of every bare `float(channel.GetX())` call (`GetMaxTravel`,
  `GetMaxOutputVoltage`, `GetMinOutputVoltage`, `GetPosition`).
- **Test fidelity improved to catch a regression of this exact bug in
  the future, not just document it.** `tests/test_thorlabs_piezo.py`'s
  `FakeChannel` now wraps its `Get*()` return values in a new
  `FakeSystemDecimal` -- a minimal stand-in that supports `str()` but
  deliberately not `float()`, mirroring the real type's actual behavior
  instead of a Python `float`/stdlib `decimal.Decimal` that would let a
  regression back to bare `float(...)` pass silently. All 12
  `test_thorlabs_piezo.py` tests re-run and still pass against the
  corrected code with this stricter fake.
- **Re-ran the real scan after the fix: full success.**

**Real scan results (all 6 of 6 frames captured, no failures):**

| target (um) | measured (um) | filename |
|---|---|---|
| 200.00 | 200.18 | `z_0200.18um.tif` |
| 202.00 | 202.06 | `z_0202.06um.tif` |
| 204.00 | 204.05 | `z_0204.05um.tif` |
| 206.00 | 206.07 | `z_0206.07um.tif` |
| 208.00 | 208.07 | `z_0208.07um.tif` |
| 210.00 | 210.07 | `z_0210.07um.tif` |

Total wall-clock time: **~10.2 seconds** for connect + camera init + 6
positions (move + 75ms settle + capture each) + disconnect -- no timing
surprise, well within a reasonable range for a 6-point scan; unit tests
never modeled real connection/capture overhead (they mock `time.sleep`
specifically, nothing else), so there was nothing for this number to
contradict. Every saved file independently verified afterward, not just
trusted from the CLI's own "scan complete" line: all 6 are genuine,
non-degenerate 2304x2304 16-bit TIFFs (`I;16` mode, matching the
C15440-20UP's known full-frame resolution already referenced elsewhere
in this project's docs) with real, non-trivial pixel value ranges
(roughly 1580-3400 across the six frames, not blank/saturated), each
~10.1MB, saved under
`hardware_tests/output/piezo_zscan_verification/session48_first_real_scan/`
(gitignored, matching this project's established `hardware_tests/output/`
convention for real-run artifacts).

**Two things flagged as genuinely unexpected, per explicit instruction,
not smoothed over:**
1. **The device was already in `CloseLoop` mode at connect time**, not
   `OpenLoop` as it was when last read in Session 45. Something changed
   the mode between that session and this one -- outside this
   conversation's own actions (no `switch_to_closed_loop()`-equivalent
   call was made in between) -- most plausibly manual interaction via
   the Kinesis GUI at some point. Net effect: this run never actually
   exercised the "declined/no-callback" failure branches of the
   ClosedLoop-confirmation pattern against real hardware, only the
   already-satisfied branch -- those remain verified only by
   `test_piezo_zscan.py`'s mocked tests, not by a real run. Worth a
   dedicated real-hardware confirmation-prompt run later if that
   specific path needs hardware sign-off too.
2. **The first move's settling residual (0.18um) was noticeably larger
   than the other five (0.05-0.07um).** Plausibly the first move from an
   idle/pre-scan position settling more slowly within the fixed 75ms
   window than subsequent smaller relative moves, but this is a single
   scan's worth of evidence -- not enough to draw a real conclusion, and
   explicitly not treated as one here. Noted for whoever tunes
   `settle_delay_ms` later, not acted on.
No image-quality issues observed (pixel ranges and dimensions checked
directly, not just file existence).

**Files touched:** [src/thermo_acoustic/thorlabs_piezo.py](src/thermo_acoustic/thorlabs_piezo.py)
(Decimal-conversion fix), [tests/test_thorlabs_piezo.py](tests/test_thorlabs_piezo.py)
(`FakeSystemDecimal`, stricter fakes). No changes to `piezo_zscan.py`
itself -- the bug was entirely inside `PiezoStage`, not the scan
orchestration layer.

**Verification:** real hardware (the scan itself, described above) plus
`tests/test_thorlabs_piezo.py` 12/12 and `tests/test_piezo_zscan.py`
13/13 re-run against the fixed code; full `tests/` suite green (242/242).

### Session 49 -- pytest `--basetemp` leftover cleanup and a fixed-scratch-directory convention to prevent recurrence

**Investigated before deleting anything, per explicit instruction.**
User-reported: ~30+ (actually 119, counted directly) leftover
`.pytest_tmp_*`/`_pytest_tmp` directories in the project root, dated
2026-07-22 through 2026-07-27. Two hypotheses were given to
distinguish: a real cleanup-fixture bug, or expected/unbounded
`--basetemp` accumulation.
- **`tests/conftest.py`'s `_qt_widget_cleanup` fixture is unrelated and
  not at fault** -- read in full: it's a plain `yield`-based fixture
  with no conditional logic after `yield`, so pytest runs its teardown
  regardless of whether the test passed, failed, or raised (no
  "skip-on-failure" gap exists). More fundamentally, that fixture only
  tears down in-memory Qt widgets between tests within a single pytest
  process -- it has no connection to on-disk `--basetemp` directories at
  all; nothing in this project's code creates or cleans those up.
- **Root cause, confirmed by reading `pyproject.toml` and this
  project's own history (Session 27):** the real default `tmp_path`
  location on this machine (`%LOCALAPPDATA%\Temp\pytest-of-<user>`)
  raises a genuine `PermissionError`, so every session since Session 27
  has worked around it by passing an explicit, uniquely-named
  `--basetemp=<descriptive-name>` per ad hoc invocation. This is
  **not** quite "pytest's default retention count set too loose" (the
  more literal reading of the second hypothesis) -- passing `--basetemp`
  explicitly bypasses pytest's own retention/rotation system for
  auto-generated `tmp_path` directories entirely; since every invocation
  used a *different* name, nothing was ever reused or purged by any
  mechanism, pytest's or this project's. `pyproject.toml` had no
  `tmp_path_retention_count` or equivalent setting -- confirmed absent,
  not just unconfigured.
- **Confirmed clean otherwise, not just assumed:** none of the 119 were
  git-tracked (`.gitignore:43` `.pytest_tmp*/` and `:44` `_pytest_tmp/`
  cover all of them; `git status`/`git check-ignore -v` verified);
  contents spot-checked as routine `settings.json` test-scratch files
  matching `make_window()`'s normal per-test writes, nothing
  unexpected; total size 9.0MB.

**Cleanup: 84 of 119 deleted; 35 blocked by a pre-existing, already-
documented OS permission issue, not something newly broken.** `rm -rf`
(bash) and `Remove-Item -Force` (PowerShell) both failed identically on
the same 35 directories with `UnauthorizedAccessException` -- even
`Get-Acl`/`icacls` on those specific paths fail the same way, unable to
even *read* the ACL, let alone modify it. This is the identical failure
mode Session 27 already documented for a different, earlier batch of
leftover directories on this same machine ("all 20 remain Permission
denied... including to `Get-Acl` itself"), and Session 34 confirmed it
was specific to certain pre-existing directories rather than a blanket
inability to delete anything matching the naming pattern. Not pursued
further (no admin rights available in this session, and forcing
ownership takeover on directories whose origin isn't fully understood is
a bigger, more invasive action than this task asked for) -- left as-is,
consistent with how the same class of leftover was handled in Session 27.

**Prevention: a fixed, reused `--basetemp`, enforced at the config
level, not just documented as a convention to remember.**
`pyproject.toml`'s `[tool.pytest.ini_options]` now sets
`addopts = "--basetemp=.pytest_tmp_scratch"` -- every pytest invocation
that doesn't explicitly override `--basetemp` on its own command line
now automatically reuses the same directory (an explicit
`--basetemp=<other-name>` on the command line still takes precedence,
for the rare case a genuinely separate scratch location is needed).
Chosen over a documentation-only note specifically because the user
flagged the real risk plainly: a written convention with no enforcement
"quietly drifts back to descriptive-per-run names" the same way the
original workaround did, one ad hoc invocation at a time, over dozens of
sessions. Verified empirically, not just by reading the config: a test
run with no `--basetemp` flag at all now creates `.pytest_tmp_scratch`
automatically; a second run reuses the exact same directory (directory
count unchanged before/after); full `tests/` suite still green (242/242)
under the new default. `.pytest_tmp_scratch` is already covered by the
existing `.pytest_tmp*/` `.gitignore` pattern -- no `.gitignore` change
needed.

**Files touched:** [pyproject.toml](pyproject.toml) (`addopts` added,
with an inline comment explaining why, per "document wherever this
project's testing conventions are already written down" -- no separate
CONTRIBUTING-style file exists in this repo to put it in instead).
Deleted: 84 `.pytest_tmp_*`/`_pytest_tmp` directories (not tracked by
git, so no git diff from this deletion itself).

**Verification:** full `tests/` suite green (242/242) run with the new
`addopts` default in effect (no explicit `--basetemp` passed). Directory
count confirmed stable across repeated runs (no new leftover
accumulation). Not a code-behavior change to the application itself --
test-infrastructure/tooling only.

### Session 50 -- New hardware, Phase 4: Z-scan calibration tab in qt_ui.py/qt_ui_v2.py

**First UI-facing work for this feature -- Sessions 45-48 were driver/
module-only, explicitly deferring UI integration.** New standalone
"Z-Scan" tab in `qt_ui.py` (`self.tabs.addTab(self._zscan_tab(), "Z-Scan")`,
parallel to Experiment, not nested inside it) exposing
`piezo_zscan.ZScanCalibration.run()`'s real parameters 1:1 -- Z Start (um),
Z End (um), Step Size (um), Exposure Time (ms), Output Directory -- plus
Start Z-Scan/Abort Z-Scan controls and a real ClosedLoop confirmation
`QMessageBox` (not a CLI prompt). `qt_ui_v2.py` exposes the identical tab
as a new "Z-Scan" sidebar button/manual-panel dialog (`_MANUAL_PANEL_BUILDERS`
entry, same pattern as the existing Camera/WFG/MSO/Pump&Valve panels),
reusing the exact same widget instances qt_ui.py's tab uses, not copies.

**Landed on top of a separate, parallel, uncommitted TEC integration
effort already touching both UI files -- explicit instruction was to
leave that diff completely alone.** Every new addition in both files was
placed as a self-contained new block anchored on lines TEC's own diff
does not touch (confirmed by inspecting each merged git hunk directly,
not assumed): `_build_state()`'s new Z-scan widgets are appended
immediately after TEC's own last `_build_state()` addition rather than
interleaved with it; the new tab-builder/action methods
(`_zscan_tab()`/`_zscan_parameters_group()`/`_zscan_control_group()`/
`_query_zscan_range()`/`_apply_zscan_range()`/`_start_zscan()`/
`_run_zscan()`/`_abort_zscan()`) live in a untouched ~380-line gap between
two of TEC's own hunks; the new `self.tabs.addTab(..., "Z-Scan")` line and
`qt_ui_v2.py`'s `_MANUAL_PANEL_BUILDERS`/`_PANEL_DISPLAY_NAMES`/sidebar-loop
edits are each single-line diffs nowhere near any TEC hunk (TEC's v2
changes are confined to `DEVICE_NAMES`/the Initialize-dialog device rows/
the experiment-area grid/`HardwareRuntimeConfig`, none of which this
feature touches at all). No TEC-authored line was modified anywhere in
either file. `application.py`/`hardware_factory.py`/`workflows.py`/`tec.py`
and their test files were not opened for editing at all this session.

**Real-time range validation against the piezo's own live `MaxTravel`,
not left to `PiezoStage.set_position()`'s existing clamp-and-return as
the only defense -- a design decision confirmed explicitly before being
logged, after the first version of this tab's report initially omitted
it.** Z Start/Z End are `QDoubleSpinBox` fields whose range is set via
`setRange(0.0, max_travel_um)` from a live device read, not hardcoded or
left at the generic `_spin()` default of `+/-1e12`. Both fields start
**disabled** (range pinned to `[0, 0]`) with a dedicated status label
reading "Connect device to see valid range" until a real `max_travel_um`
is available -- matching `PiezoStage`'s own "never assume, always
live-read" convention (Session 46) rather than inventing a plausible-
looking default range. Two paths populate the real range, both reusing
the same `_apply_zscan_range(max_travel_um)` helper so there is exactly
one enable/range-setting code path, not two divergent ones:
1. **"Query Piezo Range"** -- a new dedicated button that connects,
   reads `max_travel_um`, disconnects immediately, and applies the range
   -- a deliberately lightweight connect/read/disconnect round trip (no
   persistent piezo handle kept alive across clicks, avoiding a second
   connection-lifecycle/cleanup path to manage beyond the one Start
   Z-Scan already has) so a user can see and set real, in-range values
   *before* ever clicking Start.
2. **Start Z-Scan's own connect step** now also calls
   `_apply_zscan_range(piezo.max_travel_um)` immediately after connecting,
   before reading the Z Start/Z End widgets' current values -- so a first
   Start click on a never-queried tab still ends up validated (the fields
   were disabled/pinned at 0.0/0.0 the instant before this call, so that
   specific click runs a degenerate single-position scan at 0um, which is
   safe -- not a validation gap -- but worth knowing about; a user who
   wants to scan a real range should click Query Piezo Range first, per
   the control group's own hint label).
`PiezoStage.set_position()`'s existing soft-clamp (Session 46) is
unchanged and remains the second line of defense underneath this --
this session adds real-time input constraint on top of it, not instead
of it.

**Cooperative abort added to `ZScanCalibration` itself (`piezo_zscan.py`),
a small, additive, backward-compatible change -- required since
`ZScanCalibration.run()` had no cancellation mechanism at all before this
session, and "Start/Abort controls" was explicit scope.** New optional
`should_abort: Callable[[], bool] | None = None` dataclass field, checked
once per position (before that position's own move/settle/capture -- an
in-flight position always finishes once started, never interrupted
mid-move/mid-capture) via the same partial-completion `ZScanError`
"PARTIAL" wording the existing move/capture-failure paths already use.
`None` (the default, and every existing test's implicit behavior) means
"never abort" -- fully backward compatible, confirmed by
`test_should_abort_none_never_checked_scan_runs_to_completion`. Abort
Z-Scan's UI action just sets `self._zscan_abort_requested = True`, which
the running scan's own `should_abort=lambda: self._zscan_abort_requested`
callable reads on its next per-position check.

**ClosedLoop confirmation dialog is genuinely modal-shown, not
simulated -- and shown before the scan's background thread even starts,
for a specific Qt threading reason, not by accident.** `_run_action()`'s
worker runs on a background `QThread`; a `QMessageBox` cannot safely be
raised from that thread. So `_start_zscan()` connects to the piezo and
checks/resolves the ClosedLoop question synchronously on the UI thread
*before* calling `_run_action()` at all -- only the scan itself
(move/settle/capture loop) runs in the background thread. Trade-off
flagged explicitly, not hidden: the UI briefly blocks during the piezo's
own `connect()` call (and the range-query round trip). Not measured this
session against real hardware, but Session 48's real end-to-end run
showed connect+init+6 frames totaling ~10.2s, most of which is settle/
capture rather than connect itself.

**Camera reuse, not a second connection.** The scan reuses
`self.app.camera` (the same instance the manual Camera tab's Configure
Camera / Image buttons already use) rather than opening an independent
camera handle -- `_start_zscan()` checks `self.app.camera.handle is not
None` first and fails with a clear status message ("run Configure Camera
on the Camera tab first") rather than crashing if the camera was never
initialized. The piezo, by contrast, is a strictly tab-owned connection
(no shared `Application`-level instrument bundle entry for it) --
connected fresh per Start-or-Query click and disconnected in a `finally`
block immediately after, mirroring `piezo_zscan.py`'s own CLI `main()`
exactly (Session 47).

**New imports are local/lazy inside the methods that need them
(`PiezoStage`/`PiezoStageError`/`ZScanCalibration`), not added to
qt_ui.py's top-level import block** -- that block is one of the exact
lines TEC's own diff already touches (`from .workflows import ...,
TemperatureSeries`), so adding a new top-level import there would have
been the one place this session's work could not avoid landing on a
TEC-touched line.

**Tests:** `tests/test_piezo_zscan.py` gained
`test_should_abort_stops_before_next_position_and_reports_partial` and
`test_should_abort_none_never_checked_scan_runs_to_completion` (15/15
passing, up from 13). `tests/test_qt_ui_hardware_settings.py`'s explicit
tooltip-count drift guard (Session 41's "protect a reviewed judgment call
from silent drift" test) bumped from 138 to 143 for the 5 new genuinely
non-obvious Z-scan fields (Z Start/Z End/Step Size/Exposure Time/Output
Directory), each tooltipped per the same non-obvious-hardware-semantics
classification criteria already used throughout, not blanket-added.

**Files touched:** [src/thermo_acoustic/qt_ui.py](src/thermo_acoustic/qt_ui.py)
(new tab + control methods, on top of TEC's existing uncommitted diff, no
TEC line modified), [src/thermo_acoustic/qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py)
(new sidebar panel, same constraint), [src/thermo_acoustic/piezo_zscan.py](src/thermo_acoustic/piezo_zscan.py)
(`should_abort` field + check), [tests/test_piezo_zscan.py](tests/test_piezo_zscan.py)
(2 new tests), [tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)
(tooltip-count assertion updated). `application.py`/`hardware_factory.py`/
`workflows.py`/`tec.py`/`test_hardware_factory.py`/`test_tec.py` not opened.

**Verification:** full `tests/` suite green, 244/244, confirmed stable
across 4 consecutive offscreen runs this session (one transient failure
mid-session reproduced the already-documented Session 41/42 offscreen-Qt
MainWindow-construction flakiness -- confirmed by re-running the specific
failing test alone, where it passed; a different test failed the same way
on a later full run, also passing alone -- consistent with the documented
pattern of a roughly-fixed-point-in-the-suite object-lifecycle issue
across many MainWindow instances in one process, not a regression from
this session's changes). Manually smoke-tested (offscreen): `MainWindow`
now has 7 tabs with "Z-Scan" last; `MainWindowV2`'s sidebar opens a
"Z-Scan (Manual Test)" dialog; Z Start/Z End start disabled at `[0, 0]`
with the "Connect device to see valid range" label; calling
`_apply_zscan_range(123.45)` enables both fields with range `[0.0,
123.45]` and updates the label to "Valid range: 0.00 - 123.45 um
(live-read from device MaxTravel)"; Start Z-Scan with no camera
initialized fails gracefully with a clear status message instead of
crashing. **Not hardware-verified** -- no real PPC001/C15440-20UP run of
the new UI path this session; Query Piezo Range/Start Z-Scan's connect
step reuse `PiezoStage`'s already-hardware-confirmed (Session 45/48) call
sequence, but the UI wiring itself (range application, disabled-state
toggling, the `QMessageBox` confirmation path, Abort) has only been
exercised via the offscreen test suite and manual smoke tests above, not
against the physical device. Not yet committed -- held for review per
explicit instruction before this session's work is committed.

### Session 51 -- Hardware-safety parameter audit, Priority 1 (Item 1): Custom syringe geometry bounds

**Follows a read-only audit (prior turn, not logged separately since it
proposed no changes) that inventoried every hardware-safety-critical
parameter across Valve/Pump/AD2/Camera/Laser/Piezo for whether an
out-of-range value is currently rejected, clamped, or passed straight
through unchecked.** That audit found `configure_syringe()`'s
`inner_diameter_mm`/`max_piston_stroke_mm` (Session 44's Custom syringe
feature) had only a presence check (`None` or not), no magnitude check
at all -- unlike `max_flow_rate_ul_min`/`max_volume_ml`, which the same
method reads back from the device immediately after
`set_syringe_param()` succeeds. **A follow-up failure-mode investigation
(same prior turn) found this was the one item across the whole audit
that could not be resolved as "definitely safe" from available
documentation**: CETONI's own SDK docs don't state whether pump firmware
cross-checks these values against the physically mounted syringe, and
the neMESYS firmware specification PDF could not be read in this
environment (image-based, no extractable text layer) to confirm an
independent actuator-travel software limit exists. Reprioritized to
highest urgency on that basis, ahead of AD2/Camera/pump-flow-rate (all
three of which research showed already fail safely one way or another).

**Fix: a conservative, hardcoded app-level reject -- not a live-read
limit, since no live device readback exists for these two parameters at
all** (`PiezoStage.max_travel_um`'s pattern doesn't apply here; there is
no equivalent "ask the syringe its own real geometry" call in the Qmix
SDK). New module-level constants in
[qmix_backend.py](src/thermo_acoustic/qmix_backend.py):
`MIN_SYRINGE_INNER_DIAMETER_MM=1.0`, `MAX_SYRINGE_INNER_DIAMETER_MM=35.0`,
`MIN_SYRINGE_STROKE_MM=10.0`, `MAX_SYRINGE_STROKE_MM=65.0`. The two
bounds are **not derived from the same source** -- conflating them was
a real mistake caught before commit (see correction note below):
1. **Inner diameter bounds** span BD's full published 1mL-60mL product
   line inner diameters (4.78mm-26.72mm -- confirmed via chemyx.com's BD
   plastic syringe diameter chart, which independently reproduced this
   project's own already-hardware-confirmed 1/5/10mL preset values
   exactly, giving confidence in the rest of that same table's 3/20/30/
   60mL entries too), padded to `[1.0, 35.0]` for legitimate brand/size
   variation the three named presets don't cover. This also comfortably
   matches CETONI's own Low Pressure Hardware Manual (Section 5.1,
   NEM-B101-02 E), which clamps syringe *outer* diameter to 6-30mm on
   this pump module -- 35mm as this constant's own ceiling since inner
   diameter is always smaller than outer.
2. **Stroke bounds' upper limit is this specific pump module's own real
   mechanical piston-travel ceiling** -- CETONI Low Pressure Hardware
   Manual, Section 5.1, NEM-B101-02 E: piston stroke "up to 65 mm",
   independent of whatever syringe is mounted. **Not** a BD-range-derived
   estimate (an earlier draft of this same fix, before review, padded
   this module's own volume/diameter->stroke formula applied across the
   BD 1mL-60mL range to `[10.0, 200.0]` instead -- see the correction
   note below for why that was wrong).
Not a precise engineering limit for inner diameter -- explicitly
documented in-code as a data-entry-error backstop there (unit mixups,
stray digits, transposed fields); the stroke upper bound, by contrast,
*is* a precise, cited hardware ceiling, not a padded estimate.
`configure_syringe()` now validates both values against these bounds
**before** calling `pump.set_syringe_param(...)`, raising
`QmixPumpError` naming the offending value, the valid range, and (for
stroke specifically) the hardware manual citation, if either is outside
it -- confirmed the three named `SYRINGE_PRESETS` (BD 1/5/10ml, max
derived stroke 60.55mm for the 10ml preset) all still pass comfortably
under the corrected 65mm ceiling, and confirmed at both boundaries: a
value `0.1` below the minimum or `0.1` above the maximum is rejected,
mirroring what happens exactly at the boundary (accepted, not rejected
-- bounds are inclusive).

**Correction made before commit, per explicit user instruction, after
review caught a real safety mismatch in the draft above:** the stroke
upper bound was originally set to `200.0` by padding this module's own
BD-volume-derived stroke formula across the full 1mL-60mL range
(43.7mm-107.0mm), the same treatment applied to the inner-diameter
bound. That reasoning does not apply to stroke -- unlike inner diameter
(a property of whatever syringe barrel is mounted), max piston stroke is
bounded by *this pump module's own fixed mechanical linear-actuator
travel*, a real, independent hardware ceiling regardless of the
syringe. `200.0` left a genuine gap open: any value between the real
65mm ceiling and the wrongly-padded 200mm would have been accepted by
`configure_syringe()` and forwarded to `set_syringe_param()`, risking
exactly the over-travel damage the manual's own ATTENTION warning in
that section describes. Corrected to `65.0`, cited directly at the
constant definition and at the `configure_syringe()` raise site, not
just in this log entry. A dedicated regression test
(`test_configure_syringe_rejects_stroke_between_real_ceiling_and_old_
padded_bound`, `100.0mm`) now covers this exact gap so it can't
silently reopen. `MIN_SYRINGE_STROKE_MM` (`10.0`) and both
`inner_diameter_mm` bounds were not implicated and are unchanged.

**Provenance added for `SYRINGE_PRESETS`' inner-diameter values
(4.78/12.07/14.5mm), per explicit instruction to check `git log -p` for
prior citation.** None existed: every version of this file back to the
syringe feature's original introduction (`git log -p --follow` on
`qmix_backend.py`) carried only "confirmed authoritative" with no
external source recorded. Added directly at the `SYRINGE_PRESETS`
definition: Chemyx BD Plastic Syringe reference table (chemyx.com),
cross-checked against BD REF 309628/309649/300912 packaging.

**UI side: the Custom syringe fields (Session 44's
`custom_syringe_inner_diameter_mm`/`custom_syringe_stroke_mm` in
`qt_ui.py`) now import and reuse these exact same constants as their
`QDoubleSpinBox` range**, rather than duplicating the numbers as
separate literals that could silently drift out of sync with
`qmix_backend.py`'s own bounds. This constrains input in real time (the
spin box itself won't accept a value outside `[1.0, 35.0]`/
`[10.0, 65.0]`) as a UI-layer backstop in front of the same backend
rejection -- in spirit the same "constrain the input, don't rely solely
on the backend's own rejection" principle the Z-scan tab's
`[0, max_travel_um]` range applies (Session 50), even though the
underlying limit here is hardcoded rather than live-read, since no live
syringe-geometry readback exists to derive it from instead. Both
fields' default values were changed from `1.0`/`1.0` (the old
generic-floor defaults, with the old stroke default of `1.0` actually
below the *new* minimum of `10.0` and would have been silently clamped
on load) to `4.78`/`55.75` -- the BD 1mL preset's own real diameter/
derived-stroke values (`55.75mm`, comfortably under the corrected 65mm
ceiling too) -- so the Custom fields start at a genuine plausible
syringe geometry instead of an arbitrary placeholder that happens to
need immediate silent correction. Both fields' tooltips now cite the
hardware-manual source directly, not just the numeric range.

**Tests:** `tests/test_application.py` gained
`test_configure_syringe_rejects_inner_diameter_below_minimum`,
`_above_maximum`, `test_configure_syringe_rejects_stroke_below_minimum`,
`_above_maximum` (all confirm `QmixPumpError` is raised and
`set_syringe_param` is never called on the fake pump),
`test_configure_syringe_accepts_values_exactly_at_bounds` (confirms
inclusive boundaries),
`test_configure_syringe_named_bd_presets_still_pass_the_new_bounds`
(confirms the bounds were derived wide enough to comfortably include the
existing, already-hardware-confirmed presets, not accidentally narrower
than them), and
`test_configure_syringe_rejects_stroke_between_real_ceiling_and_old_
padded_bound` (the correction's own regression guard, `100.0mm` --
explicitly asserts `65.0 < 100.0 < 200.0` first, so the test only proves
what it claims if `100.0` is still inside the now-closed gap) -- 7 new
tests total, all against the existing `FakeQmixPumpModule`/
`FakeQmixBusModule` fakes already used throughout this file, no live
hardware or Qmix SDK DLL required.

**Landed on top of the still-separate, still-untouched TEC integration
diff, same constraint as Session 50.** `qmix_backend.py` and
`tests/test_application.py` were not part of TEC's existing diff at all
(confirmed via `git status` before editing) -- fully standalone changes,
zero risk of interleaving. The Custom-syringe-field edit in `qt_ui.py`
lands in `_build_state()`, in the existing Session 44 block (original
lines 633-652), nowhere near any of TEC's own hunks in that file
(confirmed the same way as Session 50's Z-scan additions -- by
inspecting merged hunk boundaries directly, not assuming).

**Files touched:** [qmix_backend.py](src/thermo_acoustic/qmix_backend.py)
(4 new constants + validation in `configure_syringe()` + `SYRINGE_PRESETS`
provenance comment), [qt_ui.py](src/thermo_acoustic/qt_ui.py) (Custom
syringe field ranges + defaults + tooltips), [tests/test_application.py](tests/test_application.py)
(7 new tests + import list extended).

**Verification:** full `tests/` suite green, 265/265 (up from 244),
confirmed stable across offscreen runs both before and after the
stroke-bound correction. Manually re-smoke-tested after the correction:
`custom_syringe_stroke_mm` reports range `(10.0, 65.0)` (not
`(10.0, 200.0)`); `setValue(100.0)` on the stroke field is now clamped
to `65.0` by Qt's own `QDoubleSpinBox` range enforcement, confirming the
corrected UI-layer constraint is live, not just declared in a comment.
Not yet committed -- this entry documents Priority 1 Item 1 (including
its own pre-commit correction) only; Items 2-4 (AD2 amplitude/frequency
read-back, Camera ROI pre-flight check, Pump flow-rate-vs-max check)
were built and logged afterward, unaffected by this correction.
**Real-hardware verification against the actual Qmix/neMESYS pump
happened later this session -- see the dedicated hardware-verification
entry below.**

### Session 51 continued (Item 2): AD2 amplitude/frequency clamped against the device's own live range, `WfgChannelConfig.out_of_range` wired up

**Reframed from "emergency hardware safety" to "correctness/data-integrity"
after the failure-mode research this same audit did**: confirmed against
Digilent's own WaveForms SDK reference manual (not assumed) that
`FDwfAnalogOutNodeAmplitudeSet`/`FrequencySet` never fail or reject an
out-of-range value -- they silently clamp to whatever the AD2 hardware
can actually do (W1/W2 outputs are spec'd +/-5V) and still report
success. So this was never a hardware-damage risk; the real risk is an
operator unknowingly running with a silently-substituted drive
amplitude/frequency, which matters for this project's own data
integrity (a mis-recorded drive parameter is bad science, not broken
hardware).

**Real root-cause finding: the higher-level `analog_out_node_
amplitude_set()`/`frequency_set()` wrapper methods (which already existed)
are not what the real hardware configuration path actually calls.**
`AD2Sdk.config_wfg()`/`wfg_configure()`/`wfg_start_stop_all_ch()` all
funnel through `WaveFormsBackend.configure_wfg()`, which calls its own
private `_configure_analog_node()` -- a method that talks to the raw
`self._dwf.FDwfAnalogOutNode*` ctypes function pointers directly, not
through the public wrapper methods at all. A fix aimed only at the
public wrappers would never have been exercised by any real experiment
run.

**Fix, in `_configure_analog_node()`
([waveforms.py:418](src/thermo_acoustic/waveforms.py:418)):** before
either `FrequencySet`/`AmplitudeSet` call, now reads the device's own
live `FDwfAnalogOutNodeFrequencyInfo`/`AmplitudeInfo` (real min/max,
same underlying calls the already-existing but previously-unused
`analog_out_node_frequency_info()`/`amplitude_info()` wrapper methods
expose), clamps the requested `frequency_hz`/`amplitude_v` to that range
in software before ever calling `*Set`, and returns whether either value
actually needed clamping. `configure_wfg()`
([waveforms.py:389](src/thermo_acoustic/waveforms.py:389)) now calls this
once for the carrier node and once for the FM Mod node (only if enabled,
matching existing behavior), and sets
`channel.out_of_range = carrier_out_of_range or fm_out_of_range` --
**the first place in this codebase that ever assigns `True` to this
field.** `WfgConfig.check_valid()`/`AD2Sdk.wfg_check_config_valid()`
already existed (confirmed dead in the prior audit -- no producer ever
set the flag they check) and needed no changes themselves; they now
report real information for the first time.

**Surfaced in two places, per explicit instruction ("UI and logged
experiment metadata"), not just the underlying flag:**
1. **UI:** `qt_ui.py`'s `_apply_wfg()`
   ([qt_ui.py:2836](src/thermo_acoustic/qt_ui.py:2836)) now checks
   `config.check_valid()` after `config_wfg()`/`wfg_start_stop_all_ch()`
   and, if any channel came back out of range, returns
   `"WFG configured -- WARNING: amplitude/frequency clamped to device
   limits on Ch1, Ch2"` (naming only the actually-affected 1-based
   channel(s), matching this project's existing Ch1/Ch2 UI convention --
   `channel_index` is 0-based internally) instead of the plain
   `"WFG configured"` -- this becomes the visible status-bar text via the
   existing `_run_action()`/`_handle_worker_finished()` machinery, no new
   UI widget needed.
2. **Logged experiment metadata:** `workflows.py`'s `_wfg_properties()`
   ([workflows.py:215](src/thermo_acoustic/workflows.py:215)) gained a
   new `WFGOutOfRangeCh1`/`WFGOutOfRangeCh2` TDMS property per repeat,
   directly from `channel.out_of_range` -- so a silently-substituted
   drive value is recorded in the data itself, not just a transient UI
   status line that's gone the moment the next action overwrites it.

**Tests:** a new purpose-built fake, `FakeAD2ConfigureDwf`
(`tests/test_application.py`) -- deliberately not the existing generic
`FakeDwf` in the same file, whose blanket `"*Info"`-suffix handling
returns a degenerate `(100.0, 100.0)` for every Info call (frequency and
amplitude indistinguishable, unable to exercise clamping in a specific
direction). Lets frequency/amplitude device ranges be set independently.
New tests: `test_configure_wfg_clamps_out_of_range_amplitude_and_
frequency_and_flags_channel` (confirms clamping to the real max, not the
requested value, and `out_of_range=True`),
`test_configure_wfg_leaves_in_range_values_unclamped_and_not_out_of_range`
(confirms no false positives), and
`test_configure_wfg_checks_fm_mod_node_too_when_enabled` (confirms the FM
Mod node, not just Carrier, can trigger the flag). A local, file-scoped
equivalent fake (`_FakeAD2ConfigureDwf`) in
`tests/test_qt_ui_hardware_settings.py` backs
`test_apply_wfg_surfaces_out_of_range_warning_in_status` and
`test_apply_wfg_reports_no_warning_when_in_range` (confirms the UI status
text itself, both the warning and plain-success cases) -- not imported
across test files, matching this project's existing per-file
self-contained-fake convention. `test_experiment2_writes_labview_
metadata_tdms` extended to assert `WFGOutOfRangeCh1`/`Ch2` are present
and `False` for its existing in-range fixture data. 6 new tests total.

**Landed cleanly, same standalone-from-TEC pattern as Item 1.**
`waveforms.py` was never part of TEC's diff at all. The `qt_ui.py` edit
(`_apply_wfg()`) and the `workflows.py` edit (`_wfg_properties()`) both
sit in function bodies TEC's own diff never touches in either file
(confirmed directly via `git diff`'s hunk boundaries, not assumed) --
TEC's `workflows.py` changes are confined to a new `TemperatureSeries`
class and a `tec_target_c`/`"TECTarget"` property a few lines above
`_wfg_properties()`'s own definition, never inside it.

**Files touched:** [waveforms.py](src/thermo_acoustic/waveforms.py)
(`_configure_analog_node()` clamping + return value, `configure_wfg()`
sets `out_of_range`), [qt_ui.py](src/thermo_acoustic/qt_ui.py)
(`_apply_wfg()` status message), [workflows.py](src/thermo_acoustic/workflows.py)
(`_wfg_properties()` new TDMS field), [tests/test_application.py](tests/test_application.py)
(3 new tests + `FakeAD2ConfigureDwf` + 1 extended test),
[tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)
(2 new tests + `_FakeAD2ConfigureDwf` + new imports).

**Verification:** full `tests/` suite green, 255/255 (up from 250),
confirmed via 2 consecutive offscreen runs -- one showed a single
failure in an unrelated test (`test_v2_sidebar_opening_manual_panel_
does_not_initialize_hardware`), confirmed to be the same already-
documented Session 41/42 offscreen-Qt MainWindow-construction flakiness
(passed immediately when re-run alone), not a regression from this
change. **Still not hardware-verified as of this entry** -- the
mechanism is proven against the purpose-built fake, not the physical
device (Digilent's own documented `*Set`-never-fails/`*Info()`-is-
authoritative behavior is the basis for trusting this generalizes, not
a live re-confirmation). **Real-hardware verification for this item
specifically was attempted later this session but blocked -- no
physical Analog Discovery device was connected to the machine
(confirmed via Device Manager USB VID scan: zero `VID_1443` devices
present, despite the WaveForms SDK/runtime being installed) -- see the
dedicated hardware-verification entry below for the full account,
including the other three items which the same pass DID verify against
real connected hardware.** Not yet committed, per the same
review-before-commit instruction as Items 1 and Session 50. Items 3-4
(Camera ROI pre-flight check, Pump flow-rate-vs-max check) remain
separate and not yet started as of this
entry.

### Session 51 continued (Item 3): Camera ROI pre-flight bounds check

**Explicitly framed as UX/fail-fast, not urgent, from the start** -- the
failure-mode research already found DCAM's own SUBARRAY properties
already reject an invalid combination via the existing `_check()`/
`prop_setgetvalue()` calls in `configure_roi()` (confirmed by reading the
vendored DCAM error enum directly: `INVALIDSUBARRAY = 0x8000082b`,
*"the combination of subarray values are invalid, e.g. SUBARRAYHPOS +
SUBARRAYHSIZE is greater than the number of horizontal pixel of
sensor"*), and that a wrong ROI/exposure can't physically damage a
camera sensor either way. This item just catches the same condition
earlier, with a clearer, ROI-specific message, rather than a generic
DCAM error surfacing only after a full SDK round-trip.

**Fix, in `configure_roi()`
([hamamatsu_dcam.py:86](src/thermo_acoustic/hamamatsu_dcam.py:86)):** now
calls the already-existing `read_subregion_limits_and_value()` (which
this method never called before, despite it already existing) to get
both the sensor's real, live limits and the ROI currently in effect,
then a new `_validate_roi_against_limits()` helper checks, in order:
horizontal/vertical size against their own live
`[minimum, maximum]`; horizontal/vertical offset against theirs; and a
combined offset-plus-size check against the sensor's real pixel count
-- deliberately mirroring DCAM's own documented `INVALIDSUBARRAY`
condition, not a different check invented for this fix. The combined
check uses whichever size will actually be in effect *after* this call
(the requested size if `configure_roi()` is changing it this time,
otherwise the size already in effect) -- confirmed by a dedicated test,
since size=0 has a distinct meaning in this codebase ("don't change
this axis's size," per `configure_roi()`'s own pre-existing
`if roi.horizontal_size > 0:` guard around the real `Set` call), not
"use the full sensor."

**Tests (`tests/test_application.py`):** `test_validate_roi_against_
limits_accepts_in_range_roi` (no false positives),
`test_validate_roi_against_limits_rejects_size_above_sensor_max`,
`test_validate_roi_against_limits_rejects_offset_plus_size_exceeding_
sensor` (the actual INVALIDSUBARRAY-mirroring combined check, individually
in-range values whose sum still exceeds the sensor),
`test_validate_roi_against_limits_uses_current_size_when_size_not_
being_changed` (confirms the size=0 fallback-to-current-size behavior
specifically), and `test_configure_roi_rejects_out_of_range_roi_before_
any_sdk_write` (confirms the rejection happens *before* any
`prop_setgetvalue("SUBARRAYHSIZE", ...)` call reaches the fake SDK at
all, not just that it eventually raises) -- 5 new tests, all against
plain `SubRegion`/`SubRegionLimits`/`MinMaxInc` value objects or the
existing shared `FakeDcamModule` fixture (whose generous `[0, 4096]`
fixed range already comfortably covers `test_hamamatsu_dcam_backend_
uses_sdk_wrapper`'s existing `SubRegion(4, 8, 100, 120)` call, confirmed
unaffected), no new dedicated fake needed since a clearly-out-of-range
value (`horizontal_size=5000`) was enough to exercise rejection against
that same fixture's fixed bounds.

**Landed cleanly, same standalone-from-TEC pattern as Items 1-2.**
`hamamatsu_dcam.py` was never part of TEC's diff at all.

**Files touched:** [hamamatsu_dcam.py](src/thermo_acoustic/hamamatsu_dcam.py)
(`configure_roi()` pre-flight call + new `_validate_roi_against_limits()`),
[tests/test_application.py](tests/test_application.py) (5 new tests).

**Verification:** full `tests/` suite green, 260/260 (up from 255),
confirmed stable across 2 consecutive offscreen runs, no flakiness this
round. Not yet committed. Item 4 (Pump flow-rate-vs-max check) remains
separate and not yet started as of this entry. **Real-hardware
verification against the actual C15440-20UP happened later this
session -- see the dedicated hardware-verification entry below, which
also corrects this entry's own characterization of "the old DCAM
behavior": DCAM's `INVALIDSUBARRAY` was found to fire only at the final
`SUBARRAYMODE ON` call, not at the individual `SUBARRAYHSIZE`/
`SUBARRAYHPOS` `prop_setgetvalue()` writes as implied above -- the new
pre-flight check is a stronger improvement than originally stated here,
see below for why.**

### Session 51 continued (Item 4): Pump flow rate vs. its own reported max_flow_rate_ul_min -- Priority 1 complete

**The last of the four Priority 1 items.** Failure-mode research (prior
turn) found this one "probably safe by stepper-motor physics" (open-loop
steppers generally stall/skip steps rather than break when asked to
exceed real torque/speed capability) but not confirmed by CETONI's own
documentation -- reason enough, per the user's own framing, to stop
relying on an unconfirmed safe-failure mode when the actual limit value
was already sitting right there unused.

**Root cause: `max_flow_rate_ul_min` was already being read back from
the device** (`initialize()` at
[qmix_backend.py:86](src/thermo_acoustic/qmix_backend.py:86),
re-populated by `configure_syringe()`/`configure_flow_unit()` too, since
the real achievable max depends on syringe geometry and flow unit) --
**but `generate_flow()` never actually compared the requested value
against it**, unlike `configure_syringe()`'s own new bounds check
(Item 1, same session). `LCP_GenerateFlow` was called with whatever was
requested, unconditionally.

**Fix, in `generate_flow()`
([qmix_backend.py:156](src/thermo_acoustic/qmix_backend.py:156)):** now
compares `abs(flow_rate)` against `self.max_flow_rate_ul_min` before
calling `pump.generate_flow(...)`, raising `QmixPumpError` if it's
exceeded. `abs()` specifically because `generate_flow()`'s own docstring
states a negative value means aspirate and positive means dispense --
the magnitude is what must not exceed the pump's own reported ceiling,
in either direction; a signed-only comparison would have let an
excessive aspirate rate straight through. `None` (meaning the pump
hasn't reported a real ceiling yet, e.g. `configure_syringe()` was never
called) skips the check entirely -- nothing to validate against, so this
passes through exactly as it did before this fix, not a new invented
default.

**Tests (`tests/test_application.py`):**
`test_generate_flow_rejects_dispense_rate_above_max`,
`test_generate_flow_rejects_aspirate_rate_above_max_magnitude` (confirms
the `abs()` requirement specifically -- a negative rate whose magnitude
exceeds the max is still rejected, not let through because it's
negative), `test_generate_flow_accepts_rate_exactly_at_max` (inclusive
bound), and `test_generate_flow_passes_through_when_max_flow_rate_not_
yet_known` (confirms the `None`-skips-validation path explicitly, not
just implicitly relying on it never coming up) -- 4 new tests, all
against the existing `FakeQmixPumpModule`/`FakeQmixBusModule` fakes
already used throughout this file (whose fake pump's own
`get_flow_rate_max()` returns `5000.0`, and the pre-existing
`test_qmix_pump_backend_initializes_and_dispatches` already calls
`generate_flow(-5000.0)` -- confirmed still passes, since `5000.0` is
exactly at the boundary, not above it).

**Landed cleanly, same standalone-from-TEC pattern as every other item
this session.** `qmix_backend.py` was never part of TEC's diff at all
(same file Item 1 already touched this session, no new entanglement
risk introduced).

**Files touched:** [qmix_backend.py](src/thermo_acoustic/qmix_backend.py)
(`generate_flow()` bounds check), [tests/test_application.py](tests/test_application.py)
(4 new tests).

**Verification:** full `tests/` suite green, 264/264 (up from 260),
confirmed stable across 2 consecutive offscreen runs, no flakiness this
round. Not yet committed, per the same review-before-commit instruction
as every other item this session. **Real-hardware verification against
the actual Qmix/neMESYS pump happened later this session -- see the
dedicated hardware-verification entry below.**

**All four Priority 1 items from the hardware-safety audit are now
implemented, tested, and logged, pending review before commit and
pending real-hardware verification (see below).**

### Session 51 continued: real-hardware verification of Priority 1 Items 1, 3, 4 (Item 2 blocked -- no device)

**Explicit instruction: do not commit until real-hardware verification
is done, both accept and reject paths, real bugs fixed and
re-verified.** This entry follows the same reporting pattern as Session
48's piezo hardware verification: what was tested, pass/fail per item,
and every discrepancy documented individually and plainly, not
compressed into a vague summary line.

**Hardware discovery, done before touching anything (safe, read-only
probes only):** Device Manager USB VID scan found a **Hamamatsu C15440**
camera physically connected (`USB\VID_0661&PID_144B\500478`, Status OK)
and a **CETONI VCI4 USB-to-CAN compact** adapter (Status OK) -- the real
CETONI Qmix pump's own CAN interface. `C:\Program Files\QmixElements`
(the real CETONI Elements software) and a genuine, specific single-pump
project configuration
(`C:\Users\Lab user\Desktop\Franzi\video paper 2\Paper 2 slow flow\
Configurations\Cetoni_1pump_config_FM`) were found on disk, matching
this repo's own `hardware_config.py:ONE_PUMP_QMIX_CONFIG_PATH` default
exactly -- confirming this is the genuine lab machine, not a generic
sandbox. A Thorlabs APT device (serial `44533854`, matching
`PiezoStage`'s own default serial) was also present, unrelated to
today's four items. **No Digilent Analog Discovery device was found** --
zero `VID_1443` entries anywhere in Device Manager, even after the user
attempted to connect one and a second scan. An initial, misleading
signal (`FDwfEnum` reporting device count `1` with a blank name/serial)
was investigated and dismissed as not real hardware -- likely a stale
enumeration artifact from the WaveForms runtime, since no real AD2 has
ever been discoverable via the actual PnP device list at any point this
session.

**Item 1 (Syringe geometry) -- PASS, no bugs found.** Connected via
`QMIXSDK=C:\Users\Lab user\AppData\Local\CETONI_SDK` and the real
`Cetoni_1pump_config_FM` project. **Accept path:**
`configure_syringe({"name": "BD 1ml"})` succeeded; the pump reported a
real, non-round `max_flow_rate_ul_min` before (`7316.42`) and after
(`6686.74`, genuinely different once real syringe geometry was applied)
-- confirming genuine device communication, not a fake. **Reject path:**
`configure_syringe({"inner_diameter_mm": 10.0, "max_piston_stroke_mm":
70.0})` (just above the real 65mm ceiling) raised `QmixPumpError` citing
the manual, exactly as designed. **Verified with hardware-level proof,
not just trust in the exception:** read `pump.get_syringe_param()`
before and after the rejected call -- identical (`4.78mm`/`55.73mm`,
the BD 1ml values) both times, confirming the rejected value never
reached the device's own stored state.

**Item 4 (Pump flow rate) -- PASS, no bugs found.** Same connection.
Per explicit user direction (avoiding real motor motion given no visual
confirmation of the physical syringe/tubing setup was possible),
**accept path** used `generate_flow(0.0)` -- a genuinely valid,
zero-actuation rate -- which reached the real `pump.generate_flow()` SDK
call successfully with no exception; `stop_pumping()` was called
immediately after as an additional safety measure regardless.
**Reject path:** `generate_flow(max_flow_rate_ul_min + 100000.0)` raised
`QmixPumpError` before any SDK call, citing the real reported max. No
physical pump motion occurred at any point in this item's verification.

**Item 3 (Camera ROI) -- PASS, no bugs in the fix, but a real finding
that corrects how the fix's own changelog entry characterized "the old
behavior."** Connected to the real C15440 directly (no `QMIXSDK`/CAN
involved). Real sensor limits read: `horizontal_size`/`vertical_size`
`[4, 2304]` (step 4), `horizontal_offset`/`vertical_offset` `[0, 2300]`
(step 4) -- confirming the well-known 2304-pixel full resolution
referenced throughout this project's history. **Accept path:** a valid
ROI (`offset=100,100`, `size=800x600`) configured successfully in
`0.3487s`, confirmed via readback -- no regression from the pre-fix
behavior. **Reject path:** an invalid ROI (`offset=2000`,
`size=2304` -- sum `4304` against the real `2304`px sensor) was rejected
by the new pre-flight check in `0.0001s`; readback confirmed the ROI
stayed unchanged (still the valid `800x600` one) after the rejected
attempt.

**Investigated as instructed ("compare timing/clarity against the old
behavior... to confirm this is actually an improvement, not just
different") -- this surfaced a real discrepancy from what Item 3's own
prior research assumed, worth correcting rather than ignoring since it
wasn't a test failure, just an inaccurate characterization:** bypassing
the new pre-flight check and issuing the raw DCAM calls directly
(`prop_setgetvalue(SUBARRAYHSIZE, 2304)` then
`prop_setgetvalue(SUBARRAYHPOS, 2000)`) **both succeeded individually,
with no error at all** -- DCAM does not validate the horizontal
offset+size combination at the point of writing either property. The
real `INVALIDSUBARRAY` error (confirmed: raised with code `-2147481557`
= `0x8000082b`, matching the documented enum value exactly) only fires
at the *final* `prop_setvalue(SUBARRAYMODE, ON)` call -- the last of
five calls in `configure_roi()`'s own original sequence. **This means
the pre-Session-51 code path would have transiently written the invalid
`SUBARRAYHSIZE`/`SUBARRAYHPOS` values to the physical camera before
failing at that last step**, not rejected them at the point of writing
as the Item 3 changelog entry above implied. The new pre-flight check is
therefore a **stronger improvement than originally documented**: it
doesn't just surface the same error earlier with a clearer message, it
prevents the device from ever being written into that invalid
intermediate state at all. Not a bug in the fix itself -- the fix's own
logic and every existing test remain correct, since the pre-flight
check's own combined-sum condition is independently derived from the
same documented `INVALIDSUBARRAY` semantics and was confirmed correct
against real hardware in the reject-path test above. **Recovery
confirmed:** after this raw-SDK investigation, the camera was reset to
a full-frame ROI and normal `configure_roi()` operation was confirmed to
resume with no lasting bad state -- re-opening the camera fresh showed
it had already reverted to a sane full-frame reading on its own (DCAM's
own behavior when `SUBARRAYMODE` is left off), not a stuck invalid
state. The Item 3 entry above has been corrected in place to point here
rather than left with the less-accurate original characterization.

**Item 2 (AD2) -- BLOCKED, not hardware-verified this session.** No
physical Analog Discovery device was ever detected despite the user's
attempt to connect one (confirmed via a second Device Manager scan
after connection). Per explicit user decision, this item proceeds
**without** real-hardware verification for now -- the `should_abort`-
equivalent mechanism (device-reported `AnalogOutNode*Info()` clamping,
`out_of_range` wiring) remains verified only against the purpose-built
fake from earlier in this session, not the physical device. Flagged as
the one open item from this pass; AD2 hardware verification should
happen in a future session once the device is physically connected.

**No bugs were found in any of the three verified items' actual
enforcement logic.** The one real discrepancy found (Item 3's DCAM
`INVALIDSUBARRAY` timing) was in this session's own documentation of
*why* the fix is an improvement, not in the fix's behavior -- corrected
above, no code change required as a result.

**Cleanup:** confirmed no new files were written by any verification
script this session (`configure_syringe`/`generate_flow`/`configure_roi`/
`read_subregion_limits_and_value` are all pure SDK-call/validation
paths with no file I/O) -- `git status` showed no new untracked entries
beyond what already existed before this pass. Separately, while
confirming this, found `hardware_tests/output/` (containing prior
sessions' real-run artifacts, including Session 48's own piezo
verification output) was **never actually covered by `.gitignore`**,
despite earlier changelog entries (including Session 48's) describing
it as "gitignored, matching this project's established convention" --
that convention existed in practice (nothing from it was ever
committed) but not in the actual ignore rules. Added a real
`hardware_tests/output/` rule to `.gitignore` now, with a comment
explaining the gap.

**Files touched:** [.gitignore](.gitignore) (new `hardware_tests/output/`
rule). No source files changed as a result of this verification pass --
all three verified items' existing implementations were confirmed
correct as-is against real hardware.

**Verification:** full `tests/` suite still green, 265/265 (unchanged --
no code changes this pass). Real hardware: Items 1, 3, 4 confirmed
pass (accept and reject paths, each with hardware-level evidence, not
just a raised/not-raised exception). Item 2 not yet verified, device
unavailable. **Ready for commit review with this one explicit caveat
carried forward: Item 2 (AD2) is backed by fake-based tests only, not a
live device.**

### Session 51 continued: pre-commit hunk separation found a second, genuine entanglement -- the tooltip-count assertion

**While carefully separating this session's own changes from the
still-separate, still-untouched TEC integration diff via `git add -p`
(hunk-by-hunk, verified after every file with `git diff --cached`/
`git diff`), one genuine line-level entanglement was found and could
not be resolved by hunk splitting alone** -- unlike every other shared
file this session, where spatial separation (different lines/functions)
made clean hunk-level staging straightforward and was independently
verified for each file (`workflows.py`, `qt_ui_v2.py`, `qt_ui.py`, all
confirmed hunk-by-hunk with zero TEC content in the staged diff).

`tests/test_qt_ui_hardware_settings.py`'s `test_every_value_widget_has_
a_tooltip_and_visible_marker` drift-guard assertion had been edited
*twice* on the *same line*, sequentially: `129` (the real pre-session
baseline) -> `138` (TEC's own uncommitted +9 fields) -> `143` (this
session's own +5 Z-scan fields, added on top of TEC's own edit,
Session 50). Since `git diff` only ever compares the working tree
against the last commit, both edits collapsed into a single line-level
change with no hunk boundary to split on -- reported to the user rather
than guessed at, per the same standing instruction from Session 50
("if... additions can't be cleanly distinguished... STOP and report").

**Resolved per explicit user direction:** the assertion and its comment
were rewritten to state the number correct for *this commit alone, in
isolation* -- `129` (real baseline) `+ 5` (this session's own Z-scan
fields) `= 134` -- with TEC's own eventual `+9` explicitly left for
their own future commit to add, not preempted here. **This
deliberately leaves one known, expected test failure in the current
combined working tree** (real widget count is `143` with TEC's
uncommitted diff still physically present in `qt_ui.py`, but the
assertion this commit carries says `134`) **until TEC's own future
commit bumps this same assertion line from `134` to `143` as part of
its own change.** Confirmed by direct measurement, not just reasoning
about it: `git stash --keep-index -u` temporarily set aside TEC's
entire unstaged diff and untracked files, full `tests/` suite run
against the resulting isolated (staged-content-only) working tree came
back **264/265** (one offscreen-Qt-flakiness failure, confirmed
transient by re-running alone and by two further full-suite runs each
showing a *different* transient failure, never the same test twice) --
critically, the tooltip-count assertion itself passed cleanly in that
isolated state, confirming `134` really is correct for this commit
standalone. `git stash pop` restored TEC's diff immediately afterward;
the subsequent combined-state run reproduced exactly the one expected
failure described above, `264/265`, nothing else.

**A second, smaller staging mistake was caught and fixed during this
same pre-commit pass, not left silent:** an initial `git add -p` batch
for this file accidentally staged a `from pathlib import Path` import
line alongside this session's own new imports -- that `Path` import is
actually needed by one of TEC's own new test functions
(`test_qt_ui_builds_one_experiment_group_per_tec_temperature`), not
this session's work. Caught by inspecting the staged diff directly
(not assumed correct from the `git add -p` transcript alone) and
corrected via `git reset -p` before proceeding, leaving that one import
line properly unstaged with the rest of TEC's diff.

**Files touched by this correction:**
[tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py)
(assertion `143` -> `134`, comment rewritten to explain the split and
point to this note).

### Session 51 continued: Item 2 (AD2) hardware-verified -- the earlier "device not connected" conclusion was itself a diagnostic error

**The user confirmed the AD2 works fine under the existing LabVIEW
program, ruling out "device genuinely absent/broken" and pointing
squarely at this session's own Python-side detection as the thing to
re-examine -- same diagnostic discipline as the Session 45 BPC303
class-mismatch investigation (real root cause found via direct
evidence, not the first plausible guess accepted).**

**Investigated in order, before touching any code, exactly as
instructed:**
1. **No competing process or service found holding the device.**
   `Get-Process`/`Get-Service` (PowerShell) found no LabVIEW, WaveForms,
   or any Digilent-named process or service running at the time of
   re-testing. Only one `dwf.dll` exists anywhere on the machine
   (`System32`, `SysWOW64`, and the WaveForms3 install directory, all
   byte-identical by date, 2024-02-29) -- no version/path mismatch, no
   legacy Digilent Adept Runtime installed alongside the current
   WaveForms Runtime that could be silently claiming the device under
   an older driver generation.
2. **LabVIEW uses the identical underlying SDK, not a different driver
   stack.** `labview_ports.py`'s own registry shows `AD2_SDK.lvclass`'s
   VIs call into a custom LabVIEW wrapper library, `Olasdwf.lvlib`,
   whose own VI names (`F Dwf Enum`, `F Dwf Device Open`, `F Dwf Analog
   Out Node Amplitude Set`, etc.) are a direct, function-for-function
   mirror of the WaveForms SDK's real C API -- the same `dwf.dll` this
   Python codebase's own `waveforms.py` calls into via ctypes. Ruled
   out "LabVIEW and Python are using genuinely different drivers" as
   the explanation.
3. **The actual bug, found by re-running this project's own
   `WaveFormsBackend.enum_devices()`/`enum_device_name()`/
   `enum_device_serial_number()` (no new script, the existing code
   path): this specific Analog Discovery 2 unit enumerates over USB
   under an FTDI bridge-chip Vendor ID (`VID_0403&PID_6014`, serial
   `210321A18CE2`), not Digilent's own `VID_1443`** -- confirmed by the
   real serial number read back from `enum_device_serial_number()`
   matching, character for character, a "USB Serial Converter" PnP
   entry already visible in the very first hardware-discovery pass
   earlier this session, which was misclassified at the time as an
   unrelated generic FTDI serial adapter rather than recognized as the
   AD2 itself. **The earlier "no AD2 physically connected" conclusion
   was a genuine investigative error** -- searching Device Manager for
   the wrong Vendor ID and treating the absence of that specific VID as
   proof of absence, the same class of premature-conclusion risk the
   Session 45 piezo investigation guarded against by insisting on
   independent confirmation (there, via `.NET` reflection against the
   real DLL; here, via this project's own enumeration code returning a
   real, matching name and serial rather than trusting a Device
   Manager VID filter). Not a driver conflict, not an exclusive lock,
   not a version mismatch -- a wrong assumption about which VID to look
   for.

**Re-ran this project's own enumeration code with no changes:**
```
enum_devices() count: 1
  device 0: name='Analog Discovery 2' sn='SN:210321A18CE2' opened=False
last error code: 0
```
Real name, real serial, `opened=False` (confirming nothing else
currently holds it open). Proceeded to Item 2's hardware verification
exactly as originally specified.

**Item 2 (AD2) -- PASS, no bugs found.** Real hardware throughout,
`configure_wfg()` always called with `running=False` so the analog
output stage was never actually started -- no real signal appeared on
the AD2's physical output pins at any point in this verification (the
clamping/`out_of_range` logic being verified lives entirely in the
Set-value computation inside `_configure_analog_node()`, independent of
whether output is later started). Real device-reported ranges read
first: frequency `[1e-6, 1e8]` Hz, amplitude `[0.01, 5.0]` V (Ch1
Carrier node). **Accept path:** `amplitude_v=1.0`, `frequency_hz=1000.0`
(both in range) -> `out_of_range=False`; read back via
`analog_out_node_frequency_get()`/`amplitude_get()`: `1000.0000221897726`
Hz / `0.9999862130521723` V -- matching the requested values within
real DAC quantization, not exact floating-point equality, exactly as
expected for physical hardware. **Reject path:** `amplitude_v=10.0`
(above the real 5.0V max) -> `out_of_range=True`; real applied
amplitude read back as `4.9996361796517474` V -- clamped to the
device's own real ceiling, not the requested 10.0V. **UI status line**
(`MainWindow._apply_wfg()`, real `AD2Sdk`+`WaveFormsBackend`, no fake):
`'WFG configured -- WARNING: amplitude/frequency clamped to device
limits on Ch1'` -- exact match to the designed message, naming only the
actually-affected channel. **Logged TDMS metadata**
(`Experiment2._settings_properties()`, real `WfgConfig` object straight
from the hardware call): `WFGOutOfRangeCh1=True`,
`WFGOutOfRangeCh2=False` -- correctly per-channel, not a blanket flag.

**All four Priority 1 items are now hardware-verified with no bugs
found in any of the four enforcement mechanisms.** The one earlier bug
this whole verification pass surfaced (Item 2's own detection gap) was
a diagnostic error in how *this session* checked for the device, not a
defect in the `out_of_range`/clamping code itself, which behaved
correctly the moment a real, correctly-identified device was available
to test against.

**Files touched:** none -- this entry is diagnostic and verification
only, no code changes resulted from the Item 2 investigation (the
device detection "gap" was never a code bug, so there was nothing in
`waveforms.py`/`instruments.py`/`qt_ui.py` to fix).

**Verification:** full `tests/` suite unaffected (still the one
documented, expected failure from the tooltip-count entanglement above,
264/265). Real hardware: Item 2 confirmed pass, accept and reject paths,
UI status line, and TDMS metadata field, closing the last remaining gap
from this session's hardware-verification pass.

### Session 52 -- Silent-failure/data-integrity sweep, Finding A: WFGOutOfRange written to data.tdms before it was ever computed

**Read-only sweep first (prior turn, not logged separately since it
proposed no changes), then implementing its findings one at a time,
starting with the highest-priority one.** The sweep used
`docs/known_open_items.md`'s "data-integrity gaps" section (10 items,
all re-verified unchanged against current code) as a starting
inventory, then did a fresh targeted pass of `application.py`,
`workflows.py`, and each hardware module for silent failures and
TDMS/experiment-record metadata completeness. Seven findings (A-G)
came out of that pass; this entry covers Finding A only, in isolation,
per instruction not to batch fixes into one vague entry.

**The bug.** `run_experiment2()` ([application.py:379-384](src/thermo_acoustic/application.py:379),
pre-fix) called `experiment.save_settings()` -- which snapshots
`WFGOutOfRangeCh1`/`Ch2` into `data.tdms` via `_settings_properties()`
-- **before** `self.ad2.config_wfg(experiment.wfg_config)` ran.
`WfgChannelConfig.out_of_range` is only ever set to `True` inside
`WaveFormsBackend.configure_wfg()`/`_configure_analog_node()`
([waveforms.py:393-403](src/thermo_acoustic/waveforms.py:393), Session
51 / commit `23e17d5`) -- i.e. three lines *after* the metadata
snapshot that was supposed to record it. `save_settings()` was never
called again afterward, and `Experiment2._tdms_properties` is a
snapshot dict updated in place, not a live view -- so the final
`data.tdms` for every repeat always recorded `WFGOutOfRangeCh1=False`/
`Ch2=False`, regardless of whether real clamping happened that run.
This is exactly the case the Session 51 out-of-range flag was built to
catch (an operator's requested drive amplitude/frequency silently
substituted by the AD2 hardware) -- undone by call order, so the one
piece of evidence meant to reveal it never reached the saved record.

**Why the existing test suite never caught this.**
`test_configure_wfg_clamps_out_of_range_amplitude_and_frequency_and_flags_channel`
(`waveforms.py`-level) and `test_experiment2_writes_labview_metadata_tdms`
(`workflows.py`-level, calls `experiment.save_settings()` directly
against a fixture) both test their own layer in isolation and both
passed while this bug shipped -- neither one drives the real
`run_experiment2()` call order end-to-end.

**Ordering trace performed before choosing a fix, per explicit
instruction.** Traced every field `_settings_properties()`/
`_camera_properties()` read between the original `save_settings()`
call and the end of `run_experiment2()`: `wfg_config`/`do_clock_settings`/
`sequence_settings`/`flush_settings`/`global_exposure_ms`/
`trigger_global_exposure`/`fm_sweep` are all set on `Experiment2`
before `run_experiment2()` starts and none of them are mutated again by
anything between the two candidate points, except
`WfgChannelConfig.out_of_range` itself (`config_wfg()`'s own
side-effect) -- `coerce_wfg_config()` returns the same object instance
when already a `WfgConfig` (confirmed in `ad2.py`), so `experiment.wfg_config`
and `self.ad2.wfg_config` are the same object and the mutation is
visible either way; only the *timing* of the metadata snapshot was
broken. `config_do_clock_special()` has no equivalent out-of-range
concept today (DO clock only rejects `clock_frequency_hz <= 0`, it
doesn't clamp), so it doesn't add anything new to re-snapshot, but is
covered by the same second call for consistency and to protect any
future DO-clock flag added later.

**A real regression risk found and deliberately avoided: simply moving
`save_settings()` later, rather than adding a second call, would have
silently dropped the existing partial-record-on-failure behavior.** If
`config_wfg()`/`config_do_clock_special()` itself raises (e.g. real
device disconnected mid-series), the *original* call ordering left a
`data.tdms` on disk with the requested settings already recorded before
the failure -- useful forensic context for exactly the failure case
this project's own hardware-safety work cares most about. Replacing
(not augmenting) the early call would have traded one data-integrity
gap for a smaller but real one. **Fix implemented: the original early
`save_settings()` call is kept exactly as-is, and a second
`save_settings()` call is added immediately after
`config_do_clock_special()`** ([application.py:379-397](src/thermo_acoustic/application.py:379)) --
cheap (it's the same TDMS write path already used elsewhere per
repeat, not a new mechanism) and preserves both properties: an early
partial record if hardware configuration fails, and a final record
that reflects what hardware configuration actually did.

**Test:** `test_run_experiment2_records_real_wfg_clamping_in_final_tdms`
([tests/test_application.py](tests/test_application.py)) -- the
end-to-end test the user explicitly asked for, not another isolated
unit test. Drives a real `AD2Sdk` + `WaveFormsBackend` (not
`SimulatedAD2Sdk`) against the existing `FakeAD2ConfigureDwf` fake
ctypes module (already used by the Session 51 clamping tests, reused
here rather than duplicated) with a narrowed amplitude range, so a
10.0V requested carrier amplitude genuinely gets clamped through the
same code path a real device would use; `device_handle` is pre-set on
the `AD2Sdk` to skip the fake's unmodeled `FDwfDeviceOpen` byref
behavior without weakening what's actually being tested (device
opening is not what this test is about). Calls the real
`app.run_experiment2()`, then reads back the *final* persisted
`data.tdms` properties (via the existing `install_fake_nptdms()`
harness) and asserts `WFGOutOfRangeCh1 is True`. **Verified this test
actually catches the regression, not just that it passes**: temporarily
removed the new second `save_settings()` call and re-ran this test
alone -- it failed with the exact assertion this bug produces (`False`
where `True` was expected); restored the fix immediately after and
confirmed the diff was back to its intended state.

**Files touched:** [application.py](src/thermo_acoustic/application.py)
(`run_experiment2()`, second `save_settings()` call + explanatory
comment), [tests/test_application.py](tests/test_application.py) (1 new
test, `test_run_experiment2_records_real_wfg_clamping_in_final_tdms`).

**Verification:** tested -- full `tests/` suite green, 270/270 (up from
269 pre-fix; TEC's own uncommitted diff and tests remain untouched
throughout, confirmed via `git status` before and after). Not
hardware-verified -- exercised against the same `FakeAD2ConfigureDwf`
fake the Session 51 clamping tests already used, not a real Analog
Discovery device; the underlying clamping mechanism itself was already
real-hardware-verified in Session 51's own continued entry above, this
fix only corrects when its result is captured into `data.tdms`, not the
clamping logic itself. Not committed, per instruction -- findings B-G
from this same sweep remain to be implemented and logged individually.

### Session 52 continued, Finding B: no record of simulated-vs-real hardware in the experiment record

**The gap.** `HamamatsuCamera.simulate`, `CetoniPump.simulate`,
`Valve.simulate` (and the `AD2Sdk`/`SimulatedAD2Sdk` class distinction)
were all readable from `Application`'s own live instrument instances,
but none of it ever reached `data.tdms` -- confirmed absent via grep
before starting. A simulated dry-run and a real experiment produced
structurally identical `data.tdms` files; nothing in the file itself
told a later reviewer which one they were looking at.

**Fix.** Four new fields on `Experiment2`
([workflows.py:121-144](src/thermo_acoustic/workflows.py:121)):
`sim_ad2`/`sim_camera`/`sim_pump`/`sim_valve`, all defaulting `False`
(matching this dataclass's existing convention of plain value fields
with no hardware reference of its own). `_settings_properties()`
([workflows.py:207-215](src/thermo_acoustic/workflows.py:207)) writes
them as `SimAD2`/`SimCamera`/`SimPump`/`SimValve`.
`Application.run_experiment2()`
([application.py:379-388](src/thermo_acoustic/application.py:379))
sets all four from live instrument state right after dequeuing the
experiment, before the first `save_settings()` snapshot: `sim_ad2 =
isinstance(self.ad2, SimulatedAD2Sdk)` (no `simulate` attribute exists
on `AD2Sdk` itself -- construction-time class choice is the only
signal, matching how `hardware_factory.build_hardware_bundle()` itself
decides which class to build), the other three read `.simulate`
directly.

**Test.** `test_run_experiment2_records_simulated_vs_real_instruments_in_final_tdms`
([tests/test_application.py](tests/test_application.py)) -- drives the
real `run_experiment2()`, deliberately with a **mixed** configuration
(`AD2Sdk(enabled=False)`, the real non-simulated class, left disabled
so no hardware backend is actually touched, against every other
instrument at its default `simulate=True`) specifically so a bug that
collapsed all four flags to one hardcoded value, or read the wrong
instrument for one of them, would be caught -- not just "the key
exists with some value". **Verified this test actually catches the
regression**, same discipline as Finding A: temporarily removed the
four new assignment lines and re-ran the test alone -- failed on
`SimCamera` exactly as expected; restored immediately after.

**Incidental fixture gap found and fixed while running the full
suite.** `tests/test_full_flow_dry_run.py`'s hand-rolled `FakeCamera`/
`FakePump`/`FakeValve` duck-typed test doubles had no `.simulate`
attribute at all (unlike the real classes they stand in for), so 9
existing tests in that file broke with `AttributeError` the moment
`run_experiment2()` started reading it. Added `self.simulate = True`
to each fake's `__init__` -- these fakes already exist specifically to
avoid touching real hardware, so `True` is the accurate value, not an
arbitrary placeholder.

**Files touched:** [workflows.py](src/thermo_acoustic/workflows.py)
(4 new `Experiment2` fields + 4 new TDMS properties),
[application.py](src/thermo_acoustic/application.py) (`run_experiment2()`
sets the 4 fields from live instrument state, `SimulatedAD2Sdk` added
to the existing `.instruments` import),
[tests/test_application.py](tests/test_application.py) (1 new test),
[tests/test_full_flow_dry_run.py](tests/test_full_flow_dry_run.py)
(`.simulate` added to 3 existing fakes, no test logic changed).

**Verification:** tested -- full `tests/` suite green modulo the
already-documented (Session 41/42/48) offscreen-Qt/Shiboken
construction flakiness in `test_qt_ui_v2.py` (a different single test
failed on 2 of 3 full-suite runs during verification, always passing
cleanly when re-run alone or as part of just `test_qt_ui_v2.py`) --
confirmed via `git status`/`git diff` that none of this session's
changes touch `qt_ui_v2.py` or its tests at all, so this is the
pre-existing environmental characteristic, not a regression. Not
hardware-verified -- `sim_ad2`/`sim_camera`/`sim_pump`/`sim_valve` are
plain boolean reads of already-existing instrument state, no new
hardware interaction to verify against. Not committed, per instruction.

### Session 52 continued, Finding C: camera sequence cluster (trigger source, master pulse, polarity/delay) never recorded to TDMS

**The gap.** Session 22 made `masterpulse_mode`/`masterpulse_source`/
`masterpulse_interval_s`/`masterpulse_burst_times`, `trigger_polarity`,
`trigger_delay_s`, and `trigger_source` genuinely load-bearing for
automated runs -- carried from the manual Camera tab's live widgets
into `_build_experiment_series()`'s `sequence_settings` dict, then read
by `HamamatsuDcamBackend.configure_sequence()`
([hamamatsu_dcam.py:190-235](src/thermo_acoustic/hamamatsu_dcam.py:190))
every automated run. None of it was ever written to `data.tdms` --
`_camera_properties()` only recorded `ReadoutTime`/ROI (read back from
hardware *after* capture), and `_settings_properties()` didn't include
any of these seven keys either, confirmed absent by direct grep before
starting. Given this project's own most-cited unresolved open item is
whether camera trigger source should be Internal or External, a saved
experiment's own `data.tdms` couldn't even confirm which one was
actually used for that run.

**No ordering dependency, unlike Finding A.** Traced where
`experiment.sequence_settings` is set (at `Experiment2` construction
time, by `qt_ui.py`'s `_build_experiment_series()`, well before
`run_experiment2()` is ever called) against where it's read
(`self.camera.configure_sequence(experiment.sequence_settings)`,
[application.py:403](src/thermo_acoustic/application.py:403), and
nowhere else) -- `run_experiment2()` never mutates it. So the field is
already fully populated by the time the very first `save_settings()`
call runs; this fix required no `application.py` changes at all, only
`workflows.py`.

**Fix.** New `Experiment2._sequence_properties()`
([workflows.py:229-247](src/thermo_acoustic/workflows.py:229)) reads
`self.sequence_settings` (already an existing field, nothing new to
thread through) and extracts the seven keys as `TriggerSource`/
`MasterPulseMode`/`MasterPulseSource`/`MasterPulseInterval`/
`MasterPulseBurstTimes`/`TriggerPolarity`/`TriggerDelay`, each
defaulting to `""` when the underlying `sequence_settings` dict is
`None` or the specific key is absent -- matching this file's existing
`_wfg_properties()`/`_fm_sweep_properties()` empty-string-when-inactive
convention. Wired into `_settings_properties()`
([workflows.py:218](src/thermo_acoustic/workflows.py:218)) alongside
the other `properties.update(self._..._properties())` calls.

**Tests (both in [tests/test_application.py](tests/test_application.py)):**
`test_experiment2_writes_camera_sequence_cluster_to_tdms` -- uses
distinguishable, non-default values for every one of the seven fields
(not just "present"), matching the exact dict keys
`HamamatsuDcamBackend.configure_sequence()` itself reads, so a bug that
read the wrong key or hardcoded a default would fail this test, not
just a generic key-presence check.
`test_experiment2_sequence_properties_default_to_empty_string_when_unset`
confirms the `sequence_settings=None` fallback path. **Verified both
tests actually catch the regression**, same discipline as Findings
A/B: temporarily removed the `properties.update(self._sequence_properties())`
wiring line and re-ran both alone -- both failed (`KeyError`, since the
keys didn't exist at all pre-fix, not merely wrong values); restored
immediately after.

**Files touched:** [workflows.py](src/thermo_acoustic/workflows.py)
(`_sequence_properties()` + one wiring line in `_settings_properties()`),
[tests/test_application.py](tests/test_application.py) (2 new tests).

**Verification:** tested -- full `tests/` suite green, 273/273. Not
hardware-verified -- this only changes what's read from an already-set
Python dict into `data.tdms`; the underlying `configure_sequence()`
hardware-writing behavior itself is completely unchanged.

### Session 52 continued, Finding D: flush failure surfaced live but never recorded in that repeat's data.tdms

**The gap.** Session 7 already made a failed flush surface loudly at
the process level -- `Application.flush()` returning `False` fires
`"ExperimentFlushFailed"`, logs via `logger.error`, and appends to
`Application.errors` -- but none of that reaches the experiment record
itself. The repeat's `data.tdms` (already written by the earlier
`save_settings()` calls) had `FlushVolume`/`FlushFlowrate` sitting next
to nothing indicating whether the flush they describe ever actually
completed. Someone inspecting `data.tdms` in isolation, without
cross-referencing the live app log (not persisted per-experiment),
previously had no way to tell.

**Fix.** New `Experiment2.save_flush_result(completed: bool)`
([workflows.py:160-173](src/thermo_acoustic/workflows.py:160)) -- a
small, purpose-specific write, following the same one-purpose-per-method
convention as `save_camera_settings()`/`save_image_data()`, not folded
into `save_settings()` since flush happens after both of that method's
call sites in `run_experiment2()`. `_settings_properties()`
([workflows.py:214-224](src/thermo_acoustic/workflows.py:214)) gained a
default `"FlushCompleted": ""` ("not attempted") -- correct at both of
its own call sites since flush always runs after them.
`Application.run_experiment2()`
([application.py:452-460](src/thermo_acoustic/application.py:452)) now
calls `experiment.save_flush_result(flush_completed)` immediately after
computing the result, **before** the `if not flush_completed:` branch --
so both the success and early-return-on-failure paths record it.

**Tests (all in [tests/test_application.py](tests/test_application.py)):**
`test_run_experiment2_records_flush_failure_in_final_tdms` (monkeypatches
`Application.flush` to return `False`, confirms `FlushCompleted is False`
in the final written `data.tdms`, not just that the status/log fired);
`test_run_experiment2_records_flush_success_in_final_tdms` (the
counterpart -- a genuinely successful flush against default simulated
pump/valve, confirms `FlushCompleted is True`, ruling out a hardcoded
`False` or absent-field bug); `test_experiment2_flush_completed_defaults_to_empty_string_when_flush_never_runs`
(confirms the `""`-not-attempted default for `flush_enabled=False`).
**Verified the two `run_experiment2()`-level tests actually catch the
regression**, same discipline as Findings A/B/C: temporarily removed
the `experiment.save_flush_result(flush_completed)` call and re-ran
both alone -- both failed (`'' is True`/`'' is False`, the "not
attempted" default leaking through instead of the real result);
restored immediately after.

**Files touched:** [workflows.py](src/thermo_acoustic/workflows.py)
(`save_flush_result()` + `FlushCompleted` default in
`_settings_properties()`), [application.py](src/thermo_acoustic/application.py)
(`run_experiment2()`, one call added), [tests/test_application.py](tests/test_application.py)
(3 new tests).

**Verification:** tested -- full `tests/` suite green, 276/276. Not
hardware-verified -- `flush()`'s own return-value semantics are
completely unchanged (Session 7/31/32/33 territory, already
hardware-verified); this only records that same return value into
`data.tdms`.

### Session 52 continued, Finding E: exposure and DO-clock requested-vs-applied readback

**The gap, two related parts, both a smaller version of the same class
of bug Finding A fixed for WFG amplitude/frequency.**
1. `HamamatsuDcamBackend.configure_exposure_time()`
   ([hamamatsu_dcam.py:79](src/thermo_acoustic/hamamatsu_dcam.py:79),
   pre-fix) discarded `prop_setgetvalue()`'s own return value -- per
   DCAM's own documented "set and get" contract, this call returns the
   *real* value the device applied (which can differ from the request
   due to DCAM's internal exposure quantization), not just whether the
   call succeeded. `HamamatsuCamera.configure_exposure_time()`
   ([instruments.py:501](src/thermo_acoustic/instruments.py:501)) then
   set `self.exposure_ms` to the raw *requested* value regardless --
   the exact same attribute `Application._check_camera_timing_budget()`
   already trusts for a hardware-safety-adjacent FPS/readout check.
2. `WaveFormsBackend.configure_do()`
   ([waveforms.py:504](src/thermo_acoustic/waveforms.py:504)) computes
   an **integer** `clock_divider` from the requested `clock_frequency_hz`
   -- the real achieved DO-clock frequency after that truncation was
   never computed or recorded anywhere; `data.tdms`'s `DOFreq` always
   showed the requested value.

**Fix, part 1 (DCAM exposure).**
`HamamatsuDcamBackend.configure_exposure_time()` now returns the real
applied value (`result * 1000.0`, converting `prop_setgetvalue()`'s
seconds back to ms) instead of `None`. `CameraBackend` Protocol
([instruments.py:107](src/thermo_acoustic/instruments.py:107)) and
`HamamatsuCamera.configure_exposure_time()`
([instruments.py:501-514](src/thermo_acoustic/instruments.py:501))
updated to match -- when a real backend is attached, `self.exposure_ms`
now tracks the real applied value; the simulated/no-backend case is
unchanged (no real device to read back from, requested value used
as-is). `Application.run_experiment2()`
([application.py:409-427](src/thermo_acoustic/application.py:409))
captures the return value, updates `experiment.global_exposure_ms`
with it, and calls `experiment.save_settings()` a third time so
`data.tdms`'s `ExposureTime` records what was actually applied, not
the raw request -- the same "record what actually happened, not what
was requested" guarantee Finding A already established for
`WFGOutOfRange`, extended to this field. All existing fake camera
backends across the test suite (`FakeCameraBackend` in
`tests/test_application.py`, `FakeCamera` in
`tests/test_full_flow_dry_run.py`) updated to echo the requested value
back (`return exposure_ms`) rather than implicitly returning `None`,
which would otherwise have corrupted `self.exposure_ms`/
`experiment.global_exposure_ms` to `None` for every test using them --
caught immediately by the full suite (9 failures) before being fixed.

**Fix, part 2 (DO clock).** New
`DoSingleChannelConfig.achieved_clock_frequency_hz: float | None = None`
field ([ad2.py:171-184](src/thermo_acoustic/ad2.py:171)), mirroring
`WfgChannelConfig.out_of_range`'s "never assigned until the real
hardware call runs" pattern. `configure_do()`
([waveforms.py:497-509](src/thermo_acoustic/waveforms.py:497)) computes
it as `internal_clock_hz / (2.0 * clock_divider)` whenever
`clock_divider > 0`; **deliberately left unset (not guessed at) when
`clock_divider` truncates to 0** -- this codebase has no confirmed
real-hardware behavior for a zero divider to derive an
achieved-frequency formula from, and this project's own established
convention is to flag an unconfirmed case rather than invent a
plausible-looking number for it (same discipline as the syringe-stroke
Pattern (d) cautionary tale in `docs/hardware_safety_patterns.md`).
`_settings_properties()`
([workflows.py:231-244](src/thermo_acoustic/workflows.py:231)) gained
`DOFreqActual` alongside the existing `DOFreq` (both recorded, not one
replacing the other) -- no `application.py` changes needed here, since
`config_do_clock_special()` mutates the same `DoConfig` object
`experiment.do_clock_settings` references, and Finding A's existing
second `save_settings()` call (already running after
`config_do_clock_special()`) captures the result with no new ordering
fix required.

**Tests (all in [tests/test_application.py](tests/test_application.py)):**
`test_configure_exposure_time_returns_real_applied_value_not_requested`
(a quantizing fake DCAM handle that returns `requested + 0.1ms`, not an
exact echo); `test_run_experiment2_records_real_applied_exposure_in_final_tdms`
(end-to-end through `run_experiment2()`, confirms both the facade's
`self.exposure_ms` and the final `data.tdms`'s `ExposureTime`);
`test_configure_do_records_achieved_frequency_after_integer_divider_rounding`
(33.0 Hz requested against a fixed 100.0 Hz fake internal clock
truncates to 50.0 Hz achieved -- a stark, unambiguous gap, not
rounding-noise-level); `test_configure_do_leaves_achieved_frequency_none_when_no_clock_requested`;
`test_run_experiment2_records_do_clock_achieved_frequency_in_final_tdms`
(end-to-end, confirms both `DOFreq` and `DOFreqActual` land correctly
in the final `data.tdms`). **Verified every one of the five tests
actually catches its specific regression**, same discipline as
Findings A-D: reverted each of the four independent fix points (DCAM
backend return value, facade wiring, `application.py` re-snapshot,
`configure_do()`'s achieved-frequency computation) one at a time and
re-ran the relevant test(s) alone -- all failed with the exact expected
symptom each time; restored immediately after each check.

**Files touched:** [hamamatsu_dcam.py](src/thermo_acoustic/hamamatsu_dcam.py)
(`configure_exposure_time()` returns real applied value),
[instruments.py](src/thermo_acoustic/instruments.py) (`CameraBackend`
Protocol + `HamamatsuCamera.configure_exposure_time()`),
[application.py](src/thermo_acoustic/application.py) (`run_experiment2()`,
captures + re-records applied exposure), [ad2.py](src/thermo_acoustic/ad2.py)
(`DoSingleChannelConfig.achieved_clock_frequency_hz`),
[waveforms.py](src/thermo_acoustic/waveforms.py) (`configure_do()` computes
it), [workflows.py](src/thermo_acoustic/workflows.py) (`DOFreqActual`),
[tests/test_application.py](tests/test_application.py) (5 new tests),
[tests/test_full_flow_dry_run.py](tests/test_full_flow_dry_run.py)
(`FakeCamera.configure_exposure_time()` now returns the value).

**Verification:** tested -- full `tests/` suite green, 281/281. Not
hardware-verified -- exercised against fakes/quantizing test doubles
only; DCAM's own real exposure-quantization magnitude and the AD2's
own real internal digital-out clock frequency have not been
independently re-confirmed against physical hardware in this session
(the underlying `read_readout_time()`/`digital_out_internal_clock_info()`
SDK calls themselves are unchanged and were already exercised in prior
real-hardware sessions).

### Session 52 continued, Finding F: HamamatsuDcamBackend.close() silently swallowed cleanup failures

**The gap.** `close()` ([hamamatsu_dcam.py:377-408](src/thermo_acoustic/hamamatsu_dcam.py:377),
pre-fix): both `_stop_capture_if_active()` and `buf_release()` failures
were caught with a bare `except Exception: pass` -- no logging at all,
unlike every other cleanup path in this codebase
(`Application._cleanup_instruments` logs; `QmixPumpBackend.close()`/
`PiezoStage.disconnect()` both re-raise with details). If the camera
genuinely failed to stop capture or release its buffer during
`Application.cleanup()`, the operator would see a clean "System Not
Initialized" with zero indication the device might still be in an
inconsistent internal state -- only surfacing later as a confusing,
seemingly unrelated re-Initialize failure with no link back to the
real cause.

**Fix.** Both `except` blocks now call `logger.error(...)`, naming
which step failed and the real exception -- **not** re-raised, since
this remains an intentionally best-effort cleanup path (matching this
project's own established distinction: `_cleanup_instruments` itself
already tolerates per-device cleanup failures without stopping overall
cleanup; only the silence inside this one method is fixed, not its
best-effort nature).

**Test.** `test_hamamatsu_close_logs_swallowed_cleanup_errors_instead_of_silently_passing`
([tests/test_application.py](tests/test_application.py)) -- forces
both cleanup steps to raise independently (`_stop_capture_if_active()`
monkeypatched at the class level via `monkeypatch.setattr`, since
`HamamatsuDcamBackend` is `@dataclass(slots=True)` and doesn't allow
arbitrary instance-attribute assignment; `buf_release()` patched
directly on the fake instance), confirms **both** distinct error
messages are logged (not just one), and confirms `close()` itself still
completes without raising. **Verified this test actually catches the
regression**, same discipline as every other finding this session:
temporarily restored the bare `pass` and re-ran the test alone -- failed
(`assert False` on the first logged-message check, empty `caplog.records`);
restored the fix immediately after.

**Files touched:** [hamamatsu_dcam.py](src/thermo_acoustic/hamamatsu_dcam.py)
(`close()`, 2 `pass` statements replaced with `logger.error(...)` calls),
[tests/test_application.py](tests/test_application.py) (1 new test).

**Verification:** tested -- full `tests/` suite green, 282/282. Not
hardware-verified -- logging-only change to an already-best-effort
cleanup path; no behavior change to what `close()` actually does or
returns.

### Session 52 continued, Finding G: PriorZMotor.read_position() silently returned stale data on a parse failure

**The gap.** `read_position()` ([instruments.py:804-811](src/thermo_acoustic/instruments.py:804),
pre-fix): if the serial response couldn't be parsed as a float, the
`ValueError` was swallowed with a bare `except ValueError: pass`,
returning the last-known `self.position` with no indication the read
had actually failed -- a garbled/partial serial response was
indistinguishable from "position genuinely unchanged". Confirmed via
grep that this method currently has **zero callers anywhere in
`src/`** -- lower real-world exposure than the other six findings, and
consistent with this whole hardware path being separately flagged
legacy/obsolete elsewhere in this project's docs (current Z hardware is
the Thorlabs piezo, `thorlabs_piezo.py`, Sessions 45-50) -- included
for completeness of the requested `instruments.py` sweep, not because
it's reachable from `run_experiment2()` today.

**Fix.** `instruments.py` gained a module-level `logger` (it had none
before -- `import logging` + `logger = logging.getLogger(__name__)`,
matching the existing pattern already used in `application.py`/
`hamamatsu_dcam.py`). The `except ValueError:` branch now calls
`logger.error(...)`, naming the unparseable response, the serial
resource, and the stale value being returned instead -- **logged, not
raised**, since (a) no dedicated `PriorZMotorError` class exists for
this device and creating one solely for this fix would be
disproportionate for an already-legacy, currently-uncalled path, and
(b) there is no current caller whose behavior this could safely change
by raising instead.

**Test.** `test_prior_zmotor_read_position_logs_and_keeps_last_known_on_unparseable_response`
([tests/test_application.py](tests/test_application.py)) -- confirms
both halves explicitly: the stale value really is still returned
(existing, correct fallback behavior, deliberately unchanged) **and**
the failure is now logged with the actual bad response and resource
name in the message (the real gap this finding closes). **Verified
this test actually catches the regression**, same discipline as every
other finding this session: temporarily restored the bare `pass` and
re-ran the test alone -- failed (`assert False`, empty
`caplog.records`); restored the fix immediately after.

**Files touched:** [instruments.py](src/thermo_acoustic/instruments.py)
(module-level `logger` added, `read_position()`'s except branch),
[tests/test_application.py](tests/test_application.py) (1 new test).

**Verification:** tested -- full `tests/` suite green, 283/283. Not
hardware-verified -- logging-only change to a currently-uncalled,
already-legacy-flagged code path; no behavior change to what
`read_position()` returns.

**All 7 findings from this session's silent-failure/data-integrity
sweep (A-G) are now implemented, individually tested (with each test
independently verified to actually catch its specific regression, not
just pass), and logged separately. Full `tests/` suite green, 283/283.
TEC's own uncommitted diff (`tec.py`, and the TEC-authored hunks within
`application.py`/`hardware_factory.py`/`qt_ui.py`/`qt_ui_v2.py`/
`workflows.py` + their tests) was never opened for editing at any point
across all 7 findings, confirmed via `git status`/`git diff` hunk
inspection before and after each change. Not committed, per
instruction -- awaiting review.**

**Update: committed.** All 7 findings landed as commit `a59aa1f`
("Fix seven silent-failure and data-integrity gaps in
run_experiment2()'s data.tdms record"), with `application.py`/
`workflows.py` hunk-separated from TEC's own uncommitted diff before
staging (verified via reconstructed-content diffing, not assumed --
`git diff --cached` confirmed zero TEC-related lines, `git diff`
confirmed the working tree still carried exactly TEC's untouched
content afterward). `docs/known_open_items.md`/
`docs/hardware_safety_patterns.md` (from the separate consolidation
task that preceded this session) landed separately as commit `86442bc`.

### Session 53 -- Full simulated end-to-end dry-run verification (Initialize -> multi-repeat series -> shutdown), one Priority-1-class finding fixed

**Context: every hardware module had been verified independently
(pump, valve, AD2, camera, piezo) across this project's history, but no
single pass had run the actual combined `run_experiment2()` sequence
with all modules interacting together end-to-end**, checking for
resource conflicts, timing collisions, or state leaking between
modules that unit-level tests can't catch by construction. Commit
`a59aa1f`'s seven data-integrity fixes made this newly meaningful: a
dry-run's resulting `data.tdms` should now actually be trustworthy, not
just "the run completed."

**Existing simulated path found and used, not built from scratch.**
`hardware_factory.build_hardware_bundle()` + `apply_hardware_bundle()`
is the real, already-existing production wiring -- the exact code path
`qt_ui.py`'s Initialize button calls when all four sim checkboxes are
checked (the documented safe default). It builds `SimulatedAD2Sdk`,
`HamamatsuCamera(simulate=True)`, `CetoniPump(simulate=True)`,
`Valve(simulate=True)` (all `backend=None`, no real SDK/DLL touched)
plus a disabled `TecController` -- confirmed a safe no-op by *reading*
`tec.py` (not editing it): `TecController.initialize()`/`cleanup()`
both short-circuit cleanly when `enabled=False`, and `build_hardware_bundle()`
always constructs a real `SimulatedTecBackend()` regardless of
`tec_enabled`, so including it in the wiring is inert.

**What was run.** A standalone scratchpad script (not committed to the
repo -- a one-off verification tool, not permanent test infrastructure)
drove `Application` through `initialize() -> multi-repeat series ->
cleanup() -> re-initialize()`, against the real filesystem and the
genuinely-installed `nptdms` 1.11.0 package (not the pytest suite's
fake), in four scenarios: (1) 3-repeat series, flush enabled; (2)
2-repeat series, flush disabled, fresh `Application`; (3) two
back-to-back series on the *same* `Application` instance with no
`cleanup()` between them, probing cross-series state leakage; (4) a
3-repeat series with `stop_fired` set mid-series, directly re-testing
Session 32's own abort-stops-queuing fix and the same *class* of bug
Finding A found (an implicit ordering assumption).

**Result: pass, with one finding.** All 9 repeats across the four
scenarios completed (`ExperimentComplete`), zero entries in
`app.errors`, no thread leakage (`threading.enumerate()` checked
independently before/after `cleanup()` in *every* one of the four
scenarios, not just the first two -- closing a gap this verification's
own first pass had left open and explicitly disclosed), re-`initialize()`
immediately after `cleanup()` succeeded cleanly, mid-series abort
stopped exactly after repeat 1 with `repeat_002/` never created. All
seven Finding A-G fixes verified correct end-to-end: `SimAD2`/
`SimCamera`/`SimPump`/`SimValve` read `True` throughout, `FlushCompleted`
correctly `True`/`""` depending on whether flush ran, `TriggerSource`/
`MasterPulse*` fields present and correct, image/timestamp channel
counts matched frame counts. (`WFGOutOfRangeCh1=False` and
`DOFreqActual=""` are the *expected* simulated-mode values --
`SimulatedAD2Sdk` never calls the real clamp/divider logic -- not gaps.)

**The one finding: `Application.flush()` validated flush volume against
the syringe's total *capacity*, never against how much liquid is
actually loaded right now.** [application.py:345-350](src/thermo_acoustic/application.py:345)
(pre-fix) only checked `flush_volume_ml > syringe_volume_ml` (default
60mL) before computing `new_fill_level = self.pump.fill_level -
settings.flush_volume_ml` and pushing it straight to `set_fill_level()`
-- nothing checked the result wasn't negative. `refill()`/
`reference_move()` are confirmed manual-only, never called from the
automated path (Session 21), so a real operator who starts a series
before refilling -- or whose fill level is already low from a prior
series -- would previously get a silent negative `pump.fill_level` with
no error, no warning, and a completely normal-looking
`"ExperimentComplete"`/`data.tdms`. On real hardware this reaches
`QmixPumpBackend.set_fill_level()`, which passes the value straight to
the real Qmix SDK unconditionally -- whether the real firmware itself
rejects a negative absolute fill-level target gracefully is unconfirmed
in this repo.
- **Reproduction (no fix needed to see it):**
  ```python
  app = Application(pump=CetoniPump(simulate=True))  # fill_level defaults to 0.0
  app.flush(FlushSettings(flush_flowrate=200.0, flush_volume_ml=0.05, wait_after_flush_s=0.0))
  assert app.pump.fill_level == -0.05  # negative, no error, no warning
  ```
- **Why no existing unit test caught this:** the one test exercising
  `flush()`'s happy path (`test_flush_sets_valve_and_status`) explicitly
  pre-sets `app.pump.fill_level = 60.0` before calling `flush()` --
  sidestepping the very default state (`fill_level=0.0`) this end-to-end
  dry run started from and exposed directly.

**User instruction: treat this with the same priority as the earlier
syringe-stroke hardware-safety work (commit `23e17d5`), not as a
lower-priority data-integrity note -- fixed in this same session, not
deferred.**

**Fix, classified per `docs/hardware_safety_patterns.md`'s own decision
tree, not guessed at.** This case doesn't fit any of the four existing
patterns exactly -- it's neither a live device query (Patterns
(a)/(b)) nor a fixed vendor-manual ceiling (Pattern (d)): the "limit"
is already-known in-memory application state (`self.pump.fill_level`,
tracked in Python, no vendor research or device round trip needed).
**But the reject-vs-clamp choice still follows the same reasoning as
Patterns (c)/(d):** clamping the flush to whatever's actually available
would itself be a data-integrity bug, since the `FlushVolume` value
already recorded in `data.tdms` (written by the earlier `save_settings()`
calls, before `flush()` ever runs) would then silently no longer match
what was actually drawn. [application.py:345-374](src/thermo_acoustic/application.py:345):
new check, `settings.flush_volume_ml > self.pump.fill_level`, raises
`ValueError` naming both values and instructing "refill the syringe
first" -- placed before any valve/pump call, same as the existing
capacity check right above it, so a rejected flush leaves `fill_level`
and `valve.position` completely untouched.

**Test:** `test_flush_rejects_volume_exceeding_current_fill_level`
([tests/test_application.py](tests/test_application.py)) -- deliberately
starts from `CetoniPump()`'s real default (`fill_level=0.0`), not a
pre-set value (asserted explicitly, so the test can't silently start
from the wrong state), confirms the `ValueError`, and confirms
`fill_level`/`valve.position` are both unchanged after the rejection
(rejected before any hardware call, not after one that partially ran).
`test_flush_accepts_volume_exactly_at_current_fill_level` covers the
inclusive boundary (flushing exactly what's loaded, down to 0.0
remaining, is physically valid). **Verified the regression test
actually catches the bug**, same discipline as Findings A-G:
temporarily removed the new check and re-ran the rejection test alone
-- failed (`DID NOT RAISE`); restored immediately after.

**One existing test required updating, not because it was wrong, but
because it relied on the now-closed gap without realizing it.**
`test_run_experiment2_records_flush_success_in_final_tdms` (Finding D,
this session) pre-set `app.pump.fill_level = 1.0` while flushing 6.0 mL
-- passed before this fix only because nothing checked the mismatch.
Updated to `fill_level = 60.0` (comfortably sufficient), which is what
the test's own intent (a genuinely successful flush) already required.

**Files touched:** [application.py](src/thermo_acoustic/application.py)
(`flush()`, new pre-flight check), [tests/test_application.py](tests/test_application.py)
(2 new tests, 1 existing test's setup corrected).

**Verification:** tested -- full `tests/` suite green, 285/285 (up from
283; 2 new tests), modulo the same already-documented (Session 41/42/48)
offscreen-Qt/Shiboken flakiness in `test_qt_ui_v2.py` (a different
single test failed on 2 of 3 full-suite runs during verification,
always passing cleanly alone or as part of just that file) -- confirmed
via `git diff` that nothing this session touches `qt_ui_v2.py` at all.
Re-ran the full simulated end-to-end dry-run script (all four
scenarios, including the two independently-verified thread-leak checks)
against the fixed code -- clean pass, `pump.fill_level` now correctly
`0.95` (not negative) after a `1.0 -> flush 0.05` sequence. **Not
hardware-verified -- flagged as a separate follow-up, same as commit
`23e17d5`'s own precedent for items needing physical verification:
whether the real Qmix/neMESYS firmware itself rejects a negative
absolute fill-level target gracefully (as opposed to Python now
catching it first) has not been confirmed against real hardware and
requires bench access.** **Update:** committed -- confirmed cleanly
separable (its own isolated hunk, not line-entangled) from TEC's own
uncommitted diff in the same file before staging, same
reconstruction-and-verify discipline as every other hunk-separated
commit this project has made.

### Session 54 -- Real-hardware verification, Item 1: valve default COM port was wrong (COM6 -> COM5), a standing documentation error

**Found while beginning real-hardware verification of Session 53's
findings.** `Application.initialize()` against real hardware
(AD2/camera/pump enabled, real backends) succeeded through AD2, camera,
and pump, then failed at the valve: `ValveError: Valve did not respond
on COM6`. Investigated properly rather than assumed a hardware fault:
1. **Ruled out port contention or a hidden/undiscovered port.** A
   read-only status-query probe (`S\r`, the documented handshake, no
   position-changing command) against every COM port Windows currently
   exposes (`serial.tools.list_ports.comports()` and
   `Get-PnpDevice -Class Ports`, cross-checked against each other, both
   returning the identical 4-port set: COM1/4/5/6) got silence on all
   four at a 1.0s timeout. No competing process held any port
   (`Get-Process` clean).
2. **Traced the real USB topology** (`DEVPKEY_Device_Parent` walk from
   each COM port's PnP instance up to the root hub) rather than
   guessing: COM4/COM5/COM6's FTDI adapters, the AD2's own FTDI
   adapter, the CETONI VCI4 pump-CAN interface, and the piezo's APT
   USB device are all physically riding the same two-tier USB hub
   assembly (confirmed by the user as a real single multi-port
   hub/dock, not three independently-cabled adapters as originally
   assumed) -- explaining why an earlier physical unplug test (part of
   this same investigation, not described further here) took all three
   COM ports down simultaneously.
3. **Retried the status query with a longer timeout (3.0s) and
   line-ending variants** (`\r` documented, `\r\n` alternate, no
   terminator) specifically to distinguish a genuine hardware fault
   from a protocol-level mismatch or a device still settling after a
   power-cycle: **COM5 responded correctly** (`S\r` -> `01\r`, and
   `S\r\n` -> `01\r`; no response to a bare `S` with no terminator,
   consistent with the device genuinely requiring a real line
   terminator, not evidence of a different protocol). `01` parses
   cleanly under the existing `Valve._apply_status_response()` logic as
   position 1 (Open), `status_note="confirmed"` -- a well-formed,
   correct reply, not a marginal/garbled one. COM4 and COM6 remained
   silent across every timeout/line-ending combination tried.
4. **Confirmed independently by the user as a standing issue, not
   tonight's artifact**: COM5 had already been identified as the
   valve's real port in a prior session too. This matches
   `docs/labview_migration_completeness_audit.md`'s own pre-existing
   (and previously never acted on) note that "LabVIEW screenshot
   candidate mentions COM5" -- the correct port was hinted at in this
   project's own documentation long before this session, just never
   independently verified or corrected in the actual default.

**This is the same class of mistake as the Session 51 AD2 wrong-VID
investigation** (a real, present, working device, looked for under the
wrong identifier) -- not a hardware failure, and not this session's own
artifact.

**Fix.** `Valve.visa_resource` default
([instruments.py:698-706](src/thermo_acoustic/instruments.py:698)):
`"COM6"` -> `"COM5"`, cited in a code comment. `qt_ui.py`'s matching
UI default ([qt_ui.py:525](src/thermo_acoustic/qt_ui.py:525)):
`QLineEdit("COM6")` -> `QLineEdit("COM5")`. Docs updated to match:
`docs/current_workflow_audit.md`'s "Valve COM/position mapping" row
(now "COM port confirmed" instead of "Unresolved"),
`docs/labview_migration_completeness_audit.md`'s item 5 (marked
resolved, cross-referencing its own prior COM5 hint),
`hardware_tests/README.md`'s serial-resources line,
`hardware_tests/test_serial_discovery.py`'s `DEFAULT_PORTS` dict, and
`hardware_tests/test_valve_command_probe.py`'s two usage-example
strings (illustrative only, not enforced defaults).

**Deliberately left unchanged, per explicit scope, not overlooked:**
`hardware_tests/test_real_workflow_smoke.py` and its own
`tests/test_real_workflow_smoke_plan.py` suite (~10 `COM6` references)
-- this script already requires an *explicit* `--valve-port` choice
(`{"COM5", "COM6"}`, both already valid) for its real-full-workflow
mode, so there is no silent-stale-default risk there the way there was
in `instruments.py`'s dataclass default; changing its own internal
default would additionally require updating roughly a dozen test
assertions in a parallel file, out of proportion for what the user
asked. `src/thermo_acoustic/ui.py` (confirmed dead since Session 7,
592 lines, no importers) left untouched, matching this project's own
established convention (Session 36) of not selectively editing pieces
of that file. Every `tests/test_application.py`/
`test_hardware_factory.py`/`test_qt_ui_hardware_settings.py`/
`test_qt_ui_v2.py` fixture that passes `visa_resource`/`valve_resource`
explicitly (rather than relying on the dataclass default) needed no
change -- confirmed by reading each one, not assumed.

**One test genuinely depended on the old default and needed
updating**, not a bug in the test: `test_valve_and_prior_backend_commands`
constructs a bare `Valve(backend=..., command_position_1=...,
command_position_2=...)` with no explicit `visa_resource`, asserting
the resulting `("write", "OPEN COM6")` command -- updated to
`"OPEN COM5"`.

**COM4 and COM6's real identity remains deliberately unresolved, per
explicit instruction.** Both are confirmed present, confirmed silent to
the valve's own protocol, and cannot be tested against a TEC/Meerstetter
protocol because none exists anywhere in this repository (grepped
exhaustively: `tec.py` and every doc mentioning MeCom all state the
real register map/protocol was never implemented, by explicit design,
"to avoid inventing hardware commands" without a reviewed client) --
inventing one from outside knowledge to fire at real hardware was
correctly declined, per instruction. This stays a genuine open item,
not chased further.

**Files touched:** [instruments.py](src/thermo_acoustic/instruments.py),
[qt_ui.py](src/thermo_acoustic/qt_ui.py),
[docs/current_workflow_audit.md](docs/current_workflow_audit.md),
[docs/labview_migration_completeness_audit.md](docs/labview_migration_completeness_audit.md),
[hardware_tests/README.md](hardware_tests/README.md),
[hardware_tests/test_serial_discovery.py](hardware_tests/test_serial_discovery.py),
[hardware_tests/test_valve_command_probe.py](hardware_tests/test_valve_command_probe.py),
[tests/test_application.py](tests/test_application.py) (1 existing
test's assertion corrected).

**Verification:** tested -- full `tests/` suite green, 285/285 (same
count as before; no test added or removed, one assertion corrected).
Real hardware: the corrected port itself is real-hardware-confirmed
(the status-query response described above *is* the verification, not
a downstream consequence of it). TEC files not touched -- confirmed via
`git diff` before and after. Not committed, per instruction --
real-hardware verification of the rest of Session 53's findings
continues below.

### Session 54 continued: full real-hardware verification pass (closing the loop on Session 53's simulated dry-run)

**Context.** Every hardware module had been verified independently
across this project's history (pump, valve, AD2, camera, piezo), but
no single pass had run the actual combined `run_experiment2()` sequence
with all modules interacting together end-to-end on real hardware.
Session 53's simulated dry-run covered this class of scenario in
simulation; this session re-ran the same class of scenarios against
real hardware, plus the flush() boundary question Session 53 left
formally unconfirmed. User explicitly authorized real experiment
sequences (not just probe/identify calls) on pump, valve, AD2, camera,
and piezo for this session.

**Result: all three scenario groups PASS.** Full detail below; a
complete, unfiltered issue log (kept per explicit instruction to
over-collect, not filter for severity) was also produced this session
and is summarized here.

**Scenario 1 -- full experiment sequence on real hardware: PASS.**
Real `Application.initialize()` (AD2/camera/pump/valve all real, TEC
disabled/simulated and untouched) succeeded cleanly once the valve
port fix above was in place. A 3-repeat series (conservative
parameters: 15ms exposure, 2 frames/repeat, AD2 Ch1 1000Hz/0.3V/0.2s
run -- a low-amplitude test signal, not a real acoustic drive
configuration -- flush 0.01ml/repeat @ 200 uL/min, matching Session
31-33's own established real-hardware flow-rate convention) completed
all 3 repeats (`ExperimentComplete`), zero `app.errors`, clean
`cleanup()` with **zero thread leak** (`threading.enumerate()` checked
before/after), and a clean re-`initialize()` immediately after
`cleanup()`. Real `data.tdms` metadata confirmed every relevant
Session 52/53 fix working correctly on real hardware, not just in
simulation: `SimAD2=False`/`SimCamera=False`/`SimPump=False`/
`SimValve=False` for all 3 repeats (Finding B), `FlushCompleted=True`
for all 3 (Finding D), `WFGOutOfRangeCh1=False` (0.3V/1000Hz correctly
not flagged, well within the real AD2's range). **Notably,
`ExposureTime=15.00025`, not exactly the requested `15.0`** -- real
DCAM exposure quantization, correctly captured as the actually-applied
value rather than echoed back (Finding E confirmed working on real
hardware, not just against the quantizing fake used in its own unit
test). A separate 3-repeat series with `fire_stop_event()` called
after repeat 1 (mirroring `qt_ui.py`'s `_abort()`) correctly stopped
before repeat 2 started -- `repeat_002`/`repeat_003` folders never
created, 2 repeats correctly left in the queue -- re-confirming Session
32's fix on real hardware in this session, not just relying on Session
31-33's own prior confirmation.

**Scenario 2 -- flush() boundary check against real Qmix firmware:
PASS, answers Session 53's open question.** Real syringe confirmed
empty first (`get_fill_level()` -> `0.0`ml, read directly via the raw
Qmix SDK, not the Python-tracked value), then filled to a known,
controlled `~0.10`ml via a small real motion (`200` uL/min, matching
the same established convention). **Reject path:** requested `0.15`ml
against the real `0.10`ml fill level -- `ValueError` raised; real
`get_fill_level()` readback identical before and after
(`0.09999509429297194` both times); real valve position identical
before and after (`1` both times) -- proves the real Qmix SDK's own
`set_fill_level()` call was never reached and the valve was never
touched, not just that an exception happened to fire. **Accept path:**
requested `0.05`ml (within the same `0.10`ml level) -- succeeded; real
fill level genuinely dropped from `0.09999509429297194` to
`0.04999482006952973`, a real, measured decrease matching the request;
valve ended at position 2 (Closed), `flush()`'s normal end state. This
makes the original open question ("does the real Qmix/neMESYS firmware
itself reject a negative absolute fill-level target gracefully?") moot
for any request that goes through `Application.flush()` normally -- the
app-level guard now categorically prevents that scenario from ever
reaching the SDK. The firmware's own behavior in a hypothetically
bypassed case remains formally unconfirmed by design (deliberately not
attempted, since doing so would require routing around the new safety
guard).

**Scenario 3 -- Piezo Z-Scan UI end-to-end on real hardware: PASS,
first time ever through the UI, not just the CLI.** Session 47/48
verified `piezo_zscan.py`'s CLI directly; the UI wrapper
(`qt_ui.py`'s Z-Scan tab -- Start button, the real `QMessageBox`
ClosedLoop confirmation, Abort button, `_zscan_abort_requested` flag)
had never been exercised against physical hardware before this
session (Session 50's own entry says so explicitly). Driven via
genuine `QTest.mouseClick()` on the real `QPushButton` widgets (not
calling `_start_zscan()`/`_abort_zscan()` as bare Python method
calls), with `QMessageBox.question` monkeypatched to auto-answer Yes
(this project's own established test-suite technique for driving
modal dialogs programmatically -- the real ClosedLoop-confirmation
*logic* still runs for real; only the blocking modal wait itself is
scripted, since no interactive human was available to click it).
**Full scan**, parameters matching Session 48's own already-verified
real-hardware example exactly (Z 200-210um, step 2um, exposure 20ms):
`Query Piezo Range` click correctly populated the real range (`0.00 -
450.00 um`, matching Session 45/46's known real MaxTravel); `Start
Z-Scan` click completed all 6 real frames (`z_0200.31um.tif` ...
`z_0210.04um.tif` -- real measured closed-loop positions with small
settling residuals, exactly as designed); status `"Z-scan complete: 6
frames written"`; zero errors. **Mid-scan abort**: `Start Z-Scan`
click, waited for real frames to land on disk, then a real `Abort
Z-Scan` click -- scan correctly stopped after 3 of 6 positions (the
in-flight position at abort-click time was allowed to finish, matching
Session 47's documented `should_abort` check timing), and
`app.errors` recorded the exact "PARTIAL" wording designed in Session
47 (`"Z-scan aborted at position 4/6 (target=206.00 um). 3 of 6
positions completed successfully before this abort -- this is a
PARTIAL, incomplete stack, not silently treated as done."`) -- the
first time that exact message has ever been produced by a real Abort
click on real hardware, not just a unit test. **Residual gap, disclosed
not glossed over:** the piezo was already in `CloseLoop` mode both
runs this session, so neither the dialog's "confirm and switch" nor its
"decline" branch was actually exercised against real hardware -- the
same limitation Session 48 already documented for its own CLI run.
Still open for a future session where the device happens to start in
`OpenLoop`.

**Issue log -- everything observed this session, not filtered for
severity, per explicit instruction to over-collect.** Four items found;
two already addressed (the valve port, above), two deliberately left
open per "verify first, fix later," to become dedicated follow-up
tasks:

1. **Valve default COM port was wrong (COM6 -> COM5)** -- covered in
   the entry immediately above this one.
2. **`SerialTextCommandBackend.query()` uses `readline()`, which splits
   on `\n`, but the valve's real protocol only ever sends `\r` -- the
   highest-value finding of this session, per explicit user framing.**
   Discovered while diagnosing why `Application.initialize()` still
   failed on the *correct* port (COM5) with the class's default
   `timeout_s=1.0`. Direct timing characterization (`S\r` query,
   `timeout=5.0`, 3 repeated attempts) showed the device responds
   correctly and consistently (`b'01\r'` every time) but **each call
   takes the full configured timeout window to return** (~5.02-5.03s
   against a 5.0s timeout, every time) -- not "however long the device
   actually takes." Root cause: `query()`
   ([instruments.py](src/thermo_acoustic/instruments.py)) calls
   `self.port.readline()`, which defaults to splitting on `\n` (LF).
   This device's real protocol (and this codebase's own `line_ending =
   "\r"` convention used for *writing*) only ever terminates a
   response with `\r` (CR), never `\n` -- so `readline()` never sees
   the terminator it's actually looking for and always blocks for the
   entire timeout before returning whatever is in the buffer at that
   point, rather than returning promptly once the real response has
   fully arrived. **Affects every caller of
   `SerialTextCommandBackend.query()`**, not just this one probe --
   `Valve.initialize()`, `Valve._apply_status_response()`'s call
   sites, and `Valve.wait_until_ready()`'s own poll loop all go
   through this same method. `wait_until_ready()`'s poll loop has
   likely been silently paying the full per-call timeout cost on every
   single iteration for its entire existence, not occasionally --
   making its real elapsed time before giving up likely far longer
   than its own nominal `timeout_s` parameter would suggest. May
   retroactively explain prior "valve seems slow" observations from
   earlier real-hardware sessions that were never root-caused before
   now. **Not fixed this session, per explicit instruction** -- a
   session-local workaround (a separately-constructed `Valve` with
   `SerialTextCommandBackend(timeout_s=5.0)`, not touching the shared
   class default) was used to continue the rest of this session's
   real-hardware work. Becomes the highest-priority dedicated follow-up
   task.
3. **No fill-level readback/sync path anywhere in this codebase --
   `pump.fill_level` always starts at `0.0` in a fresh process,
   regardless of the real device's actual current state.** Discovered
   directly: starting the full-sequence test (Scenario 1) in a fresh
   process with the syringe genuinely at `~0.05`ml real fill level
   (confirmed moments earlier by Scenario 2's own real SDK readback),
   `Application.flush()`'s new guard (Session 53) rejected a
   perfectly legitimate `0.01`ml flush request, because the
   Python-tracked value was `0.0` (the dataclass default for a
   brand-new `CetoniPump` instance with no memory of the prior
   process's real motion). Root cause confirmed by reading the code:
   `CetoniPump.fill_level` is only ever updated by this project's own
   code calling `set_fill_level()`/`refill()`/`empty()` through that
   exact object; nothing anywhere calls the real SDK's own
   `get_fill_level()` (confirmed to exist and work, used directly for
   this session's own Scenario 2 verification) to sync the tracked
   value from reality. `refill()` is the only existing way to set a
   known-real value, but it always commands a full refill to the
   syringe's maximum capacity, not a "read what's actually there"
   query. **Real-world consequence:** any app restart while the
   physical syringe genuinely still has partial volume loaded now
   actively blocks legitimate flushes (previously the same mismatch
   was silent and could under/overshoot; the Session 53 fix makes the
   *absence* of a sync path newly consequential, not the fix itself
   wrong). **Not fixed this session** -- worked around for this
   session's own testing by manually reading `get_fill_level()` and
   assigning it to `app.pump.fill_level` before starting the series.
   Fails safe (rejects rather than silently mis-flushing), so left as
   a follow-up candidate, not a safety stop.
4. **Environment gotcha, not a code bug:** any piezo-touching
   real-hardware script needs the `exp_ctrl` conda environment
   specifically (`C:\Users\Lab user\.conda\envs\exp_ctrl`), not the
   base/system Python -- confirmed via `conda env list`. Session 45
   had installed `pythonnet` into this environment specifically;
   pump/valve/AD2/camera scripts work fine under base Python since
   they don't need pythonnet, but the piezo's Kinesis .NET interop
   does. This isn't documented anywhere obvious in this repo and cost
   real diagnostic time this session (`ImportError`-style failure,
   `pythonnet is not installed in this environment`, on an otherwise
   correctly-written script). Flagged as a documentation follow-up.

**Files touched this pass:** none beyond the valve-port-fix entry
above -- this entry is verification/diagnostic only, no further code
changes. Real-hardware run artifacts (TIFFs, `data.tdms` files) were
written to temporary directories outside the repo and are not part of
this repo's own tracked/gitignored output conventions.

**Verification:** real hardware throughout, described in full above --
this entry *is* the verification for Scenarios 1-3. TEC files/hunks
confirmed untouched via `git diff` before and after every step,
consistent with every other entry this session. Not committed, per
instruction. Issues 2-4 above remain open, prioritized for dedicated
follow-up sessions.

### Session 55 -- Fixed SerialTextCommandBackend.query()'s readline()/\r timing bug (Session 54's top follow-up)

**The bug, precisely.** `query()` called `self.port.readline()`, which
(per pyserial's own generic default implementation) only stops early on
a literal `b"\n"` byte or an empty `read()`. This backend's own `write()`
already terminates every outgoing command with `self.line_ending`
(`"\r"` by default) -- and the valve, the only real device confirmed to
talk to this backend, only ever terminates its responses the same way.
Since `readline()` was looking for the wrong byte, every call drained
the correct `"\r"`-terminated response instantly into its internal
buffer, then blocked for the *entire* remaining `timeout_s` on the next
read waiting for a `"\n"` that was never coming, before finally giving
up and returning the (correct) bytes it already had. Real-hardware
timing characterization (Session 54) had already caught the symptom
(~5.02s response time against a 5.0s `timeout_s`, repeatably) without
yet fixing the cause.

**Confirmed the installed pyserial version before assuming an API,
per instruction.** `pip show pyserial` -> `3.5`, and
`inspect.getsource(serial.Serial.read_until)` against the actually
installed package (not documentation, not memory) confirmed this
version's `read_until(expected=b"\n", size=None)` signature -- the
`expected` keyword is correct for 3.5+; pre-3.5 used `terminator`
instead, a real documented breaking rename, so this was worth checking
rather than assuming.

**Fix:** `query()` now calls
`self.port.read_until(expected=self.line_ending.encode("ascii"))`
instead of `self.port.readline()` -- reading until the exact same
terminator `write()` already sends with, taken from the instance's own
`line_ending` field rather than a newly hardcoded `b"\r"`, so the two
stay in sync if `line_ending` is ever changed for a different device.

**Searched for the same bug pattern elsewhere before assuming this was
the only call site**, per instruction: `readline(` appears exactly once
in `src/`, this one call site
([instruments.py](src/thermo_acoustic/instruments.py)). Two standalone
scratch probe scripts in `hardware_tests/`
(`test_valve_command_probe.py`, `test_valve_command_probe_v2.py`) read
raw serial responses via `ser.read(64)` instead -- a related but
distinct pattern (blocks for the timeout waiting for a fixed byte count
rather than the wrong terminator), and out of scope here since they're
one-off manual diagnostic scripts, not part of the production backend.

**New regression test file, [tests/test_instruments.py](tests/test_instruments.py)**
(no dedicated test file for `instruments.py` existed before this).
`_FakeCarriageReturnOnlyPort` reimplements pyserial 3.5's real
`read_until()` algorithm (confirmed via the same `inspect.getsource`
call above) and a `readline()` that faithfully reproduces the real,
hardware-confirmed failure mode: drain whatever's buffered, then block
the full configured timeout on the next `read()` before giving up.
Two tests: `test_query_returns_as_soon_as_carriage_return_terminator_arrives`
proves the fixed `query()` returns in well under the configured timeout
once the `"\r"`-terminated response is available; `test_readline_based_read_would_have_blocked_for_the_full_timeout`
directly exercises the fake's `readline()` (the exact call the old code
made) to prove it reproduces the real slow-path behavior on its own,
independent of the fix.

**Verified the regression test actually catches the bug**, same
discipline as every prior finding: temporarily reverted `query()` back
to `self.port.readline()`, reran `test_instruments.py` -- the
fast-path test failed as expected (`query() took 0.300s ... assert
0.300... < 0.1`), confirming it would have caught this exact
regression; restored the fix immediately after and reran clean.

**Files touched:** [instruments.py](src/thermo_acoustic/instruments.py)
(`SerialTextCommandBackend.query()`), new
[tests/test_instruments.py](tests/test_instruments.py) (2 tests).

**Verification:** tested -- full `tests/` suite green, 287/287 (up from
285; 2 new tests), modulo the same already-documented (Session
41/42/48) offscreen-Qt/Shiboken flakiness in
`test_qt_ui_hardware_settings.py` (a different single test failed on 1
of 2 full-suite runs during verification, always passing cleanly alone)
-- confirmed via `git diff` that nothing this session touches
`qt_ui.py`/`qt_ui_v2.py`. Not hardware-verified against the real valve
yet -- flagged as a natural next step, since this is the exact call
path Session 54's real-hardware timing characterization exercised, but
doing so requires bench access this session didn't have. TEC's own
uncommitted diff confirmed untouched throughout. Not committed, per
instruction -- proposed separately from Task 1 (Session 53's flush fix
commit) above.

### Session 56 -- Synced CetoniPump.fill_level from real device readback at initialize() time (Session 54's second follow-up)

**The gap, precisely.** `CetoniPump.fill_level` is a Python-side
dataclass field defaulting to `0.0` -- nothing anywhere ever called the
real Qmix SDK's own `Pump.get_fill_level()` to reconcile it against
what the physical syringe actually holds. `refill()`/`empty()` only
ever *command* the pump to a known target (full/empty), they don't
*read back* the current state, so they're no substitute for a genuine
sync. Confirmed on real hardware (Session 54 dry-run): a fresh process
read `pump.fill_level == 0.0` while the real syringe still held ~0.05
ml loaded from a prior session -- worked around manually at the time by
reading `get_fill_level()` and assigning it onto `app.pump.fill_level`
before starting a series. **Consequence was fail-safe, not unsafe**:
Session 53's flush() fill-level guard (already committed) just wrongly
refused a legitimate flush on the stale `0.0`, rather than
under/overshooting -- but it recurred on every single app restart with
partial volume loaded, which is every normal day of use, not an edge
case.

**Fix:** `CetoniPump.initialize()` now calls the new
`backend.read_fill_level()` right after `backend.initialize()`
succeeds, and sets `self.fill_level` from that real reading -- placed
inside `CetoniPump.initialize()` itself (not `Application.initialize()`),
since that's the one place already guaranteed the backend is truly
connected (`enabled` is checked first) and it keeps `application.py`
-- which already carries TEC's own uncommitted diff -- untouched.
`QmixPumpBackend.read_fill_level()`
([qmix_backend.py](src/thermo_acoustic/qmix_backend.py)) is a thin
wrapper around the real SDK's `Pump.get_fill_level()` (confirmed
present and working during Session 54's real-hardware testing), and
`read_fill_level()` was added to the `PumpBackend` Protocol
([instruments.py](src/thermo_acoustic/instruments.py)) alongside it.
Only runs when `self.backend is not None` (i.e. never for a simulated
pump), matching every other real-backend-only call in this class.

**Regression tests, [tests/test_application.py](tests/test_application.py):**
`test_cetoni_pump_initialize_syncs_fill_level_from_real_backend`
constructs a fresh `CetoniPump` with a fake backend reporting `0.73`
ml (deliberately not `0.0` or any other prior default, so the test
can't pass by coincidence), confirms `fill_level` starts at the stale
Python default `0.0` before `initialize()` and matches the real
reading after; `test_cetoni_pump_initialize_without_backend_leaves_fill_level_untouched`
confirms a simulated pump (`backend=None`) is correctly left alone;
`test_qmix_pump_backend_reads_real_fill_level_from_sdk` covers the SDK
wrapper directly. `FakePumpBackend`/`FakeQmixPumpModule.Pump` (both
pre-existing fakes in this test file) gained `read_fill_level()`/
`get_fill_level()`; `test_cetoni_backend_commands`'s expected call
list was updated to include the new `("read_fill_level",)` call
immediately after `("initialize", ...)`.

**Verified the regression tests actually catch the gap**, same
discipline as every prior finding: temporarily reverted
`CetoniPump.initialize()`'s sync line, reran -- both
`test_cetoni_backend_commands` and the new sync test failed as
expected (`assert 0.0 == 0.73`); restored immediately after and reran
clean.

**Files touched:** [instruments.py](src/thermo_acoustic/instruments.py)
(`PumpBackend` Protocol, `CetoniPump.initialize()`),
[qmix_backend.py](src/thermo_acoustic/qmix_backend.py)
(`QmixPumpBackend.read_fill_level()`),
[tests/test_application.py](tests/test_application.py) (3 new tests,
2 existing fakes/assertions updated).

**Verification:** tested -- full `tests/` suite green, 290/290 (up
from 287; 3 new tests), modulo the same already-documented (Sessions
41/42/48) offscreen-Qt/Shiboken flakiness in
`test_qt_ui_hardware_settings.py` -- confirmed via `git diff` that
nothing this session touches `qt_ui.py`/`qt_ui_v2.py`. Not
hardware-verified against the real Qmix pump yet -- flagged as a
natural next step, same caveat as Session 55's fix above, requires
bench access this session didn't have. `application.py` deliberately
untouched (the sync lives entirely in `instruments.py`/`qmix_backend.py`
instead), so TEC's own uncommitted diff there is unaffected by this
change at all, not just verified-untouched.

---

## Known remaining open items as of this writing

**Resolved since the previous version of this list** (kept out of the list below, not repeated): SeriesPath overwrite protection, syringe-volume-vs-flush-capacity mismatch, camera trigger source left undefined, Qmix fill-level unit ambiguity, valve ready-check only at init (not reused during flush), the `"BD 5ml"` inner-diameter value, the experiment-path exposure time never reaching real DCAM hardware (Session 20), TDMS write verification (Session 26), the WFG-tab live-use labeling (Session 29, proposed 3 days prior to that session, previously only done for Camera), the WFG tab's Sweep "Center Frequency" unit (Session 16's MHz choice corrected to kHz in Session 29, alongside every other Carrier/FM-Mod/Sweep frequency field on both tabs), the settings.json Hz->kHz silent-misload gap Session 29 itself flagged as unfixed (Session 30: versioned `schema_version` key + one-time auto-convert + load-time warning), Abort not stopping a running experiment series (Session 31 found it on real hardware, Session 32 fixed it, Session 33 hardware-reconfirmed the fix), `FlushSettings.timeout_s`'s missing minutes-to-seconds conversion (Session 31/32, hardware-reconfirmed Session 33 with the exact originally-failing parameters), and the real Qmix pump being unable to connect via `qt_ui.py`'s Initialize button on a clean environment because `QMIXSDK` was never set (Session 31/32, hardware-reconfirmed Session 33 with `QMIXSDK` genuinely unset beforehand).

- **Valve status-query handshake (`"S"` command)** was originally protocol-derived and unverified (Session 2), but later real-hardware GUI verification reported `status_note="confirmed"` (Session 31). Remaining caution: current code still treats some non-empty but unrecognized status responses as connected-with-note rather than a hard initialization failure, so inspect `Valve._apply_status_response()` before relying on the handshake as a strict device-identity proof.
- **DCAM frame timestamp clock domain** is unverified -- real per-frame values are now captured and used when the camera/driver reports support, but which clock (camera-internal vs. host-driver) produced them, and what epoch `sec` is measured from, has not been confirmed against real hardware or official SDK documentation. (Session 8.)
- **Pump flow-rate sign convention** is no longer completely unknown: current UI labeling records `-=aspirate, +=dispense`, and no sign-inversion logic exists anywhere in `CetoniPump`/`Application.flush()`/the UI. Remaining caution: review the live tooltip text before using it as operator guidance, because an independent audit found at least one tooltip still carried older "unverifiable" wording after the label was corrected.
- **`src/thermo_acoustic/ui.py`** (592 lines, a separate unused Tkinter `MainWindow`) remains in the repo, confirmed unreachable from any launcher, flagged for a removal decision but not removed. (Session 7.)
- **`qt_ui_v2.py`/`MainWindowV2`** remains explicitly *not* the default launch target (see Session 4) pending hardware verification and user approval, despite having working sidebar panels, valve handshake, and Init dialog fixes.
- **Camera trigger source is now deterministic but not necessarily correct**: hardcoded to `"Internal"` (Session 13) purely to remove undefined leftover-state risk. Whether the real experiment should instead use `"External"` (paced by the AD2 DIO pulse train) has not been resolved -- **Session 19 traced the real LabVIEW call path (`RunExperiment2.vi` -> `CreateExperiments.vi` -> `Experiment2_Init.vi` -> `ConfigureSequence.vi` -> `tm_inputtriggersource_40.vi`) and confirmed the actual wired value is not recoverable from the exported VI diagrams** (compiled block-diagram wiring, not text); the front-panel screenshot's "Internal" is explicitly not used as a substitute. Still needs oscilloscope verification against real hardware -- unchanged in practice, now backed by a real (negative) investigation instead of screenshot inference. **Session 31 added real supporting evidence** (not a resolution): real per-frame `dcam_clock:` timestamp deltas from an actual hardware run were ~0.0316s apart, matching the camera's own readout time, not the configured DO-clock frame period (0.2s at 5 fps) -- consistent with `"Internal"` free-running the camera at its own rate rather than being paced by the DO clock at all. Deliberately not acted on (needs oscilloscope verification, not fixable from software alone).
- **DCAM exposure vs. readout timing validation -- fixed (Session 19).** `Application._check_camera_timing_budget()` now queries the real `read_readout_time()` and rejects (`ValueError`, before `start_capture()`) any configured Camera FPS that the current exposure+ROI readout time cannot sustain. (Originally flagged in Session 12.) The exposure value it checks against is now guaranteed to be the one actually applied to hardware -- see the next item.
- **Experiment-path exposure time not reaching real DCAM hardware -- fixed (Session 20).** `run_experiment2()` previously called `self.camera.configure(exposure_ms=...)`, a Python-side bookkeeping setter that never wrote `DCAM_IDPROP.EXPOSURETIME` to the real camera (only the manual Camera tab's `configure_exposure_time()` did that). Now calls `configure_exposure_time()` directly, the same real hardware-writing call the manual tab already used -- same bug class, and same fix pattern, as Session 13's camera-trigger-source fix.
- **WFG amplitude/frequency bounds checking remains absent** beyond the generic `-1e12..1e12` spin-box range -- no physically-meaningful ceiling (e.g. AD2 hardware output limits) is enforced. (Flagged in Session 9, not fixed.)
- **Custom/arbitrary syringe geometry for real hardware -- fixed (Session 44).** Was: only the three named BD presets (1/5/10 mL) existed; selecting "Custom" and clicking Configure Syringe always failed with a real `QmixPumpError`, since `_configure_syringe()` only ever sent `{"name": syringe}` and "Custom" isn't in `SYRINGE_PRESETS` (confirmed concretely, Session 38 Task 4). Now: two new fields, Custom Inner Diameter (mm) and Custom Max Piston Stroke (mm), are sent as `inner_diameter_mm`/`max_piston_stroke_mm` whenever Syringe="Custom" -- the user's real spec values, not a value derived/guessed from Custom Volume (a volume alone can't determine both diameter and stroke). Custom Volume itself is unchanged, still flush-safety-check-only.
- **Syringe stroke length is a derived value, not an independently-sourced BD spec figure** -- computed as `volume / cross-sectional area` assuming the full nominal volume fills the entire piston travel in a cylindrical bore; no authoritative real BD stroke-length value was available to verify this assumption against. (Session 17.) The inner-diameter values themselves (1mL=4.78mm, 5mL=12.07mm, 10mL=14.5mm) are confirmed against BD's published spec.
- **The LabVIEW port registry (`labview_ports.py`) is confirmed materially incomplete** relative to the real LabVIEW project (Session 11): the entire `AD2_MSO_SDK_class` surface (17 real VIs, 1 documented), several `AD2_SDK_class`/`AD2_WFG_SDK_class`/`AD2_DO_SDK_class` member VIs, `TDMSlogg_class`, the `REGLO Digital` peristaltic pump driver (referenced directly in `Main.vi`'s front panel, with a corresponding but entirely unwired `RegloPumpControl` dataclass already in [instruments.py:142-146](src/thermo_acoustic/instruments.py:142)), and `Application.lvclass:SaveData.vi` are all undocumented in the registry and not evaluated for a Python equivalent.
- **Frequency Scanning / Dynamic Frequency -- implemented (Session 34).** (Investigated Session 14.) `_build_experiment_series()` now builds a fresh `WfgConfig` per repeat; the new "Frequency Scanning (Dynamic Frequency, Ch1 only)" Experiment-tab group (Start/Stop Frequency in kHz, Number of Frequencies) substitutes a linear-spaced per-repeat frequency into Channel 1 only, with a `ValueError` if the frequency count doesn't match Repeats. Not hardware-verified -- the linear-spacing assumption and the Dynamic-Camera-Start-Time-parallel substitution mechanism remain LabVIEW-behavior-inferred, not confirmed from `CreateExperiments.vi`'s compiled block-diagram wiring (same opacity already hit for trigger source and WFG symmetry/phase), and no real AD2 run has confirmed the actual per-repeat output frequency changes as expected.
- **FM Sweep's three explicitly-flagged unverified assumptions** (Session 16), none confirmed against the real LabVIEW binary or the source literature:
  1. Sweep-Type -> Function enum mapping (Symmetric->Triangle, RampUp->RampUp, RampDown->RampDown) is the most architecturally plausible correspondence given the shared enum, not a confirmed one.
  2. Dual-enable semantics (Enable Sweep forcing both `Carrier.enable=True` and `fm_mod.enable=True`) is this feature's own designed convention, not confirmed against `WfgConfigureSweepCh1.vi`'s actual wiring.
  3. Width interpreted as total span (`Top = Center + Width/2`) was an explicit user unit decision; the Martens et al. reference states "a sweep of 50 kHz" without specifying half- vs. full-span convention. Unchanged in substance since Session 35's UI conversion to Start/Stop Frequency inputs -- `width_hz = abs(stop_hz - start_hz)` is the exact same full-span assumption, just computed from different user-facing inputs.
- Several Category A/LabVIEW-migration items in the "Pre-existing baseline" section above are marked "tested" (via fakes) but explicitly **not hardware-verified**: abort concurrency, Qmix bus close on failure, serial write timeout, the AD2 SDK clock-divider wiring in `waveforms.py`, and the tdms metadata content itself (no real npTDMS-vs-LabVIEW file comparison has been performed).
- **Hardcoded physical/hardware constants audit completed (Session 18)** -- full per-constant table in that section above. Headline items not otherwise tracked elsewhere in this list:
  - Live camera ROI/exposure startup defaults (`roi_v_offset=900`, `roi_v_size=500`, `exposure_ms=50.0` in `qt_ui.py`) diverge from this repo's own validated-on-real-hardware combination (`792`/`740`/`40.0 ms`, recorded in `docs/current_workflow_audit.md` and `experiment_presets.py`, never wired into the live UI).
  - The Prior Z-motor's serial backend silently inherits the valve's hardware-confirmed 19200 baud default with zero independent verification for the Prior protocol (low current risk only because that path is separately flagged as legacy/obsolete).
  - MSO/scope default voltage range (1 V) is below the real acoustic drive signal's documented level (up to 2 V), risking clipping if scoped at defaults.
  - A cluster of operationally-chosen timeouts (Qmix reference-move/close, `Application` cleanup, DCAM frame-wait) have no cited hardware-response basis anywhere in this repo.
  - The WFG `1000.0 Hz`/`1.0 V` fm_mod defaults were confirmed genuinely inert while disabled (traced to `waveforms.py`'s `if channel.fm_mod.enable:` gate), but the same pair is a latent (not live) placeholder risk in `ad2.py`'s dict-coercion fallback for a future partial-config-loading code path.
- **Manual-tab/automated-path hardware-apply parity audit completed (Session 21)** -- full table and reusable methodology in the "Recurring audit" section above. Three of the five findings were fixed in Session 22 (see below); two remain open:
  - **DCAM ROI is never applied in the automated path** -- `configure_roi()` is absent from `application.py`/`workflows.py` entirely, so an automated run relies on whatever ROI a manual Camera-tab session last configured. Confirmed a pre-existing LabVIEW limitation, not a Python regression (`RunExperiment2.vi`'s own call tree has no `ConfigureROI.vi` either, only a read-back `GetSubRegion.vi` for metadata). Not fixed -- lower priority since LabVIEW has the same gap, but still a real risk for automated runs starting from an unknown ROI.
  - **Qmix syringe geometry (`configure_syringe()`) is never applied automatically** -- the physical `inner_diameter_mm`/`stroke_mm` pushed to the Qmix SDK is whatever a manual "Configure" click last set; `Application.flush()` only ever does mL-level bookkeeping (`FlushSettings.syringe_volume_ml`). Confirmed likely a pre-existing LabVIEW limitation too (lower-confidence cross-check than the ROI one -- see Session 21). Not fixed.
- **Session 22 fixed three of Session 21's five findings:** the DCAM sequence cluster (masterpulse mode/source/interval/burst + trigger polarity/delay) is now carried into the automated path from the manual Camera tab's live widgets; WFG symmetry/phase/repeat_trigger are now settable from new Experiment-tab controls instead of hardcoded; and `center_roi()` now actually re-applies centered coordinates via a real `configure_roi()` call instead of only updating local Python state. `synchronize_state` was deliberately left hardcoded, not "fixed" -- investigation confirmed it has no real hardware effect anywhere in this codebase (the manual tab's own control is an explicitly-disabled non-functional stub), so adding a working automated-path control for it would misrepresent a fake feature as real.
- **`qt_ui_v2.py`'s Experiment area was missing FM Sweep and Frequency Scanning entirely -- fixed (Session 39).** Both are real, fully-wired `qt_ui.py` features; neither had any reachable control in v2 (FM Sweep flagged since Session 25, never fixed; Frequency Scanning's v2 gap never even flagged). New `_experiment_fm_sweep_group()` and a reused `_experiment_frequency_scan_group()` bind the identical widget instances, not copies.
- **"Analog Discovery 3" row label (Initialization tab) -- flagged, not resolved (Session 39).** The only place in the live codebase calling this device generation "3" (everywhere else says "2") -- looked like the same stray-suffix class as "MX Valve 2" (Session 36), but `docs/PORTING_TBD.md`'s own "real AD2/AD3 hardware" reference means this lab may genuinely have both units, making "typo vs. deliberate" a real, unresolved fork rather than a confirmed bug. Not changed pending the user's own knowledge of what hardware is actually in the lab.
- **Save/Load Settings persistence coverage -- flagged, not resolved (Session 39); Frequency Scanning specifically closed (Session 44).** Most manual-tab-only fields (WFG Trigger/FM Mod/Sweep sub-fields, the entire Pump&Valve and Camera tabs including the Session-22 load-bearing Sequence cluster, and several later-added Experiment-tab fields: Camera FPS/Start/Array, Dynamic Camera Start Time, GlobalExposure, FM Sweep) are still silently dropped by Save Settings and reset to defaults on the next Load -- long-standing baseline behavior, not a recent regression. Whether comprehensive persistence was ever the intended design, or Save/Load Settings was always meant to cover only hardware-connection + core experiment-repeat parameters, remains a genuine design-scope question this list cannot resolve from the code alone. A mechanical fix (extending `_settings_dict()`/`_load_settings()` with the same tolerant `if key in data` pattern already used throughout) is available for the rest if the answer is "yes, persist everything." **Frequency Scanning** (Start/Stop/Number of Frequencies/Step Size, plus its Enable toggle) was named explicitly in this bullet since Session 34 and is now persisted (Session 44) -- removed from this still-open list.
- **Z stage backend selection has no real effect -- newly confirmed while grounding a tooltip (Session 39).** `hardware_factory.build_hardware_bundle()` never reads `config.z_backend`/the UI's own "Z stage backend" combo at all -- enabling "Z stage" always builds a Prior-serial `PriorZMotor`, regardless of whether the (already-disabled) combo shows `"prior_serial"` or `"thorlabs_apt"`. A stronger claim than the existing "Not wired to a real backend" stub tooltip already made; low current risk only because this whole path is separately flagged as legacy/obsolete (Session 18) since current Z hardware is Thorlabs/APT, which has no real backend implemented at all yet.
- **`sequence_exposure_ms` was dead since Session 11 and never actually fixed until now -- fixed (Session 39).** Flagged alongside `capture_mode` in that session's audit; `capture_mode` was fixed in Session 24, this field was not, until this session's Category 1 pass caught the same class of bug it had already fixed once before.
