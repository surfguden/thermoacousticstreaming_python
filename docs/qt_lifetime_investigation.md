# Qt / PySide Lifetime Investigation

Tracking ID: `TEST-QT-LIFETIME-001`.

Classification: **PRE-EXISTING**, **UNRESOLVED**, and
**NONBLOCKING_FOLLOWUP**.

## Current post-CP2 reproduction surface

V2 was retired in CP2. Its tests and implementation are no longer current
executable reproduction or suspect surfaces. The retained direct construction
test is
`tests/test_qt_ui_v3.py::test_v3_constructs_on_first_attempt_without_retry`.
It runs the V3 window under `QT_QPA_PLATFORM=offscreen` without construction
retry, so a first-attempt construction failure remains visible.

`build_with_retry(attempts=8)` remains used by other UI tests and can mask a
first-attempt failure. A passing retried construction is therefore not evidence
that this intermittent issue did not occur.

## Known signatures

Known signatures were collected from the canonical open-item record and test
harness:

- `RuntimeError: Internal C++ object ... already deleted`, during widget walks
  or `MainWindow.closeEvent()` settings access;
- `SystemError: <class ...> returned NULL without setting an exception`, during
  construction, including native Qt widgets and `_TooltipIconWrapper`;
- an occasional full-suite hang, suspected but not proven to share the cause.

## Historical V2 observations (pre-retirement)

The following observations are retained as historical evidence only; they are
not current V2 reproduction instructions or current executable suspect
surfaces.

The local `_TooltipIconWrapper` was created without an initial parent and then
inserted into a `QFormLayout`; Qt reparented the wrapper and its field/icon
children when the layout adopted them. An inspected completed V2 window
contained 675 QObject descendants, all reached through the normal Qt parent
tree. The wrapper class itself contains no custom destructor or lifetime logic,
and failures naming unrelated widget types made it an unlikely sole cause.

V2's lazy manual-panel design first created V1 state widgets, but deferred
WFG/MSO/Pump/Camera/Z-Scan panels until requested. In one inspected fresh V2
window, 70 QObject-valued attributes had no QObject parent while waiting for
those panels. Python attributes retained their wrappers, but whether this
ownership pattern triggered the observed offscreen Shiboken invalidation was
not established.

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

Ten fresh-process isolated invocations of the former V2 setup-tabs test under
`QT_QPA_PLATFORM=offscreen` all passed in the 2026-08-28 investigation pass.
That historical result does not falsify the larger retained dataset; it means
that bounded attempt did not reproduce the intermittent failure. No production
`windows`-platform failure was observed or claimed.

Current conclusion: **root cause unresolved**. Evidence favors an
intermittent offscreen Qt/PySide construction or lifetime interaction under
full-window widget load. It is not established as a production-Windows defect;
production relevance is unproven rather than impossible.

## Closure plan

1. Build a standalone minimal stress case with the same pinned PySide version:
   compare many unparented, Python-retained controls against controls parented
   to a hidden owner widget.
2. Record `shiboken6.isValid()` for late-panel widgets before panel creation,
   after layout adoption, and during explicit deferred-delete teardown.
3. Run each case in fresh processes under both `offscreen` and `windows`, with
   fixed iteration counts and retained failure logs.
4. If a hidden owner eliminates the failure, test a narrow retained V1/V3
   state-widget ownership change without modifying runtime behavior. Otherwise
   reduce the case for an upstream PySide/Qt report.
5. Remove retries or markers only after repeated complete-suite runs are
   deterministic; do not turn this family into skip/xfail behavior.
