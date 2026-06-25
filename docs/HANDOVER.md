# Codex Handover

This project is a Python port of a LabVIEW thermo-acoustic streaming application.
The current repo is pushed to:

```text
git@github.com:surfguden/thermoacousticstreaming_python.git
```

At handover time the local branch was `main`, tracking `origin/main`, with the
initial commit:

```text
ac355b9 Initial Python port
```

## How To Run

From PowerShell:

```powershell
cd "C:\Users\Ola\Documents\Labview to Python Conversion"
python tools\run_ui.py
```

If `python` is not visible in that shell, use the bundled runtime:

```powershell
& "C:\Users\Ola\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" tools\run_ui.py
```

Run tests with:

```powershell
python -m pytest -q
```

Last verified test result before handover:

```text
20 passed
```

## Main Files

- `tools/run_ui.py`: launches the PySide6 application.
- `src/thermo_acoustic/qt_ui.py`: main Qt UI. Current tabs are Initialization,
  WFG, MSO, Pump&Valve, Camera, and Experiment.
- `src/thermo_acoustic/application.py`: application orchestration. The
  experiment execution order is in `Application.run_experiment2`.
- `src/thermo_acoustic/instruments.py`: instrument facade classes and simulator
  implementations.
- `src/thermo_acoustic/waveforms.py`: Digilent WaveForms `ctypes` backend for
  Analog Discovery WFG, DO, and MSO/AnalogIn calls.
- `src/thermo_acoustic/hamamatsu_dcam.py`: Hamamatsu DCAM SDK backend.
- `src/thermo_acoustic/workflows.py`: `Experiment2`, `ExperimentSeries2`, and
  `FlushSettings`.
- `tools/generate_port_registry.py`: regenerates `port_status.json`,
  `labview_ports.py`, and `docs/PORTING_TBD.md`.
- `docs/PORTING_TBD.md`: generated VI coverage plus manual runtime/hardware
  validation checklist.

## Current Functional State

The VI semantic registry reports all documented LabVIEW sections represented:

```text
Documented VI sections: 305
Implemented in Python: 305
Partially represented: 0
Stub only: 0
```

The runnable UI reconstructs the in-scope LabVIEW tabs. `DOCustom`, `DOClock`,
and `Zstack` were intentionally omitted from the UI by user request, though some
lower-level DO/Z-stack behavior exists in the Python modules.

Instrument status:

- Analog Discovery: real WaveForms calls are implemented. WFG and MSO can use
  real hardware when `Simulate AD2` is unchecked.
- MSO: UI supports CH1/CH2 enable selection, trigger-source selection, sample
  frequency, sample count, range, offset, dual-channel plotting, and x/y axes.
- Hamamatsu camera: real DCAM backend is implemented against the uploaded
  `dcamsdk4/samples/python/dcam.py` wrapper. Sequence saving now writes TIFF
  files named `frame_00000.tiff`, `frame_00001.tiff`, etc.
- Camera smoke test: `tools/test_hamamatsu_camera.py` opens the real camera,
  captures a snapshot, and saves `hamamatsu_snapshot.tiff`.
- Pump: simulated API exists and `QmixPumpBackend` provides the real
  Cetoni/Qmix SDK adapter. It opens the Qmix bus, looks up a pump by name or
  index, starts communication, clears faults, enables the drive, configures
  uL/min flow units, supports syringe presets/explicit geometry, and dispatches
  refill/empty/flow/fill-level/reference commands.
- Valve/Z-stage: serial text backend exists through `pyserial`, but real command
  strings, baud, line endings, and response parsing still need validation on the
  actual hardware.

## Experiment Execution Order

The experiment execution path is in `src/thermo_acoustic/application.py`:
`Application.run_experiment2`.

Current order:

1. Dequeue one experiment from `ExperimentSeries2`.
2. Create experiment folder and save settings.
3. Configure AD2 WFG.
4. Configure AD2 DO clock special settings.
5. Configure camera exposure.
6. Configure camera sequence.
7. Start camera capture.
8. Fire AD2 PC trigger.
9. Capture image sequence.
10. Stop camera capture.
11. If aborted, cleanup and return.
12. Flush with pump/valve settings.
13. Save camera sequence as TIFF files.
14. Save image data/settings hooks.
15. Cleanup and emit `ExperimentComplete`.

The Qt UI builds experiment queues in `MainWindow._build_experiment_series` and
runs them in `MainWindow._run_experiment_series`.

## Important Hardware Notes

- If Analog Discovery reports busy or `DwfDeviceOpenEx`, check whether LabVIEW
  or another process still owns the device. `tools/release_ad2.py` can enumerate
  and close WaveForms handles.
- The user previously connected Wavegen CH1 to oscilloscope input and verified
  capture/plotting with Python.
- The user's requested image output format is TIFF, not NumPy `.npy`.
- The Hamamatsu SDK folder `dcamsdk4` is currently committed in full, including
  docs, samples, headers, and library files. If repo size becomes a problem,
  consider keeping only the Python wrapper files actually used by the backend.

## Version Control Notes

`.gitignore` intentionally ignores:

- Python caches and pytest caches.
- Local UI state: `.thermo_acoustic_ui.json`.
- Hardware capture outputs such as `ad2_scope_capture.*`,
  `ad2_matplotlib_plot.*`, `hamamatsu_snapshot.*`, `frame_*.tiff`,
  `frame_*.npy`, and `*.tdms`.

The SSH key created for GitHub is:

```text
C:\Users\Ola\.ssh\thermoacousticstreaming_python_ed25519
```

The public key is:

```text
C:\Users\Ola\.ssh\thermoacousticstreaming_python_ed25519.pub
```

Do not expose or commit the private key.

## Next Best Steps

1. Run `python -m pytest -q` after pulling the handover repo.
2. Run `python tools\run_ui.py` with all simulate toggles enabled.
3. Validate Hamamatsu real camera with `python tools\test_hamamatsu_camera.py`.
4. Validate TIFF output bit depth and metadata expectations against downstream
   analysis.
5. Run MSO hardware tests across all trigger-source options.
6. Validate the real Cetoni/Qmix pump backend with the installed SDK, actual
   device configuration, and confirmed syringe geometry.
7. Validate valve serial commands on the MX valve.
8. Run the full Experiment tab end-to-end with AD2, Hamamatsu, pump, and valve.
9. Decide packaging/startup path for the operator.
