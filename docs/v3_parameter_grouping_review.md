# V3 Experiment-Parameter Relationship and Grouping Review

**Status:** implementation follow-up. Commit `085c06a` implemented six of the
seven UI recommendations in Sections 4.1 and 4.2. The Channel 1/“Ch2” identity,
DIO1 synchronization, and related behavior-policy questions in Section 4.3
remain unresolved; the implementation is not hardware verification.

**Scope:** the parameters inherited from the LabVIEW `Experiment` tab and their
current presentation in `src/thermo_acoustic/qt_ui_v3.py`. Manual diagnostic
panels, initialization, Z-scan, and TEC behavior are outside the grouping
proposal except where they help distinguish experiment state from manual state.

## Evidence and terminology

This review uses the following provenance tags so that an implementation
decision is not mistaken for a verified hardware fact:

- **[PROJECT FACT]** Directly established by current repository code or project
  documentation. A file-and-line citation follows each material claim.
- **[HISTORICAL EVIDENCE]** Retained LabVIEW material, a repository preset, or
  git history. It can show an earlier convention without proving current wiring.
- **[OWNER CONVENTION]** An operating practice supplied for this review. It is
  tested against the repository before being accepted as a project fact.
- **[EXTERNAL]** Supplemental vendor, HMI, or publication guidance. It cannot
  override this apparatus's code or physical evidence.
- **[JUDGMENT]** A proposed information architecture or presentation choice.
- **[UNVERIFIED HARDWARE]** A relationship that still needs physical inspection
  or measurement.

In this document, “independent” means that current software neither derives nor
validates one parameter from the other. It does **not** mean that the two cannot
affect the same scientific outcome.

The historical reference is one combined LabVIEW Experiment panel containing
series controls, camera timing, both WFG-channel timings, acquisition counts,
fluidics, and dynamic modes (`docs/labview_ui_field_reference.md:146-168`). A
single panel proves historical proximity, not causal equivalence.

## 1. Ground-truth relationship framework

### 1.1 Execution-level causal map

The current automated path builds one experiment object per repeat, then
configures WFG and DIO, configures the camera, starts capture, issues one shared
AD2 PC trigger, waits for capture and outstanding AD2 duration, optionally
flushes, and saves the repeat (`src/thermo_acoustic/qt_ui.py:3880-3955`;
`src/thermo_acoustic/application.py:670-740,744-803`). This yields the following
software-grounded map:

```text
Series path + Repeats
  -> repeat_001 ... repeat_N folders and queued Experiment2 units
  -> Frequency-scan point count must equal Repeats when scan is enabled
  -> Dynamic DIO1-start mode consumes one of 10 delay slots per repeat

Within each repeat
  AD2 analog WFG channel 0 (LabVIEW Ch1)
    base carrier: Frequency + Amplitude (+ waveform/offset/shape)
    timing: Start delay + Run duration
    optional within-repeat FM sweep -> same channel-0 carrier/FM node
    optional per-repeat frequency scan -> channel-0 carrier override

  AD2 analog WFG channel 1 (LabVIEW Ch2)
    its own carrier and timing
    physical apparatus purpose remains unverified

  Acquisition timing request
    Camera FPS -> DIO1 requested pulse rate
    Frames / Camera FPS -> DIO1 requested run duration
    fixed Camera Start OR repeat-indexed Camera Start Array -> DIO1 wait
    Exposure + camera readout time -> maximum sustainable FPS
    camera is nevertheless forced to Internal trigger today

  Completion gate
    max(enabled WFG start+run, enabled DIO start+run)
    continuous (Run = 0) is rejected because completion is undefined

  Optional post-capture flush
    requested Volume <= syringe capacity and current fill
    movement duration = Volume / Flowrate
    timeout = movement duration in seconds + 5 s
    P01 -> pump move -> P02 -> WaitAfterFlush -> final fill-level command
```

Evidence for the DIO formula and channel is
`src/thermo_acoustic/qt_ui.py:4020-4051`. Evidence for the maximum completion
gate and finite-duration requirement is
`src/thermo_acoustic/application.py:371-400,450-459`. Evidence for the camera
timing budget is `src/thermo_acoustic/application.py:409-448`. Evidence for the
flush sequence is `src/thermo_acoustic/application.py:530-615`; its timeout is
`src/thermo_acoustic/workflows.py:52-71`.

### 1.2 Owner-stated relationship verification

| Stated relationship | Verdict | Evidence and qualification |
| --- | --- | --- |
| Ch1 WFG Run and “Ch2 camera-related” Run are normally equal and are two aspects of one timed event. | **QUALIFIED; not established as current hardware semantics.** | **[HISTORICAL EVIDENCE]** The retained working preset gives both LabVIEW Ch1 and Ch2 a 60 s run (`src/thermo_acoustic/experiment_presets.py:38-52,67-79`). **[PROJECT FACT]** Current code maps those controls to two independent analog WFG channels, index 0 and index 1 (`src/thermo_acoustic/qt_ui.py:3348-3403,4179-4195`); v3 explicitly labels the historical mapping (`src/thermo_acoustic/qt_ui_v3.py:637-638`). Channel 1's purpose is explicitly unknown in the real-hardware smoke path (`hardware_tests/test_real_workflow_smoke.py:31-38`). No equality link, warning, or validation exists. The camera-related digital timing is a separate DIO1 configuration. **[OWNER CONVENTION]** Equal values may still be a valid bench practice, but it must not be encoded as a hardware fact until “Ch2” is disambiguated. |
| Frames is normally less than FPS × Ch2 Run. | **NOT IMPLEMENTED, and the current naming makes the claim ambiguous.** | If “Ch2 Run” means analog WFG index 1, current code has no such rule. If it means the camera-related DIO run, current code derives `DIO run = Frames / FPS`, hence `Frames = FPS × DIO run` algebraically, not strictly less (`src/thermo_acoustic/qt_ui.py:4020-4041`). No warning, clamp, or rejection compares Frames with either analog WFG run. **[OWNER CONVENTION]** A strict-less-than margin could be an intentional acquisition policy, but the intended reference duration must be clarified before implementation. |
| Flush Flowrate, Volume, and WaitAfterFlush are one coupled physical sequence. | **CONFIRMED.** | Flowrate must be positive; Volume is bounded by capacity and current fill; Flowrate and Volume determine the pump timeout; WaitAfterFlush occurs after confirmed P02 (`src/thermo_acoustic/application.py:530-615`; `src/thermo_acoustic/workflows.py:52-71`). They should remain one conceptual group. |
| Dynamic Frequency / Frequency List and FM Sweep affect the same channel as static Frequency/Amplitude. | **CONFIRMED, with a mode-combination qualification.** | Both affect channel 0 only. FM sweep replaces the base carrier with its center and enables FM; the per-repeat scan override is applied afterward, so its carrier value wins if both are enabled (`src/thermo_acoustic/qt_ui.py:3372-3391`). Scan is discrete across repeats; FM is continuous within a repeat (`src/thermo_acoustic/qt_ui.py:1176-1183,1348-1356`). They are related programs of the same output, but current code permits them to be layered rather than enforcing mutually exclusive modes. Amplitude remains the channel-0 carrier amplitude. |
| Dynamic Camera Start and GlobalExposure belong to camera/AD2 timing and touch an unresolved synchronization question. | **CONFIRMED as a software coupling; synchronization remains unverified.** | Fixed or dynamic Camera Start selects DIO1 `sec_wait`; Frames/FPS supplies DIO1 `sec_run` (`src/thermo_acoustic/qt_ui.py:4020-4051`). GlobalExposure is passed to the camera (`src/thermo_acoustic/application.py:735-740`). Automated capture forces DCAM `Internal`, and the repository explicitly says DIO1/exposure coincidence and the physical trigger cable are not proven (`src/thermo_acoustic/qt_ui.py:3929-3948`; `docs/hardware_repair_plan.md:97-129`). |

The 2026 channel-caption clarification in commit `3474232` changed displayed
LabVIEW-style names from Ch1/Ch2 to zero-based CH0/CH1; the execution mapping was
already analog WFG index 0/index 1. This is a naming clarification, not evidence
that analog channel 1 is a camera trigger.

### 1.3 Parameter-by-parameter relationship table

| LabVIEW Experiment parameter | Causal dependencies and constraints | Software-independent from | Mode or alternative relationship | Grounding |
| --- | --- | --- | --- | --- |
| Camera FPS | Must be positive to build DIO1. With Frames, determines nominal DIO1 duration. Exposure plus live camera readout time limits achievable FPS. | No current formula links it to analog WFG frequency, amplitude, or either WFG duration. | Base requested DIO1 pulse rate; not a camera-trigger guarantee while DCAM is Internal. | `qt_ui.py:4020-4041`; `application.py:409-448`; `hardware_repair_plan.md:97-129` |
| Camera Start (s) | Supplies DIO1 `sec_wait` for every repeat when dynamic start is off. Contributes to AD2 completion time. | No current derivation from exposure, FPS, or analog WFG start. | Mutually selected with the current repeat's Camera Start Array value. | `qt_ui.py:4025-4033`; `application.py:387-400` |
| Ch1 Frequency (current WFG channel 0) | Sets channel-0 carrier frequency unless FM sweep and/or per-repeat scan overrides it. | No current formula derives it from acquisition counts or fluidics. | Static base value; FM center and scan point are alternate/overlaid effective values on the same channel. | `qt_ui.py:3348-3391` |
| Ch1 Amplitude (current WFG channel 0) | Sets the analog drive amplitude and is subject to backend hardware bounds. It remains the carrier amplitude under current scan/FM construction. | Independent in current orchestration from Frames, FPS, start/run durations, and flush. | Base channel property, not a separate scan mode. | `qt_ui.py:3348-3379`; `hardware_safety_patterns.md:1-44` |
| Ch1 Start (s) | Supplies WFG channel-0 `sec_wait`; with Run, determines channel-0 completion. | Not derived from Camera Start or channel-1 start. | Fixed timing for that output. | `qt_ui.py:3392-3401`; `application.py:371-385` |
| Ch1 Run (s) | Supplies WFG channel-0 `sec_run`; zero/continuous is rejected for automated completion. Participates in the maximum AD2 completion budget. | No current equality constraint with channel 1 or DIO1. | Fixed timing for that output. | `qt_ui.py:3392-3401`; `application.py:371-400,450-459` |
| Ch2 Start (s) (current WFG channel 1) | Supplies analog WFG channel-1 `sec_wait`; with Run, determines that channel's completion. | Not derived from camera start or channel-0 start. | Fixed timing for independent SDK channel 1. Physical purpose is unverified. | `qt_ui.py:3348-3403,4179-4195`; `hardware_tests/test_real_workflow_smoke.py:31-38` |
| Ch2 Run (s) (current WFG channel 1) | Supplies analog WFG channel-1 `sec_run`; zero/continuous is rejected if enabled. Participates in maximum AD2 completion. | No current equality or Frames/FPS constraint. | Fixed timing for independent SDK channel 1. Do not relabel it as camera duration without bench evidence. | `qt_ui.py:3392-3403`; `application.py:371-400,450-459` |
| Repeats | Determines queued units and repeat folders. Must equal frequency-scan point count. Dynamic-start mode has only 10 slots. Optional flush is repeated once per unit. | Does not alter each repeat's amplitude, exposure, or flush values. | Series cardinality and the indexing axis for scan/dynamic-start alternatives. | `qt_ui.py:1274-1281,3880-3955,4025-4028` |
| Frames | Passed to camera acquisition. With FPS, derives DIO1 run duration. Total progress frame count is Frames × Repeats. | No current comparison against either WFG run duration. | Count input and duration numerator, not an independent camera-timing island. | `qt_ui.py:1283-1288,3937-3955,4020-4041`; `application.py:767-775` |
| ExposureTime (ms) | Applied to real camera. Together with ROI readout time, limits sustainable FPS. | No current formula links it to WFG amplitude/frequency/timing or fluidics. | Camera exposure property; distinct from `GlobalExposure`. | `application.py:715-740,409-448` |
| Flush Flowrate | Must be positive. With Volume, determines commanded movement and timeout. | Does not configure acquisition or WFG; flush is after capture/completion. | One field of the optional post-capture flush operation. | `application.py:530-582,794-803`; `workflows.py:52-71` |
| Flush Volume | Bounded by syringe capacity and current fill. With Flowrate, determines movement duration/timeout and new fill level. | Does not configure camera or WFG. | One field of the optional post-capture flush operation. | `application.py:530-580`; `workflows.py:52-71` |
| WaitAfterFlush | Delay after confirmed P02 and before the final fill-level command/completion status. | Does not change the calculated pump movement duration. | Final phase of the same flush operation, not a generic experiment delay. | `application.py:606-615` |
| Dynamic Frequency + Frequency List | Enabled scan creates a linear per-repeat channel-0 frequency list. Count comes from Number of Frequencies or Step Size and must equal Repeats. Linear LabVIEW fidelity remains documented as inferred. | Does not alter analog channel 1 or camera timing. | Per-repeat channel-0 carrier override. Step Size and Number of Frequencies are alternative list-generation inputs. | `qt_ui.py:1348-1387,3405-3427,3884-3917` |
| FM Sweep | Sets channel-0 FM modulation and effective center; Start/Stop and Center/Width are two synchronized input conventions for the same range. | Does not affect channel 1 or fluidics. | Continuous within-repeat channel-0 mode. It can currently coexist with scan; scan carrier override wins after FM setup. | `qt_ui.py:1176-1215,3180-3218,3372-3391` |
| Dynamic Camera Start Time | Selects per-repeat array value instead of fixed Camera Start. Repeats cannot exceed ten slots. | Does not change FPS, Frames, or exposure. | Boolean selector between two DIO1-delay sources. | `qt_ui.py:1318-1337,4025-4033` |
| GlobalExposure | Requests the camera `GLOBALRESET` behavior; may require a compatible trigger source. False deliberately leaves the property unchanged. | Not the numerical exposure time and not a DIO duration. | Camera trigger/exposure behavior option with unresolved applicability. | `qt_ui_v3.py:540-548`; `application.py:735-740` |
| Camera Start Array(s) | Provides ten repeat-indexed DIO1 wait values; selected only by Dynamic Camera Start. | Does not itself set repeat count or FPS. | Alternative source to the fixed Camera Start field. | `qt_ui.py:1318-1325,4025-4033` |

### 1.4 What the reference publication does and does not establish

**[EXTERNAL]** Martens et al., [“Configurable thermoacoustic streaming by
laser-induced temperature gradients”](https://journals.aps.org/prapplied/abstract/10.1103/PhysRevApplied.23.024043),
establishes that the scientific phenomenon combines an acoustic field with a
laser-induced temperature gradient and imaging/measurement. That supports an
operator-facing experiment narrative connecting acoustic actuation, optical
heating, and acquisition. It does **not** document this Python application's
AD2 line assignment, prove that current analog WFG channel 1 is camera-related,
or establish a Ch1/Ch2 duration equality. Repository wiring evidence therefore
wins on those questions.

## 2. Supplemental external control-panel conventions

| Source | Relevant convention | Agreement or conflict with this project |
| --- | --- | --- |
| NI, [VI Front Panels](https://www.ni.com/en/support/downloads/instrument-drivers/tools-resources/instrument-driver-guidelines/vi-front-panels.html) and [LabVIEW User Manual](https://download.ni.com/support/manuals/320999e.pdf) | Keep panels simple; keep controls visible; place common controls consistently; use consistent display formats; visually group logically related controls. | **Agrees** with grouping causal sets and keeping units consistent. It does not decide which apparatus fields are physically linked. |
| NI, [LabVIEW Development Guidelines](https://download.ni.com/support/manuals/321393d.pdf) | Keep top-level interfaces simple, make important controls prominent, and group by related function rather than using clusters merely as decoration. | **Agrees** with a compact series/run layer plus task-oriented actuation, acquisition, and fluidics groups. |
| Keysight BenchVue, [Sweep Tab](https://helpfiles.keysight.com/BenchVueSoftware_HDML5HelpFiles/SigGenApp/English/Content/Modulation%20and%20Sweep%20Panel/Sweep%20Tab.htm) | Presents frequency/amplitude sweep as signal-generator behavior, exposes enable, List/Step type, direction, and repeat together. | **Agrees** that static channel-0 carrier, discrete frequency program, and FM behavior should read as one output's modes. **Conflict to avoid:** Keysight's List/Step taxonomy is not identical to this code's per-repeat scan versus continuous FM sweep, so its labels should not be copied literally. |
| Basler, [Triggered Image Acquisition](https://docs.baslerweb.com/triggered-image-acquisition) | Trigger selector, mode, source, activation, and delay form a coherent acquisition configuration. | **Agrees** that trigger-related camera fields should be presented together and their active mode made visible. It does not prove this apparatus uses external triggering. |
| Basler, [Factors Limiting Frame Rate](https://docs.baslerweb.com/knowledge/factors-limiting-the-frame-rate-of-the-pylon-camera-emulator) | Exposure and acquisition/readout behavior limit attainable frame rate. | **Agrees** with the repository's explicit FPS-versus-exposure/readout validation (`application.py:409-448`). |
| Harvard Apparatus, [Pump 11 Elite & Pico Plus manual](https://support.harvardapparatus.com/hc/en-us/article_attachments/31241958761107) | A constant-rate profile treats direction, flow rate, and target volume or time as the primary parameters determining the operation. | **Agrees** with preserving Flowrate and Volume as one operation. This project's P01/P02/settle sequence remains project-specific. |
| CETONI, [SDK Pump Library](https://cetoni.com/downloads/manuals/CETONI_SDK/PumpAPI.html) | Syringe-pump flow is limited by actuator speed and volume by actuator travel/syringe state. | **Agrees** with showing capacity/fill constraints with the flush inputs. It does not resolve the project's unverified valve routing. |
| NRC, [NUREG-0700 Revision 3](https://www.nrc.gov/reading-rm/doc-collections/nuregs/staff/sr0700/r3/index) | Reviews both physical and functional HSI characteristics and includes group-view and soft-control systems. | **Broad agreement** with assessing functional relationships, not mere visual proximity. This is high-consequence HMI guidance, not an apparatus-specific layout prescription. |

The common external pattern is useful but subordinate: show mode alternatives in
the context of the instrument/output they modify; colocate or visibly cross-link
causally dependent timing values; and expose calculated limits. None of these
sources authorizes claiming DIO1/camera synchronization before the repository's
bench question is closed.

## 3. Audit of v3's current organization

### 3.1 Current structure

V3 builds a stable hardware-status strip, experiment status, run controls, setup
tabs, and a runtime monitoring column (`qt_ui_v3.py:222-253`). The experiment
setup tabs are AD2 Output, Camera, Fluidics, and Temperature scan
(`qt_ui_v3.py:361-410`). Manual WFG, camera, pump/valve, and other diagnostic
surfaces live in separate sidebar dialogs; this audit does not propose merging
manual and automated state.

| Current grouping decision | Assessment against the relationship framework |
| --- | --- |
| **Experiment run** holds Start, graceful stop, Series path, and an execution-semantics note (`qt_ui_v3.py:323-359`). | **Sound.** These are series-level actions/storage, not device parameters. Repeats is the missing series-level companion. |
| **AD2 Output** contains a channel tab set, then sibling FM Sweep and Frequency Scan tabs (`qt_ui_v3.py:365-378`). | **Directionally sound but incomplete.** The frequency programs are near channel 0, yet the visual hierarchy does not say “base carrier → within-repeat FM and/or per-repeat override,” nor show what happens when both enables are on. |
| Each AD2 channel page groups **Carrier waveform**, **Timing and trigger**, and **Waveform shape** (`qt_ui_v3.py:412-457`). | **Sound for an independently configurable SDK channel.** It keeps each output's carrier and trigger fields together. It also reinforces that current channel 1 is an analog WFG output, not a camera duration. |
| Channel 0 and channel 1 live on separate tabs (`qt_ui_v3.py:416-420`). | **Potential workflow mismatch, not a proven physical mismatch.** The owner's equal-duration convention is invisible, but current code does not establish equality. A forced link would be premature; a neutral comparison/timeline is justified. |
| FM Sweep presents Start/Stop and Center/Width simultaneously through the inherited group (`qt_ui_v3.py:369-376`; builder at `qt_ui.py:3180-3218`). | **Controls are correctly colocated, but equivalence is mostly tooltip-dependent.** Both pairs are synchronized views of one range. A persistent “equivalent entry forms” label and computed effective range would prevent them reading as four independent frequencies. |
| Frequency Scan is a separate modulation tab (`qt_ui_v3.py:369-376`). | **Same-channel relationship is named in the title but cross-series dependency is hidden.** The list count must equal Repeats, which is in Camera. Number of Frequencies versus Step Size precedence is also primarily tooltip/error knowledge. |
| **Experiment acquisition** contains DIO1 FPS, fixed DIO1 delay, Repeats, Frames, Exposure, GlobalExposure, dynamic-delay selector, and ten delays (`qt_ui_v3.py:515-550`; inherited layout `qt_ui_v2.py:789-824`). | **Mixed.** FPS, Frames, Exposure, GlobalExposure, and fixed/dynamic DIO timing belong in one acquisition/timing context. Repeats is series cardinality, not a camera property, even though it indexes scan and dynamic delays. The group shows no `Frames/FPS` duration, no exposure/readout FPS budget, and no active-mode disabling. |
| V3 deliberately captions Camera FPS/Start/array as DIO1 pulse rate/delay (`qt_ui_v3.py:520-539`). | **Accurate and commendably cautious.** The dynamic-start tooltip says physical alignment with exposure remains bench-unverified (`qt_ui_v3.py:545-548`). However, that critical boundary is hidden behind a tooltip while the enclosing tab is simply “Camera,” which can still imply synchronization. |
| GlobalExposure is beside acquisition timing and carries a compatibility warning (`qt_ui_v3.py:525,540-544`). | **Correct neighborhood; insufficient state visibility.** It is distinct from numeric exposure and may be ineffective under the forced Internal trigger. Enabling it should surface that unresolved applicability inline. |
| Fixed and per-repeat DIO1 start values are in the same acquisition group (`qt_ui_v2.py:797-822`; adapted at `qt_ui_v3.py:521-539`). | **Good causal grouping.** The selector chooses one source, but both modes remain visually live; the active alternative is not obvious without knowing the code. |
| **Fluidics** contains an optional-sequence note and the complete inherited Flush group (`qt_ui_v3.py:386-402`; builder `qt_ui.py:3108-3116`). | **Sound and should remain intact.** Flowrate, Volume, and WaitAfterFlush stay together. The current layout does not expose derived move time, timeout, capacity, or current-fill margin, but it does not falsely separate them. |
| **Temperature scan** has its own setup page (`qt_ui_v3.py:404-409`). | **Sound and outside this review's parameter set.** It is a structurally different series dimension and explicitly marked simulated/unapproved in v3 (`qt_ui_v3.py:483-492`). |
| Runtime waveform/rate and global status form the monitoring column (`qt_ui_v3.py:468-481,552-570`). | **Sound separation of configuration from live feedback.** A future timing-plan summary should be configuration feedback, not mixed into measured live rate. |

### 3.2 Specific obscured relationships

1. **Series cardinality is mislabeled as acquisition-local.** `Experiment repeats`
   appears in the Camera acquisition group (`qt_ui_v3.py:515-533`), but it builds
   all repeat objects and folders, must equal scan count, indexes dynamic delays,
   and repeats the optional flush (`qt_ui.py:3880-3955`). This makes the scan
   relationship invisible until validation fails.

2. **The acquisition duration is available but not shown.** V3 places FPS and
   Frames together (`qt_ui_v3.py:520-525`) but presents no read-only
   `Frames / FPS` duration, even though that exact value becomes DIO1 run time
   (`qt_ui.py:4020-4041`). The operator cannot compare that window with either
   WFG channel's start/run window without manual arithmetic across tabs.

3. **The owner timing convention is entirely implicit.** Channel run durations
   are on separate AD2 tabs (`qt_ui_v3.py:416-445`), while FPS/Frames are on the
   Camera tab (`qt_ui_v3.py:515-539`). There is no live comparison, linked
   default, or soft warning. Because equality is not yet a verified current
   invariant, this is a visibility gap rather than grounds for automatic linking.

4. **Channel-0 frequency precedence is hidden.** Static Frequency is in the
   channel-0 Carrier group (`qt_ui_v3.py:428-436`); FM and scan are separate
   sibling tabs (`qt_ui_v3.py:369-377`). If both are enabled, FM first sets the
   center and scan then overwrites the carrier frequency
   (`qt_ui.py:3372-3391`). V3 offers no effective-frequency summary or explicit
   combined-mode explanation.

5. **Alternative entry forms can look like extra degrees of freedom.** FM
   Start/Stop and Center/Width are synchronized representations of the same
   range (`qt_ui.py:1203-1210,3214-3217`), while scan Count and Step Size are
   precedence-based alternatives (`qt_ui.py:1370-1387,3405-3427`). V3 renders
   each pair together but does not visibly distinguish “equivalent” from
   “overrides”; that knowledge resides in tooltips.

6. **The Camera tab can imply more synchronization than exists.** Its captions
   accurately say DIO1 (`qt_ui_v3.py:520-539`), yet automated DCAM is forced
   Internal (`qt_ui.py:3929-3948`). The persistent page has no inline statement
   that DIO1-to-exposure alignment is unverified. This is exactly the boundary
   left open in `docs/hardware_repair_plan.md:97-129`.

7. **Camera FPS feasibility is validated late but not previewed.** Exposure and
   FPS are grouped, which is correct, but the real readout-dependent maximum is
   only checked in `Application` immediately before capture
   (`application.py:409-448`). A read-only “requires hardware readback” state
   before initialization and an applied budget after connection would make the
   dependency visible without inventing a limit.

8. **Flush is correctly grouped but its causal result is opaque.** The three
   fields stay together (`qt_ui_v3.py:386-400`), but no nominal move duration,
   five-second timeout margin, or capacity/current-fill budget is displayed.
   This is a discoverability improvement, not a reason to split Fluidics.

## 4. Reorganization proposal (six of seven recommendations implemented in `085c06a`)

### 4.1 Information architecture

1. **Series and run** — keep Series path and run/stop controls where they are;
   move `Repeats` into this series-level group. Add linked summaries for
   “frequency points / repeats” and “dynamic-delay slots / repeats.”
   **[PROJECT FACT + JUDGMENT]** The move follows how `_build_experiment_series()`
   consumes the value, not visual preference.

2. **One-repeat timing plan** — add a read-only, cross-instrument summary near
   the top of setup:

   - WFG channel 0: start, run, nominal end;
   - WFG channel 1: start, run, nominal end;
   - DIO1 request: selected fixed/per-repeat start, `Frames/FPS` run, nominal end;
   - camera: requested Frames, exposure, requested FPS, and feasibility state;
   - neutral deltas/margins between the three windows.

   **[JUDGMENT]** This exposes the owner's workflow convention without enforcing
   an unverified equality. Use “requested DIO1 window,” never “camera exposure
   window” or “synchronized.” A soft informational marker may say that a saved
   operating convention expects matching durations only after the owner clarifies
   which duration is intended.

3. **Acoustic / primary analog output (AD2 channel 0, LabVIEW Ch1)** — keep base
   carrier and its start/run together. Nest a **Frequency program** directly
   beneath it with three clearly described layers:

   - static carrier frequency;
   - optional within-repeat FM sweep;
   - optional per-repeat scan keyed to series Repeats.

   Show an effective-frequency preview for each repeat and explicitly show the
   result when FM and scan are both enabled. Do not silently make them exclusive:
   that would change current semantics. **[PROJECT FACT + JUDGMENT]** Keysight's
   convention supports same-output grouping, but this project's actual override
   order determines the labels.

4. **Secondary analog output (AD2 channel 1, LabVIEW Ch2)** — retain its carrier
   and timing as an independent channel group, labelled “physical apparatus role
   not yet verified.” Place it adjacent to the timing-plan comparison but do not
   call it camera-related and do not auto-link its run time.
   **[UNVERIFIED HARDWARE + JUDGMENT]** This avoids encoding the disputed premise.

5. **Acquisition and DIO timing request** — keep FPS, Frames, numeric Exposure,
   GlobalExposure, fixed/dynamic DIO1 start, and the delay array together. Add:

   - nominal requested duration `Frames / FPS`;
   - active-mode styling that disables/fades the unused fixed start or array;
   - a visible ten-slot/Repetition budget;
   - a visible exposure/readout/FPS feasibility result when hardware data exists;
   - a persistent banner: “Automated camera trigger = Internal; DIO1/exposure
     synchronization is not yet bench verified.”

   **[PROJECT FACT + JUDGMENT]** This strengthens an already mostly correct group.

6. **Fluidics / post-capture flush** — keep enable, Flowrate, Volume, and
   WaitAfterFlush together. Add read-only nominal movement time, timeout, syringe
   capacity, and current-fill margin when known. Preserve the sequential P01 →
   pump → P02 → wait explanation. **[PROJECT FACT + EXTERNAL AGREEMENT]** No field
   should move out of this operation.

7. **Temperature scan and manual panels** — leave separate. Temperature is a
   series dimension with its own approval boundary; the manual WFG panel
   explicitly says its settings do not affect experiment runs
   (`qt_ui_v3.py:605-625`). **[PROJECT FACT + JUDGMENT]** Combining these surfaces
   would imply state sharing that v3 explicitly denies for that panel.

### 4.2 Link and warning behavior

The first implementation should prefer computed read-only relationships and soft
warnings over automatic mutation:

- Show values and deltas immediately; do not auto-copy WFG run durations.
- Warn on frequency-count versus Repeats before Start, while retaining the
  backend rejection.
- Visually select fixed versus dynamic DIO1 start and Count versus Step Size;
  preserve inactive values for easy mode switching.
- Show FM Start/Stop and Center/Width as “equivalent input conventions,” not four
  independent settings.
- Treat an enabled FM+scan combination as an explicit combined state and display
  the effective result; do not change precedence during a grouping-only pass.
- Put the unverified DIO1/camera boundary inline, not only in an information-icon
  tooltip.

This follows the repository safety principle that consequential limits and
unknowns should be surfaced and that validation should not silently clamp or
invent a value (`docs/hardware_safety_patterns.md:1-44`).

### 4.3 Required clarifications before a UI implementation

1. Trace what physical apparatus, if any, is driven by analog WFG channel 1.
2. Ask whether the owner's “Ch2 Run” in `Frames < FPS × Ch2 Run` means analog WFG
   channel 1 or the derived DIO1 pulse window.
3. Scope DIO1 against camera exposure/trigger output and trace the trigger cable,
   as already required by `docs/hardware_repair_plan.md:115-129`.
4. Decide the intended policy when FM sweep and per-repeat scan are both enabled:
   preserve the current layered behavior, reject the combination, or define a
   different explicit composition. That is a behavior decision, not a layout
   change.

Until those are answered, an implementation may safely add neutral computed
summaries and expose existing constraints, but it should not auto-link durations,
apply the strict Frames inequality, relabel WFG channel 1 as a camera channel, or
claim camera/AD2 synchronization.

## 5. Bottom-line assessment

V3's broad device/task split is not arbitrary: carrier/timing stays per WFG
channel, acquisition fields mostly stay together, and the entire flush sequence
stays in Fluidics. The recurring dissatisfaction is better explained by missing
**cross-group relationship visibility** than by wholly wrong top-level tabs.

The defensible next design is therefore not another wholesale reshuffle. It is a
series-level home for Repeats, a one-repeat timing-plan summary, explicit
channel-0 frequency-mode hierarchy, visible alternative-mode state, and inline
truth about the unverified DIO1/camera boundary. That proposal is grounded in the
current execution model; external conventions merely reinforce it.
