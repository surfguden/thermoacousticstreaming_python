# Project Control

Small current-state dashboard. Detailed evidence and closure criteria remain in
[`known_open_items.md`](known_open_items.md) and the linked hardware truth
records; this page does not replace them.

## CURRENT MILESTONE

Restore the software checkpoint, then resume the hardware-truth mainline.
Offline CI is green at `525894f`; the rules/project-control checkpoint must also
pass offline CI before any live hardware step. Engineering-control work is then
in maintenance mode unless a demonstrated failure requires another change.

Current operator surfaces:

| Surface | Repository and launcher role |
| --- | --- |
| v1 | Tracked default operator UI; `launch_gui.bat` / `tools/run_ui.py` |
| v2 | Tracked rollback/reference transitional UI; `launch_gui_v2.bat` / `tools/run_ui_v2.py` |
| v3 | Tracked opt-in UI, not independently hardware-verified; `launch_gui_v3.bat` / `tools/run_ui_v3.py` |

## ACTIVE

- **HW-TIMING-001:** restore passive camera visibility before trigger-timing work.
- **HW-QMIX-CAN-001:** narrow passive CAN/controller state without pump motion.
- **HW-TEC-001:** retain read-only evidence and prepare OFF-only verification.

## READY

- **HW-TIMING-001:** camera power/interface, DCAM enumeration, vendor visibility,
  process ownership, runtime path, and a clean vendor open/close cycle may be
  checked passively after the software gate.

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

## NEXT CHECKPOINT

Push the rules/project-control commit and require green offline CI. The next
technical checkpoint is **HW-TIMING-001** camera visibility only; do not change
trigger semantics or enable AD2 output while visibility is unresolved.
