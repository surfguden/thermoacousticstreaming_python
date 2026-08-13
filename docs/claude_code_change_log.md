# Claude Code Change Log

This is a historical record of the LabVIEW-to-Python migration and the
Claude Code sessions that worked on it. It is intentionally useful, but it
is not the live source of truth for the current repository state. For the
current state, always check `git log`, `git status`, `git diff`, and the
code itself.

**Current repo-state note, refreshed during independent audit on
2026-08-04.** The old
top-level caveat in this document said the branch history ended at
`5419043` and that none of the work below had been committed. That is no
longer true. As of this audit pass, branch `junjiebranch` has commits
through `17f24dd` (`Add TEC control and real-piezo Z-stage integration; complete
a 7-module hardware-safety review (14 fixes)`). The working tree is not
clean and includes TEC-related source/tests, UI/workflow edits, hardware
smoke-script edits, documentation updates, and untracked helper files.
Current code/docs/tests also contain explicit references through at least
**Session 77**, including uncommitted material. Treat this changelog as a historical narrative, not as an
authoritative live inventory; re-check `git log`, `git status`, `git diff`,
and the code before acting on any session claim.

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

> **Current-status correction (independent audit):** the historical
> Open/Closed claim below was supported here only by the earlier session's
> report, while the live workflow/migration audits retain physical P01/P02
> routing as unverified. Current UI text therefore uses the protocol-confirmed
> `P01`/`P02` names only; see `docs/known_open_items.md` for the holding item.

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

### Session 57 -- Code-health audit (read-only) plus one immediate fix: CetoniPump.refill()'s hardcoded fill_level=1.0

**Audit, read-only, no fixes during the sweep itself.** First systematic
code-health pass over `src/thermo_acoustic/` (excluding `tec.py` and
TEC-authored hunks entirely -- not read, not evaluated, per standing
instruction). Five categories, reported to the user before any fix was
authorized:

1. **Duplicated logic across hardware modules.** Three independently
   written "lazy SDK import" methods with the same shape
   (`QmixPumpBackend._load_sdk()`, `HamamatsuDcamBackend._load_sdk()`,
   `PiezoStage._load_kinesis()` -- the last one's own docstring even
   says it "follows this project's existing SDK-backend pattern," the
   duplication was noticed once and repeated anyway); a near
   line-for-line duplicated thread+timeout+queue wrapper at two layers
   (`Application._run_cleanup_call_with_timeout()` and
   `QmixPumpBackend._run_close_step()`); an inconsistent guard-method
   pattern (`_require_pump()`/`_require_connected()` vs. inlined
   duplicate checks in `SerialTextCommandBackend`).
2. **Dead code.** `src/thermo_acoustic/main.py` (16 lines, orphaned CLI
   stub, zero references anywhere). Four LabVIEW-VI-parity scaffold
   modules totaling ~454 lines (`utilities.py`, `imaq.py`,
   `filetypes.py`, `serial_config.py`) confirmed to map to
   `labview_ports.py` entries but never wired into the real pipeline --
   only referenced by their own unit tests in `tests/test_application.py`.
   `RegloPumpControl` cross-referenced against the already-tracked
   Session 11 item in `known_open_items.md` (not a new finding).
3. **Inconsistent error-handling/logging.** Only 4 of 12 checked modules
   define a `logger`; four different close()/cleanup() error-handling
   shapes across backends with no shared convention; a genuine,
   currently-uncaught recurrence of Finding F's exact silent-except-pass
   pattern in `thorlabs_piezo.py`'s `connect()` rollback path (no
   logger available in that module at all, consistent with the first
   point); a softer instance in `hamamatsu_dcam.py`'s `_ensure_buffer()`.
4. **application.py/workflows.py complexity.** `application.py` (614
   lines) spans 5 distinct responsibility clusters (message-bus
   plumbing, instrument accessor boilerplate, abort/error infra, AD2/
   camera timing-budget math, experiment orchestration) --
   `run_experiment2()` alone (~127 lines) is the concrete complexity
   concern, not the class as a whole. `workflows.py` (459 lines) is
   tightly cohesive around `Experiment2`/`ExperimentSeries2` and shows
   no comparable evidence a split would help.
5. **Comment/docstring accuracy.** Finding 5a (below) was the standout.
   No stray `TODO`/`FIXME`/`deprecated` markers found anywhere in `src/`.

User approved acting on finding 5a immediately; everything else (1a/1b/1c,
2a, 2b, 3a/3b/3c/3d, 4) stays documented for a future decision, not
queued as follow-up tasks.

**Finding 5a, fixed: `CetoniPump.refill()`
([instruments.py](src/thermo_acoustic/instruments.py)) hardcoded
`self.fill_level = 1.0` after calling `backend.refill()`, regardless of
the syringe's real configured capacity.** The real backend
(`QmixPumpBackend.refill()`) correctly fills the *actual device* to its
true `max_volume_ml` -- for any syringe other than exactly 1 mL (e.g.
the BD 5ml/10ml presets), this immediately desynced the Python-side
`fill_level` from real hardware state right after every `refill()` call,
the same failure class Session 56 just fixed for `initialize()`, except
uncaught until the next `initialize()`. No test anywhere asserted
`fill_level` after `refill()` -- confirmed by grep, this was completely
uncaught by the suite.

**Fix, mirroring Session 56's `initialize()` fix exactly:** for the
real-backend path, `refill()` now calls `self.backend.read_fill_level()`
right after `self.backend.refill()` succeeds (same already-existing
`PumpBackend` Protocol method, no new backend surface needed). For the
simulated (`backend=None`) path, added a new `max_volume_ml: float =
1.0` field to `CetoniPump` -- `refill()` now derives from that instead
of the hardcoded literal. The default (`1.0`) is deliberately unchanged
from the old behavior for backward compatibility with existing
simulated-mode callers that never set it explicitly (one existing test,
`test_qt_ui_hardware_settings.py`'s neighbor in `test_application.py`
at line ~693, asserts exactly this default and still passes unmodified).
**Deliberately not wired further:** `configure_syringe()` does not
auto-populate `max_volume_ml` from a resolved preset/geometry (e.g.
"BD 5ml" -> `5.0`) -- doing so would require either duplicating
`qmix_backend.py`'s `SYRINGE_PRESETS`/diameter-stroke-to-volume math
inside `instruments.py` or introducing a new cross-module dependency,
which is a separate design decision beyond "fix the hardcoded 1.0" and
was not authorized for this task.

**Regression tests, [tests/test_application.py](tests/test_application.py)
(3 new):** `test_cetoni_pump_refill_syncs_fill_level_from_real_backend_not_hardcoded_1ml`
uses a fake backend reporting `5.0` ml (BD 5ml preset context,
`inner_diameter_mm=12.07`, deliberately not `1.0` so it can't pass by
coincidence) and confirms `fill_level` matches the real reading, not
the old hardcoded value; `test_cetoni_pump_refill_without_backend_uses_configured_max_volume`
confirms the new `max_volume_ml` field is honored when set;
`test_cetoni_pump_refill_without_backend_defaults_to_1ml_when_unconfigured`
confirms the backward-compatible default. `test_cetoni_backend_commands`'s
expected call list gained the new `("read_fill_level",)` call right
after `("refill",)`.

**Verified the regression tests actually catch the gap**, same
discipline as every prior finding: temporarily reverted `refill()` to
the old hardcoded `self.fill_level = 1.0`, reran -- 3 tests failed as
expected (`test_cetoni_backend_commands`, both new real-backend/
configured-max-volume tests; the unconfigured-default test correctly
still passed, confirming backward compatibility); restored immediately
after and reran clean.

**Files touched:** [instruments.py](src/thermo_acoustic/instruments.py)
(`CetoniPump.max_volume_ml` field, `CetoniPump.refill()`),
[tests/test_application.py](tests/test_application.py) (3 new tests, 1
existing assertion updated). `qmix_backend.py` deliberately untouched --
`QmixPumpBackend.refill()`'s own real-device behavior was already
correct; only the Python-side bookkeeping in `instruments.py` was wrong.

**Verification:** tested -- full `tests/` suite green, 293/293 (up from
290; 3 new tests), modulo the same already-documented (Sessions
41/42/48) offscreen-Qt/Shiboken flakiness in
`test_qt_ui_hardware_settings.py` (hit unusually hard again this
session, flagged to the user as worth a dedicated look, not investigated
further here) -- confirmed via `git diff` that nothing this session
touches `qt_ui.py`/`qt_ui_v2.py`. Not hardware-verified against the real
Qmix pump yet, same caveat as Sessions 55/56. `application.py`
deliberately untouched throughout (fix lives entirely in
`instruments.py`), so TEC's own uncommitted diff is unaffected, not
just verified-untouched.

### Session 58 -- Status/Error Out replaced with scrollable session history (HistoryLogWidget)

Status (top toolbar) and Error Out (standalone panel) were single-line
`QLineEdit`/`QLabel` fields each new message silently overwrote --
history was gone the instant the next status changed. New
`HistoryLogWidget(QListWidget)`: `add_entry(text)` appends a
timestamped row instead of replacing the display (deliberately not
named `setText()` -- "append" and "replace" are different operations).
Consecutive identical entries are deduped, since several existing call
sites (`_handle_worker_finished()`'s "OK" branch, `_safe_call()`'s
success path) re-report the same state on every successful action, not
just on a genuine change, and without dedup that would flood the log.
Auto-scrolls to the newest entry only when already at the bottom, so
scrolling up to review history isn't yanked back down by the next
incoming message.

`self.status` is now a `HistoryLogWidget`; the one existing call site
(`_refresh_status()`) needed one line changed. The three separate
`error_status`/`error_code`/`error_source` fields were consolidated
into one `error_log` `HistoryLogWidget` plus a new
`_append_error_entry(status, code, source)` helper bundling all three
into one row; rewrote the 9 call-site triplets across
`_handle_shutdown_timeout`/`_handle_action_timeout`/
`_handle_shutdown_finished`/`_handle_worker_finished`/`_safe_call`/
`closeEvent`. `qt_ui_v2.py` has its own separate, independently
constructed copies of these widgets (not reused from v1) -- updated to
the same type, the minimum needed to keep it working against the
shared inherited setter methods, not new v2 functionality. One
knock-on fix: `_v2_status_progress_group()`'s hardcoded minimum height
(120) was too small for the new multi-row widget's real size hint,
caught by the existing
`test_v2_no_group_box_is_squeezed_below_its_minimum_size_hint` guard;
bumped to 140.

**5 new tests** in `tests/test_qt_ui_hardware_settings.py`: direct
widget-level accumulation/dedup/auto-scroll behavior, plus two
integration tests confirming multiple distinct status/error events
accumulate through a real `MainWindow` rather than the latest
overwriting the previous ones. Existing tests reading
`window.status.text()` were updated to `.latest_text()` (added
specifically for this, kept for backward-compatible single-value
reads). The tooltip-coverage regression guard was updated 134 -> 133
(`error_code`'s own tooltip was one of the counted fields;
`HistoryLogWidget` isn't a tracked widget type for that sweep).
`tests/test_qt_ui_v2.py` needed no changes at all.

**Files touched:** [qt_ui.py](src/thermo_acoustic/qt_ui.py),
[qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py),
[tests/test_qt_ui_hardware_settings.py](tests/test_qt_ui_hardware_settings.py).

**Verification:** tested -- full suite green at the time, modulo the
same already-documented (Sessions 41/42/48) offscreen-Qt/Shiboken
flakiness. Committed later this session (`556eea2`) via the same
hunk-reconstruction-and-verify discipline as every other TEC-entangled
file this session -- all 31 hunks across `qt_ui.py`'s diff turned out
cleanly non-overlapping with TEC's own uncommitted diff (no hunk mixed
both at the line level), confirmed by diffing the reconstruction
against both HEAD and the working tree before staging.

### Session 58, Part 1 -- Dual UI launcher: launch_gui_v2.bat, tools/run_ui_v2.py

Added `launch_gui_v2.bat` (mirrors `launch_gui.bat` exactly, launching
`thermo_acoustic.qt_ui_v2` instead of `qt_ui`) and
[tools/run_ui_v2.py](tools/run_ui_v2.py) (mirrors
[tools/run_ui.py](tools/run_ui.py) the same way) -- `launch_gui.bat`
and `tools/run_ui.py` themselves are untouched, confirmed via `git
diff` showing zero changes to either. Checked first whether
`tools/run_ui.py` is actually used by anything before assuming a
sibling was worth adding, per instruction: it is -- both
[README.md](README.md) and `docs/HANDOVER.md` document and reference
it directly as the primary dev entry point. `docs/HANDOVER.md` is left
untouched -- it's an explicitly point-in-time historical handover
document (old machine paths, a stale "20 passed" test count), not a
living doc; rewriting it would misrepresent its own nature, same
reasoning already applied elsewhere in this project's history to
avoid rewriting frozen changelog narrative. [README.md](README.md)
gained a new "Launchers" section listing both `.bat` files and both
`tools/run_ui*.py` scripts side by side with which UI each opens, plus
a note that `launch_gui.bat` itself was not previously documented
there at all (only `tools/run_ui.py` was). `hardware_tests/README.md`
was checked and is not the right home -- it has zero existing
main-GUI-launcher content, being entirely about `hardware_tests/`
probe scripts. v2's own default-launch-target status is unchanged
(still not launched by `launch_gui.bat`/`tools/run_ui.py`, per
`docs/legacy_unresolved_items.md`); this only makes v2 reachable by
explicit choice.

**Committed** (`395ba9a`) -- brand-new files plus a README.md edit,
none of it touching anything TEC-authored, so no hunk separation was
needed.

### Session 58, Part 2 -- v2 sequence-visualization, Phase 1: backend step decomposition

**Design decisions recorded, not left conversational.** A new comment
block at the top of [application.py](src/thermo_acoustic/application.py)
(directly above the `STEP_*` name constants) documents both: (1) Flush
is one card/step, not decomposed into sub-steps -- `flush()` fires
exactly one `step_started`/`step_completed`/`step_failed` trio around
its entire body; (2) when a TEC scan is enabled, the v2 UI is expected
to show a single reused step-card list, not one per temperature point
-- the current target/point-in-sequence is a separate top-level
indicator outside the list. This is why `SetTecTarget`/`WaitTecStable`
are their own two steps wrapping `run_temperature_series()`'s
per-point loop from outside, not folded into `run_experiment2()`'s own
per-repeat steps.

**Mechanism:** a new `_report_step(progress, name)` context manager
(module-level, not a method -- no `self` state needed) fires
`progress("step_started", name)` on entry, `progress("step_completed",
name)` on a normal exit, and `progress("step_failed", (name,
str(exc)))` then re-raises on any exception -- a no-op wrapper when
`progress` is `None`. Documented explicitly in its own docstring: only
exceptions trigger `step_failed`; a step that returns normally with a
"didn't succeed" result (e.g. `flush()`'s own `return False` on a
pump-wait timeout) still reports `step_completed`, matching this
module's existing convention of using status events/return values, not
exceptions, for expected non-exceptional stop conditions like abort or
timeout.

**`run_experiment2()`, `flush()`, `run_temperature_series()` all gained
an optional `progress: Callable[[str, object], None] | None = None`
parameter**, defaulting to `None`. Wrapped the named steps exactly as
scoped: `InitializeExperiment` (dequeue's own `NoExperiment` early
return stays outside any step, since it's not really "step 1" failing,
just nothing to run), `ConfigureWfg`, `ConfigureCamera`,
`CaptureFrames` (the existing inner `try/finally` around
`start_capture()`/`pc_trigger()`/`image_sequence()`/`stop_capture()` is
preserved exactly, just now also wrapped by the step boundary),
`WaitForAd2Completion` (only entered, so only fires, when
`remaining_ad2_wait_s > 0`, exactly as scoped), `Flush` (wraps `flush()`'s
entire body, called from `run_experiment2()` via
`self.flush(experiment.flush_settings, progress=progress)` -- not
separately wrapped at the call site, since `flush()` also has two other
call sites, `handle_message()`'s `MessageName.FLUSH` handler and a
manual "Flush" button in `qt_ui.py`, both of which now benefit from the
same wrapping automatically if a `progress` is ever passed there too),
`SaveResults`. `run_temperature_series()` gained `SetTecTarget`
(wrapping `tec.apply_static_setpoint()`) and `WaitTecStable` (wrapping
`tec.wait_until_stable()`) once per temperature point, and threads
`progress` down into each `run_experiment2(progress=progress)` call in
its per-repeat loop. `TecAbortedError` from `wait_until_stable()` still
propagates through `_report_step`'s own `except Exception` (firing
`step_failed` for `WaitTecStable`, since `TecAbortedError` is an
`Exception`) before being caught by `run_temperature_series()`'s own
existing `except TecAbortedError:` handler -- confirmed this composes
correctly, not just assumed.

**Verified v1 and all existing tests are completely unaffected**, the
single most important check per instruction: full suite green with zero
changes needed beyond three real, expected compatibility fixes caused
by the new keyword-only `progress` parameter (not by any behavior
change) -- two test doubles that fully replaced `Application.flush`
with a lambda lacking a `progress` parameter
(`tests/test_application.py`, `tests/test_full_flow_dry_run.py`), and
one `run_experiment2()` override in `tests/test_tec.py` missing the
same. All three now accept `progress=None`. No other caller anywhere in
`hardware_tests/`, `tools/`, or the rest of the test suite passes
`progress` at all, so their behavior is byte-for-byte unchanged -- the
new parameter is purely additive.

**New tests, 14 total:** [tests/test_full_flow_dry_run.py](tests/test_full_flow_dry_run.py)
(using its existing `FakeAD2`/`FakeCamera`/`FakePump`/`FakeValve`
fakes, no new fake infrastructure needed) covers the happy-path step
sequence with flush disabled, with flush enabled, and with a real
`WaitForAd2Completion` wait (reusing the same deterministic-clock
monkeypatch technique an existing test already used, so no real
sleeping); a dedicated failure-injection test per named step
(`InitializeExperiment` through `SaveResults`, plus `Flush`), each
confirming the exact `step_failed` name/message, that every step
*before* the failure point still shows `step_completed`, and that
*no* step after the failure point ever fires `step_started`; and one
test confirming `flush()` returning `False` (not raising) still
reports `step_completed`, not `step_failed`, per the documented design.
[tests/test_tec.py](tests/test_tec.py) adds three more: the
`SetTecTarget`/`WaitTecStable` pair firing once per temperature point
(2 points -> 4 step events, not folded into a stubbed
`run_experiment2()`'s own events), and a failure-injection test for
each of the two TEC steps.

**Files touched:** [application.py](src/thermo_acoustic/application.py)
(`_report_step()`, `STEP_*` constants + design-decision comment,
`progress` parameter on all three methods),
[tests/test_application.py](tests/test_application.py) (1 lambda
signature fix), [tests/test_full_flow_dry_run.py](tests/test_full_flow_dry_run.py)
(1 lambda signature fix + 9 new tests),
[tests/test_tec.py](tests/test_tec.py) (1 override signature fix + 3
new tests). `tec.py` itself untouched, confirmed via `git diff` --
this task only added new plumbing around `run_temperature_series()`'s
existing calls into it.

**Verification:** tested -- full `tests/` suite green, 313/313 (up
from 299; 14 new tests: 11 in `test_full_flow_dry_run.py`, 3 in
`test_tec.py` -- written per-step rather than parametrized, for
clarity, per the instructed "confirm the right step is reported as
failed... at each individual named step"), modulo the same
already-documented
(Sessions 41/42/48) offscreen-Qt/Shiboken flakiness (a different
random `test_qt_ui_hardware_settings.py`/`test_qt_ui_v2.py` test each
run, always clean in isolation) -- confirmed via `git diff` that this
task touches neither `qt_ui.py` nor `qt_ui_v2.py` at all (Phase 1 is
backend-only, no UI wiring yet). **Update:** committed (`64fdc99`) via
the reconstruction-and-verify discipline established this session --
`run_temperature_series()` itself doesn't exist in this commit's base
at all (it's TEC's own uncommitted addition), so its own
`SetTecTarget`/`WaitTecStable` step-wrapping remains bundled with
TEC's own work rather than included in this commit; everything else
(the `STEP_*` constants, `_report_step()`, and the `progress`
parameter/wrapping in `flush()`/`run_experiment2()`) is self-contained
and committed cleanly. Phase 2 (UI work) proceeded after this
commit landed -- see below.

### Session 58 continued -- hardware_tests/output/ disk cleanup (4.89 GB -> ~0) plus a retention convention going forward

**Investigation first, then execution, per instruction.** Confirmed
`.gitignore`'s `hardware_tests/output/` rule was genuinely working
(`git status --short`/`--ignored` and `git ls-files` all confirmed --
nothing tracked, nothing visible, zero git impact from anything done to
this directory) before touching anything. Broke down all 8
subdirectories by size/file count/date range and cross-referenced every
name against the changelog and `docs/known_open_items.md` (zero hits in
the latter) -- found that the two subdirectories whose names suggested
a deliberately-preserved reference dataset
(`piezo_zscan_verification/session48_first_real_scan/`,
`qt_ui_e2e_verification/abort_mid_repeat2/` +
`.../session33_flush_retry/`) no longer actually contained the
sessions they're named after: every file's modification timestamp was
recent (24/27 Jul 2026), not the original Session 33/48 dates, meaning
later runs had silently overwritten the same script-defined path names
with fresh captures. Reported this finding rather than assuming either
way; user confirmed after review that the changelog's own prose (pixel
ranges, resolution, pass/fail) is the durable record and authorized
deleting everything.

**Correction offered but not needed:** asked to fix the `.gitignore`
comment's session attribution (reported as saying "Session 53");
re-checked the actual file first and it already correctly said
"Session 51" -- the mislabel was in an earlier verbal summary of the
finding, not in the file itself. Left untouched rather than making a
needless edit.

**Deleted:** all content under `hardware_tests/output/` (the directory
itself kept, empty) -- 4.89 GB, 1,443 files, confirmed via `du -sh`
before (4.9G) and after (4.0K). `git status --short` before and after
the deletion diffed byte-for-byte identical, confirming zero git
impact, not just assumed from the gitignore rule's existence.

**Retention convention added, so this doesn't silently regrow.**
Confirmed the regrowth mechanism first: every real-hardware mode in
[hardware_tests/test_real_workflow_smoke.py](hardware_tests/test_real_workflow_smoke.py)
already creates a fresh `{name}_{timestamp}` run directory on every
invocation and never deletes an old one -- the script's own default
output path (`hardware_tests/_smoke_output`) doesn't even exist on
disk, confirming every real run to date was pointed at
`hardware_tests/output/<name>` by explicit operator `--output-dir`,
not the script's own default. Added `prune_old_run_dirs(output_dir,
prefix, keep_last)` (module-level helper) and a new `--keep-last`
CLI flag (default `4`, `0` disables pruning) -- called once per
real-hardware mode, right before that mode's own `run_dir` is created,
pruning older same-prefix run directories down to `keep_last - 1` so
the total settles back to exactly `keep_last` once the new run
directory exists. Prefix-scoped deliberately (not a blanket
"newest-N-of-everything" prune): if an operator ever points
`--output-dir` at a folder shared across multiple modes, pruning one
mode's history can't delete a different mode's most recent run.

**Tests, 6 new, [tests/test_real_workflow_smoke_plan.py](tests/test_real_workflow_smoke_plan.py)**
(the existing tracked test file for this script, reusing its own
established `load_smoke_module()` pattern): direct unit tests of
`prune_old_run_dirs()` covering the core "N+2 exist, keep_last=N,
confirm N-1 remain" contract, prefix-isolation (a differently-prefixed
sibling directory survives untouched), `keep_last=0` disabling pruning
entirely, and a no-op on a not-yet-existing `output_dir`; plus one
true end-to-end test through `main()` matching the exact scenario
requested -- 5 (`N+2` for `keep_last=3`) fake pre-existing timestamped
folders, run once (with the real hardware runner mocked out, matching
this file's own established testing convention), confirm exactly the
newest 3 remain (2 old + the one new run just created); plus a test
confirming `--keep-last` defaults to `4` when not passed explicitly.

**Files touched:**
[hardware_tests/test_real_workflow_smoke.py](hardware_tests/test_real_workflow_smoke.py)
(`prune_old_run_dirs()`, `--keep-last` flag, 5 call sites -- one per
real-hardware mode that creates a timestamped run directory),
[tests/test_real_workflow_smoke_plan.py](tests/test_real_workflow_smoke_plan.py)
(6 new tests). `.gitignore` unchanged (already correct, see above).

**Verification:** tested -- full `tests/` suite green, 319/319 (up
from 313; 6 new tests), modulo the same already-documented (Sessions
41/42/48) offscreen-Qt/Shiboken flakiness, confirmed unrelated via
isolation reruns of the affected files. Disk space confirmed recovered
via `du -sh` before/after; git impact confirmed zero via `git status`
before/after, not assumed from the gitignore rule alone.

### Session 58, Part 3 -- v2 sequence-visualization, Phase 2: Configuration Mode UI (ExperimentSequenceView)

**Card-to-group mapping, a judgment call recorded in-code, not a
settled design.** New `ExperimentSequenceView(QWidget)` in
[qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py): a static, vertically
stacked list of `QGroupBox` "cards," one per named per-repeat step
from `application.py`'s `STEP_*` constants
(`add_step_card(step_name, title, content=None)` /
`step_card(step_name)` / `step_names()`). Each card re-parents an
*existing*, already-validated v2 group-box builder whole -- not
rebuilt, not split field-by-field -- matching this project's
established "v2 reuses validated panel builders instead of a second
implementation" convention. `InitializeExperiment` gets
`_v2_sequence_control_group()`; `ConfigureWfg` gets a new composite of
`_v2_ad2_output_group()` plus the existing FM Sweep and Frequency
Scanning groups side by side; `ConfigureCamera` gets
`_v2_acquisition_group()`; `Flush` gets the existing
`_experiment_flush_group()`. `CaptureFrames`, `WaitForAd2Completion`,
and `SaveResults` currently have no Experiment-tab-specific
configuration of their own (their real behavior is entirely derived
from other steps' settings) -- `add_step_card()` gives those an
honest "No Experiment-tab configuration specific to this step." italic
placeholder rather than inventing content.

**TEC-scan design decision (recorded alongside `application.py`'s
`STEP_*` constants, not re-derived here):** `SetTecTarget`/
`WaitTecStable` wrap the per-repeat step list from *outside*, once per
temperature point -- they are deliberately not cards in this view. The
existing `_experiment_temperature_group()` (TEC Temperature Scan) stays
a separate top-level section in `_center_experiment_area()`, above the
sequence view, matching that same "wraps from outside" relationship
even in Configuration Mode. No live-mode wiring yet -- no in-flight
card highlighting, no per-card failure attribution from
`_report_step()`'s `progress()` events, no point-in-sequence
indicator for the TEC scan. That's Phase 3, not started.

**`_center_experiment_area()` rewritten from a `QGridLayout` to a
`QVBoxLayout`** to accommodate the new sequence view as one more
stacked section alongside the existing status/progress group, TEC
temperature group, and waveform monitoring group -- a layout-container
change only, no field ever moved between groups.

**4 new tests** in [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py):
card count/order/titles match the `STEP_*` constants exactly; each
mapped card genuinely contains the *same* widget instances the rest of
v2 already binds (`window.series_path`, `window.exp_ad2_channels`,
`window.exp_sweep_start_khz`, `window.exp_freq_scan_start_khz`,
`window.exp_camera_fps`, `window.exp_frames`,
`window.exp_flush_flowrate`, `window.exp_wait_after_flush` -- identity
via `QWidget.isAncestorOf()`, not copies); the three placeholder cards
show the honest empty-state text and nothing else; and the TEC-scan
fields (`window.exp_tec_scan_enable`, `window.exp_tec_points`) are
confirmed absent from every step card, staying in their own separate
section as designed.

**Files touched:** [qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py)
(`ExperimentSequenceView`, `_experiment_sequence_view()`,
`_center_experiment_area()` rewrite), [tests/test_qt_ui_v2.py](tests/test_qt_ui_v2.py)
(4 new tests).

**Verification:** tested -- full `tests/` suite green, 323/323 (up
from 319; 4 new tests), modulo the same already-documented (Sessions
41/42/48) offscreen-Qt/Shiboken flakiness (one `qt_ui_v2.py` test hit
it on a full-suite run, confirmed unrelated via a clean isolation
rerun). Not yet committed -- `qt_ui_v2.py` still carries TEC's own
uncommitted diff, so this needs the same hunk-reconstruction-and-verify
discipline as every other TEC-entangled file this session before it
can land.

---

### Session 59 -- GlobalExposure: resolved True-case against real LabVIEW source, made False-case conservative

**Goal:** `Experiment2`'s `GlobalExposure` setting (camera is a Hamamatsu
ORCA-Fusion BT / C15440-20UP, a rolling-shutter sensor with no true global
shutter) is wired to `HamamatsuDcamBackend.configure_trigger_global_exposure()`,
which sets the real DCAM property `DCAM_IDPROP_TRIGGER_GLOBALEXPOSURE`
(`GLOBALRESET` when enabled, `DELAYED` when disabled) -- but that mapping
had never been checked against the actual LabVIEW reference behavior.

**True case confirmed correct.** Found the real hardware-configuration VI
(not just `Experiment2.lvclass:GetGlobalExposure.vi`, which is a trivial
pass-through getter) -- `Hamamatsu.lvclass:ConfigureSequence.vi`'s block
diagram (`main_html/Hamamatsu_lvclass_ConfigureSequenced.png`/`d1.png`).
Its `globalshutter` boolean input feeds a Select node choosing between
numeric constants `0` (false) and `5` (true). `5` is an exact match for
`DCAMPROP_TRIGGER_GLOBALEXPOSURE__GLOBALRESET` in the vendored DCAM-API v4
header (`dcamsdk4/inc/dcamprop.h`) -- `enabled=True -> GLOBALRESET` needed
no change.

**False case: property-ID mismatch investigated, left unresolved.** The
numeric property-ID constant visible at the same call site (`2049680` /
`0x1F4690`, confirmed correct via pixel-level zoom, not a misread) does not
match `DCAM_IDPROP_TRIGGER_GLOBALEXPOSURE`'s real v4 value (`2032384` /
`0x1F0300`) or any other constant in the header. Tried to resolve this by
finding a DCAM-API v3 header or a Hamamatsu version-compatibility document
that might explain a numbering difference: none found locally (repo-wide
search, plus the separate `C:\git\thermacoustics` LabVIEW project repo --
which has real `.vi` binaries but no exposed DCAM headers) nor via web
search (Hamamatsu's own "Compatibility Note" PDFs exist but weren't
fetchable for this specific property; a second, independently-sourced v4
header from SLAC's public EPICS `ADOrcaUsb` module, a different SDK
snapshot than the one vendored here, has byte-identical constants for this
property, weakening but not disproving a version-drift explanation). Also,
LabVIEW's own false-case value (`0`) isn't a valid `TRIGGER_GLOBALEXPOSURE`
enum member at all (valid range 1-5) -- plausibly a "don't touch this
property" sentinel rather than an actual off-value, but that's inference,
not confirmed, since the actual DCAM call node renders as an unreadable
"?" icon in this repo's exported diagrams (an export limitation, not
something fixable from available material).

**Fix applied, matching the conservative option specified for this
outcome:** `HamamatsuDcamBackend.configure_trigger_global_exposure()`
([hamamatsu_dcam.py](src/thermo_acoustic/hamamatsu_dcam.py)) no longer
calls `prop_setvalue()` at all when `enabled=False` -- it leaves
`TRIGGER_GLOBALEXPOSURE` at its prior/default state instead of actively
setting `DELAYED` (the previous, never-verified guess). Rationale: an
unconfirmed guess at a specific "off" mode risked being systematically
wrong for every future experiment's exposure timing; not touching the
property is the safer default until this can be confirmed directly against
the real LabVIEW application (not currently runnable in this environment).

**2 new tests** in
[tests/test_hamamatsu_dcam_lifecycle.py](tests/test_hamamatsu_dcam_lifecycle.py):
`test_configure_trigger_global_exposure_enabled_sets_globalreset` and
`test_configure_trigger_global_exposure_disabled_does_not_set_property`
(added `TRIGGER_GLOBALEXPOSURE`/`DCAMPROP.TRIGGER_GLOBALEXPOSURE` to the
shared `FakeDcamModule` fixture, matching the existing `TRIGGERSOURCE`
pattern -- no prior dedicated backend-level test for this method existed
at all).

**Verification:** tested -- full suite green, 369/369, no regressions.

**Not committed** -- pending review, per standing instruction. See
`docs/known_open_items.md` for the residual False-case uncertainty this
leaves open.

---

### Session 60 -- Documentation backfill: three findings from earlier the
same day, written up for the first time

A full-project audit (code quality, silent-failure, and documentation
consistency passes) found that several real findings/fixes from earlier
in the day had never been logged anywhere -- existing only in
conversation history, the exact failure mode this project's own docs
already warn about. Backfilling now, full detail in
`docs/known_open_items.md`:

1. **`CetoniPump.referenced`/`initialized` flag split** (fix landed
   earlier the same day, before the GlobalExposure work in Session 59).
   `initialize()` was unconditionally setting `referenced = True` despite
   never performing a physical reference/homing move -- found while
   live-testing the real pump (a `0x642` SDK timeout traced back to the
   pump's incremental encoder never having been referenced). Fixed by no
   longer touching `referenced` in `initialize()` (only `reference_move()`
   sets it now, after confirming success); added a new `initialized`
   field for `qt_ui_v2.py`'s pump connection-status row, which had been
   reading `referenced` for that purpose -- a real second bug the fix
   itself would have introduced if left unhandled, caught by running the
   full suite (2 tests failed, both fixed). 2 new tests. Full suite
   369/369 at the time. **Not committed** -- pending review.
2. **Pump `generate_flow()` flow-stop mechanism, resolved: volume-based,
   not time-based.** Two real-hardware data points collected earlier the
   same day, before the CAN-driver incident (below) interrupted further
   testing: `-50` rate stopped at 225.05s/0.187290ml; `-100` rate stopped
   at 114.05s/0.187290ml -- identical stop volume, roughly-halved stop
   time. That's the volume-based signature. A third rate and the
   dispense-to-limit characterization were never run -- deprioritized,
   since the real experiment/flush path never uses `generate_flow()` at
   all, so the exact mechanism has no bearing on real experiment
   correctness. Full detail and reasoning in `known_open_items.md`.
3. **`vci4109w5.sys` (IXXAT VCI4 USB-to-CAN adapter driver) BSOD x3 in one
   session, root-caused and resolved.** All three crashes were bugcheck
   `0x1e` inside the same driver, confirmed via Windows Event Viewer.
   Root cause: outdated driver `4.0.115.0` (2018); resolved by updating to
   `4.0.131.0` (2022, HMS Industrial Networks), confirmed installed via
   `Get-CimInstance Win32_PnPSignedDriver`, no recurrence since. Before
   landing on the driver-version explanation, checked whether the day's
   diagnostic scripts were hammering the CAN bus unusually fast (a
   plausible alternative cause) -- they were not: production's own
   `wait_for_pump()` polls at 20 Hz, the diagnostic scripts used 0.33-2
   Hz, so the crashes were a genuine driver bug, not induced by unusually
   dense polling.

**GlobalExposure False-case status (Session 59) reconfirmed accurate**
during this same audit -- no code touched it since, still OPEN as
documented.

**Verification:** documentation only, no code changed in this entry --
full suite unaffected (still 369/369 from Session 59).

---

### Session 61 -- Centralize instrument enabled/disabled gating at the
orchestration layer; record enabled state in data.tdms

**Root design fix for the AD2Sdk silent-failure finding (Session 60/
full-project audit).** Previously, whether a disabled-but-real instrument
actually touched hardware was decided inconsistently, per-instrument, deep
inside each backend method: `AD2Sdk.pc_trigger()`/`config_wfg()`/
`config_do_clock_special()` silently no-op'd when disabled (and
`pc_trigger()` additionally set `self.triggered = True` regardless --
falsely reporting success); `HamamatsuCamera`/`CetoniPump`/`Valve`'s
methods instead checked `backend is not None`, not `enabled`, so a
disabled-but-not-simulated instance of any of those three would still
attempt real hardware calls. Neither was correct. Moved the decision to
where it belongs -- `Application.run_experiment2()`, the real orchestrator
-- applied uniformly to all four instrument types.

**`application.py` changes:**
- `STEP_CONFIGURE_WFG`: `self.ad2.config_wfg()`/`config_do_clock_special()`
  now only run `if self.ad2.enabled`; fires `"AD2Disabled -- WFG/DO
  configuration skipped"` otherwise.
- `STEP_CONFIGURE_CAMERA`: the entire body (exposure/sequence/global-exposure
  configuration, timing-budget check) gated behind `if self.camera.enabled`.
- `STEP_CAPTURE_FRAMES`: `start_capture()`/`pc_trigger()`/`image_sequence()`/
  `read_frame_timestamps()`/`stop_capture()` each individually gated on the
  relevant instrument's `enabled`; `ad2_triggered_at` now starts `None` and
  the AD2-completion-wait step is skipped entirely (not just short-circuited
  to zero wait) when AD2 was never triggered.
- Flush: now requires `self.pump.enabled and self.valve.enabled` in addition
  to the existing `experiment.flush_enabled` check -- flush() moves fluid via
  the pump between two valve positions, not meaningful with either disabled.
  Skipped (not attempted, not marked failed) with a new
  `"FlushSkippedInstrumentDisabled"` status event; `FlushCompleted` stays at
  its existing `""` ("not attempted") default, same value as "flush wasn't
  requested at all" -- distinguishable from the new `PumpEnabled`/
  `ValveEnabled` TDMS fields (below), not from `FlushCompleted` alone.
- `STEP_SAVE_RESULTS`: camera-touching calls (`save_sequence`,
  `get_camera_buffer_size`, `get_sub_region`, `read_readout_time`) gated the
  same way; falls back to `{"buffer_size": 0, "sub_region": {},
  "readout_time": 0.0}` when camera disabled, keeping the TDMS fields present
  (not silently absent) with values distinguishable via `CameraEnabled`.

**`instruments.py` changes:** new `AD2SdkError(RuntimeError)`.
`AD2Sdk.pc_trigger()`/`config_wfg()`/`config_do_clock_special()` now raise
`AD2SdkError` when `open_and_use_first_device()` returns `None` (which only
happens when `enabled` is `False` -- a real device-open failure raises
inside `WaveFormsBackend.open_device()` instead, never returns a falsy
handle) instead of silently succeeding. Reasoning: after the orchestrator
fix above, the real automated path never reaches these calls while disabled
at all -- reaching them with a `None` handle now indicates a caller bug
(e.g. a manual UI action bypassing an enabled check), not a legitimate
disabled-state outcome to absorb silently. `wfg_configure()`/
`wfg_start_stop_all_ch()`/`config_do_custom()` have the identical
`if handle is not None` pattern but were deliberately **not** changed --
out of scope for this pass (not reachable from `run_experiment2()`, and
`config_do_custom()`'s "DO Custom" feature is separately documented as
legacy/nonessential); flagging for a possible follow-up, not fixing now.

**`workflows.py` changes:** `Experiment2` gets four new fields --
`ad2_enabled`/`camera_enabled`/`pump_enabled`/`valve_enabled` (default
`True`, mirroring the existing `sim_*` fields' shape) -- and
`_settings_properties()` now writes `AD2Enabled`/`CameraEnabled`/
`PumpEnabled`/`ValveEnabled` into `data.tdms` alongside the existing
`SimAD2`/`SimCamera`/`SimPump`/`SimValve`. Closes the metadata gap the
audit identified: previously a run with an instrument genuinely disabled
and a run with it fully active were structurally identical in the saved
record (`Sim*` only captures simulated-vs-real, not enabled-vs-disabled).

**8 new tests** in
[tests/test_application.py](tests/test_application.py): a shared
`_PoisonBackend` (raises `AssertionError` on any attribute access) proves
each disabled instrument's real backend is never touched at all, not just
that the call happens to no-op safely --
`test_run_experiment2_skips_disabled_ad2_steps_without_touching_backend`,
`test_run_experiment2_skips_disabled_camera_steps_without_touching_backend`,
`test_run_experiment2_skips_flush_when_pump_disabled_without_touching_backend`,
`test_run_experiment2_skips_flush_when_valve_disabled_without_touching_backend`
(each also asserting the matching new TDMS field), plus 3 direct unit tests
that `AD2Sdk.pc_trigger()`/`config_wfg()`/`config_do_clock_special()` raise
`AD2SdkError` rather than silently succeeding when disabled. Extended the
existing `test_run_experiment2_records_simulated_vs_real_instruments_in_final_tdms`
with assertions on the four new `*Enabled` fields.

**Found and fixed while writing the new pump/valve tests:** `Application`'s
default `ad2` field is a real, `enabled=True` `AD2Sdk()` (not simulated) --
a pump-disabled/valve-disabled test that didn't also override `ad2=` would
have made `STEP_CONFIGURE_WFG` genuinely try to open a real AD2 device
(`FDwfDeviceOpen`) during a unit test. Not a product bug, a test-authoring
trap worth noting for future tests in this file: any test constructing
`Application(...)` with only some instruments overridden should be
deliberate about what the *un-overridden* ones default to.

**Verification:** tested -- full suite green, 376/376 (369 baseline + 7 new
test functions; one existing test extended, not counted as new), modulo the
same already-documented offscreen-Qt/shiboken flakiness (2 tests hit it on
the full run, both confirmed passing in isolation, unrelated to this
change).

**Not committed** -- pending review, per standing instruction. Did not
touch the uncommitted TEC integration branch's own files/diff.

---

### Session 62 -- Fix the production environment's missing-dependency gap:
manifest + sanity-check script

**Background:** Session 61's real-hardware verification found `exp_ctrl`
(the conda environment `launch_gui.bat` actually uses for production runs)
was missing `npTDMS`, installed as a stopgap at the time. This session
fixes the underlying gap so it can't silently recur.

**Root cause, confirmed not guessed:** `pyproject.toml` already existed and
already correctly declared `npTDMS>=1.10` -- the gap wasn't a missing
declaration, it was that `exp_ctrl` was hand-assembled over time and never
actually built *from* that manifest, so its real installed packages had
drifted from what the project declared. Re-audited every third-party import
reachable from `launch_gui.bat`'s real path (`src/thermo_acoustic/*.py`,
including lazily-imported ones like `clr`/`nptdms`/`serial` that a naive
top-of-file-only import scan would miss) against `exp_ctrl`'s actual `pip
list` output. Found two more of the same class of gap, previously
undetected only because they happened to already be installed: `numpy`
(top-level import in `workflows.py`/`qt_ui.py`) and `pythonnet` (imported
as `clr` in `thorlabs_piezo.py`, needed for the real Z-stage/piezo motion
path) were both real, always-needed dependencies never listed in
`pyproject.toml` at all. Also confirmed `pylablib` (used by
`thorlabs_apt.py`) is *not* part of the real production path -- that module
has zero importers anywhere else in `src/`, only reachable from a
standalone diagnostic script (`hardware_tests/test_thorlabs_apt_discovery.py`).

**Fixes:**
- `pyproject.toml`: added `numpy>=1.24` and `pythonnet>=3.0` to
  `dependencies`; added a new `[project.optional-dependencies]` group
  `thorlabs-apt-discovery = ["pylablib>=0.5"]` for the diagnostic-only
  package, kept out of the core list.
- New `requirements-exp_ctrl.txt` (repo root): exact pinned versions
  currently validated in the real `exp_ctrl` environment (`PySide6==6.11.1`,
  `Pillow==12.2.0`, `pyserial==3.5`, `npTDMS==1.11.0`, `numpy==2.4.6`,
  `pythonnet==3.1.0`, `clr_loader==0.3.1`, plus `pylablib`/`pywin32` in a
  clearly-separated optional section) -- deliberately separate from
  `pyproject.toml`'s loose `>=` bounds, which serve general installability,
  not exact reproduction of the one real machine this actually runs on.
  Documents inline why vendor SDKs (Qmix, DCAM, Kinesis) aren't and can't be
  covered by a pip requirements file.
- New `tools/check_environment.py`: imports every real core dependency and
  reports pass/fail per package (plus optional ones, non-fatally). Exit 0
  if complete, exit 1 naming exactly what's missing. Verified against both
  `exp_ctrl` (all green) and the unrelated `base`/pytest environment
  (correctly reports `pythonnet` missing there) -- confirms it actually
  discriminates a complete environment from an incomplete one, not just
  prints green unconditionally.
- New `README.md` "Environment Setup" section: how to recreate `exp_ctrl`
  from `requirements-exp_ctrl.txt`, and to run
  `tools/check_environment.py` after setup or whenever drift is suspected.

**Verification:** tested -- full suite green, 376/376, no regressions
(`pyproject.toml`'s TOML validity double-checked via `tomllib.load()`
before running pytest, since pytest itself reads this file for
`[tool.pytest.ini_options]`). `tools/check_environment.py` manually run
against both `exp_ctrl` (exit 0) and `base` (exit 1, correctly identifying
the missing package) to confirm it actually discriminates, not just a
script that always prints success.

**Not committed** -- pending review, per standing instruction. Did not
touch the uncommitted TEC integration branch, and made no changes to the
dev/test environment used for pytest (scope was `exp_ctrl` only, per
instruction).

---

### Session 63 -- Fix the HIGH/MEDIUM findings from instruments.py's
line-by-line review

**H1 -- `CetoniPump.set_fill_level()`'s optimistic update never re-synced
on a flush timeout, fixed.** `set_fill_level()` sets `self.fill_level` to
the requested target immediately, before the real (asynchronous) pump move
is confirmed -- correct once `wait_for_pump()` confirms arrival, silently
wrong if it times out (`Application.flush()`'s existing `if not completed:
return False` path), since nothing re-synced it from real hardware on that
path. A later flush's own over-draw guard
(`flush_volume_ml > self.pump.fill_level`) would then trust a fabricated
number instead of reality. **Fixed:** new `CetoniPump.sync_fill_level()`
([instruments.py](src/thermo_acoustic/instruments.py)) -- the single
canonical place this project's repeated "read back the real fill level"
pattern now lives (`initialize()`/`refill()` refactored to call it too,
identical behavior, just de-duplicated); `Application.flush()`'s timeout
path now calls it before returning `False`. Deliberately does **not**
catch a failure from the re-sync read itself -- a pump that's both
unconfirmed *and* unreadable must not be silently absorbed into an
ordinary-looking `False` return. **1 new test**,
`test_flush_resyncs_fill_level_from_real_hardware_when_wait_for_pump_times_out`
([tests/test_application.py](tests/test_application.py)), using a fake
backend reporting a real fill level distinct from the optimistic target,
confirming the post-timeout value is the real one, not the fabricated one.

**Verification:** tested -- full suite green (see final tally below).

**Not committed** -- pending review, per standing instruction.

**H2 -- `CetoniPump.cleanup()` didn't reset `initialized`, fixed; the
`ZStage.cleanup()` half of this finding was a review mistake, corrected
here, not fixed (there was nothing to fix).** `initialized` (added earlier
today for `qt_ui_v2.py`'s pump connection-status row) was never reset back
to `False` in `cleanup()`, unlike `Valve.cleanup()`'s existing correct
`self.initialized = False`. **Fixed:** added the same reset to
`CetoniPump.cleanup()`. **Correction:** the review also flagged
`ZStage.cleanup()` as having the same gap for `status_note` -- re-reading
the live file before touching it found `self.status_note = ""` already
present there ([instruments.py:955-958](src/thermo_acoustic/instruments.py:955)),
and existing tests (`tests/test_application.py:904-906`, `:1069-1071`)
already cover it. The original review's claim about `ZStage` was simply
wrong -- noted here rather than silently dropped, and rather than "fixing"
something that wasn't broken. **1 new test**,
`test_cetoni_pump_cleanup_resets_initialized`
([tests/test_application.py](tests/test_application.py)).

**Verification:** tested -- full suite green (see final tally below).

**Not committed** -- pending review, per standing instruction.

**M1 -- `SerialTextCommandBackend.close()` could wedge `self.port`
permanently if `port.close()` raised, fixed.** `self.port = None` only ran
after `port.close()` returned -- a raise left `self.port` set to the
broken handle, so a future `_open()` would see it as "already open" and
skip reopening, and a future `close()` would try to close the same broken
handle again. **Fixed:** wrapped in `try/finally` so the reset happens
regardless; the exception itself still propagates normally (`log_call()`
logs and re-raises, unchanged). **1 new test**,
`test_close_resets_port_to_none_even_when_port_close_raises`
([tests/test_instruments.py](tests/test_instruments.py)), using a fake
port whose `close()` raises -- confirms the exception still propagates,
`self.port` is `None` afterward, and a second `close()` call doesn't
attempt to close the same broken port again.

**Verification:** tested -- full suite green (see final tally below).

**Not committed** -- pending review, per standing instruction.

**M2 -- `Valve.set_position()` assigned `self.position` before confirming
the write reached the device, fixed.** Same optimistic-update shape as H1,
on the valve: `self.position = position` ran before `backend.write()`, so
a raised exception left `self.position` claiming a move that was never
sent. **Fixed:** moved the assignment to after `backend.write()` returns
without raising. Checked every real caller (`application.py`'s two
`flush()`/`run_temperature_series()` call sites, `qt_ui.py`'s Valve Pos1/
Pos2 buttons, the confirmed-dead `ui.py`) -- none reads `self.valve.position`
in the same expression as the `set_position()` call, so nothing depends on
the old ordering. **1 new test**,
`test_valve_set_position_does_not_update_position_when_write_raises`
([tests/test_application.py](tests/test_application.py)).

**Verification:** tested -- full suite green, 380/380.

**Not committed** -- pending review, per standing instruction.

**M3 -- extended this morning's AD2Sdk enabled-gating fix
(`pc_trigger()`/`config_wfg()`/`config_do_clock_special()`) to the 8
remaining methods with the identical silent-no-op shape.** Fixed:
`wfg_configure()`, `wfg_start_stop_all_ch()`, `config_do_custom()`,
`do_configure()`, `do_reset()`, `start_stop_do()`, `capture_scope()`,
`capture_scope_channels()` -- all now raise `AD2SdkError` instead of
silently no-op'ing (or, for the two `capture_scope*` methods, silently
returning `[]`/`{}`) when reached with AD2 disabled. **Highest-value fix
in this set:** `capture_scope()`/`capture_scope_channels()` are live and
manually reachable (`qt_ui.py`'s MSO tab, `_mso_capture()`) -- previously
returned misleadingly-empty capture data with zero indication AD2 was
disabled, indistinguishable from a real capture that genuinely returned
zero samples. Confirmed the real UI caller already runs through
`_run_action()`/`ActionWorker` (the same pattern already verified to
catch and cleanly surface `AD2SdkError` for `config_wfg()`'s "Apply WFG"
button) -- not a crash. Two standalone diagnostic scripts,
`tools/capture_ad2_wavegen_scope.py` and
`tools/capture_ad2_wavegen_scope_matplotlib.py`, call `capture_scope()`
directly (not through the UI) -- if AD2 is disabled there, they'll now
show a clear Python traceback instead of silently plotting nothing,
which is the right failure mode for a standalone CLI tool. **8 new
tests** in [tests/test_application.py](tests/test_application.py), same
`_PoisonBackend`-based pattern as this morning's `pc_trigger()`/
`config_wfg()`/`config_do_clock_special()` tests.

**Verification:** tested -- full suite green, 388/388.

**Not committed** -- pending review, per standing instruction.

---

### Session 64 -- Fix the HIGH finding from qmix_backend.py's line-by-line
review: refill()/empty() never waited for real completion

**`CetoniPump.refill()`/`empty()` issued the same asynchronous, target-based
`set_fill_level()` SDK call `flush()` uses, but nothing ever waited for the
real pump to arrive -- the third instance today of the optimistic-update-
without-confirmation shape (after `CetoniPump.set_fill_level()`'s own H1 fix
and `Valve.set_position()`'s M2 fix).** Traced through the real call chain:
`CetoniPump.refill()`'s own internal fill-level sync ran immediately after
issuing the move, before any wait -- reading back a premature, likely
still-in-progress value even on what would otherwise look like a normal,
successful call. The manual "Refill"/"Empty" buttons
(`qt_ui.py`) called `self.app.pump.refill()`/`empty()` directly, bypassing
`Application` (and its `wait_for_pump()` machinery) entirely.

**Fix, following the existing architectural precedent rather than inventing
a new one:** new `Application.refill()`/`Application.empty()`
([application.py](src/thermo_acoustic/application.py)) -- issue the move via
`self.pump.refill()`/`empty()`, call the same `wait_for_pump(timeout_s)`
`flush()` already uses (default `timeout_s=60.0`, mirroring
`QmixPumpBackend.reference_move_timeout_s`'s own default -- no
`FlushSettings`-equivalent volume/flowrate-derived formula exists for these,
since neither takes a caller-supplied settings object), then **always**
re-sync `fill_level` from real hardware afterward -- not only on timeout
(unlike `flush()`'s own conditional-only-on-timeout shape): because
`CetoniPump.refill()`/`empty()`'s own internal sync already ran before the
wait, even the success path needs a fresh post-wait read, not just the
failure path. Return `True`/`False` matching `flush()`'s own contract; fires
`"RefillComplete"`/`"RefillTimedOut"` (and the `Empty` equivalents) status
events.

**`qt_ui.py`'s "Refill"/"Empty" buttons updated** to call new `_refill()`/
`_empty()` wrapper methods (which call `self.app.refill()`/`empty()` and
convert the bool result to a status string), matching `_flush()`'s own
already-established wrapper pattern just above it -- not the raw
`self.app.pump.refill()`/`empty()` calls from before. `qt_ui_v2.py` needed no
separate change -- confirmed it has no direct call site of its own, reusing
v1's Pump&Valve panel builder as usual.

**4 new tests** in [tests/test_application.py](tests/test_application.py)
(`test_application_refill_waits_for_completion_and_ends_with_accurate_fill_level`,
`test_application_refill_resyncs_fill_level_from_real_hardware_when_wait_for_pump_times_out`,
and the `Empty` equivalents), reusing the same `_FakePumpBackendWithRealFillLevel`
fixture the flush H1 test already established (extended with no-op
`refill()`/`empty()` methods).

**Verification:** tested -- full suite green, 392/392.

**Not committed** -- pending review, per standing instruction. No TEC-related
code exists in `qmix_backend.py`; not applicable here.

---

### Session 65 -- Fix the three MEDIUM findings from hamamatsu_dcam.py's
line-by-line review

**Finding 1 -- `configure_sequence()`'s optimistic `sequence_settings`
update (the same shape found twice already in Sessions 63/64, this time in
software state rather than physical motion).**
[hamamatsu_dcam.py](src/thermo_acoustic/hamamatsu_dcam.py) previously
assigned `self.sequence_settings = settings or {}` *before*
`_configure_sequence_properties()` applied any of the individual DCAM
property writes -- a mid-sequence failure (an unsupported
`masterpulse_mode`, an out-of-range `masterpulse_interval_s`, ...) left
`sequence_settings` reflecting the requested-but-unconfirmed configuration.
`_sequence_buffer_frame_count()` reads `sequence_settings["frames"]` to size
the buffer for the *next* capture, so a retry after a partial failure could
size a buffer against a configuration the real device never actually got.
**Fix:** `_configure_sequence_properties()` now takes `settings` as a
parameter instead of reading `self.sequence_settings`; `configure_sequence()`
only commits `self.sequence_settings = new_settings` after the whole method
returns without raising, so a failure leaves it at the last *confirmed*
configuration, not a third, distinct "partially applied" state.

**Finding 2 -- `_ensure_buffer()`'s `buf_release()` failure was silently
swallowed with a bare `except Exception: pass`,** the identical shape
already identified and fixed as "Finding F" in `close()`
(Session 51/52-era work) but never swept into this second call site.
**Fix:** logs via `logger.error()` + `log_transaction(..., success=False)`,
same pattern as `close()`'s two cleanup steps -- retry behavior (the
subsequent `buf_alloc()` call) is unchanged, only the silence is fixed.

**Finding 3 -- `read_readout_time()` could not distinguish "property
genuinely unsupported on this camera" from "the property exists but the
live query call failed,"** collapsing both to a plausible-looking `0.0`.
Traced the consequences of that masking to two real call sites:
`application.py`'s `experiment.save_camera_settings(...)` writes it straight
through to TDMS as `ReadoutTime` (permanent experiment metadata), and
`Application._check_camera_timing_budget()` -- a real safety check that
raises `ValueError` if the configured Camera FPS exceeds what
exposure+readout can sustain -- fed a masked failure in as an artificially
low readout time, which could let an unachievable FPS silently pass the
check. **Fix:** genuine query failures (property exists, `prop_getvalue()`
itself returns `False`) now return `None` -- this project's existing
"value unavailable" TDMS sentinel (`_tdms_scalar()` already maps
`None -> ""`, distinguishable from a real `0.0` reading in the written
file) -- logged as a failed transaction via `log_transaction`, not raised
(this is a metadata read, not a command that leaves hardware in an
unconfirmed state). The genuinely-unsupported-property case still returns
`0.0` unchanged. `_check_camera_timing_budget()` (application.py) now
explicitly checks for `None` and raises its own `ValueError` with a clear
message instead of crashing on `max(None, 0.0)` or silently treating
"unknown" as "0 seconds, FPS is fine." Return-type hints widened to
`float | None` in `hamamatsu_dcam.py` and `instruments.py`'s
`HamamatsuCamera.read_readout_time()` passthrough.

**5 new tests:** `test_configure_sequence_partial_failure_does_not_update_sequence_settings`
([tests/test_hamamatsu_dcam_lifecycle.py](tests/test_hamamatsu_dcam_lifecycle.py),
Finding 1 -- forces a real partial hardware write via a fake `Dcam` whose
`prop_setvalue()` fails only for the second property);
`test_ensure_buffer_logs_swallowed_buf_release_failure_instead_of_silently_passing`,
`test_read_readout_time_returns_none_on_genuine_query_failure_not_zero`,
`test_read_readout_time_still_returns_real_zero_when_device_reports_it`, and
`test_check_camera_timing_budget_raises_when_readout_time_unavailable`
([tests/test_application.py](tests/test_application.py)).

**Finding 4 (LOW, not fixed)** -- `_stop_capture_if_active()` clears
`capture_active = False` in a `finally` block even when the real
`cap_stop()` call raises. Left as-is per its own reasoning (the exception
is still raised/logged, not swallowed -- a caller has to actively ignore it
to hit the false-idle-state scenario) and backlogged in
[known_open_items.md](known_open_items.md).

**Verification:** tested -- full suite green, 397/397 (one run hit the
already-documented pre-existing offscreen-Qt/shiboken flakiness in
`test_qt_ui_v2.py::test_v2_every_value_widget_has_a_tooltip_and_visible_marker`,
confirmed via isolation rerun to pass alone -- unrelated to this session's
changes, which touch only `hamamatsu_dcam.py`/`instruments.py`/`application.py`).

**Not committed** -- pending review, per standing instruction. No
TEC-related code exists in `hamamatsu_dcam.py`; not applicable here.

---

### Session 66 -- Fix the two findings from waveforms.py's line-by-line
review (1 local, 1 in instruments.py's AD2Sdk)

**Finding 1 -- `configure_do()`'s `output_mode` silently fell back to
"pushpull" for any unrecognized string, with no validation anywhere
upstream.** Unlike `function`/`trigger_source` (real
`WaveformFunction`/`TriggerSource` enums, pre-validated -- well, silently
defaulted, see Finding 3 below -- by `ad2.py`'s `_coerce_enum()` before
ever reaching this file), `DoSingleChannelConfig.output_mode` is a plain
`str` field with zero upstream validation
(`coerce_do_channel_config()` just casts to `str`). `waveforms.py:599`
was the *only* point in the whole pipeline that could ever catch a typo,
and it silently substituted push-pull drive mode instead of raising.
**Fix:** new `_output_mode_value()` helper
([waveforms.py](src/thermo_acoustic/waveforms.py)) raises `WaveFormsError`
listing the valid options when `output_mode` doesn't match any known key.
Deliberately did **not** add a second validation layer in `ad2.py`'s
`coerce_do_channel_config()`: `_OUTPUT_MODES` is `WaveFormsBackend`-only
mapping data, `ad2.py` cannot import `waveforms.py` (circular --
`waveforms.py` already imports from `ad2.py`), and duplicating the
valid-values set in two files would create two sources of truth that
could silently drift -- a worse outcome than one well-placed check. This
also matches the `hamamatsu_dcam.py` ROI-validation precedent: validation
lives where the domain-specific limits/mapping data actually lives, not
in the plain-dataclass module above it.

**Finding 2 -- the 5th instance today of the optimistic-update-before-
confirmation shape, in `instruments.py`'s `AD2Sdk`.**
`config_wfg()`, `wfg_configure()`, `config_do_custom()`, and
`config_do_clock_special()` all committed the new config to
`self.wfg_config`/`self.do_config`/`self.do_custom_config`/
`self.do_clock_settings` *before* the real `WaveFormsBackend` call was
confirmed to succeed -- discovered while verifying (per explicit
instruction, not assumed) whether `waveforms.py` sits under any of this
morning's AD2Sdk disabled-state fixes with its own independent gap; it
didn't (see the waveforms.py review's pattern-(c) verdict), but tracing
that boundary surfaced this separate, unrelated pattern-(a) issue in the
same four methods M3 touched this morning for a different reason.
**Traced downstream consumers first, as instructed:** TDMS metadata for
WFG/DO settings is built from `Experiment2.wfg_config`/
`Experiment2.do_clock_settings` directly ([workflows.py:218-219](src/thermo_acoustic/workflows.py:218))
-- a completely separate field from `AD2Sdk`'s, set once by the caller at
experiment-construction time -- so this bug does **not** reach permanent
experiment metadata. No UI display reads `AD2Sdk.get_wfg_config()`/
`get_do_config()` either (`wfg_configure_read_back()` exists for that
purpose per its LabVIEW-parity name but has zero call sites in
`qt_ui.py`/`qt_ui_v2.py` today). The only other consumers are `AD2Sdk`'s
own single-channel staging methods (`wfg_configure_carrier_single_ch()`
etc.), which are *intentionally* pre-hardware-call, no-confirmation
staging mutations by design (they issue no backend call at all) --
different in kind from the four fixed methods, which do call hardware as
part of the same call. No legitimate "show the requested-but-unconfirmed
value" consumer was found, so no separate staging field was needed.
**Fix:** each of the four methods now coerces the config into a local
variable, issues the real backend call with it, and only assigns it to
the persistent field(s) after that call returns without raising.

**Not fixed, flagged for your triage:** `AD2Sdk.do_configure()`
([instruments.py:376-381](src/thermo_acoustic/instruments.py:376)) has
the identical shape but wasn't one of the four methods named in this
task's scope -- left untouched.

**4 new regression tests** (one per fixed method) in
[tests/test_application.py](tests/test_application.py), using a new
`FakeWaveFormsBackendThatRaisesOnConfigure` fixture (a `fail` flag
toggled after an initial successful call establishes a real "last
confirmed" config) -- each asserts the field still points to the exact
same object after a failing second call, not a new one reflecting the
failed request. Plus 2 new tests for Finding 1
(`test_configure_do_rejects_unsupported_output_mode_instead_of_defaulting_to_pushpull`,
`test_configure_do_accepts_known_output_modes_case_and_space_insensitively`).

**Finding 3 (LOW, not fixed)** -- `_enum_value()`'s silent
default-value fallback ([waveforms.py:193-198](src/thermo_acoustic/waveforms.py:193))
is currently dead code (all four enum-to-int mappings it backs are
exhaustive 1:1 matches of their enums, and `ad2.py`'s own `_coerce_enum()`
already independently silently-defaults before values reach this file)
but has no test enforcing the enum/mapping stay in lockstep. Backlogged in
[known_open_items.md](known_open_items.md).

**Verification:** tested -- full suite green, 403/403.

**Not committed** -- pending review, per standing instruction. No
TEC-related code exists in `waveforms.py`; not applicable here.

---

### Session 67 -- Fix Finding 1 from application.py's line-by-line review:
dict-input WfgConfig/DoConfig clamping data loss

**`run_experiment2()`'s deliberate "re-snapshot settings after
config_wfg()/config_do_clock_special()" mechanism -- added specifically so
`WFGOutOfRangeCh1`/`Ch2` and `DOFreqActual` in `data.tdms` reflect real
hardware clamping, not pre-configure defaults -- silently failed to work
whenever `Experiment2.wfg_config`/`do_clock_settings` started out as a
dict instead of a typed `WfgConfig`/`DoConfig` object.** Root cause:
`coerce_wfg_config()`/`coerce_do_config()` ([ad2.py](src/thermo_acoustic/ad2.py))
return the *same* object unchanged when already typed, but build a
brand-new, disconnected object from a dict. `AD2Sdk.config_wfg()`/
`config_do_clock_special()` coerce `experiment.wfg_config`/
`do_clock_settings` internally -- when that's a dict, the object
`WaveFormsBackend.configure_wfg()`/`configure_do()` actually mutates with
the real clamping result was never the same object the second
`save_settings()` call reads back. `Experiment2.wfg_config`'s own type
hint (`WfgConfig | dict[str, Any] | None`) documents dict as a supported
input, and it's exercised by `tests/test_application.py`,
`tests/test_full_flow_dry_run.py`, and -- notably -- 
[hardware_tests/test_real_workflow_smoke.py](hardware_tests/test_real_workflow_smoke.py:854),
a real-hardware test script. Not reachable through the live GUI today
(`qt_ui.py` always constructs a real `WfgConfig`), but a live risk for any
future dict-based caller (e.g. a preset-loading feature).

**Fix location decided by checking every other caller of
`coerce_wfg_config()`/`coerce_do_config()` first, as instructed:**
`application.py`'s own `_ad2_completion_wait_seconds()`/
`_configured_camera_fps()` and several `AD2Sdk` methods call these
coercion functions purely to *read* -- making them mutate a caller-supplied
dict in place (the alternative fix location) would be a surprising,
undocumented side effect on every one of those read-only call sites, and
would also require reverse-mapping the clamping results back onto
whichever of several key-name aliases (`frequency_hz`/`frequencyHz`/
`frequency`/`freq`, etc. -- see `_first_present()`) the original dict
happened to use. Instead, fixed at the true point of divergence:
`run_experiment2()` ([application.py](src/thermo_acoustic/application.py))
now reassigns `experiment.wfg_config = self.ad2.get_wfg_config()` and
`experiment.do_clock_settings = self.ad2.get_do_config()` immediately
after `config_wfg()`/`config_do_clock_special()` succeed (inside the
`if self.ad2.enabled:` branch only) -- `AD2Sdk`'s own fields are only ever
set post-confirmation since Session 66's Fix 2, so this makes
`experiment.wfg_config`/`do_clock_settings` point at the confirmed,
clamped object regardless of which type they started as, with zero
changes to `coerce_wfg_config()`/`coerce_do_config()` themselves.

**1 new test:**
`test_run_experiment2_records_real_wfg_clamping_in_final_tdms_when_wfg_config_is_a_dict`
([tests/test_application.py](tests/test_application.py)) -- mirrors the
existing typed-`WfgConfig` regression test for the original "Finding A"
bug, but with a dict-shaped `wfg_config`. Verified end-to-end: manually
disabled the fix (commented out the two reassignment lines), confirmed
the new test fails with a clear assertion (`experiment.wfg_config` still
a plain `dict`, not the confirmed `WfgConfig`), then restored the fix and
confirmed it passes.

**Findings 2 and 3 (LOW, not fixed)** -- both already correctly assessed
in the review as currently-unreachable/inherited limitations, not live
bugs: `handle_message()`'s `CETONI_REFILL`/`CETONI_EMPTY` branches still
bypass this morning's `Application.refill()`/`empty()` H1 fix (confirmed
unreachable -- `qt_ui.py` never drives the message-queue dispatch path),
and `wait_for_pump()`'s single boolean return can't distinguish abort
from timeout (pre-existing `flush()` behavior, correctly inherited by
today's `refill()`/`empty()`, not a new bug). Backlogged in
[known_open_items.md](known_open_items.md).

**Verification:** tested -- full suite green, 404/404. The fix's
`self.ad2.get_wfg_config()`/`get_do_config()` calls initially broke 18
tests in `tests/test_full_flow_dry_run.py`, whose minimal `FakeAD2` test
double didn't implement those methods (only `config_wfg()`/
`config_do_clock_special()`) -- fixed by having `FakeAD2` track and
return the config it was given, matching what a real `AD2Sdk` returns
post-Session-66-Fix-2. Two separate runs each hit one already-documented
pre-existing offscreen-Qt/shiboken flake (different test each time,
same `SystemError: ... returned NULL without setting an exception`
signature), both confirmed via isolation rerun to pass alone -- unrelated
to this session's changes, nowhere near `application.py`/`ad2.py`.

**Not committed** -- pending review, per standing instruction. No
TEC-related code touched; `run_temperature_series()` calls into
`TecController` only at the boundary (`apply_static_setpoint()`,
`wait_until_stable()`), not reviewed or modified.

---

### Session 68 -- Fix Finding 1 from workflows.py's line-by-line review:
missing WfgChannelConfig fields in data.tdms

**`_wfg_properties()` only ever recorded `carrier.frequency_hz`/
`amplitude_v`, `trigger.sec_run`/`sec_wait`/`repeat_count`, and
`out_of_range` per WFG channel -- real, user-editable Experiment-tab
fields (`carrier.function`, `carrier.offset_v`, `carrier.symmetry_percent`,
`carrier.phase_deg`, `trigger.source`, and the entire `fm_mod` sub-carrier)
were never written to `data.tdms` at all, so a saved experiment's actual
waveform shape (or FM-modulation settings) could not be reconstructed
after the fact.** Confirmed these are real, live GUI fields, not
theoretical: `qt_ui.py`'s `exp_ch1_function`/`exp_ch1_offset`/
`exp_ch1_symmetry`/`exp_ch1_phase` widgets and the FM sub-carrier group
are all user-editable on the Experiment tab.

**Fix:** `_wfg_properties()` ([workflows.py](src/thermo_acoustic/workflows.py))
now also records `WFGFunction{Ch}`/`WFGOffset{Ch}`/`WFGSymmetry{Ch}`/
`WFGPhase{Ch}`/`WFGTriggerSource{Ch}`, following the file's existing
`WFG<Field><Suffix>` naming convention. New `_wfg_fm_mod_properties()`
helper adds the `fm_mod` sub-carrier as its own `WFGFM<Field><Suffix>`
cluster (`WFGFMEnabled`/`WFGFMFreq`/`WFGFMAmp`/`WFGFMFunction`/
`WFGFMOffset`/`WFGFMSymmetry`/`WFGFMPhase`), mirroring
`_fm_sweep_properties()`'s existing "gate on enabled, degrade the rest to
`\"\"`" pattern for the top-level FM sweep feature -- `WfgChannelConfig.
fm_mod` is never actually `None` (its dataclass default is
`CarrierSettings(enable=False)`, not `None`), so reporting its own
default `frequency_hz`/`amplitude_v` unconditionally would misleadingly
look like real applied FM-mod settings when FM mod was never active;
gating on `fm_mod.enable` avoids that. Both the channel-absent case
(existing) and the new fm_mod-disabled case degrade to the same `""`
sentinel convention already used throughout this file. `WaveformFunction`/
`TriggerSource` (both `str, Enum`) are stored as the raw enum member,
matching this file's existing convention of storing raw typed values and
letting `_tdms_scalar()` do the final `Enum -> .value` conversion at
write time (confirmed via `_tdms_scalar()`'s explicit `isinstance(value,
Enum)` branch) -- not manually `str()`'d at the call site.

**2 new tests**
(`test_experiment2_writes_wfg_carrier_trigger_and_fm_mod_fields_to_tdms`,
`test_experiment2_wfg_fm_mod_fields_default_to_sentinel_when_channel_absent`)
in [tests/test_application.py](tests/test_application.py), using
distinguishable non-default values for every new field (Ch1 with fm_mod
enabled, Ch2 with fm_mod left at its disabled default) plus a
channel-entirely-absent case, so a bug reading the wrong field,
hardcoding a default, or conflating the two different "unavailable"
cases (channel absent vs. fm_mod disabled) would be caught.

**Findings 2, 3, and the DO-channel-selection omission (all LOW,
not fixed)** -- backlogged in [known_open_items.md](known_open_items.md):
the `"FlushCompleted": ""` unenforced call-order invariant,
`_git_commit_hash()`'s process-lifetime cache, and
`_settings_properties()`'s DO-channel selection only recording the first
enabled DO channel (currently unreachable -- `qt_ui.py`'s
`_experiment_do_clock_config()` only ever configures one).

**Verification:** tested -- full suite green, 406/406.

**Not committed** -- pending review, per standing instruction. No
TEC-related code exists in the fixed portion of `workflows.py`;
`TemperatureSeries` (this file's own TEC-scheduling dataclass) was
reviewed but not touched by this fix.

---

### Session 69 -- Fix Finding 1 from the targeted qt_ui.py/qt_ui_v2.py UI
audit: "GO" button bypasses fill-level confirmation

**The manual "GO" button (`_start_go_level()`) had the exact same
fire-and-forget bug refill()/empty() were fixed for the same day
(Session 64's H1 fix) -- it just wasn't in that fix's scope, since it's a
different button (arbitrary-level pump moves, not full/empty).** Called
`self.app.pump.set_fill_level()` directly: no wait for the real pump to
arrive, no re-sync afterward, so `self.pump.fill_level` was left at
`set_fill_level()`'s own optimistic target if the move didn't actually
complete -- the same scenario the H1 fix's comment explicitly worried
about (a later `flush()`'s over-draw guard trusting a fabricated number).

**Fix:** new `Application.go_to_level(level, flow_rate=None,
timeout_s=60.0)` ([application.py](src/thermo_acoustic/application.py)),
the exact `refill()`/`empty()` pattern reused verbatim (not redesigned,
per instruction): issue the move via `self.pump.set_fill_level()`, wait
via `wait_for_pump(timeout_s)`, then unconditionally re-sync
`fill_level` from real hardware regardless of timeout/success. Fires
`"GoToLevelComplete"`/`"GoToLevelTimedOut"` status events, matching the
`Refill`/`Empty` naming convention. `qt_ui.py`'s `_start_go_level()` now
routes through a new `_go_to_level()` wrapper (converts the bool result
to a status string, same shape as `_refill()`/`_empty()`) instead of
calling `self.app.pump.set_fill_level()` directly.

**2 new tests**
(`test_application_go_to_level_waits_for_completion_and_ends_with_accurate_fill_level`,
`test_application_go_to_level_resyncs_fill_level_from_real_hardware_when_wait_for_pump_times_out`)
in [tests/test_application.py](tests/test_application.py), mirroring the
existing `refill()`/`empty()` tests exactly (same `_FakePumpBackendWithRealFillLevel`
fixture, no changes needed to it).

**Finding 2 (`wfg_start_stop_all_ch()`) folded into the existing
`do_configure()` backlog entry** in
[known_open_items.md](known_open_items.md) (same root cause, confirmed
reachable from the manual WFG tab and the Abort path). **Finding 3**
(no general per-channel FM-mod control on the Experiment tab) added as a
short feature-completeness note in the same entry -- not a bug,
independently confirmed no misleading "looks editable but ignored"
widget exists for it.

**Verification:** tested -- full suite green, 408/408, first run clean.

**Not committed** -- pending review, per standing instruction. No
TEC-related code touched.

**This closes the module review queue:** `instruments.py` →
`qmix_backend.py` → `hamamatsu_dcam.py` → `waveforms.py` →
`application.py` → `workflows.py` → `qt_ui.py`/`qt_ui_v2.py`. Across
the six full reviews plus this targeted UI audit: 14 real bugs found
and fixed (5 in `instruments.py`, 1 in `qmix_backend.py`, 3 in
`hamamatsu_dcam.py`, 2 in `waveforms.py`/its `AD2Sdk` layer, 1 in
`application.py`, 1 in `workflows.py`, 1 in `qt_ui.py`), plus a
documented backlog of low-priority items in `known_open_items.md`.

---

### Session 70 -- Backfill: fix for `do_configure()`/`wfg_start_stop_all_ch()`'s
optimistic-commit shape (landed without a changelog entry)

**Documentation backfill, not new work this session.** The documentation-
accuracy audit following the module review series (2026-08-02) found
`AD2Sdk.do_configure()` and `AD2Sdk.wfg_start_stop_all_ch()` already
fixed in the working tree -- both now use the same commit-after-
confirmation shape as `config_wfg()`/`wfg_configure()`/`config_do_custom()`/
`config_do_clock_special()` (Session 66's Fix 2), with passing regression
tests (`test_do_configure_leaves_do_config_unchanged_when_backend_call_fails`,
`test_wfg_start_stop_leaves_wfg_config_unchanged_when_backend_call_fails`
in `tests/test_application.py`) -- but with no comment marker or
changelog entry of the kind every other fix this session recorded.
`known_open_items.md`'s own backlog entry for these two methods had
already been correctly updated in place to note the fix (dated
2026-08-02), so the *information* was never wrong anywhere -- only this
file's narrative record was missing, breaking from the
one-doc-plus-one-narrative-entry convention every other fix in this
series followed. This entry closes that gap; see `known_open_items.md`'s
`waveforms.py` backlog entry for the technical detail (both methods now
build the coerced config into a local variable, issue the real backend
call, and only commit it to `self.do_config`/`self.wfg_config` after
that call succeeds -- `wfg_start_stop_all_ch()` additionally configures
a *copy* of the current `WfgConfig`, not the live one, so a failed
attempt can't leave it half-mutated either).

**Verification:** confirmed via `git show HEAD:...` that the committed
version still has the pre-fix optimistic-commit code (so this is a real,
already-landed working-tree fix, not a documentation error going the
other direction), and via the two regression tests above passing against
current code.

**Not committed** -- pending review, per standing instruction, same as
everything else in this series.

---

### Session 71 -- CORRECTION: tooltip text does not actually auto-wrap on
real Windows; Session 41's claim (and this session's own initial
re-confirmation of it) were both wrong

**Correcting a false claim that has stood in this changelog since Session
41, not a new regression.** Session 41 stated "Tooltip text auto-wrap
confirmed, not just assumed... `QToolTip.showText()` wraps Qt's standard
tooltip rendering, which auto-wraps long text at a reasonable pixel width
by default." An earlier pass in this same broader session re-derived and
restated the identical conclusion ("Step 2c needs no code change")
independently, via its own offscreen-platform measurement -- both were
wrong, caught only when the user captured a real desktop screenshot of the
MSO tab's Range (V) tooltip (`self.mso_range`, [qt_ui.py:673-678](src/thermo_acoustic/qt_ui.py:673))
rendering as one long unwrapped line.

**Root cause of both false verifications: the "offscreen" QPA platform
cannot reproduce this bug at all, by construction, not through bad luck.**
On real Windows, `QToolTip` delegates to the native OS tooltip control,
which does **not** word-wrap plain text. The "offscreen" platform has no
native OS window system to delegate to, so it always falls back to Qt's
own internal QLabel-based tooltip renderer -- which *does* auto-wrap,
regardless of text length or platform. Confirmed directly: triggering the
exact real click-triggered code path (`_TooltipIconButton._show_explanation()`
-> `QToolTip.showText()`) for `mso_range`'s real 307-character tooltip
under `QT_QPA_PLATFORM=offscreen` produced a wrapped 476x130 label every
time, for every tooltip tried, regardless of length -- there was no
offscreen test that could have caught this, since the platform itself
never exercises the code path where the bug lives.

**Real fix:** `_wrap_with_tooltip_icon()` ([qt_ui.py:1592-1624](src/thermo_acoustic/qt_ui.py:1592))
-- the single choke point all 142 tooltip-bearing widgets already pass
through -- now wraps the tooltip text in a minimal HTML tag
(`f"<html>{html.escape(tip)}</html>"`) before setting it, both on the
field widget's own `.toolTip()` (still set and reachable via plain hover,
never cleared -- both trigger paths needed the same fix, not just the
icon button's explicit call) and on `_TooltipIconButton`'s stored
explanation. This is Qt's own documented mechanism for forcing
`QToolTip` to render as word-wrapped rich text regardless of platform.
Escaped, not raw HTML, so a literal `&`/`<`/`>` in tooltip text (found:
"Pump&Valve", "z_<measured_um>um.tif") renders as the real character
instead of being misinterpreted as markup or silently dropped by the
HTML parser.

**Verification: genuinely non-offscreen this time, with before/after
visual proof, not another geometry measurement.** Ran with
`QT_QPA_PLATFORM` unset (confirmed `QApplication.platformName() ==
"windows"`, the real native platform, not a fallback) and triggered the
exact real user code path (found and clicked the real `_TooltipIconButton`
next to `mso_range`). Grabbed only the specific tooltip `QLabel` widget
itself (`QWidget.grab()`), not the screen (`QScreen.grabWindow()` was
tried first and had to be discarded -- it captured the entire real
desktop, including unrelated windows, not just the test window; deleted
immediately, nothing from it is retained or described anywhere).
**Before the fix** (temporarily reverted via Edit, not git, to avoid
disturbing this session's own uncommitted diff): real widget size
1659x20, `wordWrap=False` -- a single unwrapped line, visually confirmed
by inspecting the grabbed image, reproducing the user's screenshot
exactly. **After the fix restored:** real widget size 241x132,
`wordWrap=True`, `textFormat=AutoText` (Qt auto-detected the HTML markup
and switched to rich-text rendering) -- visually confirmed as cleanly
wrapped across 9 short lines, fully readable, no truncation.

**Tests:** full suite green, 410/410, two consecutive clean runs (no
existing test asserted on tooltip wrap behavior specifically, so none
needed updating; the 142-widget tooltip-coverage count and every
substring-based tooltip-content assertion are unaffected since HTML-
escaping only touches `&`/`<`/`>`/`"`/`'` characters, confirmed absent
from every string any test currently checks for).

**Not committed** -- pending review, per standing instruction.

---

### Session 72 -- Refill/Empty default flow rate set to 200 uL/s
(12000 uL/min), confirmed on real hardware; corrects a prior
investigation's mistaken premise about the old ceiling number

**Context: a prior investigation this session found real evidence
directly contradicting its own starting premise.** The premise was
that an earlier-cited `flow_rate_max` of 7316.42 uL/min was stale,
specific to a smaller syringe from an unrelated diagnostic session,
and should not be reused as a ceiling. A read-only trace (real
hardware transaction log, real Cetoni XML config, live SDK query
values) found the opposite: 7316.42 uL/min is the live, current,
real ceiling for the syringe actually configured right now (`"1 ml
Glass"`, 5mm inner diameter, 60mm stroke,
`Cetoni_1pump_config_FM`) -- confirmed twice today via the SDK's own
`get_flow_rate_max()`, logged in `logs/hardware_transactions.log`.
That investigation also found `QmixPumpBackend._fill_flow_rate()`
([qmix_backend.py:164](src/thermo_acoustic/qmix_backend.py:164))
unconditionally ran Refill/Empty at exactly 100% of whatever the
current syringe's live max was (no margin at all, syringe-dependent),
and could not pin a root cause on a specific stall mechanism from the
available log evidence (one non-reproduced CANopen SDO timeout, no
occurrence of the CAN Error Passive/Heartbeat pattern during
refill/empty specifically).

**This session's fix, on direct user instruction:** the user verified
200 uL/s directly on real hardware via CETONI Elements with the
currently-mounted syringe and confirmed it works reliably --
superseding further investigation.
`QmixPumpBackend.default_fill_flow_rate_ul_min`
([qmix_backend.py:94](src/thermo_acoustic/qmix_backend.py:94)) changed
from `None` to `200.0 * 60.0` (12000.0 uL/min), wired as an actual
dataclass default -- `QmixPumpBackend` is constructed with no
explicit args anywhere in this codebase
(`hardware_factory.build_hardware_bundle()`), so every real run now
gets this value automatically, without any caller needing to pass it.

**Scope confirmed, one shared-path behavior change flagged, not
silently made:** `Application.flush()` remains untouched -- it passes
`settings.flush_flowrate` explicitly to `set_fill_level()`, a
completely separate path that never reaches `_fill_flow_rate()`.
`Application.go_to_level(level, flow_rate=None, ...)` shares the same
`_fill_flow_rate()` fallback via
`QmixPumpBackend.set_fill_level()`'s own `flow_rate is None` check
([qmix_backend.py:238](src/thermo_acoustic/qmix_backend.py:238)) --
its one current caller, the GO button
(`qt_ui.py::_start_go_level()`), always passes an explicit
`self.flow_rate.value()`, so this is currently a dormant effect, not
an active behavior change -- but any future caller of
`go_to_level()`/`set_fill_level()` that omits `flow_rate` will now
also get 200 uL/s instead of the syringe's live max. Flagged per
explicit instruction rather than silently left ambiguous.

**Tests:** `test_qmix_pump_backend_initializes_and_dispatches`
updated (`set_fill_level`/`empty`/`refill` assertions: `5000.0` ->
`12000.0`, matching the new default rather than the fake pump's own
`get_flow_rate_max()`). Added
`test_qmix_refill_and_empty_use_the_200_ul_per_s_default_not_the_syringes_live_max`,
which deliberately keeps the fake pump's own max flow at a different
value (5000.0) so a regression back to "100% of live max" would
produce a visibly wrong flow value instead of accidentally matching.
Full suite green.

**Not committed** -- pending review, per standing instruction.

---

### Session 73 -- Refill/Empty: user-adjustable flow rate clamped to
the syringe's real live max (fixes a real SDK rejection from Session
72's flat default); PumpValve "Reference move" promoted to its own
leading Setup section (confirmed never actually implemented from the
earlier design conversation, not a caching/wrong-file issue)

**Part 1 -- root cause confirmed from real evidence, not assumed.** A
fresh screenshot showed Refill throwing Error -> Refilling -> Error.
`logs/hardware_transactions.log` (2026-08-03 15:28:34) had the real
error: `('Value range of parameter exceeded', -513, 'Flow of pump ...
out of range. Value 12000 - range [0...7316.42]')`. Tracing the same
log window back to `pump | initialize` (15:27:53) showed the pump
connected via `Cetoni_1pump_config_FM`'s own default syringe ("1 ml
Glass", 5mm ID, real live max 7316.42 uL/min) -- with **no
`configure_syringe` call anywhere in between**, even though "BD 5ml"
appeared selected in the Syringe dropdown in the screenshot.
Selecting a syringe in that dropdown does not apply it to the real
pump; only clicking "ConfigureSyringe" does. So Session 72's flat
12000 uL/min default (verified on real hardware, but evidently with a
different syringe actually configured at verification time) genuinely
exceeded the syringe active by default, and the SDK correctly
rejected it -- confirmed, not guessed, per explicit instruction not
to silently pick a new fix without checking this.

**Fix, per explicit direction (Option A from a user decision point):**
added a real "Refill/Empty Flow Rate (uL/min)" field
(`self.fill_flow_rate`, [qt_ui.py:841](src/thermo_acoustic/qt_ui.py:841)-area,
default 12000.0) to the Pump group, replacing the buried constant.
`QmixPumpBackend._fill_flow_rate(requested_ul_min=None)`
([qmix_backend.py:172](src/thermo_acoustic/qmix_backend.py:172)) now
always clamps the target (explicit argument, or
`default_fill_flow_rate_ul_min` if none given) to
`self.max_flow_rate_ul_min` -- the currently-configured syringe's own
live-reported ceiling -- via `min(target, live_max)`. `flow_rate`
threaded through as an optional parameter at every layer:
`Application.refill()/empty()` ->
`CetoniPump.refill()/empty()` -> `QmixPumpBackend.refill()/empty()`,
mirroring `go_to_level()`'s existing shape rather than inventing a new
one. `flush()` (separate `settings.flush_flowrate` path) and
`go_to_level()`'s own explicit-rate behavior are both unchanged;
`go_to_level()`'s `flow_rate=None` fallback still shares
`_fill_flow_rate()`, so it now also benefits from the clamp (a safety
improvement, not a behavior change for its one real caller, which
always passes an explicit rate).

**Flagged, not fixed:** the Syringe-dropdown UX trap that caused this
(selection looks live but needs a separate ConfigureSyringe click) is
now a `known_open_items.md` entry for a future UX pass, not silently
left undocumented.

**Part 2 -- confirmed never implemented (not a caching/wrong-file
bug).** `_pump_tab()` still had `flow_form.addRow("Reference move",
ref)` as the last row of "Flow Control" -- the earlier Part 3 design
conversation's reorg was discussed and agreed but never actually
built. Fixed: a new leading "Setup" `QGroupBox`
([qt_ui.py:2093](src/thermo_acoustic/qt_ui.py:2093)-area) now holds
Reference move alone, placed first in column 1 (ahead of Valve/Stop),
ahead of Refill/Empty and Flow Control's own experiment-adjacent
fields -- matching the physical sequence (reference move before
mounting/refilling a syringe). Shared by v1's tab and v2's page, as
scoped in the task.

**Tests:** `test_qmix_pump_backend_initializes_and_dispatches` and
Session 72's own new test updated for the clamp (fake pump max_flow
5000.0 < requested 12000.0 -> actual SDK call now correctly 5000.0,
not the unclamped target). Added
`test_qmix_refill_and_empty_target_200_ul_per_s_but_clamp_to_the_syringes_live_max`,
`test_qmix_refill_and_empty_use_the_target_unclamped_when_syringe_can_reach_it`,
`test_qmix_refill_and_empty_accept_an_explicit_flow_rate_clamped_the_same_way`
(test_application.py), `test_pump_tab_reference_move_is_promoted_to_a_leading_setup_group`,
`test_refill_and_empty_pass_the_fill_flow_rate_field_value_through`
(test_qt_ui_hardware_settings.py -- also updated the hardcoded
tooltip-coverage count, 142 -> 143, for the new field). Two existing
fake pump backends (`FakePumpBackend`, `_FakePumpBackendWithRealFillLevel`
in test_application.py) updated to accept the new optional
`flow_rate` parameter on `refill()`/`empty()`. Real-platform
screenshot verification: Setup/Reference move confirmed first in
column 1; Refill/Empty Flow Rate field confirmed showing 12000.0
under Refill/Empty. Full suite: 416 passed, clean run (two
SystemError-class failures during earlier runs both confirmed via
isolation rerun as the same pre-existing offscreen/shiboken
construction flakiness documented elsewhere in this log, not
regressions).

**Not committed** -- pending review, per standing instruction.

---

### Session 74 -- Real Meerstetter TEC integration via pyMeCom: investigation, then dual-channel implementation, both scoped to 5 whitelisted parameters

**Part 1 -- investigation (no device-control code changed).** Read
`tec.py`'s existing scaffold in full and compared it against pyMeCom
(`github.com/meerstetter/pyMeCom`, MIT, org `meerstetter`, no PyPI
release -- confirmed via a direct PyPI JSON API check for both
`mecom` and `pyMeCom`, both `{"message": "Not Found"}`) and the real
71-page vendor protocol document (TEC-Family MeCom Communication
Protocol 5136AU, downloaded directly from meerstetter.ch, text
extracted locally with `pypdf` since this Windows environment has no
`pdftoppm`). Confirmed the exact parameter IDs for the 5 operations
this integration is allowed to touch -- 2010 "Output Enable Status"
(write 1 = Static ON), 3000 "Target Object Temp" (write, °C), 1000
"Object Temperature" (read-only, °C), 104 "Device Status" (read-only,
0 Init/1 Ready/2 Run/3 Error/4 Bootloader/5 Resetting), 105 "Error
Number" (read-only) -- cross-checked against a worked wire-level
example in the protocol document itself, not just pyMeCom's own
`commands.py` table. Confirmed pyMeCom's own built-in safety design:
`get_parameter()`/`set_parameter()` (by name) resolve only through a
static allow-list and raise `UnknownParameter` otherwise;
`get_parameter_raw()`/`set_parameter_raw()` are separate methods that
bypass that list entirely and must never be called. Confirmed the
existing local `TEC_TARGET_MIN_C=0.0`/`TEC_TARGET_MAX_C=80.0` bound in
`tec.py` cannot be responsibly tightened from in-scope evidence alone
(the real device-specific safe range lives in Upper/Lower Error
Threshold parameters 4010/4011, explicitly out of scope to read) --
recommended leaving it unchanged. Real hardware detail: the
established COM port discovery methodology from Session 54 (passive
`serial.tools.list_ports.comports()` cross-checked against
`Get-PnpDevice -Class Ports` and real USB topology via
`DEVPKEY_Device_Parent`) surfaced two active, not-yet-identified FTDI
candidates (COM4, COM6) plus one currently-disconnected candidate
(COM3) -- no live protocol probe was attempted this session (see
below).

**Part 2 -- implementation.** `tec.py` extended, not restructured:
`TecStatus` gained a `channel: int = 1` field; `TecBackend`'s
per-operation methods (`read_status`, `set_output_stage_static_on`,
`set_target_temperature`) now take a `channel: int` argument;
`SimulatedTecBackend` converted from scalar fields to per-channel
dict-keyed state; `MeerstetterTecBackend` threads `channel` through to
its client. New `_PyMeComTecClient` class wraps pyMeCom's
`MeComSerial`, calling only `get_parameter()`/`set_parameter()` by
name for the 5 whitelisted parameters above, never `*_raw`; `mecom` is
imported lazily inside `connect()`, matching this project's existing
vendor-SDK convention (`qmix_backend.py`'s `_load_sdk()`,
`thorlabs_piezo.py`'s lazy `import clr`). `write_config()` is a
deliberate no-op (documented inline, not just here): MeCom `VS`
commands apply immediately in the device's RAM per the protocol
document's own worked examples, so flash persistence isn't needed --
the app re-applies its target every session anyway, and flash write
cycles are finite, a real cost for a temperature series stepping
through many setpoints. `close()` is wrapped the same way as
Pump/Valve/Piezo's own cleanup path (via `hw_logging.run_with_timeout()`
inside `MeerstetterTecBackend`/`TecController`, unchanged from before
this session).

**Channel architecture decision, reasoned from the real call sites
before implementing:** rejected two independent `TecController`
instances in favor of one `TecController` with a new
`channels: tuple[int, ...] = (1, 2)` field and an optional `channels`
parameter on `apply_static_setpoint()`/`wait_until_stable()`/
`read_status()`, defaulting to `self.channels` ("apply to all
configured channels" when the caller omits it). Chosen because
`application.py`'s only real caller
(`run_temperature_series()`) calls both methods with no channel
argument today -- this design requires zero changes there while still
letting a future caller drive channels independently (e.g.
`apply_static_setpoint(t1, channels=(1,))` then
`apply_static_setpoint(t2, channels=(2,))`). `last_status` changed
from a single `TecStatus` to `dict[int, TecStatus]`; confirmed via a
repo-wide grep that no UI code (`qt_ui.py`/`qt_ui_v2.py`) reads
`last_status` or any `TecStatus` field directly, so this shape change
has no other call site to update. The single "Temperature points (C)"
UI field therefore continues to broadcast the same target to both
channels unchanged, via this default.

`hardware_factory.py`'s `build_hardware_bundle()` now wires
`client_factory=_real_tec_client_factory` into the non-simulated
`MeerstetterTecBackend` (previously left unset, an intentional gap
from before pyMeCom existed). `pyproject.toml`/`requirements-exp_ctrl.txt`
declare `mecom` as a PEP 508 git reference pinned to tag `v1.1` (not
on PyPI, so a plain `pip install mecom` would not work);
`tools/check_environment.py` gained a matching `CORE_DEPENDENCIES`
entry so a missing `mecom` install is caught the same way the original
npTDMS gap should have been (Session 62).

**Tests (`test_tec.py`, fake-backend only -- no real hardware, per
explicit instruction this pass):** existing fakes/tests updated for
the channel-aware signatures and the new `dict[int, TecStatus]` return
shape. Added a `FakeMeComSerial` double (raises if any parameter name
outside the 5 whitelisted ones is ever read or written, and exposes
`get_parameter_raw()`/`set_parameter_raw()` stubs that raise
`AssertionError` if `_PyMeComTecClient` ever reaches for them) plus
tests confirming: only the 5 named parameters are ever touched;
"Error Number" is read only when "Device Status" == 3; channels 1 and
2 are addressed independently (`parameter_instance`); `write_config()`
makes no calls at all, a true no-op. `TecController`-level tests added
for independent per-channel setpoints and for the existing
all-channels-by-default broadcast. One pre-existing safety-gate test
(`client_factory is None` after building a real-backend bundle) was
now stale -- replaced with a test confirming the real factory is wired
in while building the bundle still performs zero I/O (the client is
constructed lazily, only inside `connect()`, which the test
deliberately never calls). Full suite: 424 tests, all green (two
Qt/PySide6 `SystemError`-class failures on the first full-suite run
both confirmed via isolated rerun as the same pre-existing
offscreen/shiboken construction flakiness already documented
elsewhere in this log, not regressions, and unrelated to this
session's changes).

**Explicitly not done this session, per direct instruction:** no real
serial connection to the physical TEC was attempted (`AskUserQuestion`
resolved the task's own Step 1/Step 5 tension in favor of deferring
the live confirming probe); `hardware_tests/test_serial_discovery.py`'s
`DEFAULT_PORTS` was not extended with a "TEC default" entry, since the
port hasn't been confirmed by a live probe yet. Real-hardware
verification (connect -> enable -> set both channels' temperatures ->
read back -> disconnect) is reserved for a separate pass with the user
present.

**Not committed** -- pending review, per standing instruction.

---

### Session 75 -- First real-hardware TEC verification: confirmed port, found and fixed a real blocker bug, safe shutdown, channel-2 addressing under diagnosis

**Part 1 -- real-hardware verification (user present, step by step,
confirming before each hardware-touching action).** Installed the
already-reviewed, pinned `mecom` (pyMeCom) package into the real
`exp_ctrl` conda environment for the first time (declared since Session
74, never actually installed since no real hardware had been touched
yet). **Step 1:** re-ran the established port-enumeration methodology
(`list_ports.comports()` cross-checked against `Get-PnpDevice -Class
Ports`) -- COM4 and COM6 still the active untested candidates from
Session 74. A read-only confirming probe (parameter 104, Device Status)
on each: COM4 timed out (not a MeCom device); **COM6 responded `1`
(Ready)** -- confirmed as the real TEC, no other port touched. **Step
2:** read-only status on both channels -- channel 1: Ready, 24.66 C, no
error; **channel 2: `ResponseException('device 0 raised Instance is not
available')`** -- not an error *status*, a communication-level rejection
of the channel-2 instance itself. Stopped per the task's own abnormal-
condition rule and asked the user how to proceed (`AskUserQuestion`);
user chose to proceed on channel 1 only for this pass. **Step 3:**
enabled Output Stage Static ON (parameter 2010 = 1) for channel 1 only
-- Device Status moved to Run, no error. **Step 4:** set Target Object
Temp on channel 1 to a small, safe +1.85 C step (24.65 C baseline -> 26.5
C target) -- **first attempt raised `UnknownParameter()`**, revealing a
real bug (below); after using the correct name, the object temperature
climbed monotonically over 20s (25.02 -> 25.15 -> 25.82 -> 26.43 -> 26.58
-> 26.60 C) toward the target, confirming genuine closed-loop control,
not a silent-accept write. **Step 5:** disconnected through the real
production path (`TecController`/`MeerstetterTecBackend`/
`_PyMeComTecClient`, channel 1 only, not a throwaway script) --
`initialize()` read back 26.4997 C (essentially exact on target),
`ready=True`, `error=None`; `cleanup()`/`close()` completed with no
exception.

**Part 2 -- urgent shutdown, then fix the bug Step 4 exposed.** The
device was left with channel 1's output actively enabled and holding
26.5 C between turns. **First action this session:** turned Output
Enable Status (2010) off (value 0) for channel 1 via the real production
`MeerstetterTecBackend`/`_PyMeComTecClient` connect path (the OFF write
itself used the client's internal `set_parameter()` directly, since
`set_output_stage_static_on()` only ever writes the ON value 1 --
still the same whitelisted parameter 2010, still not `*_raw`). Confirmed
off: Output Enable Status readback `False`, Device Status no longer
Run, no error, temperature reading 23.31 C at that moment (a lower
transient reading than the pre-heating ~25 C baseline; observed and
reported as-is, not investigated further -- not a safety-relevant
value).

**Root cause of the Step 4 write failure, confirmed against the real
installed package, not guessed:** `tec.py`'s `_MECOM_PARAM_TARGET_TEMP`
was `"Target Object Temp"`; the actual installed pyMeCom's own
`mecom.commands.TEC_PARAMETERS` table names parameter 3000 **"Target
Object Temperature"**. Every other whitelisted constant (Device Status,
Error Number, Object Temperature, Output Enable Status) matched exactly
-- confirmed by inspecting `TEC_PARAMETERS` directly, not by trial and
error. As shipped since Session 74, this meant `apply_static_setpoint()`
would have raised `UnknownParameter` on every real write; caught here
because this was the first real-hardware exercise of that code path.
Fixed in `tec.py`. New regression test
(`test_tec_parameter_name_constants_match_the_real_installed_pymecom_table`)
compares all 5 `_MECOM_PARAM_*` constants directly against the
installed package's own `mecom.commands.TEC_PARAMETERS`, not a second
hand-typed string, so a future mismatch can't hide behind two wrong
strings agreeing with each other -- `pytest.importorskip("mecom")`
skips it (not fails it) when `mecom` isn't installed, matching this
project's existing real-vendor-SDK test convention; confirmed to
actually pass (not just skip) by running the suite a second time under
the real `exp_ctrl` environment where `mecom` is now installed.

**Scope rule updated (user decision, real loosening from Session 74's
"5 parameters, read or write" rule):** writes remain strictly limited to
exactly 2 parameter names (`_MECOM_WRITABLE_PARAMETER_NAMES` = Output
Enable Status, Target Object Temperature), never any other parameter,
never `*_raw`. Reads are no longer restricted to a fixed list -- any
parameter may be read by name for real-hardware diagnostics, since a
read cannot change device state. `tec.py`'s module comment,
`_PyMeComTecClient`'s class docstring, and `test_tec.py`'s
`FakeMeComSerial` double were all updated to match: the fake no longer
raises on an unlisted *read*, but still raises on any *write* outside
the 2-name whitelist, and still forbids `get_parameter_raw()`/
`set_parameter_raw()` in both directions.

**Tests:** `test_tec.py` fully updated for the corrected parameter name
and the loosened read policy; two tests renamed/refocused (whitelist-
enforcement framing no longer applies to reads); two new tests added
(write-restriction-to-2-parameters, and unrestricted-diagnostic-reads).
Full suite: 427 passed, 1 skipped (the mecom-dependent regression test,
correctly skipped under the base environment where `mecom` isn't
installed, independently confirmed to pass under `exp_ctrl` where it
is).

**Part 3 -- channel-2 diagnosis (read-only, no writes of any kind, no
code changes).** User was confident the device is genuinely dual-channel
and asked for real diagnosis rather than accepting "single-channel" as
the conclusion. Read-only investigation (all via `get_parameter()`/
`get_parameter_raw()` by name/id -- reads are unrestricted project-wide
per this session's scope update, `*_raw` reads used only where a
parameter isn't in pyMeCom's own name table, e.g. Device Type/General
Operating Mode) found:

- **Device Type (parameter 100, not 1123 -- 1123 is the model NUMBER
  value "TEC-1123", not a parameter ID) reads 1123** -- confirms the
  real model matches the TEC Service Software screenshot. Hardware
  Version 2.00, Firmware Version 5.10, Serial Number 5091.
- **General Operating Mode (parameter 2040) reads 0 (Bipolar)** -- not
  one of the "Parallel Bipolar" combined-loop modes; could not confirm
  this is the exact register behind the TEC Service Software's "Single
  (Independent)" label without the user's own screenshot cross-check.
- **A clean, consistent pattern across instances 1-4 for 4 parameters**
  (Device Type, Device Status, Object Temperature, Output Enable
  Status): instance 1 -- all 4 succeed. **Instance 2 -- Device Type and
  Device Status both fail ("Instance is not available"), but Object
  Temperature (23.49 C, a distinct real reading from channel 1's 23.45 C)
  and Output Enable Status (reads 0/OFF) both SUCCEED.** A follow-up
  read-only check found Target Object Temperature also succeeds at
  instance 2 (25.0 C, a different value than channel 1's leftover 26.5 C
  target). Instances 3 and 4 fail across the board.
- **Working hypothesis, not yet confirmed by a write test:** Device Type
  and Device Status may simply be device-wide "Common Product
  Parameters" by protocol design (the real protocol document files them
  under that heading), not genuinely per-channel -- meaning Device Type
  failing at instance 2 doesn't prove channel 2 is absent, only that
  Device Type itself was never going to be per-instance on any
  multi-channel unit. Device Status behaving the same way is a weaker
  but still real signal that the device may report one unified run-state
  for the whole unit rather than one per control loop. The fact that
  Output Enable Status and Target Object Temperature both hold real,
  independent, distinct state at instance 2 is the strongest evidence
  found this session that **channel 2 is likely a genuine second control
  loop**, just one whose Device Status can't be queried the way `tec.py`'s
  `read_status()` currently assumes (`get_parameter(parameter_name="Device
  Status", parameter_instance=channel)` for every channel) -- which is
  the direct, confirmed reason `TecController.initialize()`/`read_status()`
  fail for channel 2 today.
- **Deliberately not tested this session (per the read-only constraint):**
  whether *writing* Output Enable Status or Target Object Temperature at
  instance 2 actually drives a second physical Peltier loop. That would
  confirm or refute the hypothesis directly but is a real hardware write,
  reserved for an explicit future step with the user present.

No code changes made for Part 3 -- this is diagnosis only, reported for
the user to decide how `tec.py`'s `read_status()` should be redesigned
around a possibly device-wide (not per-channel) Device Status parameter.

**Not committed** -- pending review, per standing instruction.

---

### Session 76 -- Confirmed channel 2 is a genuine independent control loop with a real write test, then fixed read_status()'s Device Status addressing

**Part 1 -- confirmed the Session 75 hypothesis against the real
protocol document's own section structure, not just the live-probe
pattern, before touching hardware again.** Device Status (104)/Device
Type (100) are filed under Sec 3.3.1 "Common Product Parameters" --
the same section as Firmware Version, which the document's own general
addressing rule (Sec 3.1) names as its worked example of a
single-instance parameter ("If there is only one instance available,
Parameter Instance must be set to 1, e.g. Firmware Version"). Object
Temperature (1000), Target Object Temp (3000), and Output Enable (2010)
are all filed under a separate section, Sec 3.3.4 "Temperature
Controller." Real textual support for the hypothesis, not proof beyond
doubt on its own -- confirmed properly in Part 2.

**Part 2 -- real controlled write test on channel 2, same discipline as
the original channel-1 verification.** Baseline (channel 2): Object
Temperature 23.64 C, Output Enable 0, Target Object Temperature 25.0 C
(confirmed channel 1 still off first). Enabled Output Stage on channel
2 ONLY (2010=1, instance 2) -- readback confirmed, no error;
device-wide Device Status flipped to Run. Set Target Object Temperature
on channel 2 to 25.5 C (a small, safe step) and polled for 24s: **object
temperature climbed and held/oscillated tightly around 25.5 C (25.11 ->
25.54 -> 25.53 -> 25.44 -> 25.50 -> 25.55 -> 25.47 C)** -- genuine
closed-loop thermal response, fully independent of channel 1 (verified
off throughout), matching channel 1's original verification behavior
exactly. **Confirms channel 2 is a real, physically populated second
control loop**, not an artifact of the device accepting writes to an
absent instance. Turned channel 2's Output Enable back to 0 regardless
of outcome; confirmed BOTH channels off at the end (Output Enable
Status = 0 for instance 1 and 2), and device-wide Device Status dropped
back to Ready (1) once both loops were disabled -- further confirming
it aggregates across both loops rather than being per-channel.

**Part 3 -- fixed `read_status()` based on the confirmed evidence (not
the hypothesis alone).** `_PyMeComTecClient.read_status()` (and the
`TecBackend` Protocol / `SimulatedTecBackend` / `MeerstetterTecBackend`
implementing it) changed from a per-channel signature
(`read_status(channel: int) -> TecStatus`, called once per channel in a
loop) to a multi-channel signature
(`read_status(channels: tuple[int, ...]) -> dict[int, TecStatus]`,
called once per `TecController` operation). Device Status (104) and
Error Number (105) are now read ONCE at instance 1 and applied to every
requested channel's `TecStatus` -- not re-read per channel, which is
exactly what broke channel 2 before. `TecController.initialize()`,
`read_status()`, and `apply_static_setpoint()` all updated to call
`backend.read_status(channels)` once instead of looping
`backend.read_status(channel)` per channel. `TecStatus`'s own shape is
unchanged (still per-channel, still carries `ready`/`error_state`) --
chose to keep those fields duplicated across each channel's `TecStatus`
(populated from the same shared device-wide read) rather than splitting
into a separate device-level status type, since this requires zero
changes to `wait_until_stable()`'s/`apply_static_setpoint()`'s existing
per-channel iteration over `dict[int, TecStatus]`, matching this
project's repeated "extend, don't restructure" instruction.

**Tests:** all three `test_tec.py` fakes
(`RecordingTecBackend`/`FailingStatusTecBackend`/
`ChannelAwareRecordingTecBackend`) updated for the new
multi-channel-in/dict-out `read_status()` signature; every assertion on
`backend.calls` for `("read_status", ...)` updated from a per-channel
int to the channels tuple actually passed. New regression test
`test_real_tec_client_reads_device_status_once_for_multiple_channels`
asserts Device Status is queried exactly once (at instance 1) when
reading both channels -- fails loudly if a future change reintroduces
the per-channel Device Status read that broke channel 2 originally.
Full suite: 428 passed, 1 skipped (the mecom-dependent regression test
from Session 75, confirmed passing again under `exp_ctrl`).

**Both channels confirmed OFF at the end of this session**, per the
task's explicit requirement, regardless of the write test's outcome.

**Not committed** -- pending review, per standing instruction.

---

### Session 77 -- TEC wrap-up: dual-channel lock/unlock scan UI, wait_until_stable() real-hardware pass, error-state gap accepted, docs closed out

**Item 1 -- dual-channel lock/unlock temperature scan.** Investigated the
current `TemperatureSeries`/`run_temperature_series()` shape first: one
flat `list[float]` (`temperature_points_c`), broadcast to both channels
via `apply_static_setpoint()`/`wait_until_stable()` calls with no
`channels=` argument. Two real complications flagged before touching
code: (a) unequal-length per-channel series has no coherent mapping onto
`run_temperature_series()`'s one-group-per-step loop -- resolved to
require equal length, stepped together; (b) `wait_until_stable()` took
one scalar target, so a shared call couldn't check two channels against
two different targets correctly. User confirmed extending
`wait_until_stable()`/`apply_static_setpoint()` to accept
`float | dict[int, float]` (over calling per-channel sequentially, which
would double per-step wait time). Implemented: both methods now accept
either shape -- a float broadcasts (unchanged, backward compatible with
every existing real-hardware-verified call site); a `dict[int, float]`
drives each channel to its own target, polled genuinely simultaneously
in one call, not one channel's full wait followed by the other's.
`TemperatureSeries` gained `temperature_points_ch2_c: list[float] | None`
(`None` = locked, unchanged default; a list = unlocked, same length as
channel 1's required, `ValueError` otherwise) plus a `target_at(index)`
helper and `from_text(text, text_ch2=...)`. `Application.run_temperature_series()`
updated to call `temperature_series.target_at(step)` instead of a plain
zip, passing whichever shape through unchanged.

**UI**: a lock/link toggle next to the CH1/CH2 "Temperature points (C)"
fields in `_experiment_temperature_group()` (shared by v1's tab and v2's
page) -- the same Photoshop-aspect-ratio-lock / CSS-box-model-link-icon
pattern, a plain checkable `QPushButton` with a Unicode glyph (checked
this codebase's convention first: no `QIcon`/`QStyle.standardIcon` usage
anywhere in `qt_ui.py`, so no new icon-asset pipeline was introduced).
Locked (default): CH2 is disabled and mirrors CH1 live as it's typed.
Unlocked: CH2 becomes independently editable, starting from whatever
value it was already mirroring (not reset to a default). Relocking
copies CH1's current value into CH2 -- the less-surprising choice for a
reversible text-field toggle, no confirmation dialog (this isn't a
hardware action; CH1's value is preserved and visible either way).
Persisted via new `tec_lock_channels`/`tec_points_ch2` Save/Load Settings
keys, restored last (after the lock-checkbox restore's own mirroring
side effect) so a save/load round trip is exact regardless of internal
signal ordering; absent (older saved settings) defaults to locked,
matching the existing tolerant-load convention. Also fixed a stale
tooltip on `exp_tec_scan_enable` claiming real TEC selection "intentionally
fails" -- no longer true since Sessions 74-76's real integration.

**Tests**: `tec.py`-level tests for the dict-target extension (including
a regression test proving per-channel targets are checked against their
own channel, not a shared value -- the actual bug the extension fixes);
`workflows.py`-level tests for `TemperatureSeries`'s new field (locked
default, unlocked shape, mismatched-length rejection, safety-range
validation on CH2 too); an end-to-end `Application.run_temperature_series()`
test confirming an unlocked series drives real independent per-channel
writes; widget-level tests in `test_qt_ui_hardware_settings.py` for
locked-mirrors-live, unlock-preserves-value, relock-copies-CH1, and the
full Save/Load round trip. Tooltip-coverage hardcoded count updated
143 -> 144 (one new tooltipped `QLineEdit`; the lock toggle itself is a
`QPushButton`, outside that sweep's tracked widget types). Real-render
screenshot check (offscreen) confirmed the enabled/disabled visual state
actually flips between locked and unlocked.

**The new dict-target code path itself has not been run against real
hardware this session** -- fake/unit-tested only. The single-float
broadcast path it's built on top of has been real-hardware verified
repeatedly (Sessions 75-77).

**Item 2 -- error-state verification: investigated, accepted as a
documented gap, not fixed.** `read_status()`'s Error-Number-read branch
(`if device_status_id == 3`) is fake-tested only; real hardware has never
entered Error state. Investigated whether a safe real trigger exists:
Error Threshold parameters (4010/4011 per-channel, 5010/5011
device-level) could be read (unrestricted now) to learn configured
margins, and an auto-reset feature exists (parameter 6310, "Delay till
Restart"). But deliberately tripping a real threshold means commanding
the Peltier to a value the device itself flags unsafe, with no confirmed
in-scope recovery path if auto-reset turns out disabled (recovery would
need a `Device Reset` write, parameter 111, outside the 2-parameter
writable scope). Recommended not manufacturing that risk for a one-line
conditional already covered by fake tests -- accepted as a gap that will
close itself if a genuine fault ever occurs during real use.

**Item 3 -- `wait_until_stable()` real-hardware test: proposed, confirmed,
run.** Plan: channel 1, baseline read, `apply_static_setpoint(baseline +
1.5, channels=(1,))`, then `wait_until_stable(...)` itself (not a
hand-rolled polling script) with `tolerance_c=0.2, min_settle_s=5.0,
max_wait_s=60.0, poll_interval_s=2.0`. User confirmed; ran against the
real device: baseline 24.15 C, target 25.65 C, converged to 25.75 C,
`ready=True`, `error_state=None`, well inside the 60s bound. Turned
channel 1 back off afterward, confirmed OFF.

**Item 4 -- documentation.** `docs/tec_verification_matrix.md` and
`docs/known_open_items.md` both updated: all 5 whitelisted parameters'
core paths (connect, per-channel read/write/enable, write_config no-op,
device-wide Device Status fix) marked real-hardware-verified;
`wait_until_stable()`'s success path added as real-hardware-verified;
the new dual-channel dict-target feature and lock/unlock UI documented
as implemented but fake-tested only; the error-state gap documented as
investigated-and-accepted, not "unverified" with no explanation.

**Full suite: 442 passed, 1 skipped** (the mecom-dependent regression
test; one unrelated `SystemError`-class Qt/PySide6 flakiness on the WFG
tab appeared on the first full run, confirmed via isolated rerun as the
same pre-existing offscreen/shiboken construction issue documented
elsewhere in this log, not a regression).

**Not committed** -- pending review, per standing instruction.

---

### Session 78 -- SAFETY-BEHAVIOR CHANGE: Abort no longer force-stops hardware mid-operation -- it now always finishes the current repeat first

**This session changes what the Abort button actually does. Read this
entry before relying on Abort's behavior.** Previous behavior: clicking
Abort immediately, forcibly called `pump.stop()`/`camera.stop_capture()`/
`ad2.wfg_start_stop_all_ch(False)` on a separate concurrent thread,
regardless of what the in-flight repeat was doing -- this could interrupt
a flush mid-pump-move (leaving the valve stuck at position 1) or a
capture mid-frame (discarding captured data, since the repeat would then
bail out of `run_experiment2()` without ever reaching the save step).
**New behavior, by explicit user decision (no separate emergency hard-stop
is offered anymore): Abort only ever prevents the *next* repeat from
starting. The currently in-flight repeat, if any, always runs to full,
genuine completion -- capture, the AD2-completion wait, flush (valve
position 1 -> pump move -> valve position 2), and save -- before the
series actually halts.**

**Step 1 -- investigation, before removing anything.** Traced every real
caller of `_abort_hardware()` (the removed concurrent hard-stop) and its
three primitives: confirmed it had exactly one caller (`_abort()`
itself) -- no shutdown/close path or other UI element used it, so
removing it destroys no other functionality. `pump.stop` is *also* wired
independently to the manual Pump&Valve tab's own "Stop" button
([qt_ui.py:2127](src/thermo_acoustic/qt_ui.py:2127)) -- untouched, a
distinct operator-initiated action. `qt_ui_v2.py` has no independent
Abort wiring -- `MainWindowV2(MainWindow)` inherits `_abort()` directly,
so fixing the shared base class fixes both UIs.

**A bigger finding than expected: the `listen_abort()` mid-repeat checks
inside `run_experiment2()`/`wait_for_pump()` were already dead code, not
a live bug, in the real UI.** `listen_abort()` peeks `Application.main_queue`
for an ABORT/EXIT message -- but `qt_ui.py` never enqueues anything into
that queue (verified: zero `Message(`/`enqueue_main` calls anywhere in
`qt_ui.py`). The message-queue dispatch loop
(`run_until_idle()`/`handle_message()`) is only ever driven by `main.py`,
a trivial CLI stub -- already documented in
[known_open_items.md:874-876](docs/known_open_items.md:874) from an
earlier, unrelated investigation. The real `_abort()` set `stop_fired`
directly, a wholly separate mechanism `listen_abort()` never read. So in
practice, only `_abort_hardware()`'s concurrent hard-stop was ever a live
interrupt path in production; the `listen_abort()` checks were misleading
dead code implying a working "abort mid-repeat" feature that was never
actually reachable. Confirmed further by zero test coverage of
`"ExperimentAborted"`/`listen_abort()` triggering anywhere in
`test_application.py` before this session.
`_run_experiment_series_body()`'s existing between-repeats `stop_fired`
check was confirmed to already be correct and sufficient on its own (an
existing test, `test_run_experiment_series_stops_queuing_further_repeats_after_abort`,
already proved it works).

**Step 2 -- implementation.**
- `qt_ui.py`'s `_abort()` no longer calls `_abort_hardware()` (deleted
  entirely -- no other caller existed). It now only calls
  `self.app.fire_stop_event()` and updates status -- synchronous, no
  QThread, no busy-state tracking (nothing left to run in the
  background).
- `application.py`'s `run_experiment2()`: removed the dead post-capture
  and post-AD2-wait `listen_abort()`/`_is_abort_exit_or_error()` early
  returns (`_is_abort_exit_or_error()` itself deleted, now unused). A
  repeat that has started always continues through flush and save.
- `wait_for_pump()`: removed its `listen_abort()` poll -- flush's pump
  move always runs to genuine completion or genuine timeout (the
  pre-existing timeout-return path is unchanged).
- Confirmed: the between-repeats check in `_run_experiment_series_body()`
  is now the *only* place abort state is ever read anywhere in this
  codebase's experiment-run path.

**Step 3 -- tests.** Two existing tests were built entirely around the
now-explicitly-rejected behavior and were replaced, not just adapted:
`test_abort_hardware_worker_starts_while_another_action_is_blocked` and
`test_abort_stops_dcam_wait_and_releases_buffer_with_measured_elapsed_time`
both asserted Abort forcibly interrupts blocking hardware calls quickly
-- the opposite of the new intended behavior. Replaced with
`test_abort_does_not_touch_hardware_even_while_another_action_is_blocked`
and `test_abort_sets_stop_flag_synchronously_without_a_background_thread`,
confirming the new behavior directly. New `test_application.py`
regression tests:
`test_run_experiment2_completes_fully_even_after_abort_is_fired_mid_run`
(a real `run_experiment2()` call with `fire_stop_event()` already set
still completes fully: `status="ExperimentComplete"`, valve ends at
position 2 not stuck at 1, `FlushCompleted=True` in the final `data.tdms`,
queue correctly drains) and
`test_wait_for_pump_no_longer_checks_abort_state` (direct unit coverage
of the removed check). The existing
`test_run_experiment_series_stops_queuing_further_repeats_after_abort`
was left unchanged -- it already validates the correct target behavior.

**Step 4 -- Part C follow-up: graceful-stop visibility + Flush tooltip.**
New `MainWindow._stopping_after_current_repeat` flag: set by `_abort()`
(only when a series is actually running -- Abort is reachable even when
idle, where there's no repeat counter to replace), shown by replacing
the v2 live-monitoring column's repeat-counter area (`self.queue_count`)
with `"Stopping after this repeat..."` instead of the raw remaining
count, until the series actually halts. Deliberately cleared at the
`"experiment_series_active"` progress kind going `False` (fires via
`try`/`finally` on every exit path) rather than waiting for a future
series' first repeat to clear it -- the specific TestStand stale-
highlight mistake this was designed to avoid (a leftover "Stopping..."
from a previous Abort still showing when the next series starts). Also
restores a real count immediately once cleared, rather than leaving the
label stuck reading "Stopping..." past the point the series has already
halted. `ExperimentSequenceView.add_step_card()` gained an optional
`tooltip` parameter; the Flush card (`qt_ui_v2.py`) now explains the
real sequential valve-position-1 -> pump-move -> valve-position-2
relationship (Part A's finding from the prior session) so the operator's
mental model matches reality, without decomposing Flush into multiple
cards (that design decision from Session 58 stays unchanged).

**Full suite: 456 passed** (454 + 2 confirmed-flaky Qt/PySide6
`SystemError`-class failures on unrelated widgets -- WFG channel group,
FM sweep -- verified via isolated rerun as the same pre-existing
offscreen/shiboken construction issue documented elsewhere in this log,
not a regression), 1 skipped (the mecom-dependent regression test).

**Not committed** -- pending review, per standing instruction. This is a
real safety-behavior change to how the app responds to Abort during a
running experiment series -- operators should be aware Abort no longer
provides an immediate hardware stop.

---

### Session 79 -- TEC temperature scan: add a separate post-stabilization hold for real sample thermal equilibration

**Extends the uncommitted TEC integration, does not restructure it.**
Added `TemperatureSeries.post_stable_hold_s: float = 0.0`
(workflows.py) -- deliberately distinct from `min_settle_s`:
`min_settle_s` is part of HOW `wait_until_stable()` itself decides the
TEC's own sensor reading counts as "stable" (continuous time within
tolerance); this is a SEPARATE, additional hold applied only after that
stability is already confirmed, before the temperature point's
experiment group runs -- for real sample thermal equilibration, which
can lag behind the TEC sensor. Default `0.0` -- no behavior change for
any existing config unless explicitly set.

`Application.run_temperature_series()`: after `wait_until_stable()`
returns successfully for a temperature point, if `post_stable_hold_s > 0`
it now fires a status event and calls `self.wait(post_stable_hold_s)`,
then checks `self.listen_abort()` before running that point's experiment
group -- matching the exact abort-awareness convention this loop already
uses at its other checkpoints (the pre-existing `listen_abort()`-based
mechanism for this specific TEC-scan loop, left untouched by Session 78's
separate abort-behavior fix, which only touched `run_experiment2()`/
`wait_for_pump()`, not `run_temperature_series()`).

New UI field "Post-stabilization hold (s)" (`self.exp_tec_post_stable_hold_s`,
a `QDoubleSpinBox`, default `0.0`, unit named explicitly in the label per
request) added to `_experiment_temperature_group()` (shared by v1's tab
and v2's page) after Poll interval, same styling/tooltip convention as
its siblings. Persisted via a new `tec_post_stable_hold_s` Save/Load
Settings key, same tolerant-absent-defaults-to-widget-default pattern as
every other field in this group.

**Tests:** `workflows.py`-level (`TemperatureSeries` default/validation/
`from_text`), `application.py`-level via `test_tec.py`
(`run_temperature_series()`: default `0.0` calls `Application.wait()`
zero times; a nonzero value calls `wait()` exactly once, for exactly the
configured duration, strictly before `run_experiment2()`; abort arriving
during the hold -- simulated via `listen_abort()` returning `True` only
once the hold has actually been waited -- stops the series with
`TemperatureSeriesAborted` and never runs the experiment group, while
still confirming the hold itself ran for its full duration first), and
`qt_ui.py`-level (Save/Load round trip, default value feeds
`_temperature_series()` correctly, a changed field value feeds through
correctly). Tooltip-coverage hardcoded count updated 144 -> 145 (one
new tooltipped `QDoubleSpinBox`). Real-render (offscreen) screenshot
confirmed the new row renders cleanly as the group's 9th row, correctly
sized, with its own tooltip icon marker (font glyphs render as boxes
under the offscreen QPA platform -- a known, already-documented
limitation of this environment, not a rendering defect).

**Full suite: 463 passed, 1 skipped** (the mecom-dependent regression
test) -- clean run, no flaky Qt failures this time.

**Not committed** -- pending review, per standing instruction.

---

### Session 80 -- TEC temperature scan abort: closes a gap Session 78's non-TEC abort fix didn't reach

**Not a regression from Session 79's `post_stable_hold_s` work -- a
pre-existing gap in `run_temperature_series()`, present before this
session touched anything, now investigated and fixed.**

**Investigation (requested and done before any implementation).**
Traced every `listen_abort()` call site inside `run_temperature_series()`
(pre-target-set, `wait_until_stable()`'s `should_abort=self.listen_abort`,
the `post_stable_hold_s` wait, the inner per-repeat loop) against the
same fact Session 78 established: `qt_ui.py`'s real `_abort()` only ever
calls `Application.fire_stop_event()` -- it never enqueues a message
`listen_abort()` reads. **Confirmed identical dead pattern** -- not a
different, live mechanism. Worse: unlike the non-TEC path (which has a
real `self.app.stop_fired` check between repeats in
`_run_experiment_series_body()`), the TEC-scan wrapper,
`_run_temperature_experiment_series()`, had **no fallback check at all**
-- a single blocking call into `run_temperature_series()`, no loop, no
`stop_fired` read anywhere. **Net effect confirmed: clicking the real
Abort button during a running TEC temperature scan did nothing --
the scan always ran to completion regardless.** The passing test added
in Session 79 (`test_run_temperature_series_abort_during_post_stable_hold`)
masked this by overriding `Application.listen_abort()` directly on a
subclass -- proving the interface contract, not proving the real UI ever
reaches it, the exact same reachability gap Session 78's fix was
originally about.

**Investigated whether `_run_temperature_experiment_series()` (qt_ui.py)
needs its own loop, mirroring `_run_experiment_series_body()`, before
assuming yes.** Finding: no -- `Application.run_temperature_series()` is
already architecturally the loop-across-units method for the TEC path
(it takes the full `experiment_groups` list and loops internally, unlike
`run_experiment2()`, which only ever does one repeat and requires an
external loop in qt_ui.py). This is a pre-existing structural difference
between the two paths, not something to relocate as part of this fix.
The correct fix is to make `run_temperature_series()`'s own existing
loop check `self.stop_fired` at the right granularity instead of
`listen_abort()` at the wrong one.

**Implemented, applying Session 78's exact principle ("finish the
current unit, then stop") at the temperature-point granularity:** the
smallest unit for a TEC scan is one full temperature point -- target
set, wait for stability, the post-stable hold, and its ENTIRE experiment
group including every repeat. `run_temperature_series()` now checks
`self.stop_fired` exactly once per temperature point, at the very top of
that point's loop iteration, before it does anything -- mirroring
`_run_experiment_series_body()`'s `if self.app.stop_fired:` between-
repeats check precisely. Every other abort check inside the method was
removed, not replaced: the pre-target-set check, `wait_until_stable()`'s
`should_abort` wiring (dropped entirely -- `wait_until_stable()`'s own
`should_abort`/`TecAbortedError` machinery in `tec.py` is untouched and
still available for other callers, just no longer fed a dead callable
from this one), the post-hold check, and the inner per-repeat loop's
check. `TecAbortedError` import removed from `application.py` (now
genuinely unused there). `_run_temperature_experiment_series()`
(qt_ui.py) needed no new loop -- it already calls
`self.app.create_stop_event()` before its one call into
`run_temperature_series()`, matching the non-TEC wrapper's own reset-
before-start.

**Part C follow-up extended to TEC scans.** The graceful-stop indicator
from Session 78 ("Stopping after this repeat...") now generalizes
correctly: a new `self._temperature_scan_active` flag (set/cleared via a
new `"temperature_scan_active"` progress kind, bracketing
`_run_temperature_experiment_series()` the same way
`"experiment_series_active"` already does) lets `_abort()` pick the
right wording -- "this temperature point" for a TEC scan, "this repeat"
otherwise -- for both the general status text and the repeat-counter
area. Also fixed a small pre-existing wording inconsistency in the same
change: the status text used to say "Stopping after **current**
repeat..." while the counter said "Stopping after **this** repeat..." --
now unified to the same wording in both places.

**Tests:** the two Session 79 tests that mocked `listen_abort()` directly
were confirmed stale against the new behavior (one would now raise
`AssertionError` inside its own stubbed `run_experiment2()`, since the
group it asserted must never run, now correctly does) and were replaced,
not patched around, matching Session 78's precedent for handling
now-incorrect tests. New tests exercise the **real** `stop_fired`
mechanism directly (`self.fire_stop_event()`, the exact call `_abort()`
makes) -- not a mocked `listen_abort()` override -- confirming: abort
signaled during `wait_until_stable()` still lets that point reach its
target and run its full group; abort signaled during the post-stable
hold still lets that point's group run; abort signaled mid-repeat within
a point's own group still lets every remaining repeat in that same point
run; in all three cases, the *next* temperature point never starts.
Also new `qt_ui.py`-level tests for the temperature-point-vs-repeat
wording split, including a sanity check that a plain series doesn't
accidentally pick up TEC wording from a stale flag.

**Full suite: 466 passed effectively** (464 + 2 confirmed-flaky
Qt/PySide6 `SystemError`-class failures on unrelated widgets --
WFG channel group, FM sweep group-box sizing -- verified via isolated
rerun as the same pre-existing offscreen/shiboken construction issue
documented elsewhere in this log, not a regression), 1 skipped (the
mecom-dependent regression test).

**Not committed** -- pending review, per standing instruction. Like
Session 78, this is a real safety-behavior correction to what Abort
actually does -- TEC temperature scans now genuinely respond to Abort
for the first time (previously it silently did nothing during a running
scan).

---

### Session 81 -- v2 step-progress breadcrumb: the previously-deferred Phase 3 stepper indicator

**Investigation before implementing, findings reported first.** Confirmed
the 7-step per-repeat order (`application.py`'s `STEP_*` constants, same
order `ExperimentSequenceView`'s cards already use) and the recorded
design decision that `SetTecTarget`/`WaitTecStable` wrap that sequence
from outside, once per temperature point -- not folded into it.
Recommended keeping the breadcrumb scoped to the same 7 steps only,
deferring a separate "temperature point X of Y" indicator as a follow-up
candidate rather than expanding scope.

**Critical pre-existing gap found and fixed first, not scope creep:**
neither `_run_experiment_series_body()` (`self.app.run_experiment2()`)
nor `_run_temperature_experiment_series()`
(`self.app.run_temperature_series(...)`) passed `progress=progress` into
their real call -- `step_started`/`step_completed`/`step_failed`
(`application.py`'s `_report_step()`) never reached the UI at all, for
either the plain series or a TEC scan, before this fix. No per-card
highlighting existed yet either (Phase 3 was never previously started,
confirmed by `ExperimentSequenceView`'s own docstring) -- so this
introduces the first shared source of truth (`MainWindow._step_states`,
base-class-tracks/subclass-renders, matching `_experiment_series_active`'s
existing split) that both the new breadcrumb and any future per-card
highlighting should read from.

**Implemented:** `STEP_ORDER` (application.py) as the single ordered
7-step tuple; a new `"step_reset"` progress event, fired explicitly (not
inferred from the next step's own `step_started`) at the top of
`run_experiment2()` (every new repeat) and at the top of
`run_temperature_series()`'s per-point loop, right where Session 80's
`stop_fired` check already lives (every new temperature point, covering
the SetTecTarget/WaitTecStable/hold window that would otherwise show the
*previous* point's stale completed markers for however long
stabilization takes). `qt_ui.py`'s `_handle_worker_progress()` now tracks
`_step_states` and calls a `_refresh_step_breadcrumb()` hook (no-op in
the base v1 window). `qt_ui_v2.py` adds `_StepBreadcrumb` (7 markers,
`○`/gray = pending, `●`/dodgerblue = active, `●`/green = completed,
`●`/red = failed -- colors matching this window's own existing
running/connected/not-connected conventions), placed first in the
"Status / Progress" group (top of the live-monitoring column, the one
built to stay visible without scrolling); `group.setMinimumHeight()`
bumped 175->187 to match the real measured minimumSizeHint with the new
row. Deliberately does not show a separate "stopping" visual during a
graceful stop (Session 78/80's indicator already owns that message) --
the breadcrumb keeps reporting the real in-progress state of the unit
that is still genuinely running to completion.

**Tests:** widget-level (7 markers in `STEP_ORDER`; `step_started` marks
only that step active; `step_completed`/`step_failed` render distinct
colors from `active` and from each other; `step_reset` clears every
marker including one left `active` mid-highlight, not just untouched
ones; base v1 window tracks `_step_states` correctly with no widget
attached) plus two **real, non-mocked progress-plumbing tests** calling
the actual `_run_experiment_series()`/`_run_temperature_experiment_series()`
chain (not `_handle_worker_progress()` called directly) -- confirming the
prerequisite fix lands for real: the non-TEC test found
`WaitForAd2Completion`/`Flush` are genuinely conditional in real
`run_experiment2()` (not always fired), corrected the test to assert
against that real, expected behavior rather than a wrong "all 7 always
fire" assumption; the TEC test confirms one `step_reset` + one
`SetTecTarget` + one `WaitTecStable`, correctly ordered, per temperature
point across 2 points.

**Real (non-offscreen) rendering verified**, not just the automated
offscreen suite: launched `MainWindowV2` on the real Qt platform at
1440x860, drove real progress events (two completed steps, one failed
step), screenshotted -- markers 1-2 render filled green, marker 3 filled
red, markers 4-7 hollow gray, exactly as designed, breadcrumb visible
without scrolling above Elapsed Time/Time Left/queue count.

**Full suite: 473 passed, 1 skipped** -- clean run, no flaky Qt failures
this time.

**Not committed** -- pending review, per standing instruction.

---

### Session 82 -- Save/Load Settings gap-closure, batch 1: Pump&Valve manual tab (including the confirmed-never-implemented fill_flow_rate)

**Preceded by a dedicated audit (same day)** that traced `schema_version`
back to commit `f569143` -- confirmed it has only ever gated the Hz->kHz
unit migration, never a broader persistence effort -- and enumerated every
control across every tab against the real, current `_settings_dict()`/
`_load_settings()`. Found the entire Pump&Valve manual tab, entire Camera
manual tab, entire Z-Scan tab, WFG's `wfg_running`, and the Experiment
tab's FM Sweep group + camera-acquisition-adjacent fields all genuinely
unpersisted today. Also found `fill_flow_rate` specifically was the
subject of an earlier task explicitly titled "persist new field per
existing Save/Load Settings convention" -- confirmed via grep that it was
never actually added to `_settings_dict()`/`_load_settings()`, and no
round-trip test for it exists, only a test that it's passed into
`refill()`/`empty()` calls (different, unrelated wiring). A real
instruction that was never executed, not a memory error.

**This session closes batch 1: the Pump&Valve manual tab only**, per
explicit scope. `_settings_dict()` (`qt_ui.py`) gained a new
`"pump_valve"` sub-dict, mirroring `"mso"`'s own existing sub-dict shape
(the audit's own recommendation) rather than scattering loose top-level
keys: `syringe`, `custom_syringe_volume_ml`,
`custom_syringe_inner_diameter_mm`, `custom_syringe_stroke_mm`,
`flow_rate`, `fill_flow_rate`, `level_ml`, `flush_flowrate`,
`flush_volume`, `wait_after_flush`, `flush_count`. `_load_settings()`
loads each field with the same tolerant `if key in data` pattern already
used everywhere else in this method -- an older settings.json with no
`"pump_valve"` key at all loads cleanly, leaving these fields at their
`_build_state()` construction defaults. No `schema_version` bump: these
are new keys, not a meaning change to an existing one, matching the exact
precedent the recent TEC field additions (`tec_lock_channels`/
`tec_points_ch2`/`tec_post_stable_hold_s`) already established.

**Confirmed, not assumed, that qt_ui_v2.py needed no changes:** checked
`"_settings_dict" in qt_ui_v2.MainWindowV2.__dict__` and
`"_load_settings" in qt_ui_v2.MainWindowV2.__dict__` directly after this
edit -- both `False`, confirming v2's Save/Load Settings menu actions
still resolve to the same inherited base-class methods, so this batch
applies to v2 automatically with no separate wiring.

**The manual tab's own `flush_flowrate`/`flush_volume`/`wait_after_flush`/
`flush_count` (`self.flush_flowrate` etc.) are distinct Qt objects from
the Experiment tab's own `exp_flush_flowrate`/`exp_flush_volume`/
`exp_wait_after_flush` (`self.exp_flush_flowrate` etc.) -- different
Python attributes, different settings.json keys (`"pump_valve"` vs.
`"experiment"`), confirmed by a dedicated test setting different values
on each and asserting both save and reload independently with no
cross-contamination.**

**Tests:** full save/load round trip for all 11 fields in this batch
(`test_qt_ui_save_and_restore_pump_valve_manual_tab_fields`); an
old-format settings.json missing the `"pump_valve"` key entirely still
loads without error, all fields at construction defaults
(`test_qt_ui_load_settings_without_pump_valve_key_loads_without_error`);
the manual-vs-Experiment-tab flush-field independence test described
above (`test_qt_ui_pump_valve_manual_flush_fields_round_trip_independently_of_experiment_flush_fields`).

**Full suite: 476 passed, 1 skipped** -- clean run, no flaky Qt failures
this time.

**Not committed** -- pending review, per standing instruction. Remaining
batches (Camera tab, Z-Scan tab, WFG `wfg_running`, Experiment tab's FM
Sweep + camera-acquisition fields) are out of scope for this session, per
the batch-1-only instruction.

---

### Session 83 -- Save/Load Settings gap-closure, batch 2: Camera manual tab (plus a real, deterministic process-crash root-cause and fix, not the usual pre-existing flakiness)

**Confirmed the field list against real current attribute names before
implementing**, per instruction -- `conversion_shifts` (not "shifts"), and
found `conversion_min`/`conversion_max` (both always `setReadOnly(True)`,
written only from `_set_conversion_range()`'s live-capture-derived
display range, never a user-set value) needed excluding, the same
disposition batch 1 gave nothing but this batch's own new find:
**`image_continuous` also needed excluding, for a different, more
consequential reason -- see below.**

**Implementation:** new `"camera"` sub-dict in `_settings_dict()`
(`qt_ui.py`), 17 fields: `roi_h_offset`/`roi_v_offset`/`roi_h_size`/
`roi_v_size`/`center_roi`, `exposure_ms` (the manual ROI-group field,
`self.exposure_ms` -- confirmed a distinct Qt object and settings key
from the Experiment tab's own `self.exp_exposure_ms`/`"experiment".
exposure_ms`, by a dedicated independence test), `conversion_method`/
`conversion_shifts`, `sequence_mode`/`sequence_source`/
`sequence_interval`/`sequence_burst`/`sequence_frames`, `capture_mode`,
`dcam_source`, `external_polarity`/`external_delay`,
`sequence_exposure_ms`. Tolerant `if key in data` loads for all, no
`schema_version` bump, matching batch 1's proven pattern exactly.
Confirmed `qt_ui_v2.py` needed no changes the same way batch 1 did --
`_settings_dict`/`_load_settings` still absent from
`MainWindowV2.__dict__`, checked directly.

**A real, deterministic full-suite process crash was found and root-
caused during verification -- not the documented pre-existing offscreen-
Qt flakiness class, despite initially looking identical to it.**
Constructing this batch's round-trip test crashed the entire pytest
process (no traceback, no catchable exception -- `exit 127`) 100% of the
time it ran after ~30 preceding tests in the same file, every attempt,
across many isolated bisection re-runs. Two false leads were investigated
and ruled out before the real cause was found: (1) the general "SystemError,
random widget, retry helps" class this codebase's own
`conftest.py:build_with_retry()` already documents and handles --
ruled out because retry/`.close()`/widening `_live_image_continuous_
checkbox()`'s except clause to also catch `SystemError` (a real,
independently-defensible improvement, kept) did not stop the crash; (2)
the checkbox's own documented "C++ object can be dead" fragility --
ruled out because a pure `.isChecked()` read never crashed, only
`.setChecked(True)` did, and `blockSignals()` around it didn't help
either. **Systematic field-by-field bisection within the real full-suite
context (not an isolated repro, which could not reproduce it) traced it
conclusively to `image_continuous.setChecked(True)`**, and inspecting
its connected `toggled` signal explained why: `_set_image_continuous()`
opens a real `ImagePreviewWindow`, starts a repeating `QTimer`, and
attempts a live camera capture -- real side effects entirely unrelated to
what a settings round-trip test (or, more importantly, `_load_settings()`
loading a saved settings.json at real app startup) should ever trigger.
**Fix: excluded `image_continuous` from persistence entirely** -- not a
test workaround, a genuine design correction: unlike every other field in
this batch, it is a live action trigger, not passive configuration, and
restoring it via `_load_settings()` would auto-start continuous capture
the instant settings load, before hardware is even connected. Same
category as `conversion_min`/`conversion_max`'s exclusion (a value that
shouldn't be treated as a saved preference), reached via a different
mechanism (an action side effect instead of a computed readout).

**Tests:** full round trip for the 17 included fields
(`test_qt_ui_save_and_restore_camera_manual_tab_fields`); old-format
settings.json missing the `"camera"` key loads cleanly at construction
defaults (`test_qt_ui_load_settings_without_camera_key_loads_without_error`);
manual-vs-Experiment `exposure_ms` independence test, mirroring batch 1's
flush-field independence test
(`test_qt_ui_camera_manual_exposure_field_round_trips_independently_of_experiment_exposure_field`);
explicit assertions that `conversion_min`/`conversion_max`/
`image_continuous` are absent from the saved dict, not just omitted by
oversight.

**Full suite: 495 passed, 1 skipped** -- clean run. (Two unrelated,
different-widget-each-time `RuntimeError: already deleted` failures
appeared on other full-suite attempts during this session's own
verification passes -- confirmed via isolated re-run both times as the
genuinely pre-existing, already-documented offscreen-Qt flakiness class,
not a regression; contrast with the crash investigated and fixed above,
which was 100% deterministic and had a real root cause.)

**Not committed** -- pending review, per standing instruction.

---

### Session 84 -- Save/Load Settings gap-closure, batch 3: Z-Scan manual tab

**Confirmed the 5-field list against real current attribute names**
before implementing (`zscan_output_dir`, `zscan_z_start_um`,
`zscan_z_end_um`, `zscan_step_size_um`, `zscan_exposure_ms`) -- all
matched exactly, no renames needed this time.

**Applied batch 2's lesson explicitly, not just by habit:** grepped all
5 fields for any connected `.valueChanged`/`.textChanged`/
`.editingFinished` signal before writing a single line of persistence
code. None exists -- none of these 5 fields is a live action trigger the
way `image_continuous` was. But the check surfaced a different, real
correctness hazard specific to two of them: `zscan_z_start_um`/
`zscan_z_end_um` are constructed disabled with range `[0.0, 0.0]` and
only get a real range (and get enabled) via `_apply_zscan_range()`,
itself only ever called after a genuine `_query_zscan_range()` hardware
read of the piezo's `MaxTravel`. A bare `widget.setValue(loaded_value)`
at load time -- before any hardware has ever been queried in a fresh
process -- would have silently clamped a real saved value straight to
`0.0` (standard Qt spin-box behavior: `setValue()` clamps into the
current `[minimum, maximum]`). Not a crash, not a live-action trigger,
but the same class of "looks like it persisted, silently didn't" trap
in spirit.

**Fix, in `_load_settings()` only (not a widget-lifecycle change):**
for these two fields specifically, widen `.setMaximum()` to the loaded
value first if it exceeds the field's current maximum, then
`.setValue()`. The field stays disabled exactly as it already does by
default -- only the numeric range is touched, not the enablement gate --
and `_apply_zscan_range()` still fully overwrites this range with the
real device-reported bound the next time a genuine hardware query runs,
so this does not weaken that safety gate in any way.

**Implementation:** new `"zscan"` sub-dict in `_settings_dict()`, all 5
fields; tolerant `if key in data` loads in `_load_settings()`, no
`schema_version` bump -- same proven shape as batches 1-2. Confirmed
`qt_ui_v2.py` needed no changes by direct `MainWindowV2.__dict__` check,
both before and after the edit.

**Tests:** full round trip
(`test_qt_ui_save_and_restore_zscan_tab_fields`) -- deliberately uses
`zscan_z_start_um`/`zscan_z_end_um` values (12.5/487.5) that exceed the
field's real default `[0.0, 0.0]` range on the freshly-constructed
`second_window`, specifically to prove the range-widening fix actually
engages rather than merely happening to fit; also confirms both fields
stay disabled after load, matching the unchanged safety gate. Old-format
settings.json missing the `"zscan"` key loads cleanly at construction
defaults, including confirming `isEnabled() is False` for both
range-gated fields
(`test_qt_ui_load_settings_without_zscan_key_loads_without_error`).

**Full suite: 497 passed, 1 skipped** -- clean on the confirming re-run.
(Two different-widget `SystemError: <class> returned NULL without
setting an exception` failures appeared on the first full-suite attempt
this session -- one in an unrelated batch-1 test, one in `test_qt_ui_v3.py`,
neither touched by this batch's changes -- confirmed via isolated re-run
both times as the same pre-existing, already-documented offscreen-Qt
flakiness class this project has hit repeatedly, not a regression.)

**Not committed** -- pending review, per standing instruction. Remaining
batch: WFG's `wfg_running`, and the Experiment tab's FM Sweep +
camera-acquisition-adjacent fields.

---

### Session 85 -- Save/Load Settings gap-closure, batch 4 (final): WFG running + FM Sweep/camera-acquisition, plus v3 Proposal C adoption

**Part 1 -- final persistence batch.** Confirmed all field names against
real current attributes first, same discipline as batches 1-3 -- all
matched, `camera_start_array` confirmed exactly 10 widgets
(`range(10)`). Applied both standing checks (batch 2's live-action-
trigger grep, batch 3's disabled/range-gated-state check) to all 15
fields explicitly before implementing: no connected
`.valueChanged`/`.toggled`/`.stateChanged` signal with a real side
effect on any of them, and none is disabled or range-gated at
construction the way `zscan_z_start_um`/`zscan_z_end_um` were -- both
checks came back clean this time, no special load-time handling needed.
One real design decision surfaced: `wfg_running` could not be nested
under a new `"wfg"` sub-dict the way batches 1-3 nested their new
fields, because `"wfg"` is already the existing per-channel list key --
added as a plain top-level `"wfg_running"` key instead to avoid the
collision. FM Sweep's `sweep_start_khz`/`sweep_stop_khz`/
`sweep_center_khz`/`sweep_width_khz` are cross-synced live by
`_connect_sweep_dual_mode_refresh()` (pure UI-side arithmetic, no
hardware touch, confirmed not a live action trigger) -- all four
persisted anyway for an exact round trip rather than relying on
recomputation from just the primary pair. All fields added as tolerant,
purely-additive keys (`"wfg_running"` top-level; the rest under the
existing `"experiment"` dict), no `schema_version` bump. Confirmed
`qt_ui_v2.py` needed no changes by direct `MainWindowV2.__dict__` check.

**This closes the Save/Load Settings gap-closure effort entirely** --
every field identified in the original audit (2026-08-04) across
Pump&Valve, Camera, Z-Scan, WFG, and the Experiment tab's FM
Sweep/camera-acquisition fields is now persisted, with three
deliberate, documented exclusions (`conversion_min`/`conversion_max`,
`image_continuous`) for fields that are genuinely not passive
configuration.

**Part 2 -- v3 design-idea adoption, Proposal C.** Added or confirmed a
one-line orienting note at the top of every manual test panel stating
its relationship to automated Experiment runs, matching the model
wording already correct on the WFG tab (`qt_ui.py`, unchanged).
Confirmed via grep that MSO is never referenced anywhere in
`application.py`/`workflows.py`, so its "does NOT affect" note is
genuinely, not just apparently, true. Camera tab already had a
correctly-scoped "DO affect" note on its Sequence Settings group
specifically (not duplicated) -- added a top-level note alongside it
covering the rest of the tab (Image/ROI/Conversion, confirmed
independent by batch 2's own `exposure_ms` independence test) and
pointing to the Sequence Settings exception rather than restating it.
Pump&Valve and Z-Scan tabs had no top-level orienting note at all --
added both, Pump&Valve's confirmed against batch 1's own manual-vs-
Experiment flush-field independence test, Z-Scan's confirmed by
tracing that its calibration workflow is never called from
`run_experiment2()`/the automated path at all. Z-Scan's existing "Scan
Control" hint (about needing the Camera tab's Configure Camera first)
covers a different topic and was left untouched, not merged with the
new note. Shared by v1 and v2 automatically (same source methods, no
separate v2 wiring needed). `qt_ui_v3.py` itself untouched throughout,
per instruction.

**Verification:** real (non-offscreen) render of all 5 manual tabs
confirmed every note wraps cleanly with no layout breakage, including
the Camera and Z-Scan tabs' grid-row insertions (existing widgets
shifted down one row programmatically, not by hand-editing every
`addWidget` call's row index individually).

**Tests:** full round trip for all 15 batch-4 fields, including reading
back the FM Sweep dual-mode sync's own live-recomputed center/width
values (not hardcoded expectations) to confirm the saved values stay
internally consistent; old-format settings.json missing all batch-4
keys loads cleanly at construction defaults.

**Full suite: 499 passed, 1 skipped** on the clean run. (A further
re-run surfaced two more different-widget-each-time `SystemError`/
`RuntimeError` failures -- one in a pre-existing, untouched-by-this-
batch test, one in `test_qt_ui_v3.py` -- both confirmed passing in
isolation as the same pre-existing offscreen-Qt flakiness class hit
repeatedly throughout this whole gap-closure effort, not a regression.)

**Not committed** -- pending review, per standing instruction.

---

### Session 86 -- Backfill: waveforms.py's configure_do() ambiguous-trigger-timing refusal (found undocumented during commit preparation)

Found while drafting a commit message spanning the accumulated diff since
17f24dd: `WaveFormsBackend.configure_do()` (waveforms.py, currently
[waveforms.py:546](../src/thermo_acoustic/waveforms.py:546)) contains a
real fix with no changelog entry anywhere (confirmed via grep for
`trigger_signatures`/`different global trigger` across this file --
zero prior matches). No in-code date marker exists for this specific
change; dated here from the file's own last-modified timestamp
(2026-08-04), consistent with the working-tree period other same-day
fixes in this file (`_coerce_enum()`, see Session 88 below) are dated
to.

**The bug:** WaveForms exposes Wait/Run/Repeat/TriggerSource once for
the whole DigitalOut instrument, not once per channel -- `configure_do()`'s
per-channel loop unconditionally overwrote the shared `trigger`/
`trigger_source` locals on every iteration, so with more than one
channel configured, whichever channel happened to be last in
`config.channels` silently won, including a disabled trailing channel
overwriting the timing actually intended for the live output.

**The fix:** before the loop, build a `trigger_signatures` set from the
`(sec_wait, sec_run, repeat_count, repeat_trigger, source)` tuple of
every *enabled* channel only. If more than one distinct signature
exists, raise `WaveFormsError` ("Digital output channels request
different global trigger timing...") instead of silently picking one.
The loop itself now only lets an `channel.enable == True` channel select
the shared `trigger`/`trigger_source` values, so a disabled trailing
channel can no longer participate at all.

**Not committed** -- pending review, per standing instruction; this is a
documentation-only entry for an already-landed code change.

---

### Session 87 -- Backfill: hamamatsu_dcam.py's open_camera() rollback-on-failure (found undocumented during commit preparation)

Also found undocumented while drafting the same commit message (grep for
`open_camera.*rollback`/`rollback.*open_camera`/`Dcam.dev_close after
failed` across changelog and known_open_items.md returned zero matches).
Dated from the file's own last-modified timestamp (2026-08-04); no
in-code date marker exists.

**The bug:** `HamamatsuDcamBackend.open_camera()`
([hamamatsu_dcam.py:69](../src/thermo_acoustic/hamamatsu_dcam.py:69))
previously ran its 2-3 step open sequence (load SDK, `Dcamapi.init()`,
`Dcam.dev_open()`) with no rollback on a mid-sequence failure -- if
`dev_open()` raised after `Dcamapi.init()` had already succeeded, the
API was left initialized with no device open and no way for a
subsequent retry to know that state without its own separate check.

**The fix:** the whole body is now wrapped in try/except. On failure,
rollback is attempted in reverse: close the device if it was opened
(`Dcam.dev_close()`), then uninit the API if `init()` had succeeded
(`Dcamapi.uninit()`). Rollback errors are collected separately from the
original exception; if rollback itself failed, a combined
`HamamatsuDcamError` is raised naming both the original failure and the
rollback failure(s); if rollback succeeded, the original exception is
re-raised unchanged. Leaves no partial init state for a caller to
reason about after a failed `open_camera()`.

**Not committed** -- pending review, per standing instruction; this is a
documentation-only entry for an already-landed code change.

---

### Session 88 -- Backfill: ad2.py's _coerce_enum() / waveforms.py's _enum_value() fail-closed on unrecognized values (promoting an inline "pending review" note to a real entry)

`docs/known_open_items.md`'s waveforms.py backlog section carried only an
inline "Resolved in the current working tree (2026-08-04; pending
review)" note for this change, with no changelog Session entry -- this
entry gives it one; the known_open_items.md note has been updated to
point here (see below).

**The bug (Session 66's own original finding, only partially fixed at
the time):** `_coerce_enum()` (ad2.py) and `_enum_value()`
(waveforms.py) both silently returned/mapped to a default value for
*any* unrecognized input, including an explicitly-supplied but
misspelled or genuinely-unsupported enum string -- not just a truly
missing field. A typo in a dict-shaped WFG/DO config (e.g. from a
saved-settings round trip or a manually-constructed config) could
silently select the wrong hardware mode with zero error.

**The fix:**
- `ad2._coerce_enum(enum_type, value, default)`
  ([ad2.py:228](../src/thermo_acoustic/ad2.py:228)): `value is None` still
  returns `default` (a genuinely missing field keeps its documented
  compatibility default), but any other unrecognized value now raises
  `ValueError(f"Unsupported {enum_type.__name__}: {value!r}")`.
- `WaveFormsBackend._enum_value(mapping, value)`
  ([waveforms.py:194](../src/thermo_acoustic/waveforms.py:194)): dropped
  its `default` parameter entirely -- accepts a raw `int` (an SDK value
  passed straight through) or a recognized mapping key, and otherwise
  raises `WaveFormsError(f"Unsupported WaveForms enum value: {value!r}")`.
  No silent-default path remains at all in this function; the "missing
  field keeps its default" behavior is now exclusively `ad2.py`'s
  responsibility, applied before a value ever reaches this function.
- `coerce_wfg_config()`/`coerce_do_config()` (ad2.py) had their
  dict-key detection sets significantly expanded (offset/symmetry/
  phase/function/enable/trigger keys for WFG; clock_frequency_hz/
  frequency/output_type/output_mode/idle_state/trigger keys for DO) --
  reduces how often a dict-shaped input's field is misread as "missing"
  (and silently defaulted) versus correctly recognized as an explicit,
  possibly-invalid value that must now be validated.

**Tests:** focused fake-only regression tests cover both the
missing-field-keeps-default boundary and the explicit-unrecognized-
value-raises boundary; full offline suite passes.

**Not committed** -- pending review, per standing instruction; this is a
documentation-only entry for an already-landed code change.

---

### Session 89 -- Backfill: shared hardware-utility extraction -- hw_logging.run_with_timeout() and Application._move_pump_and_confirm() (found undocumented during commit preparation)

Part of the cross-module architecture review (2026-08-02, matching the
in-code dating already used for this effort in qmix_backend.py's and
thorlabs_piezo.py's own comments) -- previously only mentioned in
passing inside Session 74's TEC entry, with no entry of its own.
Confirmed genuinely new since `17f24dd` via
`git show 17f24dd:<file> | grep <name>` on both functions below (both
returned empty against the 17f24dd-committed content).

**hw_logging.run_with_timeout(action, name, timeout_s) -> str | None**
([hw_logging.py:127](../src/thermo_acoustic/hw_logging.py:127)): runs
`action()` in a daemon thread with a bounded join, so a real hardware
cleanup/close/disconnect call that hangs cannot block the caller
indefinitely. Never raises itself -- returns `None` on success, or a
one-line description of what went wrong (timeout, a raised exception,
or the thread finishing without reporting a result) for the caller to
collect. Replaces three independent, hand-copied implementations of the
identical thread+queue+join shape:
`QmixPumpBackend._run_close_step()`, `PiezoStage._run_disconnect_step()`,
and `Application`'s own cleanup-call timeout guard. Message wording at
each call site is unchanged from before the extraction.

**Application._move_pump_and_confirm(action, timeout_s, event_prefix) -> bool**
([application.py:439](../src/thermo_acoustic/application.py:439)):
consolidates `refill()`, `empty()`, and `go_to_level()`, which
independently had the identical bug -- `set_fill_level()` is an
asynchronous SDK call, and all three previously returned as soon as the
command was issued rather than once the pump actually arrived (found
independently by the qmix_backend.py line-by-line review's Fix H1 and
the targeted qt_ui.py UI audit's Finding 1 -- two different reviews,
same root bug, on three different buttons). On a wait timeout, requests
an SDK stop (fail closed) before reporting `TimedOut` -- explicitly
distinct from Abort, which intentionally does not interrupt an
in-progress pump operation (see Session 78). Always re-syncs
`fill_level` from the real device after waiting, even on the success
path, since a pre-confirmation snapshot cannot be trusted. `flush()` is
deliberately NOT migrated to this helper -- it has its own capacity
pre-check and a sandwiched valve move that don't generalize into this
shape.

**docs/hardware_safety_patterns.md** gained a new named pattern, Pattern
(e) -- "Commit configuration state only after the real hardware call
confirms" -- documenting a *different*, related shape found six times
across five files (`CetoniPump.set_fill_level()`, `Valve.set_position()`,
`CetoniPump.refill()`/`empty()`, `HamamatsuDcamBackend.configure_sequence()`,
and `AD2Sdk`'s six WFG/DO config methods): coerce/build the new
configuration into a local variable, issue the real hardware call(s)
using the local, and only assign it to `self.X` once every call
succeeds. Deliberately NOT consolidated into one shared helper the way
the two functions above were -- the hardware-call shape differs enough
case to case that this is documented as a principle to apply by hand,
not a procedure to call.

**Not committed** -- pending review, per standing instruction; this is a
documentation-only entry for an already-landed code change.

---

### Session 90 -- Backfill: v2's Error Out black-rectangle rendering fix (found undocumented during commit preparation)

Dated from the diff's own in-code comment ("Real-platform rendering bug
(2026-08-03)") -- confirmed via grep across the changelog for
`Error Out black-rectangle`/`_configuration_column`/
`_live_monitoring_column`/`_CompactPlaceholderRow`/`WFG live waveform
preview`/`sidebar status indicator`/`Phase 0`/`Phase 1`/`Phase 2`/
`Phase 3` (beyond the already-documented breadcrumb) that none of v2's
restructuring work has a searchable changelog entry anywhere. This is
the first of three entries backfilling that gap (see Sessions 91-92
below); the step-progress breadcrumb itself already has its own entry
(Session 81) and needs no new one.

**The bug:** `qt_ui_v2.py`'s Global Status group's "Error Out" row
(`self.error_log`, a `HistoryLogWidget`) inherits `QListWidget`'s
default Expanding vertical `QSizePolicy`. Combined with the enclosing
`QFormLayout`'s `WrapLongRows` policy, whether the row wraps or sits
side-by-side is width-timing-sensitive on the real Qt platform (the
offscreen test platform always wrapped cleanly and never reproduced
this). When it doesn't wrap, `QFormLayout` gives the row's field cell a
height driven by the Expanding policy (measured 575px, against the
widget's own 90px `maximumHeight`-capped size), then vertically centers
the small widget inside that oversized cell -- the ~485px of empty cell
above/below is what a real user screenshot showed as a solid black
rectangle swallowing the actual log content.

**The fix:** caps the *wrapper's* own height (after
`_add_tooltip_icons()` wraps the row), not `self.error_log`'s own
vertical `QSizePolicy`. Setting `error_log`'s own policy to `Maximum`
was tried first and reverted -- confirmed by direct experiment to break
other `WrapLongRows` rows in the same form that use `wordWrap()`'d
runtime text (e.g. the valve's `status_note` passthrough getting stuck
at an 8px single-line height instead of re-wrapping on a later text
change).

**Not committed** -- pending review, per standing instruction; this is a
documentation-only entry for an already-landed code change.

---

### Session 91 -- Backfill: v2 restructure, proposals 1 and 2 -- compact placeholder rows and the configuration/live-monitoring column split (found undocumented during commit preparation)

Dated from the diff's own in-code comments: "Redesign (2026-08-03,
restructure proposal 1)" and "Restructure (2026-08-03, proposal 2)".
Second of three backfill entries for v2's undocumented restructuring
work (see Session 90 above, Session 92 below).

**Motivation (v2 audit finding 1d, 2026-08-02):** the prior single
shared-scroll `_center_experiment_area()` meant the AD2 Output
Parameters table's own inner horizontal scroll forced the *entire*
center column to also scroll horizontally with it, and a long step
card's configuration content could push live status/progress
information out of view entirely.

**Proposal 1 -- `_CompactPlaceholderRow`** (new class,
[qt_ui_v2.py:205](../src/thermo_acoustic/qt_ui_v2.py:205)): a
single-line stand-in for a step card with no real configuration content
(bullet, numbered step title, em dash, grayed/italic "no configuration"
note) replacing a prior full-height placeholder card that competed for
screen space without adding content. Carries its own `.title()` so
callers that ask a step card for its title don't need to know which of
the two card types they got.

**Proposal 2 -- column split** (`_configuration_column()`/
`_live_monitoring_column()`,
[qt_ui_v2.py:524](../src/thermo_acoustic/qt_ui_v2.py:524) and
[:557](../src/thermo_acoustic/qt_ui_v2.py:557), replacing
`_center_experiment_area()`): configuration content (set once before a
run -- the TEC-scan group and the experiment sequence view) separated
into its own independently-scrolling column from live-monitoring
content (status/progress, waveform preview, connection/error state --
watched during/after a run), matching Digilent WaveForms' own
config-panel + live-preview convention. Growing configuration content
can no longer push live status out of view, and the AD2 table's inner
horizontal scroll no longer drags either column with it.

**Verification:** before/after scroll dimensions measured at 1440x860
on a real (non-offscreen) render; full test suite run after the
restructure.

**Not committed** -- pending review, per standing instruction; this is a
documentation-only entry for an already-landed code change.

---

### Session 92 -- Backfill: v2 restructure Phase 2 -- WFG live waveform preview (Part A) and sidebar connection/status dots (Part B) (found undocumented during commit preparation)

No explicit date comment survives on Phase 2 itself in the diff (unlike
Phase 3's "2026-08-04" and the restructure proposals' "2026-08-03");
placed here between them in the same restructuring sequence per the
diff's own "Phase 2 Part A"/"Phase 2 Part B" labeling. Third and final
entry backfilling v2's undocumented restructuring work (see Sessions
90-91 above).

**Part A -- WFG live waveform preview**
(`_wfg_preview_group()`/`_update_wfg_preview()`/`_schedule_wfg_preview_update()`,
[qt_ui_v2.py:913](../src/thermo_acoustic/qt_ui_v2.py:913)): the v2 WFG
manual-test panel gained a "Waveform Preview (computed)" group showing a
`WaveformGraph` synthesized from the current Ch1/Ch2 field values (not
read from hardware), reusing the same waveform-synthesis path `qt_ui.py`'s
own WFG tab already uses. Recomputes on a 150ms debounced `QTimer`
restarted on every relevant field change (Function/Frequency/Amplitude/
Offset/Symmetry/Phase/Enable) -- no per-keystroke live-recompute
precedent existed elsewhere in this app to reuse (MSO's own graph only
updates on its Capture button click), so a short singleShot debounce was
used instead of recomputing synchronously on every keystroke. Disabled
channels are omitted from the preview.

**Part B -- sidebar connection/status dots**
(`_make_status_dot()`/`_set_status_dot()`,
[qt_ui_v2.py:494](../src/thermo_acoustic/qt_ui_v2.py:494)): each sidebar
device button (AD2/Camera/Pump&Valve/etc.) gained a small colored dot
reusing the exact same state reads as the existing Global Status panel
(not a fabricated separate signal) -- gray for disabled or not-yet-
connected (the Global Status panel's own text already collapses those
two states into one read, so the dot doesn't distinguish them further
either), green for connected (matching `connection_button`'s own
existing "connected" color), and a new blue ("dodgerblue") for actively
running, since no existing color in this app previously represented
that state. MSO/WFG/Camera share one dot keyed to their underlying
device (AD2 for WFG/MSO, Camera for Camera) rather than each getting an
independent one, since showing only half the picture per device would
misleadingly imply more than it means.

**Not committed** -- pending review, per standing instruction; this is a
documentation-only entry for an already-landed code change.

---

### Session 93 -- v2 restructuring, v3 design-idea adoption Proposal A: elevate "Start Experiment" to its own prominent group

Continuing the earlier v3 design evaluation (Proposal C already adopted,
Session 85) -- this implements the first of the three remaining scoped
proposals.

**Investigation.** "Start exp" previously sat as one of several
equally-weighted rows/cards: a flat grid row in `qt_ui.py`'s
`_experiment_tab()`, and a "Sequence Control" `QGroupBox` buried as
step-card 1 of 7 inside v2's (now-retired, see Session 94)
`ExperimentSequenceView`. Confirmed `self.series_path`
(persistent `QLineEdit`, built once in `_build_state()`),
`self._browse_folder`, and `self._start_experiment` as the real,
reusable state -- the `start`/`browse` `QPushButton`s themselves were
already freshly constructed on every call in both prior locations, same
as every other builder in this codebase.

**Implementation.** New `Application`-adjacent
`_experiment_primary_run_control_group()` (`qt_ui.py`, shared base
class -- v2 inherits it automatically): a dedicated `QGroupBox("Run
Experiment")` with a 44px-tall Start button, the series-path field +
browse button, and an inline scope-disclosure note ("Uses the
configured setup below and the currently initialized hardware.") --
reusing v3's own wording for this note, confirmed to already match this
project's tone. Placed at the TOP of `qt_ui.py`'s `_experiment_tab()`
grid (v1) and as the first widget inside `qt_ui_v2.py`'s
`_configuration_column()` (v2) -- deliberately NOT stacked above the
config/live-monitoring column split, which would compete with the
live-monitoring column's own always-visible screen space (the specific
stacking mistake v3's own layout makes, flagged during the earlier
evaluation and explicitly avoided here). `_v2_sequence_control_group()`
retired as redundant (see Session 94 -- both changes landed together
since they touch the same method).

**Verification:** real (non-offscreen) render at 1440x860 confirmed the
live-monitoring column remains fully visible without page-level
scrolling with the new group in place (see Session 94's entry for the
combined measurement, taken after Proposal B also landed).

**Tests:** `test_v2_primary_run_control_group_reuses_series_path_and_start_button`,
`test_v2_configuration_column_places_run_control_above_setup_tabs`
(tests/test_qt_ui_v2.py). `test_hardware_action_buttons_disclose_missing_global_confirmation_gate`
(tests/test_qt_ui_hardware_settings.py) continued to pass unchanged --
the Start button's tooltip text is byte-identical to before.

**Not committed** -- pending review, per standing instruction.

---

### Session 94 -- v2 restructuring, v3 design-idea adoption Proposal B: task-oriented setup tabs replace the per-step card sequence

**Investigation.** Confirmed the builder-method mapping: AD2 Output ->
`_v2_ad2_output_group()` (qt_ui_v2.py) + `_experiment_fm_sweep_group()`
+ `_experiment_frequency_scan_group()` (qt_ui.py, already reused as-is);
Camera -> `_v2_acquisition_group()` (qt_ui_v2.py); Fluidics ->
`_experiment_flush_group()` (qt_ui.py); Advanced ->
`_experiment_temperature_group()` (qt_ui.py). Also found, not mentioned
in the original proposal: `ExperimentSequenceView`'s own docstring
states Phase 2 was "Configuration Mode only... no live wiring," and
Phase 3's live highlighting was planned to go *into that view's own
cards* but was never built there -- the real Session 81 implementation
instead built the fully separate `_StepBreadcrumb` widget in the
Status/Progress group. Replacing the step-card view with tabs therefore
removes no live functionality; the breadcrumb is unaffected either way.
~15 assertions in tests/test_qt_ui_v2.py called `view.step_card(...)`/
`window._experiment_sequence_view()` directly and needed rewriting
against the new structure -- the "medium-risk" item the original
proposal flagged.

**Implementation.** New `_v2_experiment_setup_tabs()` (qt_ui_v2.py): a
`QTabWidget` with "AD2 Output"/"Camera"/"Fluidics"/"Advanced" tabs, each
re-parenting the existing group-box builders whole (not rebuilt),
replacing `_experiment_temperature_group()` + `_experiment_sequence_view()`
in `_configuration_column()`. Fluidics tab carries "Optional
post-capture pump/valve workflow. Disabled by default."; Advanced
carries "Simulated by default. Real TEC operation remains unapproved."
(reusing v3's own wording, confirmed to already match this project's
TEC safety framing). The sequential valve->pump->valve safety
explanation that used to live on the Flush step card's own tooltip is
now set directly on the Flush group box itself (`flush_group.setToolTip(...)`)
-- caught and fixed during implementation as a real regression risk
(the first draft only left this as a code comment, not attached to any
widget, which would have silently dropped it from the real UI).
`ExperimentSequenceView`, `_CompactPlaceholderRow`,
`_experiment_sequence_view()`, and `_v2_sequence_control_group()`
(Session 93) retired as genuinely dead code once nothing called them --
3 stale comment references to `ExperimentSequenceView` elsewhere
(`application.py`'s `STEP_ORDER` comment, `_StepBreadcrumb`'s own
docstring x2) updated to stop describing a class that no longer exists.

**Verification:** real (non-offscreen) render at 1440x860 (v2,
`MainWindowV2`, both Proposal A and B in place): the live-monitoring
column's `QScrollArea` measured 320x809px, fully visible on screen with
no page-level scrolling required to reach it -- confirmed as a
DIFFERENT `QScrollArea` instance from the configuration column (the
two-column split is intact). Its own internal content `sizeHint()`
(830px) is ~21px taller than its own viewport (809px) -- an existing,
pre-existing characteristic of `_live_monitoring_column()` itself
(untouched by this change; nothing in Proposals A/B/D modified
`_v2_status_progress_group()`/`_v2_waveform_group()`/
`_global_status_panel()`), causing a small internal scrollbar within
that column only, not a regression of the "live status stays visible
without scrolling past configuration" principle this restructure
protects (that principle is about the outer/page-level scroll, which
this column is independent of by design). Screenshots taken at
1440x860 for both v1 (`Experiment` tab) and v2 (full window) confirm
clean layout with no clipping or overlap.

**Tests:** `test_v2_experiment_setup_tabs_has_four_task_oriented_tabs`,
`test_v2_experiment_setup_tabs_embeds_the_real_shared_group_widgets`,
`test_v2_flush_group_tooltip_explains_the_real_sequential_valve_pump_relationship`,
`test_v2_experiment_setup_tabs_have_inline_safety_caveats`
(tests/test_qt_ui_v2.py) replace the 5 retired
`ExperimentSequenceView`-specific tests.

**Full suite: 500 passed, 1 skipped** (one further run surfaced 1 more
different-test-each-time `SystemError` failure --
`test_camera_adjust_reprocesses_last_raw_frame_without_recapture`, a
Z-Scan/Camera-tab test unrelated to this change -- confirmed passing in
isolation as the same pre-existing offscreen/real-platform `_TooltipIconWrapper`
flakiness class hit repeatedly throughout this project's history, not a
regression; also observed directly on the real platform during this
session's own verification script runs, confirming it is not
offscreen-specific).

**Not committed** -- pending review, per standing instruction.

---

### Session 95 -- v2 restructuring, v3 design-idea adoption Proposal D: split Pump&Valve tab into Operational vs Static configuration

**Investigation.** Confirmed `_pump_tab()` (qt_ui.py) is shared by v1
and v2 (`MainWindowV2._MANUAL_PANEL_BUILDERS["PumpValve"] = "_pump_tab"`
maps directly to it), so editing it once updates both, no separate v2
change needed. Mapped its existing 4 columns onto operational-vs-static:
**operational** (touched every run) = Valve (Pos1/Pos2), Pump's
Refill/Empty + flow rate, Flow Control, Flush + Flush Settings, STOP;
**static** (one-time-per-mount setup) = Setup (Reference move -- its
own existing comment already called this "a one-time-per-mount
calibration step"), Syringe (selection/custom geometry/Configure).

**Implementation.** `_pump_tab()` restructured into two labeled
sections -- "Operational controls" (Valve+STOP / Pump / Flow Control /
Flush, unchanged internally, same 4 columns minus Setup/Syringe) then
"Static configuration" (Setup / Syringe, in their own row) -- reusing
every existing widget verbatim, no new state. Continues the same
precedent Reference Move's own leading Setup section already
established (UI layout audit Part 3, 2026-08-03): Reference move must
happen BEFORE a syringe is loaded/refilled, so it stays with the other
one-time setup, not mixed into Flow Control's actual flow-rate
controls.

**Verification:** real (non-offscreen) render at 1440x860 (v1's
Pump&Valve tab) confirms clean two-section layout with no clipping.

**Tests:** `test_pump_tab_reference_move_is_promoted_to_a_leading_setup_group`
(tests/test_qt_ui_hardware_settings.py) updated -- its original
assertion that "Setup" must be the literal first `QGroupBox` in the
whole tab no longer holds now that "Operational controls" reads first;
replaced with confirming Setup still precedes Syringe within "Static
configuration" (the ordering intent the test actually protects: Reference
move before syringe selection/loading). All other existing Pump&Valve
tests (valve position tokens, etc.) passed unchanged.

**Full suite: 500 passed, 1 skipped, 1 flaky failure** (same
pre-existing `_TooltipIconWrapper` `SystemError` class as Session 94's
entry, confirmed passing in isolation, unrelated to this change).

**Not committed** -- pending review, per standing instruction.

---

### Session 96 -- Valve post-open handshake rollback and AD2 initialization audit

**Confirmed failure shape.** `Valve.initialize()` opened its serial backend
before issuing the `S` status handshake. A query exception, empty response, or
unrecognized response then escaped without closing that just-opened backend.
`Application.initialize()` could not repair this because it only rolls back
instruments whose own `initialize()` calls already completed.

**Implementation.** `Valve.initialize()` now closes its own backend whenever
the open/handshake sequence raises. If close succeeds, the original exception
is re-raised unchanged. If close also fails, a combined `ValveError` reports
both failures and chains from the original handshake exception. Application
initialization order and rollback scope are unchanged.

**AD2 audit.** No matching gap was found. `AD2Sdk.open_and_use_first_device()`
assigns `device_handle` only after `WaveFormsBackend.open_device()` has returned
successfully, and `AD2Sdk.initialize()` has no post-open handshake/configuration
step that can fail after ownership is committed. No AD2 code was changed.

**Regression coverage.** Focused fake-backend tests assert that a handshake
exception closes the backend and propagates as the same exception object, and
that a simultaneous close failure reports both errors while retaining the
handshake exception as the cause. The existing empty-response and unknown-status
tests also assert that the backend is closed.

**Verification:** focused Valve initialization tests: **10 passed**. Full suite:
**502 passed, 1 skipped, 2 failed**; both failures were the pre-existing,
suite-order-dependent `_TooltipIconWrapper` `SystemError` in two v3 tests and
both passed immediately in isolation (**2 passed**). v3 was explicitly out of
scope and was not changed.

**Not committed** -- pending review, per standing instruction.

---

### Session 97 -- CetoniPump.initialize() rollback on post-open fill-level readback failure

Continues the same instrument-initialize-rollback theme as Session 96's Valve
fix, found and verified during a documentation/consistency audit of a
concurrent session's work (not authored in this conversation; verified here
before logging).

**Confirmed failure shape.** `CetoniPump.initialize()` called
`self.backend.initialize(self.configuration_path)` then unconditionally
`self.sync_fill_level()`. If the real device's fill-level readback failed
after a successful backend open, the exception propagated with the backend
left open and `self.initialized` never set -- no rollback, unlike every other
instrument's initialize() failure path.

**Implementation.** `CetoniPump.initialize()` now tracks `backend_initialized`
separately from success. A failure before the backend finishes opening
(inside `QmixPumpBackend.initialize()` itself) still propagates unchanged --
that backend owns its own rollback. A failure *after* a successful backend
open (i.e., inside `sync_fill_level()`) now closes the backend, with a
combined `RuntimeError` if the close itself also fails, preserving the
original exception as the cause either way.

**Regression coverage:** `test_cetoni_pump_initialize_closes_backend_when_post_open_fill_read_fails`,
`test_cetoni_pump_initialize_reports_post_open_failure_and_cleanup_failure`
(tests/test_application.py) -- both confirmed passing, alongside the 3
pre-existing tests in the same area
(`test_cetoni_pump_initialize_syncs_fill_level_from_real_backend`,
`test_cetoni_pump_initialize_without_backend_leaves_fill_level_untouched`,
`test_cetoni_pump_initialize_does_not_falsely_claim_referenced`).

**Verification:** focused tests, 5/5 passed. No interaction found with any
other change in the current working tree.

**Not committed** -- pending review, per standing instruction. Originated
from a concurrent session; this entry documents and verifies it, not adopts
it on your behalf.

---

### Session 98 -- TecController.cleanup() and failed-initialize rollback now timeout-guarded

Closes the exact gap `docs/known_open_items.md` had flagged OPEN (found
during the cross-module architecture review, 2026-08-02): "`TecController.cleanup()`
(`tec.py`) has no local timeout guard of its own... added after the original
Session 57 audit, and didn't pick up the documented template despite the
doc's explicit instruction to use it for new modules." Found and verified
during a documentation/consistency audit of a concurrent session's work.

**Implementation.** `TecController.cleanup()` and the failed-initialize
rollback path in `TecController.initialize()` (`tec.py`) both now call the
shared `hw_logging.run_with_timeout()` utility -- the same one
`QmixPumpBackend`/`PiezoStage`/`Application` already share -- with a new
`cleanup_timeout_s: float = 5.0` field. A stuck `backend.close()` now raises
`TecError` naming the timeout instead of blocking the caller indefinitely; the
daemon thread itself may still be alive afterward (bounded caller behavior,
not a claim the vendor call was cancelled -- same caveat as every other
`run_with_timeout()` use in this codebase).

**Regression coverage:** `test_tec_controller_failed_initialize_bounds_a_stuck_backend_close`,
`test_tec_controller_cleanup_bounds_a_stuck_backend_close` (tests/test_tec.py)
-- both use a real hanging-`close()` fake backend and assert the call returns
within the configured timeout (`cleanup_timeout_s=0.02`) rather than blocking,
the same "prove the guard actually bounds a stuck call" pattern this
project's other timeout-guard tests use.

**Verification:** focused tests, 2/2 passed. `docs/known_open_items.md` was
already updated (by the same concurrent session) to mark this
"RESOLVED for the shared timeout mechanism... `TecController` share[s] one
implementation" -- confirmed accurate against the real diff.

**Not committed** -- pending review, per standing instruction. Originated
from a concurrent session; this entry documents and verifies it, not adopts
it on your behalf.

---

### Session 99 -- PiezoStage.connect() now stops polling before shutdown on post-poll failure

Same instrument-rollback theme as Sessions 96-98. Found and verified during a
documentation/consistency audit of a concurrent session's work.

**Confirmed failure shape.** `PiezoStage.connect()` calls
`channel.StartPolling()`, then reads `GetMaxTravel()`/`GetMaxOutputVoltage()`/
`GetMinOutputVoltage()`/`GetPositionControlMode()`. If any of those readback
calls failed after polling had already started, the rollback path only
attempted `device.ShutDown()` (best-effort, exceptions silently swallowed) --
polling was never explicitly stopped first.

**Implementation.** `connect()` now tracks `polling_started` and the live
`channel` reference. On any failure after `StartPolling()` succeeded, rollback
now calls `channel.StopPolling()` *before* `device.ShutDown()`, both routed
through the shared `_run_disconnect_step()` helper (same timeout-guarded,
error-collecting shape `disconnect()` already used). If either rollback step
fails, a combined `PiezoStageError` reports the original failure plus every
rollback error, chained from the original exception.

**Regression coverage:** `test_channel_initialize_failure_stops_polling_and_shuts_down`
(asserts both `StopPolling` and `ShutDown` were called, in that order, on a
`GetMaxTravel()` failure), `test_channel_initialize_failure_reports_cleanup_failure_too`
(asserts a simultaneous `StopPolling` failure is reported alongside the
original error) -- both in tests/test_thorlabs_piezo.py.

**Verification:** focused tests, 2/2 passed. No interaction found with any
other change in the current working tree.

**Not committed** -- pending review, per standing instruction. Originated
from a concurrent session; this entry documents and verifies it, not adopts
it on your behalf.

---

### Session 100 -- Application.flush() now rejects a non-positive flow rate before moving valve or pump -- CONFIRMED REGRESSION against pre-existing tests, not yet reconciled

Found and verified during a documentation/consistency audit of a concurrent
session's work. **Unlike Sessions 97-99, this one is NOT clean** -- flagging
that prominently rather than presenting it as ready.

**Implementation.** `Application.flush()` (`application.py`) now raises
`ValueError` if `settings.flush_flowrate <= 0`, before either the valve or
pump is touched -- alongside the pre-existing `flush_volume_ml > syringe_volume_ml`
capacity check, both inside the same `_report_step(progress, STEP_FLUSH)`
block, before any hardware call.

**Regression coverage (new, all passing):** `test_flush_rejects_nonpositive_flow_before_valve_or_pump_moves`
(parametrized `[0.0, -1.0, -5000.0]`), `test_flush_settings_timeout_is_zero_for_nonpositive_flowrate`
(tests/test_application.py) -- 4/4 passed in isolation.

**CONFIRMED REAL CONFLICT (not flakiness -- re-run in isolation, still fails
the same way):** the full suite run for this verification pass found 3
pre-existing, unmodified-in-this-diff failures, all in
tests/test_full_flow_dry_run.py:
`test_application_full_flow_dry_run_can_opt_into_fake_flush`,
`test_run_experiment2_step_sequence_with_flush_enabled`,
`test_run_experiment2_step_failure_in_flush`. Root cause: that file's shared
`make_recording_experiment()` helper
([tests/test_full_flow_dry_run.py:221](../tests/test_full_flow_dry_run.py:221))
constructs `FlushSettings(flush_flowrate=0.0, flush_volume_ml=0.0,
wait_after_flush_s=0.0)` as a "the exact numbers don't matter for this test"
placeholder, used by every test in that file exercising `flush_enabled=True`
-- the new guard now rejects that placeholder outright, before those tests
ever reach what they're actually trying to verify (step-sequence ordering,
failure attribution). This is a genuine, confirmed test-fixture conflict
between the new fix and pre-existing, untouched coverage, not something this
verification pass fixed -- `tests/test_full_flow_dry_run.py` was not
modified. Whoever adopts this fix will also need to give
`make_recording_experiment()` a real positive `flush_flowrate` default (or
override it per-test) before committing.

**Verification:** focused new tests, 4/4 passed. Full suite:
**520 passed, 1 skipped, 5 failed** -- 2 of the 5 (`test_v2_every_value_widget_has_a_tooltip_and_visible_marker`,
`test_v2_experiment_setup_tabs_have_inline_safety_caveats`, tests/test_qt_ui_v2.py)
are the pre-existing offscreen-Qt object-lifetime flakiness class
(`RuntimeError: ... QCheckBox ... already deleted`), confirmed passing in
isolation (2/2); the other 3 are the real, reproducible conflict described
above, confirmed still failing in isolation (not order-dependent flakiness).

**Not committed** -- pending review, per standing instruction, and per the
unresolved test conflict above, should not be committed as-is regardless.
Originated from a concurrent session; this entry documents and verifies it
(including the problem it currently has), not adopts it on your behalf.

---

### Session 101 -- v2 connection_button fixed: no longer derived from a transient status string

Real bug fix (found and independently verified during the v3 design
re-evaluation, Round 2), adopted here -- not a v3 preference, a confirmed
defect in v2's own existing behavior.

**Confirmed failure shape.** `MainWindowV2._refresh_status()`
(`qt_ui_v2.py`) computed `connected = self.app.status == "System
Initialized"`. `app.status` is a general status string overwritten by
every subsequent action -- a flush, a refill, an experiment run, Abort,
etc. -- so `connection_button` flipped to red "* Not Connected" after the
very first successful post-initialization action, even though hardware
remained fully connected. Verified directly against source
(`qt_ui_v2.py:1106`, pre-fix) before adopting the fix.

**Implementation.** `connection_button`'s "connected" state is now derived
from the same four per-device connection-status labels
(`ad2_connection_status`/`camera_connection_status`/`pump_connection_status`/
`valve_connection_status`) `_refresh_status()` already computes each call,
each independently sourced from live device attributes
(`_connected_text()`/`_valve_connection_text()`), not from `app.status`.
A device reporting "Disabled" no longer counts against the overall claim;
any enabled device reporting anything other than "Connected"/"Connected
(...)" does. At least one device must be enabled for the button to claim
"Connected" (an all-disabled session is not connected). Reordered the
method so the per-device labels are computed before the button reads them,
rather than the previous side-by-side, independently-derived structure.

**Regression coverage:** extended
`test_v2_initialization_progress_uses_existing_instrument_order`
(tests/test_qt_ui_v2.py) -- after a full simulated initialize confirms
`connection_button.text() == "* Connected"`, directly overwrites
`window.app.status = "FlushComplete"` (same "simulate a later action via
direct status overwrite" pattern already established for the analogous
`experiment_running_status` fix, Category 2/Session 39) and confirms the
button still reads "* Connected" with the green stylesheet, rather than
flipping to red.

**Verification:** full `tests/test_qt_ui_v2.py`, 35/35 passed.

**Not committed** -- pending review, per standing instruction.

---

### Session 102 -- v3 design-idea adoption, Proposals 2-7: label/grouping clarity fixes, shared v1+v2

Six low-risk, label-or-grouping-only adoptions from the v3 round-2
evaluation, none touching widget sharing/mutation. Each verified real
(non-offscreen) at 1440x900 and against the full test suite.

- **Proposal 2 -- "Error Out" -> "Status and error history"** (`qt_ui.py`'s
  `_error_panel()`, `qt_ui_v2.py`'s row label). Session 58 replaced the
  single-value display with `HistoryLogWidget`, but the caption was never
  updated to match.
- **Proposal 3 -- "(unavailable)" captions for Elapsed Time / Time Left**
  (both files). These are confirmed-dead placeholders
  (`_stale_static_display()`, Session 39 Category 4) -- the value widgets
  were already disabled+tooltipped; the caption itself said nothing.
- **Proposal 4 -- DIO1-clarifying captions** for Camera FPS ("drives DIO1
  LED clock"), Camera Start (s) ("DIO1 pulse delay"), Dynamic Camera Start
  Time and Camera Start Array(s) ("per-repeat DIO1 delays") -- matching the
  real relationship these fields' own existing tooltips already explain,
  in both `qt_ui.py`'s Experiment tab and `qt_ui_v2.py`'s
  `_v2_acquisition_group()`.
- **Proposal 5 -- Initialize dialog reorganized into Connections /
  Reference paths / Retained fields tabs.** New shared module-level
  `_hardware_reference_tabs(window, mark_unwired_stub)` in `qt_ui.py`
  (matching `_widen_for_content()`'s own established shared-helper
  convention), called from both `qt_ui.py`'s `_instrument_group()`
  (Enable checkboxes now split into their own leading form, resource/path
  fields moved into the new tabbed widget below) and `qt_ui_v2.py`'s
  `InitializationDialog._hardware_details_group()`. **Real ordering bug
  found and fixed during implementation:** `_add_tooltip_icons(form)` must
  run *after* the form's layout is installed on a parent widget, not
  before -- every other call site in this codebase uses the
  `QFormLayout(parent)` constructor form (immediate installation); the new
  code's `QFormLayout()` + later `outer.addLayout(form)` two-step
  construction silently produced un-wrapped tooltip icons until the order
  was corrected, caught by
  `test_every_value_widget_has_a_tooltip_and_visible_marker`.
- **Proposal 6 -- Camera tab: capture_mode/sequence_exposure_ms isolated**
  into a new `_camera_retained_fields_group()` ("Retained (not used by
  runtime)"), removed from Sequence Settings' own form where they
  previously sat inline (each individually "(unused)"-suffixed) among
  genuinely live, automated-run-affecting fields. `qt_ui_v2.py` needs no
  change (Camera manual panel maps directly to the shared `_camera_tab`).
  Updated `test_camera_sequence_group_flags_live_automated_use_and_dead_capture_mode`
  to check the new group instead of row indices inside the now-shorter
  settings form.
- **Proposal 7 -- selective clearer button text** (Pump&Valve tab only,
  the four genuinely ambiguous ones): "Refill"->"Refill syringe",
  "Empty"->"Empty syringe", "GO"->"Move to target fill level",
  "STOP"->"Stop pump". Left Configure/Generate/Ref Move/Flush alone
  (already reasonably self-explanatory).

**CONFIRMED SIDE EFFECT ON qt_ui_v3.py -- not fixed, per explicit
instruction not to modify that file.** `qt_ui_v3.py` was not touched, but
Proposals 2-4's renames break its construction: `_v3_runtime_column()` ->
`_global_status_panel()` calls the module-level `_rename_unique_text_widget(group,
QLabel, "Error Out", ...)`, which raises `RuntimeError` when it can't find
exactly one match -- by design (its own docstring: "fail visibly if the v2
contract drifts"). Since "Error Out" no longer exists anywhere (renamed to
"Status and error history"), `MainWindowV3.__init__()` now raises
immediately, before ever reaching its other renames
(`_v2_status_progress_group()`'s Elapsed Time/Time Left,
`_v2_acquisition_group()`'s Camera FPS/Camera Start (s)/Dynamic Camera Start
Time/Camera Start Array(s)) -- those would fail the same way if this one
were resolved first. Confirmed via the full test suite: all 14
`tests/test_qt_ui_v3.py` failures trace to this single root cause (`grep`
across the failure tracebacks found exactly one distinct `RuntimeError`
message). Proposals 5/6/7 do NOT affect v3 -- confirmed its
`_pump_tab()`/`_hardware_details_group()`/Camera-tab methods are full,
independent rebuilds that never call `super()` or do `_rename_unique_*`
lookups against the fields those three proposals touched. This is v3's own
maintenance responsibility (its authors chose fail-loud contract-checking
deliberately), not a v1/v2 defect -- see `docs/known_open_items.md` for the
full boundary writeup.

**Verification:** real (non-offscreen) render at 1440x900 for v1's
Initialization/Camera/Pump&Valve tabs and v2's Initialize dialog + full
window -- all clean, no clipping, no layout breakage. Full suite: **507
passed, 1 skipped, 18 failed** -- 3 are the pre-existing Session 100 flush
regression (unrelated, already flagged as blocked), 14 are the confirmed
v3 breakage above (expected, not a v1/v2 defect), 1
(`test_v2_experiment_setup_tabs_has_four_task_oriented_tabs`) is the
pre-existing offscreen-Qt object-lifetime flakiness class, confirmed
passing 4/4 on isolated re-run. **Effective: 511 passed (507 + this
session's own genuinely-clean re-runs), 1 skipped, 3 pre-existing blocked
(Session 100), 14 expected v3 contract breaks.**

**Not committed** -- pending review, per standing instruction.

---

### Session 103 -- v3 compatibility fix following v1/v2 caption renames (not a v3 feature change)

Narrow, explicitly-scoped fix: updates only the specific string literals
`qt_ui_v3.py` matches against v1/v2's captions, so `MainWindowV3`
constructs successfully again after Session 102's renames. No layout,
structure, or behavior change; no other v3-evaluation finding (e.g. the
shared-widget-mutation pattern documented in `known_open_items.md`)
adopted here. `qt_ui.py`/`qt_ui_v2.py` not touched -- confirmed via file
mtimes both predate this session's only edit (`qt_ui_v3.py`).

**Re-verified root cause (Step 1) before fixing, not assumed from the
prior report.** Ran the full `tests/test_qt_ui_v3.py` file fresh: all 14
failures traced to the exact same single `RuntimeError` message ("V3
expected exactly one QLabel captioned 'Error Out'; found 0"), confirmed
by grepping every failure's traceback -- `_v3_runtime_column()` (the
first thing `_build_layout()` builds) reaches `_global_status_panel()`'s
now-stale "Error Out" lookup before any of Proposals 3/4's other renames
are ever attempted, so those remained latent (not yet individually
surfaced) rather than independently confirmed broken. Fixed all of them
in this pass regardless, not just the one visibly failing.

**Seven `_rename_unique_text_widget()`/`_rename_unique_group()` calls
updated** (`qt_ui_v3.py`), each changing only the `old_text` search key to
match Session 102's new v1/v2 caption, `new_text` (v3's own preferred
wording) left unchanged in every case except one:
- `_global_status_panel()`: `"Error Out"` -> `"Status and error
  history"`. v3's own preferred wording is now identical to v1/v2's new
  caption -- kept as a same-text rename (not removed) to preserve both
  the fail-loud uniqueness check and the stable `objectName` assignment.
- `_v2_status_progress_group()`: `"Elapsed Time"` ->
  `"Elapsed Time (unavailable)"`, `"Time Left"` ->
  `"Time Left (unavailable)"`.
- `_v2_acquisition_group()`: `"Camera FPS"` ->
  `"Camera FPS (drives DIO1 LED clock)"`, `"Camera Start (s)"` ->
  `"Camera Start (s) (DIO1 pulse delay)"`, `"Dynamic Camera Start Time"`
  -> `"Dynamic Camera Start Time (per-repeat DIO1 delays)"`, and the
  `_rename_unique_group()` call for `"Camera Start Array(s)"` ->
  `"Camera Start Array(s) (per-repeat DIO1 delays)"`.
- `"Repeats"`/`"Frames"`/`"GlobalExposure"`/`"Average FPS"` were not
  touched by Session 102, so those existing rename calls were left as-is.

**Verification:** `tests/test_qt_ui_v3.py` -- all 15 passed, confirmed
stable across 3 consecutive full-file re-runs (no flakiness masking a
partial fix). Full project suite: 519 passed, 1 skipped, 6 failed -- 3
are the pre-existing, already-flagged, still-blocked Session 100 flush
regression (unrelated), 3 are the pre-existing offscreen-Qt
`SystemError`/object-lifetime flakiness class, confirmed passing 3/3 in
isolation. **Effective: 522 passed, 1 skipped, 3 pre-existing blocked
(Session 100), 0 v3 failures** -- the 14 confirmed in Session 102 are
fully resolved.

**Not committed** -- pending review, per standing instruction.

---

### Session 104 -- Manual, explicit pump fault-clear escape hatch (a deliberate, scoped exception to fail-closed initialization, NOT a reversal of it)

**Framing, stated up front because it matters more than the diff:** every
other session touching the pump's CAN-bus fault (Sessions 96-99) has
treated `QmixPumpBackend._enable_pump()`'s refusal to auto-clear a fault as
correct and load-bearing -- and it still is. `initialize()` itself is
**not touched by this session at all**; its fail-closed behavior is
unchanged (re-confirmed by re-running
`test_qmix_initialization_refuses_existing_fault_without_clearing_or_enabling`
fresh, still green, still asserting `("clear_fault",) not in pump.calls`).
What's new is a second, deliberately separate path that only an operator
can reach by clicking a distinctly-styled button and clicking through a
non-skippable warning -- an acknowledged, human-authorized bypass for a
real, still-unresolved hardware condition (the pump's CAN Tx Queue
Overrun / 0x81FF fault, confirmed in Session 99 to relatch on fresh bus
connections even with QmixElements fully closed -- see
`docs/hardware_repair_plan.md`), not a claim that the fault is fixed or
that auto-clearing is now safe anywhere else.

**`QmixPumpBackend.clear_fault_and_reinitialize(configuration_path)`**
([qmix_backend.py](src/thermo_acoustic/qmix_backend.py)) -- deliberately
NOT refactored out of `initialize()` into a shared helper: the two methods'
bodies are near-identical by design (open bus, look up pump, start bus,
[fault-check], `_enable_pump()`, configure flow/volume units, cache
max_flow_rate/max_volume), duplicated rather than shared so `initialize()`
itself never has to change to support this and stays trivially auditable
for zero behavioral drift. The one real difference: right before
`_enable_pump()`, this new method checks `is_in_fault_state()` and calls
`clear_fault()` if needed. `_enable_pump()` itself is reused completely
unchanged as the final gate -- if the fault immediately relatches (the
real observed behavior), it correctly raises `QmixPumpError` again, same
as `initialize()` would. Rollback on any failure fully tears down
`bus`/`pump` back to `None` via `close()`, same as `initialize()`'s own
rollback.

**`CetoniPump.clear_fault_and_reinitialize()`**
([instruments.py](src/thermo_acoustic/instruments.py)) -- thin wrapper
mirroring `initialize()`'s own backend-open/rollback structure. Not added
to the `PumpBackend` Protocol (would force every backend/test fake to
implement it); instead uses the same `getattr(self.backend,
"clear_fault_and_reinitialize", None)` duck-typing convention
`_enable_pump()` already established for `read_last_error`. No-op when
`enabled=False`; falls back to a plain `initialize()` when simulated
(`backend=None`, no real fault state to clear); raises `RuntimeError` if
the configured backend doesn't support it at all.

**`Application.clear_pump_fault_and_retry()`**
([application.py](src/thermo_acoustic/application.py)) -- the only place
in the whole codebase that calls the above. Reachable independently of
the normal `initialize()` flow (device order AD2->Camera->Pump->Valve->
Z-stage->TEC stops at the first failure, so a faulted pump blocks
`initialize()` from ever reaching later devices) -- calls
`self.pump.clear_fault_and_reinitialize()` directly against the live
`self.pump` instance. Records the action both ways the task required:
`fire_status_event("Clearing Pump Fault (manual operator action)")` /
`fire_status_event("PumpFaultClearedAndReconnected (manual operator
action)")` (or `"PumpFaultClearFailed: {exc}"` on failure) in the live
status/history log, and sets the new
`pump_fault_manually_cleared_this_session` field (a plain session-scoped
bool, not persisted to `settings.json` -- a fresh process starts `False`
again, matching that the underlying condition is live hardware state, not
a saved preference).

**`Experiment2.pump_fault_manually_cleared`**
([workflows.py](src/thermo_acoustic/workflows.py)) -- new `data.tdms`
property (`"PumpFaultManuallyCleared"`), same pattern as the existing
`sim_*`/`*_enabled` flags: `Application.run_experiment2()` copies
`pump_fault_manually_cleared_this_session` onto the experiment right
alongside them ([application.py](src/thermo_acoustic/application.py)), so
a run whose pump fault was manually cleared earlier in the session stays
traceable in saved data, not just in the live (unpersisted) log.

**UI: "Pump Fault Recovery (advanced)" group,
`qt_ui.py`'s `_pump_tab()`** -- its own group box, its own column, in the
"Static configuration" row (not folded into "Setup" or anywhere near the
routine operational controls), with a dark-red bold "Clear Fault && Retry
Connection" button (real-render-confirmed to display as a single literal
`&`, not a mnemonic underline -- Qt's `&&`-escaping convention).
`qt_ui_v2.py` inherits `_pump_tab()` unchanged from `MainWindow`, so it
gets this for free; `qt_ui_v3.py` was not touched, per the task's explicit
instruction. Clicking it calls the new `_start_clear_pump_fault()`, which
shows a `QMessageBox.question()` (default button No, same non-skippable
pattern as this file's existing Z-scan/reference-move confirmations)
naming the real fault code, stating plainly that clearing lets the pump
be used now but does **not** fix the underlying cause and the fault may
return, pointing at `docs/hardware_repair_plan.md`, and stating the action
will be recorded -- only on an explicit Yes does it call
`Application.clear_pump_fault_and_retry()` via `_run_action()`.

**Real-render verification** (`QT_QPA_PLATFORM` unset, confirmed
`platformName() == "windows"`, same method as Session 41's tooltip-wrap
fix): screenshotted the Pump&Valve tab (fault-recovery group visually
separated from Setup/Syringe, no layout squeeze), the group box in
isolation, and the real `QMessageBox.question()` dialog triggered by an
actual button click (captured its real title/text, then answered No to
close it without touching any real hardware or app state) -- all three
confirmed correct by inspection.

**Tests** (`tests/test_application.py`, `tests/test_qt_ui_hardware_settings.py`,
12 new, all passing): `clear_fault_and_reinitialize()` actually clears a
fault and a subsequent bare `initialize()` then succeeds;
`clear_fault_and_reinitialize()` still fails closed if the fault
relatches (does not silently succeed); `CetoniPump` wrapper delegates,
no-ops when disabled, falls back correctly when simulated, raises when
unsupported; `Application.clear_pump_fault_and_retry()` records both
status events and the session flag on success, records a failure event
and leaves the flag `False` on failure; `run_experiment2()` carries the
flag into the real final `data.tdms` properties; the UI button shows the
warning and does not proceed without it (`QMessageBox.question()` stubbed
to return No -> `_run_action` never called), proceeds only after an
explicit Yes (and the queued action really does call
`clear_fault_and_reinitialize()`, not a bare `initialize()` that would
silently skip the clear step); and `_start_initialize()`'s normal path
never reaches `clear_pump_fault_and_retry()` or touches the session flag,
even when actually exercised.

**Full suite:** 534 passed, 4 failed, stable across 2 consecutive runs.
Of the 4: 3 are the pre-existing, already-flagged, still-blocked Session
100 flush-flowrate-guard regression (unrelated, explicitly out of scope
for this task). The 4th
(`test_run_experiment2_skips_disabled_camera_steps_without_touching_backend`)
is a real, environment-level failure unrelated to this session's code --
its own default `Application(ad2=AD2Sdk())` tries to open the real AD2
device and got `"FDwfDeviceOpen failed: Devices are busy, used by other
applications"`; the test file's relevant lines are byte-identical to
`HEAD` (confirmed via `git show HEAD:...`), and no file this session
touched (`qmix_backend.py`, `instruments.py`, `application.py`,
`workflows.py`, `qt_ui.py`) has any AD2/`waveforms.py` involvement.
Reproduced consistently (2/2) while some other process was apparently
holding the real AD2 device open -- worth the user's attention as a
possible sign something else is actively using the AD2 right now, but not
a code regression from this task. **Effective: 534 passed, 0 new
regressions.**

**Not committed** -- pending review, per standing instruction.

---

## Known remaining open items as of this writing

**This section predates [docs/known_open_items.md](known_open_items.md)
(compiled 2026-07-28) and has known staleness -- confirmed via a
dedicated cross-reference pass (Session 58) that several bullets below
say "open"/"not fixed" for items later sessions actually resolved (two
specific corrections are inlined below where found). `known_open_items.md`
is the actively-maintained, current source of truth going forward; this
section is kept as historical narrative, not re-synced line-by-line on
every session (that duplication is exactly what caused the staleness in
the first place).**

**Resolved since the previous version of this list** (kept out of the list below, not repeated): SeriesPath overwrite protection, syringe-volume-vs-flush-capacity mismatch, camera trigger source left undefined, Qmix fill-level unit ambiguity, valve ready-check only at init (not reused during flush), the `"BD 5ml"` inner-diameter value, the experiment-path exposure time never reaching real DCAM hardware (Session 20), TDMS write verification (Session 26), the WFG-tab live-use labeling (Session 29, proposed 3 days prior to that session, previously only done for Camera), the WFG tab's Sweep "Center Frequency" unit (Session 16's MHz choice corrected to kHz in Session 29, alongside every other Carrier/FM-Mod/Sweep frequency field on both tabs), the settings.json Hz->kHz silent-misload gap Session 29 itself flagged as unfixed (Session 30: versioned `schema_version` key + one-time auto-convert + load-time warning), Abort not stopping a running experiment series (Session 31 found it on real hardware, Session 32 fixed it, Session 33 hardware-reconfirmed the fix), `FlushSettings.timeout_s`'s missing minutes-to-seconds conversion (Session 31/32, hardware-reconfirmed Session 33 with the exact originally-failing parameters), and the real Qmix pump being unable to connect via `qt_ui.py`'s Initialize button on a clean environment because `QMIXSDK` was never set (Session 31/32, hardware-reconfirmed Session 33 with `QMIXSDK` genuinely unset beforehand).

- **Valve status-query handshake (`"S"` command)** was originally protocol-derived and unverified (Session 2), but later real-hardware GUI verification reported `status_note="confirmed"` (Session 31). Remaining caution: current code still treats some non-empty but unrecognized status responses as connected-with-note rather than a hard initialization failure, so inspect `Valve._apply_status_response()` before relying on the handshake as a strict device-identity proof. **[Stale, corrected Session 58]:** the "reject unrecognized status responses" hardening this bullet describes as still-open was investigated and left "uncommitted, pending a decision" in an earlier version of this changelog -- it has since been committed (`8149bc1`), confirmed via `git log --all -- instruments.py`; see `known_open_items.md`.
- **DCAM frame timestamp clock domain** is unverified -- real per-frame values are now captured and used when the camera/driver reports support, but which clock (camera-internal vs. host-driver) produced them, and what epoch `sec` is measured from, has not been confirmed against real hardware or official SDK documentation. (Session 8.)
- **Pump flow-rate sign convention** is no longer completely unknown: current UI labeling records `-=aspirate, +=dispense`, and no sign-inversion logic exists anywhere in `CetoniPump`/`Application.flush()`/the UI. Remaining caution: review the live tooltip text before using it as operator guidance, because an independent audit found at least one tooltip still carried older "unverifiable" wording after the label was corrected.
- **`src/thermo_acoustic/ui.py`** (592 lines, a separate unused Tkinter `MainWindow`) remains in the repo, confirmed unreachable from any launcher, flagged for a removal decision but not removed. (Session 7.)
- **`qt_ui_v2.py`/`MainWindowV2`** remains explicitly *not* the default launch target (see Session 4) pending hardware verification and user approval, despite having working sidebar panels, valve handshake, and Init dialog fixes.
- **Camera trigger source is now deterministic but not necessarily correct**: hardcoded to `"Internal"` (Session 13) purely to remove undefined leftover-state risk. Whether the real experiment should instead use `"External"` (paced by the AD2 DIO pulse train) has not been resolved -- **Session 19 traced the real LabVIEW call path (`RunExperiment2.vi` -> `CreateExperiments.vi` -> `Experiment2_Init.vi` -> `ConfigureSequence.vi` -> `tm_inputtriggersource_40.vi`) and confirmed the actual wired value is not recoverable from the exported VI diagrams** (compiled block-diagram wiring, not text); the front-panel screenshot's "Internal" is explicitly not used as a substitute. Still needs oscilloscope verification against real hardware -- unchanged in practice, now backed by a real (negative) investigation instead of screenshot inference. **Session 31 added real supporting evidence** (not a resolution): real per-frame `dcam_clock:` timestamp deltas from an actual hardware run were ~0.0316s apart, matching the camera's own readout time, not the configured DO-clock frame period (0.2s at 5 fps) -- consistent with `"Internal"` free-running the camera at its own rate rather than being paced by the DO clock at all. Deliberately not acted on (needs oscilloscope verification, not fixable from software alone).
- **DCAM exposure vs. readout timing validation -- fixed (Session 19).** `Application._check_camera_timing_budget()` now queries the real `read_readout_time()` and rejects (`ValueError`, before `start_capture()`) any configured Camera FPS that the current exposure+ROI readout time cannot sustain. (Originally flagged in Session 12.) The exposure value it checks against is now guaranteed to be the one actually applied to hardware -- see the next item.
- **Experiment-path exposure time not reaching real DCAM hardware -- fixed (Session 20).** `run_experiment2()` previously called `self.camera.configure(exposure_ms=...)`, a Python-side bookkeeping setter that never wrote `DCAM_IDPROP.EXPOSURETIME` to the real camera (only the manual Camera tab's `configure_exposure_time()` did that). Now calls `configure_exposure_time()` directly, the same real hardware-writing call the manual tab already used -- same bug class, and same fix pattern, as Session 13's camera-trigger-source fix.
- **WFG amplitude/frequency bounds checking remains absent** beyond the generic `-1e12..1e12` spin-box range -- no physically-meaningful ceiling (e.g. AD2 hardware output limits) is enforced. (Flagged in Session 9, not fixed.) **[Stale, corrected Session 58]:** fixed since Session 51 (commit `23e17d5`) -- `waveforms.py`'s `configure_wfg()`/`_configure_analog_node()` now reads the device's own live `AnalogOutNode*Info()` range and clamps before every `Set` call, setting `WfgChannelConfig.out_of_range` (surfaced in the UI status line and TDMS metadata), verified against a real Analog Discovery 2; see `known_open_items.md`.
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

### Session 105 -- File/structure audit cleanup (repository hygiene, no functional change)

Executes the six approved findings from an earlier read-only file/asset
audit (`main_html/`, `UI_tabs/` images, `qmix_sdk_for_codex/`, `dcamsdk4/`,
and `labview_manifest.json` were explicitly out of scope and untouched
throughout, per that audit's own protected-evidence classification; so was
`qt_ui_v3.py`). Five implementation items, none of them a behavior change
to any hardware backend, workflow, or UI logic:

1. **`gui_log.txt` removed from tracking.** A single-line, zero-citation
   stray Qt `DLL_PROCESS_DETACH` trace, tracked since one commit
   (`3474232`) and never referenced anywhere in `src/`, `tools/`, or
   `docs/`. `git rm`'d outright, not left untracked.
2. **Real-hardware run artifacts relocated into a new top-level `runs/`.**
   `hardware_tests/output/enabled_gating_verification/` (122 MB, 16 files,
   content/structure unchanged) and the loose root-level `data.tdms` both
   moved (plain `mv`, not `git mv` -- both were already gitignored/
   untracked, so there was no history to preserve) into `runs/`.
   `.gitignore` gained a new `runs/` rule alongside the existing
   `hardware_tests/output/` one (kept, not removed, in case anything still
   writes there; its comment now notes it's superseded).
   `docs/legacy_asset_index.md`'s "HISTORICAL / DIAGNOSTIC EVIDENCE" row
   updated to name `runs/` as the current location. Historical
   `hardware_tests/output/` mentions inside this changelog's own past
   session entries were deliberately left unedited -- they describe where
   artifacts were written *at the time*, consistent with this file's own
   stated methodology of not rewriting history.
3. **Two confusingly-named `tools/` scripts renamed:**
   `tools/test_hamamatsu_camera.py` -> `tools/legacy_hamamatsu_camera_probe.py`,
   `tools/test_qmix_pump.py` -> `tools/legacy_qmix_pump_probe.py` (both via
   `git mv`, history preserved). These two were legacy, action-capable,
   confirmation-gate-free diagnostics that happened to share the
   `test_*.py` naming convention with `hardware_tests/`'s own *gated*
   scripts -- `hardware_tests/README.md` previously had to spend a
   dedicated paragraph explaining the two were unrelated; that paragraph
   is now shorter since the naming collision itself is gone. Every live
   reference to the old names was found and updated: `docs/HANDOVER.md`,
   `docs/known_open_items.md`, `docs/legacy_unresolved_items.md`,
   `tools/generate_port_registry.py` (source, so the regenerated
   `docs/PORTING_TBD.md` picks it up too), and
   `tests/test_piezo_zscan.py::test_legacy_action_capable_tools_are_explicitly_manual_only`.
4. **`port_status.json` regenerated fresh** against the current
   `src/thermo_acoustic/labview_ports.py` via
   `tools/generate_port_registry.py`. Result: **zero drift** --
   `port_status.json` and `src/thermo_acoustic/labview_ports.py` came out
   byte-identical to their committed `ac355b9` versions, despite ~10
   commits of real hardware work since. `docs/PORTING_TBD.md` (the
   generator's other output) did change on regeneration, but not from real
   data drift -- the generator's own template has never produced the
   hand-authored safety-caveat framing (the `>` blockquote intro,
   "Generator-labelled" wording) that two later commits (`17f24dd`,
   `7c7e19f`) added directly to the file by hand. Regenerating would have
   silently dropped that caveat text; it was restored on top of the fresh
   body instead, so the final diff against the committed version is only
   the two real, correct changes (`tools/legacy_hamamatsu_camera_probe.py`
   rename; a `main_html/main` -> `main_html/main.html` typo fix) -- a
   pre-existing gap between the generator script and this hand-edited doc,
   not something this session introduced, and not fixed here (out of
   scope for this pass).
5. **`docs/labview_ui_field_reference.md` created**, transcribing all five
   `UI_tabs/*.png` LabVIEW front-panel screenshots (Initialization, WFG,
   Pump&Valve, Camera, Experiment) into field-label/default-value tables,
   with every checkable field cross-referenced against its current
   `qt_ui.py` default and explicitly flagged where they diverge. PNGs
   themselves untouched. Confirmed drift: valve `COM6`->`COM5` (already
   known); Z-stage Prior/`COM7`->Thorlabs PPC001/Kinesis (whole hardware
   target replaced, not a stale port); Cetoni config path (generic
   QmixElements folder -> the real one-pump project path); Image
   Continuous default `On`->`Off`; the already-documented removal of the
   static "476 is Vertical is max for 100 fps" hint (Session 36). One
   apparent drift resolved rather than left open: the Camera tab's ROI
   vertical offset/size and exposure (`900`/`500`/`50ms` in the screenshot
   vs. `792`/`740`/`40ms` live) traces via `git log -S` to a deliberate,
   already-git-recorded supersession in `17f24dd` -- the screenshot's raw
   default was intentionally replaced by a separately real-hardware-tested
   "LabVIEW camera preset" (`docs/current_workflow_audit.md`), not
   unexplained rot. The WFG tab's individual numeric spin-box defaults
   were transcribed but not exhaustively cross-checked against `qt_ui.py`
   field-by-field (flagged as future follow-up work inside the doc itself,
   not silently left implying they were verified).

**Full suite:** 537 passed, 4 failed -- the same 4 pre-existing failures
this changelog already tracked as of Session 104 ("534 passed, 4 failed,
stable across 2 consecutive runs"; the 3-test increase is from unrelated
new test files already present in the working tree, `docs/HANDOVER.md`
etc. not affected). All 4 are `application.py`'s flush-flowrate validation
rejecting `flush_flowrate=0.0` in pre-existing fake-driven tests -- nothing
in any failure traceback touches `tools/`, `runs/`, `gui_log.txt`, or
`port_status.json`. Zero regressions from any of the five items above.

**Files touched:** `.gitignore`, `gui_log.txt` (removed),
`docs/legacy_asset_index.md`, `docs/HANDOVER.md`, `docs/known_open_items.md`,
`docs/legacy_unresolved_items.md`, `docs/PORTING_TBD.md`, `port_status.json`
(regenerated, byte-identical), `src/thermo_acoustic/labview_ports.py`
(regenerated, byte-identical), `tools/generate_port_registry.py`,
`tools/legacy_hamamatsu_camera_probe.py` (renamed from
`tools/test_hamamatsu_camera.py`), `tools/legacy_qmix_pump_probe.py`
(renamed from `tools/test_qmix_pump.py`), `hardware_tests/README.md`,
`tests/test_piezo_zscan.py`, `docs/labview_ui_field_reference.md` (new),
plus the relocation of `hardware_tests/output/enabled_gating_verification/`
and `data.tdms` into the new `runs/`. Nothing committed -- pending review.

### Session 106 -- ARCHITECTURE CHANGE: Application.initialize() no longer aborts on the first device failure or rolls back devices that already succeeded

**This session changes what a failed device does to the other five during
Initialize Hardware. Read this entry before relying on that flow's
behavior.** Previous behavior: `Application.initialize()` processed
devices in a fixed AD2 -> Camera -> Pump -> Valve -> Z-stage -> TEC order
and, the instant any one device's `initialize()` raised, called
`_cleanup_instruments()` on every device that had already succeeded (real
teardown -- `AD2Sdk.cleanup()`/`HamamatsuCamera.cleanup()`/etc., genuinely
closing handles), then re-raised, skipping every device after the failing
one entirely. Concretely: a pump fault (AD2/Camera succeed before Pump in
the order) tore AD2 and Camera back down, and Valve/Z-stage/TEC (after
Pump) never even attempted a connection. **New behavior: every device
gets its own independent `initialize()` attempt regardless of what
happened to any other device. A device that succeeds stays connected. A
device that fails is simply reported as failed and the loop moves on to
the next device. `initialize()` still raises at the end if one or more
devices failed (same external contract callers already relied on), but
only after every device had its chance, and the exception now names every
device that failed, not just the first.**

**Step 1 -- investigation, before changing anything (as required).**
Searched `docs/known_open_items.md`, `docs/hardware_repair_plan.md`, and
this changelog for any documented rationale for the cross-device rollback
specifically (as opposed to a device's own partial-init cleanup). Found
none. Every rollback-related entry in this project's history (Sessions
96-99, and `known_open_items.md`'s "device whose own `initialize()` call
fails is not part of the rollback list" passage) is about a *different*,
narrower concern: a single device cleaning up its *own* partial connection
state after its *own* `initialize()` fails partway through (Valve closing
a just-opened serial port after a failed handshake; `CetoniPump` closing
its backend after a failed post-open fill-level readback; `PiezoStage`
stopping polling before shutdown after a failed post-connect readback).
Nothing anywhere argues Device B depends on Device A's success. This reads
as the incidental behavior of a simple sequential `try`/`except` loop, not
a deliberate safety design.

**Step 2 -- confirmed genuine independence, not assumed.** Inspected every
one of the six devices' `initialize()` methods
(`instruments.py`/`tec.py`): `AD2Sdk.initialize()`, `HamamatsuCamera.
initialize()`, `CetoniPump.initialize()`, `Valve.initialize()`, `ZStage.
initialize()`, `TecController.initialize()` -- none takes another
instrument as a parameter, and none reads `self.app` or a sibling
instrument's state. Each is fully self-contained, touching only its own
dataclass fields and its own backend. The AD2 -> Camera -> Pump -> Valve ->
Z-stage -> TEC order is confirmed to be an arbitrary reporting sequence,
not a dependency chain.

**Fix.** `Application.initialize()` ([application.py](src/thermo_acoustic/application.py))
rewritten: the per-device loop no longer breaks or rolls back on the first
exception -- it collects `(display_name, exc)` per failure and `continue`s
to the next device. After the loop, if any failures were collected, fires
`"System Partially Initialized (N/6 succeeded; failed: ...)"` and raises
one `RuntimeError` whose message names every failed device (`"; "`-joined,
same style the old code already used to combine a primary error with
rollback errors), chained `from` the first failure for traceback context.
`self.fire_status_event("System Initialized")` still only fires when every
device succeeds. `_cleanup_instruments()` itself is untouched and still
used by `Application.cleanup()` -- only its cross-device call from inside
`initialize()`'s except-branch was removed. Neither UI caller
(`qt_ui.py`/`qt_ui_v2.py`'s `_initialize_system()`) needed a change: both
already call `self.app.cleanup()` unconditionally before every Initialize
attempt, so a retry already tears down anything left from a prior partial
attempt regardless of whether `initialize()` itself does cross-device
rollback -- removing it introduces no leak risk on retry.

**Per-device UI reporting confirmed correct, not merely assumed.** The
`progress("init_device", (display_name, status))` stream v1 emits but
never consumes (`qt_ui.py`'s `_handle_worker_progress()` has no
`"init_device"` case at all -- dead for v1) is consumed only by v2's
`InitializationDialog.set_device_status()`
([qt_ui_v2.py](src/thermo_acoustic/qt_ui_v2.py)), a direct
`(device_name, status)` -> label-text pass-through with no special-casing
removed or needed. The old "Rolled back (X init failed)" progress text
naturally stops being emitted (nothing is rolled back anymore); succeeded
devices now correctly keep reporting their own genuine "Complete", failed
ones "Failed" -- more accurate than before, since v2's own
`ad2_connection_status`/`pump_connection_status`/etc. labels already read
live instrument state (`self.app.ad2.device_handle`, `self.app.pump.
initialized`, ...) directly, not a cached "did the whole `initialize()`
succeed" flag -- they were already capable of showing "Connected" for a
device the old code had artificially disconnected via rollback; now they
agree with the dialog instead of contradicting it, without needing any of
their own logic to change.

**Valve given the same lazy-reconnect fallback AD2/Camera already had.**
`AD2Sdk.config_wfg()`/`pc_trigger()` and `HamamatsuDcamBackend.
configure_exposure_time()`/etc. already lazily reopen (`open_and_use_
first_device()`/`open_camera()`) whenever their handle is `None` and the
device is enabled -- confirmed by reading both, not assumed -- which is
exactly the state a rolled-back-or-never-attempted device is left in. This
made AD2/Camera silently self-heal on the next manual-tab action even
under the old buggy `initialize()`, masking how bad the old coupling
really was; Valve had no equivalent and would raise a real `"Serial port
is not open"` `RuntimeError` from `set_position()` if it was ever skipped.
New `Valve._ensure_connected()` ([instruments.py](src/thermo_acoustic/instruments.py)):
if `self.backend is not None and not self.initialized`, calls
`self.initialize()` -- not a shortcut "just open the port" duplicate, the
real `initialize()` itself, so the "S" status handshake/validation always
runs before a position command is trusted. Called from `set_position()`
before every position write. Z-stage was checked and found to already have
no gap: the manual Z-Scan tab's own action handlers call `piezo.connect()`/
`piezo.disconnect()` directly, per action, entirely independent of
`Application.initialize()` -- it never depended on the main Initialize
flow succeeding in the first place. TEC was checked and its real-use
methods (`read_status()`/`apply_static_setpoint()`) likely have the same
gap as old Valve (`_backend()` only lazily constructs the backend object,
never calls `connect()`) -- **not fixed here**, deliberately: TEC
real-hardware operation is a separately-unresolved boundary
(`docs/tec_verification_matrix.md`), and bundling an untested TEC
connection-semantics change into this architecture fix would conflate two
different reviews. Flagged as a follow-up, not silently patched.

**Docs updated to match** (both live/maintained docs, not the historical
changelog narrative style): `docs/hardware_repair_plan.md`'s
"Initialization And Failure Recovery" section and its Qmix-CAN-fault
"Confirmed" bullet; `docs/known_open_items.md`'s rollback-list bullet;
`qt_ui_v2.py`'s own stale "Rolled back (...)" example in a column-width
comment.

**Tests** (`tests/test_full_flow_dry_run.py`, `tests/test_application.py`,
`tests/test_qt_ui_v2.py`): `test_initialize_rolls_back_already_initialized_
devices_when_later_device_fails` (the old regression test asserting the
now-removed behavior) rewritten as `test_initialize_lets_every_device_
attempt_independently_when_one_fails` -- Valve failing no longer stops
Z-stage from attempting, and produces zero `cleanup()` calls anywhere. New:
`test_initialize_pump_failure_does_not_block_ad2_camera_valve_z_stage`
(the exact user-reported scenario -- Pump failing does not block or roll
back AD2/Camera/Valve/Z-stage); `test_initialize_reports_every_
independent_failure_not_just_the_first` (two independent failures, both
named in the raised exception); `test_initialize_reports_per_device_
progress_independently_on_partial_failure` (per-device progress events
show genuine independent Complete/Failed, never "Rolled back"). Three new
Valve tests: lazy-reconnect fires when never initialized, does NOT
redundantly reconnect when already initialized, and fires again correctly
after a *previously failed* (not just never-attempted) `initialize()` call
via a purpose-built `_FlakyOnceTextBackend`. `test_v2_tec_init_failure_
reports_rollback_instead_of_stale_complete` (the old v2-dialog regression
test) rewritten as `test_v2_tec_init_failure_leaves_other_devices_
genuinely_connected` -- confirms both the per-device dialog rows AND
Global Status now agree AD2/Camera/Pump/Valve stayed connected when only
TEC failed.

**Full suite:** 543 passed, 4 failed -- the same 4 pre-existing,
already-tracked `application.py` flush-flowrate-validation failures (see
Session 105's entry and the earlier "534 passed, 4 failed" baseline from
Session 104), unrelated to this change; none of their tracebacks touch
`Application.initialize()`, `Valve`, or any file this session edited.

**Files touched:** `src/thermo_acoustic/application.py`,
`src/thermo_acoustic/instruments.py`, `src/thermo_acoustic/qt_ui_v2.py`
(comment only), `docs/hardware_repair_plan.md`, `docs/known_open_items.md`,
`tests/test_full_flow_dry_run.py`, `tests/test_application.py`,
`tests/test_qt_ui_v2.py`. Nothing committed -- pending review.
