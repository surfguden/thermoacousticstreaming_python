# Project Control

Small current-state dashboard. Detailed evidence and closure criteria remain in
[`known_open_items.md`](known_open_items.md) and the linked hardware truth
records; this page does not replace them.

## CURRENT MILESTONE

The software checkpoint is restored: offline CI is green at the deterministic
test fix (`525894f`) and the rules/project-control checkpoint (`da4a790`).
Engineering control is in maintenance mode. The active mainline is hardware
truth; camera visibility is restored, but physical trigger timing is not yet
verified.

Current operator surfaces:

| Surface | Repository and launcher role |
| --- | --- |
| v1 | Tracked default operator UI; `launch_gui.bat` / `tools/run_ui.py` |
| v2 | Tracked rollback/reference transitional UI; `launch_gui_v2.bat` / `tools/run_ui_v2.py` |
| v3 | Tracked opt-in UI, not independently hardware-verified; `launch_gui_v3.bat` / `tools/run_ui_v3.py` |

## ACTIVE

- **HW-TIMING-001:** confirm scope wiring, then run the prepared bounded physical
  trigger-timing diagnostic.
- **HW-QMIX-CAN-001:** narrow passive CAN/controller state without pump motion.

## READY

- **HW-TIMING-001:** Windows PnP, the vendor sample, and the repository backend
  now see camera `C15440-20UP` / `S/N: 500478`; a clean read-only open/close
  succeeded. The later low-output capture is ready only after an operator
  confirms the exact scope wiring and load.

## BLOCKED

- **HW-VALVE-001:** physical routing awaits a safe, operator-visible harmless
  observation path.
- **HW-PUMP-MOTION-001:** reference, fill, and motion remain blocked by
  **HW-QMIX-CAN-001**.

## VERIFYING

- **ARCH-PREFLIGHT-001:** shared planning remains a shadow path; the production
  builder is authoritative.
- **TEST-QT-LIFETIME-001:** the open-ended PySide/Shiboken lifetime family remains
  informationally marked, not retried, skipped, or hidden.

## DEFERRED

- **ARCH-PERSISTENCE-001:** the hardware-profile/protocol split waits for shared
  planning contracts to stabilize.

## RECENTLY CLOSED

- Injected WaveForms startup no longer requires the vendor DLL (`ba25e27`).
- The serial blocking regression test no longer depends on scheduler timing
  (`525894f`); its pushed offline workflow is green.
- **HW-TEC-001:** the authorized real Static OFF path wrote only parameter 2010
  value 0 to both channels, read both back OFF, and closed cleanly.

## NEXT CHECKPOINT

The next technical checkpoint is **HW-TIMING-001**: operator-confirmed scope
wiring followed by the already-prepared bounded timing capture. Do not infer a
timing result from restored camera visibility, and do not enable AD2 output
without that physical setup confirmation.
