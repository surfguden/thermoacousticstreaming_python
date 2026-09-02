# Project Control

Small current-state dashboard. Detailed evidence and closure criteria remain in
[`known_open_items.md`](known_open_items.md) and the linked hardware truth
records; this page does not replace them.

## CURRENT MILESTONE

The software architecture is frozen at
`1ef76949ef7f5216a9b0ed2f540dd1cc171cc1ed` after adversarial verification.
Normal production Start
uses the shared independent planner: `ExperimentRequest` is the canonical
normalized request, immutable `RunPlan`/`RunCondition` hold software planning
truth, and `legacy_series_from_run_plan()` is the compatibility boundary into
the retained `Experiment2` runtime. The legacy builder remains an explicit
rollback-only path and is not concurrently authoritative. Physical camera
trigger timing remains explicitly deferred.

Current operator surfaces:

| Surface | Repository and launcher role |
| --- | --- |
| v1 | Tracked default operator UI; `launch_gui.bat` / `tools/run_ui.py` |
| v2 | Tracked rollback/reference transitional UI; `launch_gui_v2.bat` / `tools/run_ui_v2.py` |
| v3 | Tracked opt-in UI, not independently hardware-verified; `launch_gui_v3.bat` / `tools/run_ui_v3.py` |

## ACTIVE

- No active software architecture change; the freeze remains in force.

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
  unknown physical syringe/loading/travel and fluid-route state. H2B closed the
  startup recovery question without enabling or moving the pump. Advancement
  still requires physical readiness evidence and separately approved
  reference, fill-truth, stop-latency, and bounded-motion stages.

## VERIFYING

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

- **HW-QMIX-CAN-001 — startup/no-motion recovery:** H2B issued exactly one
  accepted `LCP_ClearFault` per trial in five trials. Pre-clear fault was true
  in 5/5; clear succeeded, fault became false immediately, remained false at
  +0.5/+1.5/+3.0 seconds, enabled/pumping remained false, and stop/close was
  clean in 5/5. H2A's pre-clear startup communication events remain valid;
  H2B observed clear-associated `0x0000` recovery and no post-clear nonzero
  emergency. This is no-motion recovery evidence, not pump-motion authorization
  or a physical termination/root-cause finding.
- **ARCH-PREFLIGHT-001:** normal Start now uses the independent
  `ExperimentRequest` -> `RunPlan`/`RunCondition` path and the legacy builder is
  rollback-only; v3 `BuildResult` remains presentation/audit derivation.

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

The independent request/plan DTO and legacy-adapter seam has immutable
planning data, a bounded semantic-equivalence matrix, and a series-local
lifecycle manifest. V3's older `BuildResult`/shadow-preflight is retained for
presentation and audit derivation only. Software architecture remains frozen.
The next Qmix checkpoint is a no-command, operator-visible confirmation of the
installed syringe identity/geometry, loading, available travel, tubing route,
and harmless destination. Powered-down termination/CAN-path work is deferred
unless recovery later fails or relatches. Do not enable, reference, or move the
pump without a separate later authorization.
**HW-TIMING-001** remains deferred / ready for physical verification; do not
enable AD2 output as part of this software work.
