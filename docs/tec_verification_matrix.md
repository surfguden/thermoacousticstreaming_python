# TEC Verification Matrix

This document is the TEC-specific verification boundary for the current
Meerstetter integration. It is documentation only; it does not authorize real
hardware operation.

> **Independent-audit status (2026-08-05):** the current working tree contains
> an executable pyMeCom client, and its five named parameters/IDs match both the
> installed `mecom.commands.TEC_PARAMETERS` table and Meerstetter's official
> TEC-Family protocol (104, 105, 1000, 2010, and 3000). The Session 75-77
> hardware statements below remain historical, self-reported evidence: they are
> not independently reproducible from source or fake-only tests. The client
> implementation is committed in `7c7e19f`, but that is not independent bench
> authorization. Treat real TEC operation as unapproved
> and leave the application on its disabled/simulated default until a human
> review reconciles the implementation with a retained bench record. Also note
> that `_PyMeComTecClient.write_config()` is intentionally a no-op: it applies
> RAM values through MeCom `VS`, but does **not** perform the vendor's separate
> flash-persistence "Write Config"/save operation.
> Except for the independently retained 2026-08-28 read-only and Static OFF
> evidence below, every "real-hardware verified" label retained below is a
> historical session claim, not current authorization.

Current run metadata records `TECRequested`, `TECEnabled`, `SimTEC`, legacy
`TECTarget`, and explicit `TECTargetCh1`/`TECTargetCh2`. Those fields preserve
unlocked dual-channel requested targets and distinguish disabled/simulated
runs; they are not applied-setpoint readbacks or measured temperatures. The
metadata change does not alter MeCom I/O. The independent read-only/OFF/write
bench sequence is prepared in `docs/runtime_truth_and_bench_preparation.md`.
On 2026-08-28 read-only COM6 probes independently read Device Status 104 = 1
and both channels at plausible room temperatures with Output Enable Status
2010 = 0. A later authorized check used the public shared controller path to
write only parameter 2010 value 0 to channels 1 and 2; both channels read back
OFF and the client closed cleanly. No Static ON, target, PID/calibration, raw,
or flash write occurred. Partial-failure cleanup remains fake-tested because no
real failure was induced. The retained evidence and limits are in
`docs/p0_hardware_truth_20260828.md`.

## Official Source Check

Official Meerstetter pages confirm the following high-level facts:

- TEC Service Software can connect to TEC-family controllers over USB, RS232
  TTL, and RS485, and supports monitoring, logging, error management, and
  controller configuration:
  <https://www.meerstetter.ch/products/systems-software-accessories/software/tec-service-software>
- MeCom is the serial communication protocol for TEC controllers, and the
  TEC controller software does not need to be running for MeCom remote control:
  <https://www.meerstetter.ch/customer-center/compendium/64-tec-controller-remote-control>
- pyMeCom is Meerstetter's Python interface for communicating with and
  controlling Meerstetter controllers over MeCom:
  <https://www.meerstetter.ch/products/systems-software-accessories/software/pymecom>
- Parameter IDs are device-specific and are published in the relevant
  Communication Protocol documents. Five parameter IDs are bound to a
  reviewed real Meerstetter client (`_PyMeComTecClient` in `tec.py`) -- 2010
  "Output Enable Status" (write 0=OFF/1=Static ON), 3000 "Target Object
  Temperature" (write, degrees C), 1000 "Object Temperature" (read-only,
  degrees C), 104 "Device Status" (read-only), 105 "Error Number"
  (read-only). **Updated (Session 76): the exact parameter name for ID 3000
  is "Target Object Temperature", not "Target Object Temp"** -- the wrong
  name (originally taken from a paraphrase, not the installed package)
  raised `UnknownParameter` on every real write until caught during
  real-hardware verification (Session 75) and fixed, with a regression test
  that compares directly against the installed `mecom.commands.TEC_PARAMETERS`
  table so a future mismatch can't hide behind two wrong strings agreeing
  with each other. Writes remain strictly limited to exactly these 2
  parameters (2010, 3000), by name, never `get_parameter_raw()`/
  `set_parameter_raw()`. **Updated (Session 76): reads are no longer
  restricted to a fixed parameter list** -- a read cannot change device
  state, so any parameter may be read by name for real-hardware diagnostics
  (this is how Device Type/General Operating Mode were read during the
  channel-2 investigation below); `get_parameter_raw()`/`set_parameter_raw()`
  remain forbidden in both directions, since every parameter this
  integration has needed to read has had a known name.
- The current TEC-Family communication protocol defines parameter 2010
  "Output Enable" as 0=Static OFF, 1=Static ON, 2=Live, and 3=HW Enable.
  This integration deliberately writes only 0 or 1; it does not use the Live
  or HW Enable modes. Parameter 2000 ("Output Stage Input
  Selection") is a separate, related parameter and remains explicitly out
  of scope; it is never read or written here.
- The vendor's configuration workflow describes Write Config as saving
  changed parameters to the controller. `_PyMeComTecClient.write_config()`
  deliberately performs no flash save: MeCom `VS` writes update RAM and the
  app re-applies targets each session. That is an intentional RAM-only policy,
  not an implementation of vendor Write Config. Historical Sessions 75-76
  reported immediate thermal response without a separate apply step, but that
  report is not retained bench evidence and does not prove flash persistence.
- **New (Session 75-76): Device Status (104) and Device Type (100) are
  device-wide "Common Product Parameters" on this hardware, not per-channel**
  -- confirmed two ways: (1) the real protocol document files them under
  Sec 3.3.1 "Common Product Parameters," the same section as Firmware
  Version, which the document's own general addressing rule (Sec 3.1) names
  as its worked example of a single-instance parameter; Object
  Temperature/Target Object Temp/Output Enable are all filed under a
  separate section, Sec 3.3.4 "Temperature Controller." (2) A live instance
  sweep on real hardware: querying Device Status/Device Type at
  `parameter_instance=2` raised `ResponseException('Instance is not
  available')`, while Object Temperature/Output Enable Status/Target Object
  Temperature all held real, independent state at instance 2. `tec.py`'s
  `read_status()` was fixed accordingly (see Verification Matrix item 2).

No MeCom register number beyond the 5 bound parameters above (plus
diagnostic reads of Device Type/Hardware Version/Firmware Version/Serial
Number/General Operating Mode, all read-only, done during the Session 76
channel-2 investigation) has ever been referenced anywhere in this
repository.

## Model / Firmware / Protocol Compatibility Review (Closed, 2026-08-05)

This closes `docs/hardware_repair_plan.md`'s TEC/MeCom item 2 ("Human-review
the attached controller model/firmware against the exact official
communication-protocol revision and the installed pyMeCom table") -- **it
does not close, and is not evidence for, any other open TEC item** (see
`docs/known_open_items.md` for what remains open: real-operation
authorization, the flash-persistence decision, target-readback/readiness
semantics, and real error-state testing).

- **Device identity confirmed.** A real board photo shows model
  "TEC-1123-HV", serial number beginning "509..." -- matches the
  SDK-reported Device Type 1123 and Serial Number 5091 already on record
  from the earlier real-hardware verification session (Session 75,
  `docs/claude_code_change_log.md`). Same physical unit, correctly
  connected -- the "-HV" suffix was not previously reconciled against
  the reviewed protocol documentation.
- **Protocol compatibility confirmed.** Per Meerstetter's own
  documentation, the entire TEC-Family (including the -HV variant)
  shares one common platform bus, communication protocol, and hardware
  architecture -- there is no separate "HV protocol." The official
  Communication Protocol document (5136AF, cross-referenced 5136AU)
  applies identically to this unit.
- **HV-specific parameter differences located and confirmed out of
  scope.** The protocol's HV-specific value-range differences are
  confined to voltage/current limitation and error-threshold parameters
  -- 2021 (Set Voltage), 2030 (Current Limitation), 2031 (Voltage
  Limitation), 2032/2033 (Current/Voltage Error Threshold). None of
  these are among this integration's 5 whitelisted parameters (104,
  105, 1000, 2010, 3000). No correction to the existing implementation
  is needed.
- **Firmware requirement met.** The TEC-1123 datasheet (5144Y, cross-
  referenced 5144R) states HV electrical characteristics require
  firmware >= v4.00. This unit's real SDK-reported firmware is 5.10
  (on record since Session 75), which satisfies that requirement.

**Sources:** TEC-1123 datasheet (Meerstetter document 5144Y/5144R) and
the TEC-Family Communication Protocol (Meerstetter document 5136AF),
both from the same [TEC-Family downloads
category](https://www.meerstetter.ch/customer-center/downloads/category/35-latest-communication-protocols)
already cited elsewhere in this document.

## Historical Protocol-Mapping Inventory

| Required action | Official evidence | Current repository state | Classification |
| --- | --- | --- | --- |
| Connect / discover | MeCom supports USB, RS485, and RS232 TTL; direct USB appears as a virtual serial port. | `MeerstetterTecBackend(client_factory=_real_tec_client_factory)`, wired by `hardware_factory.py`'s non-simulated TEC path. `_PyMeComTecClient.connect()` lazily constructs pyMeCom's `MeComSerial(serialport, timeout=1, baudrate=57600, metype='TEC')`. **Real-hardware verified (Session 75): the physical TEC is on COM6** (confirmed via `serial.tools.list_ports.comports()` + `Get-PnpDevice -Class Ports` cross-check, then a live parameter-104 probe -- COM4 timed out, COM6 responded). Controller address (bus address, not COM port) still uses pyMeCom's own default (0/broadcast) -- not separately confirmed, since only one TEC unit is on this bus. | Real-hardware verified on COM6 |
| Read device status / fault | TEC-Family protocol catalogues device-status and error fields (parameter 104 Device Status, 105 Error Number). | `_PyMeComTecClient.read_status(channels)` reads 104 and (if ==3) 105 ONCE at instance 1 and applies the result to every requested channel's `TecStatus` -- **fixed in Session 76** after real hardware confirmed these are device-wide, not per-channel (previously read per-channel, which broke channel 2). | Real-hardware verified, both channels |
| Read object temperature | The protocol documents object-temperature readback (parameter 1000) for a TEC-Family controller instance. | `_PyMeComTecClient.read_status(channels)` reads parameter 1000 "Object Temperature" per channel via `get_parameter(parameter_name="Object Temperature", parameter_instance=channel)`. | Real-hardware verified, both channels hold independent real readings |
| Set target object temperature | The protocol documents a target-object-temperature setting (parameter 3000) for a TEC-Family controller instance. | `_PyMeComTecClient.set_target_temperature(channel, temperature_c)` writes parameter 3000 "Target Object Temperature" via `set_parameter()`. | Real-hardware verified, both channels (genuine closed-loop thermal response) |
| Static ON/OFF output stage | The protocol defines parameter 2010 values 0=Static OFF and 1=Static ON (instance-addressed). | The client writes only the selected value through named parameter 2010; parameter 2000 remains out of scope. | Static ON remains a historical Session 75-76 claim; Static OFF through the current shared path was independently verified on both channels on 2026-08-28 |
| Write configuration | Vendor configuration guidance says Write Config saves changed parameters to the controller; the protocol document's worked examples show `VS` (Value Set) commands take effect immediately in RAM. | `_PyMeComTecClient.write_config()` is a deliberate RAM-only no-op; it does not issue vendor Write Config or persist to flash. | Intentional omission, not equivalent to vendor Write Config; historical response claims are not independently retained bench evidence |
| Readback, stable wait, abort / timeout | Vendor material distinguishes Ready, Run, and Error states, but does not establish this experiment's stability criterion. | `TecController.wait_until_stable()` polls per-channel `TecStatus` (`dict[int, TecStatus]`), with explicit tolerance, settle time, timeout, and abort callback, for both simulated and reviewed-client backends. | Real device-status readback verified. **Session 77: `wait_until_stable()`'s own success-path loop (tolerance + `min_settle_s` continuous-stability timer) real-hardware verified on channel 1** (target 25.65 C, converged and held within 0.2 C tolerance, `ready=True`, returned inside the 60s bound) -- timeout/abort paths still offline-tested only |

The official references for this inventory are the [TEC controller remote-control
overview](https://www.meerstetter.ch/customer-center/compendium/64-tec-controller-remote-control),
the [TEC-Family MeCom protocol downloads](https://www.meerstetter.ch/customer-center/downloads/category/35-latest-communication-protocols),
and the [TEC-Family user manual downloads](https://www.meerstetter.ch/customer-center/downloads/category/15-tec-family-tec-controllers-user-manuals).

## Current Code Boundary And Historical Claims

The executable boundary below is source-inspected. Any bench-result wording in
this section is retained as historical context under the independent-audit caveat
above.

The safe default is:

- TEC disabled by default.
- TEC simulated by default.
- The shipped factory (`hardware_factory.py`) wires the current source-limited Meerstetter
  client factory (`_real_tec_client_factory`) into the non-simulated TEC
  path. `MeerstetterTecBackend` without an explicit `client_factory` still
  refuses cleanly before any I/O. **The real path has now been exercised
  against physical hardware (Sessions 75-77)** -- COM6, TEC-1123 -- not
  just wired.
- Temperature series uses one target temperature per experiment group,
  broadcast by default to both of the device's channels (`TecController`'s
  `channels=(1, 2)` default). **Both channels confirmed real and
  independently controllable on real hardware (Sessions 75-76)** -- a
  future caller can drive channels independently via an explicit
  `channels=` argument without further changes to `TecController`.
  **Updated (Session 77): the UI now has a lock/unlock toggle** (default
  locked, matching the original broadcast behavior unchanged) --
  unlocked, `TemperatureSeries.temperature_points_ch2_c` and
  `TecController.apply_static_setpoint()`/`wait_until_stable()`'s new
  `dict[int, float]` per-channel-target support drive both channels to
  independent targets, genuinely simultaneously, at each scan step. The
  dict-target code path itself is fake/unit-tested only -- not yet run
  against real hardware (the single-float broadcast path it's built on
  has been, repeatedly).
- The TEC waits for stability, on both channels, before running that group
  (via `TecController.wait_until_stable()` -- success-path polling loop
  real-hardware verified on channel 1, Session 77; timeout/abort paths
  still offline-tested only).
- The wait has an explicit timeout. `wait_until_stable()` also accepts a
  general `should_abort` callback as part of its own `tec.py` API, but as
  of Session 80 the real production call path (`run_temperature_series()`)
  no longer feeds it -- TEC-scan abort is checked via `self.stop_fired`
  once per temperature point instead (see Verification Matrix item 9).
- Target temperatures are rejected outside the local application safety range
  `[0.0, 80.0] C` before they reach any backend.

The `[0.0, 80.0] C` range is a local software safety envelope, not a
Meerstetter device-limit claim.

## Historical Verification Matrix (Not Current Authorization)

| Item | Expected behavior | Code path | Confirm success by | Failure mode | Current status |
| --- | --- | --- | --- | --- | --- |
| 1. Connection / discovery | TEC connects only when enabled, on the confirmed real port (COM6). | `HardwareRuntimeConfig.tec_enabled`, `build_hardware_bundle()`, `TecController.initialize()`, `MeerstetterTecBackend.connect()`, `_PyMeComTecClient.connect()` | `TecController.initialized=True`, backend `read_status()` returns without error | Real backend without client raises `TecError`; a real connect against a wrong/absent port raises a serial-level exception, not a silent success | **Real-hardware verified (COM6, Session 75)** |
| 2. Read-only status | Read current temperature, output stage state, ready flag, and error state, per channel; Device Status/Error Number read once, device-wide. | `TecController.read_status()`, backend `read_status(channels)`, `_PyMeComTecClient.read_status(channels)` | `dict[int, TecStatus]` populated for every requested channel | Missing/unsupported client method raises `TecError`; backend error state surfaces | **Real-hardware verified, both channels (Sessions 75-76)** -- includes the Session 76 fix for Device Status's device-wide addressing |
| 3. Target temperature validation | Reject non-finite or out-of-range target before backend call. | `validate_tec_target_temperature()`, `TemperatureSeries.__post_init__()`, `TecController.apply_static_setpoint()` | Accepted target is finite and within `[0.0, 80.0] C` | `ValueError` before any backend write | Offline-tested |
| 4. Set target temperature | Apply one static target for a group, broadcast by default to both configured channels. | `Application.run_temperature_series()` -> `TecController.apply_static_setpoint()` -> backend `set_target_temperature(channel, temperature_c)` -> `_PyMeComTecClient` writes parameter 3000 | Readback status target/current fields | Backend raises `TecError`; error state raises `TecError` | **Real-hardware verified, both channels (Sessions 75-76)** -- genuine closed-loop thermal convergence observed on each channel independently |
| 5. Output-stage Static ON/OFF | Static ON uses parameter 2010 value 1 before a target; shutdown uses value 0 per channel. | `TecController.apply_static_setpoint()` uses Static ON; `TecController.set_output_stage_static_off()` issues bounded per-channel OFF and readback. | `TecStatus.output_stage_static_on=True`/`False` | Missing client method raises `TecError`; OFF path reports command/readback failures | Static ON remains historical Session 75-76 evidence; the current Static OFF path was independently real-verified on both channels on 2026-08-28 |
| 6. Write config | `_PyMeComTecClient.write_config()` is a deliberate RAM-only no-op; it is not vendor flash persistence. | `TecController.apply_static_setpoint()` -> backend `write_config()` -> `_PyMeComTecClient.write_config()` (no-op) | A test confirms zero calls are made to the fake MeCom double during `write_config()` | No flash save occurs; persistence is outside the current boundary | No-op behavior offline-tested; vendor Write Config remains intentionally unimplemented |
| 7. Temperature/readiness readback | Confirm current temperature, ready flag, and fault/error state after write and during wait, per channel. | `TecController.read_status()`, `wait_until_stable()` (over `dict[int, TecStatus]`) | `ready=True`, current within tolerance for the minimum settle time, for every configured channel | Error state raises `TecError`; unsupported status response raises `TecError` | **Real-hardware verified, including through `wait_until_stable()`'s own loop (Sessions 75-77)** |
| 8. Stability wait | Wait until current temperature remains within tolerance for `min_settle_s`, bounded by `max_wait_s`, across all configured channels. | `TecController.wait_until_stable()` | Returns final `dict[int, TecStatus]` | Raises `TimeoutError` after `max_wait_s` | **Success path (tolerance + `min_settle_s`) real-hardware verified on channel 1 (Session 77)**; timeout path still offline-tested only |
| 9. Abort/cancel during wait | Abort request does NOT interrupt a long stabilization wait -- the current temperature point (target set, wait, post-stable hold, and its entire experiment group) always finishes; only the *next* temperature point is prevented from starting. | `Application.run_temperature_series()` checks `self.stop_fired` once per temperature point, before that point's target is set; `wait_until_stable()` is called with no `should_abort` argument (Session 80 removed the `self.listen_abort` wiring -- that callback is a general `tec.py` API feature, not fed by this real call path) | Returns `False`, status `TemperatureSeriesAborted`, only after the in-flight temperature point's full group (including all repeats) has run | The next temperature point starting after `stop_fired` was set would indicate a regression | **Real `stop_fired` mechanism tested (Session 80)** -- abort during `wait_until_stable()`, during the post-stable hold, and mid-repeat all confirmed to let the current point finish before stopping; not yet run against real hardware |
| 10. Timeout behavior | Non-stabilizing target fails clearly instead of running the group. | `TecController.wait_until_stable()` | `TimeoutError` with last status | No experiment group should run after timeout | Offline-tested only |
| 11. One temperature per group | Set one target, wait stable on both channels, then run all repeats in that group before moving to next target. | `Application.run_temperature_series()` | Target calls match group count; repeat calls occur under each group path | Mismatched count raises `ValueError`; group stops on failed repeat | Offline-tested only |
| 12. Isolation from other hardware | TEC orchestration must not alter AD2/camera/pump/valve/Qmix/Z except by running the normal experiment group after stabilization. | `Application.run_temperature_series()` | Before group start, only TEC calls occur | Any extra hardware call before stabilization is a bug | Fake-tested indirectly; real hardware still gated |
| 13. Writable-parameter enforcement | Writes are strictly limited to exactly 2 parameters (2010 Output Enable Status, 3000 Target Object Temperature), only via `set_parameter()` by name, never `set_parameter_raw()`. Reads are unrestricted (Session 76 scope update). | `_PyMeComTecClient` (all methods) | A fake MeCom double raises `AssertionError` on any write outside the 2-parameter whitelist or any `get_parameter_raw()`/`set_parameter_raw()` call | Any other parameter written, or a `*_raw` call made | Fake-MeCom-double-tested, real-hardware-consistent (writes only ever sent 2010/3000, Sessions 75-76) |
| 14. Parameter name correctness | `tec.py`'s parameter-name constants must match the real installed pyMeCom package's own table, not a second hand-typed string. | `test_tec_parameter_name_constants_match_the_real_installed_pymecom_table` compares against `mecom.commands.TEC_PARAMETERS` directly | Test passes when `mecom` is installed; skips (not fails) otherwise | A silent name mismatch would raise `UnknownParameter` on every real write, as the original `"Target Object Temp"` bug did | **Regression-tested (Session 76)**, confirmed to actually catch the real bug it's named for |
| 15. Dual-channel independent (unlocked) scan | Both channels move to their own target, genuinely simultaneously, at each scan step; UI lock/unlock toggle drives this via `TemperatureSeries.temperature_points_ch2_c`. | `apply_static_setpoint()`/`wait_until_stable()` accepting `dict[int, float]`; `qt_ui.py`'s `exp_tec_lock_channels` toggle + `exp_tec_points_ch2` field | Fake-backend test confirms each channel's own target is written and checked against its own target, not a shared one | A shared-target implementation would incorrectly compare one channel's temperature against the other's target | **Fake/unit-tested only (Session 77)** -- the dict-target code path has not been run against real hardware; the single-float broadcast path it shares is real-hardware verified |

## Historical Remaining Real-Hardware Claims

**Updated (Session 77):** connection, both channels' read/write/enable
paths, the write-config no-op assumption, and `wait_until_stable()`'s
own success-path loop are now real-hardware verified. What's left:

1. ~~connection over the intended physical interface~~ -- **done, COM6
   (Session 75).**
2. ~~read-only status and error-state readback against real values~~ --
   **done for both channels (Sessions 75-76); no error condition has been
   observed on real hardware yet -- see item 5.**
3. ~~target write on a harmless setpoint~~ -- **done, both channels
   (Sessions 75-76), including confirming `write_config()`'s no-op
   assumption holds on real hardware.**
4. ~~output-stage static-on semantics~~ -- **done, both channels, both
   ON and OFF (Sessions 75-76).**
5. stable/ready flag meaning (device status 1/2 vs. 3) -- confirmed
   Ready(1)/Run(2) transitions are real and device-wide (including the
   real transition back to Ready once both channels were disabled,
   Session 76). **Error(3) has never been observed on real hardware, and
   Session 77 investigated and decided against deliberately inducing one**
   (the real trigger -- exceeding an unread Error Threshold parameter --
   risks a genuine fault with no confirmed in-scope recovery path if
   auto-reset turns out disabled). **Accepted as a documented gap, not
   planned to be closed proactively** -- will be exercised for real if a
   genuine fault ever occurs during real use.
6. timeout behavior with a deliberately unreachable or guarded condition
   -- not yet attempted on real hardware.
7. abort behavior during a long wait -- offline/fake-tested against the
   real `stop_fired` mechanism (Session 80: the current temperature point
   always finishes, the next one never starts); not yet attempted on real
   hardware. This is no longer a `wait_until_stable()`-level interrupt
   question -- `should_abort` is a general `tec.py` API parameter, not fed
   by the real production call path (see item 9 above).
8. ~~both channels addressed independently on the real 2-channel unit~~ --
   **done (Session 76): a controlled write test confirmed channel 2 is a
   genuine, independent second control loop, not just an accepted write to
   an absent instance.**
9. ~~`TecController.wait_until_stable()`'s own polling loop~~ --
   **success path (tolerance + `min_settle_s`) done on channel 1
   (Session 77): target 25.65 C, converged and held within the requested
   0.2 C tolerance, `ready=True`, returned inside the 60s `max_wait_s`
   bound.** Timeout (`max_wait_s` exceeded) and abort (`should_abort`
   mid-wait) paths through this specific method are still offline-tested
   only.
10. ~~design question: how should the UI expose independent per-channel
    targets?~~ -- **answered and implemented (Session 77): a lock/unlock
    toggle, default locked (unchanged broadcast behavior), unlocked
    drives `TemperatureSeries.temperature_points_ch2_c` through the new
    `apply_static_setpoint()`/`wait_until_stable()` dict-target support.**
11. **New (Session 77):** the dict-target code path itself
    (`apply_static_setpoint({1: x, 2: y})`/`wait_until_stable({1: x, 2:
    y})`, genuinely simultaneous per-channel targets) has only been
    fake/unit-tested -- not yet run against real hardware. The
    single-float broadcast path it's built on top of has been
    real-hardware verified repeatedly (Sessions 75-77), but a real run
    with two different simultaneous per-channel targets has not.

The historical session record names a TEC-1123 with FW 5.10/HW 2.00 and
pyMeCom's default communication address (0/broadcast). Those details and the
reported connection/read/write/stability results are not independently
reproducible from this repository. Current authorization therefore remains
disabled/simulated despite the source-checked named parameter mapping.
