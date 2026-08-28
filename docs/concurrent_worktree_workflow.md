# Concurrent Agent Worktrees

Use a separate worktree when two coding tasks will genuinely overlap in time.
Do not require one for a read-only check or a single sequential edit.

1. Record the shared base with `git rev-parse HEAD` and ensure the owner knows
   about any dirty state in the primary checkout.
2. Create a task branch and worktree, for example:
   `git worktree add ..\thermo-task -b codex/<task-name> <base-hash>`.
3. Keep each agent in its assigned worktree. Do not share or copy a dirty
   working tree between tasks.
4. Before integration, review each branch's complete diff and test evidence.
5. Merge, cherry-pick, or reconcile deliberately in the owner-selected target;
   do not silently retain duplicate fixes.
6. Remove the worktree only after its branch and evidence are no longer needed.

Hardware access is a separate shared physical resource: worktree isolation does
not authorize simultaneous hardware clients or broaden an action's scope.
