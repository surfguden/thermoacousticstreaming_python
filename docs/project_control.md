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
configuration. New owner-supplied wiring evidence identifies API channel 1 / W2
as the laser Analog In path; normal production now rejects any enabled carrier
or FM node on that channel before hardware configuration while its exact laser
input semantics remain unresolved.

## CURRENT OWNER-SUPPLIED AD2 WIRING AND VERIFIED SOFTWARE MAPPING

The owner physically inspected and photographed the current wiring on
2026-09-02. The attached green board is consistent with Digilent's official
**BNC Adapter for Analog Discovery**, product SKU `410-263`; it must not be
treated as a generic or custom breakout. The official one-page reference manual
applies to Discovery BNC rev. B, while Digilent's later schematic is document
`500-263`, rev. C.0. The installed PCB's exact revision is not readable from the
evidence available in this workspace and therefore remains unconfirmed.

The same owner-supplied photographs identify the installed laser as a TOPTICA
`iBEAM-SMART-785-S-HP` and the installed camera as a Hamamatsu ORCA-Fusion BT,
model `C15440-20UP`, serial `500478`. These are
`PHOTO_CONFIRMED_IDENTITY`; the laser's Class 3B / `<500 mW` safety marking is
not an experimental optical-power measurement and must not be used as one.

Official Digilent interface facts:

| AD2 signal | Native connector / flywire identity | BNC Adapter disposition |
| --- | --- | --- |
| W1 | Waveform Generator 1 | BNC `J4`, labeled W1; AWG termination selected by `JP4` |
| W2 | Waveform Generator 2 | BNC `J5`, labeled W2; AWG termination selected by `JP5` |
| Scope Ch1 (`1+`) | Oscilloscope channel 1 positive input | Single-ended BNC `J1`, labeled CH1; `1-` is grounded and `JP2` selects AC/DC coupling |
| Scope Ch2 (`2+`) | Oscilloscope channel 2 positive input | Single-ended BNC `J3`, labeled CH2; `2-` is grounded and `JP3` selects AC/DC coupling |
| DIO0 | Digital I/O 0, pink flywire | Passed through to the outer `J6` header; no BNC connector |
| DIO1 | Digital I/O 1, green flywire | Passed through to the outer `J6` header; no BNC connector |
| T1 / T2 | Trigger I/O 1 / 2 | Passed through to the outer `J6` header; no BNC connector |

The official schematic shows that `J6` passes through DIO0--DIO15, T1/T2,
grounds, and the user power-supply rails. W1, W2, and the two scope positive
inputs are diverted to their BNC circuits rather than duplicated at `J6`. The
adapter contains no powered or active signal-processing stage: its schematic
shows routing, grounding, selectable 0.1-uF AC coupling on the scope inputs,
and selectable 49.9-ohm series termination on the AWG outputs.

Current four-layer routing truth:

| SOFTWARE | AD2 HARDWARE | BNC ADAPTER | EXTERNAL DEVICE | Provenance and current state |
| --- | --- | --- | --- | --- |
| Project Ch1: `exp_ch1_*` -> `exp_ad2_channels[0]` -> `WfgChannelConfig.channel_index=0`; WaveForms API index 0 | W1 | W1 BNC `J4`; `JP4` supports 0-ohm or 50-ohm selection, but its installed shunt position is unverified | Acoustic amplifier -> piezoelectric transducer -> acoustic field | `SOFTWARE_MAPPING_VERIFIED`; `OFFICIAL_DIGILENT_CONFIRMED`; `OWNER_SUPPLIED_WIRING`; `PHYSICAL_CONNECTOR_CONFIRMED`; `PHYSICAL_TERMINATION_UNVERIFIED` |
| Project Ch2: `exp_ch2_*` -> `exp_ad2_channels[1]` -> `WfgChannelConfig.channel_index=1`; WaveForms API index 1 | W2 | W2 BNC `J5`; `JP5` supports 0-ohm or 50-ohm selection, but its installed shunt position is unverified | TOPTICA `iBEAM-SMART-785-S-HP` Analog In (SMB) | `SOFTWARE_MAPPING_VERIFIED`; `OFFICIAL_DIGILENT_CONFIRMED`; `OFFICIAL_VENDOR_CONFIRMED`; `OWNER_SUPPLIED_WIRING`; `PHOTO_CONFIRMED_IDENTITY`; `PHYSICAL_CONNECTOR_CONFIRMED`; `PHYSICAL_TERMINATION_UNVERIFIED`; `INPUT_ELECTRICAL_SEMANTICS_UNRESOLVED`; production fails closed pending laser semantics |
| No normal-production DO request | DIO0, pink flywire | `J6` pass-through header; no BNC and no AWG-termination jumper | Hamamatsu ORCA-Fusion BT `C15440-20UP`, S/N `500478`, `EXT.TRIG` input | `OFFICIAL_DIGILENT_CONFIRMED`; `OFFICIAL_VENDOR_CONFIRMED`; `OWNER_SUPPLIED_WIRING`; `PHOTO_CONFIRMED_IDENTITY`; `PHYSICAL_CONNECTOR_CONFIRMED`; `PHYSICAL_TIMING_UNVERIFIED`; `CONNECTED_BUT_CURRENTLY_UNUSED` for the standard internal-trigger run and deferred for transient/synchronized modes |
| Normal-production DO payload disabled | DIO1, green flywire | `J6` pass-through header; no BNC and no AWG-termination jumper | TOPTICA `iBEAM-SMART-785-S-HP` Digital In (SMB) | `OFFICIAL_DIGILENT_CONFIRMED`; `OFFICIAL_VENDOR_CONFIRMED`; `OWNER_SUPPLIED_WIRING`; `PHOTO_CONFIRMED_IDENTITY`; `PHYSICAL_CONNECTOR_CONFIRMED`; `INPUT_ELECTRICAL_SEMANTICS_UNRESOLVED`; `PHYSICAL_TIMING_UNVERIFIED`; connected but unprogrammed |

`BNC_AWG_TERMINATION_PHYSICAL_CONFIRMATION_REQUIRED`: the current photographs
are not available as readable image attachments in this workspace, so neither
the `JP4` nor `JP5` shunt position can be determined reliably. Do not guess and
do not change software from this uncertainty alone. At 0 ohms the adapter adds
no intentional series termination; a high-impedance input should receive close
to the AD2 open-circuit programmed voltage, subject to the AD2, cable, load, and
frequency response. At 50 ohms the adapter inserts approximately 49.9 ohms in
series. A downstream 50-ohm input then forms an approximately 2:1 divider and
receives about half the open-circuit voltage, while a high-impedance input has
little low-frequency divider loss. Therefore a programmed AD2 voltage must not
be reported as the voltage at either the acoustic-amplifier input or the laser-
control input until the applicable jumper state and downstream input impedance
are known or the loaded voltage is measured. The acoustic setting affects
amplifier input and ultimately transducer drive; the laser setting affects its
control-input level but is not evidence of optical power.

TOPTICA's official family documentation confirms that all iBeam smart models
provide analog modulation up to 1 MHz, with user-configurable high-/low-active
behavior and mixed analog/digital modulation support. Digital modulation is an
option with TTL-level input support; the public family documents do not prove
that option's exact installed configuration, the Analog In voltage range or
transfer function, the current high-/low-active choices, or which simultaneous
input states permit emission on this particular unit. Preserve
`LASER_INPUT_SEMANTICS_NEEDS_OWNER/MODEL_CONFIGURATION_CONFIRMATION` and do not
translate W2 or DIO1 commands into a claim of laser emission or optical power.

Hamamatsu's official camera manual identifies `EXT.TRIG` as an external trigger
input accepting TTL or 3.3-V LVCMOS into 10 kohm with selectable rising/falling
polarity; `TIMING 1/2/3` are separate camera outputs. The owner's photograph and
wiring evidence therefore support `PHYSICAL_CONNECTOR_CONFIRMED` for DIO0/pink
to camera `EXT.TRIG`, not to a timing output. Current normal software still
selects DCAM `Internal` and programs no DIO0 pulse, so the cable is
`CONNECTED_BUT_CURRENTLY_UNUSED` for standard steady/quasi-steady acquisition.
External-trigger use remains deferred to transient/synchronized work with
explicit trigger-mode selection and later physical timing validation.

`WaveFormsBackend.configure_wfg()` passes `channel_index` unchanged to the
`FDwfAnalogOut*` calls; Digilent's zero-based SDK examples and W1/W2 connector
documentation therefore close the software translation above. Physical timing
and electrical behavior have not been exercised in this reconciliation.

External evidence used for this decision:

- Digilent's [Analog Discovery 2 reference manual](https://digilent.com/reference/_media/reference/test-and-measurement/analog-discovery-2/ad2_rm.pdf)
  establishes the native W1, W2, T1/T2, and DIO0--DIO15 pinout. Its official
  color-coded pinout identifies DIO0 as pink and DIO1 as green. The
  [AD2 WaveForms hardware guide](https://files.digilent.com/manuals/WaveForms/3.25.1/start3.html)
  specifies the native AWG outputs and the 3.3-V LVCMOS digital/trigger pins.
- Digilent's [BNC Adapter product page](https://digilent.com/shop/bnc-adapter-for-analog-discovery/),
  [Discovery BNC reference manual](https://digilent.com/reference/_media/analog_discovery_bnc_adapter_board:discoverybnc_rm.pdf),
  and [official schematic](https://digilent.com/reference/_media/reference/test-and-measurement/bnc-adapter-board/discovery_bnc_sch.pdf)
  establish SKU `410-263`, the four BNC routes, connector and jumper reference
  designators, single-ended scope conversion, pass-through header, and passive
  AC/DC-coupling and 0/50-ohm AWG-selection circuits. They do not establish the
  installed board revision or current physical jumper positions.
- Digilent's [WaveForms SDK getting-started guide](https://digilent.com/reference/test-and-measurement/guides/waveforms-sdk-getting-started)
  uses channel index 0 for the first waveform-generator channel, while the
  [WaveForms instrument guide](https://files.digilent.com/manuals/WaveForms/3.25.1/start3.html)
  identifies the physical analog outputs as W1 and W2. This directly applies to
  the AD2/WaveForms API mapping; it does not identify the attached apparatus.
- The same-group Lund paper,
  [*Configurable thermoacoustic streaming by laser-induced temperature gradients*](https://journals.aps.org/prapplied/pdf/10.1103/PhysRevApplied.23.024043),
  identifies an approximately 2 MHz acoustic transducer, a fixed-power 785 nm
  heating laser turned on before acoustic actuation/acquisition, and 20 fps
  steady-state imaging. It supports W1's MHz acoustic role and the requirement
  not to introduce dynamic laser-power modulation; it does not establish the
  current cable polarity or controller input configuration.
- TOPTICA's current [iBeam smart product documentation](https://www.toptica.com/products/single-mode-diode-laser/ibeam-smart)
  [family brochure](https://www.toptica.com/fileadmin/Editors_English/11_brochures_datasheets/01_brochures/toptica_iBeam_smart_sp.pdf),
  and [technical drawing](https://www.toptica.com/fileadmin/Editors_English/11_brochures_datasheets/05_technical_drawings/toptica_TD_iBeam_smart.pdf)
  show separate Supply & I/O, Analog In (SMB), and Digital In (SMB) interfaces
  and establish the family modulation capabilities described above. They do
  not provide the installed-unit voltage transfer function or configuration.
- Hamamatsu's [ORCA-Fusion BT product specification](https://www.hamamatsu.com/us/en/product/cameras/cmos-cameras/C15440-20UP.html)
  and [C15440-20UP instruction manual](https://www.hamamatsu.com/content/dam/hamamatsu-photonics/sites/static/sys/en/manual/C15440-20UP,-20UP01_IM_En.pdf)
  establish the 2304 x 2304, 6.5-um-pixel camera identity, USB 3.0 and dual
  CoaXPress interfaces, external trigger modes/delay, `EXT.TRIG` input, and
  separate timing outputs. They establish interface semantics, not current
  physical timing.

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
| Waveform generator | CONFIRMED CURRENT — device identity and official adapter family | Digilent Analog Discovery 2 using the WaveForms SDK; live read-only WaveForms enumeration on 2026-08-28 found one unopened device, `SN:210321A18CE2`. Owner photographs show the official BNC Adapter product family, SKU `410-263` | Physical USB route, adapter PCB revision, JP4/JP5 termination, and waveform/trigger timing are unverified; no output is authorized by inventory status |
| Laser | CONFIRMED CURRENT — photograph-confirmed identity | TOPTICA `iBEAM-SMART-785-S-HP`, approximately 785/787-nm class, Class 3B; owner photographs identify its Analog In and Digital In connections. The safety-label `<500 mW` warning is not experimental optical-power evidence | Analog voltage range/transfer function, input impedances, active polarity, installed digital-modulation option/configuration, mixed-input emission conditions, and actual optical power remain unverified; optical power is independently measured |
| Camera | CONFIRMED CURRENT — photograph, enumeration, and open/close | Hamamatsu ORCA-Fusion BT, model `C15440-20UP`, `S/N: 500478`, confirmed by owner photographs, current Windows PnP, and read-only DCAM enumeration/open-close. DIO0/pink is physically connected to `EXT.TRIG`; the rear `TIMING 1/2/3` connectors are outputs, not that input | Physical USB route and trigger timing remain unverified. Standard acquisition remains Internal, making DIO0 connected-but-currently-unused; transient/synchronized use is deferred |
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
- **SW-AD2-ROUTING-001:** project Ch1 -> API 0 -> W1 is the acoustic output;
  project Ch2 -> API 1 -> W2 is the owner-identified laser Analog In cable.
  Planner and runtime guards prevent W2 from being enabled by stale settings.
  Normal production configures neither DIO0 nor DIO1. This is offline software
  correspondence, not laser electrical or physical timing verification.
  Offline validation: 406/406 affected tests passed; the broad suite reported
  657 passed and 1 skipped, with two known PySide/Shiboken lifetime-family
  failures that each passed immediately in isolation. Repository hygiene,
  compileall, and `git diff --check` also passed.

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
- **Laser wiring provenance supersession:** checkpoint `770e92a` correctly
  established WFG API channel 0 as acoustic and removed unproven generic DO
  Clock programming. Later owner photographs now establish separate laser
  connections at W2/API channel 1 and DIO1. They supersede the earlier
  "no validated current role" conclusion, but do not establish analog scaling,
  polarity, or digital gate semantics. W2 now fails closed and DIO1 remains
  unprogrammed. Camera+acoustic-only testing is not blocked; software-controlled
  laser gating remains blocked.
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
**HW-TIMING-001** remains deferred / ready for physical verification. Normal
production DIO0 and DIO1 are disabled.

The next minimal camera+AD2 fast-sweep experiment is
**READY_FOR_SEPARATE_HARDWARE_AUTHORIZATION** provided CH0 is explicitly
enabled with `Repeat=1`, Frequency Scan is off, the finite run duration covers
acquisition, and the operator confirms the requested ROI/exposure/amplitude.
Laser alignment and optical power remain manual/fixed. The physical gate wiring
is now owner-confirmed, but software-controlled laser gating remains unavailable
until the exact current laser Analog In and Digital In semantics are identified.
