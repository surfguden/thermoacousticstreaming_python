# Scientific Parameter Semantics Audit — 2026-09-03

**HISTORICAL AUDIT EVIDENCE — NOT CURRENT OPERATIONAL AUTHORITY**

Current operational truth remains exclusively in
[`project_control.md`](project_control.md) and
[`known_open_items.md`](known_open_items.md). This report records how the
2026-09-03 conclusions were reached so an independent reviewer can reproduce,
challenge, or supersede them.

## 1. Scope, checkpoint, and Git range

- Repository: `C:\git\thermoacousticstreaming_python`
- Branch: `junjiebranch`
- Audit start: clean pushed commit
  `bfd1b3168081fdd6bf29494b683973b9dc54aeaa`
- Start parity: local/origin `0/0`; no tracked, staged, or untracked changes.
- Reviewed range: start commit plus the unstaged working-tree audit correction,
  expressed as `bfd1b3168081fdd6bf29494b683973b9dc54aeaa..WORKTREE`.
- The audit did not stage, commit, push, open a hardware session, or issue a
  hardware command.

The start commit already contained the checkpointed WFG requested/effective,
FM total-span, and sweep-shape corrections. Those corrections were re-audited;
they were not accepted merely because their tests passed.

## 2. Final combined methodology

All parameter families were evaluated retroactively under one methodology,
including requirements added while the audit was in progress:

1. identify operator label, internal representation, planner/runtime/backend
   path, conversion, clamp, evidence stage, persistence, and test;
2. establish fundamental quantity/unit semantics from SI/metrology or a
   recognized standard where applicable;
3. establish exact installed-device/API behavior from the manufacturer;
4. selectively compare professional vendors where terms or architectures are
   high-risk or overloaded;
5. compare scientific intent with the actual Lund peer-reviewed method without
   importing unstated conventions;
6. distinguish project/owner physical evidence from independent observation;
7. challenge critical numerical tests with externally anchored hard cases;
8. trace each material lesson from failure through production/test/document
   control and commissioning consequence;
9. make only narrow, evidence-supported offline corrections; and
10. re-run the full drift questions after all steering instructions, not only
    for conclusions reached later.

The semantic classifications used were `VERIFIED`,
`VERIFIED_WITH_SOFTWARE_DERIVATION`, `AMBIGUOUS`,
`PHYSICAL_MEASUREMENT_REQUIRED`, `DEFERRED`, and `OBSOLETE`.

## 3. Source register

### Fundamental, metrology, and industry standards

| Source | Use and limit |
| --- | --- |
| [NIST Guide to the SI, chapter 7](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-7-rules-and-style-conventions-expressing-values) and [chapter 8](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-8) | Quantity/unit expression, seconds, frequency, volume, Celsius intervals. It does not define device APIs. |
| [NIST Technical Note 699](https://www.nist.gov/system/files/documents/calibrations/tn699.pdf) | Independent peak/RMS voltage distinction for sine-wave contexts. It does not set AD2 UI semantics. |
| [EMVA 1288](https://www.emva.org/standards-technology/emva-1288/) | Standardized camera characterization and exposure as a physical integration quantity. It does not define C15440-20UP trigger/API behavior. |

### Exact installed-device manufacturer/API sources

| Subsystem | Primary source and use |
| --- | --- |
| AD2/WaveForms | [Digilent WaveForms SDK guide](https://digilent.com/reference/test-and-measurement/guides/waveforms-sdk-getting-started), [WaveForms reference](https://digilent.com/reference/software/waveforms/waveforms-3/reference-manual), [AD2 specifications](https://files.digilent.com/manuals/WaveForms/3.25.1/start3.html), installed WaveForms SDK 3.22.1 reference PDF, `dwf.h`, and `samples/c/analogout_sweep.cpp`: channel indices, volts versus FM percentage, enum, symmetry, source characteristics, clamp inputs, and sweep formula. |
| BNC Adapter | [Digilent schematic](https://digilent.com/reference/_media/reference/test-and-measurement/bnc-adapter-board/discovery_bnc_sch.pdf): J4/J5/J1/J3 routing and JP4/JP5 direct-versus-49.9-ohm-series topology. |
| Camera | [Hamamatsu C15440-20UP/-20UP01 manual](https://camera.hamamatsu.com/content/dam/hamamatsu-photonics/sites/static/sys/en/manual/C15440-20UP,-20UP01_IM_En.pdf): exact model, sensor, pixel pitch, exposure ranges/quantization, readout times, trigger modes/delay, and Internal/free-running cadence. DCAM set/get semantics are implemented by the installed SDK wrapper. |
| Pump | [CETONI neMESYS Low Pressure manual](https://cetoni.com/downloads/manuals/Manual_Hardware_Nemesys_LowPressure_EN.pdf): module/syringe concepts and device operations; current units are explicitly configured by the repository. |
| Laser | [TOPTICA DLC pro/iBeam family material](https://www.toptica.com/products/locking-driving-electronics/dlc-pro) and retained exact owner-label evidence: family capabilities only, not installed Analog/Digital transfer or optical power. |
| Z | [Thorlabs PFM450E/PPC001 manual](https://media.thorlabs.com/contentassets/e92d618c92c94cea9096b3f231859611/etn018233-d02.pdf): controller/stage behavior and nominal units; no microscope datum. |
| TEC | [Meerstetter TEC controller manuals](https://www.meerstetter.ch/customer-center/downloads/category/15-tec-family-tec-controllers-user-manuals): controller quantities and states; no fluid-temperature transfer. |

### Selective cross-vendor convention sources

| Source | Semantic trap checked |
| --- | --- |
| [Tektronix AFG3000 manual](https://download.tek.com/manual/077095702_July_2019.pdf) | Displayed amplitude depends on configured load; source and loaded voltage must be separated. |
| [Keysight analog-demodulation guide](https://www.keysight.com/bi/en/assets/9018-01829/user-manuals/9018-01829.pdf) | Universal sinusoidal FM beta is peak deviation divided by modulation frequency, unlike Digilent's FM-node percent argument. |
| [Andor/Oxford rolling/global exposure guidance](https://andor.oxinst.com/learning/view/article/faqs-on-rolling-and-global-exposure) | Exposure/readout overlap is architecture/mode dependent; timing terms must not be intuitively added. |

These checks expose naming traps but do not override the installed Digilent or
Hamamatsu manuals.

### Peer-reviewed scientific source

[Martens et al., “Configurable thermoacoustic streaming by laser-induced
temperature gradients,” Physical Review Applied 23, 024043 (2025)](https://journals.aps.org/prapplied/pdf/10.1103/PhysRevApplied.23.024043)
was used for matching apparatus/method facts: Pz26 geometry, reported generator
settings, frequency, sweep wording/time, camera/exposure/frame count/repeats,
laser setting/transmitted measurement, and repeat-to-repeat sample replacement.
It does not describe the present custom amplifier or define whether its phrase
“sweep of 50 kHz” means total span or +/- deviation.

### Project and owner evidence

- current source, tests, action/evidence taxonomy, and Git history;
- `project_control.md`, `known_open_items.md`, retained hardware truth records,
  and prior bounded run evidence;
- owner-confirmed W1/W2/DIO routing and P01/P02 fluid routes;
- owner photographs of the current BNC Adapter and custom amplifier enclosure.

Owner/photo evidence establishes only what it visibly or explicitly supports.
It does not supply unreadable numeric characteristics or independent physical
measurement.

## 4. Parameter-definition matrix

| Family | Operator/internal/API transformation | Evidence/persistence | Source basis | Status |
| --- | --- | --- | --- | --- |
| Carrier frequency | Qt kHz -> internal/API Hz by `x1000`; W1 is API 0, W2 API 1. | Requested `WFGFreq*`; separate post-clamp `WFGEffectiveFreq*`. | SI Hz + Digilent SDK. | VERIFIED |
| FM endpoints/span | `center=(start+stop)/2`; total=`stop-start`; half=total/2. | Explicit requested/effective endpoint, total, half fields. | Digilent sample/API + project endpoint contract. | VERIFIED_WITH_SOFTWARE_DERIVATION |
| Digilent FM argument | `100*half_deviation/center` percent. This is not universal beta. | Requested/effective modulation-index-percent fields. | Digilent SDK; Keysight comparison. | VERIFIED_WITH_SOFTWARE_DERIVATION |
| Sweep period/rate | UI ms; rate Hz=`1000/period_ms`; zero/non-finite fails. | Period ms, FM frequency Hz, shape/direction/symmetry. | SI prefixes + Digilent function semantics. | VERIFIED |
| Sweep shape | Triangle/50% bidirectional; RampUp/100% start->stop/reset; RampDown inverse. Triangle phase-origin endpoint is not claimed. | Requested and software-effective shape fields. | Digilent enums/manual/sample. | VERIFIED |
| Trigger repeat/run | `Repeat=1` required for normal enabled W1; run/wait seconds; zero run is continuous and rejected where completion is required. | WFG trigger fields and preflight/action evidence. | Digilent API + current workflow safety. | VERIFIED |
| Source amplitude/offset | AD2 periodic carrier amplitude is source peak V around source DC offset. Zero-offset sine only: Vpp=2Vpeak, Vrms=Vpeak/sqrt(2). | Qualified UI/tooltips and TDMS convention; requested/effective split. | NIST, Digilent, Tektronix sanity check. | VERIFIED |
| Loaded/acoustic chain | `Vin=Vsource*Zin/(Rsource+Zin)` only for the stated lumped model; JP4 gives direct or 49.9-ohm series path. Amplifier/transducer/acoustic quantities need characterization. | No downstream quantity is fabricated. | Digilent schematic + circuit definition + physical evidence gap. | PHYSICAL_MEASUREMENT_REQUIRED |
| Camera exposure | UI/internal ms -> DCAM s by `/1000`; DCAM set/get s -> ms by `*1000`; device rounds upward by mode. | Requested and configured set/get exposure retained separately. | SI prefixes + exact Hamamatsu/DCAM. | VERIFIED |
| Camera cadence | FPS frames/s; interval `1/FPS`; Internal/free-running limit uses `max(exposure_s, readout_s)`. | Requested FPS; fresh readout seconds; no measured FPS unless timestamps support it. | Hamamatsu exact model + Andor architecture check. | VERIFIED_WITH_SOFTWARE_DERIVATION |
| Capture duration/count | Requested capture-window estimate=`frames/FPS`; actual duration is runtime chronology/timestamps, not guaranteed by request. Camera and AD2 overlap; flush follows. | Frame count/FPS and display-only estimate. | Quantity relation + runtime order. | VERIFIED_WITH_SOFTWARE_DERIVATION |
| ROI/pixel pitch | ROI coordinates/sizes are sensor pixels; requested -> applied -> fresh readback. Pixel pitch 6.5 um is model specification, not sample-plane calibration. | Applied ROI; no object-space claim. | Hamamatsu exact manual. | VERIFIED |
| Camera trigger | Normal mode Internal; DIO0 physically routes to EXT.TRIG but is not programmed. Trigger delay is seconds in API/metadata. | Trigger source plus explicit seconds field; no physical timing claim. | Hamamatsu manual + owner route. | VERIFIED semantics / DEFERRED physical timing |
| Condition/repeat | Internal repeat and temperature-point indices are zero-based; operator/action/folder repeat numbers are one-based; groups precede repeats. | Base metadata, one-based folder/log wording. | Current planner/runtime. | VERIFIED |
| Refresh | One command between confirmed P01 and P02; wait after P02. | Requested fields, protocol/action outcome, no delivery claim. | Current runtime + owner routes. | VERIFIED semantics / PHYSICAL_MEASUREMENT_REQUIRED delivery |
| Pump flow/volume | Positive dispense uL/min; volume/fill absolute mL; estimated travel=`mL*1000/uL_per_min*60` s. | Explicit TDMS units and command/protocol evidence. | SI conversion + CETONI/current configured unit. | VERIFIED |
| Syringe geometry | Diameter/stroke mm, capacity mL; configuration/model values are not installed syringe proof. | Requested/configured state only. | CETONI and project config. | VERIFIED semantics / PHYSICAL_MEASUREMENT_REQUIRED installation |
| Valve | Software 1 -> P01 through-chip, 2 -> P02 bypass. | Owner route truth remains distinct from protocol acknowledgement. | Owner evidence + protocol implementation. | VERIFIED owner mapping / PHYSICAL_MEASUREMENT_REQUIRED independent route |
| Laser | W2 electrical command, Analog In level, Digital In state, rated/emitted/channel optical powers are distinct. | W2/DIO production disabled; no electrical value called optical power. | TOPTICA family + owner label/routing. | DEFERRED / PHYSICAL_MEASUREMENT_REQUIRED |
| Z | Target and readback are controller coordinates in um; physical direction, zero, scale, and microscope datum unresolved. | Authoritative result says `controller_readback_um`; `measured_um` is compatibility alias only. | Thorlabs + current API. | VERIFIED semantics / DEFERRED physical datum |
| TEC | Target and sensor are controller degrees Celsius; stable is controller state, not fluid/imaging-plane equilibrium. | Qualified controller evidence only. | SI/NIST + Meerstetter. | VERIFIED semantics / PHYSICAL_MEASUREMENT_REQUIRED sample state |
| Time/chronology | Configured delays/periods/timeouts use explicit s/ms; UTC is wall clock; monotonic seconds are host elapsed time. | Action chronology and timeout diagnosis only. | SI/NIST + current logging. | VERIFIED semantics / PHYSICAL_MEASUREMENT_REQUIRED synchronization |

## 5. Complete finding register

### F01 — Historical FM total-span factor of two

- Original behavior: project “width” was treated as total span in UI but mapped
  to twice the official SDK percentage.
- Challenge: endpoint reconstruction contradicted the installed official
  `analogout_sweep.cpp` hard case.
- Authority: Digilent SDK manual/sample; SI Hz; Lund only supplies ambiguous
  “sweep of 50 kHz” wording.
- Path: request -> `FmSweepSettings` -> planner -> WaveForms backend -> TDMS.
- Disposition: fixed and checkpointed before audit start; revalidated as
  `100*half_deviation/center`.
- Independent test: `test_fm_sweep_settings_match_martens_et_al_reference_case`
  uses 1.909--1.959 MHz -> 50 kHz total, +/-25 kHz, about 1.2926577%.
- Residual: no tracked historical run proves physical output; literature does
  not define its 50 kHz endpoint convention.

### F02 — Historical FM sweep-shape ambiguity

- Original behavior: shape/direction/symmetry were insufficiently grounded.
- Challenge: exact WaveForms enums and symmetry behavior were available.
- Authority: installed SDK PDF, `dwf.h`, sample; standard FM beta is not used to
  redefine a triangle/ramp device sweep.
- Path: shape selector -> FM carrier settings -> SDK -> action/TDMS evidence.
- Disposition: fixed/checkpointed before audit start and revalidated.
- Independent test: `test_fm_sweep_shape_uses_official_function_and_full_period_directional_ramps`.
- Residual: triangle phase-origin endpoint is intentionally unclaimed.

### F03 — Generic AD2 “Amplitude (V)” label

- Original behavior: current Qt/Tk surfaces and evidence summary could be read
  as loaded, Vpp, RMS, amplifier, or transducer voltage.
- Challenge: Digilent uses peak source amplitude while Tektronix demonstrates
  that generator displays can follow different load conventions; NIST
  distinguishes peak and RMS.
- Authority: Digilent SDK/manual, NIST TN 699, Tektronix AFG manual.
- Path: waveform policy, v1/v2/v3/Tk labels, V3 effective evidence, TDMS.
- Fix: `AD2 source peak amplitude (V)` plus explicit exclusions and an additive
  TDMS convention marker.
- Independent tests: waveform policy semantics, v1/v2/v3 label tests, V3
  effective-evidence test, TDMS metadata test.
- Residual: loaded voltage and all downstream quantities remain unknown.

### F04 — Camera FPS gate added overlapping timing terms

- Original behavior: maximum frame period was modeled as exposure + readout.
- Challenge: the exact C15440-20UP manual states that in free running, long
  exposure gives frame rate 1/exposure; shorter exposure is readout/interface
  limited. Cross-vendor material confirms overlap is architecture dependent.
- Authority: Hamamatsu exact manual; Andor/Oxford overlap sanity check.
- Path: `Application._check_camera_timing_budget()` and UI explanation.
- Fix: use `max(applied_exposure_s, fresh_readout_s)`; unavailable readout still
  fails closed.
- Independent test: hard 40 ms exposure, 11.22 ms documented Fast full-frame
  readout, 25 fps accepted and 25.01 fps rejected.
- Residual: this relationship is for current Internal/free-running operation;
  external modes must be re-derived and physical timing remains unmeasured.

### F05 — Aggregate camera action status overstated mixed evidence

- Original behavior: action stage was `EFFECTIVE` but aggregate status was
  `APPLIED`, even though ROI is fresh readback and exposure set/get while
  sequence configuration is retained accepted software state.
- Challenge: one aggregate label must not promote the least-proven member.
- Authority: project evidence taxonomy and DCAM behavior.
- Path: `Application` camera configuration action record.
- Fix: aggregate status is `EFFECTIVE`; requested/effective payload remains.
- Independent test: correlated full-flow action stream expects `EFFECTIVE`.
- Residual: individual camera fields still need field-level interpretation;
  no physical exposure waveform is claimed.

### F06 — Programmed duration omitted camera-only acquisition

- Original behavior: display estimate used only AD2 output windows plus flush,
  so camera-only runs could show zero programmed acquisition time.
- Challenge: requested `frames/FPS` is known and runtime overlaps camera/AD2.
- Authority: quantity relationship and current execution order.
- Path: `_programmed_repeat_duration_s()` used by v1/v2/v3 timing display.
- Fix: acquisition estimate is max(camera requested window, AD2 window), then
  flush is additive; Camera Start remains excluded because it is metadata only.
- Independent test: 100 frames / 20 fps -> 5 s camera-only estimate; existing
  concurrent AD2-plus-flush case remains 39 s.
- Residual: estimate is not observed duration and is refined from host runtime.

### F07 — Zero-based repeat leaked into operator failure text

- Original behavior: flush failure displayed `experiment.repeat_id` directly.
- Challenge: folders, progress, action records, and operator language are
  one-based while only internal indices are zero-based.
- Authority: current planner/runtime contract.
- Path: `Application.run_experiment2()` flush failure.
- Fix: add one for operator message; persist both base conventions.
- Independent test: exact `repeat 1` failure assertion and TDMS base assertions.
- Residual: legacy `Repeat ID`/`RepeatIndex` stay zero-based for compatibility.

### F08 — Persisted compatibility names hid units/conventions

- Original behavior: `ReadoutTime`, `TriggerDelay`, `MasterPulseInterval`,
  flush fields, FPS, and repeat fields relied on implicit conventions.
- Challenge: a future reader could not answer unit/base from the field alone.
- Authority: SI/NIST, manufacturer APIs, and current source configuration.
- Path: `Experiment2` TDMS property builders.
- Fix: additive `*Seconds`, unit, base, and amplitude-convention fields; legacy
  names retained.
- Independent test: TDMS metadata assertions for exact values and strings.
- Residual: old records still require historical schema interpretation.

### F09 — Z controller coordinate called “measured position”

- Original behavior: structured result, tooltip, CLI, and comments promoted
  controller readback to “real measured position.”
- Challenge: controller readback does not establish direction, scale, zero, or
  microscope displacement metrology.
- Authority: Thorlabs controller semantics plus project physical-evidence rule.
- Path: `piezo_zscan.py`, manual Z UI, filenames, tests.
- Fix: authoritative `controller_readback_um`, qualified UI/CLI wording, and a
  read-only `measured_um` compatibility alias.
- Independent test: result exposes controller-readback value and compatibility
  alias while retaining target/readback distinction.
- Residual: filename prefix remains historical `z_`; current Z commissioning is
  deferred pending physical datum/scale/direction.

### F10 — Lund “50 kHz sweep” convention is not explicit

- Original assumption: the paper independently confirmed total-span wording.
- Challenge: its method gives center, width phrase, and sweep time but no start
  and stop endpoints or +/- qualifier.
- Authority: the publication itself.
- Path: scientific interpretation/documentation only.
- Disposition: current project defines 50 kHz as total span, explicitly labeled
  project/owner interpretation rather than literature fact.
- Independent check: direct paper-method read against repository endpoints.
- Residual: historical Lund data cannot resolve the convention without another
  primary record or author clarification.

### F11 — Current acoustic chain cannot justify a starting amplitude

- Original risk: historical 3 Vpp, 0.1 V, or 2 V values could be reused without
  same-chain termination, amplifier, and load semantics.
- Challenge: photographs show a custom amplifier and unreadable annotations;
  JP4 and transducer identity remain unknown.
- Authority: owner photos/routing, Digilent schematic, Lund paper, circuit
  source/load relation.
- Disposition: no software amplitude chosen; retain
  `CUSTOM_ACOUSTIC_AMPLIFIER_CHARACTERIZATION_REQUIRED` and powered-down
  minimum characterization envelope.
- Independent test/control: W1 still requires explicit safe plan/preflight, but
  no test can prove a physical safe voltage; commissioning stop rule controls.
- Residual: open hard physical blocker before every energized W1 action.

No material conversion defect was found in pump mL/uL/min/seconds arithmetic,
FM kHz/Hz conversion after F01, camera ms/seconds conversion, or Z settle
milliseconds/seconds conversion. This negative conclusion was based on explicit
equations and independent boundary cases, not string-search alone.

## 6. Requested/planned/effective/observed audit

| Layer | Current meaning | Audit conclusion |
| --- | --- | --- |
| REQUESTED | Operator/canonical request before planning or clamp. | Preserved for camera, WFG/FM, timing, refresh, TEC, and output identity. |
| PLANNED | Immutable normalized condition/order and requested device recipe. | `RunPlan` is authority; V3 projection is not authority. |
| EFFECTIVE | Successful software/protocol arguments after policy/clamp or accepted aggregate configuration. | WFG post-clamp and camera aggregate correctly stop here. |
| COMMAND_SENT | A call/write was issued. | Not used as evidence of physical effect. |
| PROTOCOL_ACKNOWLEDGED | Device/transport accepted or returned state. | Valve/Qmix/camera/controller evidence remains protocol scoped. |
| OBSERVED | Returned device/controller data or captured records, explicitly scoped. | Does not by itself prove fluid delivery, physical displacement, sample temperature, voltage, pressure, or synchronization. |
| PHYSICAL_VERIFIED | Independent physical observation/measurement. | Production emits none; required bench evidence remains explicit. |

The audit found and fixed F05, the one remaining aggregate requested/effective
label mismatch. No model specification is persisted as a measured run value.

## 7. Lesson-to-control matrix

| Lesson | Origin | Prevention/control | Independent evidence | Documentation | Residual risk |
| --- | --- | --- | --- | --- | --- |
| Tests can encode the same wrong model | F01/F04 | Externally anchored hard cases | Digilent sample; Hamamatsu 40 ms/11.22 ms case | `lessons_learned.md` | Future formulas need the same review discipline. |
| API conventions are not universal quantities | Digilent percentage versus FM beta | Separate explicit names | Digilent + Keysight | `project_control.md` registry | Non-sinusoidal sweep is not universal beta. |
| Specs/configured/readback/measured differ | Camera/pixel/Z/controller evidence | Evidence taxonomy; qualified fields; no physical stage | Manufacturer manuals + action tests | Project control evidence model | Bench measurement remains required. |
| Peak/Vpp/RMS/source/load differ | F03/F11 | Qualified UI/TDMS; W1 hard stop | NIST + Digilent + Tektronix | Project control amplitude rows | Loaded/acoustic quantities unknown. |
| Post-clamp effective must be separate | Historical WFG loss of request | Separate immutable requested/effective objects | Clamp persistence tests | Project control WFG section | Effective still is not device waveform readback. |
| Connected does not mean driven | W2/DIO routing corrections | W2 fail closed; DIO disabled | Preflight/runtime tests | Four-layer routing table | Future enablement needs separate closure. |
| Timing follows architecture | F04 | `max`, not intuitive addition | Hamamatsu + Andor + hard test | Camera cadence row | Other modes need re-derivation. |
| Historical values are not safe settings | F11 | Commissioning stop rule | Provenance comparison | Electrical closure/readiness | Owner characterization needed. |
| Custom hardware needs characterization | Current amplifier photos | Minimum envelope; no live internal inspection | Owner/build evidence or bounded later plan | HW-ACOUSTIC-CHAIN-001 | STILL_OPEN physical blocker. |
| UI/status is not execution authority | V3 architecture risk | Start rebuilds canonical plan | Shadow-plan parity tests | Architecture/V3 sections | UI may lag but cannot redefine plan. |
| Owner truth needs provenance | Routing/photos | Explicit owner/photo classification | Official connector semantics + owner evidence | Routing/inventory | Independent physical checks remain separate. |
| Internal/operator counts differ | F07 | One-based operator display + base metadata | Exact failure/TDMS tests | Condition/repeat row | Legacy fields remain zero-based. |
| New material defect pauses commissioning | F04 discovered during paused run | No hardware continuation until offline closure/review | Working contract + validated correction | Readiness and this report | Current correction still needs checkpoint authorization. |

Detailed classifications and failure-to-consequence chains are retained in
[`lessons_learned.md`](lessons_learned.md). Material lessons are
`DOCUMENTED_AND_ENFORCED` except the physical characterization itself, which is
`STILL_OPEN` and enforced as a commissioning blocker rather than fabricated in
software.

## 8. Unresolved physical uncertainties and owner decisions

- installed JP4 position/revision and loaded W1 voltage;
- custom amplifier connector roles, controls, input impedance, gain/transfer
  near 1.9--2.0 MHz, output/load envelope, and clipping/current limiting;
- current transducer identity, assembled impedance/resonance, and safe drive;
- a defensible same-chain first source peak amplitude;
- exact installed laser Analog/Digital semantics and all optical powers;
- delivered pump volume/flow, valve route observation, and motion readiness;
- Z direction/scale/zero/microscope datum;
- fluid/imaging-plane temperature and equilibration;
- physical trigger/exposure/acoustic timing.

Owner decisions remain V3-default promotion and any global Manual & Service
interlock policy. These do not alter the current W1 physical blocker.

## 9. Files changed by this audit

At final validation the exact unstaged set was:

1. `docs/known_open_items.md`
2. `docs/lessons_learned.md`
3. `docs/project_control.md`
4. `docs/scientific_parameter_semantics_audit_20260903.md`
5. `src/thermo_acoustic/ad2.py`
6. `src/thermo_acoustic/application.py`
7. `src/thermo_acoustic/piezo_zscan.py`
8. `src/thermo_acoustic/qt_ui.py`
9. `src/thermo_acoustic/qt_ui_v2.py`
10. `src/thermo_acoustic/qt_ui_v3.py`
11. `src/thermo_acoustic/ui.py`
12. `src/thermo_acoustic/workflows.py`
13. `tests/test_application.py`
14. `tests/test_full_flow_dry_run.py`
15. `tests/test_piezo_zscan.py`
16. `tests/test_qt_ui_hardware_settings.py`
17. `tests/test_qt_ui_v3.py`

## 10. Tests and validation evidence

Independent reference cases added or strengthened:

- 1.909--1.959 MHz -> 50 kHz total span, +/-25 kHz, approximately
  1.2926577% Digilent FM argument;
- all three sweep shapes mapped to independent enum/symmetry/direction
  expectations;
- 50.0 ms requested camera exposure reaches DCAM as 0.05 s and a 50.1 ms
  set/get result returns to the application;
- exact C15440-20UP Fast case: 40 ms exposure and 11.22 ms readout permit
  25 fps but reject 25.01 fps;
- 100 frames at 20 fps produce a 5 s requested camera-only duration estimate;
- 0.05 mL at 200 uL/min produces 15 s travel before the separate timeout
  margin;
- repeat index 0 is operator repeat 1 and metadata declares both bases;
- Z result is controller readback, with compatibility alias explicitly tested.

Validation completed before finalization:

- initial focused application/UI suite: `444 passed` before the final Z wording
  and lesson-control additions;
- final semantics-focused suite: `265 passed` (application, full-flow,
  piezo-Z, waveform policy/labels/duration, and V3 evidence);
- broad offline suite: `684 passed, 1 skipped, 3 failed`; all three failures
  had the already-tracked PySide/Shiboken deleted-C++-widget lifetime signature,
  not a parameter-semantic assertion. Two passed immediately in fresh isolated
  processes; the third passed on the next fresh isolated run. No retry/skip/
  xfail or production workaround was added, and `TEST-QT-LIFETIME-001` remains
  visible as a nonblocking follow-up;
- change-surface audit covered camera timing, duration estimator, waveform
  policy, TDMS settings/sequence/camera builders, and UI inheritance;
- `python -m compileall -q src tools`: passed;
- `python tools/check_repository_hygiene.py`: passed with zero issues;
- `git diff --check`: passed;
- no hardware-backed tests were run.

Reproducible final validation commands (run from the repository root):

```text
python -m pytest -q tests/test_application.py tests/test_full_flow_dry_run.py tests/test_piezo_zscan.py "tests/test_qt_ui_hardware_settings.py::test_every_exposed_waveform_has_explicit_policy" "tests/test_qt_ui_hardware_settings.py::test_wfg_tab_and_experiment_tab_carry_live_use_labels" "tests/test_qt_ui_hardware_settings.py::test_programmed_repeat_duration_uses_concurrent_ad2_window_then_flush" "tests/test_qt_ui_hardware_settings.py::test_programmed_repeat_duration_includes_camera_only_capture_window" "tests/test_qt_ui_v3.py::test_v3_action_log_surfaces_requested_effective_discrepancies"
python -m pytest -q
python -m pytest -q "tests/test_qt_ui_v2.py::test_v2_no_group_box_is_squeezed_below_its_minimum_size_hint"
python -m pytest -q "tests/test_qt_ui_v2.py::test_v2_every_value_widget_has_a_tooltip_and_visible_marker"
python -m pytest -q "tests/test_qt_ui_v2.py::test_v2_configuration_column_places_run_control_above_setup_tabs"
python tools/audit_change_surface.py --symbol _check_camera_timing_budget --symbol _programmed_repeat_duration_s --symbol WaveformParameterPolicy --symbol _settings_properties --symbol _sequence_properties --symbol _camera_properties
python -m compileall -q src tools
python tools/check_repository_hygiene.py
git diff --check
```

The preliminary 444-test selection was an intermediate signal rather than the
final acceptance command; the final 265-test command above supersedes it for
reproduction of the affected semantic paths.

## 11. Final classification

`PARAMETER_SEMANTICS_AND_ENGINEERING_RULES_VALIDATED`

This classification means software parameter definitions, transformations,
evidence boundaries, controls, and durable rules are coherent under the final
combined methodology. It does **not** mean the acoustic chain is commissioned
or that unresolved physical quantities have been measured. Gate 3/Gate 4 and
all energized W1 output remain prohibited until the physical chain closure is
complete and a later run is separately authorized.
