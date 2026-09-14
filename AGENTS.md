# Working rules

- First priority: before creating, modifying, or deleting any file, tell the user
  what you intend to change.
- Stay within the requested scope. Preserve existing behavior unless a change is
  requested. Ask when requirements are unclear.
- Check Git status before editing and preserve unrelated work. Commit non-minor
  changes without asking, including only work from the current task. Leave minor
  edits uncommitted until grouped into a meaningful change. After a large commit
  or several minor changes accumulate, suggest pushing and ask permission first.
  Never discard work or rewrite history without explicit authorization.
- Read only the context needed for the task. Verify facts against current code
  and evidence; label assumptions.
- Only access hardware when explicitly authorized. Passive UI rendering,
  automated tests, and CI must not access hardware. Keep hardware probes
  manual-only and explicitly gated under `hardware_tests/`. Do not treat
  software success as proof of physical behavior.
- Keep experiment sequences, hardware control, and application behavior outside
  UI code. The UI displays state, collects input, and invokes application actions.
  Use clear controls and confirmations to prevent mistakes, but enforce safety
  and validity checks in application code too.
