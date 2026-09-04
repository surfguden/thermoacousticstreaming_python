# Thermoacoustic Streaming Instrument Control

Python control software for the laboratory thermoacoustic-streaming instrument.
The repository originated as a LabVIEW migration, but the current normal
experiment is governed by the Python request/plan/runtime path; retained
LabVIEW exports are migration evidence, not current operational authority.

Read [`docs/project_control.md`](docs/project_control.md) first for current
architecture, workflow, routing, evidence semantics, readiness, and the single
next project step. Genuine unresolved/deferred work is in
[`docs/known_open_items.md`](docs/known_open_items.md). Historical audits,
handovers, and changelogs preserve reasoning but may describe superseded state.

## Useful Commands

```powershell
python tools\run_ui.py
python -m pytest -q
```

For an objective session-start snapshot and mechanical repository checks:

```powershell
python tools\project_state_report.py
python tools\audit_change_surface.py --symbol _build_experiment_series
python tools\check_repository_hygiene.py
```

`AGENTS.md` is the concise repository working contract. The offline GitHub
Actions workflow compiles Python, validates tracked-file/LabVIEW-export
consistency, runs fake/unit coverage, and exercises selected shared v1/v2/v3
contracts. It never collects `hardware_tests/` or manual probes and does not
authorize real devices. Recommended repository policy: require this workflow
to pass before merging, while leaving hardware evidence as a separate reviewed
bench process.

Before committing, compare the drafted commit message with the actual staged
change:

```powershell
git diff --cached --stat
git show --stat --oneline HEAD  # after committing, before pushing
```

Every changed file must be accounted for, and no message claim may contradict
the diff. This check is mandatory because `c918eb3` overstated its discovery
test coverage, `7c7e19f` said the four v3 files were excluded while adding
them, `4105fa8` retained unfilled message-template placeholders, and `22c68cb`
re-added the v3 files without disclosing them.

The retained 2026-08-28 P0 bench evidence and its explicit unresolved limits
are in `docs/p0_hardware_truth_20260828.md`.

On Windows, `launch_gui.bat` (double-click, or run from a terminal) does the
same thing as `python tools\run_ui.py`, using a fixed Conda environment path
instead of whatever `python` currently resolves to on your PATH -- see the
"Launchers" section below for the tracked v1, v2, and v3 variants.

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
Normal production plans explicitly disable digital output on DIO0 and DIO1,
and the experiment runtime does not program DO Clock Special; retained DO
helpers are legacy/manual capabilities only. Owner-supplied current wiring maps project Ch1
to AD2 API 0 / W1 / acoustic amplifier and transducer, and project Ch2 to API 1
/ W2 / laser Analog In. Normal production rejects enabled W2 pending exact
laser input semantics. DIO0/pink is connected to camera trigger and DIO1/green
to laser trigger, but neither digital line is programmed in the current
steady-state workflow.
`src/thermo_acoustic/qt_ui_v2.py` (`MainWindowV2`) is the retained transitional
rollback/reference UI that reuses `qt_ui.py`'s widget-building, manual-test-panel
code, and the same `Application`/hardware-backend instance (WFG/MSO/
Pump&Valve/Camera open as dialogs from a sidebar). It is **not a simulated
sandbox or an independent hardware stack**: when the operator initializes a
real device there, it uses the shared real runtime. It is not yet independently
hardware-verified and is **not the default launch target** until approved -- it
must be launched explicitly (see "Launchers" below), never by running
`tools/run_ui.py`/`launch_gui.bat` alone.

`src/thermo_acoustic/qt_ui_v3.py` (`MainWindowV3`) is the tracked, opt-in,
offline-UX-reviewed instrument surface. It has V3-owned compatibility support,
does not import or subclass v2, and shares the same
`Application` and hardware backends; it is not a simulator or a separate
execution stack. Its persistent instrument state and run controls surround four
workspaces: Experiment, Monitor, Manual & Service, and Diagnostics. Experiment
contains the canonical-request-derived “Start will run” review and surfaces
requested-versus-latest-applied evidence without becoming a second planner.
V3 remains non-default and not independently hardware-verified. V1 remains the
default operator UI; v2 remains present for rollback/reference during the
owner-approved early-retirement sequence.

## Environment Setup

Production (real hardware) runs use a dedicated Conda environment named
`exp_ctrl` -- `launch_gui.bat`/`launch_gui_v2.bat` and this project's
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

Three tracked, clearly-separated launchers exist for the repository UIs:

| Launches | Windows batch file (double-click) | Dev command |
| --- | --- | --- |
| v1 (`qt_ui.py`, `MainWindow`) -- default operator UI | `launch_gui.bat` | `python tools\run_ui.py` |
| v2 (`qt_ui_v2.py`, `MainWindowV2`) -- older transitional layout and rollback/reference path | `launch_gui_v2.bat` | `python tools\run_ui_v2.py` |
| v3 (`qt_ui_v3.py`, `MainWindowV3`) -- offline-UX-reviewed opt-in instrument workflow, not independently hardware-verified | `launch_gui_v3.bat` | `python tools\run_ui_v3.py` |

V3 is available from a fresh checkout but is not the default launch target.
Its reviewed presentation does not promote it over v1, authorize hardware, or
turn software/protocol state into physical verification.

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
- Hamamatsu camera and CETONI/Qmix pump: real SDK backends are implemented in
  `thermo_acoustic.hamamatsu_dcam` and `thermo_acoustic.qmix_backend`, with
  simulator paths still available through the UI toggles. Real operation still
  remains subject to the feature-specific gates in `docs/known_open_items.md`.

The UI runs hardware actions on worker threads, persists settings in
`.thermo_acoustic_ui.json`, and performs cleanup on Exit.

The current evidence/action model and operator boundary are summarized in
`docs/project_control.md`. `docs/runtime_truth_and_bench_preparation.md` is a
dated design/bench-preparation record and must not override newer current truth.
