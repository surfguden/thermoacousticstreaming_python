# Thermo-acoustic control

This repository contains a single-process, simulation-first Qt application for
the thermo-acoustic test rig. It is deliberately limited to individual device
commands; experiments, recipes, and multi-device sequencing are deferred.

## Architecture

`main.py` creates one `QApplication`, one `ApplicationController`, one Qt
window, one console reader, and one device registry. The controller owns a
global FIFO queue and dispatches exactly one command at a time. UI buttons and
stdin both create the same `DeviceCommand` objects, so they have identical
validation, request IDs, lifecycle events, and audit records.

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
camera snapshot
tec set-temperature 25
z-stage enable-closed-loop
z-stage move 50
status
quit
```

The console prints accepted, queued, running, completed, and failed events with
request IDs. EOF is treated as a quiet end of console input; it does not close
the UI. `quit` requests coordinated safe-stop, disconnection, and worker-thread
shutdown.

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

The canonical pump path is `drivers/pump/CetoniPump` with `QmixPumpDriver`.
Each device folder also contains a reusable simulated implementation exposing
the device-level methods used by its HAL worker. These simulators contain no Qt
or application code. Vendor APIs, data types, and errors remain behind the HAL
boundary. There is no aggregate `instruments.py` module or redundant standalone
neMESYS path.
