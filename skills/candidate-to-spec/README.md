# candidate-to-spec

Turn the deepening candidates that `improve-codebase-architecture` reports into approved specs and
`ready-for-agent` tickets, ready for `implement-feature`. The report's grilling step asks the
human seam, interface, and test questions; this skill has agents answer them instead and leaves
the human one checkpoint: approving a spec whose first section is written in plain English.

Per candidate, a designer worker walks the design tree and answers every node with evidence (a
code citation, a design-it-twice comparison, or a throwaway prototype), reading a per-project
`docs/architecture-policy.md` for taste questions and escalating only behaviour changes, ADR
conflicts, dependency changes, and scope widening. A separate reviewer worker, briefed as the
maintainer and carrying `ponytail-review`'s lean checklist, reviews the log once. The designer
revises or rejects with evidence; rejections become "Contested decisions" in the spec. The spec is
published at `needs-triage`, the user approves it, and the reviewer answers `to-tickets`' quiz
before the tickets publish as sub-issues.

A planning worker orders several candidates by dependency. Only candidates whose predecessors
have merged get specs in one run; re-running from the same report path after a merge re-validates
the rest against the current tree.

[SKILL.md](SKILL.md) holds the workflow; [references/workers.md](references/workers.md) the planning,
designer, reviewer, and revision contracts; [references/spec-and-tickets.md](references/spec-and-tickets.md)
the spec template, checkpoint, and ticket steps; [references/policy.md](references/policy.md) the
first-run policy interview.

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/candidate-to-spec
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install candidate-to-spec@relentless-data-skills
```

Install `orchestrator-mode` from this repository. Required companions from
[Matt Pocock's engineering skills](../../README.md#matt-pococks-engineering-skills):
`codebase-design`, `to-tickets`, and `improve-codebase-architecture` to produce the report.
Optional: `prototype`, `ponytail-review`, and the [Cursor pstack](../../README.md#cursors-pstack)
writing skills `technical-writing` and `unslop`. Setup reports a missing optional skill and
continues with the stated fallback.

## Validation

Repository CI checks skill frontmatter and line budgets with `scripts/lint_skill.py`,
and registry consistency with `scripts/sync_registry.py --check`.
