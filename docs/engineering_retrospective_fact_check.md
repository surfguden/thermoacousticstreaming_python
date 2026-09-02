# Engineering Retrospective Fact Check

> **Historical appendix.** This document records a point-in-time assessment.
> Use `project_control.md` for current project truth and
> `known_open_items.md` for the live unresolved/deferred registry.

The retrospective artifact itself was not present in the repository or the
2026-08-28 task attachment. This appendix evaluates the lessons and example
claims stated in that task against the current repository. It is not a rewrite
of the missing retrospective.

## Lessons

| Lesson | Classification | Current repository evidence |
| --- | --- | --- |
| Durable rules lived mainly in prompts/session history | CONFIRMED AND STILL RELEVANT | No repository `AGENTS.md` existed before this pass; rules were distributed across long documents and comments. |
| Repeated stale-state assumptions | CONFIRMED AND STILL RELEVANT | Several current documents explicitly warn that historical status is not live state; objective start-state reporting was still manual. |
| v1/v2/v3 ownership and tracking drift | PARTIALLY ADDRESSED | README and tracked launchers now describe v1 default, v2 reference, and v3 tracked opt-in; no automatic state report existed. |
| Shared-change/override omissions | CONFIRMED AND STILL RELEVANT | v3 contains method overrides that intentionally replace inherited builders, and boundary comments exist because later base changes do not propagate automatically. |
| Generated files accidentally entering tracking | PARTIALLY ADDRESSED | `.gitignore` covers Python/pytest caches and runtime outputs, but no tracked-file hygiene gate existed. Retained LabVIEW exports are evidence, not disposable output. |
| Parallel-agent dirty-tree collisions | CONFIRMED AND STILL RELEVANT | The current tree contains overlapping multi-session edits; no repository concurrency procedure existed. |
| Known regressions becoming background noise | PARTIALLY ADDRESSED | `known_open_items.md` and the informational `known_flaky` marker preserve visibility, but closure fields and automated gates were absent. |
| Qt/PySide lifetime failures handled mainly by reruns | CONFIRMED AND STILL RELEVANT | `tests/conftest.py` retries construction and forces deferred deletion; the documented family remains open and larger than the marked set. |
| No repeatable CI/merge gate | CONFIRMED AND STILL RELEVANT | No `.github/workflows` directory existed before this pass. |
| Evidence provenance must be explicit | ALREADY ADDRESSED | `runtime_truth.py`, the P0 evidence record, and canonical workflow docs distinguish requested/applied/observed/derived and software/protocol/physical evidence. Enforcement remains a review responsibility. |
| Automate semantic commit-message judgement | NOT SUITABLE FOR AUTOMATION | Whether a message truthfully represents scientific/hardware meaning requires review; mechanical diff/state facts can be automated. |

## Stale, Overstrong, Or Historical-Only Claims

- **“Functional parity complete across all six instruments” — overstrong.**
  The migration audit itself says the full experiment is not proven completely
  equivalent. Physical timing, valve routing, Qmix readiness/motion, and other
  hardware boundaries remain open.
- **“TEC verified on both channels” — historical-only unless qualified.**
  Historical controlled-write reports exist. The independent 2026-08-28 result
  is read-only communication on both channels; the new Static OFF and partial-
  failure paths are fake-tested only.
- **“v3 is untracked/local” — stale.** v3 source, launcher, runner, and test are
  currently tracked; v3 remains opt-in and not independently hardware-verified.
- **Session, commit, and test counts — UNVERIFIED and inherently dynamic.** No
  retrospective artifact was available to identify the claimed numbers, and
  repository state must be queried when a count matters.
- **“Qmix recovery solved the CAN problem” — overstrong.** Automatic init-time
  clear is an approved policy, but the 2026-08-28 baseline retained the fault
  flag in 3/3 no-motion trials. The CAN root cause and motion readiness remain
  unresolved.
- **A fixed count of v3 builder overrides — stale-prone.** The current AST
  audit reports 21 `MainWindowV3` methods overriding an inherited method, nine
  without a same-method `super()` call. This is a current mechanical count, not
  a permanent project fact; not every override is a panel builder.
