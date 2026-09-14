# Laboratory hardware drivers

Hardware-only baseline for the thermoacoustic-streaming instruments.
There is no UI, experiment planner, or automatic experiment runner.

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

## Setup

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

Follow `AGENTS.md`. Keep future UI presentation and experiment sequencing
outside the drivers. Preserve measurement files, logs, vendor manuals, and
SDKs during cleanup.

The old application is preserved at Git tag `reference/old-ui` and in the
separate reference checkout. Consult it only when explicitly requested.
