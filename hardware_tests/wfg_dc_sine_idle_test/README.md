# WFG1 DC versus 0 Hz sine idle probe

This is a **manual, output-capable hardware probe**, not a pytest test. It is
never imported or run by CI. Run it only with WFG1 connected directly to
Scope 1 by BNC, with the laser and all other loads disconnected. Verify that
the requested voltage is safe for that loopback before proceeding.

From the repository root, using the project environment:

```powershell
.venv\Scripts\python.exe hardware_tests\wfg_dc_sine_idle_test\run_probe.py --voltage-v 0.5 --confirm CONFIRM_REAL_AD2_WFG1_SCOPE1_LOOPBACK
```

The voltage has **no default**; `0.5` above is only an example, not a safe
value for arbitrary attached equipment. The script opens the first AD2. It
tests these WFG1 configurations, each armed for one PC-triggered 3 s run:

1. DC, offset = requested voltage, idle = Disabled. If the device does not
   report Disabled as supported, this case is recorded as skipped.
2. Sine, frequency = 0 Hz, amplitude = requested voltage, offset = 0 V,
   phase = 0°, idle = Offset. A rejected or clamped frequency is recorded,
   not silently interpreted as successful DC generation.

For each configured case, Scope 1 is captured while WFG1 waits for the PC
trigger, soon after triggering, and after the run has finished. Each phase is
a separate short trace, **not** one continuous time-aligned recording. The
script writes `results/<UTC timestamp>/manifest.json`, one case JSON file,
and phase CSV files. SDK idle/frequency capabilities, requested settings,
readbacks, command and capture timestamps, summary statistics, failures,
and cleanup errors are preserved. These generated results are Git-ignored;
copy or share the result folder when ready for analysis.

The script stops/resets/closes the AD2 after each case. A cleanup failure is
reported as a failure; do not assume the physical output is safe after one.
