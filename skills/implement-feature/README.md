# implement-feature

Implement a selected set of feature tickets as one PR. The main thread coordinates through
`orchestrator-mode`; each ticket worker follows `implement-ticket` in an isolated worktree.
Explicit ticket selection controls scope even when the parent spec contains more requirements.

Dependency waves merge into an integration branch. Each wave has an immutable base SHA;
original baseline failures and decisions survive resume in a durable run record. Failed WIP
remains recoverable. Verified integrations, an independent whole-feature review, and an executed
verification plan precede PR publication. The agent never merges the feature PR.

[SKILL.md](SKILL.md) defines the workflow and [references/reference.md](references/reference.md)
holds setup, integration, review, and publication contracts. Install `orchestrator-mode` and
`implement-ticket` alongside it. `code-review` supplies the review when available, with direct
independent standards and criteria reviews as the fallback. Prose and testing skills follow
the user's and environment's requirements.

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/implement-feature
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install implement-feature@relentless-data-skills
```

## Validation

Repository CI checks skill frontmatter and line budgets with `scripts/lint_skill.py`,
and registry consistency with `scripts/sync_registry.py --check`.
