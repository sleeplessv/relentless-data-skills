# orchestrator-mode

Coordinate requested work through subagents while keeping detailed findings in worker
artifacts. Scoped delegation applies to the named tasks; explicit orchestrator mode continues
until the user changes it. The main thread loads relevant skills, dispatches work, handles
decisions, and reports outcomes.

The workflow uses active tool schemas, bounded parallel waves, compact handoffs, and evidence
from the actual artifact. Parallel writers use isolated worktrees with pinned base commits.
Cleanup requires recorded ownership and preservation evidence. Detailed rules live in
[SKILL.md](SKILL.md), with conditional nesting and worktree procedures in
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
