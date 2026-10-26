# Retained hardware notes and evidence limits

These notes retain electrical relationships and apparatus observations from named
junjiebranch sources. Source claims, installed-device assumptions and unresolved
questions are not interchangeable. No new physical measurement was made by copying
these notes. Current dispositions are in `known_open_items.md`.

## AD2 analog output path — BNC breakout jumper configuration (JP4/JP5)

**Source**: junjiebranch's `docs/known_open_items.md`, item
`HW-AD2-BNC-001` (retained in that branch's git history; removed from its
working tree during the later documentation reset, now summarised here).

**Established facts**:
- The Digilent Analog Discovery 2 BNC breakout board is official SKU
  `410-263`, schematic `500-263` revision `C.0`.
- That schematic establishes two signal paths: W1 through connector `J4`,
  selected by jumper `JP4`; W2 through connector `J5`, selected by jumper
  `JP5`.
- **`JP4`/`JP5` each select between two electrically different paths: a
  direct path, or a 49.9-ohm *series-source* path.** They are **not** a
  50-ohm shunt load selector. This distinction changes the real output
  voltage math at the load: a series-source resistor forms a voltage
  divider with the downstream input impedance (loaded voltage depends on
  what's connected), whereas a shunt load would not.

**What remains unverified** (unchanged from junjiebranch's own record, not
re-investigated this round): the installed PCB revision and the physical
jumper positions on the actual board in use. No code on this branch (or
junjiebranch's) ever reads or asserts a jumper position — this is purely a
physical, hands-on-the-board fact.

**Software interpretation**: `amplitude_v`/`offset_v` are configuration values,
not an independent load-voltage measurement. A 49.9-ohm series path and downstream
input impedance can divide the voltage. A quantitative claim about voltage at the
load therefore needs the applicable path/load information or an actual measurement;
this note does not require a new board inspection for every experiment.

**Disposition**: retained wiring reference, not a runtime jumper readback or a
software-calibrated load-voltage conversion. No output code is changed.

## Facts carried over from junjiebranch records (2026-10-25)

Sources are junjiebranch documents; none re-verified on the integrated path.

- **Pump continuous flow stall.** `docs/pending_feedback.md` §6: a 330 s
  continuous `generate_flow()` stopped cleanly with no fault around 0.1873 mL
  of a 1.178 mL syringe and persisted across a fresh `generate_flow()`; cause
  unresolved (soft limit vs a ~225 s time limit). Relevant to manual
  "Set flow…". The same record notes a five-device 330 s soak with zero
  failures and "random connection failures" that never reproduced.
- **Laser path (`HW-LASER-PATH-001`).** AD2 W2 feeds the iBEAM analog input
  (0..+5 V, default polarity `sub`): ~0 V is not a safe "off" assumption.
  junjie's planner refuses any W2 output; the integration uses W2 as a fixed
  5 V square. Installed unit unconfirmed.
- **AD2 USB identity.** This unit enumerates under the FTDI vendor ID 0403,
  not Digilent's; this once caused a false "no AD2 connected" diagnosis.
- **Valve routing (`HW-VALVE-001`).** Owner mapping: P01 through-chip, P02
  bypass; open/closed wording is unverified.
- **Camera.** Hamamatsu C15440-20UP, S/N 500478; timing outputs unmeasured
  (`HW-TIMING-001`). Electrical levels of trigger input/timing outputs and
  AD2 DIO/W1/W2 limits are in junjie's records.
- **TEC.** `TEC-AFTER-RUN-POLICY-001` and `SCI-TEC-EQUIL-001` name the old
  policy/equilibrium questions. Current integration retains regulation after a run
  and requests OFF on Panic/exit; controller stability is not sample equilibrium.
  They are not repeated pending decisions for this acceptance baseline.
