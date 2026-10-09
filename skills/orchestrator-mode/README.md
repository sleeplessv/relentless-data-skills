# orchestrator-mode

Coordinate requested work through subagents while keeping detailed findings in worker
artifacts. Scoped delegation applies to the named tasks; explicit orchestrator mode continues
until the user changes it. In that mode the main thread only dispatches, plans, loads skills,
and talks to the user, and it passes worker artifacts on by path.

Every workflow step ends on a completion criterion. Handoffs assume the worker starts with no
conversation context, quote prior findings, and name one shared run directory. Parallel writers
use isolated worktrees with pinned base commits, and cleanup requires recorded ownership and
preservation evidence. The report step saves reusable research to the repo's `docs/research/`
rather than only the session's run directory, and offers worktree and branch cleanup once the
run's PRs merge. Core rules live in [SKILL.md](SKILL.md); nesting, parallel writes, and
harness limits live in [references/reference.md](references/reference.md).

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
