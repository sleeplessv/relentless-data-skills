# orchestrator-mode

Coordinate requested work through subagents while keeping detailed findings in worker
artifacts. Scoped delegation applies to the named tasks; explicit orchestrator mode continues
until the user changes it. In that mode the main thread only dispatches, plans, loads skills,
and talks to the user, and it passes worker artifacts on by path.

Each worker runs on a model class: strong for work that turns on judgement, standard for work
a recorded procedure settles, and never above the session's own. A task whose result fails its
check moves up a class. Every workflow step ends on a completion criterion. Every follow-up,
verification, or new phase goes to a fresh worker briefed by artifact path, never a resumed
one, and writers record their reasons and rejected approaches so that worker can take the change over. Handoffs assume the worker starts with no
conversation context, quote prior findings, and name one shared run directory. Decisions go
to a dated, append-only decision list in that directory, so they survive a compaction. Workers
return environment friction (a missing check, information out of reach, a workaround taken)
and the report lists it as proposed follow-ups. Parallel writers
use isolated worktrees with pinned base commits, and cleanup requires recorded ownership and
preservation evidence. The report step saves reusable research to the repo's `docs/research/`
rather than only the session's run directory, with claims about code dated and tied to a
commit, and offers worktree and branch cleanup once the
run's PRs merge. A run that promotes a version lists the checks the promotion requires,
gives each to a worker that can run it where it must pass, and promotes once every check
passes on that version. Core rules live in [SKILL.md](SKILL.md); nesting, parallel writes,
promotion checks, and harness limits live in
[references/reference.md](references/reference.md).

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/orchestrator-mode
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install orchestrator-mode@relentless-data-skills
```

## Validation

Repository CI checks skill frontmatter and line budgets with `scripts/lint_skill.py`,
and registry consistency with `scripts/sync_registry.py --check`.
