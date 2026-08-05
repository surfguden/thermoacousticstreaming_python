# LabVIEW to Python Conversion

This workspace is being converted from the LabVIEW HTML export in `main_html/`.

The export currently documents `Main.vi` and its subVIs as images. The Python
conversion starts with the application structure and simulated instrument
interfaces, then ports individual VI behavior into focused Python methods.

## Useful Commands

```powershell
python tools\run_ui.py
python -m pytest -q
```

On Windows, `launch_gui.bat` (double-click, or run from a terminal) does the
same thing as `python tools\run_ui.py`, using a fixed Conda environment path
instead of whatever `python` currently resolves to on your PATH -- see the
"Launchers" section below for the v1, v2, and v3 variants.

## Application Status

The default operator entry point is `tools/run_ui.py`, which launches
`thermo_acoustic.qt_ui` (`MainWindow`). It reconstructs the LabVIEW
front panel tabs that are still in scope:

- Initialization
- WFG
- MSO
- Pump&Valve
- Camera
- Experiment

The direct DOCustom, DOClock, and Zstack tabs are intentionally omitted.
DO Clock Special remains structurally active in the experiment path for the
DIO1 LED timing configuration; it is not a standalone UI tab.
`src/thermo_acoustic/qt_ui_v2.py` (`MainWindowV2`) is an actively maintained
transitional UI that reuses `qt_ui.py`'s widget-building, manual-test-panel
code, and the same `Application`/hardware-backend instance (WFG/MSO/
Pump&Valve/Camera open as dialogs from a sidebar). It is **not a simulated
sandbox or an independent hardware stack**: when the operator initializes a
real device there, it uses the shared real runtime. It is not yet independently
hardware-verified and is **not the default launch target** until approved -- it
must be launched explicitly (see "Launchers" below), never by running
`tools/run_ui.py`/`launch_gui.bat` alone.

`src/thermo_acoustic/qt_ui_v3.py` (`MainWindowV3`) is the newer transitional
layout. It subclasses v2 and reuses the same `Application`, hardware objects,
workers, initialization, and experiment builders. Its changes are limited to
information hierarchy and manual-panel layout; v2 remains available as the
rollback/reference path. v3 is also opt-in and not independently hardware-
verified.

For current v3 layout development, the recommended launch command is
`launch_gui_v3.bat` on the lab Windows machine, or
`python tools\run_ui_v3.py` from an already-configured environment. This does
not change v1's status as the approved default operator entry point.

## Environment Setup

Production (real hardware) runs use a dedicated Conda environment named
`exp_ctrl` -- `launch_gui.bat`/`launch_gui_v2.bat`/`launch_gui_v3.bat` and this project's
own real-hardware verification scripts (`hardware_tests/`) point at it. It
is hand-assembled, not created fresh from a manifest each time, so it can
drift from what the code actually needs -- this happened once already
(`npTDMS` was missing until 2026-07-31, undetected until a real experiment
run tried to write `data.tdms`; see `docs/known_open_items.md`).

**To (re)create `exp_ctrl` from scratch:**

```powershell
conda create -n exp_ctrl python=3.11
conda activate exp_ctrl
pip install -r requirements-exp_ctrl.txt
```

**To confirm an environment (new or existing) actually has everything the
real app needs**, run this after setup and any time you suspect drift:

```powershell
python tools\check_environment.py
```

It imports every real, third-party dependency the production code path
uses and reports pass/fail per package -- exit code 0 means the environment
is complete, non-zero means something is missing (and names exactly what).
This is the check that would have caught the original `npTDMS` gap
immediately instead of on a real-hardware run.

`requirements-exp_ctrl.txt` records the intended versions for the lab's
`exp_ctrl` environment; it is not proof that a local environment or a real
hardware path has been independently validated. `pyproject.toml` declares
looser minimum dependencies for general installability. Vendor SDKs (CETONI
Qmix, Hamamatsu DCAM, Thorlabs Kinesis) are not pip packages and are not
covered by either file -- see the comments at the top of
`requirements-exp_ctrl.txt` for how each is installed/located.

## Launchers

Three clearly-separated launchers exist for the three UIs, on purpose -- never a
single script with a mode switch, so there's no way to launch the wrong one
by mistake:

| Launches | Windows batch file (double-click) | Dev command |
| --- | --- | --- |
| v1 (`qt_ui.py`, `MainWindow`) -- default operator UI | `launch_gui.bat` | `python tools\run_ui.py` |
| v2 (`qt_ui_v2.py`, `MainWindowV2`) -- older transitional layout and rollback/reference path | `launch_gui_v2.bat` | `python tools\run_ui_v2.py` |
| v3 (`qt_ui_v3.py`, `MainWindowV3`) -- active layout-development direction; opt-in and not hardware-verified | **`launch_gui_v3.bat` (recommended for v3 work)** | `python tools\run_ui_v3.py` |

The `.bat` files use a fixed Conda environment path (edit `PYTHON_EXE` at the
top of either script if that path changes); the `tools/run_ui*.py` scripts
use whatever `python` currently resolves to instead, which is more
convenient for day-to-day development.

The source contains three hardware-integration layers. Their presence is not
independent real-hardware validation:

- Analog Discovery: real Digilent WaveForms calls are implemented in
  `thermo_acoustic.waveforms` and are selected by clearing `Simulate AD2`.
  The WFG and MSO tabs both use this path for real hardware. The MSO tab can
  capture CH1, CH2, or both channels, configure the AnalogIn trigger source,
  and plot captured traces with time and voltage axes.
- Valve serial transport: real COM-port text command transport is implemented
  with `pyserial` and is selected by clearing the valve's Simulate toggle. The
  current Z hardware is a Thorlabs PPC001 controlled through the Kinesis USB
  API; its manual calibration motion is not a generic serial-device path.
- Hamamatsu camera and Cetoni/Qmix pump: real SDK backends are implemented in
  `thermo_acoustic.hamamatsu_dcam` and `thermo_acoustic.qmix_backend`, with
  simulator paths still available through the UI toggles. Real operation still
  needs hardware validation with the installed SDKs and device configurations.

The UI runs hardware actions on worker threads, persists settings in
`.thermo_acoustic_ui.json`, and performs cleanup on Exit.
