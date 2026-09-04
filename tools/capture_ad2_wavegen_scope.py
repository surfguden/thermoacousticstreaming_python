"""Manual real-AD2/W1 output/capture engineering diagnostic.

This diagnostic does not commission the acoustic chain. No bundled amplitude
is a trusted safe default for the unresolved physical W1 path.
"""

from __future__ import annotations

__test__ = False

import argparse
import csv
import math
import time
from pathlib import Path

from thermo_acoustic.ad2 import CarrierSettings, TriggerSettings, WaveformFunction, WfgChannelConfig, WfgConfig
from thermo_acoustic.ad2_capture_tooling import (
    REAL_AD2_W1_CONFIRMATION,
    require_real_ad2_w1_confirmation,
    run_capture_with_cleanup,
)
from thermo_acoustic.instruments import AD2Sdk


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "ad2_scope_capture.csv"
SVG_PATH = ROOT / "ad2_scope_capture.svg"


def write_svg(samples: list[float], sample_frequency_hz: float, wave_frequency_hz: float, amplitude_v: float) -> None:
    vmin = min(samples)
    vmax = max(samples)
    vpp = vmax - vmin
    mean = sum(samples) / len(samples)
    rms = math.sqrt(sum((x - mean) ** 2 for x in samples) / len(samples))

    width = 1000
    height = 420
    pad_l = 70
    pad_r = 24
    pad_t = 36
    pad_b = 56
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    span = vmax - vmin or 1.0

    points = []
    for i, value in enumerate(samples):
        x = pad_l + plot_w * i / (len(samples) - 1)
        y = pad_t + plot_h * (vmax - value) / span
        points.append(f"{x:.2f},{y:.2f}")

    zero_y = pad_t + plot_h * (vmax - 0.0) / span
    zero_y = max(pad_t, min(pad_t + plot_h, zero_y))
    duration_s = (len(samples) - 1) / sample_frequency_hz

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="{pad_l}" y="24" font-family="Segoe UI, Arial" font-size="18" fill="#111827">AD2 Wavegen 1 captured on Scope 1</text>
  <text x="{pad_l}" y="{height - 18}" font-family="Segoe UI, Arial" font-size="12" fill="#374151">{wave_frequency_hz:.0f} Hz sine, requested amplitude {amplitude_v:.3f} V, sample rate {sample_frequency_hz:.0f} S/s, samples {len(samples)}</text>
  <text x="{width - pad_r}" y="24" text-anchor="end" font-family="Segoe UI, Arial" font-size="12" fill="#374151">min {vmin:.4f} V | max {vmax:.4f} V | Vpp {vpp:.4f} V | RMS(ac) {rms:.4f} V</text>
  <line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" stroke="#9ca3af"/>
  <line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" stroke="#9ca3af"/>
  <line x1="{pad_l}" y1="{zero_y:.2f}" x2="{pad_l + plot_w}" y2="{zero_y:.2f}" stroke="#d1d5db" stroke-dasharray="4 4"/>
  <text x="{pad_l - 10}" y="{pad_t + 4}" text-anchor="end" font-family="Segoe UI, Arial" font-size="12" fill="#4b5563">{vmax:.3f} V</text>
  <text x="{pad_l - 10}" y="{pad_t + plot_h}" text-anchor="end" font-family="Segoe UI, Arial" font-size="12" fill="#4b5563">{vmin:.3f} V</text>
  <text x="{pad_l + plot_w}" y="{pad_t + plot_h + 20}" text-anchor="end" font-family="Segoe UI, Arial" font-size="12" fill="#4b5563">{duration_s:.4f} s</text>
  <polyline fill="none" stroke="#2563eb" stroke-width="1.6" points="{" ".join(points)}"/>
</svg>
"""
    SVG_PATH.write_text(svg, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Engineering diagnostic that drives REAL AD2 / REAL W1 OUTPUT and captures Scope 1. "
            "It does not commission the acoustic chain; no bundled amplitude is a trusted safe default."
        )
    )
    parser.add_argument("--confirm", help=f"Required exact acknowledgement: {REAL_AD2_W1_CONFIRMATION}")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_real_ad2_w1_confirmation(args.confirm)

    sample_frequency_hz = 10_000.0
    sample_count = 4096
    wave_frequency_hz = 100.0
    amplitude_v = 0.2

    ad2 = AD2Sdk()

    def capture() -> list[float]:
        ad2.initialize()
        print(f"handle {ad2.get_phdwf()}")

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
        print("wavegen 1 running")
        time.sleep(0.25)

        samples = ad2.capture_scope(
            channel_index=0,
            sample_frequency_hz=sample_frequency_hz,
            sample_count=sample_count,
            range_v=1.0,
        )
        ad2.wfg_start_stop_all_ch(False)

        return samples

    def finalize_evidence(samples: list[float]) -> None:
        with CSV_PATH.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["time_s", "voltage_v"])
            for i, value in enumerate(samples):
                writer.writerow([i / sample_frequency_hz, value])
        write_svg(samples, sample_frequency_hz, wave_frequency_hz, amplitude_v)

    samples = run_capture_with_cleanup(ad2, capture, finalize_evidence)

    vmin = min(samples)
    vmax = max(samples)
    mean = sum(samples) / len(samples)
    rms = math.sqrt(sum((x - mean) ** 2 for x in samples) / len(samples))
    print(f"captured {len(samples)} samples")
    print(f"csv {CSV_PATH}")
    print(f"svg {SVG_PATH}")
    print(f"min={vmin:.6f} max={vmax:.6f} vpp={vmax - vmin:.6f} mean={mean:.6f} rms_ac={rms:.6f}")


if __name__ == "__main__":
    main()
