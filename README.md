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

## Application Status

The runnable application is `tools/run_ui.py`. It reconstructs the LabVIEW
front panel tabs that are still in scope:

- Initialization
- WFG
- MSO
- Pump&Valve
- Camera
- Experiment

The DOCustom, DOClock, and Zstack tabs are intentionally omitted.

Hardware support currently works in three layers:

- Analog Discovery: real Digilent WaveForms calls are implemented in
  `thermo_acoustic.waveforms` and are selected by clearing `Simulate AD2`.
  The WFG and MSO tabs both use this path for real hardware. The MSO tab can
  capture CH1, CH2, or both channels, configure the AnalogIn trigger source,
  and plot captured traces with time and voltage axes.
- Valve and Z-stage serial devices: real COM-port text command transport is
  implemented with `pyserial` and is selected by clearing the relevant simulate
  toggle or enabling the Z-stage.
- Hamamatsu camera and Cetoni/Qmix pump: app protocols and simulated behavior
  are implemented. Real operation requires plugging vendor SDK adapters into
  `CameraBackend` and `PumpBackend` in `thermo_acoustic.instruments`.

The UI runs hardware actions on worker threads, persists settings in
`.thermo_acoustic_ui.json`, and performs cleanup on Exit.
