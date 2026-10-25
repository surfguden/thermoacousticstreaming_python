# Hardware notes — electrical/physical facts not captured in code

Distinct from `known_open_items.md`: that file tracks open *questions*.
This file records facts that are **already established** (from junjiebranch's
retained documentation, before its removal from that branch's working tree)
but were never written down anywhere in this branch's code or docs. Nothing
here is new evidence gathered this round — it is evidence that already
existed, now given a place to live so it is not lost again.

## AD2 analog output path — BNC breakout jumper configuration (JP4/JP5)

**Source**: junjiebranch's `docs/known_open_items.md`, item
`HW-AD2-BNC-001` (retained in that branch's git history; removed from its
working tree during the later documentation reset, and never present on
this branch at all).

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

**Why this matters for software**: `drivers/ad2/analog_discovery.py`'s
`amplitude_v`/`offset_v` fields on a `CarrierSettings` (see
`application/commands.py`) are the *commanded* AD2 analog-output values.
Whichever path is actually installed (direct or 49.9-ohm series-source)
determines whether the real voltage delivered to a downstream load equals
the commanded value or is attenuated by a voltage divider with that load's
input impedance. **Do not assume the commanded `amplitude_v`/`offset_v`
equals the physical output voltage at any downstream instrument without
first confirming, by physical inspection (powered down, per
`hardware_tests/README.md`'s safety boundary), which jumper position is
installed and what the downstream input impedance actually is.**

**Disposition**: documentation-only, as instructed — no code change.
Grepped this round to re-confirm no existing code references this anywhere
(`JP4`, `JP5`, `series-source`, `49.9` all absent from
`drivers/ad2/analog_discovery.py` and `drivers/ad2/configuration.py`, both
branches). This file is the fix for that absence.

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
- **TEC.** `TEC-AFTER-RUN-POLICY-001` (no TEC-off at run end) and
  `SCI-TEC-EQUIL-001` are junjie owner questions still open.
