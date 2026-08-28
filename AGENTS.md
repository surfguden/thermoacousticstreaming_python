# Repository Working Contract

This file contains durable working boundaries. Current milestone, UI-role, CI,
and hardware state belongs in `docs/project_control.md`; detailed unresolved
evidence belongs in `docs/known_open_items.md` and the hardware truth records.

## Authority And Conflict Resolution

- Hardware and operator safety outrank parity, convenience, and presentation.
- Act only within explicit authorization, and preserve user work and retained
  evidence.
- Current repository state, tests, CI, and runtime evidence establish factual
  claims. The current user request establishes the desired outcome and action
  authorization.
- Preserve established LabVIEW/source parity unless it conflicts with safety,
  current evidence, or an explicit owner decision; label inference. Usability
  follows correctness and safety. If no clearly safe interpretation resolves a
  conflict among task intent, evidence, safety, and these rules, stop and report
  it.

## Scope And Change-Surface Discipline

- Inspect fresh state and verify in proportion to risk. Local documentation,
  isolated tests, and narrow helpers need local evidence; shared runtime and
  safety behavior need relevant consumers and tests; architecture cutovers need
  a clean checkpoint, broad equivalence/regression evidence, and a rollback
  boundary. Use the repository state, hygiene, and CI mechanisms instead of
  duplicating their inventories here.
- For shared runtime, safety capability, or shared UI-builder changes, run
  `tools/audit_change_surface.py` and interpret its scoped consumers, overrides,
  and tests. Do not require a repository-wide audit for an unrelated local edit.

## Hardware And Evidence Integrity

- Do not issue unrequested motion, output, valve, fault-clear, target, or
  persistence writes. Stop at an unsafe or physically ambiguous live boundary.
- Action-capable probes are manual-only, explicitly gated, located under
  `hardware_tests/`, and excluded from automated tests and CI.
- Use the repository's current runtime-truth/evidence model. Do not represent
  cached, software, or protocol evidence as fresh or physical evidence; keep
  unresolved semantics explicit, and preserve retained evidence rather than
  replacing it with test output.
- Passive UI rendering must not cause hardware I/O. Explicit operator refresh
  or action may use established shared hardware paths within its authorization.

## Validation And Reporting

- Automated tests and CI must not access real hardware. When claiming
  validation, report exact commands, selection scope, and results. For hardware
  work, report every device accessed and action issued, including none.

## Git And Workspace Integrity

- Do not stage, commit, push, discard, or rewrite work without explicit
  authorization. Preserve unrelated dirty-tree changes and do not delete
  ambiguous historical or hardware evidence merely because it looks generated.
- For genuinely concurrent overlapping coding work, follow
  `docs/concurrent_worktree_workflow.md`; it is not required for read-only or
  sequential local work.
