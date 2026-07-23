# Claude Code Change Log

This is a factual record of everything modified in this repository across
Claude Code sessions to date, compiled from `git log`, `git status`, and
`git diff` against the working tree on branch `junjiebranch`.

**Important caveat on dating**: as of this writing, none of the work
described below has been committed. `git log` shows the branch's real
commit history ending at `5419043` (2026-07-09), and every file discussed
here still shows as `modified`/untracked in `git status`. That means none
of this has a git timestamp of its own -- it all exists only as
uncommitted working-tree changes. No dates are invented; where a date is
stated, it comes from `git log`.

**Caveat on methodology -- read this before treating the document as
authoritative.** This log was compiled from two distinct kinds of source,
and they are not equally verifiable:

1. **Fresh git diff/grep against the current working tree.** Every
   file:line reference, current behavior description, and test-count claim
   in this document was re-checked against the working tree at compile
   time, not recalled from earlier summaries. This part is independently
   reproducible by anyone with repo access.
2. **This conversation's own history**, used for *sequencing and
   narrative only*: which session did what, in what order, and -- in
   particular -- the fact that the qt_ui_v2 default-entry-point swap and
   its later revert happened at all. This is **not** git-derived. Checked
   at the time this caveat was written: `git stash list` is empty, and
   `git reflog` contains only commits/checkouts/pulls -- nothing tracks
   uncommitted working-tree edits. Concretely, for the swap-then-revert
   sequence:
   - `tools/run_ui.py`'s two edits (swap, then revert) net to a diff of
     zero against the last commit -- `git diff` alone shows no evidence
     this file was ever touched.
   - `launch_gui.bat` is untracked the entire time; git has never
     recorded any state for it other than "it currently exists," so there
     is no diff/log showing it ever pointed at `qt_ui_v2`.
   - `README.md` is tracked, but `git diff` only shows current-vs-last-
     commit (the final, reverted state) -- the intermediate rewritten
     state is invisible to git.

   The only reason this document records that sequence is that it was
   carried out directly in this conversation, across two separate user
   instructions, and is recalled here rather than rediscovered from
   artifacts. A reader (or a future compiler of this log) starting only
   from `git log`/`git diff`/`git stash list`/`git reflog` on this repo,
   with no access to the conversation, would have no way to know this
   swap-and-revert happened -- the working tree alone would just show
   `qt_ui` as the current default, with no trace of the detour.

   A direct consequence: if any *other* change in this conversation was
   made and then fully reverted without being recalled here, it would be
   invisible both to git and to this document. This log's completeness
   for "things done and later undone" is bounded by what was recalled
   while compiling it, not by anything independently checkable in git.

Also note: this log covers everything currently sitting in the working
tree, which includes work from **two different sources**:

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

---

## Known remaining open items as of this writing

**Resolved since the previous version of this list** (kept out of the list below, not repeated): SeriesPath overwrite protection, syringe-volume-vs-flush-capacity mismatch, camera trigger source left undefined, Qmix fill-level unit ambiguity, valve ready-check only at init (not reused during flush), and the `"BD 5ml"` inner-diameter value.

- **Valve status-query handshake (`"S"` command)** is protocol-derived from third-party documentation, not yet run against real hardware. (Session 2.)
- **DCAM frame timestamp clock domain** is unverified -- real per-frame values are now captured and used when the camera/driver reports support, but which clock (camera-internal vs. host-driver) produced them, and what epoch `sec` is measured from, has not been confirmed against real hardware or official SDK documentation. (Session 8.)
- **Pump flow-rate sign convention**: no sign-inversion logic exists anywhere in `CetoniPump`/`Application.flush()`/the UI, and no documented LabVIEW reference convention exists in this repo to compare against -- there is nothing to verify a match or mismatch against. (Flagged in Session 6.)
- **`src/thermo_acoustic/ui.py`** (592 lines, a separate unused Tkinter `MainWindow`) remains in the repo, confirmed unreachable from any launcher, flagged for a removal decision but not removed. (Session 7.)
- **`qt_ui_v2.py`/`MainWindowV2`** remains explicitly *not* the default launch target (see Session 4) pending hardware verification and user approval, despite having working sidebar panels, valve handshake, and Init dialog fixes.
- **Camera trigger source is now deterministic but not necessarily correct**: hardcoded to `"Internal"` (Session 13) purely to remove undefined leftover-state risk. Whether the real experiment should instead use `"External"` (paced by the AD2 DIO pulse train) has not been resolved -- needs oscilloscope verification against real hardware.
- **DCAM exposure vs. readout timing is unvalidated**: nothing checks that `exposure_ms/1000 + readout_time <= 1/camera_fps`; an invalid combination is silently accepted rather than rejected or warned about. (Flagged in Session 12, not fixed.)
- **WFG amplitude/frequency bounds checking remains absent** beyond the generic `-1e12..1e12` spin-box range -- no physically-meaningful ceiling (e.g. AD2 hardware output limits) is enforced. (Flagged in Session 9, not fixed.)
- **TDMS write verification remains deferred**: `_write_tdms()`'s only check that a write succeeded is that `TdmsWriter.write_segment()` didn't raise -- no re-open, size check, or field-count assertion exists. (Flagged repeatedly, most recently Session 9; explicitly out of scope each time.)
- **Custom/arbitrary syringe geometry for real hardware is still unsupported** -- only the three named BD presets (1/5/10 mL) exist; a syringe outside this set requires manually supplied `inner_diameter_mm`/`max_piston_stroke_mm` with no UI for it.
- **Syringe stroke length is a derived value, not an independently-sourced BD spec figure** -- computed as `volume / cross-sectional area` assuming the full nominal volume fills the entire piston travel in a cylindrical bore; no authoritative real BD stroke-length value was available to verify this assumption against. (Session 17.) The inner-diameter values themselves (1mL=4.78mm, 5mL=12.07mm, 10mL=14.5mm) are confirmed against BD's published spec.
- **The LabVIEW port registry (`labview_ports.py`) is confirmed materially incomplete** relative to the real LabVIEW project (Session 11): the entire `AD2_MSO_SDK_class` surface (17 real VIs, 1 documented), several `AD2_SDK_class`/`AD2_WFG_SDK_class`/`AD2_DO_SDK_class` member VIs, `TDMSlogg_class`, the `REGLO Digital` peristaltic pump driver (referenced directly in `Main.vi`'s front panel, with a corresponding but entirely unwired `RegloPumpControl` dataclass already in [instruments.py:142-146](src/thermo_acoustic/instruments.py:142)), and `Application.lvclass:SaveData.vi` are all undocumented in the registry and not evaluated for a Python equivalent.
- **Frequency Scanning / Dynamic Frequency (discrete per-repeat WFG frequency substitution) is investigated but NOT implemented.** (Session 14.) `_build_experiment_series()` still builds one `WfgConfig` outside the per-repeat loop and reuses it for every repeat; there is no `dynamic_frequency`/`frequency_list` state anywhere in `qt_ui.py`. This is a real, currently-un-ported LabVIEW feature (`FrequencyHelper.vi` + `CreateExperiments.vi`'s `Dynamic Frequency`/`Frequency List` inputs), tracked here as the actual next migration candidate in this area -- distinct from FM Sweep (Session 16), which was fully implemented.
- **FM Sweep's three explicitly-flagged unverified assumptions** (Session 16), none confirmed against the real LabVIEW binary or the source literature:
  1. Sweep-Type -> Function enum mapping (Symmetric->Triangle, RampUp->RampUp, RampDown->RampDown) is the most architecturally plausible correspondence given the shared enum, not a confirmed one.
  2. Dual-enable semantics (Enable Sweep forcing both `Carrier.enable=True` and `fm_mod.enable=True`) is this feature's own designed convention, not confirmed against `WfgConfigureSweepCh1.vi`'s actual wiring.
  3. Width interpreted as total span (`Top = Center + Width/2`) was an explicit user unit decision; the Martens et al. reference states "a sweep of 50 kHz" without specifying half- vs. full-span convention.
- Several Category A/LabVIEW-migration items in the "Pre-existing baseline" section above are marked "tested" (via fakes) but explicitly **not hardware-verified**: abort concurrency, Qmix bus close on failure, serial write timeout, the AD2 SDK clock-divider wiring in `waveforms.py`, and the tdms metadata content itself (no real npTDMS-vs-LabVIEW file comparison has been performed).
