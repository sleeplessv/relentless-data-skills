# implement-feature

Implement a selected set of feature tickets as one PR. The main thread coordinates through
`orchestrator-mode`; each ticket worker follows `implement-ticket` in an isolated worktree.
Spec-only runs check the whole spec; explicit ticket selection controls scope when provided.

This is the local counterpart to Matt Pocock's `implement-spec`. Both schedule a task graph,
use isolated worktrees, and review the integrated result. This workflow retains GitHub issues
and one feature PR; upstream also supports trackers that close work without a PR.

Completed tickets merge into an integration branch as workers return. Verified, preserved
integration unlocks dependants while unrelated tickets continue from their own pinned bases.
Original baseline failures and decisions survive resume in a durable run record. Failed WIP
remains recoverable. A draft PR opens once verified work provides a publishable diff. Integrated
checks and independent review precede readiness. The agent never merges the feature PR.

[SKILL.md](SKILL.md) defines the workflow and [references/reference.md](references/reference.md)
holds setup, integration, review, and publication contracts. Install `orchestrator-mode` and
`implement-ticket` alongside it. The coordinator always runs both independent `code-review`
reviewers in parallel on the integrated feature; ticket workers perform self-review.
Follow-up review covers fixes, their consequences, and new evidence. Optional preferences can
receive a reasoned disposition without another implementation cycle.

The installed `pr` skill supplies Summary, Evidence, and Merge Danger.
`technical-writing` governs authored docs, commit messages, issue text, and PR prose.
`unslop` edits all authored prose, including worker handoffs, progress updates, and final reports.
Testing skills follow the user's and environment's requirements.

## Install

Install and update this skill with `implement-ticket` from the same repository
revision. Follow the [implementation workflow update guidance](../../README.md#implementation-workflow-updates)
for the compatible pair and the [installation methods](../../README.md#install).

Install upstream `code-review` and `pr` for final review and PR publication using the
[companion skills command](../../README.md#matt-pococks-engineering-skills). Setup checks
dependencies before dispatch and reports any missing skills. The workflow invokes
these installed skills without copying or modifying them. Upstream `implement-spec`
is a design reference, not a dependency.

Install `technical-writing` and `unslop` with the [Cursor pstack command](../../README.md#cursors-pstack).
Setup resolves their installed paths and passes them to workers. The
[shared writing rule](../implement-ticket/references/setup.md#writing) covers reading these skills
as references when automatic invocation is disabled and continuing with a concise fallback
if either is missing.

## Validation

Repository CI checks skill frontmatter and line budgets with `scripts/lint_skill.py`,
and registry consistency with `scripts/sync_registry.py --check`.
