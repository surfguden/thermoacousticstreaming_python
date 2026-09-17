# Thermo-acoustic control

This repository contains a single-process, simulation-first Qt application for
the thermo-acoustic test rig. It is deliberately limited to individual device
commands; experiments, recipes, and multi-device sequencing are deferred.

## Architecture

`main.py` creates one `QApplication`, one `ApplicationController`, one Qt
window, one console reader, and one device registry. The controller owns a
global FIFO queue and dispatches exactly one command at a time. UI buttons and
stdin both create the same typed `DeviceCommand` objects. The console parser is
only a text-to-command adapter; operation enums, argument models, validation,
request IDs, lifecycle events, and audit records are shared.

Long-running camera, pump, and TEC commands remain the one active FIFO command,
but advance through short `QTimer`-driven steps on their existing device worker
thread. This leaves the worker event loop responsive. Abort, safe-stop, camera
capture-stop, pump stop, and TEC outputs-off commands use a separate urgent
control path and therefore never wait behind the active FIFO command. Hardware
calls still run only on the target device worker thread; an urgent request first
terminates the deferred operation, performs its stop action, and only then lets
the controller dispatch the next normal command.

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
├── hal/          Qt device workers, registry, and simulations
├── drivers/      reusable real and simulated implementations, grouped by device
├── ui/           Qt Widgets only
└── main.py       the single process entry point
```

The design is analogous to a LabVIEW queued message handler: one producer-safe
application queue, one dispatcher, and a dedicated actor/loop for each device.
There is no TCP/HTTP/socket protocol, named pipe, thread pool, or controller
process.

## Launch simulation

```powershell
pip install -e ".[ui,test]"
python -m thermo_acoustic.main
```

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
camera snapshot
camera configure-sequence 100 2.5
camera sequence
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

The console prints accepted, queued, running, completed, and failed events with
request IDs. EOF is treated as a quiet end of console input; it does not close
the UI. `quit` requests coordinated safe-stop, disconnection, and worker-thread
shutdown.

The desktop UI provides one independent control tab for each device. Every tab
shows connection, activity, fault, and typed readback state; normal actions use
the same global FIFO as the console, while abort and stop controls retain their
urgent path. Duplicate clicks for an already-pending action are rejected with a
visible notice. The controls use grouped multi-column layouts sized for a
maximized 1920 × 1080 display, with scrolling retained only as a fallback for
smaller windows. AD2 has separate Oscilloscope, Waveform generator, and Digital
output sub-tabs. Scope, waveform, and digital-output triggers are typed through
the HAL to the driver; camera sequence trigger and master-pulse settings follow
the same route. Camera results include an image preview, and AD2 scope reads are
drawn in an inline dependency-free plot.

Use **File > Save settings** and **File > Load settings** to manage explicit
JSON input profiles. Profiles contain editable control values only. Loading a
profile never connects hardware, submits commands, restores stale readback, or
replays a previous log.

The application command surface exposes stable direct operations only. Driver
coercion helpers, SDK handles, discovery functions, raw protocol methods, and
camera persistence helpers are not HAL commands. Discovery and hardware probes
remain manual-only under `hardware_tests/`. Device status uses typed per-device
readback models rather than free-form key/value dictionaries.

## Real mode safeguards

Use `--mode real` only on an authorized workstation. Creating the registry and
workers does not construct, connect to, or probe devices. Every real connection
is rejected unless the application controller receives explicit operator
confirmation; only then does the target worker construct its driver and connect
on its persistent thread. The UI is only a presentation of that policy; safety
and validation remain in application and worker code. Existing driver timeouts
remain in the retained drivers.

```powershell
python -m thermo_acoustic.main --mode real --audit-log logs\run.jsonl
```

Offline tests use simulation or injected fake drivers and do not prove physical
behavior. Never run `hardware_tests/` without explicit hardware authorization.

## Verification

```powershell
.venv\Scripts\python.exe -m compileall -q src
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python.exe -m pytest -q
python tools\check_repository_hygiene.py
```

Audit output is structured JSON Lines and is disabled unless `--audit-log` is
provided. Tests write logs only under temporary directories.

## Retained drivers

The canonical real pump implementation is `drivers/pump/CetoniPump`, which
directly owns the Qmix SDK integration without another pump wrapper.
Each device folder also contains a reusable simulated implementation exposing
the device-level methods used by its HAL worker. These simulators contain no Qt
or application code. Vendor APIs, data types, and errors remain behind the HAL
boundary. There is no aggregate `instruments.py` module or redundant standalone
neMESYS path.
