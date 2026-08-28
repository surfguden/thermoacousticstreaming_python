# Qt / PySide Lifetime Investigation

Tracking ID: `TEST-QT-LIFETIME-001`.

## Bounded 2026-08-28 investigation

Known signatures were collected from the canonical open-item record and test
harness:

- `RuntimeError: Internal C++ object ... already deleted`, during widget walks
  or `MainWindow.closeEvent()` settings access;
- `SystemError: <class ...> returned NULL without setting an exception`, during
  construction, including native Qt widgets and `_TooltipIconWrapper`;
- an occasional full-suite hang, suspected but not proven to share the cause.

The relevant local wrapper is `_TooltipIconWrapper`, created without an initial
parent and then inserted into a `QFormLayout`; Qt reparents the wrapper and its
field/icon children when the layout adopts them. An inspected completed v2
window contained 675 QObject descendants, all reached through the normal Qt
parent tree. The wrapper class itself contains no custom destructor or lifetime
logic, and failures naming unrelated widget types make it an unlikely sole
cause.

The stronger local risk is v2's lazy manual-panel design. `MainWindowV2` first
creates v1 state widgets, but does not build WFG/MSO/Pump/Camera/Z-Scan panels
until requested. In one inspected fresh v2 window, 70 QObject-valued attributes
had no QObject parent while waiting for those panels. Python attributes retain
their wrappers, but whether this ownership pattern triggers the observed
offscreen Shiboken invalidation has not been established.

`QApplication` lifetime was also checked. After creating the application,
dropping the local Python variable, and forcing `gc.collect()`, both a weak
reference and `QApplication.instance()` remained live. The absence of an
explicit fixture-held application reference is therefore not the demonstrated
cause.

The existing teardown fixture explicitly calls `deleteLater()`, drains
`DeferredDelete`, processes events, and collects Python cycles. That is a
reasonable cleanup mechanism, but the construction-time signature can occur
before teardown and has historically exhausted all eight construction retries.

## Reproduction result

Ten fresh-process isolated invocations of
`test_v2_experiment_setup_tabs_has_four_task_oriented_tabs` under
`QT_QPA_PLATFORM=offscreen` all passed in this pass. This does not falsify the
larger retained dataset; it means this bounded attempt did not reproduce the
intermittent failure. No production `windows`-platform failure was observed or
claimed.

Current conclusion: **root cause unresolved**. Evidence favors an offscreen-
test/native-allocation or ownership interaction under full-window widget load.
Production relevance is unproven rather than impossible; the recorded absence
on the real Windows QPA platform argues against calling it a production defect.

## Closure plan

1. Build a standalone minimal stress case with the same pinned PySide version:
   compare many unparented, Python-retained controls against controls parented
   to a hidden owner widget.
2. Record `shiboken6.isValid()` for late-panel widgets before panel creation,
   after layout adoption, and during explicit deferred-delete teardown.
3. Run each case in fresh processes under both `offscreen` and `windows`, with
   fixed iteration counts and retained failure logs.
4. If a hidden owner eliminates the failure, test a narrow v2/v3 state-widget
   ownership change without modifying v1 or runtime behavior. Otherwise reduce
   the case for an upstream PySide/Qt report.
5. Remove retries or markers only after repeated complete-suite runs are
   deterministic; do not turn this family into skip/xfail behavior.
