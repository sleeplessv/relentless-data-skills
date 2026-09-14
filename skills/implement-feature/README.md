# implement-feature

Implement a selected set of feature tickets as one PR. The main thread coordinates through
`orchestrator-mode`; each ticket worker follows `implement-ticket` in an isolated worktree.
Spec-only runs check the whole spec; explicit ticket selection controls scope when provided.

Completed tickets merge into an integration branch as workers return. Verified, preserved
integration unlocks dependants while unrelated tickets continue from their own pinned bases.
Original baseline failures and decisions survive resume in a durable run record. Failed WIP
remains recoverable. A draft PR opens once verified work provides a publishable diff. Integrated
checks, independent review, and an executed verification plan precede readiness. The agent
never merges the feature PR.

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
