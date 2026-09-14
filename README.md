# Thermo-acoustic control

The retained instrument drivers now sit behind a new simulation-first
application boundary and desktop UI. Real-hardware adapters are deliberately
not enabled yet; launching or passively rendering the UI does not probe,
import, or initialize hardware.

## Architecture

Dependencies point inward and the UI knows nothing about driver classes:

```text
PySide6 UI -> application actions/state -> device ports -> adapters -> drivers
                         ^
                 experiment runner
```

| Layer | Location | Responsibility |
| --- | --- | --- |
| Domain | `src/thermo_acoustic/domain/` | Immutable device, experiment, and status models |
| Application | `src/thermo_acoustic/application/` | Lifecycle, validation, and non-blocking sequence execution |
| Infrastructure | `src/thermo_acoustic/infrastructure/` | Explicit simulated/real adapter selection |
| Presentation | `src/thermo_acoustic/ui/` | Render state, collect input, and invoke application actions |

The initial infrastructure implementation is simulation-only. Connecting to
real devices will require a separately reviewed adapter implementation and an
explicit real-mode choice. Safety limits and connection preconditions are
enforced in the application layer even though the UI also uses confirmations.

## Run the offline UI

Install the project with its UI dependency, then launch it from the source
checkout:

```powershell
pip install -e ".[ui]"
python tools\run_ui.py
```

The only accepted mode is currently `simulation`. The Overview page provides
explicit simulated connections. Device pages exercise validated application
actions, and the Experiment page demonstrates an application-owned sequence.

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
