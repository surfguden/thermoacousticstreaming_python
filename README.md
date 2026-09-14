# Thermoacoustic Streaming Instrument Control

Python control software for the laboratory thermoacoustic-streaming instrument.

## Setup

Use Python 3.11 and the lab environment dependencies:

```powershell
conda create -n exp_ctrl python=3.11
conda activate exp_ctrl
pip install -r requirements-exp_ctrl.txt
python tools\check_environment.py
```

`requirements-exp_ctrl.txt` pins the lab environment; `pyproject.toml` declares
minimum package dependencies. Vendor SDK installation and configuration are
separate; see the comments in the requirements file. The camera and pump
backends use wrappers in `dcamsdk4/` and `qmix_sdk_for_codex/`.

## Launch

| UI | Python command | Windows launcher |
| --- | --- | --- |
| V1, default operator UI | `python tools\run_ui.py` | `launch_gui.bat` |
| V3, opt-in UI | `python tools\run_ui_v3.py` | `launch_gui_v3.bat` |

The batch files set machine-specific Python and Qmix SDK paths; check those
paths before use. The Python commands use the active environment.
Local settings are stored in ignored `.thermo_acoustic_ui.json`.

Both UIs share `Application` and the hardware backends. Experiment planning,
execution, and hardware control belong outside UI presentation. V3 is not
independently hardware-verified.

## Offline checks

```powershell
python tools\check_repository_hygiene.py
python -m pytest -q
```

Pytest collects only `tests/`. The offline CI workflow checks repository
hygiene and selected software contracts using fakes and offscreen UI tests.
Software checks do not establish physical hardware behavior.

## Hardware and working rules

Follow `AGENTS.md`. Hardware access requires explicit authorization.
Manual hardware probes belong under `hardware_tests/` with explicit gates;
read that folder's README and the selected script before any authorized use.
The `manual_*.py` diagnostics there include action-capable commands.

Treat persisted settings and historical bench notes as context, not proof of
current readiness. Preserve measurement files and hardware logs when cleaning
generated caches.

Historical LabVIEW exports, migration registries, and removed documentation
remain available in Git history.
