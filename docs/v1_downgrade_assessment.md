# Gradual v1 Downgrade Assessment

Date: 2026-08-27
Evidence baseline: `085c06a` (`085c06a8da5a8e7c7d379bd8f207a9793d7d26ca`);
live citations revalidated at `a3d000f`
Status: **investigative only.** Nothing here is implemented, and nothing here
authorizes an entry-point, documentation, UI, inheritance, or hardware-behavior
change. All findings below were re-derived directly from the code at this
baseline.

## Scope and conclusion

The owner wants `qt_ui.py`'s `MainWindow` to end up as an internal-only base
class rather than a directly launched, user-facing interface, done gradually as
internal differentiation rather than one restructuring pass.

V1 currently holds two separate roles: it is the **default operator interface**
*and* it is the **concrete base class** from which `MainWindowV2` and
`MainWindowV3` inherit essentially all of their behavior. Those two roles are
separable, and only the first one is what "downgrading v1" is about.

The smallest safe first increment is a **launcher-default and
documentation-level change**, not a code change to `MainWindow` -- with one
unavoidable exception noted below (`tools/run_ui.py` is itself a two-line Python
launcher, so redirecting it edits a `.py` file even though no UI, runtime, or
inheritance code changes).

That increment has a hard prerequisite the repository cannot satisfy on its own:
**which surface becomes the new default is an owner decision.** README lines
51-68 and all three launcher comments state that neither v2 nor v3 is
independently hardware-verified. Naming a successor is therefore an owner call,
not something this assessment can make.

## 1. V1's current actual usage

V1 is still directly operator-facing, in executable code and in documentation:

| Evidence | What it currently says or does |
| --- | --- |
| `launch_gui.bat:23` | The unversioned Windows launcher runs `python -m thermo_acoustic.qt_ui` directly. |
| `tools/run_ui.py:12-16` | The unversioned developer launcher imports and calls `qt_ui.main`. |
| `src/thermo_acoustic/qt_ui.py:5261-5275` | `main()` builds and shows `MainWindow`; its own comment calls this "the day-to-day application". |
| `README.md:12` | `python tools\run_ui.py` is the first entry under "Useful Commands". |
| `README.md:30-38` | `launch_gui.bat` "does the same thing as `python tools\run_ui.py`"; v1 is "the default operator entry point". |
| `README.md:51-68` | V2 is "**not the default launch target**"; v3's acceptance "does not make v3 the default UI"; "V1 remains the default operator UI". |
| `README.md:115-117` | The launcher table lists v1 as "default operator UI". |
| `docs/current_workflow_audit.md:78-96` | V1 "is the default operator UI and owns the normal UI-to-Application path"; "V1 remains the default". |
| `docs/HANDOVER.md:49-51` | Historical handover snapshot calls `tools/run_ui.py` the PySide6 launcher and `qt_ui.py` the main UI. Its opening banner explicitly says it is not current runtime evidence, so it is context only, not part of the live-state proof above. |
| `tools/check_environment.py:2,54` | Describes the production app as "launch_gui.bat -> qt_ui.py". |
| `launch_gui_v2.bat:4-6`, `launch_gui_v3.bat:4-8`, `tools/run_ui_v3.py:1-6` | The *versioned* launchers actively point operators back at v1 as the validated day-to-day path. |

Calling v1 "internal-only" today would contradict both executable and documented
repository state in nine places.

## 2. V1-specific presentation vs. the already-shared base

The split already exists inside `qt_ui.py`, at the method level, and it is
cleaner than the file layout suggests:

- **`_build_state()` (`qt_ui.py:731-1681`, 951 lines including its boundary docstring)** constructs every field
  widget and every piece of run state. It is **not overridden by v2 or v3** --
  both inherit it verbatim via `super().__init__()` and then place the same
  widget objects into their own layouts. This is the real shared base.
- **`_build_layout()` (`qt_ui.py:1683-1766`, 84 lines excluding its boundary docstring)** is v1's own
  presentation: the four-button top row, the `Status` log placement, the seven
  tabs, and the side error panel. V2 replaces it (`qt_ui_v2.py:350-358`); v3
  replaces it again (`qt_ui_v3.py:223-261`). Neither calls
  `super()._build_layout()`.

### Genuinely v1-specific presentation (retired with v1's launch role)

- `MainWindow._build_layout()` itself and its tab composition
  (Initialization / WFG / MSO / Pump&Valve / Camera / Experiment / Z-Scan).
- V1's standalone `main()` and its window title/geometry (`qt_ui.py:641-644`,
  `qt_ui.py:5261-5275`).
- V1's own `Abort` push button `self.stop_series_button` (`qt_ui.py:1692`) --
  verified at runtime as **absent** from both v2 and v3 windows, which use v2's
  menu action instead. Note that `qt_ui.py` contains **no `QMenuBar` at all**;
  the menu-based Abort is v2's own (`qt_ui_v2.py:361-373`), not something
  inherited from v1.
- V1-only tab-composition builders: `_init_tab()`, `_experiment_tab()` (with its
  `_ad_settings_group()` / `_add_experiment_channel_sections()` /
  `_experiment_settings_column()` / `_experiment_numbers_group()` helpers),
  `_error_panel()`, and the Initialization-tab groups `_instrument_group()` /
  `_simulation_group()`. V2 and v3 build their own equivalents (an
  initialization *dialog*, their own experiment setup tabs, their own
  global-status panel).

### Base presentation builders that live in `qt_ui.py` but are already shared

V2's manual-panel dispatch maps four of v1's tab builders directly
(`qt_ui_v2.py:306-320`): `MSO -> _mso_tab`, `PumpValve -> _pump_tab`,
`Camera -> _camera_tab`, `ZScan -> _zscan_tab`, plus a v2 wrapper that reparents
v1's `_wfg_tab()` whole (`qt_ui_v2.py:839-855`). V3 overrides `_mso_tab` (with
`super()`), fully rewrites `_pump_tab`, `_camera_tab`, and `_zscan_tab` (without
`super()`), and still inherits v2's WFG wrapper.

These methods are therefore **shared implementation that happens to live in the
v1 file**. Their widget identities are a live contract: settings save/load and
every action binding depend on them.

### Shared base behavior that must not be treated as disposable v1 UI

`MainWindow` defines **134 methods** in its class body. V2 overrides exactly
**7** of them (`__init__`, `_build_layout`, `_start_initialize`,
`_initialize_system`, `_handle_worker_progress`, `_refresh_status`,
`_refresh_step_breadcrumb`). V3 overrides **10** v1-defined methods and **10**
v2-defined methods. Everything else in both later surfaces resolves through
`MainWindow`, including:

- shared field-widget and run-state construction (`_build_state()`), and the
  attribute names v2/v3 reparent;
- settings save/load (`_settings_dict()` 245 lines, `_load_settings()` 288 lines);
- worker dispatch, timeout, completion, and **visible error reporting**
  (`_run_action()`, `_handle_worker_finished()`, `_append_error_entry()`);
- initialization, shutdown, status history, cleanup interaction;
- manual hardware action callbacks and typed configuration builders;
- experiment construction, ordinary and TEC series execution, progress events,
  graceful-stop semantics (`_abort()`), and result handling;
- camera preview and Z-scan controller behavior;
- tooltip/focus-wheel infrastructure and shared widget wrappers.

## 3. Recent features: where their boundaries actually sit

### Elapsed time / estimated time remaining (added in `66016bd`)

Shared-base behavior, **not** a v1-only display feature:

- programmed-duration estimator: `qt_ui.py:85-132`;
- timing state and the 250 ms refresh timer: `qt_ui.py:669-679`;
- label *factories* `_elapsed_time_label()` / `_time_left_label()`:
  `qt_ui.py:1845-1860`;
- series progress emission: `qt_ui.py:4113-4303`;
- progress handling and measured-repeat refinement: `qt_ui.py:4507-4530`;
- live refresh: `qt_ui.py:4590-4605`.

Only *placement and caption text* differ per surface: v1 lays the labels out in
its Experiment tab (`qt_ui.py:2964-2967`), v2 places them in its Status/Progress
group (`qt_ui_v2.py:671-674`), and v3 only renames the inherited captions
(`qt_ui_v3.py:683-701`). Retiring v1's label placement must leave the base
timing state and events intact.

### Repeats relocation (v3, `085c06a`)

`self.exp_repeats` is created by v1's `_build_state()`. V1 places it in
`_experiment_numbers_group()` (`qt_ui.py:3156-3164`); v2 places the same object in its
acquisition group (`qt_ui_v2.py:796`); v3 **reparents that same widget instance**
out of v2's grid into its own run-control row (`qt_ui_v3.py:723-736`), raising
`RuntimeError` if the inherited grid shape is not what it expects.

This is presentation only -- but it means v3 is coupled to v2's *layout
structure*, not merely to the widget. Any future move of repeat semantics, or
regrouping of that form, is a cross-surface change.

### Safety controls (v3 Recovery sub-tab and graceful-stop button, `2c0ffc6`)

Both are presentation affordances over inherited paths. The confirmation dialog,
the Qmix fault gate, `_abort()`, the between-repeat stop check, worker failure
display, and the menu action all live in `qt_ui.py`, `qt_ui_v2.py`,
`application.py`, `instruments.py`, and `qmix_backend.py`. These are
cross-surface safety behavior and cannot be classified as removable v1
presentation. (Independently verified -- see this task's Part A review.)

**Structural risk worth recording here:** because v3's `_pump_tab()`,
`_camera_tab()`, and `_zscan_tab()` rewrite v1's builders *without* calling
`super()`, an affordance present in v1 and v2 can silently disappear from v3.
This already happened once: at `8433ba0` (the commit that formally adopted v3),
v3's rebuilt Pump&Valve panel had **no manual Qmix fault-clear control at all**,
even though v1 and v2 both did; `2c0ffc6` restored it. At `085c06a` there is full
parity again -- verified by comparing, across v2 and v3, both the set of
inherited field widgets placed in each manual panel (identical for all five
panels) and the set of actions their buttons dispatch (identical except for valve
status wording and one extra v3 "stop capture" button).

## 4. Smallest possible first increment

**Prerequisite (owner decision, not a code question):** name the successor
surface and complete whatever real-hardware/operator acceptance it needs.
Repository evidence does not currently justify silently choosing v2 or v3.

Once that is settled, one coordinated change reduces v1's role as a *directly
launched* interface without touching the inheritance chain and without moving any
code between files:

1. Point `launch_gui.bat:23` and `tools/run_ui.py:12-16` at the approved
   surface's `main()`.
2. Update the wording that currently names v1 as the default: `README.md`
   (lines 12, 30-38, 37-38, 51-68, 115-117),
   `docs/current_workflow_audit.md:78-96`,
   `tools/check_environment.py:2,54`, and the "launch_gui.bat remains the
   validated day-to-day v1 UI" comments in `launch_gui_v2.bat:4-6` and
   `launch_gui_v3.bat:4-8`.
3. Stop advertising `python -m thermo_acoustic.qt_ui` as an operator command.
   Keep `qt_ui.main()` in place as an undocumented developer/compatibility entry
   point during the migration -- deleting it is a later increment.
4. Leave `launch_gui_v2.bat`, `launch_gui_v3.bat`, `tools/run_ui_v2.py`, and
   `tools/run_ui_v3.py` untouched as explicit versioned alternatives.

**Is this a code change?** Almost entirely no. `MainWindow`, `_build_state()`,
`_build_layout()`, every widget, the runtime, the hardware paths, and
`MainWindowV3 -> MainWindowV2 -> MainWindow` are all unchanged. The single
unavoidable `.py` edit is `tools/run_ui.py`, which *is* a launcher -- it exists
only to call `main()` -- so redirecting it cannot be done in documentation alone.
No test asserts that v1 is the default launch target, so no test changes are
implied.

## 5. Longer-term sequence (explicitly not for this pass)

Ordered by increasing risk. The ownership note on each step is the point: from
step 1 onward every step is cross-owned.

1. **Freeze and characterize the inherited contract.** Cross-surface tests for
   required widget attributes, action callbacks, progress event kinds, settings
   keys, recovery, abort, and error propagation. *Needs v3-owner (Codex)
   agreement on what the contract is -- v3 is the surface most exposed to it,
   since it reparents inherited widgets and depends on inherited grid shapes.*
2. **Separate pure helpers first.** Move only independently testable timing,
   formatting, and typed parameter-adapter helpers out of `qt_ui.py`, keeping
   compatibility imports. *Needs v3-owner review for anything the v3 timing and
   relationship displays consume.*
3. **Separate controller/lifecycle behavior.** A shared controller or mixin for
   workers, shutdown, progress, experiment series, settings, and safety actions.
   High risk: it changes attribution boundaries around working,
   hardware-verified code, and should wait for the relevant real-hardware
   verification. *Cross-owned.*
4. **Introduce a true shared window base.** Only after step 1's contract tests
   exist: create an explicitly named shared base and leave a thin v1
   presentation subclass. Migrate v2 and v3 one at a time; never change the full
   MRO in one commit. *Cross-owned; v3 must be migrated by its owner.*
5. **Extract or replace inherited panel builders.** Decide panel by panel whether
   WFG/MSO/Pump/Camera/Z-Scan belongs in a shared component or in each surface.
   *Needs v3-owner coordination for every panel v3 overrides or reparents
   (`_mso_tab`, `_pump_tab`, `_camera_tab`, `_zscan_tab`, `_wfg_channel_group`),
   and v2-owner coordination for every inherited manual dialog.*
6. **Retire the v1 presentation.** Remove `main()` and the v1-only tab
   composition only once neither successor depends on any v1 presentation method
   and the rollback requirement has been explicitly resolved by the owner.

Any change to `MainWindow` method signatures, field attribute names, settings
keys, progress event kinds, action callbacks, manual-panel builders, or
inheritance order requires v3-owner review in addition to v2/shared-layer review.
