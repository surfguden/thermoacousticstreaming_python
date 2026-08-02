# Porting TBD

> Generated LabVIEW VI coverage registry and historical porting checklist. It is
> not a current hardware-validation or operational-status document; entries below
> may have been implemented, superseded, or deliberately retained as legacy.
> Use current source, `docs/current_workflow_audit.md`, and
> `docs/known_open_items.md` for live status.

This file is generated from `labview_manifest.json` and records the current
semantic porting status for every documented VI in `main_html/main`.
Runtime and hardware validation items are maintained here as post-port tasks.

## Summary

- Documented VI sections: 305
- Implemented in Python: 305
- Partially represented: 0
- Stub only: 0

## Remaining Work By Module

## Runtime / Hardware Validation

The VI registry is semantically complete, but these items still need real-device
validation or operator-facing polish before calling the Python app finished.

- **Hamamatsu real camera validation**: Run `tools/test_hamamatsu_camera.py` against the connected camera and verify open, exposure, ROI/subarray, snapshot, sequence capture, software trigger, and cleanup behavior.
- **Camera image handling**: Verify that the Python TIFF output matches the LabVIEW image output needs, including bit depth, frame naming, metadata, and any TDMS sidecar data expected by downstream analysis.
- **Camera UI preview**: Add a live/snapshot image display in the Camera tab if the operator needs the Python UI to replace LabVIEW's image window behavior.
- **Cetoni/Qmix real pump backend**: The Qmix/Cetoni backend is implemented through `QmixPumpBackend`, but it still needs to be validated with the installed Qmix/Cetoni stack, real syringe geometry, safe flow limits, and the user's device configuration.
- **Valve serial validation**: Confirm real valve commands, baud rate, line endings, and response parsing on the connected MX valve hardware.
- **Analog Discovery MSO hardware validation**: Exercise all MSO trigger source options on the real AD2/AD3 hardware and check that channel enable, sample rate, duration, x-axis scale, and y-axis scale match the physical oscilloscope signal.
- **End-to-end experiment execution**: Run the Experiment tab with the real AD2, Hamamatsu camera, pump, and valve together, then compare folder output, saved settings, image data, trigger timing, flush timing, abort cleanup, and status messages against the LabVIEW behavior.
- **Packaging and operator startup**: Decide whether the final app should be launched from source, a shortcut, or a packaged executable, then document the required SDK/runtime installations.
