# Legacy and Unresolved Items

This is a focused high-risk safety summary, not the canonical complete holding
list. For the consolidated live register of unresolved, deferred, legacy, and
manual-only items, see `docs/known_open_items.md`. It is not an authorization to
run hardware. Treat the current source and targeted tests as the source of truth
for implemented behavior; keep the items below out of the active workflow until
a human decision, hardware confirmation, or focused implementation resolves them.

## Hardware Integration

- **Real TEC MeCom mapping remains unresolved.** TEC Service Software/MeCom/
  pyMeCom are the expected vendor stack, but this repository still does not
  contain a reviewed Meerstetter client or register map. The current TEC path is
  a conservative scaffold: disabled by default, simulated by default, locally
  range-limited, and refusing real connection before I/O because the shipped
  UI/factory cannot supply a reviewed client/factory. A UI resource field alone
  does not enable real TEC control. The installed controller model/firmware,
  selected channel instance, communication address, and persistence mapping are
  also unrecorded. See `docs/tec_verification_matrix.md` for the official-source
  inventory and step-by-step verification matrix.
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
- **Passive Thorlabs/APT discovery remains separate from PPC001 motion.**
  `thorlabs_apt.py` and `hardware_tests/test_thorlabs_apt_discovery.py` are
  discovery-only helpers. Do not use their "discovery-only" status to describe
  the separate manual PPC001 Z-Scan motion path.
- **Qmix/pump real-motion semantics still need hardware confirmation.** The
  one-pump Qmix configuration is the current validated setup, and the UI now
  labels the flow-rate sign convention. Real pump flow, reference move,
  syringe-specific geometry, and flush behavior still require deliberate
  operator confirmation before broad use.
- **Valve physical routing remains hardware-dependent.** The code sends Rheodyne
  position commands `P01\r` and `P02\r` and rejects unknown initialization
  responses. The physical meaning of position 1 vs. position 2 and COM-port
  selection still need confirmation against the actual tubing/wiring.

## AD2 and Timing

- **Full LabVIEW acoustic output remains blocked.** The full `1.975 MHz`, `2 V`,
  `60 s` condition is not considered a default-safe action and must remain behind
  explicit gates.
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

- **Initialization fields for future backends are intentionally stub-marked.**
  Z backend selection, Thorlabs/APT fields, Qmix SDK Python Path, and Qmix
  QMIXSDK Path are visible for continuity but are disabled/marked as not wired
  unless future backend work makes them operational.
- **Elapsed Time and Time Left are display stubs.** They are marked as not wired
  because no current timing update path drives them.
- **v2 is an opt-in preview UI, not a separate implementation.** Its manual
  WFG/MSO/PumpValve/Camera buttons reuse the validated v1 panel builders and
  shared `Application` instance. That reuse is deliberate; v2 should not drift
  into a second hardware-control implementation.
- **Settings persistence is not comprehensive.** Several manual-tab-only fields
  remain outside the saved settings file by long-standing design ambiguity. Add
  persistence only when the expected operator workflow is explicit.

## Documentation Status

- `docs/claude_code_change_log.md` is historical and self-reported; it must be
  checked against git and current source before being used as evidence.
- `docs/current_workflow_audit.md` is the operational safety map for the current
  workflow.
- `docs/labview_migration_completeness_audit.md` is a migration-parity audit and
  still contains historical findings that later sessions may have partially
  closed.
