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

## CURRENT HARDWARE INVENTORY

This is the single current hardware inventory. Detailed truth records retain
their point-in-time evidence but do not form competing current inventories.
`CONFIRMED CURRENT` requires a present physical label, live read-only
enumeration, current repository configuration, or exact applicable vendor
documentation. Remembered and historical identities remain `CANDIDATE` until
such evidence is obtained. Confirmation should be gathered opportunistically
during the next separately authorized device-specific validation, not through
a standalone full-hardware audit. Last reconciled: 2026-09-02.

| Subsystem | Current classification | Identity and current evidence | Still unresolved |
| --- | --- | --- | --- |
| Waveform generator | CONFIRMED CURRENT — device identity | Digilent Analog Discovery 2 using the WaveForms SDK; live read-only WaveForms enumeration on 2026-08-28 found one unopened device, `SN:210321A18CE2` | Physical USB route and waveform/trigger timing are unverified; no output is authorized by inventory status |
| Camera | CONFIRMED CURRENT — enumerated model; family name retained separately | Hamamatsu `C15440-20UP`, `S/N: 500478`, confirmed by current Windows PnP and read-only DCAM enumeration/open-close. `ORCA-Fusion BT` is the candidate family/product name associated with this model | Physical USB route is not currently traced; timing/output behavior remains unverified |
| Pump | CONFIRMED CURRENT — physical module label and logical node | CETONI label strings preserved exactly: `Niederdruckmodul / Low-pressure module 14:1`, `NEM-B101-02 E 5`, `CET-003455-1505`. Logical enumeration: `neMESYS_Low_Pressure_1_Pump`, node 2. H2B confirmed stable clear-fault/no-motion recovery | Do not reinterpret either identifier as article or serial number. Exact base type, base serial, integrated Ixxat article/serial/firmware, syringe/loading/travel, fluid route, and termination remain unknown |
| Valve | CONFIGURED CURRENT / PHYSICAL CANDIDATE | Current repository path uses serial `COM5`, 19200 baud, MX Series II protocol family, status `S`, and current `P01`/`P02` command semantics | Exact physical SKU and the fluidic meaning of P01/P02 remain unverified |
| Z stage | CANDIDATE — live re-verification required | Thorlabs `PPC001` controller driving `PFM450E`; candidate controller serial `44533854`, consistent with current repository configuration and retained historical discovery | Do not promote to current physical truth until the controller/stage identity and serial are re-enumerated during an authorized Z-stage validation; no motion is implied |
| TEC | CANDIDATE — identity not read in current verification | Meerstetter `TEC 1123-HV`, candidate firmware `5.10`, candidate serial family `509xx`. Current read-only status communication succeeded on COM6, but that probe did not read identity | Current model, exact serial, firmware, and physical USB route require a future authorized read-only identity check; no TEC write is implied |

Current system-level USB topology:

| Path | Classification | Evidence boundary |
| --- | --- | --- |
| PC -> i-tec `U3HUB742` -> white USB cable -> CETONI USB Type-B/base | CONFIRMED CURRENT — physical branch | Direct cable tracing plus current PnP/Qmix evidence supports an Ixxat USB-CAN interface integrated in the CETONI base; this does not identify the exact base or adapter article/serial |
| Pump + AD2 + TEC + PPC001 + valve sharing a two-stage hub path | CANDIDATE | Historical project knowledge only beyond the confirmed pump branch; promote individual branches only when physically traced or confirmed by current PnP parent topology |
| Camera on an independent USB path | CANDIDATE | Current USB3 enumeration confirms the camera endpoint, not its physical independence from the shared hubs |

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
