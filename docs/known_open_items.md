# Known Open Items

Reference document, not a narrative. Consolidates every item flagged across
`docs/claude_code_change_log.md` (all sessions, read start to finish) as
unresolved, deferred, unverified, or needing future confirmation, plus current
status verified against git history and the live code -- not assumed from the
changelog's own claims. Compiled 2026-07-28.

**Related, overlapping document:** `docs/legacy_unresolved_items.md` already
exists and covers similar ground (hardware-integration/AD2-timing/UI-settings
caveats). As of this writing it is itself part of the same uncommitted TEC
integration work sitting in the working tree (`git status` shows it modified,
not committed) -- treat its current content as reflecting that in-progress
effort, not settled fact, until TEC's own commit lands. This document is
sourced independently from the changelog and git history, not copied from it.

Status legend: **OPEN** (confirmed still true in current code/git history),
**RESOLVED** (confirmed fixed, cited), **STALE-IN-CHANGELOG** (changelog says
open but code/git shows resolved, or vice versa -- see Part 2 of the report
for the full list), **DESIGN FORK** (not a bug -- a genuine either-way
decision only the user can make).

---

## Hardware verification gaps

- **DIO0 (acoustic)/DIO1 (LED) relative timing never oscilloscope-verified.**
  Session 19/31/43. The DO-clock derivation (`_experiment_do_clock_config()`)
  is structurally wired from real UI values, but whether its physical timing
  actually matches LabVIEW has never been confirmed with a scope. Session 31
  added real per-frame `dcam_clock:` timestamp evidence (~0.0316s deltas,
  matching camera readout time, not the configured 0.2s DO-clock period) that
  is *consistent with* camera trigger source `"Internal"` free-running rather
  than being paced by the DO clock -- supporting evidence, not a resolution.
  **Status: OPEN.**
- **Camera trigger source Internal-vs-External unresolved.** Session 13
  hardcoded `"Internal"` to remove undefined-leftover-state risk; Session 19
  traced the real LabVIEW call chain (`RunExperiment2.vi` ->
  `CreateExperiments.vi` -> `Experiment2_Init.vi` -> `ConfigureSequence.vi` ->
  `tm_inputtriggersource_40.vi`) and confirmed the actual wired value is not
  recoverable from exported VI diagrams (compiled block-diagram wiring, not
  text) -- a genuine negative result, not a gap in effort. Needs oscilloscope
  verification, not fixable from software alone. **Status: OPEN.**
- **DCAM frame timestamp clock domain unverified.** Session 8. Real per-frame
  timestamps are captured when the camera/driver reports support, but which
  clock (camera-internal vs. host-driver) produced them, and the epoch, is
  unconfirmed against real hardware or official SDK docs. **Status: OPEN.**
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
  hardware-verified:** abort concurrency, Qmix bus close on init failure,
  serial read/write timeouts, the AD2 SDK clock-divider wiring in
  `waveforms.py`'s `configure_do()`, and the TDMS metadata *content* itself
  (no real npTDMS-vs-LabVIEW file comparison has ever been performed, though
  the write-verification *mechanism* was independently confirmed against a
  real npTDMS install in Session 27). **Status: OPEN.**
- **"Analog Discovery 3" row label** (`qt_ui.py:504`, `qt_ui.py:1395`,
  confirmed still present in current code) is the only place calling this
  device generation "3" -- everywhere else says "2". `docs/PORTING_TBD.md`
  separately references real "AD2/AD3" validation hardware, so this may be
  a deliberate label for a second, newer unit this lab has, not a typo.
  Session 39 flagged this as a genuine fork needing the user's own knowledge
  of lab hardware, not a code decision. **Status: DESIGN FORK, unresolved.**
- **Z stage backend selection has no real effect.**
  `hardware_factory.build_hardware_bundle()` never reads `config.z_backend`;
  enabling "Z stage" always builds a Prior-serial `PriorZMotor` regardless of
  the UI's (already-disabled) backend combo. Session 39. Low current risk
  since this path is separately flagged legacy/obsolete (current Z hardware
  is Thorlabs/APT via the *separate*, unrelated piezo Z-scan calibration
  feature, Sessions 45-50). **Status: OPEN.**

## Communication reliability gaps

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
  **Status: RESOLVED in code, not yet hardware-verified** -- Session 55
  had no bench access; confirming the fixed `query()` actually returns
  quickly against the real valve (not just the fake port) remains a
  natural follow-up next time real hardware is available.

## Data-integrity gaps

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
- **Pump flow-rate sign convention was found unverifiable from code alone.**
  Session 6/31. UI labels record `-=aspirate, +=dispense`; no sign-inversion
  logic exists anywhere in the pipeline, but no documented LabVIEW reference
  convention exists in-repo to compare against. An independent audit found at
  least one tooltip still carrying older "unverifiable" wording after the
  label was corrected elsewhere. **Status: OPEN.**
- **`CetoniPump.fill_level` has no readback/sync mechanism, so it always
  starts at `0.0` in a fresh process regardless of the real device's actual
  loaded volume.** No method anywhere in the pump path calls the real Qmix
  SDK's `get_fill_level()` to sync the tracked Python-side value against
  hardware state -- `refill()` only ever sets a full-capacity value, it does
  not read back the true current level, and nothing runs at
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
  `Application.initialize()`, keeping `application.py` -- which still
  carries TEC's own uncommitted diff -- untouched. Regression tests added
  ([tests/test_application.py](tests/test_application.py)), verified to
  fail against the old code before the fix landed. **Status: RESOLVED in
  code, not yet hardware-verified** -- Session 56 had no bench access;
  confirming the fixed sync actually reads the real Qmix pump's true fill
  level (not just the fake backend) remains a natural follow-up next time
  real hardware is available, same caveat as the
  `SerialTextCommandBackend.query()` fix above.
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
- **Save/Load Settings persistence is incomplete for most manual-tab-only
  fields.** Session 39, Frequency Scanning specifically closed Session 44.
  WFG Trigger/FM Mod/Sweep sub-fields, the entire Pump&Valve and Camera tabs
  (including the Session-22 load-bearing Sequence cluster), and several
  Experiment-tab fields (Camera FPS/Start/Array, Dynamic Camera Start Time,
  GlobalExposure, FM Sweep) are silently dropped by Save Settings and reset
  to defaults on next Load. Long-standing baseline behavior, not a
  regression. **Status: DESIGN FORK** -- whether comprehensive persistence
  was ever the intended design is not resolvable from code alone; a
  mechanical fix is available (`_settings_dict()`/`_load_settings()`'s
  existing tolerant `if key in data` pattern) if the answer is "yes."
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
  inferred, not confirmed.** Session 14/34. No real AD2 run has confirmed the
  actual per-repeat output frequency changes as expected during a live
  experiment. **Status: OPEN.**
- **Hardcoded physical/hardware constants audit (Session 18) found several
  items not tracked elsewhere:** live camera ROI/exposure startup defaults
  (`roi_v_offset=900`, `roi_v_size=500`, `exposure_ms=50.0`) diverge from
  this repo's own validated-on-real-hardware combination (`792`/`740`/
  `40.0ms`) never wired into the live UI; the Prior Z-motor's serial backend
  silently inherits the valve's 19200 baud default with zero independent
  Prior-protocol verification; MSO/scope default voltage range (1V) is below
  the real acoustic drive signal's documented level (up to 2V), risking
  clipping at defaults; a cluster of operationally-chosen timeouts (Qmix
  reference-move/close, `Application` cleanup, DCAM frame-wait) have no
  cited hardware-response basis. **Status: OPEN** (all items).
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

## Out-of-scope-by-design items

- **`src/thermo_acoustic/ui.py` (592 lines, unused Tkinter `MainWindow`) --
  confirmed dead, flagged for removal, never removed.** Session 7, reiterated
  Session 39. **Verified still present in the current working tree**
  (`ls src/thermo_acoustic/ui.py` succeeds). No importers anywhere in the
  repo. **Status: OPEN**, awaiting a removal decision.
- **`qt_ui_v2.py`/`MainWindowV2` remains explicitly not the default launch
  target.** Session 3 set it as default; Session 4 explicitly reverted that
  per direct user instruction ("not yet hardware-verified... must not be the
  default until the user explicitly approves it") -- deliberate, not a bug.
  Still pending hardware verification and approval despite working sidebar
  panels, valve handshake, and Init dialog fixes. **Status: DESIGN FORK,
  deliberately held.**
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

## Other

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
  (Session 31, `status_note="confirmed"`). Remaining caution:
  `Valve._apply_status_response()` still treats some non-empty but
  unrecognized responses as connected-with-note rather than a hard failure
  -- inspect before relying on the handshake as strict device-identity
  proof. **Status: MOSTLY RESOLVED**, one caution remains.
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
