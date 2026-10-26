# Thermo-acoustic control

This repository contains a single-process, simulation-first Qt application for
the thermo-acoustic test rig. It supports individual device commands,
experiment batches, and application-owned acquisition workflows.

## Architecture

`main.py` creates one `QApplication`, an application controller, a main
window, a console reader and a device registry. UI and console requests use
shared typed commands, validation and result events. Normal device commands
share one active dispatch lane. The queue is ordered, with explicit exceptions:
a flush owns its pump/valve resources while unrelated commands can proceed,
and background TEC observations use a separate request path. A queued wait is
an ordering barrier.

Long-running camera, pump and TEC operations use timer-driven steps on their
device workers. Urgent stop/cancel requests bypass the normal queue, but still
need the target worker event loop to execute them. They cannot interrupt an SDK
call that blocks that thread. Normal device dispatch is through workers; some
retained driver timeout/cleanup helpers also use their own threads.

The `hal/` package is the application-facing Hardware Abstraction Layer. Each
`DeviceWorker` is a `QObject` moved to its own persistent `QThread`.
`AD2Worker`, `PumpWorker`, `ValveWorker`, `CameraWorker`, `TecWorker`, and
`ZStageWorker` keep device-specific validation and device calls behind the HAL.
There is one worker per device in both modes. `DeviceRegistry` selects either a
real or simulated device factory and gives it to that worker. The factory runs
only after Connect reaches the worker's thread, so no device implementation is
constructed during startup or passive rendering.

```text
thermo_acoustic/
├── application/  command queue, controller, configuration, and audit
├── console/      stdin parsing and reading
├── domain/       shared device identity and status models
├── hal/          Qt device workers and registry
├── drivers/      reusable real and simulated implementations, grouped by device
├── ui/           Qt Widgets only
└── main.py       the single process entry point
```

The design is analogous to a LabVIEW queued message handler: one producer-safe
application queue, one dispatcher, and a dedicated actor/loop for each device.
There is no TCP/HTTP/socket protocol, named pipe, or controller process.
Image saving uses a host-side thread pool so the Qt event loop stays responsive.

## Start by double-click (Windows)

- `launch_ui.bat` starts the UI in **simulation** mode (no hardware is touched).
- `launch_ui_real.bat` starts **real** mode. Connect actions submit real device connections;
  there is no additional confirmation dialog for each Connect.

Both use `tools\launch_common.cmd`, which picks the first usable Python from: `THERMO_ACOUSTIC_PYTHON`
(your explicit choice; if it is set and unusable the launch fails instead of trying others), the
workspace `.venv`, then `%USERPROFILE%\.conda\envs\exp_ctrl`. Each candidate is validated by
`tools\check_launch_python.py` (Python 3.11+, PySide6, numpy, Pillow; real mode also pyserial,
pythonnet, mecom). `PATH` is not searched, nothing is installed, and a failed search never changes
the mode. If no Python qualifies, the window lists what was tried and what to do. Logs are written
to `logs\` in the workspace folder whatever directory the script is started from.

## Launch simulation

From the checkout root, using a Python with the UI dependencies already available:

```powershell
python tools/run_ui.py --mode simulation
```

On this lab workstation the double-click entry above can reuse `exp_ctrl` without
creating a workspace `.venv`. Installation/setup is a separate action; the launchers
do not install packages. An editable installation is another option when setting
up a new environment (`python -m pip install -e ".[ui,test]"`).

The program starts with every device disconnected. Example stdin commands:

```text
help
connect pump
pump set-flow 100
pump stop
pump read-fill-level
pump configure-syringe bd-5ml
pump configure-flow-unit ul/min
pump refill
pump empty 500
pump reference-move
camera set-exposure 2.5
camera set-roi 100 120 512 256
valve wait-ready
camera snapshot --exposure-ms 2.5
camera continuous-snapshot --exposure-ms 2.5
camera configure-sequence 100 2.5
camera sequence
camera save-sequence "C:/data/run-001" --format stacked
camera read-timing
ad2 configure-do 0 500 1100
ad2 start-do
ad2 stop-do
tec set-temperature 25
tec wait-stable 25 0.2 5 300
tec read-status
abort tec
z-stage check-closed-loop
z-stage enable-closed-loop
z-stage move 50
status
quit
```

The console prints timestamped, human-readable queued, running, completed, and
failed events with request IDs, call arguments, results, and errors. EOF is
treated as a quiet end of console input; it does not close the UI. `quit`
requests Qt application exit. Window-close handling drains an active batch before
worker shutdown; stop and cleanup errors keep the window open for inspection.

The desktop UI provides one independent control tab for each device. Every tab
shows connection, activity, fault, and typed readback state; normal actions use
the same global FIFO as the console, while abort and stop controls retain their
urgent path. Buttons for an already-pending operation are disabled until that
operation finishes. Numeric controls have no increment/decrement buttons, and
mouse-wheel changes are disabled for editors and dropdowns. The main window has
a 960 × 1080 minimum client size. Concise command progress appears in the status
bar; **Log > Show detailed log** opens a timestamped, scrollable event log. AD2
has separate Oscilloscope, Waveform generator, and Digital output sub-tabs. Its
waveform generator presents CH1 and CH2 side by side with Single Frequency,
Sweep, and Advanced views over one canonical two-channel configuration. Each
channel includes trigger and idle-output settings. AD2 Connect reads WaveForms
capabilities and applies the device limits to the editors. Scope input range is
selected from the exact SDK-reported range steps, and scope sampling defaults
to the device-reported maximum. The HAL rejects out-of-range UI or console
commands before configuration reaches the SDK. A successful configure is
followed by SDK getter readback, and the SDK-reported configuration repopulates
the controls; this is configuration evidence, not a measurement of physical
output. Scope uses single acquisition with an internal 10 ms completion poll;
analog detector triggering is edge-only. Scope, waveform, and digital-output
triggers are typed through the HAL to the driver; camera sequence trigger and
master-pulse settings follow the same route. Camera snapshot, continuous, and
buffered-sequence acquisitions apply their visible settings when capture starts
and display the latest frame in a separate acquisition window. Finite sequences
use DCAM's non-wrapping snapshot buffer, report captured-frame progress, and can
be saved as individual TIFF frames or one stacked TIFF. Every saved sequence
also includes `camera_settings.json` with timestamps and all readable DCAM
properties. AD2 scope reads are drawn in a dependency-free plot.

Use **File > Save settings** and **File > Load settings** to manage explicit
JSON input profiles. Profiles contain editable control values only. Loading a
profile never connects hardware, submits commands, restores stale readback, or
replays a previous log.

The application command surface exposes stable direct operations only. Driver
coercion helpers, SDK handles, discovery functions, and raw protocol methods are
not HAL commands. Camera sequence persistence is exposed as a typed application
command. Discovery and hardware probes
remain manual-only under `hardware_tests/`. Device status uses typed per-device
readback models rather than free-form key/value dictionaries.

## Experiment and Z-stack controls

The Experiments tab checks camera and syringe readiness separately. **Preflight
camera settings** exercises each distinct camera/trigger configuration in the
current form before it is queued. Its green result follows those tested camera
settings. **Preflight batch syringe level** refreshes each pump's level and
compares it with all planned flushes across the queued batch. Adding, editing,
or removing a series invalidates that batch result. A queued series can be
selected, loaded into the form, updated, or removed; removing it keeps its
output folder. In real mode, Start requires a current syringe capacity check
and warns about series without a camera preflight.

The TEC tab selects a COM port before a real connection. The Z-stage tab has
absolute and relative moves. The Z stack tab uses software-triggered camera
snapshots at evenly spaced positions, verifies each controller position before
capture, and writes TIFF images with camera and Z-position metadata. Choose an
existing empty folder before starting. Live preview is available while setting
endpoints and continues between stack captures. The pump tiles control a
two-position built-in CETONI valve independently of the serial valve tab.

## Real mode behaviour

`--mode real` selects real driver factories. Creating the registry/workers does
not construct or probe devices. A Connect button or console command submits the
connection directly; there is no generic extra Connect confirmation. The target
worker constructs and initializes its driver when that request executes.

Specific operations have their own handling: pump reference moves ask for
confirmation; Z closed-loop enabling requires its requirement to have been read;
real batch Start asks for approval and applies its preflight rules. Input/resource
validation is in the application and workers. Driver timeouts do not imply that
a blocked SDK call can be interrupted or that physical outputs are independently
confirmed stopped.

```powershell
python -m thermo_acoustic.main --mode real
```

Offline tests use simulation or injected fake drivers and do not prove physical
behavior. Never run `hardware_tests/` without explicit hardware authorization.

## Verification

```powershell
.venv\Scripts\python.exe -m compileall -q src
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python.exe -m pytest tests -q --basetemp=.pytest_tmp
python tools\check_repository_hygiene.py
```

Use the selected environment's interpreter in place of `.venv\Scripts\python.exe`
if this checkout has no local virtual environment. These are manual verification
commands, not prerequisites to opening the application.

Each UI launch creates a UTC-timestamped folder under `logs/` with a detailed
UI command log, structured JSON Lines audit log, and hardware transaction log.
The folder is ignored by Git. `--audit-log PATH` overrides only the audit file
location for callers that need a fixed path. Tests write logs only under
temporary directories.

## Retained drivers

The real pump factory creates `QmixPumpBank` in `drivers/pump/bank.py`. It
uses the CETONI implementation in `drivers/pump/cetoni.py` and a shared Qmix
session to expose the units declared in the selected Elements configuration.
Each device folder also contains a reusable simulated implementation exposing
the device-level methods used by its HAL worker. These simulators contain no Qt
or application code. Vendor APIs, data types, and errors remain behind the HAL
boundary. There is no aggregate `instruments.py` module or redundant standalone
neMESYS path.

## Current integration references

- `docs/integration/acceptance_table.md`: current scope, inheritance and evidence.
- `docs/integration/migration_checklist.md`: operating steps and where common changes go.
- `docs/integration/known_open_items.md`: retained policies and specific remaining questions.

Historical investigation and decision logs are source records, not the current
operating instructions. Existing hardware evidence is reused within its scope;
a missing new branch-labelled log does not by itself require hardware re-validation.
