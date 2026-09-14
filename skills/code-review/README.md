# code-review

Review a branch, pull request, or working-tree change against two independent axes.
The Standards review checks the repository's documented rules and a fixed Fowler smell
baseline. The Spec review checks the requirements that authorized the change. Parallel
subagents report each axis separately so one result cannot hide the other.

The caller supplies the fixed comparison point. It can also supply an immutable review head
and an authoritative set of scope files, ticket snapshots, or fetched issue contents. Without
explicit scope sources, the skill discovers one originating spec from commit references or
repository files.

[SKILL.md](SKILL.md) defines the workflow. [Codex UI metadata](agents/openai.yaml) preserves
the installed skill's display name and short description.

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/code-review
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install code-review@relentless-data-skills
```

## Validation

Repository CI checks skill frontmatter and line budgets with `scripts/lint_skill.py`,
and registry consistency with `scripts/sync_registry.py --check`.
