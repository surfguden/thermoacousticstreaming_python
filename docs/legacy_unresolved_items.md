# Legacy and Unresolved Items

> **Historical focused safety snapshot.** This file is no longer a second live
> unresolved-items summary. Later TEC, Qmix, routing, planning, acquisition, and
> V3 checkpoints closed or reclassified several statements below. Use
> [`known_open_items.md`](known_open_items.md) as the only live unresolved/deferred
> registry and [`project_control.md`](project_control.md) for current truth.
> Preserve the body as evidence of what was unresolved at this snapshot.

This was a focused high-risk safety summary, not the canonical complete holding
list. For the current live register, see `docs/known_open_items.md`. It is not
an authorization to run hardware. Treat the current source and targeted tests as the source of truth
for implemented behavior; keep the items below out of the active workflow until
a human decision, hardware confirmation, or focused implementation resolves them.

## Hardware Integration

- **Real TEC MeCom operation is unresolved pending reconciliation.** Commit
  `7c7e19f` contains a pyMeCom client and
  historical real-hardware claims. Independent source review confirms its five
  named parameter IDs against the installed pyMeCom table and official
  TEC-Family protocol, but does not authenticate those bench claims. Model/
  firmware compatibility is CLOSED -- see `docs/tec_verification_matrix.md`'s
  "Model / Firmware / Protocol Compatibility Review". Its `write_config()` is
  deliberately a RAM-only no-op, not the vendor's flash-save operation. Keep
  TEC disabled/simulated by default and require human review of the
  implementation, hardware record, and bench record before real operation.
  See the canonical entry in `docs/known_open_items.md` and the evidence
  inventory in `docs/tec_verification_matrix.md`.
- **Manual PPC001 Z-scan is integrated only as a manual calibration feature.**
  The Qt Z-Scan tab can connect to the PPC001/PFM450(E), query live travel
  range, optionally switch to ClosedLoop after explicit confirmation, and then
  requires a separate explicit motion authorization before moving the piezo.
  It is not part of the canonical `Application.run_experiment2()` experiment
  sequence and should not be treated as automatic experiment Z motion or as
  discovery-only support.
- **Manual PPC001 piezo probe remains quarantined.**
  `hardware_tests/manual_ppc001_piezo_probe.py` is a local manual hardware probe
  with real action paths, including polling and a gated move/voltage-change
  command. It is intentionally ignored by `.gitignore`, deliberately not named
  `test_*.py`, and must not become part of automated pytest collection without a
  separate review.
- **Legacy action-capable `tools/` scripts remain manual-only.**
  `tools/legacy_hamamatsu_camera_probe.py`, `tools/legacy_qmix_pump_probe.py`
  (renamed from `tools/test_hamamatsu_camera.py`/`tools/test_qmix_pump.py`,
  file/structure audit cleanup), and the two
  `tools/capture_ad2_wavegen_scope*.py` scripts sit outside pytest collection
  and are explicitly marked `__test__ = False`. The two AD2 diagnostics now
  require a typed REAL AD2/W1 confirmation before constructing the device, but
  remain engineering diagnostics rather than approved/commissioned procedures.
- **Passive Thorlabs/APT discovery remains separate from PPC001 motion.**
  `thorlabs_apt.py` and `hardware_tests/test_thorlabs_apt_discovery.py` are
  discovery-only helpers. Do not use their "discovery-only" status to describe
  the separate manual PPC001 Z-Scan motion path.
- **Qmix/pump real-motion semantics still need hardware confirmation.** The
  current code is configured around a one-pump Qmix setup, and the UI labels
  the flow-rate sign convention. Real pump flow, reference move,
  syringe-specific geometry, and flush behavior still require deliberate
  operator confirmation before broad use. The software boundary is narrower:
  automated flush is a positive-rate dispense operation and rejects zero or
  negative flow before touching the valve or pump; that does not establish its
  physical tubing outcome.
- **Qmix connection policy is approved; the CAN root cause is not resolved.**
  Normal initialization now clears the vendor fault latch after bus start,
  records before/after state, and retains a final gate that refuses enable if a
  fault remains or immediately relatches. A colleague reported successful real
  initialization and operation under this policy, but the earlier `0x81FF`
  (`CAN Tx Queue Overrun`) sequence still requires adapter/bus/controller
  diagnosis; recovery is not proof that the transport issue is solved.
- **Valve physical routing remains hardware-dependent.** The code sends Rheodyne
  position commands `P01\r` and `P02\r` and rejects unknown initialization
  responses. The physical meaning of position 1 vs. position 2 and COM-port
  selection still need confirmation against the actual tubing/wiring.

## AD2 and Timing

- **Staged-script safety gates do not protect the canonical GUI.**
  `CONFIRM_REAL_HARDWARE` and timing acknowledgements are command-line
  interlocks in newer `hardware_tests/` tools. They are not application-wide
  policy: after real devices are initialized, the GUI can start WFG output,
  pump/valve actions, and an experiment without those flags. This is an
  unresolved operator-safety boundary and must not be described as if the
  canonical GUI were already confirmation-gated.

- **Full LabVIEW acoustic output is not approved.** The staged smoke script
  blocks the full `1.975 MHz`, `2 V`, `60 s` condition behind explicit gates,
  but the canonical GUI does not provide the same application-wide interlock.
  Do not mistake the script refusal for a GUI-enforced block.
- **DIO/LED timing has been migrated structurally, not fully hardware-proven.**
  The experiment path builds a DIO1 LED clock configuration from Camera FPS,
  Camera Start, Frames, and Dynamic Camera Start Time, but physical timing should
  still be checked with an oscilloscope/MSO before treating it as equivalent to
  LabVIEW in all conditions.
- **AD2 WFG trigger semantics remain a risk area.** `config_wfg()` and
  `pc_trigger()` are both present, but the physical start timing depends on
  trigger-source configuration and should not be inferred from code names alone.
- **DO Custom remains legacy/nonessential.** It should stay out of the active
  workflow unless new LabVIEW or hardware evidence proves it is load-bearing.

## UI and Settings

- **Some Initialization reference fields are intentionally stub-marked.** Z
  backend selection, legacy Prior VISA, Thorlabs/APT backend/discovery-only,
  and the Qmix SDK Python/QMIXSDK path fields remain visible for continuity but
  are disabled as unwired. The Thorlabs device serial is different: it is live
  input to the real PPC001/Kinesis connection when Z stage is enabled. Do not
  generalize the stub label to every Thorlabs field.
- **Elapsed Time and estimated Time Left are live, display-only indicators.**
  Commit `66016bd` wired a monotonic elapsed clock and a remaining-time estimate
  based first on programmed WFG/DIO/flush duration, then on measured mean repeat
  duration. They do not change experiment validation or hardware behavior, and
  the estimate deliberately excludes unpredictable TEC stabilization and other
  hardware/acquisition variability.
- **v2 is an opt-in transitional UI, not a separate implementation.** Its manual
  WFG/MSO/PumpValve/Camera buttons reuse the v1 panel builders and
  shared `Application` instance. That reuse is deliberate; v2 should not drift
  into a second hardware-control implementation.
- **v3 is formally accepted tracked repository content; v1 remains the default
  and v2 remains the rollback/reference path.** The owner decision in the
  commit `8433ba0` supersedes the earlier "never commit v3" rule. V3 subclasses
  `MainWindowV2` and shares the real `Application`/backend runtime; it is not an
  independently hardware-verified replacement. Its rebuilt panels still create
  maintenance coupling. Commit `2c0ffc6` closed the earlier menu-only Abort and
  missing-manual-Qmix-recovery capability gaps with v3-specific presentations
  that reuse the shared behavior; acceptance and those closures do not provide
  independent hardware validation.
- **Settings persistence is not comprehensive.** Several manual-tab-only fields
  remain outside the saved settings file by long-standing design ambiguity. Add
  persistence only when the expected operator workflow is explicit.

## Documentation Status

- `docs/claude_code_change_log.md` is historical and self-reported; it must be
  checked against git and current source before being used as evidence.
- `docs/current_workflow_audit.md` is a retained point-in-time safety audit;
  `docs/project_control.md` is the operational map for the current workflow.
- `docs/labview_migration_completeness_audit.md` is a migration-parity audit and
  still contains historical findings that later sessions may have partially
  closed.
