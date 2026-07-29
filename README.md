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

The DOCustom, DOClock, and Zstack tabs are intentionally omitted.
`src/thermo_acoustic/qt_ui_v2.py` (`MainWindowV2`) is an in-development
preview UI that reuses `qt_ui.py`'s widget-building and manual-test-panel
code (WFG/MSO/Pump&Valve/Camera open as dialogs from a sidebar). It is not
yet hardware-verified and is **not the default launch target** until
approved -- it must be launched explicitly (see "Launchers" below), never by
running `tools/run_ui.py`/`launch_gui.bat` alone.

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
- Valve and Z-stage serial devices: real COM-port text command transport is
  implemented with `pyserial` and is selected by clearing the relevant simulate
  toggle or enabling the Z-stage.
- Hamamatsu camera and Cetoni/Qmix pump: real SDK backends are implemented in
  `thermo_acoustic.hamamatsu_dcam` and `thermo_acoustic.qmix_backend`, with
  simulator paths still available through the UI toggles. Real operation still
  needs hardware validation with the installed SDKs and device configurations.

The UI runs hardware actions on worker threads, persists settings in
`.thermo_acoustic_ui.json`, and performs cleanup on Exit.
