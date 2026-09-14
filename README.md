# Thermo-acoustic control

The retained instrument drivers sit behind a typed, simulation-first application
boundary and a PySide6 desktop UI. Simulation is the default. Real adapters are
available only through an explicit `--mode real` launch and every real device
still requires a separate, confirmed Connect action. Launching or passively
rendering either mode does not probe or initialize hardware.

## Architecture

Dependencies point inward and the UI knows nothing about driver classes:

```text
PySide6 UI -> typed commands -> application services -> typed device ports
                                     |                    |
                              experiment runner      adapters -> drivers
                                     |
                              safety coordinator
```

| Layer | Location | Responsibility |
| --- | --- | --- |
| Domain | `src/thermo_acoustic/domain/` | Immutable commands, configurations, results, status flags, and experiment plans |
| Application | `src/thermo_acoustic/application/` | Command routing, per-device serialization, background execution, sequences, and safe shutdown |
| Infrastructure | `src/thermo_acoustic/infrastructure/` | Typed simulated and real adapters around retained drivers |
| Presentation | `src/thermo_acoustic/ui/` | Render passive snapshots, collect input, and invoke typed application actions |

This is a pragmatic Hexagonal (Ports-and-Adapters) architecture. The ports are
Python protocols rather than factories or inheritance-heavy base classes.
Commands are typed per operation, and each adapter exposes simple status flags
(`connected`, `busy`, `configured`, `active`, `fault`) instead of embedding a
state-machine class. Safety limits and connection preconditions are enforced in
the application layer even though the UI also uses confirmations. Experiment
plans and their worker are application-owned; Qt never advances a sequence.

All potentially blocking device calls run outside the Qt event thread. UI
refreshes consume cached adapter state only; they never poll real hardware.
Experiment cancellation, failure, and application shutdown use the centralized
best-effort safety coordinator to stop active outputs before disconnecting.

## Run the offline UI

Install the project with its UI dependency, then launch it from the source
checkout:

```powershell
pip install -e ".[ui]"
python tools\run_ui.py
```

The default mode is `simulation`. The Overview page provides explicit device
connections. Device pages submit typed actions, and the Experiment page
demonstrates an application-owned simulation sequence.

Real mode must be chosen explicitly:

```powershell
python tools\run_ui.py --mode real
```

This constructs real adapters but performs no device I/O until the operator
confirms a Connect action. Real execution still requires workstation-specific
vendor runtimes and bench commissioning; offline success is not proof of
physical behavior.

Offline tests use simulation/fakes only:

```powershell
pip install -e ".[test,ui]"
pytest
```

Do not run files under `hardware_tests/` without explicit hardware authorization.

## Retained code

| Module | Purpose |
| --- | --- |
| `waveforms.py` | Digilent WaveForms DLL wrapper |
| `hamamatsu_dcam.py` | Hamamatsu DCAM camera driver |
| `qmix_backend.py` | CETONI Qmix pump driver |
| `nemesys_pump.py` | Standalone neMESYS pump interface |
| `thorlabs_piezo.py` | Thorlabs PPC001/Kinesis piezo driver |
| `tec.py` | Meerstetter communication and temperature-controller operations |
| `instruments.py` | Device interfaces, serial/valve control, and simulations |
| `ad2.py`, `camera.py` | Device configuration and ROI types |
| `hw_logging.py` | Shared driver logging and timeout/cleanup support |
| `thorlabs_apt.py` | Optional APT device-discovery support |
| `ad2_capture_tooling.py` | Confirmation and cleanup helpers for manual AD2 diagnostics |

These are retained implementations, not newly commissioned or redesigned drivers.
The AD2 interface and DLL wrapper remain separate; consolidation is future work.

## Driver setup

Use Python 3.11 or newer. The existing lab package pins are retained for the
remaining dependencies in `requirements-exp_ctrl.txt`:

```powershell
pip install -r requirements-exp_ctrl.txt
python tools\check_environment.py
```

Vendor SDKs remain separate: DCAM and Qmix wrappers are in `dcamsdk4/` and
`qmix_sdk_for_codex/`; WaveForms, DCAM, CETONI runtime DLLs and Kinesis must
be installed/configured on the hardware workstation. No local environment
was changed as part of this cleanup.

## Verification and hardware use

CI compiles Python and checks repository hygiene. The retired application's
test suite is removed; these checks do not prove driver or hardware behavior.
Manual diagnostics remain in `hardware_tests/` and are never run by CI.
Some discovery scripts access real devices: read the selected script and
obtain explicit authorization before running it. See `hardware_tests/README.md`.

Follow `AGENTS.md`. Keep UI presentation and experiment sequencing outside the
drivers. Preserve measurement files, logs, vendor manuals, and SDKs.

The old application is preserved at Git tag `reference/old-ui` and in the
separate reference checkout. Consult it only when explicitly requested.
