# Integration investigation log

This branch (`codex/integration`) was created from `origin/ola-branch` at
`5014fc8f479c058904e7e69f2f67384851ab88ce` to combine ola-branch's device/
experiment-flow architecture with junjiebranch-specific algorithm and device
capability (TEC temperature-scan sequencing, Z-axis, UI affordances), where
that capability is genuinely missing or weaker on ola-branch. Both original
branches (`ola-branch`, `junjiebranch`) are left untouched; this branch lives
in an independent worktree at `C:\git\thermoacoustic-integration`.

This file condenses four rounds of read-only investigation conducted before
this branch existed. Treat it as a starting index, not the full record — the
original conversation transcripts contain the complete evidence trail,
including corrections made across rounds (see `decision_log.md` for what
changed and why).

## Branch topology (git facts)

- `origin/junjiebranch` HEAD: `2528c1c4120fd709c6ca2ee37a5ac777f03783de`
  (2026-09-07, "Operator control gate audit + documentation reduction closure").
- `origin/ola-branch` HEAD: `5014fc8f479c058904e7e69f2f67384851ab88ce`
  (2026-09-30, "Add real TEC connection, Z stack, and batch preflight controls").
- `git merge-base origin/junjiebranch origin/ola-branch` = `2528c1c` itself:
  **junjiebranch's tip is a direct ancestor of ola-branch**. ola-branch is not
  an independent rewrite from `main` — it is junjiebranch's full history,
  followed by an 88-commit rewrite (`git diff origin/junjiebranch
  origin/ola-branch --stat`: 2374 files changed, +35,113/-84,152 lines).
- `main` HEAD: `aa7b954a5432821a5191102aa161cd0c98f6e75c` (2026-06-25) — ancestor
  of both branches; not otherwise involved in this integration.

## AGENTS.md diff at the two target commits (Phase 0 deliverable — not modified)

Diffed `junjiebranch:AGENTS.md` (`2528c1c`) against `ola-branch:AGENTS.md`
(`5014fc8`); confirmed byte-identical to `ola-branch:AGENTS.md` at `f381796`
(no AGENTS.md change in the last ola-branch commit).

- junjiebranch's `AGENTS.md` (101 lines) is an elaborate "Repository Working
  Contract": authority/conflict-resolution rules, a layered session-reading
  order, a `tools/audit_change_surface.py` requirement for shared-runtime
  changes, an explicit V1/V3 UI-surface ownership map (`qt_ui.py` vs
  `qt_ui_v3.py`), and concurrent-worktree rules.
- ola-branch's `AGENTS.md` (29 lines, the file this worktree now has) is a
  short, generic "Working rules" file — the product of commit
  `c747419 "Simplify agent instructions and retire LabVIEW screenshots"`.
- **Not modified this round or any prior round.** This diff is reported, not
  acted on, per explicit instruction every round.

## Architecture summary (ola-branch, this branch's starting point)

`main.py` -> `DeviceRegistry` (one `QThread` per device: AD2/Pump/Valve/
Camera/TEC/Z-stage, `hal/registry.py`) -> `DeviceWorker.execute()`/
`execute_urgent()` (`hal/base.py`) -> `ApplicationController.submit()`
(`application/controller.py`) -> UI only ever calls
`controller.submit(command)` (`ui/main_window.py:257`); `ui/device_panels.py`
imports only `application.commands`/`domain.models`, never a driver.

Automated batch experiments: `application/experiment_runner.py`'s
`ExperimentManager` (queue/start/stop_after_current/abort/panic_abort),
built on typed commands dispatched through the same per-device workers.

Pump/valve resource-holding during a flush is a dedicated state machine,
`application/workflows.py`'s `FlushWorkflow`, not a generic mutex — see
`decision_log.md` for the corrected analysis of how it confirms valve
position (timeout + recovery) and where its pump-capacity check actually is
weak.

## junjiebranch-specific findings (condensed)

- junjiebranch's manual/service device-control dispatch
  (`qt_ui.py`/`qt_ui_v3.py`) is built around one global `_busy_count`/
  `_run_action(resource=...)` mutex (`qt_ui.py:791,5340`), with a
  resource-tag overlay added for Pump/Valve only in commit `56386f1`
  ("Real Shakedown Round 2"). Camera/Z/TEC remain globally gated; that
  commit's own text states their independence "was not investigated or
  evidenced." Confirmed still the live architecture at HEAD (`2528c1c`):
  34 call sites in `qt_ui.py`, 11 in `qt_ui_v3.py`, and `qt_ui_v3.py`'s
  `MainWindowV3Compatibility` inherits directly from `qt_ui.MainWindow`
  (`qt_ui_v3_support.py:203`).
- This defect is confined to the **manual-dispatch UI layer**. The automated
  experiment engine (`workflows.py`: `Experiment2`, `ExperimentSeries2`,
  `TemperatureSeries`, `SeriesLifecycleManifest`) has **zero references** to
  `_busy_count`/`_run_action`/`QThread` (grep-confirmed) — it is portable,
  reusable algorithm code, not coupled to the broken dispatch pattern.
- Four concrete base-flow bugs were found via real hardware shakedown and
  fixed within junjiebranch's own history, **before** HEAD `2528c1c`:
  1. Stale cached pump fill-level exceeding just-configured syringe capacity
     -> real `-513` SDK rejection (fixed `430893a`, `known_capacity_ml`
     guard in `application.py:1149-1156`, source field in
     `instruments.py:845,981`). The underlying device/SDK behavior question
     (`HW-PUMP-FILL-GEOMETRY-001`) is still open in junjiebranch's own docs.
  2. A non-exceptional flush failure (`wait_for_pump()` timeout returning
     `False` without raising) was invisible to the execution indicator
     (fixed `430893a`).
  3. "Stop pump" silently no-op'd behind the global busy guard (fixed
     `430893a`, via `_run_action(force=True)`); the fix's own thread-safety
     is explicitly marked unverified (`UI-PUMP-STOP-THREAD-SAFETY-001`,
     not found closed by any later commit through HEAD).
  4. A real AD2 Channel-0 continuous-output misconfiguration surfaced too
     late (deep inside `STEP_INITIALIZE_EXPERIMENT`) and too vaguely (fixed
     `56386f1`, moved to preflight in `experiment_planning.py`'s
     `build_independent_run_plan()`).
- Real-hardware evidence read directly off disk (gitignored, untracked,
  still physically present in the original working tree):
  `logs/hardware_transactions.log` (root, 20,173 lines, 2026-07-30 to
  2026-09-07, junjiebranch era) contains 305 non-OK lines, including real
  Hamamatsu camera faults/timeouts and a real Thorlabs piezo connect
  failure (`FAIL cmd='44533854' error=Failed to connect... Device is not
  connected`). **This single FAIL line must not be read as "Z-stage never
  worked on junjiebranch"** — it is one entry from a broad 2-month,
  305-non-OK-line window, and `docs/claude_code_change_log.md`'s own
  Session 45-48 (standalone PPC001 verification, driver wrapper, a real
  bug found and fixed) and Session 54 (the same real scan repeated
  through the UI, plus a real mid-scan abort) show the device later
  connecting and scanning successfully, dated after this log's window
  closes (2026-09-07). Likely an earlier-session wiring/driver state this
  log's window happens to include, not a standing failure — see the
  "ola-branch-specific findings" section below for the corrected summary
  and `known_open_items.md`'s Stage 1 Z-stage entry for what this means
  for this branch.

## ola-branch-specific findings (condensed)

- TEC and Z-stage are **not absent** from ola-branch (an earlier investigation
  round's premise was corrected after direct code review): driver, HAL
  worker, UI panel, and automated-experiment-node integration all exist —
  `drivers/tec/controller.py`, `hal/tec.py`, `ui/device_panels.py:1847
  TecPanel`, `experiment_runner.py:865-874` dispatching
  `TEC_SETPOINTS_APPLY`/`TEC_WAIT_STABLE`/`Z_STAGE_POSITION_SET` as batch
  nodes. What is genuinely missing is junjiebranch's richer
  `TemperatureSeries` multi-point scan algorithm, and any real-hardware log
  evidence of TEC output or Z-stage motion.
- Real-hardware evidence read directly off disk, ola-branch era:
  `logs/20260925T132740877811Z_real/hardware_transactions.log` (34,671
  lines, 2026-09-25, 72-minute session): pump bus open/select/enable/
  configure, 17,322 status polls, 8,661 fill-level reads (constant at
  1.068 mL throughout — no real motion exercised), valve connect + 8,657
  polls + close, camera open/close, AD2 `configure_wfg`/stop/reset/close —
  **zero FAIL lines**. A second log
  (`logs/20260925T144218712126Z_real/hardware_transactions.log`, 98 lines)
  shows a **real physical valve transition**: `write cmd='P01'` ->
  `query resp='01\r'`, and the reverse for P02. **No TEC or Z-stage
  real-hardware log entries exist in ola-branch's own logs.** (This is
  about ola-branch's own log files specifically, not a claim that no such
  evidence exists anywhere: junjiebranch has real Z-stage motion evidence
  in its own change log — `claude_code_change_log.md` Sessions 45-48/54 —
  described above and corrected in `acceptance_table.md`/
  `known_open_items.md`. **TEC — correcting another overstatement**: a
  prior pass here claimed junjiebranch's "MeCom/TEC protocol was never
  implemented," citing Session 54's remark that no reviewed protocol
  existed *at that point in the project's history* to test COM4/COM6
  against. That was true only as of Session 54. junjiebranch's
  `docs/tec_verification_matrix.md` (Sessions 75-77, dated after Session
  54) shows a real, reviewed `_PyMeComTecClient` (pyMeCom's `MeComSerial`)
  was built, with **independently retained** real-hardware evidence from
  2026-08-28: real read-only queries (Device Status=104, Object
  Temperature=1000, Output Enable Status=2010, both channels at plausible
  room temperature) plus one authorized write — parameter 2010 set to 0
  (Static OFF) on both channels, confirmed by real readback, client closed
  cleanly. That document is explicit that this narrow read+OFF-write
  record is the only evidence it still treats as solid; broader Session
  75-77 claims (real setpoint writes, "immediate thermal response") are
  self-reported and marked **not** independently reproducible, and real
  TEC *operation* (setpoint writes, Static ON) was left formally
  unapproved pending bench review. The same real client class exists in
  this branch too — `drivers/tec/controller.py`'s `_PyMeComTecClient`
  carries the identical 5-parameter allow-list (104/105/1000/2010/3000),
  the same "Target Object Temperature" naming fix, and the same
  write-restricted-to-2010/3000 discipline, confirmed by direct code
  read; it was ported, not reinvented. **Net correction**: TEC is not "no
  protocol ever built" — it is "a real, reviewed protocol client exists
  on both branches, with narrow retained real-hardware read/OFF-write
  evidence on junjiebranch and none yet on this branch; real *setpoint*
  operation remains unauthorized/unverified on both," per
  `acceptance_table.md`'s corrected TEC row.)
- `ui/z_stack_panel.py` was compared field-by-field against junjiebranch's
  Z-Scan tab this round: ola's panel already has start/stop Z, points,
  step, exposure, 4-field ROI, position tolerance, position timeout, output
  folder, manual jog, live preview, and camera-settings import — a superset
  of junjiebranch's tab fields. **No Z-axis UI gap found.**
- `application/event_formatting.py:42 event_summary()`'s `"failed"` branch
  already renders `f"{subject} — failed: {event.message}"`, with
  `event.message` always populated from `command_failed.emit(request_id,
  str(exc))` (`hal/base.py`) — the bare-"Error" bug junjiebranch fixed in
  `56386f1` cannot occur here by construction. **No fault-message gap
  found.**

See `decision_log.md` for what to actually do about the remaining,
precisely-scoped gaps, and `migration_checklist.md` for the per-module
tracking table.

## 2026-10-25 — System survey (junjiebranch `2528c1c` vs `codex/integration`)

Method: six read-only passes (task domains, per-device, cross-device flow) plus
simulation/fake-device runs; no hardware, no `reference/old-ui`. Tags as in
`known_open_items.md` ("System survey" section, findings S1–S13).

**Coverage by level**
- *Investigated with evidence this round:* device preparation/recovery, manual
  panels, settings save/load, orchestration, scan/temperature, repeat/flush,
  acquisition/saving, status/stop/exit, result use, camera viewer; all six
  registered devices (AD2, PUMP, VALVE, CAMERA, TEC, Z_STAGE) — capabilities,
  reachability, readback, behaviour on completion/fault/stop/abort/exit; the
  representative flow (prepare → TEC → camera/AD2 arm → trigger/capture →
  save/flush → next → wrap-up) with failure injection per device [SIM].
- *Carried from earlier rounds (not redone):* Z-algorithm parity, TEC protocol
  client, AD2 JP4/JP5, flush-workflow guards, settings-profile design.
- *Not investigated:* vendor SDK internals; TEC MeCom reconnect internals;
  Z-stack interaction with a running series; most of junjie's 8,103-line change
  log (about 25 sessions read); `tec_verification_matrix.md` (via summary only);
  real `MainWindow.closeEvent` under failure (controller called directly);
  real-hardware behaviour of any integrated path.
- External dependencies: LabVIEW analysis VI / TDMS (need unchecked), vendor
  SDKs/DLLs (Qmix, DCAM, WaveForms, Thorlabs .NET, pyMeCom). Laser, LED,
  ultrasound amplifier and camera trigger all run through the AD2. The pump has
  a built-in valve and a multi-unit bank (ola-side only).

**Devices (one line each; see S-items for gaps)**

| Device | Reachable from | Automated use | End states | vs junjie |
|---|---|---|---|---|
| Pump | PumpPanel, console | initial/post flush, capacity check | stop on abort/panic/exit; flush failure → stop + confirm idle + close valve | ported + stronger recovery; S1, S3, S4 |
| Valve | ValvePanel | flush sequencing, readback-confirmed | closed after flush recovery; left open on panic/exit mid-flush | ported; stronger readiness check; labels unverified |
| Camera | CameraPanel + viewer; configure/arm/collect engine-only | timing + exposure checks, arm, collect, save | preview running after normal end; stopped after abort/panic/exit | near-verbatim port; S5 |
| AD2 | scope/wave/DIO panels; experiment DIO program engine-only | waveform + DIO trigger, achieved-rate poll | cleanup stops W1/W2/DO; safe_stop sequential (S6) | ported; polls completion where junjie waits a fixed time |
| TEC | TecPanel | set, wait stable, hold | stays on after run/abort; off on panic/exit | ported; after-run policy open |
| Z stage | Z panel/stack; `stage_move` hand-written steps only | not in simple series | exit stops | ported incl. Decimal fix; S7 |

**Cross-device flow [CODE]+[SIM]**: one command lane serialises all device
commands; true parallelism only for file save, AD2 status polling and the
flush workflow; `tec_wait_stable` holds the lane. Camera/AD2 are configured and
validated (achieved AD2 rate, read-back exposure) before any fluidics. Manual
commands are rejected while a run is active (manual TEC set / pump refill
rejected; reads and SAFE_STOP accepted); a manual AD2 waveform running at start
fails the series before fluidics. Any single-device failure kept earlier
experiments' data and discarded only the unfinished folder; `_fail` sends
SAFE_STOP to camera and AD2 only. ola's order and barrier semantics are
preserved; junjie's flush/save overlap, initial flush, flush guards,
applied-exposure check and TEC partial-apply cleanup are adapted (counterparts
below). Requested vs applied: AD2 achieved rate and camera exposure read-back
feed later steps once per series; camera ROI snap and TEC set-point are not fed
back (S9).

**Traceability (selected; source → problem → later correction → applicability → integration counterpart → disposition)**

| Source | Problem | Later correction | Applies now | Integration counterpart | Disposition |
|---|---|---|---|---|---|
| `qmix_backend.py` init gates | enabling pump with fault / position sensing off | auto-clear on init replaced manual clear (`bcd1634`, reversing Session 104) | yes | `drivers/pump/cetoni.py:186,244` | retained; tests missing (S12) |
| junjie valve handshake (`instruments.py`) | partial open, bare replies | rollback + strict parse | yes | `drivers/valve/serial_valve.py` | retained, stronger |
| DCAM open rollback, timeout buffer release, exposure 15.0→15.00025 (Session 54) | leaked API init, unquantised exposure | — | yes | `drivers/camera/hamamatsu.py`; applied-exposure check in `_configure_all_before_fluidics` | retained |
| flush timeout minutes→seconds (Sessions 31–33) | spurious flush timeouts | — | yes | `workflows.py` `travel_s = volume*1000/flow*60 + 10` | retained |
| flush over-draw guard (Session 54) | target < 0 | — | yes | `FlushWorkflow._implausible_reading`, target<0 reject | retained |
| abort policy (Session 78) | dead mid-repeat abort checks | hard-stop abort removed by owner | yes | `stop_after_current` (+ `abort`, `panic_stop`) | retained, superset |
| `430893a` urgent stop | Stop pump ignored while busy | — | yes | `controller._is_urgent` / `hal/base.execute_urgent` | retained |
| `c58e092` TEC off on close | TEC left regulating | — | yes | `drivers/tec/controller.py:406` cleanup | retained; after-run policy open |
| Piezo `System.Decimal` fix | `float()` failure | — | yes | `thorlabs_piezo._decimal_to_float` | retained |
| `application.py` flush thread + save | overlap flush and save | — | yes | runner parallel save/flush block | adapted (flow_trace corrected) |
| partial-capture preservation | keep frames of failed acquisition | ola `f717884` discards | no (deliberately overturned) | dead `partial_capture_folder` code in `hamamatsu.py:463-523` | dropped; doc fixed; dead code → your call |
| `66016bd` elapsed / time left | planning long series | — | maybe | none | S13, optional |
| TDMS `GitCommitHash`, `sim_*` flags | provenance of data | — | yes | none | S9 |
| `hardware_factory` COM6 reject (`7a2ef57`, `a0a2de2`) | valve opened on TEC port | — | yes (generic form) | none | S11 |
| settings auto-save/load | convenience | hardware_tests/README: tests must not reuse persisted UI | no | explicit, validated, all-or-nothing profile (`main_window.save_profile/load_profile`) | intentionally different |
| `ARCH-PERSISTENCE-001` (hardware profile vs protocol split) | settings granularity | unlanded | partly | all-or-nothing profile | defer |
| `experiment_presets.py` LabVIEW values (ROI 2304×740@y792, 40 ms, 20 fps…) | working defaults | referenced by junjie tests/UI | data only | none | defer; profile JSON if wanted |
| W2 refusal in junjie planner (`HW-LASER-PATH-001`) | laser input polarity | — | yes | integration drives W2 at 5 V | policy question |
| commissioning trace / evidence taxonomy | audit framework | — | no | event messages (`event_formatting.py`), `CAMERA_SETTINGS_READ` | not adopted; the readback and error-reason parts exist as named |
| junjie `ImagePreviewWindow` (Full / 90% / Fixed / Downshift) | display range | — | yes | `widgets.py` `CameraImageWindow` | adapted; per-frame percentile and downshift deferred |
