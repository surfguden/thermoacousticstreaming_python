# Hardware Safety Enforcement Patterns

Reference document for adding hardware-safety-critical parameter enforcement
to a new device or a new parameter on an existing device. This project has
built four instances of the same underlying problem -- "an out-of-range
value could risk damaging physical hardware" -- and arrived at four related
but distinct patterns depending on what information is actually available
about the real device. Read this before repeating the vendor-doc research,
reject-vs-clamp decision, or live-read-vs-hardcoded decision from scratch.

Compiled 2026-07-28, from the current implementation of each pattern (not
from prior changelog summaries) -- see each pattern's "worked example" for
exact current file:line references.

## The one decision tree that governs all four patterns

1. **Does the device report its own real limit, and can you read it every
   time you connect (or before every write)?**
   - Yes -> **live-read** the limit from the device itself. Never hardcode a
     plausible-looking number if the device can just tell you.
   - No, but a vendor manual/datasheet states a fixed limit for this specific
     hardware model -> **hardcode it, cite the exact manual/section/revision
     in a code comment at the point of use**, not just in a commit message.
   - No live read, no vendor citation available -> you don't have enough
     information to enforce a real limit yet. Don't invent one (see Pattern
     (d)'s own cautionary history below -- an earlier version of this
     project's own pump-stroke bound was accidentally derived from an
     unrelated formula instead of the real vendor spec, and it took an
     external review to catch it).
2. **Once you know the limit, does the SDK/device itself reject an
   out-of-range value (raises, returns an error code), or does it silently
   accept and clamp/substitute internally?**
   - Check this empirically against the real SDK if at all possible --
     don't assume either behavior. This project found two genuine surprises
     doing exactly this: Digilent's WaveForms SDK documents that `*Set`
     functions never fail on an out-of-range value (silently clamps
     instead), and Hamamatsu's DCAM SDK's `INVALIDSUBARRAY` error only fires
     at a *later* step (`SUBARRAYMODE ON`) than the individual property
     writes that actually carry the bad values -- not where either of those
     behaviors would naively have been guessed.
   - If the SDK silently clamps/substitutes: you need your own explicit
     **out-of-range flag** surfaced somewhere a human will see it, not just
     a clamp with no record (Pattern (b)).
   - If the SDK already fails loudly and safely: a pre-flight check in front
     of it is a UX/timing improvement (catch it earlier, clearer message,
     avoid writing partial invalid state to the device), not a new safety
     guarantee (Pattern (c)).
   - If there is no live-read limit and this is the *only* line of defense
     against physical damage: **reject**, don't clamp -- clamping silently
     substitutes a value the operator didn't ask for, with no way to know
     it happened, for a parameter you can't independently verify a "safe"
     clamped value for anyway (Pattern (d)).

---

## Pattern (a) -- Live-read range at connect() + soft-clamp-and-return at the call site

**When to use:** the device itself can report its own real operating range
over the same connection you use to control it, and that range doesn't
change between connects (or you re-read it on every reconnect). This is the
strongest position to be in -- prefer it whenever the hardware supports it.

**Reject vs. clamp:** clamp is appropriate here specifically because the
clamped value is *returned to the caller*, so nothing is silently lost --
the caller can inspect what was actually sent and compare it to what was
requested. This only works because the call site controls both the request
and the immediate consumption of the result in the same synchronous call.

**Skeleton:**
```python
@dataclass(slots=True)
class DeviceStage:
    max_travel_um: float | None = None  # never hardcoded -- read at connect()

    def connect(self) -> None:
        ...
        self.max_travel_um = _to_float(channel.GetMaxTravel())  # live SDK read

    def set_position(self, target_um: float) -> float:
        if self.max_travel_um is None:
            raise DeviceError("MaxTravel was never read -- cannot soft-limit a move.")
        clamped_um = max(0.0, min(float(target_um), self.max_travel_um))
        channel.SetPosition(clamped_um)
        return clamped_um  # caller can detect a request that got clamped
```

**Worked example:** `src/thermo_acoustic/thorlabs_piezo.py`'s `PiezoStage` --
`max_travel_um`/`max_output_voltage_v`/`min_output_voltage_v` are all read
live in `connect()` (`thorlabs_piezo.py:113-165`); `set_position()`
(`thorlabs_piezo.py:239-250`) clamps to `[0, max_travel_um]` and returns the
clamped value. Note this pattern is *also* mirrored one layer up, in the
UI: the Z-scan tab's `Z Start`/`Z End` `QDoubleSpinBox` fields apply the
exact same live-read range as their real-time input range (not just
relying on `set_position()`'s clamp as the only defense) -- see
`qt_ui.py`'s `_apply_zscan_range()`. When a live-read limit exists, applying
it at *both* the UI input layer and the hardware call site is the preferred
belt-and-suspenders approach, not redundant.

---

## Pattern (b) -- Live-read range + software clamp + explicit out-of-range flag surfaced in UI/metadata

**When to use:** the device reports its own real range (same as Pattern
(a)), *but* the underlying SDK does not fail on an out-of-range `Set` call --
it silently clamps or substitutes a value with no error and no indication
anything unusual happened. A bare clamp-and-return isn't enough here,
because the caller in this codebase's own architecture (a background worker
thread applying a whole multi-field config) doesn't necessarily inspect
every individual return value the way Pattern (a)'s single synchronous
call site does. You need a **persistent flag on the config object itself**
that a human-facing layer (UI status text, logged experiment metadata) can
check after the fact.

**Reject vs. clamp:** clamp, because the SDK will clamp/substitute
regardless of what you do -- your only real choice is whether the resulting
substitution is silent or surfaced. Reject is not available here as an
option before the SDK is even involved, unlike Pattern (d), because there is
no way to validate against the live range without first querying the
device's own `*Info()`-style call, which itself requires being connected --
by the time you have the range, you're already at the point of applying it,
so clamping through and flagging is the more useful choice than refusing
outright.

**Skeleton:**
```python
@dataclass(slots=True)
class ChannelConfig:
    out_of_range: bool = False  # never assigned True until something sets it
    amplitude_v: float = 1.0

def configure(handle, channel: ChannelConfig) -> None:
    real_min, real_max = sdk.query_real_range(handle)  # live device read
    clamped = min(max(channel.amplitude_v, real_min), real_max)
    channel.out_of_range = clamped != channel.amplitude_v  # the actual flag
    sdk.set_value(handle, clamped)  # SDK itself never errors either way

# surfaced downstream, not just computed and dropped:
if channel.out_of_range:
    ui_status = "Configured -- WARNING: clamped to device limits"
metadata["OutOfRange"] = channel.out_of_range  # logged with the experiment
```

**Worked example:** `src/thermo_acoustic/waveforms.py`'s
`_configure_analog_node()` (`waveforms.py:484`) reads the device's real
`FDwfAnalogOutNodeFrequencyInfo`/`AmplitudeInfo` range before every `Set`
call, clamps in software, and returns whether it had to; `configure_wfg()`
(`waveforms.py:445`) sets `WfgChannelConfig.out_of_range` per channel. This
flag existed as a *dataclass field* and a *dead check method*
(`WfgConfig.check_valid()`) for a long time before anything actually set
it -- confirm the whole chain (something sets the flag -> something reads
it -> something surfaces it to a human) is wired end to end, not just that
the field exists. Surfaced in `qt_ui.py`'s `_apply_wfg()` (UI status line)
and `workflows.py`'s `_wfg_properties()` (`WFGOutOfRangeCh1`/`Ch2` in the
logged TDMS metadata) -- both consuming the same flag, not two separate
mechanisms.

---

## Pattern (c) -- Live-read limits + pre-flight reject before the SDK round-trip

**When to use:** the device/SDK *already* fails safely on an out-of-range
value (raises a real error), but only after one or more property writes have
already reached the device, or only at a late step in a multi-call
sequence -- meaning by the time the SDK complains, the device may already be
sitting in a transient invalid intermediate state. This pattern doesn't add
a new safety guarantee (the SDK's own rejection is already real); it moves
the rejection earlier and gives a clearer, domain-specific message, while
avoiding ever writing the invalid intermediate values to the device at all.

**Reject vs. clamp:** reject, always -- clamping a camera ROI or similar
configuration parameter to "the nearest valid value" is rarely meaningful
(there's no single obviously-correct substitute region), and since the SDK
was always going to reject this anyway, a pre-flight reject changes nothing
about what the operator has to do differently, only when and how clearly
they find out.

**Skeleton:**
```python
def configure_roi(self, roi: SubRegion) -> None:
    limits, current = self.read_real_sensor_limits_and_current_value()
    self._validate_against_limits(roi, limits, current)  # raises before any SDK write
    sdk.set_property(HSIZE, roi.horizontal_size)
    sdk.set_property(HPOS, roi.horizontal_offset)
    sdk.set_property(MODE, ON)  # this is where the SDK's OWN rejection used to fire

def _validate_against_limits(self, roi, limits, current) -> None:
    if not (limits.horizontal_size.minimum <= roi.horizontal_size <= limits.horizontal_size.maximum):
        raise DeviceError(f"horizontal_size={roi.horizontal_size} outside real sensor range")
    # combined check mirrors the SDK's OWN failure condition -- don't invent a different one
    effective_size = roi.horizontal_size or current.horizontal_size
    if roi.horizontal_offset + effective_size > limits.horizontal_size.maximum:
        raise DeviceError("offset + size exceeds the sensor's real pixel count")
```

**Worked example:** `src/thermo_acoustic/hamamatsu_dcam.py`'s
`configure_roi()` (`hamamatsu_dcam.py:117`) now calls
`read_subregion_limits_and_value()` and a new `_validate_roi_against_limits()`
(`hamamatsu_dcam.py:151`) before any `SUBARRAYHSIZE`/`HPOS`/`MODE` write.
Confirmed against real hardware that DCAM's own `INVALIDSUBARRAY` error
(`0x8000082b`) only actually fires at the final `SUBARRAYMODE ON` call --
the individual `SUBARRAYHSIZE`/`HPOS` writes succeed even with an invalid
combination -- so without this pre-flight check, an invalid ROI would
transiently reach the device before the SDK's own rejection kicked in.
Confirm this kind of "where does the SDK's rejection actually happen"
detail empirically against the real SDK before assuming a pre-flight check
changes only cosmetics -- it can genuinely prevent bad intermediate state
from ever reaching the device, which is a real (if secondary) improvement.

---

## Pattern (d) -- Fixed vendor-manual ceiling (not live-readable) + hard reject

**When to use:** no live read exists for this parameter at all -- the device
has no SDK call that reports its own real limit for this specific value --
but a real, physical, model-specific ceiling exists and is documented by
the manufacturer. This is the weakest information position of the four
patterns (a hardcoded number can silently go stale if the physical hardware
is ever swapped for a different model), so treat the citation itself as
load-bearing, not optional.

**Reject vs. clamp:** reject, always. There is no live-read value to derive
a "safe clamped substitute" from, and unlike Pattern (a)/(b) where the
clamp target comes from the device's own live report, any clamp target here
would itself be an assumption layered on top of an already-uncertain fixed
number -- two guesses compounding instead of one. Reject and require the
operator to supply a genuinely in-range value.

**A real cautionary tale from this exact codebase, worth repeating:** the
first version of this project's syringe-stroke bound conflated two
different kinds of limit -- it derived the upper bound by applying this
project's own volume/diameter-to-stroke *formula* (meant for estimating a
specific syringe's geometry) across a *range* of BD syringe sizes, arriving
at a padded estimate (200mm) that had nothing to do with the actual pump
hardware's real mechanical travel limit (65mm, per the vendor manual). The
mistake left a real gap open -- any value between 65mm and 200mm would have
been silently accepted and forwarded to the pump SDK, risking exactly the
kind of over-travel damage the manual's own warning describes -- and was
only caught by an external review cross-checking the number against the
actual manual. **The lesson: a fixed ceiling for pattern (d) must trace to
the specific physical limit of the specific hardware component being
protected, cited by document/section/revision, not derived by applying a
formula or an estimate meant for a *different* purpose.**

**Skeleton:**
```python
# CETONI Low Pressure Hardware Manual, Section 5.1, NEM-B101-02 E:
# this pump module's own absolute mechanical piston travel is "up to 65 mm",
# independent of whatever syringe is mounted. Not derived from syringe
# geometry math -- a real, cited, model-specific hardware ceiling.
MAX_STROKE_MM = 65.0

def configure_syringe(self, inner_diameter_mm: float, stroke_mm: float) -> None:
    if not (MIN_STROKE_MM <= stroke_mm <= MAX_STROKE_MM):
        raise DeviceError(
            f"stroke_mm={stroke_mm} outside [{MIN_STROKE_MM}, {MAX_STROKE_MM}] -- "
            "this pump module's own real mechanical ceiling, per <vendor manual citation>"
        )
    sdk.set_syringe_param(inner_diameter_mm, stroke_mm)  # rejected value never reaches here
```

**Worked example:** `src/thermo_acoustic/qmix_backend.py`'s
`MAX_SYRINGE_STROKE_MM = 65.0` (`qmix_backend.py:86`), enforced in
`configure_syringe()` (`qmix_backend.py:373-418`) before `set_syringe_param()`
is ever called -- confirmed with hardware-level proof (not just "an
exception was raised"): reading `pump.get_syringe_param()` back from the
real device before and after a rejected attempt showed the device's own
stored geometry was completely unchanged. `MIN_SYRINGE_INNER_DIAMETER_MM`/
`MAX_SYRINGE_INNER_DIAMETER_MM` (`qmix_backend.py:83-84`) are a related but
distinct case -- a *plausible-range* backstop against data-entry errors
(unit mixups, transposed digits) derived from BD's published syringe
product-line range, not a single hardware component's own physical
ceiling -- don't conflate the two kinds of bound even when they live next
to each other in the same file (this is exactly the distinction the stroke
mistake above blurred).

**Also note:** `generate_flow()`'s rejection of a flow rate exceeding
`max_flow_rate_ul_min` (`qmix_backend.py:329-352`) looks similar to this
pattern but is actually closer to Pattern (a)/(b)'s territory -- that
ceiling *is* read back live from the device (`get_flow_rate_max()`, right
after `set_syringe_param()` succeeds), it's simply enforced at a different
call site (`generate_flow()`) than where it's read (`configure_syringe()`).
Don't assume "pump module" implies "hardcoded" -- check which specific
parameter has a live read and which doesn't before choosing a pattern.

---

## Pattern (e) -- Commit configuration state only after the real hardware call confirms

**Not one of the four out-of-range enforcement patterns above** (those
answer "is this value safe to send"; this answers "when is it safe to
*record* that a value was sent") -- grouped here as a named pattern
because it's the single most repeated mistake found across this
project's line-by-line review series: the identical shape, independently
found and fixed **six times** across five files in one day
(`CetoniPump.set_fill_level()`, `Valve.set_position()`,
`CetoniPump.refill()`/`empty()`, `hamamatsu_dcam.py`'s
`configure_sequence()`, and `AD2Sdk`'s six WFG/DO config methods).

**When it applies:** a method that both (1) issues one or more real
hardware writes and (2) also updates an in-memory field meant to
represent "the configuration currently confirmed on the device" (read
later for UI display, a subsequent safety check, or permanent experiment
metadata). If the in-memory field is assigned *before* the hardware
call(s) actually succeed, a failure partway through (a raised exception
on write #2 of 3, say) leaves that field claiming a configuration the
real device never fully received -- indistinguishable, to any later
reader, from a genuinely confirmed one.

**The fix is always the same shape, regardless of whether the underlying
hardware call is synchronous (one SDK call that either raises or doesn't
-- `hamamatsu_dcam.py`/`AD2Sdk`'s case) or asynchronous (issue a move,
then separately poll for real completion -- Pattern (e) as applied to
pump moves specifically also needs Pattern (e)-plus-a-wait; see
`Application._move_pump_and_confirm()`):

1. Coerce/build the new configuration into a **local** variable -- never
   write it to `self.X` yet.
2. Issue the real hardware call(s) using the local variable.
3. Only after every call returns without raising, assign the local
   variable to `self.X`.

**Skeleton (synchronous case):**
```python
def configure(self, settings: dict | None) -> None:
    new_config = coerce_config(settings)   # local, not self.config yet
    self._apply_to_hardware(new_config)    # raises on any failure
    self.config = new_config                # only reached on full success
```

**Worked examples:** `HamamatsuDcamBackend.configure_sequence()`
(`hamamatsu_dcam.py:205`) and `AD2Sdk`'s `config_wfg()`/`wfg_configure()`/
`wfg_start_stop_all_ch()`/`config_do_custom()`/`config_do_clock_special()`/
`do_configure()` (`instruments.py:266`/`311`/`326`/`344`/`358`/`400`).
Each differs in what's being coerced and which backend call confirms
success, which is exactly why these were **not** consolidated into one
shared code abstraction the way Pattern (e)'s pump-move cousins were
(`Application._move_pump_and_confirm()`, see the cross-module
architecture review, 2026-08-02) -- the shared part here is this
principle, not a reusable procedure. Do not force a new instance of this
pattern into a shared helper just because this note names it; check
whether the specific hardware call shape actually matches an existing
implementation closely enough first.

---

## Standard hardware-cleanup shape (for new hardware modules going forward)

**Not one of the four out-of-range enforcement patterns above** -- a
separate, additional convention for a different problem: how a new
hardware module's `close()`/`cleanup()`/`disconnect()` should handle
failures during its own multi-step teardown.

**Context:** a code-health audit (Session 57) originally found this
codebase had four different, independently-evolved shapes for this --
`HamamatsuDcamBackend.close()` logs individual failures and swallows
them (best-effort, never raises); `QmixPumpBackend.close()`,
`PiezoStage.disconnect()`, and `Application._cleanup_instruments()`
each collected error strings from each step, thread-timeout-wrapped
each one, and raised a single combined error at the end -- each its
own hand-copied implementation of the same shape. **Updated
(cross-module architecture review, 2026-08-02): those three are no
longer independent implementations.** They now share one utility,
`hw_logging.run_with_timeout(action, name, timeout_s) -> str | None`
-- direct evidence the "just document a copyable template" approach
below wasn't enough on its own: a fourth hardware module
(`TecController.cleanup()`, `tec.py`) was added after the original audit and did
**not** initially pick up the pattern. That propagation gap is now closed:
failed-initialize rollback and direct TEC cleanup both call the shared
`run_with_timeout()` helper with a local bound. `HamamatsuDcamBackend.close()` remains
deliberately different by design (best-effort swallow, not raise --
see Finding F's own reasoning), not an inconsistency to unify.

**For any NEW hardware module added to this project, call
`hw_logging.run_with_timeout()`
directly -- do not hand-copy the thread/queue implementation.** It
already logs nothing on its own (fire-and-forget style, matching
`log_transaction()`'s own contract), so pair it with your own
`logger.error()` call per failure if you want a trace left even if the
caller loses the final combined exception, matching the shape below.

- Collect error strings from each teardown step rather than raising
  immediately on the first failure -- so one device/resource's failure
  doesn't prevent attempting cleanup on the others.
- Call `run_with_timeout()` for each step so a hung SDK call during
  cleanup can't block the whole teardown indefinitely.
- Log each failure as it's found.
- Raise a single combined error at the end summarizing everything that
  failed, rather than either swallowing everything silently or
  stopping at the first failure.

**Skeleton:**
```python
import logging

from .hw_logging import run_with_timeout

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class NewDeviceBackend:
    close_timeout_s: float = 5.0
    device: Any = None

    def close(self) -> None:
        errors: list[str] = []
        errors.extend(self._run_close_step("stop", self._stop))
        errors.extend(self._run_close_step("release", self._release))
        self.device = None
        if errors:
            raise NewDeviceError("; ".join(errors))

    def _run_close_step(self, name: str, action) -> list[str]:
        error = run_with_timeout(action, f"NewDevice {name}", self.close_timeout_s)
        if error is None:
            return []
        logger.error(error)
        return [error]
```

**Worked examples:** `src/thermo_acoustic/hw_logging.py`'s
`run_with_timeout()` for the shared timeout-guard itself; any of
`QmixPumpBackend.close()`/`_run_close_step()` (`qmix_backend.py:458`/
`481`), `PiezoStage.disconnect()`/`_run_disconnect_step()`
(`thorlabs_piezo.py:167`/`189`), or
`Application._cleanup_instruments()`/`_run_cleanup_call_with_timeout()`
(`application.py:328`/`347`) for the collect-errors + timeout-wrap +
combined-raise shape built on top of it -- these three now differ only
in their own error-message prefix and where the collected errors get
logged/raised, not in the underlying timeout mechanism.
