# Known Open Items

Canonical live holding list, not a narrative. It consolidates unresolved,
deferred, unverified, legacy, and manual-only items. Current source and targeted
tests remain authoritative for implemented behavior; this document records what
must not be treated as proven merely because a historical changelog says so.

`docs/legacy_unresolved_items.md` is a focused high-risk safety summary, not a
second canonical list. The historical migration and session documents are useful
evidence trails, but neither replaces checking the current working tree.
Concrete evidence requirements and later repair steps for the hardware-blocked
items are consolidated in `docs/hardware_repair_plan.md`; that plan does not
authorize hardware actions.

Status legend: **OPEN** (confirmed still true in current code/git history),
**RESOLVED** (confirmed fixed, cited), **STALE-IN-CHANGELOG** (changelog says
open but code/git shows resolved, or vice versa -- see Part 2 of the report
for the full list), **DESIGN FORK** (not a bug -- a genuine either-way
decision only the user can make).

The headings below deliberately separate four categories: active workflow
items that still need hardware confirmation; retained legacy/reference code;
manual-only probes that must never be mistaken for automated tests; and
historical notes. This document is a live issue register, whereas
`docs/claude_code_change_log.md` is historical only.

---

## Active workflow: unresolved hardware-confirmation items

- **Valve protocol position versus physical fluidic routing.** The serial
  protocol and status tokens confirm numeric positions `P01`/`P02`, but the
  current workflow and migration audits still record the physical routing as
  unverified. Current source/UI text deliberately labels controls only
  `P01`/`P02`; it does not claim a fluidic route for either numeric protocol
  position. Treat physical routing as an unresolved bench mapping until a
  controlled hardware check records what each position does; numeric protocol
  confirmation is not proof of fluidic semantics. A successful real serial
  write is now shown as `requested P01/P02; confirmation pending`; only a
  subsequent recognized `S` status reply restores `confirmed` state.
- **DIO0 (acoustic)/DIO1 (LED) relative timing never oscilloscope-verified.**
  Session 19/31/43. The DO-clock derivation (`_experiment_do_clock_config()`)
  is structurally wired from real UI values, but whether its physical timing
  actually matches LabVIEW has never been confirmed with a scope. Session 31
  added real per-frame `dcam_clock:` timestamp evidence (~0.0316s deltas,
  matching camera readout time, not the configured 0.2s DO-clock period) that
  is *consistent with* camera trigger source `"Internal"` free-running rather
  than being paced by the DO clock -- supporting evidence, not a resolution.
  The current experiment configuration creates DIO1 only and explicitly sets
  DCAM trigger source to `Internal`; it does not configure DIO0 or establish a
  physical camera-trigger line. `Camera Start` is therefore a programmed DO
  `sec_wait`, not a proven delay relative to the later `pc_trigger()` call.
  **Status: OPEN.**
- **Staged hardware-test confirmations are not global GUI interlocks.**
  `CONFIRM_REAL_HARDWARE` and timing acknowledgements protect action-capable
  modes in newer `hardware_tests/` scripts. They do not apply to the tracked
  `qt_ui.py`/`qt_ui_v2.py` GUIs (or to any local untracked v3 derivative):
  after real backends are initialized, manual WFG, pump, valve, and experiment
  actions can be invoked without those command-line gates.
  This is current reachable behavior, not proof that the actions are approved
  or physically verified. **Status: OPEN; needs an explicit operator-policy/
  UI-interlock decision.**
- **The visible `Abort` action is a graceful series-boundary request, not an
  emergency hardware stop.** It sets the shared stop flag and prevents the next
  repeat (or next TEC temperature point) from starting; the current unit runs
  through capture, AD2 wait, flush, and save. The v1 button, inherited v2 menu
  action, and Start-experiment tooltips now state that boundary. Local v3 work
  may inherit the same behavior but is outside the tracked runtime boundary.
  **Status:
  RESOLVED for wording; OPEN if a separate emergency-stop policy is desired.**
- **`qt_ui_v2.py` is an actively maintained transitional UI, not legacy or a
  simulated preview shell.** It remains opt-in and not independently
  hardware-verified, but it shares the real `Application` and hardware
  backends. Its initialization now delegates to `Application.initialize()`
  with progress reporting, removing the duplicate device-order/rollback loop.
  **Status: TRANSITIONAL, not the default launch target.**
- **Local v3 files are the active local layout-development direction, not part
  of the committed runtime boundary.** Commit
  `d180eea` intentionally removed `qt_ui_v3.py` and its launcher/test companions
  from tracking. Copies can remain in a developer working tree, but a fresh
  checkout does not contain or support a v3 entry point. **Status: LOCAL,
  UNTRACKED DEVELOPMENT MATERIAL; not independently hardware-verified.**
- **Local v3 inherited presentation coupling has been reduced without changing
  hardware behavior.** Initialization, status, acquisition, and MSO caption
  adaptations validate unique matches and assign stable v3 `objectName`
  values. The shared manual-WFG builder now assigns neutral stable IDs to its
  carrier, trigger, and FM labels; local v3 uses those IDs instead of walking
  the widget tree and rewriting matching substrings; the preview description
  likewise has a stable shared ID instead of relying on the first label in the
  group. **Status: RESOLVED FOR CURRENT V3 ADAPTATIONS IN THE LOCAL UNTRACKED
  WORKTREE; this does not promote v3 into the committed runtime boundary.**
  **Update (Session 102, 2026-08-06): NOT all v3 caption dependencies use this
  safer objectName pattern.** `_rename_unique_text_widget()`/
  `_rename_unique_group()` (still text-matching, by v3's own explicit design
  choice -- their docstring says "fail visibly if the v2 contract drifts") are
  still used for "Error Out", "Elapsed Time", "Time Left", "Camera FPS",
  "Camera Start (s)", "Dynamic Camera Start Time", and "Camera Start Array(s)".
  Session 102's caption renames of exactly these seven strings (Proposals 2-4)
  confirmed this mechanism working as designed: `MainWindowV3.__init__()` now
  raises `RuntimeError` immediately (all 14 `tests/test_qt_ui_v3.py` failures
  trace to the single "Error Out" case, since that rename is reached first in
  construction order -- the other six would fail the same way once that one is
  resolved). **This is not a v1/v2 defect and was not fixed as part of Session
  102** (out of scope for that pass, `qt_ui_v3.py` not modified there) -- it
  was confirmed, current, expected fallout of v1/v2 caption changes on v3's
  own chosen fail-loud contract. **Update (Session 103, 2026-08-06): fixed.**
  All seven `old_text` search keys updated to match Session 102's new v1/v2
  captions (`_v2_status_progress_group()`/`_v2_acquisition_group()`/
  `_global_status_panel()`); `new_text` (v3's own preferred wording) left
  unchanged in six of seven -- the "Error Out" case's own preferred wording
  now happens to be identical to v1/v2's new caption, kept as a same-text
  rename rather than removed, to preserve both the fail-loud check and the
  stable `objectName` assignment. `tests/test_qt_ui_v3.py`: 15/15 passing,
  confirmed stable across 3 re-runs. **Status: RESOLVED for this specific
  drift; the underlying still-text-matching (not objectName) mechanism for
  these seven remains, so a future v1/v2 caption change will break v3 the
  same way again** -- migrating them to the safer objectName pattern (like
  the WFG panel above) was explicitly out of scope for the Session 103 fix
  and remains open if wanted.

- **v1/v2-to-v3 process and object isolation boundary (Session 102
  investigation, 2026-08-06).** Established what v3 can and cannot safely do
  relative to v1/v2, and corrected an imprecise claim from the round-2 v3
  evaluation.
  1. **Process isolation: CONFIRMED, by construction, already the enforced
     boundary.** `launch_gui.bat`/`launch_gui_v2.bat`/`launch_gui_v3.bat` each
     invoke `"%PYTHON_EXE%" -m thermo_acoustic.qt_ui[_v2/_v3]` as a separate
     OS process (confirmed reading all three `.bat` files directly); each of
     `tools/run_ui*.py`/each module's own `main()` constructs exactly one
     window class. Separate OS processes have categorically no shared live
     Python/Qt object state -- a mutation in one process's widget cannot be
     observed by another process, full stop. **No code change is needed to
     enforce this; it already holds.** The only rule to state explicitly: v3
     must only ever be launched via its own dedicated launcher, never
     imported/instantiated in the same Python process as a real v1/v2
     session outside of this repository's own test suite or a knowing
     diagnostic script.
  2. **Correction to the round-2 audit's framing:** that evaluation described
     v3's `state["enable"].setText(...)` pattern as risking that "v1's own
     tabs would show the corrupted label afterward, in the same running
     session" -- **this overstated the risk.** `MainWindow._build_state()`
     (called exactly once per `__init__()`, confirmed at
     `qt_ui.py:652`) constructs a brand-new set of field widgets for
     *every* window instance, including every `QCheckBox` in
     `self.exp_ad2_channels`/`self.wfg_channels`. Two separate window
     objects -- even a `MainWindow()` and a `MainWindowV3()` constructed in
     the same process (e.g., in this repository's own test suite, which
     legitimately does this) -- never share the same widget instances. The
     real risk is scoped to *within a single v3 window instance's own
     lifecycle*: whether that one object's inherited-from-v1 dynamic
     relabeling logic and v3's own static relabeling logic (both touching
     the same widget because it genuinely is the same object, referenced by
     more than one of that instance's own tab-building methods) can disagree
     with each other over time. This is a v3-internal self-consistency
     question, not a cross-window-instance or cross-UI-version corruption
     risk.
  3. **Settings.json is the only confirmed real cross-process state carrier**
     (`SETTINGS_PATH` is one fixed path, shared by all three UI versions) --
     but it only ever persists field *values* (checked state, text/numeric
     content), never widget caption/label text, and this is the pre-existing,
     intentional point of a shared settings file (any two of v1/v2/v3 loading
     each other's saved settings is expected behavior, not a v3-introduced
     risk). No hidden state-sharing mechanism found beyond this.
  4. **Real hardware contention** (two processes both trying to control the
     same physical device) is a genuine risk, but pre-existing, general
     (applies equally to any two of v1/v2/v3), and already explicitly
     warned about in the Initialization dialog's own note ("Only one UI
     window should control real hardware at a time"). Not v3-specific.

  **Enforced boundary going forward:** v3 may only be launched via its own
  dedicated launcher, in its own process. Within that process, v3's own
  internal consistency (not fighting itself over a shared widget's caption
  text across its own construction/refresh methods) is v3's own concern.
  Settings.json sharing is intentional and value-only. No v1/v2 code
  protection is needed or was added.
- **The device whose own `initialize()` call fails is not part of any
  cross-device rollback.** (Cross-device rollback itself no longer exists as
  of the 2026-08-13 independent-per-device fix -- see
  `docs/hardware_repair_plan.md`'s "Initialization And Failure Recovery"
  section; earlier devices that succeed are never torn down because a
  later one failed.) Camera/Qmix/Piezo/TEC have varying degrees of local
  partial-initialize cleanup, but the failed device must clean up its
  own partial state. The current working tree has narrow local rollback for the
  confirmed gaps: Valve closes after a failed post-open handshake; CetoniPump
  closes after a successful backend open followed by failed fill-level
  readback; PiezoStage stops polling and shuts down after failed post-connect
  readback. Each preserves the primary error and reports cleanup errors too.
  AD2 assigns its handle only after its single checked open call succeeds;
  Hamamatsu and Qmix backends already own their partial-open rollback; TEC owns
  connect/status rollback and now bounds both that rollback close and direct
  cleanup through the shared timeout helper. See `docs/hardware_repair_plan.md`.
  **Status: CONFIRMED LOCAL GAPS RESOLVED IN THE CURRENT UNCOMMITTED WORKTREE;
  keep the ownership rule as a review requirement for new backends.**
- **GlobalExposure's disabled (`enabled=False`) DCAM behavior is
  implemented conservatively, not confirmed against real LabVIEW source
  (2026-07-31).** `HamamatsuDcamBackend.configure_trigger_global_exposure()`
  ([hamamatsu_dcam.py](../src/thermo_acoustic/hamamatsu_dcam.py)) sets
  the real DCAM property `DCAM_IDPROP_TRIGGER_GLOBALEXPOSURE`. The
  **enabled/true case is resolved and confirmed**: the real hardware VI
  (`Hamamatsu.lvclass:ConfigureSequence.vi`, not the trivial
  `Experiment2.lvclass:GetGlobalExposure.vi` getter) selects numeric value
  `5` for its true case, an exact match for
  `DCAMPROP_TRIGGER_GLOBALEXPOSURE__GLOBALRESET` in the vendored DCAM-API
  v4 header (`dcamsdk4/inc/dcamprop.h`) -- current code's `GLOBALRESET`
  for `enabled=True` is correct. **The disabled/false case remains
  genuinely unresolved**: LabVIEW's false-case value (`0`) is not a valid
  `TRIGGER_GLOBALEXPOSURE` enum member (valid range 1-5), and the
  property-ID constant visible at that same block-diagram call site
  (`2049680`/`0x1F4690`) does not match `DCAM_IDPROP_TRIGGER_GLOBALEXPOSURE`'s
  real v4 value (`2032384`/`0x1F0300`) or any other constant in the header
  -- a genuine discrepancy, not a misread (verified by pixel-level zoom).
  A dedicated search for a DCAM-API v3 header or a Hamamatsu
  version-compatibility document that might explain the numbering
  difference found nothing locally (this repo, and the separate
  `C:\git\thermacoustics` LabVIEW project repo, which has real `.vi`
  binaries but no exposed DCAM headers) or via web search; a second,
  independently-sourced DCAM-API v4 header (SLAC's public EPICS
  `ADOrcaUsb` module, a different SDK snapshot) has byte-identical
  constants for this property, weakening but not disproving a
  version-drift explanation. The actual DCAM call node at that site
  renders as an unreadable "?" icon in every exported diagram available
  in this repo -- a real export limitation, not something resolvable from
  available material. **Implemented fix (conservative, not a confirmed
  match):** `configure_trigger_global_exposure(False)` no longer calls
  `prop_setvalue()` at all -- it leaves the property at its prior/default
  state rather than actively setting a specific guessed "off" value (the
  previous code guessed `DELAYED`, never verified). This avoids risking a
  systematically-wrong exposure-timing mode for every future experiment,
  but it is a pragmatic choice, not a confirmed replication of LabVIEW's
  real behavior. **Revisit if/when direct access to the real, runnable
  LabVIEW application becomes available** -- the clean way to resolve this
  would be a live side-by-side: read `DCAM_IDPROP_TRIGGER_GLOBALEXPOSURE`'s
  actual value immediately after LabVIEW itself sets `globalshutter=False`
  on real hardware. **Status: OPEN** (false-case behavior only; true case
  is RESOLVED).
- **TEC real-path evidence remains unapproved, but the protocol mapping is no
  longer wholly unknown (independent audit 2026-08-05).** Commit `7c7e19f`
  contains an executable pyMeCom client plus
  Sessions 75-77 real-hardware claims, while
  `docs/legacy_unresolved_items.md` and older workflow text still say that no
  reviewed client/register map exists and real selection refuses before I/O.
  Source inspection independently confirms that the installed pyMeCom table
  and Meerstetter's official TEC-Family protocol agree with the five named
  IDs used by this client: 104, 105, 1000, 2010, and 3000. That does not
  independently establish the historical bench claims or safe real operation.
  **Model/firmware fit against the official protocol is now
  CLOSED** -- see `docs/tec_verification_matrix.md`'s "Model / Firmware /
  Protocol Compatibility Review" entry (TEC-1123-HV confirmed protocol-
  compatible with the rest of the TEC-Family, HV-specific parameters
  confirmed out of this integration's scope, firmware 5.10 meets the
  HV documentation's stated minimum). Also, `_PyMeComTecClient.write_config()`
  is a no-op and does not perform the vendor's separate flash-save operation.
  Keep TEC disabled/simulated and do not use the historical claims as
  authorization until a human review reconciles the implementation and bench
  record. **Status: OPEN for real operation; mapping source-checked;
  model/firmware fit CLOSED.**
- **Historical, unverified Meerstetter TEC session record (Sessions 75-77).**
  The following claim has not been independently verified in this audit and
  must not be read as current authorization for real operation: core path
  reportedly real-hardware verified, including `wait_until_stable()`'s own
  polling loop, plus a dual-channel lock/unlock scan UI. The real
  device (COM6, TEC-1123, HW 2.00, FW 5.10) has been connected to and
  both control loops individually confirmed with controlled write
  tests: channel 1 (Session 75) and channel 2 (Session 76) each showed
  genuine closed-loop thermal response to a target-temperature change,
  fully independent of the other channel. Session 77 additionally
  exercised `TecController.wait_until_stable()` itself (not a
  hand-rolled polling script) against real hardware on channel 1 --
  tolerance/settle-time/timeout logic confirmed working (target 25.65 C,
  converged and held within the requested 0.2 C tolerance, `ready=True`,
  no `error_state`, returned well inside the 60s bound). A real blocker
  bug found during Session 75 -- `_MECOM_PARAM_TARGET_TEMP` was
  `"Target Object Temp"`, but the real installed pyMeCom names parameter
  3000 `"Target Object Temperature"`, so every real write would have
  raised `UnknownParameter` -- was fixed and given a regression test
  that compares directly against the installed package's own parameter
  table. A second real finding -- Device Status (104)/Device Type (100)
  are device-wide "Common Product Parameters" on this hardware, not
  per-channel, confirmed both by the real protocol document's own
  section structure and a live instance sweep -- was also fixed in
  Session 76: `read_status()` now reads Device Status once (at
  instance 1) instead of once per channel, which is what broke
  channel 2's status reads originally. Scope loosened (user decision,
  Session 76): writes remain strictly limited to Output Enable Status
  (2010) and Target Object Temperature (3000), never any other
  parameter, never `*_raw`; reads are no longer restricted to a fixed
  parameter list, since a read cannot change device state.

  **Dual-channel lock/unlock temperature scan -- implemented
  (Session 77).** `TecController.apply_static_setpoint()`/
  `wait_until_stable()` now accept either a plain float (broadcast to
  every channel, original behavior) or a `dict[int, float]` (independent
  per-channel targets, polled genuinely simultaneously in one call, not
  one channel's full wait followed by the other's). `TemperatureSeries`
  gained an optional `temperature_points_ch2_c` (`None` = locked,
  unchanged default; a list = unlocked, same length as channel 1's
  series required). New UI: a lock/link toggle (Photoshop-aspect-ratio-
  lock pattern, plain checkable `QPushButton`, no new icon-asset
  pipeline) next to the CH1/CH2 temperature-points fields, shared by
  v1's tab and v2's page. Persisted via `tec_lock_channels`/
  `tec_points_ch2` in Save/Load Settings, tolerant-absent = locked.
  **The dict-target code path itself has only been fake/unit-tested,
  not yet exercised against real hardware** -- the single-float
  broadcast path it's built on has been real-hardware verified
  repeatedly, but a real two-simultaneous-different-targets run has not.

  **Error-state (Device Status == 3) surfacing -- investigated,
  accepted as a documented gap (Session 77).** Real hardware has never
  entered Error state, so `read_status()`'s Error-Number-read branch is
  fake-tested only. A real trigger exists in principle (Error Threshold
  parameters 4010/4011, an auto-reset feature at 6310) but deliberately
  tripping a real threshold risks a genuine fault with no confirmed
  in-scope recovery path (if auto-reset is disabled, recovery needs a
  `Device Reset` write, parameter 111, outside the 2-parameter writable
  scope) -- decided not to manufacture that risk for a one-line
  conditional already covered by fake tests; will get exercised for
  real if a genuine fault ever occurs during real use.

  See `docs/tec_verification_matrix.md` for the full verification
  matrix and `docs/claude_code_change_log.md` Sessions 75-77 for the
  complete real-hardware evidence trail. Both channels were left OFF
  (Output Enable Status = 0) at the end of every real-hardware session.
  **Historical claimed status, not independently verified:** core
  single-channel and per-channel read/write/enable path, and
  `wait_until_stable()`'s own loop, real-hardware verified on both channels;
  still open -- a real-hardware run of the new dict-target
  (genuinely simultaneous dual-channel) code path, a `wait_until_stable()`
  timeout/abort real-hardware pass, and error-state surfacing (accepted
  gap, see above, not planned).**
- **Camera trigger source Internal-vs-External unresolved.** Session 13
  hardcoded `"Internal"` to remove undefined-leftover-state risk; Session 19
  traced the real LabVIEW call chain (`RunExperiment2.vi` ->
  `CreateExperiments.vi` -> `Experiment2_Init.vi` -> `ConfigureSequence.vi` ->
  `tm_inputtriggersource_40.vi`) and confirmed the actual wired value is not
  recoverable from exported VI diagrams (compiled block-diagram wiring, not
  text) -- a genuine negative result, not a gap in effort. Needs oscilloscope
  verification, not fixable from software alone. **Status: OPEN.**
- **The manual Camera sequence controls are low-level operations, not a
  complete sequence-read workflow.** `start_capture()` starts the DCAM capture
  session and `sw_trigg()` sends a software trigger, but neither call transfers
  a resulting frame into the UI's `_last_camera_image_data` save buffer. That
  buffer is populated by the separate `Capture image` action; the save action
  writes only that buffer. V3 now says this explicitly and supplies a matching
  `Stop capture session` action using the existing `camera.stop_capture()` path. V1/v2
  retain their historical labels. **Status: OPEN as a feature-completeness
  item if triggered sequence readback is required; resolved for v3 wording and
  manual capture-stop access.**
- **DCAM frame timestamp clock domain unverified.** Session 8. Real per-frame
  timestamps are captured when the camera/driver reports support, but which
  clock (camera-internal vs. host-driver) produced them, and the epoch, is
  unconfirmed against real hardware or official SDK docs. **New supporting
  data, not a resolution (Part C, pending_feedback.md item 5):** a fresh
  3-frame real capture independently reproduced Session 31's exact finding
  -- per-frame `dcam_clock:` deltas (~0.03164s) match `read_readout_time()`
  (0.031645s) almost exactly, not the configured exposure time. Still
  doesn't answer *which* clock or *what epoch* -- needs official SDK
  documentation, not resolvable from a live test alone. **Status: OPEN.**
- **Pump flow-rate hardware-safety enforcement relies on unconfirmed
  stepper-stall behavior.** Session 51. `generate_flow()` now rejects rates
  exceeding the device's own reported `max_flow_rate_ul_min` (real-hardware
  verified, commit `23e17d5`) -- but *why* exceeding that limit was
  historically believed safe (open-loop steppers stall/skip steps rather than
  break) was never confirmed against CETONI's own documentation; the
  session's own research called this "probably safe by stepper-motor physics,
  not confirmed by vendor documentation." The enforcement itself is now real
  and hardware-verified; the *original justification for treating an
  unenforced excess as low-risk* remains uncited. **Status: OPEN** (as a
  documentation/citation gap, not as an enforcement gap -- the enforcement
  itself is resolved).
- **Syringe max_piston_stroke_mm ceiling (65mm) is a fixed vendor-manual
  value, not live-readable.** Session 51. Sourced from CETONI's Low Pressure
  Hardware Manual Section 5.1, NEM-B101-02 E -- this specific pump module's
  real mechanical travel limit, independent of whatever syringe is mounted.
  No live device readback exists for this parameter (unlike
  `max_flow_rate_ul_min`, which is read back after `set_syringe_param()`
  succeeds), so the bound is hardcoded and must be manually re-verified if
  the physical pump module is ever swapped for a different model.
  **Status: OPEN by design** (see `docs/hardware_safety_patterns.md` pattern
  (d) for why hardcoding was the correct choice here, not a shortcut).
- **AD2 amplitude/frequency bounds checking -- flagged open in the
  changelog's own "Known remaining" list (Session 9), but actually RESOLVED
  since (Session 51, commit `23e17d5`).** `configure_wfg()` now reads the
  device's own live `AnalogOutNode*Info()` range and clamps before every
  `Set` call, setting `WfgChannelConfig.out_of_range` (surfaced in the UI
  status line and TDMS metadata). Verified against a real Analog Discovery 2:
  accept path applies as requested, reject path clamps to the real device
  ceiling. **The changelog's summary section (`## Known remaining open items
  as of this writing`, pre-dating Session 45) was never updated to reflect
  this -- see Part 2 of the report.** **Status: RESOLVED**, changelog
  stale on this point.
- **AD2 device detection depends on knowing the correct USB VID.** Session 51
  (post-commit follow-up). This specific lab's Analog Discovery 2 enumerates
  via an FTDI bridge chip (`VID_0403&PID_6014`), not Digilent's own
  `VID_1443` -- a Device-Manager-based "is it connected" check must search
  for the right VID or it will falsely conclude the device is absent (this
  happened once during this project's own verification work and was
  corrected). Not a code gap; a documented gotcha for future hardware
  troubleshooting. **Status: OPEN** (as a documentation note, not a bug).
- **Several Category-A/LabVIEW-migration items remain fake-tested only, not
  hardware-verified:** ~~abort concurrency~~, ~~Qmix bus close on init
  failure~~, serial read/write timeouts, ~~the AD2 SDK clock-divider wiring
  in `waveforms.py`'s `configure_do()`~~, and the TDMS metadata *content*
  itself (no real npTDMS-vs-LabVIEW file comparison has ever been
  performed, though the write-verification *mechanism* was independently
  confirmed against a real npTDMS install in Session 27). **Two items
  hardware-verified (Part C, pending_feedback.md item 5):** Qmix bus close
  on a real, deliberately-caused init failure left `bus`/`pump` both `None`
  and a follow-up real `initialize()` succeeded cleanly; the AD2
  clock-divider math was confirmed against the real internal clock
  (100MHz) with an exact-frequency real hardware write. **"Abort
  concurrency" struck (Session 78): the concurrent-QThread hard-stop race
  this item originally referred to (`_abort_hardware()` racing against the
  in-flight repeat's own thread) no longer exists -- Abort was a real
  safety-behavior change to never touch hardware concurrently at all, so
  there is nothing left to hardware-verify under that name.** Serial
  read/write timeouts remain fake-tested only (not attempted this pass,
  time-boxed). **Status: OPEN** (serial timeouts, TDMS content
  comparison).
- **"Analog Discovery 3" row label** (`qt_ui.py:504`, `qt_ui.py:1395`,
  confirmed still present in current code) is the only place calling this
  device generation "3" -- everywhere else says "2". `docs/PORTING_TBD.md`
  separately references real "AD2/AD3" validation hardware, so this may be
  a deliberate label for a second, newer unit this lab has, not a typo.
  Session 39 flagged this as a genuine fork needing the user's own knowledge
  of lab hardware, not a code decision. **Status: DESIGN FORK, unresolved.**
- **Z stage backend selection has no real effect -- the underlying
  PriorZMotor/COM7 path itself is now retired (pending_feedback.md item
  5, Part B1).** `hardware_factory.build_hardware_bundle()` never read
  `config.z_backend`; enabling "Z stage" used to always build a
  Prior-serial `PriorZMotor` regardless of the UI's (already-disabled)
  backend combo. Session 39; escalated to a real bug report (pending_feedback.md
  item 4) confirming `COM7` never existed on this lab's hardware, so the
  checkbox was guaranteed to fail. Fixed: the Initialize dialog's
  "Z-stage" checkbox now connects to the real Thorlabs piezo
  (`thorlabs_piezo.PiezoStage`, the same connection the Z-Scan tab
  already uses) via a new `ZStage` adapter, replacing `PriorZMotor`
  entirely. `z_backend`'s combo (and `thorlabs_apt_backend`/
  `thorlabs_apt_discovery_only`) remain unwired -- there is now only one
  real backend, so backend *selection* still has no effect by design, not
  by gap. **Status: RESOLVED** (the wrong-device bug); **OPEN by design**
  (the backend-selection combo itself, since only one backend exists).
- **PPC001 Z-scan remains a manual Kinesis calibration-motion path, not a
  discovery-only feature.** Passive `thorlabs_apt.py` discovery is separate.
  Connecting or observing ClosedLoop mode does not itself authorize movement:
  the Z-Scan GUI and CLI require a distinct affirmative motion authorization
  before a calibration scan. **Status: ACTIVE MANUAL-ONLY SAFETY BOUNDARY.**

## Active workflow: communication reliability items

- **`SerialTextCommandBackend.query()` uses pyserial's `readline()`, which
  splits on `\n`, but every device confirmed to talk to it (the valve) only
  ever terminates a response with `\r`.** Since `readline()` never sees the
  terminator it's actually looking for, every single query blocks for the
  *entire* configured `timeout_s` before returning, regardless of how
  quickly the real device actually responded -- this is a genuine backend
  bug, not "the device is slow." **Confirmed on real hardware (Session
  54):** a direct timing characterization of the valve's `S\r` status
  query showed a correct, consistent response (`b'01\r'`) every time, but
  each call took the *entire* configured timeout window to return
  (~5.02-5.03s against a `timeout=5.0` call, repeatably; a `timeout=1.0`
  call returned nothing and made `Valve.initialize()` fail outright) --
  the signature of "blocks until timeout, not until response," not "the
  device needs N seconds to answer." **Affects every caller of
  `SerialTextCommandBackend.query()`**, not just this one probe --
  `Valve.initialize()`, `Valve._apply_status_response()`'s call sites,
  and critically `Valve.wait_until_ready()`'s own poll loop, which has
  likely been silently paying the full per-call timeout cost on every
  single iteration for its entire existence, not occasionally -- its real
  elapsed time before giving up is likely far longer than its own nominal
  `timeout_s` parameter would suggest. May retroactively explain prior
  "valve seems slow" observations from earlier real-hardware sessions
  that were never root-caused before now. **Fix direction:** replace
  `self.port.readline()` in `query()`
  (`instruments.py:SerialTextCommandBackend.query()`) with a real
  `\r`-terminated read (e.g. pyserial's `read_until(expected=b"\r")`),
  matching this codebase's own documented `line_ending = "\r"` *write*
  convention instead of contradicting it on the *read* side. **Fixed
  (Session 55):** `query()` now calls `self.port.read_until(expected=
  self.line_ending.encode("ascii"))`, confirmed against the actually
  installed pyserial version (`3.5`, via `pip show` + `inspect.getsource`
  -- `read_until`'s `expected` keyword is correct for 3.5+, `terminator`
  for older versions) rather than assumed. Regression test added
  ([tests/test_instruments.py](tests/test_instruments.py)), verified to
  fail against the old `readline()`-based code before the fix landed.
  **Status: RESOLVED, hardware-verified (Part C, pending_feedback.md item
  5).** Timed a real `query('S')` against the real valve on COM5: 16ms,
  not the pre-fix ~5s full-timeout block.

## Active workflow: data-integrity items

- **TDMS write verification's own field-count/content assertions are
  lightweight by design, not comprehensive.** Session 26/27 added a size
  check + npTDMS reopen + key-presence check (not a full value-by-value
  round trip), and independently confirmed this works against the real
  npTDMS 1.11.0 package (Session 27) -- but no real npTDMS-vs-real-LabVIEW
  file comparison has ever been performed. **Note: an earlier Session 9
  entry in the same changelog says this gap was "flagged but intentionally
  not fixed in any subsequent session" -- that line is now stale/incorrect
  relative to the same document's own later Session 26 entry; see Part 2 of
  the report.** **Status: RESOLVED** (the mechanism), **OPEN** (real-LabVIEW
  content comparison never done).
- **Pump flow-rate sign convention is documented by the bundled CETONI/Qmix
  Python wrapper.** `qmix_sdk_for_codex/python/qmixsdk/qmixpump.py` documents
  `generate_flow()` as negative = aspiration and positive = dispension. The
  Pump&Valve UI uses the same convention and no sign inversion occurs in the
  Python path. This establishes the software convention; physical tubing
  direction remains setup-dependent. **Status: RESOLVED (software sign
  convention).**
- **Nonpositive flush flow is not a second routing mode.** `flush()` lowers the
  target fill level and therefore uses the positive Qmix dispense convention;
  its timeout formula is defined only for a positive rate. The current working
  tree rejects zero and negative values before any valve or pump call, while UI
  spin boxes retain zero only as an unset/default-disabled value. Negative
  manual pump flow remains available through the separate manual flow control
  where it means aspiration. **Status: RESOLVED IN SOFTWARE; no hardware action
  was needed or justified to decide this boundary.**
- **`CetoniPump.fill_level` has no readback/sync mechanism, so it always
  starts at `0.0` in a fresh process regardless of the real device's actual
  loaded volume.** No method anywhere in the pump path calls the real Qmix
  SDK's `get_fill_level()` to sync the tracked Python-side value against
  hardware state -- `refill()` only ever set a full-capacity value (and, until
  Session 57, an arbitrary hardcoded `1.0` at that -- see below), it did not
  read back the true current level, and nothing ran at
  `Application.initialize()` time to reconcile the two. **Confirmed on real
  hardware (Session 54):** a fresh process's `pump.fill_level` read `0.0`
  immediately after `initialize()` while the real syringe still had
  approximately `0.05` ml physically loaded from a prior session; the
  mismatch was worked around manually for that session only by calling the
  real SDK's `get_fill_level()` directly and assigning the result onto
  `app.pump.fill_level`. **Consequence:** this fails safe, not unsafe --
  Session 53's own `flush()` fix (`application.py`) now rejects any flush
  volume exceeding the tracked fill level, so a stale `0.0` just makes
  `flush()` wrongly refuse a legitimate flush after any app restart with
  partial volume already loaded, rather than over-drawing the syringe. It is
  a usability/correctness gap, not a hardware-safety regression, but it will
  recur on every restart until fixed. **Fixed (Session 56):**
  `QmixPumpBackend.read_fill_level()` wraps the SDK's `get_fill_level()`;
  `CetoniPump.initialize()` now calls it right after `backend.initialize()`
  succeeds and syncs `self.fill_level` from the real reading (only when a
  real backend is present, never for a simulated pump). Deliberately
  placed inside `CetoniPump.initialize()` rather than
  `Application.initialize()`, keeping `application.py` -- which at that time
  carried a separate uncommitted TEC diff -- untouched. Regression tests added
  ([tests/test_application.py](tests/test_application.py)), verified to
  fail against the old code before the fix landed. **Status: RESOLVED,
  hardware-verified (Part C, pending_feedback.md item 5).** Confirmed
  `read_fill_level()` genuinely executes against the real Qmix pump right
  after `initialize()` (the mechanism, not just the fake backend) --
  logged in `hardware_transactions.log` immediately after a real
  `initialize()` call. **Session 57 closed a
  related, separately-discovered gap in the same method family:**
  `CetoniPump.refill()` itself still hardcoded `self.fill_level = 1.0`
  after calling `backend.refill()`, regardless of the syringe's real
  capacity -- found during a code-health audit (finding 5a), not this
  entry's own original scope. Fixed the same way: syncs from
  `backend.read_fill_level()` for the real-backend path; the simulated
  (`backend=None`) path now derives from a new `max_volume_ml` field
  (defaulting to `1.0` for backward compatibility) instead of an
  unconditional hardcoded value. See the Session 57 changelog entry for
  full detail.
- **`CetoniPump.referenced` was set `True` by `initialize()` even though
  `initialize()` never performs a physical reference/homing move --
  fixed (2026-07-31).** Found while live-testing the real pump: a
  real-hardware timeout (`0x642 ERR_DS402_TIMEOUT_STATUSWORD`) on
  `set_fill_level()` traced back to the pump's incremental encoder never
  having been referenced (`is_position_sensing_initialized()` reading
  `False`) -- the SDK's own header documents this as a genuine
  prerequisite for "dosing" commands (`set_fill_level()`/`pump_volume()`/
  etc.), which only `CetoniPump.reference_move()` (calling `calibrate()`)
  actually performs, gated behind the UI's manual "Reference move"
  button. `initialize()` itself never calls `reference_move()`, yet
  unconditionally set `self.referenced = True` at the end of a plain
  connect -- misleadingly claiming a reference move had happened when it
  never did. **Fixed:** `initialize()` no longer touches `referenced` at
  all; only `reference_move()` sets it, and only after
  `QmixPumpBackend.reference_move()` returns without raising (it already
  polls `is_calibration_finished()` to confirm before returning).
  **Side effect caught by the full test suite, also fixed:**
  `qt_ui_v2.py`'s pump connection-status row was reading `referenced`
  (not `initialized`) to decide "Connected"/"Not connected" -- with the
  flag now correctly `False` after a plain connect, this would have
  wrongly shown "Not connected" for a genuinely-connected-but-unreferenced
  pump. Added a new `CetoniPump.initialized` field (mirrors
  `Valve.initialized`'s existing pattern) set unconditionally at the end
  of `initialize()`, and repointed the UI to it -- separating "did
  `initialize()` succeed" from "was a reference move confirmed," two
  genuinely different questions that had been conflated under one flag.
  2 new tests in `tests/test_application.py`
  (`test_cetoni_pump_initialize_does_not_falsely_claim_referenced`,
  `test_cetoni_pump_reference_move_sets_referenced_true`). Full suite
  green, 369/369 at the time of the fix. **Status: RESOLVED, committed in
  `17f24dd`.**
- **`vci4109w5.sys` (IXXAT VCI4 USB-to-CAN adapter driver, used by the
  Qmix pump's CANopen bus) BSOD'd three times in one session during
  real-hardware pump diagnostics (2026-07-31) -- root-caused and
  resolved, documented here for future reference if it recurs.** All
  three crashes shared bugcheck `0x1e` (KMODE_EXCEPTION_NOT_HANDLED,
  `STATUS_ACCESS_VIOLATION`) inside `vci4109w5.sys`, confirmed via
  Windows Event Viewer (`System` log, events 1001/1019, each pointing at
  this driver by name). **Root cause:** the installed driver version was
  `4.0.115.0` (dated 2018) -- an old release with a documented
  vendor-side compatibility issue. **Resolution:** updated the driver to
  `4.0.131.0` (dated 2022, HMS Industrial Networks); confirmed installed
  and active via `Get-CimInstance Win32_PnPSignedDriver` after the
  update, no recurrence since. Investigation before the fix (event-log
  correlation, command-frequency audit comparing today's diagnostic
  scripts against production polling rates) found the diagnostic
  activity was *not* unusually fast (production's own `wait_for_pump()`
  polls at 20 Hz; the diagnostic scripts used 0.33-2 Hz) -- the crashes
  were a genuine outdated-driver bug, not caused by hammering the bus
  too fast. **Status: RESOLVED.**
- **Current Qmix initialization is blocked by a relatching CAN transmit
  queue fault (2026-08-05).** A minimal read-only bus session found
  `is_in_fault_state=True` while `read_last_error()` initially returned
  code `0` (all prior errors resolved). One guarded `clear_fault()` was
  issued only after confirming the pump was disabled and stopped; the
  fault cleared without movement. On the next read-only bus reconnect it
  immediately relatched as code `33279` (`0x81FF`), whose Qmix SDK text is
  `CAN Tx Queue Overrun`. The pump remained disabled, stopped, position
  sensing initialized, and at the same reported fill level. Automatic
  fault clearing remains prohibited; inspect the CAN adapter/bus and the
  controller event state in QmixElements before treating real pump
  initialization as trustworthy. **Status: OPEN; needs hardware/CAN-bus
  diagnosis.** **Session 104 (2026-08-06) added a manual, operator-only
  escape hatch** (`QmixPumpBackend.clear_fault_and_reinitialize()` ->
  `CetoniPump.clear_fault_and_reinitialize()` ->
  `Application.clear_pump_fault_and_retry()` -> qt_ui.py's "Pump Fault
  Recovery (advanced)" button, gated behind a non-skippable warning
  dialog) for a deliberate, traceable recovery attempt; it is not evidence
  that the bus-level fault is resolved or that real pump use is approved.
  Automatic fault clearing is still prohibited everywhere else;
  `initialize()` itself is unchanged.
  Every manual clear is recorded in the live status log and in
  `data.tdms` (`PumpFaultManuallyCleared`). This does not change the
  status of the underlying fault itself, which remains OPEN.
- **Automatic controlled reconnect is not justified by the current Qmix CAN
  evidence (2026-08-12).** QmixElements reproduces the transient sequence, so
  an eventual reconnect would not distinguish a healthy Python connection from
  adapter/bus instability. `QmixPumpBackend.initialize()` receives general SDK
  exceptions rather than a reliable transport-only classification; retrying
  them would also retry configuration, lookup, and other unsafe-to-mask failures.
  A delayed one-shot reopen before enable/motion would be mechanically narrow,
  but would still conceal an intermittent bus condition without proving it is
  safe. Keep one fail-closed initialization attempt, no automatic fault clear,
  and the existing explicit operator action as the only recovery exception.
  **Status: OPEN; requires CAN/adapter diagnosis and clean repeated evidence
  before reconsidering an automatic policy.**
- **Qmix project identity and stored bus settings are now separated from live
  bus diagnosis (2026-08-12).** `hardware_config.py` selects the one-pump
  project under `video paper 2\\Paper 2 slow flow\\Configurations`; its XML
  files are byte-identical to the separately retained
  `Desktop\\Franzi\\Cetoni_1pump_config_FM` copy. The project records
  `CANopenBus1`, `1000` kbit/s, a `1000` ms bus heartbeat, node `2`, and
  configured producer/consumer heartbeat entries. This rules out divergence
  between those two stored project copies as an explanation, but it does not
  establish the VCI adapter's live bitrate, bus state, ownership, error
  counters, or heartbeat traffic. **Status: OPEN, narrowed next evidence:
  capture QmixElements/VCI diagnostics for the active project and compare
  their live adapter/bus state with these stored settings before changing
  Python behavior.**
- **QmixElements/VCI first-site evidence narrows the fault ordering
  (2026-08-12).** With no Python, LabVIEW, or QmixElements client running,
  the host exposed one running automatic service, `VciDevService`, for a
  `VCI4 USB-to-CAN compact` adapter (HMS signed driver `4.0.131.0`, dated
  2022-07-11; installed VCI package `4.0.1374.0`). QmixElements' active
  project is `Paper 2 slow flow`. Its diagnostic log records node `2`
  emitting `0x8120` (CAN Error Passive), then `0x8130` (Life
  Guard/Heartbeat Error), then `0x81FF` (CAN Tx Queue Overrun) in the same
  millisecond; the 2026-08-12 15:25 occurrence logged a clean `0x0000`
  recovery about 1.25 seconds later. This supports treating `0x81FF` as a
  downstream result of a transient CAN communication failure, rather than a
  primary pump-motion fault or a Python cleanup artifact. A QmixElements UI
  launch alone produced no bus operation. **Status: OPEN, now prioritized as
  physical CAN link/adapter path or live heartbeat traffic; collect VCI
  error counters and inspect cable, connector, termination, power, and node
  traffic before any Python or automatic-recovery change.**
- **The current VCI driver is present but does not supply live bus evidence
  (2026-08-12).** Windows reports the identified adapter's Plug-and-Play
  status as `OK`. The recent System log contains three `vci4109w5.sys`
  bugchecks immediately before installation of the current VCI device service
  and signed driver; no later matching VCI/IXXAT event appeared in the
  60-day query. This makes a *current* repeated driver crash unproven, not a
  resolution of the CAN fault. `canAnaMini` is installed, and its vendor
  manual says TX-passive mode is hardware listener-only, but no existing
  analyzer profile proves that mode is selected. Do not open it with unknown
  defaults. **Status: OPEN, smallest safe next diagnostic is a manually
  configured TX-passive trace/counter capture with all other clients closed.**
- **A disabled-but-real instrument's per-step hardware calls were handled
  inconsistently -- `AD2Sdk` silently skipped them (while falsely reporting
  success), `HamamatsuCamera`/`CetoniPump`/`Valve` attempted them anyway --
  fixed (2026-07-31), found by a full-project silent-failure audit.**
  `AD2Sdk.pc_trigger()`/`config_wfg()`/`config_do_clock_special()` each
  checked `if handle is not None` before touching hardware, but
  unconditionally treated the call as successful either way --
  `pc_trigger()` set `self.triggered = True` even when the real trigger was
  never sent. Confirmed reachable from the real automated path: a real
  (non-simulated) `AD2Sdk` with `enabled=False` is directly constructible
  from the Initialize dialog (uncheck "AD2" while leaving "Simulate AD2"
  unchecked), and `run_experiment2()` never checked `ad2.enabled` before
  calling these -- an existing test (`test_run_experiment2_records_
  simulated_vs_real_instruments_in_final_tdms`) already exercised exactly
  this combination and passed, because nothing asserted the trigger
  actually happened. Camera/Pump/Valve had the mirror-image bug: their
  methods checked `backend is not None`, not `enabled`, so a
  disabled-but-not-simulated instance would still attempt real hardware
  (failing loud if the device wasn't there, rather than silently, but
  still inconsistent with what "disabled" should mean). **Fixed by moving
  the enabled/disabled decision to the orchestrator**
  (`Application.run_experiment2()`), applied uniformly to all four
  instrument types -- each step now explicitly checks the relevant
  instrument's `enabled` before calling into it, skipping (and firing a
  status event) instead of calling through when disabled. `AD2Sdk.pc_trigger()`/
  `config_wfg()`/`config_do_clock_special()` now raise a new `AD2SdkError`
  if ever reached with a `None` handle, since after the orchestrator fix
  that indicates a caller bug, not a legitimate disabled state to absorb.
  Flush (pump + valve together) is skipped as a unit when either is
  disabled, since a flush isn't meaningful with only one of the two.
  8 new tests in `tests/test_application.py`, using a shared
  `_PoisonBackend` (raises on any attribute access) to prove the disabled
  instrument's backend is never touched at all, not just that the call
  happens to no-op safely. See the Session 61 changelog entry for full
  detail. **Status: RESOLVED, committed in `17f24dd`.**
- **`data.tdms` never recorded whether an instrument was genuinely
  enabled/disabled for a run, only whether it was simulated -- fixed
  (2026-07-31), same audit as above.** `SimAD2`/`SimCamera`/`SimPump`/
  `SimValve` (Finding B, prior session) distinguish simulated-vs-real but
  say nothing about enabled-vs-disabled -- a run with AD2 genuinely
  disabled and a run with it fully active were structurally identical in
  the saved record. **Fixed:** four new `Experiment2` fields
  (`ad2_enabled`/`camera_enabled`/`pump_enabled`/`valve_enabled`, read from
  live instrument state the same way `sim_*` already is) now write
  `AD2Enabled`/`CameraEnabled`/`PumpEnabled`/`ValveEnabled` into
  `data.tdms` alongside the existing `Sim*` fields. **Status: RESOLVED,
  committed in `17f24dd`.**
- **`generate_flow()`'s "continuous" flow genuinely stops on its own after
  a bounded real run -- confirmed intentional single-syringe-pump SDK/
  device behavior, not a bug, not readback staleness (pending_feedback.md
  item 6, Task 3 + priority follow-up investigation).** Originally found
  by a 5.5-minute real-hardware soak test: `generate_flow(-50.0)` (aspirate)
  called once, `read_fill_level()` rose smoothly for 225s then froze
  bit-for-bit for the remaining 105s, with zero error anywhere. A
  dedicated follow-up investigation **distinguished the two live
  hypotheses with direct evidence, not speculation:**
  - **Confirmed (Hypothesis A): the pump physically stopped moving.**
    Three SDK signals independent of `get_fill_level()`'s own code path
    (`is_pumping()`, `get_flow_is()`, `get_dosed_volume()`) all
    corroborate "genuinely not moving," both immediately and after
    re-issuing `generate_flow()` in the same session (flow did not
    resume). `is_in_fault_state()` is `False` and the pump remains
    `enabled` throughout -- the stop is clean/intentional, not an error
    condition.
  - **Refuted (Hypothesis B): not a stale readback.** If only the
    readback were stale while motion genuinely continued, a fresh
    `is_pumping()`/`get_flow_is()` poll (each a real, independent bus
    query, not a cached value) should still have shown motion. It never
    did, in either test.
  - **Confirmed intentional, cited from the vendor's own test suite**
    ([qmix_sdk_for_codex/python/test_qmixpump.py:154-162](../qmix_sdk_for_codex/python/test_qmixpump.py:154)):
    the vendor's own `step12_generate_flow()` test calls `generate_flow()`
    then explicitly *expects and asserts* it naturally completes within a
    bounded window (`wait_dosage_finished()`, polling `is_pumping()` until
    `False`) -- documented vendor behavior for a single syringe pump, not
    a malfunction. True indefinite continuous flow requires the SDK's
    separate `ContiFlowPump` class (two syringes alternately switched by
    a valve so one refills while the other dispenses) -- never used by
    this codebase, which only ever wraps a single `qmixpump.Pump()`.
  - **The original LabVIEW software never used continuous `GenerateFlow`
    in its automated path either** -- already-established finding
    (`GenerateFlow.vi` absent from `RunExperiment2.vi`'s call tree,
    manual-only) independently re-confirmed by viewing the actual
    exported block-diagram screenshots (`main_html/CetoniPump_lvclass_GenerateFlowd*.png`):
    a trivial single-call wrapper, no timer/loop/re-issue logic. The
    Python port is a faithful translation, not a regression.
  - **The real automated `flush()` path was never exposed to this at
    all** -- it calls `set_fill_level()` (a bounded, target-based dosing
    command) + `wait_for_pump()` (polls `is_pumping()` until naturally
    `False`, the SDK's own blessed pattern), never `generate_flow()`.
    `generate_flow()` is reachable only from the manual "Generate Flow"
    UI button/message, never from an automated run.
  - **Cross-checked, not assumed: no other real-hardware run this
    session or in project history used continuous `generate_flow()` long
    enough to have silently hit this before** -- every prior use was a
    manual click followed by an immediate `stop()` (milliseconds); the
    automated real-hardware smoke script never calls it at all. This
    soak test was the first sustained continuous use in the project's
    history, LabVIEW or Python.
  - **Proximate mechanism (volume-based vs. time-based) -- RESOLVED
    (2026-07-31), by re-running at a different flow rate as this
    document's own previous version proposed.** Two real-hardware data
    points, collected before the run was interrupted (see the CAN-driver
    incident item below): `generate_flow(-50.0)` stopped at **225.05s /
    0.187290 ml**; `generate_flow(-100.0)` (double the rate, from a
    freshly-reset 0.0 ml start) stopped at **114.05s / 0.187290 ml** --
    the exact same stop *volume*, bit-for-bit, at a stop *time* that
    roughly halved when the rate doubled. That is precisely the
    volume-based signature (a time-based limit would have stopped both
    runs at ~225s, at different volumes) -- **confirmed volume-based, not
    time-based.** A third rate (-150) and the separate dispense-to-limit
    characterization (Part 4 of that session's task list) were never run
    -- deprioritized, not just interrupted: the real experiment/flush path
    never uses `generate_flow()` at all (see above), so a third
    confirmatory data point and the dispense-direction limit-strike
    behavior have no bearing on real experiment correctness. Not pursued
    further. **Status: RESOLVED** (both which-hypothesis-stops-it and
    volume-vs-time-based); still **OPEN by design, not urgency:** the
    exact real-world cause of the ~0.1873ml ceiling itself (e.g. a
    configured soft/mechanical travel limit narrower than the syringe's
    nominal capacity) was not independently identified -- moot for the
    same reason above.
- **A pump-move timeout previously reported failure without requesting a
  stop (fixed in the current working tree, 2026-08-05).** `wait_for_pump()`
  returns `False` only when its last status poll still reports pumping.
  `refill()`/`empty()`/`go_to_level()` and `flush()` now call the existing
  SDK-backed `pump.stop()` before resynchronizing fill level and reporting the
  timeout. Fake-only tests cover the stop request. This does not resolve the
  separate bench question of how quickly the real device physically stops,
  provide independent post-stop motion confirmation, or make a vendor SDK call
  already blocked inside `stop_pumping()` cancellable.
- **Syringe stroke length is a derived value, not an independently-sourced
  BD spec figure.** Session 17. Computed as `volume / cross-sectional area`
  assuming full nominal volume over full piston travel in a cylindrical bore
  -- no authoritative BD stroke-length figure was ever available to verify
  this assumption against. The three named presets' *inner diameters* (BD
  1/5/10mL) are confirmed against BD's published spec and, as of this
  session's own work, now cross-checked against the Chemyx BD Plastic
  Syringe reference table and BD REF 309628/309649/300912 packaging
  (`qmix_backend.py`'s `SYRINGE_PRESETS` comment). **Status: OPEN** (stroke
  derivation only; diameters are resolved).
- **Save/Load Settings persistence gap-closure -- RESOLVED, all 4 batches
  complete (2026-08-04/05).** Session 39, Frequency Scanning specifically
  closed Session 44. A
  dedicated audit (2026-08-04) re-confirmed via git history that
  `schema_version` has only ever gated the Hz->kHz unit migration
  (commit `f569143`), never a broader persistence effort, and traced the
  real current gap precisely: WFG's `wfg_running`, the entire Pump&Valve
  and Camera tabs (including the Session-22 load-bearing Sequence
  cluster), the entire Z-Scan tab, and several Experiment-tab fields
  (Camera FPS/Start/Array, Dynamic Camera Start Time, GlobalExposure, FM
  Sweep) were all confirmed still genuinely absent from
  `_settings_dict()`/`_load_settings()`. Also found `fill_flow_rate`
  specifically was the subject of an earlier explicit instruction to
  persist it that was never actually executed (confirmed via grep --
  no key, no round-trip test -- not a memory error). **Batch 1 (same
  day) closed the Pump&Valve manual tab**: `syringe`,
  `custom_syringe_volume_ml`, `custom_syringe_inner_diameter_mm`,
  `custom_syringe_stroke_mm`, `flow_rate`, `fill_flow_rate`, `level_ml`,
  `flush_flowrate`, `flush_volume`, `wait_after_flush`, `flush_count`
  now round-trip via a new `"pump_valve"` sub-dict, tolerant-absent per
  the established pattern. Confirmed `qt_ui_v2.py` needed no separate
  change (`_settings_dict`/`_load_settings` still not in
  `MainWindowV2.__dict__`). See Session 82 changelog entry.
  **Batch 2 (2026-08-04/05) closed the Camera manual tab**: 17 fields
  (ROI h/v offset/size, `center_roi`, the manual `exposure_ms` --
  confirmed distinct from the Experiment tab's own `exp_exposure_ms` --
  `conversion_method`/`conversion_shifts`, the sequence-cluster fields,
  `capture_mode`, `dcam_source`, `external_polarity`/`external_delay`,
  `sequence_exposure_ms`) now round-trip via a new `"camera"` sub-dict.
  Two fields deliberately excluded, not missed: `conversion_min`/
  `conversion_max` (always read-only, live-capture-derived display
  values, never user-set) and, found only during this batch's own
  verification, **`image_continuous`** -- unlike every other field
  audited so far, it is a live action trigger (its `toggled` signal opens
  a real camera preview window and starts continuous capture), not
  passive configuration; persisting it would auto-start live capture the
  instant settings load, before hardware is connected. See Session 83
  changelog entry for the full root-cause trace (a genuine, deterministic
  full-suite crash, distinct from this project's usual pre-existing
  offscreen-Qt flakiness, caused by exactly this field being toggled).
  **Batch 3 (2026-08-05) closed the Z-Scan tab**: all 5 fields
  (`zscan_output_dir`, `zscan_z_start_um`, `zscan_z_end_um`,
  `zscan_step_size_um`, `zscan_exposure_ms`) now round-trip via a new
  `"zscan"` sub-dict, none excluded -- the batch-2-mandated connected-
  signal check found no live action trigger among the 5, but did
  surface a different real hazard: `zscan_z_start_um`/`zscan_z_end_um`
  are disabled with range `[0.0, 0.0]` until a genuine
  `_query_zscan_range()` hardware read widens it, so a bare
  `setValue()` at load time would have silently clamped a real saved
  value to `0.0`. Fixed in `_load_settings()` by widening the range to
  fit the loaded value first (field stays disabled; the real hardware
  query still fully overwrites this range later, so the safety gate is
  unweakened). See Session 84 changelog entry.
  **Batch 4 (2026-08-05, final) closed WFG's `wfg_running`
  (a new plain top-level key, not nested under `"wfg"` -- that name was
  already the existing per-channel list, and reusing it would have
  collided) and the Experiment tab's FM Sweep group (`sweep_enable`/
  `start_khz`/`stop_khz`/`center_khz`/`width_khz`/`time_ms`/`type` --
  all four of the live-cross-synced start/stop/center/width values
  persisted, not just the primary pair, for an exact round trip) and
  camera-acquisition fields (`camera_fps`, `camera_start`,
  `dynamic_camera_start`, `camera_start_array` (10 fields),
  `global_exposure`) -- all 15 fields, none excluded. Both standing
  checks (live-action-trigger, hardware-query-gated range) came back
  clean for all 15. See Session 85 changelog entry.**

  **Status: RESOLVED.** Every field identified in the original audit is
  now persisted (three deliberate exclusions: `conversion_min`/
  `conversion_max`/`image_continuous`, none of them passive
  configuration). No remaining batches. The general caution below
  remains load-bearing for any *future* field ever added to a manual
  tab, not just as a closed historical note: **confirm no candidate
  field is a live action trigger** (a connected signal with real side
  effects, like `image_continuous`) **and confirm no candidate field
  has a hardware-query-gated range or other state that could silently
  discard a loaded value even without any signal being connected at
  all** (like `zscan_z_start_um`/`zscan_z_end_um`) -- "looks like a
  plain config field" is not sufficient on its own for either check.
- **The LabVIEW port registry (`labview_ports.py`) is confirmed materially
  incomplete.** Session 11. Entire `AD2_MSO_SDK_class` surface (17 real VIs,
  1 documented), several `AD2_SDK_class`/`AD2_WFG_SDK_class`/
  `AD2_DO_SDK_class` member VIs, `TDMSlogg_class`, the `REGLO Digital`
  peristaltic pump driver (referenced in `Main.vi`'s front panel, with a
  corresponding but entirely unwired `RegloPumpControl` dataclass already in
  `instruments.py:142-146`), and `Application.lvclass:SaveData.vi` are all
  undocumented in the registry. **Status: OPEN.**
- **FM Sweep's three unverified assumptions remain uncited against real
  LabVIEW binary or source literature.** Session 16: (1) Sweep-Type ->
  Function enum mapping is architecturally plausible, not confirmed; (2)
  dual-enable semantics (Enable Sweep forcing both Carrier and FM Mod enable)
  is this project's own designed convention; (3) Width-as-total-span is an
  explicit user unit decision, not confirmed against the Martens et al.
  reference's own half-vs-full-span convention. **Status: OPEN.**
- **Frequency Scanning's linear-spacing assumption is LabVIEW-behavior-
  inferred, not confirmed.** Session 14/34. No real AD2 run had confirmed the
  actual per-repeat output frequency changes as expected during a live
  experiment. **Partially resolved (Part C, pending_feedback.md item 5):**
  confirmed the *mechanism* against real hardware -- 3 distinct
  frequencies (1000/1050/1100 kHz) applied to real AD2 CH1 in sequence,
  each genuinely reached the device (readback matched requested within
  float precision). The *linear-spacing-is-the-correct-LabVIEW-behavior*
  assumption itself remains unconfirmed against the real LabVIEW binary --
  that part is still **OPEN.**
- **Hardcoded physical/hardware constants audit (Session 18) found several
  items not tracked elsewhere:** live camera ROI/exposure startup defaults
  (`roi_v_offset=900`, `roi_v_size=500`, `exposure_ms=50.0`) diverge from
  this repo's own validated-on-real-hardware combination (`792`/`740`/
  `40.0ms`) never wired into the live UI -- **fixed (pending_feedback.md
  item 5, Part B2):** `qt_ui.py`'s startup defaults now match the validated
  combination exactly; the Prior Z-motor's serial backend silently
  inherited the valve's 19200 baud default with zero independent
  Prior-protocol verification -- **moot (Part B1):** the Prior Z-motor/
  serial path was retired entirely, replaced by the real Thorlabs piezo
  connection, which has no baud-rate concept at all; MSO/scope default
  voltage range (1V) is below the real acoustic drive signal's documented
  level (up to 2V), risking clipping at defaults; a cluster of
  operationally-chosen timeouts (Qmix reference-move/close, `Application`
  cleanup, DCAM frame-wait) have no cited hardware-response basis.
  **Status: OPEN** (MSO voltage range, timeout citations only).
- **DCAM ROI was never applied in the automated path -- FIXED as a
  side-effect of Session 51's pre-flight validation work, but the original
  Session 21 finding was about a different gap (automatic *application*, not
  *validation*) and remains only partially addressed.** Session 21 found
  `configure_roi()` was absent from `application.py`/`workflows.py` entirely
  -- an automated run relies on whatever ROI a manual Camera-tab session last
  configured. Session 51 added pre-flight bounds *validation* inside
  `configure_roi()` itself, but did not add a new call to `configure_roi()`
  from the automated experiment path -- the underlying Session 21 gap (no
  automatic application) is **still OPEN**; only "if configure_roi() is ever
  called with a bad ROI, it's now rejected earlier and more clearly" is
  resolved. **Status: OPEN** (automatic-application gap unchanged).
- **Qmix syringe geometry is never applied automatically.** Session 21. The
  physical `inner_diameter_mm`/`stroke_mm` pushed to the Qmix SDK is whatever
  a manual "Configure" click last set; `Application.flush()` only does
  mL-level bookkeeping. Confirmed likely a pre-existing LabVIEW limitation
  too (lower-confidence cross-check than the ROI finding). **Status: OPEN.**

## Legacy/dead retained code and deliberately out-of-scope items

- **`src/thermo_acoustic/main.py` -- simulation-only message-queue smoke.** It
  is not an operator GUI launcher. The current working tree explicitly injects
  `SimulatedAD2Sdk` and guarantees cleanup, so invoking the package smoke cannot
  silently open the default real AD2 path. **Status: RETAINED TEST/REFERENCE
  ENTRY POINT, not active hardware control.**
- **`src/thermo_acoustic/ui.py` -- VERIFIED-DEAD Tkinter UI.** No current
  launcher or production module imports it; the supported UI is PySide6
  (`qt_ui.py`). It is retained as migration reference only and now carries an
  explicit module banner saying it is not a supported hardware-control surface.
  **Status: retained legacy, not an active removal task.**
- **DO Custom remains legacy/nonessential** per `docs/legacy_unresolved_
  items.md` -- should stay out of the active workflow unless new LabVIEW or
  hardware evidence proves it load-bearing. Not from the changelog directly;
  cross-referenced from the overlapping doc. **Status: OPEN by design.**
- **TDMS write verification's "field-count assertion" was explicitly scoped
  down, not a shortcut.** Session 26's own `_verify_tdms_write()` deliberately
  does a key-presence check, not a value-by-value comparison, "to avoid
  duplicating the existing write-path tests" per explicit instruction.
  **Status: RESOLVED as scoped**, not a gap.
- **`SynchronizeState`'s automated-path control was deliberately not added.**
  Session 22. Investigation confirmed it has no real hardware effect anywhere
  in this codebase (the manual tab's own control is an explicitly-disabled
  non-functional stub) -- adding a working automated-path control would
  misrepresent a fake feature as real. **Status: RESOLVED as scoped**, not a
  gap.
- **Laser (785nm) has no software-side control in this codebase at all.**
  Confirmed via a repo-wide case-insensitive search for "laser"/"785" (zero
  matches in `src/`) during this project's own hardware-safety audit --
  entirely out of software scope, manual-only on the physical unit.
  **Status: CONFIRMED OUT OF SCOPE** (this is the one item in this whole
  document that genuinely matches a "confirmed out of scope" framing --
  see Part 2 of the report for why the *specific* "Peltier TEC background
  temperature control confirmed out of scope" example could not be found).
- **LabVIEW-migration-parity scaffolding modules -- intentionally retained,
  not dead code.** `utilities.py`, `imaq.py`, `filetypes.py`,
  `serial_config.py` (~454 lines total) each map to specific original
  LabVIEW VIs (`labview_ports.py`'s `python_name=` entries) but have zero
  cross-references from any other file in `src/thermo_acoustic/` or from
  `tools/` -- confirmed by a code-health audit (Session 57), which
  initially flagged this as a dead-code candidate before the user
  clarified their purpose: proving migration completeness/traceability,
  i.e. evidence that no original LabVIEW capability was silently dropped
  during the port, even where production code now uses a different,
  more direct implementation instead (DCAM/PIL instead of `imaq.py`,
  `logging`/`QMessageBox` instead of `utilities.py`'s LabVIEW-mimicking
  dialog/error helpers, hardcoded serial params instead of
  `serial_config.py`'s `VisaSerialConfig`). Each of the four files now
  carries an explicit module-level docstring stating this (Session 57).
  **Status: CONFIRMED INTENTIONAL, not a gap** -- do not remove or
  re-flag as dead code without an explicit decision to do so; unlike
  `ui.py` above, this is not "awaiting a removal decision," it's settled.
  (`RegloPumpControl`, tracked separately above under Data-integrity
  gaps as part of the LabVIEW port registry's own incompleteness, is a
  genuinely different situation -- an unwired driver dataclass, not
  migration-parity reference material -- and remains its own open item.)

## Manual-only probes

- **`hardware_tests/manual_ppc001_piezo_probe.py` -- manual real-hardware
  probe, not pytest coverage.** Its `manual_` name is intentional; it directly
  uses Kinesis/pythonnet and has an explicit confirmation gate for motion. It
  remains outside `testpaths = ["tests"]` and must be run only by an operator.
- **`hardware_tests/test_valve_command_probe.py` and
  `hardware_tests/test_valve_command_probe_v2.py` -- manual command probes,
  despite their historical `test_` filenames.** They can transmit a valve
  command only with explicit port, command, and `--confirm SEND` arguments.
  They are not part of normal pytest collection because project testpaths are
  restricted to `tests/`; retain the names for historical traceability, not as
  automated test evidence.
- **Discovery and staged-smoke scripts in `hardware_tests/` are manual tools.**
  Their default/no-confirmation paths may be passive, but any action-capable
  mode is operator-gated. Their results must be recorded as hardware evidence,
  not inferred from unit-test results.
- **Legacy action-capable scripts under `tools/` are manual-only, not pytest
  coverage.** `legacy_hamamatsu_camera_probe.py`, `legacy_qmix_pump_probe.py`
  (renamed from `test_hamamatsu_camera.py`/`test_qmix_pump.py`, file/structure
  audit cleanup, to stop colliding in name with the gated `hardware_tests/
  test_*.py` scripts), and `capture_ad2_wavegen_scope*.py` are outside `testpaths` and explicitly set
  `__test__ = False`, but can still open/configure hardware without the newer
  confirmation gates. Keep them as historical diagnostics; do not treat them
  as approved procedures or automated evidence. **Status: RETAINED LEGACY,
  MANUAL-ONLY.**

## Other

- **`instruments.py` line-by-line review (2026-07-31) found 7 low-priority
  code-smell/latent-fragility items, none fixed (HIGH/MEDIUM findings from
  the same review -- H1/H2/M1/M2/M3 -- were fixed the same day; see the
  Session 63 changelog entry).** Left as a backlog list rather than five
  separate entries, since none is a live, currently-reachable bug:
  1. `SerialTextCommandBackend.query()` has an unreachable defensive
     `if self.port is None: raise` check ([instruments.py:94](../src/thermo_acoustic/instruments.py:94))
     -- `_send()` (called first) already guarantees this. Dead code.
  2. `SerialTextCommandBackend._send()` writes the unstripped `command`
     to the wire, while routing decisions use the stripped `text`
     ([instruments.py:71-78](../src/thermo_acoustic/instruments.py:71)) --
     only matters if a caller ever passes incidental whitespace; none does.
  3. `HamamatsuCamera.center_roi()`'s `self.roi is None` branch builds a
     `{"centered": True}` dict that `HamamatsuDcamBackend.configure_roi()`
     doesn't actually interpret -- it silently becomes "offset (0,0), size
     untouched," the opposite of centering
     ([instruments.py:629-637](../src/thermo_acoustic/instruments.py:629)).
     Confirmed unreachable today: the only real call site
     (`qt_ui.py`'s `_configure_camera()`) always sets a real `SubRegion`
     immediately before calling `center_roi()`. Real bug if ever called
     independently; dead code as currently wired.
  4. `SimulatedAD2Sdk.capture_scope()` marks its own parameters unused
     (`_ = channel_index` etc.) then uses every one of them
     ([instruments.py:502-513](../src/thermo_acoustic/instruments.py:502)) --
     no functional effect, just misleading to a reader.
  5. `Valve.wait_until_ready()` checks for a `status_note` value
     (`"ready"`) that `_apply_status_response()` never actually produces
     ([instruments.py:891](../src/thermo_acoustic/instruments.py:891)) --
     harmless, the `"confirmed"` half of the `or` still fires correctly.
  6. `AD2Sdk.wfg_configure_carrier_single_ch()` indexes
     `config.channels[channel_index]` with no bounds check
     ([instruments.py:275-277](../src/thermo_acoustic/instruments.py:275))
     -- `WfgConfig.channels` defaults to exactly 2 elements; any call with
     `channel_index >= 2` raises `IndexError`. No current caller passes
     anything but 0/1.
  7. `CetoniPump.generate_flow()`'s dosing-flag logic
     (`self.dosing = True` then back to `False` if `self.simulate`,
     [instruments.py:758-763](../src/thermo_acoustic/instruments.py:758))
     is only correct because the real factory
     (`hardware_factory.build_hardware_bundle()`) never constructs
     `simulate=False, backend=None` -- a combination the dataclass itself
     doesn't prevent. Not reachable via the standard factory path.
  **Status: OPEN, low priority** -- revisit if any of these becomes
  reachable (e.g. a future caller of `center_roi()` that doesn't
  `configure_roi()` first) or during a future cleanup pass.
- **`qmix_backend.py` line-by-line review (2026-07-31) found 2 more
  low-priority code-smell items and 2 latent (not live) correctness gaps,
  beyond the HIGH finding (`refill()`/`empty()` never waiting for real
  completion) fixed the same day -- see the Session 64 changelog entry.**
  Grouped here rather than four separate entries, since none is a live,
  currently-reachable bug:
  1. `configure_flow_unit()`'s unit-matching set has a redundant,
     almost-certainly-a-typo entry --
     `{"ul/s", "uL/s".lower(), "microlitre/s", "microliter/s"}`
     ([qmix_backend.py:290](../src/thermo_acoustic/qmix_backend.py:290)) --
     `"uL/s".lower()` duplicates the literal `"ul/s"` already in the same
     set. Harmless (sets de-duplicate), reads like a leftover from an
     intended different case-variant that was never written.
  2. `configure_syringe()`'s key-fallback chains use `or`
     ([qmix_backend.py:240-251](../src/thermo_acoustic/qmix_backend.py:240)),
     which would silently skip an explicitly-provided but falsy `0.0` in
     favor of a later fallback key. Not practically exploitable: `0.0` is
     already an invalid syringe dimension and gets caught by the
     `MIN_SYRINGE_INNER_DIAMETER_MM` bounds check regardless of which key
     ends up used.
  3. `_load_sdk()`'s `from qmixsdk import ...`
     ([qmix_backend.py:107-122](../src/thermo_acoustic/qmix_backend.py:107))
     is resolved through Python's global `sys.modules` cache -- a second
     `QmixPumpBackend` instance constructed with a *different*
     `sdk_python_path` in the same process would silently receive the
     first instance's already-cached SDK module instead of its own, with
     no error. Not reachable in this project's normal single-pump,
     single-path-per-process usage.
  4. `initialize()` unconditionally constructs a new `Bus()`
     ([qmix_backend.py:124-126](../src/thermo_acoustic/qmix_backend.py:124))
     with no guard against being called twice on an already-successfully-
     initialized instance -- a second call would silently overwrite
     `self.bus`, potentially leaking a real, still-open bus handle. Not
     currently exercised: `Application.initialize()` only calls each
     instrument's `initialize()` once per bring-up, always paired with
     `cleanup()`.
  **Status: OPEN, low priority** -- same disposition as the
  `instruments.py` backlog entry above: revisit if any of these becomes
  reachable, or during a future cleanup pass.
- **Camera initialization and capture-session rollback were hardened in the
  current working tree (2026-08-04).** A failed `dev_open()` now rolls back
  the partially created DCAM object and API initialization;
  `HamamatsuCamera.cleanup()` still attempts backend close when capture stop
  fails; and `Application.run_experiment2()` now attempts capture cleanup when
  either capture start or frame reading raises while preserving the primary
  acquisition error. These boundaries are covered by fake-only lifecycle
  tests. They did not require a real-camera action, and are not new hardware
  validation evidence.
- **`hamamatsu_dcam.py` line-by-line review (2026-07-31) found 1 remaining
  low-priority item, beyond the findings fixed then and the rollback hardening
  recorded above -- see the Session 65 changelog entry for the historical
  review.**
  1. `_stop_capture_if_active()` clears `self.capture_active = False` in a
     `finally` block regardless of whether the real `self.dcam.cap_stop()`
     call succeeded or raised
     ([hamamatsu_dcam.py:515-523](../src/thermo_acoustic/hamamatsu_dcam.py:515))
     -- the inverse of the optimistic-update-before-confirmation shape
     (marks state "inactive" before a real stop is confirmed, rather than
     marking it "active" before a real start is confirmed). Not fixed:
     the failure is not swallowed -- it propagates via `cleanup_error` and
     is re-raised (or logged by the caller in the wait-timeout cleanup
     path) -- so a caller has to actively ignore a raised exception to
     act on the false "not capturing" state, and a genuinely broken
     connection would very likely fail loudly again on the next
     `dcam.*` call anyway (`is_opened()`/`_check()` guards throughout).
  **Status: OPEN, low priority** -- same disposition as the
  `instruments.py`/`qmix_backend.py` backlog entries above.
- **`waveforms.py` line-by-line review (2026-07-31) found 1 remaining
  low-priority item, beyond the findings fixed the same day -- see the
  Session 66 changelog entry.**
  1. `WaveFormsBackend._enum_value()`'s silent default-value fallback
     ([waveforms.py:193-198](../src/thermo_acoustic/waveforms.py:193))
     -- backs `_FUNCTIONS`/`_TRIGGER_SOURCES`/`_DO_TYPES`/`_DO_IDLE`.
     Checked: all four are currently exhaustive 1:1 matches of their
     corresponding `ad2.py` enums, so the silent-default branch was dead
     code for every valid enum member at review time. That was still unsafe
     for a future enum/configuration mismatch.
  **Resolved in the current working tree (2026-08-02; pending review):**
  `AD2Sdk.do_configure()` and `AD2Sdk.wfg_start_stop_all_ch()` now use the
  same commit-after-confirmation pattern. The latter configures a copied
  `WfgConfig`, and both retain their last confirmed cached state if the
  backend raises. Focused raising-backend tests and the complete offline suite
  pass. This is not an open-item candidate unless real-hardware verification
  finds a separate issue.
  **Resolved in the current working tree (2026-08-04; pending review):**
  `ad2._coerce_enum()` preserves defaults only for missing values and rejects
  explicit unknown enum strings; `WaveFormsBackend._enum_value()` accepts only
  known mappings or raw integer SDK values and otherwise raises. Focused
  fake-only regression tests cover both boundaries. This entry remains as
  historical rationale, not an open item. **Status: RESOLVED in the working
  tree, pending review.** See the
  [Session 88 changelog entry](claude_code_change_log.md) for the full
  writeup (added retroactively during commit preparation -- this note
  previously had no corresponding changelog entry).
- **The Experiment tab has no general per-channel FM-modulation
  control (feature-completeness note, not a bug; found during the
  targeted `qt_ui.py`/`qt_ui_v2.py` UI audit, Session 69).**
  `_experiment_channel_config()`
  ([qt_ui.py:2833-2841](../src/thermo_acoustic/qt_ui.py:2833)) hardcodes
  `fm_mod = CarrierSettings(..., enable=False)` for both channels,
  only overridden for Ch1 when the separate "FM Sweep" feature is
  enabled. Independently confirmed this is not a "looks editable but
  silently ignored" case -- no `exp_ch1_fm_*`/`exp_ch2_fm_*` widgets
  exist on the Experiment tab at all; the only FM-mod-capable widgets
  belong to the manual WFG tab's separate, non-experiment-tracked
  config builder. Consequence: `data.tdms`'s `WFGFMEnabledCh2` (added
  Session 68) will be `False` for every real automated experiment (Ch2
  has no path to real fm_mod data), and Ch1's fm_mod values only ever
  come from the FM Sweep feature, never free-form per-channel choice.
  A real, if minor, feature-completeness gap relative to the manual
  tab, not a data-recording bug -- **Status: OPEN, low priority,
  product-decision item** (whether to expose independent per-channel
  FM-mod controls on the Experiment tab is a scope decision, not a
  fix).
- **`application.py` line-by-line review (2026-07-31) found 2 more
  low-priority items, beyond Finding 1 fixed the same day (Session 67)
  -- both correctly assessed as currently-unreachable/inherited
  limitations, not live bugs.**
  1. `handle_message()`'s `CETONI_REFILL`/`CETONI_EMPTY` branches
     ([application.py:770-773](../src/thermo_acoustic/application.py:770))
     still call `self.pump.refill()`/`self.pump.empty()` directly,
     bypassing the `Application.refill()`/`empty()` wait-for-completion
     fix from the same day (Session 64's H1 fix, extended to `qt_ui.py`'s
     buttons). Confirmed unreachable: `qt_ui.py` never calls
     `enqueue_main()`/`run_until_idle()`/`handle_message()` with any
     `MessageName.CETONI_*` message (grepped, zero hits) -- the only
     driver of `run_until_idle()` is `main.py`, a minimal CLI entry point
     that only enqueues `INITIALIZE`, and no test exercises
     `handle_message(Message(MessageName.CETONI_REFILL))` either. If the
     message-queue dispatch path is ever revived as a real caller, these
     two branches need the same fix `qt_ui.py`'s buttons got.
  2. `wait_for_pump()`'s single boolean return
     ([application.py:394-403](../src/thermo_acoustic/application.py:394))
     can't distinguish "aborted" from "timed out," so `refill()`/`empty()`
     (added the same day) fire `"RefillTimedOut"`/`"EmptyTimedOut"` status
     events even when the real cause was an abort. Not a new bug --
     `flush()` has had this exact ambiguity from `wait_for_pump()` since
     before that day, and `refill()`/`empty()` correctly followed that
     existing precedent rather than inventing new behavior.
  **Status: OPEN, low priority** -- same disposition as the backlog
  entries above.
- **`workflows.py` line-by-line review (2026-07-31) found 3 more
  low-priority items, beyond Finding 1 fixed the same day (Session 68)
  -- all correctly assessed as currently-unreachable/inherited
  limitations, not live bugs.**
  1. `_settings_properties()`'s `"FlushCompleted": ""` default
     ([workflows.py:233-237](../src/thermo_acoustic/workflows.py:233))
     is only correct because `save_settings()` is never called after
     `flush()`/`save_flush_result()` in the real `run_experiment2()`
     call order -- verified true today, but unenforced by any test. If
     a future `save_settings()` call were ever added after `flush()`
     runs, it would silently overwrite the real `True`/`False` flush
     outcome back to `""`.
  2. `_git_commit_hash()`'s `@lru_cache(maxsize=1)`
     ([workflows.py:22-49](../src/thermo_acoustic/workflows.py:22))
     caches the commit hash/dirty-state for the life of the process --
     every experiment repeat within one long-running app session
     records whatever `GitCommitHash` was true at the *first* call, not
     necessarily the current state if the working tree changes
     mid-session. Low real-world likelihood.
  3. `_settings_properties()`'s DO-channel selection
     ([workflows.py:223-225](../src/thermo_acoustic/workflows.py:223))
     -- `next((channel for channel in do_clock.channels if
     channel.enable), None)` -- only records the *first* enabled DO
     channel's `DORun`/`DOWait`/`DOFreq`/`DOFreqActual`
     (these are singular field names, not per-channel-suffixed like
     the WFG fields). A second simultaneously-enabled DO channel would
     be silently unrecorded. Confirmed unreachable: `qt_ui.py`'s
     `_experiment_do_clock_config()` only ever builds one DO channel
     (`channel_index=1`, the LED clock).
  **Status: OPEN, low priority** -- same disposition as the backlog
  entries above.
- **The production `exp_ctrl` conda environment was silently missing
  real dependencies (`npTDMS`, and two more found on audit) -- undetected
  until a real-hardware verification run tried to write `data.tdms`,
  fixed with a manifest + sanity-check script (2026-07-31).** `exp_ctrl`
  is the conda environment `launch_gui.bat` actually uses for real
  production runs, but it was hand-assembled by hand over time, never
  built from any manifest -- `npTDMS` was missing entirely, meaning the
  real app's own metadata-write path may never have been exercised
  end-to-end with real hardware before this was caught. A follow-up audit
  (cross-referencing every real third-party import reachable from
  `launch_gui.bat`'s code path against `exp_ctrl`'s actual installed
  packages) found the same class of gap twice more: `numpy` and
  `pythonnet` (imported as `clr`, needed for real Z-stage/piezo motion)
  were both real, always-needed dependencies never declared in
  `pyproject.toml` at all -- undetected only because `exp_ctrl` happened
  to already have them installed for unrelated reasons. **Fixed:**
  `pyproject.toml`'s `dependencies` completed (`numpy`, `pythonnet`
  added; `pylablib` correctly classified as an optional,
  diagnostic-only extra, since `thorlabs_apt.py` -- the only file that
  imports it -- has zero importers anywhere in the real app); new
  `requirements-exp_ctrl.txt` (repo root) pins the exact versions
  currently validated in the real environment; new
  `tools/check_environment.py` imports every real core dependency and
  reports pass/fail, verified to correctly distinguish a complete
  environment (`exp_ctrl`, exit 0) from an incomplete one (the unrelated
  `base`/pytest environment, correctly reports `pythonnet` missing,
  exit 1) -- this is the check that would have caught the original gap
  immediately instead of on a real-hardware run. New README.md
  "Environment Setup" section documents how to rebuild `exp_ctrl` and
  when to re-run the check. **This class of problem (a rarely-exercised
  real path, like the TDMS write, silently depending on something the
  production environment doesn't actually have) should be considered
  closed going forward by running `python tools/check_environment.py`
  after any environment change** -- re-run it, don't re-investigate by
  hand, if this is ever suspected again. **Status: RESOLVED, committed in
  `17f24dd`.**
- **Valve-handshake hardening (Session 43 Part 2) was investigated and left
  "uncommitted, pending a decision" in the changelog -- but has since been
  committed (`8149bc1`, "Harden valve initialize() to reject unrecognized
  status responses").** Confirmed via `git log --all -- instruments.py`.
  The changelog's own Session 43 entry was never updated to record this;
  only the top-of-file "current repo-state" banner lists the commit hash,
  with no cross-reference back to the Session 43 narrative. **Status:
  RESOLVED**, changelog stale on this point -- see Part 2 of the report.
- **Valve status-query handshake (`"S"` command)** was protocol-derived and
  unverified at introduction (Session 2), later real-hardware-confirmed
  (Session 31, `status_note="confirmed"`). Current code rejects empty
  responses and unrecognized non-empty responses during initialize:
  `Valve._apply_status_response()` returns `False` for unparseable text and
  `Valve.initialize()` raises `ValveError` instead of reporting Connected.
  Busy markers (`*`/`**`) remain accepted as an explicit busy status, not as
  a clean confirmed position. **Status: RESOLVED for unknown-response
  rejection; still hardware-dependent for choosing the correct COM port.**
- **PySide6/shiboken offscreen-Qt flakiness** -- a `SystemError`/
  `RuntimeError` (`<class> returned NULL without setting an exception` or
  `Internal C++ object ... already deleted`) intermittently reproduces when
  many `MainWindow`/`MainWindowV2` instances are constructed in one pytest
  process (observed since Session 42, still occurring as recently as this
  project's own most recent work). Confirmed environment/binding
  characteristic, not application logic -- every occurrence passes when the
  specific failing test is re-run alone. **Status: OPEN, accepted as
  environmental**, not expected to be fixed.
- **pytest leftover `.pytest_tmp_*` directories, 35 of 119 undeletable due
  to a pre-existing OS permission issue** (`UnauthorizedAccessException`,
  even to `Get-Acl` itself) -- confirmed the same failure mode Session 27
  already documented for an earlier, different batch on this same machine.
  Session 49 added a fixed, reused `--basetemp` (`pyproject.toml`'s
  `addopts`) to stop new leftovers accumulating; the 35 already-stuck
  directories were left as-is (no admin rights available). **Status: OPEN**
  (the 35 stuck directories), **RESOLVED** (no new accumulation going
  forward).
- **Four inconsistent hardware close()/cleanup() shapes, no shared
  convention.** Code-health audit finding 3b (Session 57):
  `HamamatsuDcamBackend.close()`, `QmixPumpBackend.close()`,
  `PiezoStage.disconnect()`, and `Application._cleanup_instruments()`
  each independently evolved a different error-handling shape for
  device teardown. `docs/hardware_safety_patterns.md`'s "Standard
  hardware-cleanup shape" section (added Session 57) documents the
  collect-errors + timeout-wrap + combined-raise shape as the required
  template for any *new* hardware module going forward.
  **Update (cross-module architecture review, 2026-08-02): the
  timeout-wrap mechanism itself is no longer independently implemented
  three times.** `QmixPumpBackend._run_close_step()`,
  `PiezoStage._run_disconnect_step()` (retrofitted with a timeout guard
  per `pending_feedback.md` item 6 Task 2), and
  `Application._run_cleanup_call_with_timeout()` all now call one shared
  `hw_logging.run_with_timeout()` utility -- concrete evidence the
  "document a copyable template" approach alone wasn't propagating
  reliably (see below). `HamamatsuDcamBackend.close()` (best-effort,
  never raises -- a deliberately different design per Finding F's own
  reasoning, not an inconsistency) and `Application._cleanup_instruments()`
  (device-level orchestration around the shared per-step timeout guard,
  not a competing implementation of it) remain their own shapes by
  design, not by omission.
  **The later TEC gap is now closed in the current worktree:**
  `TecController.cleanup()` and the failed-initialize rollback close both use
  `run_with_timeout()` with a local bounded timeout. A stuck call is reported
  as a `TecError`; the daemon call may still be alive, so this is bounded
  caller behavior rather than a claim that the vendor call was cancelled.
  **Status: RESOLVED for the shared timeout mechanism
  (`QmixPumpBackend`/`PiezoStage`/`Application`/`TecController` share one
  implementation). `HamamatsuDcamBackend`'s deliberately-different shape is a
  design decision, not an open gap.**
- **STALE, corrected Session 78: `Valve.wait_until_ready()` has no
  abort-awareness (fixed timeout only).** Originally flagged (2026-08-02
  cross-module architecture review) as an inconsistency against the
  pump's `wait_for_pump()`, which at the time checked `Application.
  listen_abort()`. **That comparison point no longer applies: Session 78
  deliberately removed `wait_for_pump()`'s abort check as a real
  safety-behavior fix** (Abort must never interrupt an in-progress pump
  move mid-flush -- see the Abort entry above). So `Valve.wait_until_ready()`
  having no abort-awareness is now the *consistent* state, not a gap --
  no instrument's own hardware-wait loop should be abort-interruptible
  anymore; the only abort check anywhere is the between-repeats one in
  `qt_ui.py`'s `_run_experiment_series_body()`. **Updated (Session 80):**
  `TecController.wait_until_stable()`'s `should_abort` parameter still
  exists as a general `tec.py` API feature, but it is no longer fed by
  the real production call path -- `run_temperature_series()` stopped
  passing `self.listen_abort` into it and now checks `self.stop_fired`
  once per temperature point instead, the same between-units convention
  as everything else. This closes what used to be described here as a
  "live, intentional exception" for TEC temperature-scan waits; there is
  no longer a carve-out to conflate. **Status: RESOLVED (by the
  comparison point no longer holding, not by adding abort-awareness to
  the valve).**
- **`AD2Sdk.config_do_custom()` and `config_do_clock_special()` write to
  overlapping state (`self.do_config`) with no conflict detection.**
  Found during the same review. Both assign to `self.do_config` (in
  addition to their own `self.do_custom_config`/`self.do_clock_settings`)
  -- if a future change ever wired both into the same `run_experiment2()`
  run, the second call would silently clobber the first's confirmed
  configuration with no error or warning, the same "silent state
  clobber" shape found and fixed elsewhere this session, just not yet
  triggered here. Currently dormant/unreachable: nothing in the
  automated `run_experiment2()` path calls `config_do_custom()` today
  (confirmed via the qt_ui.py call-site audit). **Not fixed -- not
  worth restructuring dormant code with no reported issue.** Flag for
  design review if `config_do_custom()` is ever wired into the automated
  path alongside `config_do_clock_special()`. **Status: OPEN, low
  priority, latent risk only.**
- **Pump&Valve "Syringe" dropdown looks live-selected but has no real
  effect until "ConfigureSyringe" is clicked -- a real operator-confusion
  trap, found investigating the Refill/Empty flow-rate rejection
  (2026-08-03).** Selecting a different syringe in the dropdown
  (`self.syringe`, [qt_ui.py:2119](../src/thermo_acoustic/qt_ui.py:2119)-area
  `syringe_form`) only updates the widget's own displayed selection --
  the real pump's configured geometry (and therefore its real live
  `max_flow_rate_ul_min`/`max_volume_ml`) does not change until the
  separate "ConfigureSyringe" button is pressed
  (`QmixPumpBackend.configure_syringe()`). Confirmed via a real
  `logs/hardware_transactions.log` session: the dropdown showed "BD
  5ml" selected while the pump remained connected with the config
  file's own default "1 ml Glass" geometry (`Cetoni_1pump_config_FM`'s
  `nemesys.xml`), since no `configure_syringe` call ever fired that
  session before Refill/Empty ran -- an operator has no way to tell
  from the dropdown alone whether the syringe they see selected is the
  one actually active on the real device. **Not fixed -- flagged for a
  future UX pass:** possible directions include disabling Refill/Empty/
  Generate Flow/Go to Level until the dropdown selection has been
  applied, or a visible "applied"/"pending" indicator next to the
  dropdown reflecting whether the last `configure_syringe()` call
  matches the current selection. **Status: OPEN, real operator-facing
  risk, not yet fixed.**
