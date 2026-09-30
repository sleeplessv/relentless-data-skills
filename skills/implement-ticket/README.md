# implement-ticket

Take a GitHub ticket through implementation, applicable checks, and a ready-for-review PR.
The workflow can select the lowest-numbered eligible ready ticket, or use an explicit number.
It preserves unrelated work, checks ownership before claiming, and records the base and PR
target explicitly. Failed work remains recoverable, including when a push fails.

Tests and runtime or artifact checks provide completion evidence. Every nonempty solo change
receives independent review against its ticket before the PR becomes ready. Trivial changes
that preserve behavior can use one reviewer with the loaded `code-review` prompts and separate
Standards and Spec reports. Behavioral changes or uncertainty require both parallel reviewers.
Follow-up review covers fixes, their consequences, and new evidence. Optional preferences can
receive a reasoned disposition without another implementation cycle.

A feature-dispatched worker uses its own pinned dispatch base, reuses the recorded original
baseline, and returns criterion evidence and preservation state. It performs self-review;
the coordinator owns independent feature review, PRs, and issue lifecycle actions.

The installed `pr` skill supplies Summary, Evidence, and Merge Danger for draft and final PR
bodies. `technical-writing` governs authored docs, commit messages, issue text, and PR prose.
`unslop` edits all authored prose, including handoffs, progress updates, and final reports.

[SKILL.md](SKILL.md) is the workflow. [Auto-pick](references/auto-pick.md) is loaded only for
selection, and [Orchestrated dispatch](references/orchestrated.md) only for feature workers.
Legacy `feat/ticket-*` and `feat/issue-*` branches remain recognizable; new branches follow
the current environment's naming convention.

## Install

For feature runs, install and update this skill with `implement-feature` from the same repository
revision. Solo ticket use needs only this skill and its companions. Follow the
[implementation workflow update guidance](../../README.md#implementation-workflow-updates)
for the compatible pair and the [installation methods](../../README.md#install).

Install upstream `code-review` and `pr` for final review and PR publication using the
[companion skills command](../../README.md#matt-pococks-engineering-skills). Setup checks
dependencies before implementation and reports any missing skills. The workflow invokes
these installed skills without copying or modifying them.

Install `technical-writing` and `unslop` with the [Cursor pstack command](../../README.md#cursors-pstack).
Setup resolves their installed paths and shares them with workers. The
[writing rule](references/setup.md#writing) covers reading these skills as references when
automatic invocation is disabled and continuing with a concise fallback if either is missing.

## Validation

Repository CI checks skill frontmatter and line budgets with `scripts/lint_skill.py`,
and registry consistency with `scripts/sync_registry.py --check`.
