# Manual hardware diagnostics

These scripts are retained for explicitly authorized bench work. They are
not automated tests, despite some historical `test_*.py` names. CI does not
import or execute them. Do not run a script merely to check that it works.

The old full-workflow smoke runner was retired with the application.
The remaining scripts use individual drivers or vendor wrappers.

## Safety boundary

- Obtain explicit authorization before any hardware access, including discovery.
- Inspect the selected script, its confirmation gate, device identity,
  connection settings, and intended actions before use.
- A confirmation token does not establish safe wiring, flow, position,
  temperature, syringe configuration, or physical readiness.
- Do not reuse persisted UI settings as authoritative connection information.
- Keep measured frames, traces, and logs separate from disposable Python caches.

Retained bench notes reported unresolved W1 acoustic-chain readiness and a
relatching Qmix pump fault. Moving to this baseline does not clear either
condition or authorize output/motion. Historical gate numbers and procedures
belong to the reference application; current readiness requires independent
bench confirmation.

## Action-capable diagnostics

| Script | Function / gate |
| --- | --- |
| `manual_hamamatsu_camera_probe.py` | Capture a camera frame; `CONFIRM_REAL_CAMERA_CAPTURE` |
| `manual_cetoni_pump_probe.py` | Initialize the pump and optionally command flow; `CONFIRM_REAL_CETONI_QMIX` |
| `manual_nemesys_reference.py` | Pump reference move; `CONFIRM_REAL_CETONI_QMIX` |
| `manual_cetoni_pump_refill.py` | Reference and refill at reported maximum flow; `CONFIRM_REAL_CETONI_QMIX` |
| `manual_capture_ad2_wavegen_scope.py` | Real W1 output and scope capture; exact token documented by `--confirm` |
| `manual_capture_ad2_wavegen_scope_matplotlib.py` | Capture with Matplotlib display; same AD2 gate |
| `manual_release_ad2.py` | Enumerate and release WaveForms device handles; `CONFIRM_REAL_AD2_RELEASE` |
| `test_valve_command_probe.py`, `test_valve_command_probe_v2.py` | Manual valve command probes; `--confirm SEND` |

Capture output paths are unchanged. No bundled waveform amplitude is established
as safe for the connected acoustic chain.

## Discovery and readiness diagnostics

The AD2, Hamamatsu, DCAM-property, Qmix, serial, and Thorlabs-APT discovery scripts
retain their existing behavior. Discovery can open devices; camera discovery
also has an opt-in capture mode. Inspect their options before authorized use.

`manual_tec_read_only_probe.py` reads controller status.
`manual_qmix_no_motion_reliability.py` checks bus ownership/status/cleanup with
its `NO_MOTION_CAN` gate.
`manual_qmix_read_only_readiness.py` checks pump readiness with its own explicit
confirmation; it may issue an emergency stop if unexpected active motion is found.

An ignored local `manual_ppc001_piezo_probe.py`, if present, remains manual-only.
Never collect vendor SDK example tests as part of automated repository checks.
