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

`src/thermo_acoustic/qt_ui_v3.py` (`MainWindowV3`) and its launcher, tool, and
test companions are tracked and formally accepted as repository content by
explicit owner decision as of this commit. V3 is an opt-in layout derivative:
it subclasses v2 and shares the same `Application` and hardware backends while
rebuilding several panels. Acceptance supersedes the prior "never commit v3"
rule; it does not make v3 the default UI or independently hardware-verified,
and it does not validate every duplicated panel or safety affordance. V1
remains the default operator UI, while v2 remains the rollback/reference path.

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
| v3 (`qt_ui_v3.py`, `MainWindowV3`) -- accepted opt-in layout derivative, not independently hardware-verified | `launch_gui_v3.bat` | `python tools\run_ui_v3.py` |

V3 is available from a fresh checkout but is not the default launch target.
Its acceptance into the repository does not promote it over v1 or establish
real-hardware validation.

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

The current shared evidence, event, shadow-preflight, TEC provenance, and
bench-preparation boundaries are documented in
`docs/runtime_truth_and_bench_preparation.md`. These software models do not
promote cached/protocol state to physical hardware verification.
