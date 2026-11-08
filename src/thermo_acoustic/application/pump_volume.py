"""One rule for "is there enough volume", used by the series start check, the batch syringe preflight and the
pump cards' queued-flush text and colour.

A level is read (or tracked) as a double and a need is a sum of doubles, so a syringe that exactly fits
(1 - 0.3 - 0.3 = 0.39999999999999997 against a need of 0.4) would be refused by a plain `<`. The rule absorbs only
that representation noise: a relative 1e-12 (about 4,500 units in the last place, enough for long sums), which is
a fraction of a picolitre on a millilitre syringe and far below any pump's volume resolution. It is not a device
tolerance: a shortfall of even a nanolitre is a shortfall. Unreadable levels (None, NaN, infinity) never count as
enough. Pump hardware resolution is deliberately not used here.
"""

from __future__ import annotations

import math

RELATIVE_NOISE = 1e-12


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def volume_available(level_ml: object, needed_ml: object) -> bool:
    """True when `level_ml` covers `needed_ml` apart from representation noise; False for any unreadable number."""
    if not (_finite(level_ml) and _finite(needed_ml)):
        return False
    return level_ml - needed_ml >= -RELATIVE_NOISE * max(abs(level_ml), abs(needed_ml))


def remaining_volume_ml(level_ml: object, needed_ml: object) -> float | None:
    """Level minus need for display, with noise reading as exactly 0; None when either number is unreadable.
    Negative only for a real shortfall, which is the same condition `volume_available` reports as False."""
    if not (_finite(level_ml) and _finite(needed_ml)):
        return None
    return level_ml - needed_ml if not volume_available(level_ml, needed_ml) or level_ml - needed_ml > 0 else 0.0
