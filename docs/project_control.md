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
trigger timing remains explicitly deferred. Normal production plans now carry
an explicit disabled DIO1/DO Clock payload, and `Application.run_experiment2()`
does not program the retained legacy DO-clock helper. Normal camera acquisition
now carries an explicit requested ROI through that same plan, applies it before
sequence configuration, forces a fresh DCAM ROI readback, and saves the applied
ROI. Normal enabled CH0 requires `Repeat=1`; FM Sweep conflicts with Frequency
Scan and requires an explicitly enabled/running CH0, all checked before AD2
configuration.

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
| Valve | CONFIGURED CURRENT / OWNER-SUPPLIED ROUTE TRUTH | Current repository path uses serial `COM5`, 19200 baud, MX Series II protocol family, status `S`, and direct software mapping position 1 -> `P01`, position 2 -> `P02`. The owner identifies position 1 / `P01` as the through-chip liquid-exchange path and position 2 / `P02` as the chip-bypass path | Exact physical SKU and independent physical observation of each commanded route remain unverified; owner-supplied routing truth, protocol acknowledgement, and physical verification remain distinct |
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

- **SW-ACQ-DETERMINISM-001:** the camera+AD2 normal path is offline-ready for a
  separately authorized minimal experiment. Requested ROI is distinct from
  fresh applied ROI metadata; CH0 Repeat must equal 1; FM Sweep cannot coexist
  with Frequency Scan and cannot auto-enable CH0. This is software/fake-test
  readiness only and does not authorize a camera or AD2 session.

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
  restored after the capture and a separately authorized diagnostic source for
  DIO1. Normal production runs no longer produce DIO1.

## BLOCKED

- **HW-PUMP-MOTION-001:** reference, fill, and motion remain blocked by
  unknown physical syringe/loading/travel and fluid-route state. H2B closed the
  startup recovery question without enabling or moving the pump. The Low
  Pressure pump uses incremental position sensing: H1 read
  `position_sensing_initialized=true` in 5/5 trials, which establishes that
  the counter was initialized in that powered session, not that it survives a
  later power cycle. Production initialization now reads that flag freshly
  after fault recovery and before enable; `false` fails closed without enable,
  reference/calibration, counter restore, fill/flow, or motion. The flush path
  now issues exactly one target command between confirmed P01 and P02 routes.
  Production `reference_move()` still raises on its 60-second timeout without
  issuing `stop_pumping()`. Advancement therefore still requires the
  no-command physical readiness inspection, a separately authorized fresh
  connection/readiness result, reviewed reference-stop behavior if reference
  is actually needed, and separate fill-truth, stop-latency, and bounded-motion
  stages.

## VERIFYING

- **TEST-QT-LIFETIME-001:** the open-ended PySide/Shiboken lifetime family remains
  informationally marked, not retried, skipped, or hidden.

## DEFERRED

- **HW-TIMING-001 — DEFERRED / READY FOR PHYSICAL VERIFICATION:** software
  timing paths are traced and the bounded measurement plan is ready, but
  physical AD2/DIO1/camera timing remains unverified. This does not block
  ordinary software development; it blocks any claim that AD2, DIO1, and
  camera exposure are physically synchronized. Normal production DIO1 is now
  explicitly disabled; any eventual DIO1 capture therefore requires a separate
  diagnostic authorization. The capture uses an operator-controlled external
  oscilloscope; repository-controlled scope acquisition is not required.
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
- **Pump software alignment:** Qmix initialization now requires a fresh
  `is_position_sensing_initialized()` result after fault recovery and before
  enable, failing closed on `false`; flush now emits one pump target command,
  not a second same-target command after P02. These are offline-verified
  software safeguards and do not authorize hardware access or motion.
- **Native Qmix load-path diagnosis:** the attempted passive readiness helper
  stopped before `Bus.open()` because the Codex filesystem sandbox denied even
  byte-level reads of `labbCAN_Bus_API.dll`. The same 64-bit Python 3.13
  executable and existing `import_qmix()`/`os.add_dll_directory()` path loaded
  the bus and pump bindings successfully outside the sandbox. DLL ACLs grant
  the signed-in user full control and all native dependencies resolved. No
  vendor reinstall, ACL change, repository loader change, or live Qmix session
  was needed. A later passive snapshot remains separately authorized hardware
  work and must run outside the filesystem sandbox.
- **Normal experiment DIO1 removal:** the shared planner emits an explicit
  disabled DO payload and `Application.run_experiment2()` configures CH0 WFG
  without calling `config_do_clock_special()`. Legacy/manual DO helpers remain.
- **Deterministic normal acquisition:** ROI is planned, explicitly configured,
  freshly read back, cached as applied state, and saved after capture. New CH0
  normal experiments default to `Repeat=1`; persisted `Repeat=0` remains
  unchanged and fails preflight. Repeat values other than 1, combined FM
  Sweep/Frequency Scan, and FM Sweep without explicit CH0 enable/running state
  all fail before AD2 configuration.
- **Laser provenance correction:** source and Git-history review establish AD2
  WFG CH0 as the acoustic actuation path, but no independent laser backend or
  gate field exists. The historical `--include-ad2-laser` smoke flag changed
  prose only; it now fails before hardware setup instead of claiming control.
  The laser gate is **OWNER/PHYSICAL WIRING CONFIRMATION REQUIRED**. This does
  not block camera+acoustic-only testing with manual alignment and fixed manual
  optical power; software must not claim independent laser gating. The retained
  LED/green-wire WFG CH0 candidate is likewise blocked from real execution
  until its physical route is confirmed.
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
and harmless destination. After that, a fresh position-sensing snapshot must
decide whether reference is necessary; the historical `true` result is not
portable across unknown power history, and the production gate will now refuse
enable on `false`. The duplicate flush command is resolved in software.
Powered-down termination/CAN-path work is deferred unless recovery later fails
or relatches. Do not enable, reference, or move the pump without a separate
later authorization.
**HW-TIMING-001** remains deferred / ready for physical verification; do not
enable AD2 output as part of this software work. Normal production DIO1 is
disabled.

The next minimal camera+AD2 fast-sweep experiment is
**READY_FOR_SEPARATE_HARDWARE_AUTHORIZATION** provided CH0 is explicitly
enabled with `Repeat=1`, Frequency Scan is off, the finite run duration covers
acquisition, and the operator confirms the requested ROI/exposure/amplitude.
Laser operation remains manual/fixed-power unless its gate wiring is separately
confirmed; no software-controlled laser-gate claim is permitted.
