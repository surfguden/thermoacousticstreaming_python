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
"Launchers" section below for both the v1 and v2 variants.

## Application Status

The runnable application is `tools/run_ui.py`, which launches
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
`src/thermo_acoustic/qt_ui_v2.py` (`MainWindowV2`) is an in-development
preview UI that reuses `qt_ui.py`'s widget-building and manual-test-panel
code (WFG/MSO/Pump&Valve/Camera open as dialogs from a sidebar). It is not
yet hardware-verified and is **not the default launch target** until
approved -- it must be launched explicitly (see "Launchers" below), never by
running `tools/run_ui.py`/`launch_gui.bat` alone.

## Environment Setup

Production (real hardware) runs use a dedicated Conda environment named
`exp_ctrl` -- both `launch_gui.bat`/`launch_gui_v2.bat` and this project's
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

`requirements-exp_ctrl.txt` pins the exact versions currently validated in
the real `exp_ctrl` environment; `pyproject.toml`'s own `dependencies` list
states the same packages with looser lower bounds, for general
installability. Vendor SDKs (CETONI Qmix, Hamamatsu DCAM, Thorlabs Kinesis)
are not pip packages and are not covered by either file -- see the comments
at the top of `requirements-exp_ctrl.txt` for how each of those is actually
installed/located.

## Launchers

Two clearly-separate launchers exist for the two UIs, on purpose -- never a
single script with a mode switch, so there's no way to launch the wrong one
by mistake:

| Launches | Windows batch file (double-click) | Dev command |
| --- | --- | --- |
| v1 (`qt_ui.py`, `MainWindow`) -- the validated, default UI | `launch_gui.bat` | `python tools\run_ui.py` |
| v2 (`qt_ui_v2.py`, `MainWindowV2`) -- in-development preview, not hardware-verified | `launch_gui_v2.bat` | `python tools\run_ui_v2.py` |

The `.bat` files use a fixed Conda environment path (edit `PYTHON_EXE` at the
top of either script if that path changes); the `tools/run_ui*.py` scripts
use whatever `python` currently resolves to instead, which is more
convenient for day-to-day development.

Hardware support currently works in three layers:

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
