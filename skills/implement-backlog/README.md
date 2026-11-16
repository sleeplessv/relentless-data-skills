# implement-backlog

Start a chief-of-staff session over a ticket backlog. The main thread triages, picks what
runs next, and carries questions to the user. Each ticket goes to one **ticket owner**: a
subagent that coordinates a whole solo `implement-ticket` run for that ticket in its own
thread, merges the PR, and reports once in at most 12 lines.

The skill exists because a chief of staff that reads `implement-ticket` itself becomes the
coordinator of every ticket. It then dispatches each implementing worker, reviewer, and
verifier from the main thread, and their reports fill the context that the session needs for
the backlog as a whole.

## Use

```text
/implement-backlog
/implement-backlog 131 132 125
/implement-backlog clear the accessibility tickets, stop at ready
```

With no argument, the goal is to triage and implement the repository's open tickets. Ticket
numbers set the work-set. Any other text is the goal.

The skill is user-only (`disable-model-invocation: true`). Invoking it grants each ticket
what `/implement-ticket` grants: claiming it, lifecycle comments, pushing its branch, and
opening and updating its PR. It also grants merging a PR whose change reverts cleanly, once
its closing verification has passed on the head being merged and CI is green. `stop at ready`
withholds the merge. A change that would not revert cleanly keeps a draft PR until you give
the go-ahead.

[SKILL.md](SKILL.md) is what the chief of staff follows.
[The ticket owner brief](references/ticket-owner.md) is what each owner reads; the chief of
staff sends its path with the ticket's facts.

## Install

Install this skill with `implement-ticket` and `orchestrator-mode` from the same repository
revision, using the [repository installation instructions](../../README.md#install):

```bash
npx skills add sleeplessv/relentless-data-skills -s implement-backlog -s implement-ticket -s orchestrator-mode
```

`chief-of-staff` is an upstream skill, with `retro`, `to-spec`, and `to-tickets` beside it
for the procedures it runs, and `triage` for the triage pass:

```bash
npx skills add mattpocock/skills -g -y -s chief-of-staff -s retro -s to-spec -s to-tickets -s triage
```

`implement-ticket`'s own companions are listed in [its README](../implement-ticket/README.md#install).
A missing `chief-of-staff` or `implement-ticket` stops the run at the start. A missing
`triage` skips the triage pass, and the run works the tickets already marked ready.

Owners dispatch their own workers, so the harness must let a subagent start subagents. Where
it cannot, the owner reports that before changing anything, and the chief of staff
coordinates that ticket from the main thread.

## Validation

Repository CI checks skill frontmatter and line budgets with `scripts/lint_skill.py`,
and registry consistency with `scripts/sync_registry.py --check`.
