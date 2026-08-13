# Hardware Repair Plans

Current triage record for unresolved hardware boundaries. This document records
evidence and later repair/verification plans only. It does not authorize hardware
actions, fault clearing, motion, output enable, or configuration writes.

Committed baseline for this repair plan: `7c7e19f` on `junjiebranch`, followed
by `d180eea` (the v3 tracking correction), inspected 2026-08-06. The current
working tree also contains uncommitted safety and documentation work. Current
source and retained hardware logs are evidence; historical session claims are
not independently verified unless stated otherwise below.

## Qmix CAN Fault

**Confirmed**

- `QmixPumpBackend._enable_pump()` fails closed when the pump reports a fault. It
  reads optional error detail, does not call `clear_fault()`, and does not enable
  the pump.
- The retained bench record shows a fault that relatched after reconnect as SDK
  code `33279` (`0x81FF`), `CAN Tx Queue Overrun`. The pump remained disabled,
  stopped, reported position sensing initialized, and stayed at the same reported
  fill level.
- ~~Application initialization rolls back earlier devices after the pump
  refuses initialization.~~ **CLOSED (2026-08-13):** the six devices are
  confirmed functionally independent (no device's `initialize()` reads
  another's state), so `Application.initialize()` no longer aborts the
  whole sequence or rolls back already-succeeded devices when one device
  fails -- see the "Initialization And Failure Recovery" section below and
  `docs/claude_code_change_log.md`'s dated entry.

**Still needed**

1. With every Python UI/process closed, inspect the QmixElements event log and
   CAN adapter state. Record the first error timestamp and any preceding bus,
   power, node, or queue messages.
2. Confirm only one bus client is active, then verify adapter driver, bus power,
   topology/termination, configuration project, and node visibility without
   clearing the fault from Python.
3. After the CAN layer is clean, use a dedicated read-only SDK session that stops
   before `QmixPumpBackend._enable_pump()` and record fault, enabled, pumping,
   position-reference, and fill-level state. Do not use normal application
   initialization for this check: on a fault-free device it enables the pump.
4. Only after human review may a separate recovery task authorize a single fault
   clear. Re-read state immediately afterward and again after a fresh reconnect
   before authorizing reference or fluid motion.

No Python backend change is indicated unless clean QmixElements evidence later
shows that the SDK is misreporting or mishandling a healthy bus.

## TEC / MeCom

**Confirmed from current source**

- TEC is disabled and simulated by default.
- Commit `7c7e19f` contains an executable pyMeCom client. Its production reads
  use named parameters 104, 105, 1000, and 2010; writes are restricted to named
  parameters 2010 and 3000.
- `_PyMeComTecClient.write_config()` is deliberately a RAM-only no-op. It does
  not implement the vendor flash-persistence operation suggested by its public
  method name.
- The local target envelope is `[0, 80] C`, and temperature-series orchestration
  remains fake-tested with one target pair per experiment group.

**Unresolved / later plan**

1. Do not use retained Session 75-77 bench prose as current authorization.
2. ~~Human-review the attached controller model/firmware against the exact official
   communication-protocol revision and the installed pyMeCom table.~~ **CLOSED
   (2026-08-05)** -- see `docs/tec_verification_matrix.md`'s "Model / Firmware /
   Protocol Compatibility Review" entry.
3. Decide explicitly whether targets are intentionally session/RAM-only. If flash
   persistence is required, identify and review the official operation before any
   implementation; do not infer it from pyMeCom parameter 108.
4. A future minimal read-only bench pass should capture identity, both-channel
   status, object temperature, output-enable state, and error state before any
   write is considered.
5. Separately review target readback and readiness semantics: the current real
   client returns `target_temperature_c=None`, and its `ready` flag means device
   status Ready/Run plus output enabled, not thermal stability by itself.

Real TEC operation remains unapproved in this audit.

## AD2, Camera, And LED Timing

**Confirmed from current source**

- The Experiment builder creates one digital channel: DIO1, pulse output,
  requested frequency `Camera FPS`, 50% duty representation (`high=1`, `low=1`),
  run time `Frames / Camera FPS`, and wait time from `Camera Start` or the current
  dynamic-start-array entry.
- WaveForms derives the divider from the device's reported internal clock and
  applies Wait/Run/Repeat/TriggerSource globally to DigitalOut.
- `run_experiment2()` configures WFG and DIO before camera configuration, starts
  camera capture, then calls one AD2 PC trigger. Its completion budget includes
  enabled WFG and DO run-plus-wait terms and subtracts time already spent during
  acquisition.
- The automated camera sequence is explicitly forced to DCAM trigger source
  `Internal`. Current Python code does not establish an external AD2 camera
  trigger, configure DIO0, or prove that DIO1 pulses coincide with exposure.

**Minimal evidence needed**

1. Scope DIO1 together with a camera exposure/trigger-output monitor and a PC
   trigger marker, using one conservative existing preset.
2. Record whether DIO1 begins at DigitalOut configure or at `pc_trigger()`, its
   measured start delay, frequency, duty cycle, pulse count, and overlap with
   exposure.
3. Trace the physical camera trigger cable and record its AD2 line, if any. Do
   not change DCAM to External until that wiring and polarity are known.
4. Treat DIO0/acoustic origin and laser mapping as unresolved physical wiring;
   current experiment code does not configure them.

A later code repair depends on the measurement: either preserve documented
internal/free-run camera behavior and stop claiming synchronization, or add an
explicit verified external-trigger line plus DCAM source/polarity/delay settings.

## Valve P01 / P02 Routing

**Confirmed**

- COM5, 19200 baud, bare-CR commands, `S` status query, and exact position tokens
  are implemented. Initialization rejects empty and unknown responses; busy
  markers remain explicit busy state.
- A write records only `requested P01/P02; confirmation pending`; an exact status
  readback is required for protocol confirmation.

**Still needed**

Perform one controlled, fluid-safe routing observation with pump motion disabled.
Record which physical ports connect at `P01` and `P02`, then update operator labels
and flush documentation. Do not infer fluidic meaning from the numeric protocol
token or a successful serial write.

## Qmix Motion, Stop, And Flush Semantics

**Confirmed from code/tests**

- Manual flow, refill, empty, and go-to-level are asynchronous SDK actions followed
  by bounded status polling. On timeout the application requests `stop_pumping()`
  and re-reads fill level.
- Automated flush does not use `generate_flow()`. It validates capacity/current
  fill, confirms P01, issues a target-based `set_fill_level()`, polls completion,
  confirms P02, waits, then issues the final target-based level command.
- Timeout wrappers bound the Python caller but cannot cancel a vendor SDK call
  already blocked inside that worker thread.

**Still needed**

1. Resolve the CAN fault before any motion test.
2. Confirm syringe geometry, position reference, direction/sign, and sufficient
   fluid path before a deliberately small target move.
3. Measure physical stop latency after a timeout/stop request and independently
   confirm motion has ceased; current code has no second post-stop motion proof.
4. Bench-confirm the complete P01 -> first pump move -> P02 -> final pump command
   fluidic result before enabling automated flush broadly.
5. Keep the manual single-pump `generate_flow()` volume ceiling separate from
   automated flush; its exact mechanical/configured cause remains unresolved but
   is not on the canonical experiment path.

## Initialization And Failure Recovery

**Confirmed**

- `Application.initialize()` still reports devices in the AD2 -> Camera ->
  Pump -> Valve -> Z-stage -> TEC order, but that order is now just a fixed
  reporting sequence, not a dependency chain or an abort point: **fixed
  2026-08-13** -- each device gets its own independent `initialize()`
  attempt regardless of whether an earlier one failed, and a device that
  succeeds is never torn back down because a later, unrelated device
  failed. Confirmed via inspection that none of the six devices'
  `initialize()` methods reads another instrument's state or takes one as
  an argument -- the old "stop at the first failure, roll back everything
  already-succeeded" behavior had no documented cross-device dependency
  rationale anywhere in this project's history (checked before this
  change, not assumed); see `docs/claude_code_change_log.md`'s dated entry
  for the investigation. `initialize()` now raises only after every device
  has had its own attempt, naming every device that failed, not just the
  first.
- Camera, Qmix, piezo, and TEC contain local partial-initialize cleanup paths.
  This is a different, narrower kind of rollback than the cross-device one
  above -- a device cleaning up its OWN partial connection state after its
  own `initialize()` fails partway through (e.g. Valve closing the serial
  port it just opened if the status handshake then fails) -- and is
  unaffected by the above fix.
- Cleanup is isolated per device and timeout-bounded, but a timed-out daemon thread
  is not cancelled and may remain blocked inside a vendor SDK.
- **Valve now has a lazy-reconnect fallback (2026-08-13)**, matching the
  pattern `AD2Sdk`/`HamamatsuCamera` already had: `Valve.set_position()`
  transparently re-runs `Valve.initialize()` (full handshake included, not
  a shortcut) if the valve was never connected this session -- e.g.
  because Pump failed before Valve's turn under the old design, or the
  operator simply never ran Initialize Hardware. AD2/Camera already had
  this (`open_and_use_first_device()`/`open_camera()` lazily reopen from
  inside their own real-use methods); Z-stage's manual Z-Scan tab already
  connects/disconnects the piezo per-action, independent of
  `Application.initialize()` entirely, so it never had this gap. TEC was
  not touched -- its real-use methods (`read_status()`/
  `apply_static_setpoint()`) likely have the same gap (no lazy-reconnect,
  and `_backend()` only lazily constructs the backend object, never calls
  `connect()`), but TEC real-hardware operation is a separately-unresolved
  boundary (`docs/tec_verification_matrix.md`) and was left for a
  follow-up rather than bundled into this change untested.

**Gap and later repair**

The instrument whose `initialize()` call raises is not included in Application's
rollback list. This is observable for Valve: it opens the serial port before the
status handshake, but a failed/unknown handshake does not close that just-opened
port. **Implemented, not yet committed (2026-08-05):** `Valve.initialize()` now
closes its backend on post-open handshake failure (preserving the original
exception and reporting a combined cleanup failure if close also fails), with
fake regression tests asserting the port is closed -- see
`docs/claude_code_change_log.md` Session 96 for the full writeup and test count.
AD2's open-assignment failure shape was audited in the same pass and found to
have no matching gap (`AD2Sdk.open_and_use_first_device()` only assigns
`device_handle` after a successful `open_device()`, with no post-open
handshake step that can fail after ownership is committed) -- no AD2 code was
changed. Do not broaden Application rollback by blindly calling cleanup on every failed
instrument unless each backend's partial-state behavior is verified.

**Also implemented, not yet committed (2026-08-05):** the same partial-init
rollback gap existed for two more instruments and is now closed the same way.
`CetoniPump.initialize()` now closes its backend if the post-open
`sync_fill_level()` readback fails (previously left the backend open with no
rollback at all) -- see `docs/claude_code_change_log.md` Session 97.
`PiezoStage.connect()` now calls `channel.StopPolling()` before
`device.ShutDown()` on a post-`StartPolling()` readback failure (previously
only attempted `ShutDown()`, best-effort, polling never explicitly stopped) --
see Session 99. `TecController.cleanup()`'s own timeout-guard gap (a
separately-tracked item, not this rollback-scope gap) is closed the same way
and covered in `docs/known_open_items.md` and Session 98 directly, not
duplicated here.
