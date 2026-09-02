# V3 Information Architecture Closure

> **Historical pre-redesign closure.** The sidebar/top-strip/runtime-column
> organization described below was superseded by V3 checkpoint `9a899d7`, which
> introduced persistent instrument/run state and separate Experiment, Monitor,
> Manual & Service, and Diagnostics workspaces. Use
> [`project_control.md`](project_control.md) and current `qt_ui_v3.py` for the
> live operator model. This document remains evidence of the earlier bounded
> decision, not a current layout specification.

Milestone E is bounded presentation consolidation. No hardware access, planner
authority change, or experiment-semantics change occurred.

| Item | Disposition | Current evidence |
| --- | --- | --- |
| Review hierarchy | IMPLEMENTED | `47915d5` renders final shared findings as static validity, advisory/inactive, live-feasibility, and physical-unverified groups. It remains shadow presentation, not a Start gate. |
| Derived experiment plan / one-repeat timing plan | ALREADY_SATISFIED | The former renders the current `BuildResult`; the latter is explicitly requested timing presentation. Its end deltas and completion budget are presentation math, not a second execution plan or physical-timing claim. |
| DIO1/camera uncertainty | ALREADY_SATISFIED | The always-visible V3 uncertainty banner states Internal camera trigger and bench-unverified DIO1-to-exposure timing. |
| Flush sequencing | ALREADY_SATISFIED | Visible Fluidics text states P01 → dispense → P02 → wait and retains the bench-unverified routing qualifier. |
| Connection displays | NO_ACTION_WITH_EVIDENCE | Sidebar dots provide navigation-local state, the top strip provides at-a-glance status, and the runtime column provides detailed current status. All are projections of existing status state; none adds a connection source. |
| Frequency-program navigation | NO_ACTION_WITH_EVIDENCE | Current nested channel/FM/scan grouping preserves independent channel semantics and scan-versus-within-repeat FM distinction. No concrete workflow impairment supports choosing a materially different layout. |
| Camera Manual sequence nesting | NO_ACTION_WITH_EVIDENCE | No current operator-impact evidence supports flattening the existing Actions/Timing organization. |
| No-super / cosmetic findings | NO_ACTION_WITH_EVIDENCE | No shared-propagation regression was demonstrated; no mechanical `super()` change or cosmetic normalization is justified. |

The E exit criteria are satisfied without external vendor evidence: all choices
are repository-local presentation facts and retain existing hardware caveats.
