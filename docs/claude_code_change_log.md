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

---

## Known remaining open items as of this writing

- **Valve status-query handshake (`"S"` command)** is protocol-derived from third-party documentation, not yet run against real hardware. (Session 2.)
- **DCAM frame timestamp clock domain** is unverified -- real per-frame values are now captured and used when the camera/driver reports support, but which clock (camera-internal vs. host-driver) produced them, and what epoch `sec` is measured from, has not been confirmed against real hardware or official SDK documentation. (Session 8.)
- **Pump flow-rate sign convention**: no sign-inversion logic exists anywhere in `CetoniPump`/`Application.flush()`/the UI, and no documented LabVIEW reference convention exists in this repo to compare against -- there is nothing to verify a match or mismatch against. (Flagged in Session 6.)
- **`src/thermo_acoustic/ui.py`** (592 lines, a separate unused Tkinter `MainWindow`) remains in the repo, confirmed unreachable from any launcher, flagged for a removal decision but not removed. (Session 7.)
- **`qt_ui_v2.py`/`MainWindowV2`** remains explicitly *not* the default launch target (see Session 4) pending hardware verification and user approval, despite having working sidebar panels, valve handshake, and Init dialog fixes.
- Several Category A/LabVIEW-migration items in the "Pre-existing baseline" section above are marked "tested" (via fakes) but explicitly **not hardware-verified**: abort concurrency, Qmix bus close on failure, serial write timeout, the AD2 SDK clock-divider wiring in `waveforms.py`, and the tdms metadata content itself (no real npTDMS-vs-LabVIEW file comparison has been performed).
