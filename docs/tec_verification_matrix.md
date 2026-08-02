# TEC Verification Matrix

This document is the TEC-specific verification boundary for the current
Meerstetter integration. It is documentation only; it does not authorize real
hardware operation.

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
  Communication Protocol documents. This repository has not yet bound those
  IDs to a reviewed real Meerstetter client.
- The TEC-Family user documentation distinguishes persistent `Static OFF/ON`
  output-stage settings stored in flash from volatile `Live OFF/ON` settings
  held in RAM. The controller-specific parameter mapping remains unbound here.
- The vendor's configuration workflow describes Write Config as saving changed
  parameters to the controller. This repository has no reviewed client call or
  controller-specific persistence mapping for that operation.

Therefore the current Python implementation deliberately stays at a
reviewed-client boundary. It does not guess MeCom register numbers.

## Protocol-Mapping Inventory

The vendor's TEC-Family protocol material is useful evidence, but it is not a
safe binding for this lab until the installed controller model, firmware,
channel instance, and reviewed Python client are recorded. The shipped code
does not issue any of the parameter IDs below.

| Required action | Official evidence | Current repository state | Classification |
| --- | --- | --- | --- |
| Connect / discover | MeCom supports USB, RS485, and RS232 TTL; direct USB appears as a virtual serial port. | `MeerstetterTecBackend` accepts a client factory, but no pyMeCom package/client factory or controller address is present. | Verified by official docs only, not implemented for real hardware |
| Read device status / fault | TEC-Family protocol catalogues device-status and error fields. | `TecStatus` is a high-level scaffold supplied only by simulated or externally reviewed clients. | Implemented in scaffold only; real mapping unresolved |
| Read object temperature | The protocol documents object-temperature readback for a TEC-Family controller instance. | No real read command or instance binding exists. | Verified by official docs only, not implementation-ready for this controller |
| Set target object temperature | The protocol documents a target-object-temperature setting for a TEC-Family controller instance. | No real write command or instance binding exists. | Verified by official docs only, not implementation-ready for this controller |
| Static ON output stage | The user manual says `Static OFF/ON` is persistent in flash, while `Live OFF/ON` is volatile in RAM. | `set_output_stage_static_on()` is only a required high-level reviewed-client method. | Unresolved; do not infer the static mapping from a live-mode example |
| Write configuration | Vendor configuration guidance says Write Config saves changed parameters to the controller. | `write_config()` is a high-level reviewed-client method only. | Unresolved / cannot be implemented yet |
| Readback, stable wait, abort / timeout | Vendor material distinguishes Ready, Run, and Error states, but does not establish this experiment's stability criterion. | Local simulated workflow polls `TecStatus`, with explicit tolerance, settle time, timeout, and abort callback. | Implemented in scaffold only; real ready/stability semantics unresolved |

The official references for this inventory are the [TEC controller remote-control
overview](https://www.meerstetter.ch/customer-center/compendium/64-tec-controller-remote-control),
the [TEC-Family MeCom protocol downloads](https://www.meerstetter.ch/customer-center/downloads/category/35-latest-communication-protocols),
and the [TEC-Family user manual downloads](https://www.meerstetter.ch/customer-center/downloads/category/15-tec-family-tec-controllers-user-manuals).

## Current Python Boundary

The safe default is:

- TEC disabled by default.
- TEC simulated by default.
- The shipped UI/factory does not supply a reviewed Meerstetter client/factory.
  Selecting real TEC therefore refuses before a device connection or any TEC
  I/O. A UI resource field alone does not make the real path usable.
- Temperature series uses one target temperature per experiment group.
- The TEC waits for stability before running that group.
- The wait has an explicit timeout and an abort/cancel callback.
- Target temperatures are rejected outside the local application safety range
  `[0.0, 80.0] C` before they reach any backend.

The `[0.0, 80.0] C` range is a local software safety envelope, not a
Meerstetter device-limit claim.

## Verification Matrix

| Item | Expected behavior | Code path | Confirm success by | Failure mode | Current status |
| --- | --- | --- | --- | --- | --- |
| 1. Connection / discovery | TEC connects only when enabled. Simulated backend connects locally; the shipped UI's real selection has no client/factory and refuses before I/O. | `HardwareRuntimeConfig.tec_enabled`, `build_hardware_bundle()`, `TecController.initialize()`, `MeerstetterTecBackend.connect()` | `TecController.initialized=True`, backend `read_status()` returns without error | Real backend without client raises `TecError`; no silent fake connection or attempted connection | Simulated only in shipped UI; reviewed-client integration unresolved |
| 2. Read-only status | Read current/target temperature, output stage state, ready flag, and error state. | `TecController.read_status()`, backend `read_status()` | `TecStatus` fields populated | Missing/unsupported client method raises `TecError`; backend error state surfaces | Simulated and reviewed-client-only |
| 3. Target temperature validation | Reject non-finite or out-of-range target before backend call. | `validate_tec_target_temperature()`, `TemperatureSeries.__post_init__()`, `TecController.apply_static_setpoint()` | Accepted target is finite and within `[0.0, 80.0] C` | `ValueError` before any backend write | Offline-tested |
| 4. Set target temperature | Apply one static target for a group. | `Application.run_temperature_series()` -> `TecController.apply_static_setpoint()` -> backend `set_target_temperature()` | Readback status target/current fields or reviewed client confirmation | Backend raises `TecError`; error state raises `TecError` | Simulated and reviewed-client-only |
| 5. Enable output stage static on | Turn on static output-stage control before setting target. | `TecController.apply_static_setpoint()` -> backend `set_output_stage_static_on()` | `TecStatus.output_stage_static_on=True` or reviewed client equivalent | Missing client method raises `TecError` | Simulated and reviewed-client-only |
| 6. Write config | Persist/apply the target configuration through the reviewed client. | `TecController.apply_static_setpoint()` -> backend `write_config()` | `read_status()` after write reports no error | Missing client method or error state raises `TecError` | Simulated and reviewed-client-only |
| 7. Temperature/readiness readback | Confirm current temperature, target, ready flag, and fault/error state after write and during wait. | `TecController.read_status()`, `wait_until_stable()` | `ready=True`, current within tolerance for the minimum settle time | Error state raises `TecError`; unsupported status response raises `TecError` | Simulated and reviewed-client-only |
| 8. Stability wait | Wait until current temperature remains within tolerance for `min_settle_s`, bounded by `max_wait_s`. | `TecController.wait_until_stable()` | Returns final `TecStatus` | Raises `TimeoutError` after `max_wait_s` | Offline-tested |
| 9. Abort/cancel during wait | Abort request interrupts a long stabilization wait. | `Application.run_temperature_series()` passes `self.listen_abort` into `wait_until_stable()` | Returns `False`, status `TemperatureSeriesAborted` | Raises/handles `TecAbortedError`; experiment group does not start | Offline-tested |
| 10. Timeout behavior | Non-stabilizing target fails clearly instead of running the group. | `TecController.wait_until_stable()` | `TimeoutError` with last status | No experiment group should run after timeout | Offline-tested at controller level |
| 11. One temperature per group | Set one target, wait stable, then run all repeats in that group before moving to next target. | `Application.run_temperature_series()` | Target calls match group count; repeat calls occur under each group path | Mismatched count raises `ValueError`; group stops on failed repeat | Offline-tested |
| 12. Isolation from other hardware | TEC orchestration must not alter AD2/camera/pump/valve/Qmix/Z except by running the normal experiment group after stabilization. | `Application.run_temperature_series()` | Before group start, only TEC calls occur | Any extra hardware call before stabilization is a bug | Fake-tested indirectly; real hardware still gated |

## Remaining Real-Hardware Verification

Before enabling real TEC operation in routine experiments, a human-reviewed
client/factory must bind the official MeCom parameter IDs for the actual
controller and firmware, and a separately reviewed UI/factory integration must
supply that client. The first real run should verify:

1. connection over the intended physical interface;
2. read-only status and error-state readback;
3. target write and config write on a harmless setpoint;
4. output-stage static-on semantics;
5. stable/ready flag meaning;
6. timeout behavior with a deliberately unreachable or guarded condition;
7. abort behavior during a long wait.

The actual controller model, firmware revision, selected channel/instance,
communication address, and vendor client API are still unrecorded in this
repository. Those facts are prerequisites, not values to infer from a generic
TEC-Family protocol example.

Do not treat the current scaffold as a complete real Meerstetter backend.
