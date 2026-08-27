# Pending user feedback

User-reported issue log and feedback history. This is **not** the canonical
live tracker for all unresolved project work: use
[known_open_items.md](known_open_items.md) for that, and
[hardware_repair_plan.md](hardware_repair_plan.md) for evidence requirements
and repair planning. This file preserves raw issues personally reported by the
user; [claude_code_change_log.md](claude_code_change_log.md) is historical
only.

**Convention:** any newly-reported issue gets appended here immediately,
before any other work happens on it (even mid-task). Status is one of
`open` / `in-progress` / `resolved`. Entries are not deleted when
resolved -- they're marked resolved in place, so this file also serves
as a short audit trail of what was reported and when.

File-and-line references inside an entry identify the source snapshot that was
reviewed when that entry was written. They are historical evidence, not stable
current-code anchors; use the named symbol and current source before acting.

---

## 1. Scroll wheel over a spin box changes its value on hover alone

- **Date raised:** 2026-07-29
- **Status:** resolved (2026-07-29 -- pre-existing, verified not new work)
- **Description:** Hardware-control `QSpinBox`/`QDoubleSpinBox` fields
  (frequency, amplitude, exposure, etc.) could have their value changed by
  an incidental mouse-wheel scroll while merely hovered, without being
  focused/clicked first -- a real safety concern for hardware setpoints.
- **Resolution:** Already implemented and already tested project-wide
  (v1 and v2) via `FocusWheelGuard`
  ([qt_ui.py:116](qt_ui.py:116)), a `QApplication`-level event filter
  installed once in `MainWindow.__init__`
  ([qt_ui.py:447](qt_ui.py:447)), inherited by `MainWindowV2`. Ignores
  wheel events on unfocused `QSpinBox`/`QDoubleSpinBox`/`QComboBox` and
  forwards them to the nearest ancestor `QScrollArea`'s viewport instead;
  focused widgets are unaffected. Covered by 4 existing tests:
  `test_focus_wheel_guard_ignores_unfocused_spinbox_wheel`,
  `test_ad_settings_scroll_area_wheel_guard_interaction` (both the
  unfocused-no-change and focused-still-changes cases),
  `test_focus_wheel_guard_covers_every_spin_and_combo_widget`
  (completeness sweep via `findChildren()`, not a hardcoded list), and
  `test_wheel_guard_completeness_on_both_window_types_independently`
  (same sweep run against v1 and v2 independently). No new code needed.

## 2. Initialize dialog column order

- **Date raised:** 2026-07-29
- **Status:** resolved (2026-07-29)
- **Description:** Initialize Hardware dialog columns currently read
  Enable | Simulate | Device; requested order is Device | Simulate |
  Enable (device identity first, then simulated-or-not, then
  enabled-or-not).
- **Resolution:** Confirmed this 3-column grid only exists in v2's
  `InitializationDialog._device_selection_group()`
  ([qt_ui_v2.py:65](qt_ui_v2.py:65)) -- v1's Initialization tab uses a
  structurally different layout (two separate `QFormLayout` group boxes,
  "Hardware" and "Simulation," each with device-name-as-row-label, no
  single Enable/Simulate/Device grid), so no v1 change applies. Reordered
  the header row and each device row to Device | Simulate | Enable |
  Progress. New test
  `test_v2_initialization_dialog_device_column_order_is_device_simulate_enable`
  in [test_qt_ui_v2.py](../tests/test_qt_ui_v2.py) confirms the header
  order and, per data row, that the real `sim_*`/`*_enabled` widget
  instances (unwrapped from their tooltip-icon containers) sit in the
  new column positions. Full suite green, 324/324.

## 3. Systematic sweep: undersized text/history/description boxes

- **Date raised:** 2026-07-29
- **Status:** resolved (2026-07-29)
- **Description:** Beyond the Error Out box already fixed in Session 58,
  the user wants an exhaustive sweep of `qt_ui.py`/`qt_ui_v2.py` for every
  widget displaying free-form or variable-length text with a hardcoded
  small fixed-height/fixed-width that could truncate or cramp real
  content -- reported once before, wants it closed for good rather than
  patched one widget at a time.
- **Full sweep findings (every `setFixedHeight`/`setMaximumHeight`/
  `setFixedWidth`/`setMaximumWidth`/`setFixedSize` call in both files,
  classified):**
  - **Genuine findings, fixed this pass** (below).
  - **Already correctly handled, not touched:** `_SPIN_MAX_WIDTH` sites
    (numeric fields, not free-form text); `_TooltipIconButton.setFixedSize(18,18)`
    (icon, not text); `sweep_header`/`experiment_sweep_header`/`hint_label`/
    `hint` (all `wordWrap(True)` + a deliberate wrap-width cap, Session 38 --
    text wraps, doesn't truncate); the 5 `scroll.setMaximumHeight(...)` sites
    (`QScrollArea` with `ScrollBarAsNeeded`, content scrolls rather than
    clips); `self.status`/`self.error_log`'s *group* width caps
    (`_error_panel()` 280px v1, `_global_status_panel()` 300px v2 -- a
    deliberate, previously-verified Session 38 fix for `QLabel` truncation
    elsewhere in those forms, unrelated to the list content itself).
  - **Finding A -- `HistoryLogWidget` (`qt_ui.py:381`, used as `self.status`/
    `self.error_log` in both v1 and v2):** `QListWidget` items don't wrap by
    default, so a long entry (e.g. a real exception message) was only
    reachable via horizontal scroll, one row at a time, inside the panel's
    280-300px width. **Fixed:** `self.setWordWrap(True)` added to
    `HistoryLogWidget.__init__` -- one shared class, fixes both `status` and
    `error_log` in v1 and v2 uniformly.
  - **Finding B -- `self.mso_stats` (`qt_ui.py`, MSO tab, plain `QLabel`):**
    `_set_mso_stats()` concatenates a per-channel summary with `" | ".join()`
    -- unbounded length (grows with capture channel count) -- with no
    `wordWrap`, the same unwrapped-`QLabel`-in-a-form bug class already fixed
    elsewhere in this tab (`sweep_header`/`hint`), just missed here. **Fixed:**
    `self.mso_stats.setWordWrap(True)`.
  - **Finding C -- `self.mso_text` (`qt_ui.py`, MSO tab, `QPlainTextEdit`,
    was `setMaximumHeight(90)`):** previews up to 6 samples/channel x 2
    channels = 12 lines; 90px only showed ~4-5 without scrolling (internally
    scrollable, so never literally inaccessible, but cramped). **Fixed:**
    bumped to `140`, matching the height convention already established for
    other small scrollable panels (Session 58's `HistoryLogWidget` group).
  - **Finding D -- v1 Initialization tab's 3 path fields
    (`qmix_sdk_python_path`/`qmix_qmixsdk_path`/`cetoni_config_path`,
    `qt_ui.py`'s `_instrument_group()`):** these can hold long real Windows
    paths; `qt_ui_v2.py`'s `InitializationDialog` already widens these exact
    same shared widget instances for itself (`_widen_for_content()`), but a
    user running v1 alone (never opening the v2 dialog) never got that
    treatment -- left at Qt's small default `QLineEdit` sizeHint. **Fixed:**
    extracted `_widen_for_content()` to a shared module-level function in
    `qt_ui.py` (was a v2-only `InitializationDialog` static method); v1's
    `_instrument_group()` now calls it for all three fields; v2's dialog
    updated to call the shared function too (removes the now-redundant
    duplicate implementation).
  - **4 new tests:** `test_history_log_widget_wraps_long_entries_instead_of_requiring_horizontal_scroll`,
    `test_mso_stats_label_wraps_instead_of_growing_unbounded`,
    `test_mso_text_preview_box_shows_close_to_a_full_two_channel_preview`,
    `test_initialization_tab_path_fields_are_widened_to_fit_their_real_content`
    -- all in [test_qt_ui_hardware_settings.py](../tests/test_qt_ui_hardware_settings.py).
  - **Files touched:** [qt_ui.py](../src/thermo_acoustic/qt_ui.py) (`HistoryLogWidget.__init__`,
    `mso_stats`/`mso_text` construction, new module-level `_widen_for_content()`,
    `_instrument_group()`), [qt_ui_v2.py](../src/thermo_acoustic/qt_ui_v2.py)
    (`InitializationDialog` now imports and calls the shared
    `_widen_for_content()` instead of its own duplicate; unused `QLineEdit`
    import removed), [test_qt_ui_hardware_settings.py](../tests/test_qt_ui_hardware_settings.py)
    (4 new tests).
  - **Verification:** tested -- full suite green, 328/328 (324 after Item 2,
    + 4 new here), modulo the
    same already-documented (Sessions 41/42/48) offscreen-Qt/Shiboken
    flakiness -- confirmed unrelated via isolation reruns of every test that
    failed on a full-suite pass. That flakiness is visibly hitting more
    tests per full run in this session than the historical 0-1/run baseline
    (2-5 different, always-pass-alone tests per run observed while verifying
    this item) -- not investigated further here (out of scope for items 1-4),
    but flagged since the user separately noted this same trend earlier
    this session.

## 4. Z-stage initialization failure + recurring random device connection failures

- **Date raised:** 2026-07-29
- **Status:** investigated (2026-07-30) -- root cause confirmed for the
  specific Z-stage report; general "random failures" claim still open,
  not reproduced, needs to be caught in the act. **No fix applied**, per
  instruction -- diagnostic only.

- **1. Current USB/COM state (read-only, checked live):** Healthy, no
  drift since Session 54. `serial.tools.list_ports.comports()` and
  `Get-PnpDevice -Class Ports` agree: exactly 4 ports exist --
  COM1 (onboard), COM4 (`FTDI A 0403:6015`), COM5 (`FTDI 0403:6001,
  SER=A10LJUBMA`), COM6 (`FTDI 0403:6001, SER=A601VWIFA`). **Valve is
  still correctly on COM5** (Session 54's fix holds). **COM7 does not
  exist and was not found in the enumeration at all.** The real piezo's
  own USB device ("APT USB Device", `VID_0403&PID_FAF0`, serial
  `44533854` -- matching `thorlabs_piezo.py`'s configured default) is
  present and healthy, status OK.

- **2. Reproduction + exact error.** Enabling "Z stage" on the
  Initialize Hardware dialog and clicking Initialize builds a
  `PriorZMotor` pointed at `prior_resource` (default `"COM7"`,
  [hardware_config.py:24](../src/thermo_acoustic/hardware_config.py:24))
  via `SerialTextCommandBackend` -- **not** the real Thorlabs piezo.
  Reproduced deterministically (3/3 attempts, byte-identical): the
  surfaced error is
  `RuntimeError: z_motor initialize failed: could not open port 'COM7':
  FileNotFoundError(2, 'The system cannot find the file specified.',
  None, 2)` (a real `pyserial.SerialException` at the OS level, wrapped
  by `Application.initialize()`'s per-device try/except at
  [application.py:230](../src/thermo_acoustic/application.py:230)). This
  is not a UI "Failed" placeholder -- it's the genuine underlying
  exception, and it is 100% deterministic, not intermittent: **COM7 has
  never existed on this system** in the current enumeration, so this
  path cannot ever succeed as currently wired.

- **Root cause (confirmed, not guessed): the Initialize dialog's
  "Z-stage" checkbox does not control the real piezo at all.** This was
  already independently flagged in Session 39
  (`claude_code_change_log.md`: "Z stage backend selection has no real
  effect... enabling 'Z stage' always builds a Prior-serial `PriorZMotor`,
  regardless of ... the UI's own 'Z stage backend' combo") but never
  previously connected to an actual failure report. `z_enabled`'s own
  tooltip ([qt_ui.py:540](../src/thermo_acoustic/qt_ui.py:540)) already
  states this correctly, but it's a click-to-reveal tooltip, easy to miss.
  The real piezo (Thorlabs Kinesis, `thorlabs_piezo.PiezoStage`) is
  **only** ever reached from the Z-Scan tab's own buttons ("Query Piezo
  Range" / "Start Z-Scan") -- never from `Application.initialize()` at
  all. `z_enabled` defaults to unchecked (unlike AD2/Camera/Pump/Valve,
  which default to checked), so this requires the operator to have
  deliberately turned "Z stage" on -- consistent with someone specifically
  planning piezo/Z-scan work for that run and expecting the checkbox to
  cover it.

- **Confirmed the real piezo itself connects cleanly right now**, via its
  actual code path (`PiezoStage.connect()`, using the real launcher's
  `exp_ctrl` conda env where `pythonnet`/Kinesis are actually installed --
  the base env used for the rest of this session's `pytest` runs does not
  have `pythonnet` and would misleadingly report a different error):
  `max_travel_um=450.0`, `max_output_voltage_v=150.0`,
  `min_output_voltage_v=-25.0`, `position_control_mode=CloseLoop` --
  values consistent with prior sessions' documented device specs.
  Disconnected cleanly afterward. **No failure reproducible on the real
  piezo's own path right now.**

- **3. readline()/\r bug-class cross-check: does not apply, confirmed.**
  Two independent reasons: (a) the COM7 failure happens inside
  `SerialTextCommandBackend._open()`'s `serial.Serial(...)` constructor
  call -- the port never opens, so `write()`/`query()` (where the
  Session 54/55 readline() fix lives) never runs at all; (b) the real
  piezo's own connection path doesn't use `SerialTextCommandBackend` or
  any `\r`-terminated text protocol whatsoever -- it's Thorlabs Kinesis's
  .NET SDK via pythonnet (`device.Connect()`, `channel.WaitForSettingsInitialized()`),
  a completely different communication mechanism with its own internal
  timeout handling inside the Kinesis DLL, unrelated to this project's
  own serial code. This is a different failure mode entirely from
  readline()/\r, not a variant of it.

- **USB hub topology re-confirmed current** (`DEVPKEY_Device_Parent`
  walk, same method as Session 54): COM4 (AD2), COM5 (Valve), COM6, and
  the piezo's own APT USB device all still converge through the same two
  chained USB hubs (`VID_2109&PID_0812`, instances
  `5&2fcc3441&0&7` -> `6&2528f560&0&1`) before the root hub -- the
  documented shared-hub risk factor is real and unchanged, just **not
  what caused this specific reported failure** (a wiring/labeling bug
  with a guaranteed, deterministic trigger, independent of hub state).

- **Remaining ambiguity -- "recurring random device connection
  failures" (the general claim, separate from the specific Z-stage
  report):** not reproduced during this pass -- every device enumerated
  and connected cleanly (COM ports match expectations, real piezo
  connects, valve port unchanged). The shared-hub theory remains a
  plausible risk factor for *some* future correlated failure but there is
  no current evidence it has actually fired. **What would be needed to
  pin this down further:** catch it in the act next time it happens --
  capture the exact device, exact exception/error text (not just the
  UI's "Failed"), and `comports()`/`Get-PnpDevice` state at that same
  moment, ideally with Windows Event Viewer's USB/kernel-PnP log checked
  for a hub reset/re-enumeration event around the same timestamp. Not
  attempted here since nothing is currently failing to catch.

- **Recommendation (not applied -- flagging for a future decision, per
  "diagnose before fixing"):** the Initialize dialog's "Z-stage" checkbox
  wiring to the wrong, always-nonexistent-port device is a real,
  independently-actionable bug once confirmed -- either point it at the
  real piezo, remove/disable the checkbox with a clearer non-functional-stub
  marking (matching this project's established dead-control convention),
  or at minimum default `prior_resource` to a port that could plausibly
  exist. Left as a recommendation only; not implemented in this pass.
  **Actioned in item 5, Part B1 below.**

## 5. Global hardware feedback logging (Part A) + Z-stage repoint, legacy sweep, real-hardware verification (Parts B/C)

- **Date raised:** 2026-07-30
- **Status:** resolved for the recorded Parts A-C (2026-07-30). The embedded
  "Not committed" notes describe the session-time state; the implementation
  later landed across `17f24dd`, `7c7e19f`, and `22c68cb`.

### Part A -- shared hardware transaction logging module

- **Status:** resolved (2026-07-30)
- **Design:** new [hw_logging.py](../src/thermo_acoustic/hw_logging.py) --
  one shared logger/rotating file (`logs/hardware_transactions.log`,
  5MB x 5 backups), not one file per device, since a single
  chronologically-merged timeline is what makes cross-device interference
  (the documented shared-USB-hub risk, relevant to Part C) diagnosable from
  the log at all. Two entry points: `log_transaction(device, operation,
  command=, response=, success=, error=)` (explicit, used where control
  flow must not change on failure -- e.g. `close()`'s existing
  collect-errors-then-raise cleanup shape) and `log_call(device, operation,
  command=)` (a context manager for the common "one command, one
  response-or-exception" shape, used everywhere else). Deliberately
  synchronous (plain `logging` + `RotatingFileHandler`, no threading/async)
  -- `test_synchronous_logging_overhead_is_negligible_for_real_call_frequency`
  measures 500 calls at <0.5ms/call average, many orders of magnitude below
  this project's own documented real-hardware call latencies (single-digit
  ms to multiple seconds, e.g. the pre-Session-55 valve `readline()` bug
  blocking ~5s/call), so no async wrapper was needed.
- **Instrumentation coverage** (device | call sites | file):
  - **piezo** -- `connect`, `disconnect`, `switch_to_closed_loop`,
    `get_position`, `set_position` (all 5 public hardware-touching methods)
    -- [thorlabs_piezo.py:117,157,195,211,230](../src/thermo_acoustic/thorlabs_piezo.py:117)
  - **ad2** -- `open_device`, `close`, `trigger_pc`, `configure_wfg`,
    `configure_do`, `reset_do`, `capture_analog_in`,
    `capture_analog_in_channels` -- the 8 methods actually called by
    `AD2Sdk` (the only real entry point; confirmed via
    `grep self.get_backend()\.`), not the ~80 individual ctypes-binding
    one-liner wrappers underneath them, which are SDK-surface plumbing not
    exercised by the production app at all (scoping decision explained
    in-code and here, not silently skipped) --
    [waveforms.py:204,213,227,397,498,600,713,774](../src/thermo_acoustic/waveforms.py:204).
    Per-iteration status-poll calls inside `capture_analog_in[_channels]`'s
    wait loop are deliberately not logged individually (can run hundreds of
    times per capture) -- only the terminal outcome, via the wrapping
    `log_call`.
  - **camera** -- `open_camera`, `configure_exposure_time`,
    `configure_roi`, `configure_sequence`, `configure_trigger_global_exposure`,
    `start_capture`, `stop_capture`, `capture_snapshot`, `image_sequence`,
    `read_subregion_limits_and_value`, `read_readout_time`, `sw_trigger`,
    `close` (all 13 public hardware-touching methods) --
    [hamamatsu_dcam.py:70,91,119,191,264,273,280,286,301,370,394,403,420](../src/thermo_acoustic/hamamatsu_dcam.py:70).
    `close()` uses `log_transaction()` (not `log_call()`) to preserve its
    existing Finding-F best-effort swallow-and-log cleanup shape.
  - **pump** -- `initialize`, `refill`, `empty`, `stop`, `generate_flow`,
    `read_fill_level`, `set_fill_level`, `configure_syringe`,
    `configure_flow_unit`, `reference_move`, `read_status`, `close` (all 12
    public hardware-touching methods) --
    [qmix_backend.py:117,165,172,178,201,208,219,267,285,293,306,323](../src/thermo_acoustic/qmix_backend.py:117).
    `close()` uses `log_transaction()` for the same reason as camera's.
  - **valve** -- `SerialTextCommandBackend.connect/write/query/close`, the
    shared serial primitive `Valve` (and, until Part B1 retires it, the
    legacy `PriorZMotor`) both use --
    [instruments.py:57,86,91,109](../src/thermo_acoustic/instruments.py:57).
    Added a `device_name` field (defaults to `"serial"`) so the generic
    backend tags its own log lines correctly; `hardware_factory.py`'s valve
    construction site now passes `device_name="valve"`.
- **9 new unit tests** in [test_hw_logging.py](../tests/test_hw_logging.py)
  (records written correctly, failure paths logged, fields omitted rather
  than printing `None`, timestamped, `log_call` success/failure incl.
  re-raise, `configure()` directory-creation + idempotency, the
  synchronous-overhead timing assertion) plus **5 spot-check integration
  tests** in [test_hw_logging_integration.py](../tests/test_hw_logging_integration.py)
  (one real production call site per device, using each module's existing
  fake-SDK injection pattern, confirming it actually reaches the shared log
  -- not exhaustive per-call-site testing, per instruction).
- **Verification:** tested -- full suite green, 342/342 (328 baseline + 14
  new: 9 + 5), modulo the same already-documented offscreen-Qt/Shiboken
  flakiness, confirmed unrelated via isolation reruns.
- **Not committed** -- `instruments.py`/`hardware_factory.py` carry TEC's
  own uncommitted diff; this needs the same hunk-reconstruction-and-verify
  discipline as every other TEC-entangled file before it can land. `tec.py`
  and TEC-related sections of `application.py`/`hardware_factory.py`/
  `qt_ui.py`/`qt_ui_v2.py`/`workflows.py` and their tests were not touched
  at all in this pass.

### Part B1 -- repoint Z-stage to the real piezo

- **Status:** resolved (2026-07-30)
- **Root cause recap** (from item 4's investigation): the Initialize
  dialog's "Z-stage" checkbox built a `PriorZMotor` pointed at `COM7`, a
  port that never existed on this lab's hardware and was never actually
  the real piezo. `z_stack()`/`go_to_abs_pos()` (the only other
  PriorZMotor-specific API) had zero real callers anywhere in the live
  UI/experiment path -- confirmed via a repo-wide search before touching
  anything, not assumed.
- **New `ZStage` class** ([instruments.py](../src/thermo_acoustic/instruments.py))
  replaces `PriorZMotor` -- a thin adapter wrapping the real
  `thorlabs_piezo.PiezoStage` (the exact class/connection logic the Z-Scan
  tab already uses, not a second divergent path), matching the same
  `enabled`/`initialize()`/`cleanup()` shape every other `HardwareBundle`
  member already uses (`HamamatsuCamera`/`CetoniPump`/`Valve` each wrap a
  real SDK backend the same way). `initialize()` calls `stage.connect()`
  and captures `status_note` (serial/max_travel_um/position_control_mode);
  `cleanup()` calls `stage.disconnect()` if connected. `PriorZMotor` and
  `Application.z_stack()` were both removed entirely (confirmed no other
  real dependents beyond their own now-updated tests; `piezo_zscan.py`'s
  own isolation test already asserted `PriorZMotor` is *not* imported
  there, so removal doesn't affect it).
- **Threaded through:** `Application.z_motor: ZStage` (was `PriorZMotor`),
  `get_z_stage()`/`set_z_stage()` (renamed from `get_prior_zmotor()`/
  `set_prior_zmotor()` -- "prior" was actively misleading once retired),
  `HardwareBundle.z_motor: ZStage`, `HardwareRuntimeConfig.thorlabs_apt_serial`
  (renamed from `prior_resource` -- the piezo connects by device serial via
  Kinesis, not a COM port), `build_hardware_bundle()` now constructs
  `ZStage(enabled=config.z_enabled, stage=PiezoStage(serial_number=config.thorlabs_apt_serial))`.
  Routed through Part A's `hw_logging` automatically (`PiezoStage.connect()`/
  `disconnect()` were already instrumented in Part A, tagged `"piezo"`).
- **Initialize dialog now reports real connection status.** v2's per-device
  progress loop ([qt_ui_v2.py](../src/thermo_acoustic/qt_ui_v2.py)) enriches
  the "Complete" text for any instrument exposing a `status_note` (Z-stage
  is the only one right now) to `"Complete (serial=..., max_travel_um=...,
  mode=...)"` instead of a bare status word -- consistent with every other
  row showing a real outcome, not a status word alone (matching the task's
  own acceptance criterion). v2's `InitializationDialog._hardware_details_group()`
  and v1's `_instrument_group()`: `thorlabs_apt_serial` is now genuinely
  wired (un-stubbed, real tooltip); `prior_resource` is now the unwired
  stub (row relabeled "(legacy, unwired)", tooltip explains why) -- the
  inverse of before.
- **`ui.py` (confirmed dead, unimported, separate open item) still imports
  `PriorZMotor` and will now fail if it's ever actually run** -- deliberately
  not fixed, since fixing it would imply resurrecting a codepath nobody
  asked to touch (it has zero importers anywhere in the repo, per
  `known_open_items.md`'s own "awaiting a removal decision" entry).
  `hardware_tests/test_serial_discovery.py` (a standalone diagnostic
  script, not a pytest test) still reads a persisted `prior_resource` key
  and lists `"COM7"` as the "Prior Z-stage default" -- harmless (read-only,
  best-effort) but now stale; flagged as a minor low-priority follow-up,
  not fixed here (peripheral tool, not part of the 5 backends or any
  acceptance criterion).
- **Tests:** removed 2 tests that were entirely about the retired serial
  path (`PriorZMotor` write/query command-sequence assertions, the Finding-G
  stale-position regression test -- both genuinely inapplicable now, the
  behavior they tested no longer exists), updated ~10 more across
  `test_application.py`/`test_hardware_factory.py`/`test_qt_ui_v2.py`/
  `test_qt_ui_hardware_settings.py` for the renamed field/methods, added 2
  new: `test_z_stage_initialize_connects_the_real_piezo_and_reports_status_note`
  (using the same fake-Kinesis injection pattern `test_thorlabs_piezo.py`
  already established) and `test_z_stage_disabled_never_touches_the_real_piezo`
  (a stage whose `connect()` raises if ever called, confirming the
  `enabled=False` gate genuinely short-circuits before any hardware touch).
- **Verification:** tested -- full suite green, 343/343, modulo the same
  already-documented offscreen-Qt/Shiboken flakiness (confirmed unrelated
  via isolation reruns of every test that failed on a full-suite pass, same
  as every other item this session).
- **Not committed** -- same reason as Part A (TEC-entangled files); the
  `PriorZMotor`/`z_motor` lines this touches were confirmed line-by-line
  non-overlapping with TEC's own current diff in
  `application.py`/`hardware_factory.py` before editing, but the actual
  commit still needs the full hunk-reconstruction-and-verify pass.

### Part B2 -- sweep known_open_items.md/pending_feedback.md for other fixes

- **Status:** resolved (2026-07-30)
- **Table (item | prior status | action taken | file:line | test):**

  | Item | Prior status | Action | File:line | Test |
  |---|---|---|---|---|
  | Fill-level desync after restart | Claimed possibly-open by the task; already RESOLVED (Session 56/57) | **Confirmed still fixed in current code** -- `CetoniPump.initialize()`/`refill()` both still call `backend.read_fill_level()` to sync; not re-broken by anything this session. No code change needed. | [instruments.py:686,699](../src/thermo_acoustic/instruments.py:686) | (existing coverage, unchanged) |
  | Changelog summary staleness | 2 confirmed-stale bullets in `claude_code_change_log.md`'s own "Known remaining open items" section (predates `known_open_items.md`) | **Fixed:** added a banner pointing to `known_open_items.md` as the current source (not re-syncing the whole legacy section -- that duplication is what caused the staleness); inline-corrected the 2 bullets I could verify against current code (WFG bounds checking -- actually resolved Session 51; valve-handshake hardening -- actually committed `8149bc1`) | [claude_code_change_log.md:4577](../docs/claude_code_change_log.md:4577) | n/a (docs) |
  | "ClosedLoop dialog branch not triggering" | Named by the task as a known item | **Investigated, no code defect found.** Full search of the codebase and changelog found only one related note: Session 48's real-hardware CLI run, where the confirmation branch legitimately wasn't exercised because the piezo was already `CloseLoop` at connect time -- a fact about that one test run, not a bug (the branch's own code, `needs_closed_loop_confirmation()`/`_cli_confirm_closed_loop()`/the UI's `QMessageBox` path, is unit-tested and was never reported broken). **Remains genuinely unverified against real hardware in the "device is NOT already ClosedLoop" state** -- deferred to Part C (needs the piezo actually in `OpenLoop` at connect time, not a code fix). | n/a | n/a |
  | Pump flow-rate sign-convention stale "unverifiable" tooltip wording | Audit found at least one stale tooltip | **Confirmed already fixed** -- case-insensitive repo-wide search for "unverifiable" found zero matches; both current tooltips consistently say "-=aspirate, +=dispense". Already fixed by an earlier session, not previously marked resolved. No code change needed. | n/a | n/a |
  | Camera ROI/exposure startup defaults diverge from validated combo | OPEN (Session 18 audit) | **Fixed:** `roi_v_offset` 900→792, `roi_v_size` 500→740, `exposure_ms` 50.0→40.0, matching `experiment_presets.py`'s own already-validated `LabviewCameraPreset` defaults exactly (cross-checked before applying, not assumed) -- the tooltip already spelled out these exact target values, so this was a pure constant correction, no new research needed. | [qt_ui.py:802-816](../src/thermo_acoustic/qt_ui.py:802) | (no dedicated test; not a behavior branch, just startup constants -- full suite green confirms no regression) |
  | Prior Z-motor baud rate inherited from valve, unverified | OPEN (Session 18 audit) | **Moot** -- the whole Prior Z-motor/serial path was retired in Part B1; the real piezo has no baud-rate concept at all. | n/a | n/a |
  | DCAM ROI never auto-applied in the automated experiment path | OPEN, confirmed real gap (Session 21/51) | **Deferred, not fixed.** Genuinely a larger design decision, not a small mechanical fix: auto-applying `configure_roi()` in `run_experiment2()` would be a real behavior change (a previously silently-not-applied ROI would now apply), and the docs themselves note this is "confirmed likely a pre-existing LabVIEW limitation too" -- meaning even the original LabVIEW software may not have auto-applied it either. Needs a design decision from the user, not a guess. | n/a | n/a |
  | Qmix syringe geometry never auto-applied in the automated path | OPEN, confirmed real gap (Session 21) | **Deferred, not fixed** -- same reasoning as the DCAM ROI item above (real behavior-change risk, same "possibly-intentional LabVIEW parity" ambiguity). | n/a | n/a |
  | Four inconsistent hardware `close()`/`cleanup()` shapes | OPEN for the 4 existing implementations (Session 57) | **Deferred, not fixed** -- the item's own text already states unifying them "remains a real design decision for someone to make, not resolved by this entry"; not attempted here either, per that same standing note. | n/a | n/a |
  | LabVIEW port registry materially incomplete | OPEN (Session 11) | **Deferred, not fixed** -- completing it requires tracing the original exported LabVIEW VI diagrams (`AD2_MSO_SDK_class`'s 17 undocumented VIs, etc.), external reference material not available in this pass, not a small/low-risk code change. | n/a | n/a |
  | Syringe stroke length derived, not BD-spec-sourced | OPEN by nature (Session 17) | **Not fixable from code/repo alone** -- no authoritative external BD stroke-length figure exists in this repo to substitute; would need an external vendor citation. | n/a | n/a |
  | Pump safety enforcement's stepper-stall-safety citation gap | OPEN as a citation gap (Session 51) | **Not fixed** -- the enforcement itself is already real and hardware-verified (Session 51); only the *original justification* is uncited, which needs CETONI's own vendor documentation (external), not a code change. | n/a | n/a |

- **Verification:** tested -- full suite green, 343/343, no regressions from the one code change (camera ROI/exposure defaults).

### Part C -- real-hardware verification pass

- **Status:** resolved for the items covered (2026-07-30) -- a substantial
  but not exhaustive pass, time-boxed; several items explicitly need
  equipment (oscilloscope) or external reference material not available in
  this pass and are listed as deferred, not approximated.
- **Available this pass:** piezo, AD2, camera, pump, valve all physically
  connected and responsive (confirmed via live enumeration before testing,
  not assumed). All evidence below is real hw_logging log excerpts from
  `logs/hardware_transactions.log`, generated via the real launcher's
  `exp_ctrl` conda env (the only environment with `pythonnet`/Kinesis and
  the Qmix SDK actually installed).
- **Found and fixed a real bug while setting this up:** the two new hw_logging
  test files (Part A) had no log-file redirection when first added to
  `tests/`, so running the suite in a real-hardware-capable environment let
  a handful of test-only piezo log entries leak into the real
  `logs/hardware_transactions.log`, indistinguishable from genuine evidence.
  Fixed with a new session-scoped `_hw_logging_isolated` autouse fixture in
  [conftest.py](../tests/conftest.py) that redirects hw_logging to a
  throwaway file for the entire test session, before any test can run --
  full suite reconfirmed green (343/343) and the real log confirmed
  untouched by a subsequent full-suite run.

- **Table (item | test performed | outcome | fix applied | evidence):**

  | Open item | Test performed | Outcome | Fix | Evidence |
  |---|---|---|---|---|
  | Z-stage (Part B1) stable across repeated cycles | 5x `ZStage.initialize()`/`cleanup()` cycles in a loop | **Confirmed fine** -- 5/5 clean connect/disconnect, identical status_note each time (450.0um/CloseLoop/serial 44533854) | n/a | `piezo \| connect \| OK ... resp='max_travel_um=450.0...'` x5, `piezo \| disconnect \| OK` x5 in log, 11:14:00-11:14:06 |
  | USB hub shared-risk topology -- concurrent multi-device interference | Piezo (4 moves) + AD2 (5 triggers) + valve (5 status polls) + camera (3-frame capture) run concurrently on 4 threads | **Confirmed fine** -- 2.44s total, zero errors across all 4 devices, log shows genuinely interleaved real transactions from all 4 devices with no dropped connections or cross-device corruption | n/a | log 11:15:52,202-11:15:54,582 (interleaved valve/ad2/piezo/camera lines) |
  | Pump flow-rate safety enforcement | Real pump connected; requested 2x its own reported `max_flow_rate_ul_min` (14632.8 vs real ceiling 7316.4) | **Confirmed fine** -- rejected before reaching the SDK with the exact real ceiling in the error message; a within-limit request (10.0) was accepted normally right after | n/a | `Requested flow_rate=14632.84... exceeds ... max_flow_rate_ul_min=7316.42...` |
  | Pump stepper-stall-safety citation gap | n/a -- not real-hardware-testable, needs CETONI's own vendor documentation | **Inconclusive, deferred** -- external vendor documentation, not available in this pass | n/a | n/a |
  | Category B/Category-A "fake-tested only" items, live-verified this pass | See rows below | | | |
  | -- `CetoniPump.fill_level` readback sync (Session 56/57) | Real `pump.initialize()` against the actual Qmix pump | **Confirmed fine** -- `read_fill_level()` genuinely executes against real hardware right after `initialize()` (mechanism confirmed; the specific value, 0.0, reflects the syringe genuinely being empty right now, not a stale/hardcoded fallback) | n/a | `pump \| read_fill_level \| OK \| resp=0.0` immediately after `pump \| initialize \| OK` |
  | -- `SerialTextCommandBackend.query()` readline()/`\r` fix (Session 55) | Real valve `query('S')` timed | **Confirmed fine** -- 16ms, not the pre-fix ~5s full-timeout block | n/a | `query(S) elapsed: 0.016 s` |
  | -- AD2 SDK clock-divider wiring (`configure_do()`) | Real AD2: read internal clock (100MHz), computed a divider for a 100Hz target, wrote it to real hardware | **Confirmed fine** -- clock=100MHz (matches WaveForms SDK spec), computed divider gave an exact 100.0000Hz achieved frequency, real hardware write succeeded | n/a | `digital_out_internal_clock_info(): 100000000.0 Hz`, `target=100.0Hz -> computed_divider=500000 -> achieved=100.0000Hz` |
  | -- Qmix bus close on init failure | Real `CetoniPump.initialize()` with a deliberately invalid config path | **Confirmed fine** -- real `DeviceError` from the SDK, rollback `close()` left `backend.pump`/`backend.bus` both `None`, and a second, valid `initialize()` right after succeeded cleanly (no leaked/stuck bus handle) | n/a | `backend.pump is None: True`, `backend.bus is None: True`, `follow-up real initialize() succeeded: True` |
  | -- Frequency Scanning per-repeat frequency substitution | 3 different frequencies (1000/1050/1100 kHz) applied to real AD2 CH1 in sequence, read back each time | **Confirmed fine** -- all 3 genuinely reached the device, readback matched requested within float precision | n/a | `requested 1050.0kHz -> device readback 1049.999997485429kHz` |
  | -- Abort concurrency (real devices) | Not attempted this pass | **Inconclusive** -- time-boxed out; still fake-tested only, not claimed as verified | n/a | n/a |
  | DCAM frame timestamp clock domain | 3-frame real capture, inspected per-frame `dcam_clock:` deltas | **Inconclusive (new supporting data, not a resolution)** -- deltas were ~0.03164s, matching `read_readout_time()` (0.031645s) almost exactly, not the configured exposure (20ms) -- independently reproduces Session 31's exact finding with fresh data. Still doesn't answer *which* clock domain or epoch -- needs official SDK documentation. | Not fixed (not fixable from a live test alone) | `timestamps: ['dcam_clock:1785402932.013011', ...]`, deltas ≈0.031645s vs `read_readout_time(): 0.03164457...` |
  | ClosedLoop confirmation branch, "device NOT already ClosedLoop" | Attempted -- checked current real piezo state | **Inconclusive, deferred** -- the real piezo is currently already in `CloseLoop` mode every time it was connected this pass (5 fresh connects, all `CloseLoop`), so the confirmation-needed branch cannot be naturally exercised right now without manually forcing `OpenLoop` -- which `PiezoStage`'s own design deliberately never does without explicit user confirmation (Session 45 decision), so not attempted. Needs the device to actually be in `OpenLoop` at connect time. | Not fixed | n/a |
  | Camera trigger source Internal-vs-External | Not attempted -- explicitly needs an oscilloscope | **Deferred, needs oscilloscope** | n/a | n/a |
  | DIO0(acoustic)/DIO1(LED) relative timing | Not attempted -- explicitly needs an oscilloscope | **Deferred, needs oscilloscope** | n/a | n/a |
  | TDMS content vs. real LabVIEW file comparison | Not attempted -- needs an external real-LabVIEW-written TDMS file for comparison, not available in this repo | **Deferred, needs external reference file** | n/a | n/a |
  | FM Sweep's 3 unverified assumptions vs. real LabVIEW binary/literature | Not attempted -- needs the compiled LabVIEW binary's block-diagram wiring or the Martens et al. source literature, neither available in this pass | **Deferred, needs external material** | n/a | n/a |
  | LabVIEW port registry completeness | Not attempted -- needs tracing exported LabVIEW VI diagrams not available in this pass | **Deferred, needs external material** | n/a | n/a |

- **Valve real port reconfirmation:** COM5, matches both the code default
  and Session 54's fix -- **no code/docs mismatch found**, nothing to fix
  (already confirmed once in item 4's investigation; reconfirmed again here
  with fresh enumeration, no drift).
- **Verification:** full suite green, 343/343, throughout Part C (no code
  changes were made as a *result* of Part C testing itself -- every tested
  item came back "confirmed fine," so there was nothing to fix; the one
  real bug found and fixed was in the test infrastructure itself, listed
  above).

## 6. Three approved follow-ups from item 5's evidence-gathering pass

- **Date raised:** 2026-07-30
- **Status:** resolved for all three recorded tasks and the pump-stall
  investigation. The residual reason for the pump's approximately 0.1873 ml
  stop remains explicitly open below; the parent task itself is no longer
  underway.

### Task 1 -- instrument the 9 reachable-but-unlogged AD2 methods

- **Status:** resolved (2026-07-30)
- Confirmed reachable from real-hardware-touching code outside `AD2Sdk`'s
  8 production entry points (per the evidence-gathering pass): all 9 now
  route through `hw_logging` via `log_call()`, same pattern as every other
  instrumented method.
- **Coverage table** (method | file:line | real reachable call site):

  | Method | File:line | Reachable from |
  |---|---|---|
  | `close_all` | [waveforms.py:217](../src/thermo_acoustic/waveforms.py:217) | `tools/release_ad2.py` |
  | `reset_device` | [waveforms.py:224](../src/thermo_acoustic/waveforms.py:224) | `hardware_tests/test_real_workflow_smoke.py`'s `safe_disable_ad2_outputs()` |
  | `enum_devices` | [waveforms.py:242](../src/thermo_acoustic/waveforms.py:242) | both `tools/release_ad2.py` and `hardware_tests/test_real_workflow_smoke.py`'s `read_ad2_identity()` |
  | `enum_device_is_opened` | [waveforms.py:257](../src/thermo_acoustic/waveforms.py:257) | both |
  | `enum_device_name` | [waveforms.py:264](../src/thermo_acoustic/waveforms.py:264) | both |
  | `enum_device_serial_number` | [waveforms.py:273](../src/thermo_acoustic/waveforms.py:273) | both |
  | `analog_out_configure` | [waveforms.py:418](../src/thermo_acoustic/waveforms.py:418) | `hardware_tests/test_real_workflow_smoke.py`'s `safe_disable_ad2_outputs()` |
  | `analog_out_node_enable_set` | [waveforms.py:321](../src/thermo_acoustic/waveforms.py:321) | same |
  | `digital_out_configure` | [waveforms.py:728](../src/thermo_acoustic/waveforms.py:728) | same |

- **9 new spot-check tests** in [test_hw_logging_integration.py](../tests/test_hw_logging_integration.py)
  (one per method, reusing a shared `_FakeDwf`/`_FakeDwfFunction` fixture
  extended from the existing `open_device` test's pattern to support the
  new FDwf function names). Test count: 5 -> 14 in that file.
- **Verification:** tested -- full suite green, 352/352 (343 baseline + 9
  new), modulo the same already-documented offscreen-Qt/Shiboken flakiness,
  confirmed unrelated via isolation reruns.
- **Not committed** -- `waveforms.py` is not TEC-entangled, but nothing in
  this session has been committed pending review, per standing instruction.

### Task 2 -- `PiezoStage.disconnect()` timeout protection

- **Status:** resolved (2026-07-30)
- Retrofitted to match `QmixPumpBackend.close()`'s actual current shape
  (the documented template in `docs/hardware_safety_patterns.md`) exactly:
  collect error strings from each step, each step wrapped in its own
  timeout-guarded daemon thread (`_run_disconnect_step()`, mirroring
  `_run_close_step()`), null out `device`/`channel`/`connected` regardless
  of outcome, raise one combined `PiezoStageError` at the end if anything
  failed or timed out. New `disconnect_timeout_s: float = 5.0` field,
  matching `close_timeout_s`'s own default.
- **Deliberately did not** add the per-step `log_transaction()` calls the
  hardware_safety_patterns.md note aspirationally suggests -- confirmed
  `QmixPumpBackend._run_close_step()` (the actual cited template) doesn't
  do that either, only the final combined outcome is logged. Matching the
  template's *real* behavior, not its aspirational doc text, keeps this a
  faithful "drop-in behavioral superset" as scoped -- not a second,
  independent improvement bundled in.
- **1 new test**, `test_disconnect_times_out_and_reports_instead_of_hanging_on_a_stuck_kinesis_call`
  in [test_thorlabs_piezo.py](../tests/test_thorlabs_piezo.py): a
  `StopPolling()` that genuinely never returns (`threading.Event().wait()`,
  the same pattern `test_application.py`'s own matching cleanup-timeout
  test already uses) with `disconnect_timeout_s=0.1` -- confirms
  `disconnect()` raises `PiezoStageError` matching "timed out after 0.1s"
  and returns in well under 1s (not hanging the test process), and that
  `channel`/`device`/`connected` are still cleaned up despite the timeout.
- **Verification:** tested -- full suite green, 353/353 (352 baseline + 1
  new), modulo the same already-documented offscreen-Qt/Shiboken flakiness,
  confirmed unrelated via isolation rerun. Also re-verified the success
  path against the real piezo directly (connect + disconnect, real
  hardware) -- unchanged, confirming the "drop-in superset, not a change
  to the success path" requirement.
- **Not committed** -- pending review, per standing instruction.

### Task 3 -- USB-hub long-duration soak test

- **Status:** USB-hub interference question resolved (no interference found)
  -- **but a separate, unrelated real-hardware anomaly was found and is
  explicitly NOT fixed, per instruction ("stop, report, wait for
  review").** See full write-up below.
- **Setup:** all 5 devices pre-opened, then run concurrently for 330.0s
  (5.5 min) real wall-clock time under a realistic per-device cadence:
  piezo `set_position()` every 2s (6-position cycle, 50-200um), AD2
  `trigger_pc()` every 2s + `configure_wfg()` every 15s (3 rotating
  frequencies), valve `query('S')` every 1.5s, camera `image_sequence(3)`
  every 25s, pump: one `generate_flow(-50.0)` (continuous aspirate, ~0.7%
  of the real 7316.42 ul/min ceiling) plus `read_fill_level()` polling
  every 15s to confirm the flow's progress without repeatedly restarting it.
- **Solo-run baselines established this pass** (piezo/pump previously
  unmeasured): piezo `set_position` min/mean/max = 0.19/1.84/15.96ms (10
  calls); pump `generate_flow`+`stop` min/mean/max = 3.62/4.04/4.52ms (5
  cycles); AD2 `trigger_pc` min/mean/max = 0.16/0.20/0.29ms (10 calls);
  valve `query` ~16ms (previously established).
- **Call counts over the 330s window:** piezo 165, AD2 trigger_pc 165 +
  configure_wfg 22, valve 218, camera 13 (39 real frames total), pump
  read_fill_level 23. **Zero `FAIL` entries anywhere in the window**
  (confirmed via `datetime`-bounded log parsing, not eyeballing).
- **Per-operation interval tightness (log-timestamp-derived, not raw
  per-call latency -- hw_logging doesn't capture call duration, only
  timestamp+outcome):** every device's actual call cadence stayed within
  single-digit-to-low-double-digit milliseconds of its target interval for
  the entire 330s, with **no drift over time** (spread stayed flat from
  start to finish, not widening) -- AD2 trigger 2.000-2.009s (target 2.0s),
  piezo set_position 2.000-2.009s (target 2.0s), valve query 1.503-1.521s
  (target 1.5s), AD2 configure_wfg 15.009-15.014s (target 15.0s), pump
  read_fill_level 15.000-15.002s (target 15.0s). Camera's 25.443-25.453s
  (target 25.0s) reflects real multi-frame capture time on top of the
  wait, expected. **No latency outliers, no growing delay, no evidence of
  cross-device contention for piezo/AD2/valve/camera.**
- **USB-hub interference conclusion for piezo/AD2/valve/camera: no
  interference observed, one 5.5-minute continuous run** (stronger than
  the two earlier short bursts, but still one run of this specific
  duration/load combination -- see the same honest-framing caveat as
  before: a longer/heavier/repeated soak would be needed to fully rule out
  an intermittent hub-power/re-enumeration risk; this test narrows the
  evidence further in the "no interference" direction, it doesn't close
  the question outright).

- **SEPARATE FINDING, NOT FIXED, AWAITING REVIEW:** the pump's real
  aspirate flow silently stopped moving fluid partway through the run,
  with zero error, zero exception, zero `FAIL` log entry.
  - `generate_flow(-50.0)` was called exactly once, at 12:23:01,558.
  - `read_fill_level()` (polled every 15s, 23 calls total, log-confirmed
    clean 15.000-15.002s cadence throughout -- the *read* operation itself
    was never delayed) rose smoothly and consistently with the requested
    rate from `0.0` to `0.18727791935442584` ml between 12:23:01 and
    12:26:46 (225s -- 50ul/min x 225s/60 = 187.5ul, matching the observed
    ~187.3ul almost exactly).
  - From 12:27:01 onward, **6 consecutive real `read_fill_level()` calls
    across the remaining 105s (12:27:01 through 12:28:16) all returned
    the bit-for-bit identical value `0.18727791935442584`** -- real fluid
    motion (or the SDK's internal tracking of it) genuinely stopped
    advancing, with no corresponding log entry of any kind marking the
    stop. `pump.backend.stop()` was not called by this test's own code
    until the very end (12:28:31,611), well after the value had already
    frozen.
  - **Two plausible explanations, not distinguished here (deliberately --
    this needs review, not a guess):** (a) the real Qmix SDK's
    `LCB_GenerateFlow`/`generate_flow()` call may have a bounded real
    duration per invocation rather than running indefinitely until an
    explicit `stop()` (i.e. "continuous" may not mean what this codebase
    assumed), or (b) `read_fill_level()`'s readback stopped tracking a
    still-genuinely-running physical motion (a caching/staleness issue in
    the SDK layer, not a real physical stop). Nowhere near the syringe's
    real `max_volume_ml=1.1780972450961724` capacity (0.187ml reached,
    <16% of capacity), so a capacity limit is ruled out.
  - **Not attempted in this pass:** distinguishing (a) vs (b), any fix,
    any further probing beyond what the soak test itself already
    captured. Per instruction, this is reported for review, not resolved.
  - Raw log excerpt (verbatim, `logs/hardware_transactions.log`):
    ```
    12:23:01,558 | pump | generate_flow    | OK | cmd=-50.0 | resp='applied'
    12:26:46,593 | pump | read_fill_level  | OK | resp=0.18727791935442584
    12:27:01,595 | pump | read_fill_level  | OK | resp=0.18727791935442584
    12:27:16,595 | pump | read_fill_level  | OK | resp=0.18727791935442584
    12:27:31,597 | pump | read_fill_level  | OK | resp=0.18727791935442584
    12:27:46,598 | pump | read_fill_level  | OK | resp=0.18727791935442584
    12:28:01,599 | pump | read_fill_level  | OK | resp=0.18727791935442584
    12:28:16,601 | pump | read_fill_level  | OK | resp=0.18727791935442584
    ```
- **Verification:** no code changes made as a result of Task 3 (pure
  real-hardware testing). Full test suite not re-run for this task (no
  source changed).
- **Not committed** -- pending review, per standing instruction.

### Task 3 follow-up -- priority root-cause investigation (pump flow stall)

- **Status:** resolved -- **Hypothesis A confirmed, Hypothesis B refuted**,
  by direct real-hardware evidence, not speculation. No code changes made
  (read-only investigation, as instructed).

**Conclusion up front:** the pump's real physical motion genuinely stopped
(Hypothesis A). It was not a stale `read_fill_level()` readback while
motion continued (Hypothesis B) -- three independent SDK signals
(`is_pumping()`, `get_flow_is()`, `get_dosed_volume()`), none of which
share a code path with `get_fill_level()`, all corroborate "genuinely not
moving" throughout. The *exact* proximate mechanism (why it stops around
there specifically) is narrowed but not 100% pinned down -- flagged
honestly below, not overclaimed.

**Step 1 -- `generate_flow()` implementation + SDK source review.**
Our own wrapper ([qmix_backend.py:182-205](../src/thermo_acoustic/qmix_backend.py:182))
is a thin pass-through: safety-ceiling check, then `pump.generate_flow(flow_rate)`
unconditionally. The real SDK implementation is present in this repo at
[qmix_sdk_for_codex/python/qmixsdk/qmixpump.py:222-230](../qmix_sdk_for_codex/python/qmixsdk/qmixpump.py:222):
```python
def generate_flow(self, flow):
    """
    Generate a continuous flow.

    A negative flow indicates aspiration and a positiove flow indicates
    dispension.
    """
    result = pump_api.LCP_GenerateFlow(self.handle, ctypes.c_double(flow))
    qmixbus.throw_on_error(result)
```
No duration/timeout/buffer-depth constant anywhere in this file or
`qmixbus.py`. `qmixbus.py` does define a `GuardEventId.heartbeat_err_occurred`
enum member (CANopen node-guard/heartbeat monitoring, a bus-level link
health mechanism) -- noted as background context, but not directly
implicated: our own polling (`read_fill_level()` every 3-15s) would have
kept real bus traffic flowing throughout, and no `DeviceError` was ever
raised by any call (confirmed via `log_call()`'s own re-raise-on-exception
behavior -- zero `FAIL` entries anywhere in either test).

**Step 2 -- fire-once vs. needs-re-issuing, and the original LabVIEW
implementation.** Two independent, decisive findings:
1. **`known_open_items.md`'s own existing research (Session-era finding,
   confirmed still accurate) already states:** *"Neither `GenerateFlow.vi`
   nor `ReferenceMove.vi` appears in `RunExperiment2.vi`'s call tree
   despite both VIs existing in `CetoniPump_class` -- confirmed
   manual-only/one-time-calibration tools in LabVIEW too, not gaps"*
   ([claude_code_change_log.md:410](../docs/claude_code_change_log.md:410)).
   The original LabVIEW software never used continuous `GenerateFlow` in
   its real automated experiment path either.
2. **Viewed the actual exported LabVIEW block-diagram screenshots**
   (`main_html/CetoniPump_lvclass_GenerateFlowd.png`/`d1.png`/`d2.png`,
   referenced from `labview_ports.py`'s own registry entry at
   [labview_ports.py:99](../src/thermo_acoustic/labview_ports.py:99)):
   the original VI is a **trivial single-call wrapper** -- extract pump
   handle, pass Flow Rate through to one SDK call node, done. No timer, no
   loop, no re-issue/keep-alive logic in either the "No Error" or "Error"
   case. The original LabVIEW implementation never re-issued it
   periodically either -- our Python port is a faithful, behavior-matching
   translation, not a regression.
3. **Confirmed in our own current codebase:** `generate_flow()` is
   reachable from exactly two places, both the *same* manual UI action --
   `qt_ui.py`'s "Generate Flow" button
   ([qt_ui.py:3046](../src/thermo_acoustic/qt_ui.py:3046)) and the
   equivalent `CETONI_GENERATE_FLOW` message handler
   ([application.py:650-652](../src/thermo_acoustic/application.py:650)).
   **The real automated path (`flush()`) never calls it at all** -- it
   calls `pump.set_fill_level()` (a bounded, target-based dosing command,
   architecturally different from `generate_flow()`) followed by
   `wait_for_pump()` ([application.py:381-390](../src/thermo_acoustic/application.py:381)),
   which polls `read_status()`/`is_pumping()` until it naturally becomes
   `False` or a timeout elapses -- **exactly the vendor SDK's own blessed
   usage pattern** (see Step 4 below). `flush()` was never exposed to this
   behavior in either implementation.

**Step 3 -- reproduction with dense polling.** Ran a second real-hardware
test: `generate_flow(-50.0)` once, then polled 4 signals together every
3s for 260s (past the ~225s stall point observed in the original soak
test), using a new diagnostic script (not part of the repo, scratchpad
only). **Result: could not reproduce a live transition this run** --
because the pump's fill_level had *persisted* at `0.18727791935442584 ml`
from the original soak test (confirmed: a real syringe pump's physical
plunger position doesn't reset just because the software disconnected/
reconnected), and `generate_flow(-50.0)` produced **zero movement from
the very first poll** (`is_pumping=False`, `flow_is=0.0` at t+0.0s,
unchanged for the full 260s). This is itself informative: whatever
stopped the original run is a **persistent, not transient, state** --
the pump doesn't "wake up" and resume on a fresh `generate_flow()` call
issued from a clean process. (A genuine "hard cutoff vs. gradual
slowdown vs. instant freeze" characterization of the *original* 0->225s
transition was not captured, since it happened during Task 3's own coarser
15s-interval polling and could not be re-triggered live this run --
flagged as a real limitation, not glossed over.)

**Step 4 -- SDK return/error codes and status flags, checked exhaustively,
not just the fill-level value.** Every call in both tests returned a
clean, error-free result (`throw_on_error()` never raised, confirmed via
zero `FAIL` log entries). Beyond `read_fill_level()`, checked directly
against the real device just now:
```
fill_level: 0.18727791935442584
is_in_fault_state: False
is_enabled: True
is_pumping: False
get_flow_is: 0.0
get_target_volume: 0.0
get_volume_max: 1.1780972450961724
get_flow_rate_max: 7316.420224360222
```
**No fault flag, device fully enabled, no error anywhere** -- the stop is
not a device error/fault condition, it presents as a clean, intentional
stop. `get_target_volume: 0.0` also confirms `generate_flow()` never sets
an internal target the way `pump_volume()`/`dispense()`/`aspirate()` do,
ruling out "it reached a target volume it was secretly given" as an
explanation.

Also found the vendor's own single-pump test suite
([qmix_sdk_for_codex/python/test_qmixpump.py:154-162](../qmix_sdk_for_codex/python/test_qmixpump.py:154)):
```python
def step12_generate_flow(self):
    print("Testing generating flow...")
    max_flow = self.pump.get_flow_rate_max()
    self.pump.generate_flow(max_flow)
    time.sleep(1)
    flow_is = self.pump.get_flow_is()
    self.assertAlmostEqual(max_flow, flow_is)
    finished = self.wait_dosage_finished(self.pump, 30)
    self.assertEqual(True, finished)
```
where `wait_dosage_finished()` ([test_qmixpump.py:65-79](../qmix_sdk_for_codex/python/test_qmixpump.py:65))
polls `pump.is_pumping()` in a loop and returns once it becomes `False`.
**The vendor's own test explicitly expects and asserts that a single
syringe pump's `generate_flow()` call naturally stops on its own within a
bounded window** -- this is documented, intended vendor behavior for a
single-syringe pump, not a malfunction. (The vendor's own *continuous*,
never-stops flow mechanism is a separate, different API --
`ContiFlowPump`, built from *two* syringe pumps alternately switched by a
valve specifically so one can refill while the other dispenses,
[test_contiflow.py](../qmix_sdk_for_codex/python/test_contiflow.py) --
our codebase has never used this class; `CetoniPump`/`QmixPumpBackend`
only ever wrap a single `qmixpump.Pump()`.)

**Step 5 -- re-issuing `generate_flow()` after the apparent stall.**
Re-issued in the same session, without disconnecting (`generate_flow(-50.0)`
called a second time). **Flow did not resume** -- `is_pumping`/`flow_is`
stayed at `False`/`0.0` for a further 60s of post-reissue polling.
**This directly favors Hypothesis A** (a persistent state, not a
transient one a simple re-issue clears) **and further weakens Hypothesis
B** (if only the *readback* were stale while motion genuinely continued,
a fresh `generate_flow()` call reaching a still-moving pump should still
show *some* signal of motion on the next `is_pumping()`/`flow_is()` poll
-- both are fresh bus queries each call, not a cached value; they stayed
flat too).

**Step 6 -- independent physical signal.** No camera is physically
positioned to observe the pump's plunger in this lab setup (the
Hamamatsu camera used elsewhere in this session is mounted for
microscopy/experiment imaging, not pointed at the pump) -- stated
explicitly, not glossed over, per instruction. **Given how decisively the
three independent SDK-level signals (`is_pumping`/`flow_is`/`dosed_volume`)
already agree with each other and with `fill_level`, and that a live
re-issue also failed to show any sign of motion, this software-only
evidence is already strong enough that the physical check was not judged
necessary to reach a confident conclusion** -- but if an even stronger
ground-truth confirmation is wanted, the minimal physical check would be:
photograph the syringe plunger position now (it should currently be
sitting at whatever position corresponds to `fill_level=0.1873ml`
aspirated from empty), then again after a *fresh* `generate_flow()` run
started from `fill_level=0.0` (requires first dispensing back down, a
real physical action -- not done in this pass) to visually confirm the
plunger really does stop moving at the same point.

**Residual open question (explicitly not resolved, not overclaimed):**
*why* does motion stop around `~0.1873 ml` specifically -- well short of
the syringe's own nominal reported `max_volume_ml=1.178ml` (~16% of
capacity)? Two explanations remain live, not distinguished by this pass:
(a) a genuine configured soft/mechanical travel limit for this specific
pump instance (e.g. a device-config-file setting narrower than the
syringe's nominal capacity) that the SDK enforces silently without
raising a fault; or (b) a time-based limit around ~225s independent of
volume -- **these two would be distinguishable by re-running at a
different flow rate** (a volume-based limit stops at the same volume
regardless of rate; a time-based limit stops at the same elapsed time but
a different volume) -- **not attempted in this pass**, flagged as the
natural next step if further precision is wanted, not guessed at here.

**Cross-check: any other real-hardware runs this session or in
`known_open_items.md`/changelog history that used long continuous flow
and might have silently hit this?** Checked, not assumed:
- Grepped the entire changelog and `hardware_tests/*.py` for every
  `generate_flow`/"Generate Flow"/`CETONI_GENERATE_FLOW` reference.
  **Confirmed: every prior real-hardware use of `generate_flow()` in this
  project's history was a brief manual click followed by an immediate
  `stop()`** (the flow-rate-safety-enforcement verification, the earliest
  real-pump-connection smoke check, and this session's own solo baseline
  timing -- all `generate_flow()` -> `stop()` within milliseconds, never
  sustained). **`hardware_tests/test_real_workflow_smoke.py` (the
  automated real-hardware verification script) never calls
  `generate_flow()` at all.**
- **Confirmed: Task 3's soak test (330s) was the first time in this
  project's entire history -- LabVIEW or Python -- that `generate_flow()`
  was ever run continuously for more than a few seconds.** No other
  already-completed real-hardware run was at risk of silently hitting
  this; it took a purpose-built long-duration test to surface it at all.

**Physical state note:** the real syringe currently sits at
`fill_level=0.1873 ml` aspirated (not returned to `0.0`) as a residual
effect of these investigation runs -- worth knowing/resetting before any
real experimental use of this pump.

**Not fixed, per instruction** -- this was root-cause isolation only. No
code changes were made or proposed in this pass.
