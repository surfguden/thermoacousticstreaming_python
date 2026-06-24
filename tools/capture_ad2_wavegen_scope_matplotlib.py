from __future__ import annotations

import csv
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import matplotlib.pyplot as plt

from thermo_acoustic.ad2 import CarrierSettings, TriggerSettings, WaveformFunction, WfgChannelConfig, WfgConfig
from thermo_acoustic.instruments import AD2Sdk


CSV_PATH = ROOT / "ad2_scope_capture.csv"
PNG_PATH = ROOT / "ad2_scope_capture.png"


def main() -> None:
    sample_frequency_hz = 10_000.0
    sample_count = 4096
    wave_frequency_hz = 100.0
    amplitude_v = 0.2

    ad2 = AD2Sdk()
    try:
        ad2.initialize()
        print(f"handle {ad2.get_phdwf()}", flush=True)

        wavegen_1 = WfgChannelConfig(
            channel_index=0,
            carrier=CarrierSettings(
                frequency_hz=wave_frequency_hz,
                amplitude_v=amplitude_v,
                offset_v=0.0,
                function=WaveformFunction.SINE,
                enable=True,
            ),
            trigger=TriggerSettings(sec_run=0.0, sec_wait=0.0, repeat_count=0),
        )
        wavegen_2 = WfgChannelConfig(channel_index=1, carrier=CarrierSettings(enable=False))

        ad2.config_wfg(WfgConfig(running=True, channels=[wavegen_1, wavegen_2]))
        print("wavegen 1 running", flush=True)
        time.sleep(0.25)

        samples = ad2.capture_scope(
            channel_index=0,
            sample_frequency_hz=sample_frequency_hz,
            sample_count=sample_count,
            range_v=1.0,
        )
        ad2.wfg_start_stop_all_ch(False)
    finally:
        try:
            ad2.wfg_start_stop_all_ch(False)
        except Exception:
            pass
        ad2.cleanup()

    times = [i / sample_frequency_hz for i in range(len(samples))]
    vmin = min(samples)
    vmax = max(samples)
    mean = sum(samples) / len(samples)
    rms = math.sqrt(sum((x - mean) ** 2 for x in samples) / len(samples))

    with CSV_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["time_s", "voltage_v"])
        writer.writerows(zip(times, samples))

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(times, samples, color="#2563eb", linewidth=1.4)
    ax.axhline(0.0, color="#9ca3af", linewidth=0.9, linestyle="--")
    ax.set_title("AD2 Wavegen 1 Captured on Scope 1")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Voltage (V)")
    ax.grid(True, alpha=0.25)
    ax.text(
        0.995,
        0.98,
        f"min {vmin:.4f} V\nmax {vmax:.4f} V\nVpp {vmax - vmin:.4f} V\nRMS(ac) {rms:.4f} V",
        transform=ax.transAxes,
        ha="right",
        va="top",
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#d1d5db"},
    )
    fig.tight_layout()
    fig.savefig(PNG_PATH, dpi=160)

    print(f"captured {len(samples)} samples", flush=True)
    print(f"csv {CSV_PATH}", flush=True)
    print(f"png {PNG_PATH}", flush=True)
    print(f"min={vmin:.6f} max={vmax:.6f} vpp={vmax - vmin:.6f} mean={mean:.6f} rms_ac={rms:.6f}", flush=True)
    plt.show(block=False)
    while plt.fignum_exists(fig.number):
        plt.pause(0.25)


if __name__ == "__main__":
    main()
