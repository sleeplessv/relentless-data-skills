# implement-ticket

Take a GitHub ticket through implementation, applicable checks, and a ready-for-review PR.
The workflow can select the lowest-numbered eligible ready ticket, or use an explicit number.
It preserves unrelated work, checks ownership before claiming, and records the base and PR
target explicitly. Failed work remains recoverable, including when a push fails.

Tests and runtime or artifact checks provide completion evidence. A feature-dispatched worker
uses a pinned base and returns criterion evidence and preservation state without creating its
own PR or changing the issue lifecycle. The coordinator owns those actions.

[SKILL.md](SKILL.md) is the workflow. [Auto-pick](references/auto-pick.md) is loaded only for
selection, and [Orchestrated dispatch](references/orchestrated.md) only for feature workers.
Legacy `feat/ticket-*` and `feat/issue-*` branches remain recognizable; new branches follow
the current environment's naming convention.

## Install

See the [repo root README](../../README.md) for the general install patterns
(`npx skills`, Claude Code plugin, manual clone). For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/implement-ticket
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install implement-ticket@relentless-data-skills
```

## Validation

Repository CI checks skill frontmatter and line budgets with `scripts/lint_skill.py`,
and registry consistency with `scripts/sync_registry.py --check`.
