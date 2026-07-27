# Legacy and Unresolved Items

This document is the conservative holding area for issues that are still not
confidently decidable from the current code alone. It is not an authorization to
run hardware. Treat the current source and targeted tests as the source of truth
for implemented behavior; treat this file as the explicit list of items that
should stay out of the active workflow until a human decision, hardware
confirmation, or a focused implementation task resolves them.

## Hardware Integration

- **Thorlabs/APT Z-stage motion is not integrated.** Passive discovery found an
  APT piezo controller, serial `44533854`, but the current experiment workflow
  does not enable, poll, home, jog, move, or configure it. The legacy Prior COM7
  path remains present for compatibility but is not valid for the currently
  connected Z-stage.
- **Manual BPC piezo probe remains quarantined.**
  `hardware_tests/test_bpc_piezo_probe.py` is a local manual hardware probe with
  real action paths, including polling and a gated move/voltage-change command.
  It is intentionally ignored by `.gitignore` and must not become part of
  automated pytest collection without a separate review.
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
