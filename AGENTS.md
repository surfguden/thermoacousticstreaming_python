# Repository Working Contract

## Priorities

1. Preserve LabVIEW/source parity where it is established; label inference.
2. Protect hardware and the operator.
3. Report evidence at its actual strength.
4. Improve usability only after correctness and safety.

## Start From Repository State

- Read branch, HEAD, upstream, `git status`, and the relevant files fresh.
- Repository state overrides conversation, prompt, or session memory.
- Verify tracking and launcher state; do not assume it from historical notes.

## UI Boundaries

- v1 (`qt_ui.py`) is the default operator UI.
- v2 (`qt_ui_v2.py`) is the rollback/reference transitional UI.
- v3 (`qt_ui_v3.py`) is tracked, opt-in repository content.
- All three share `Application` and hardware backends. Presentation may differ;
  safety-relevant capabilities and shared-builder changes need a cross-UI audit.
- Before changing a shared symbol, inspect all uses, subclasses, overrides, and
  tests. An override that does not call `super()` will not inherit later fixes.

## Hardware And Evidence

- Do not issue unrequested motion, output, valve, fault-clear, target, or
  persistence writes. Stop at an unsafe or physically ambiguous boundary.
- Manual hardware probes belong in `hardware_tests/`, outside ordinary pytest,
  with explicit action gates where they can change hardware state.
- Protocol confirmation is not physical confirmation.
- Use the runtime evidence dimensions consistently:
  requested/applied/observed/derived; fresh/cached/unknown; and
  software/protocol/physical/unverified.
- A UI may render retained state but must not query hardware merely to render.

## Testing And Completion

- `tests/` is offline/simulated coverage. Real-hardware CI is forbidden.
- Report the exact tests run, their selection scope, and their results.
- Report every hardware device actually accessed and every action issued.
- Keep unresolved physical or semantic questions explicitly unresolved.
- Preserve retained hardware evidence; do not replace it with test output.

## Git And Concurrency

- Do not stage, commit, push, discard, or rewrite work unless explicitly asked.
- Generated caches and runtime output are not source. Do not track them or
  delete ambiguous evidence merely because it looks generated.
- Preserve unrelated dirty-tree changes. Parallel coding tasks should use
  separate branches/worktrees when practical and record their common base HEAD.
