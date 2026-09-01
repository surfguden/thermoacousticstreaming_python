# Project Control

Small current-state dashboard. Detailed evidence and closure criteria remain in
[`known_open_items.md`](known_open_items.md) and the linked hardware truth
records; this page does not replace them.

## CURRENT MILESTONE

The software checkpoint is restored: offline CI is green at the deterministic
test fix (`525894f`) and the rules/project-control checkpoint (`da4a790`).
Engineering control is in maintenance mode. The active mainline is offline
software consistency; camera visibility is restored, but physical trigger
timing is not yet verified and is explicitly deferred.

Current operator surfaces:

| Surface | Repository and launcher role |
| --- | --- |
| v1 | Tracked default operator UI; `launch_gui.bat` / `tools/run_ui.py` |
| v2 | Tracked rollback/reference transitional UI; `launch_gui_v2.bat` / `tools/run_ui_v2.py` |
| v3 | Tracked opt-in UI, not independently hardware-verified; `launch_gui_v3.bat` / `tools/run_ui_v3.py` |

## ACTIVE

- **HW-QMIX-CAN-001:** narrow passive CAN/controller state without pump motion.

## READY

- **HW-TIMING-001:** Windows PnP, the vendor sample, and the repository backend
  now see camera `C15440-20UP` / `S/N: 500478`; a clean read-only open/close
  succeeded. Vendor documentation now identifies AD2 `W1`, AD2 `DIO1`, and the
  camera's SMA `TIMING 1/2/3` outputs and their electrical levels. A bounded
  read-only camera probe found all three timing outputs configured as fixed
  `LOW`; none is currently an exposure monitor. The first capture uses an
  operator-controlled external oscilloscope with one common timebase and three
  simultaneous inputs: CH1 DIO1, CH2 W1, and CH3 Camera TIMING 1; CH4 is unused.
  Repository-controlled scope acquisition is not required. The capture remains
  ready only after the operator identifies the scope and confirms wiring/load,
  then approves a temporary camera timing-output configuration that will be
  restored after the capture.

## BLOCKED

- **HW-VALVE-001:** physical routing awaits a safe, operator-visible harmless
  observation path.
- **HW-PUMP-MOTION-001:** reference, fill, and motion remain blocked by
  **HW-QMIX-CAN-001**. Advancement requires reviewed single-client ownership,
  fault-free no-motion transport trials, known physical syringe/loading and
  fluid-route state, and a separately approved stop-latency/reference/fill
  verification plan before any bounded motion.

## VERIFYING

- **ARCH-PREFLIGHT-001:** shared planning remains a shadow path; the production
  builder is authoritative.
- **TEST-QT-LIFETIME-001:** the open-ended PySide/Shiboken lifetime family remains
  informationally marked, not retried, skipped, or hidden.

## DEFERRED

- **HW-TIMING-001 — DEFERRED / READY FOR PHYSICAL VERIFICATION:** software
  timing paths are traced and the bounded measurement plan is ready, but
  physical AD2/DIO1/camera timing remains unverified. This does not block
  ordinary software development; it blocks any claim that AD2, DIO1, and
  camera exposure are physically synchronized. The eventual capture uses an
  operator-controlled external oscilloscope; repository-controlled scope
  acquisition is not required.
- **ARCH-PERSISTENCE-001:** the hardware-profile/protocol split waits for shared
  planning contracts to stabilize.

## RECENTLY CLOSED

- Injected WaveForms startup no longer requires the vendor DLL (`ba25e27`).
- Z-Scan now reuses the initialized Application-owned configured Thorlabs
  stage; no independent default-stage discovery or scan-owned disconnect
  remains (`42fee3b`, `df50083`). Physical Z-stage operation remains
  unverified.
- The serial blocking regression test no longer depends on scheduler timing
  (`525894f`); its pushed offline workflow is green.
- **HW-TEC-001:** the authorized real Static OFF path wrote only parameter 2010
  value 0 to both channels, read both back OFF, and closed cleanly.

## NEXT CHECKPOINT

The next technical checkpoint is **BuildResult independent request/plan DTO and
legacy-adapter prototype**. It must remain offline and shadow-only until all UI
versions share one independent constructor with equivalence and rollback
evidence. **HW-TIMING-001** remains deferred / ready for physical verification;
do not enable AD2 output as part of this software work.
