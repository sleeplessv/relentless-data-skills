# implement-ticket

The **`implement-ticket`** agent skill: take a ticket (on GitHub: an issue) from
open → ticket branch → working code → green tests + runtime smoke check →
draft PR, with explicit stop conditions instead of improvising when something
is off.

> **Renamed from `implement-issue`.** The workflow steps are unchanged, but new
> branches are named `feat/ticket-<N>-<slug>` instead of `feat/issue-<N>-<slug>`
> (the legacy form is still recognised when detecting existing branches) — update
> any CI filters or branch tooling keyed on the old prefix. The vocabulary
> follows the spec/ticket terminology (a *spec* is broken into *tickets*; on
> GitHub or GitLab a ticket is stored as an issue). If you installed
> `implement-issue`, remove it and reinstall under the new name.

## What it does

- **Ticket selection** — works a given `#N`, or auto-picks the lowest-numbered open ticket labelled `ready-for-agent` (excluding specs, which carry a `spec` label — `prd` on older repos).
- **Claiming** — assigns itself and comments on the ticket so two agents never grab the same ticket.
- **Safe branching** — refuses to branch over a dirty working tree, honours repo naming conventions, and handles blocked-by chains (branches off the blocker's branch, or stops if the blocker hasn't started).
- **Task-aware implementation** — builds testable backend work in red-green-refactor tracer bullets (deferring to the `tdd` skill), and implements frontend, notebook, and exploratory data work directly where the test suite can't pin the behaviour.
- **Verification before "done"** — baselines the test suite before editing, then runs a type-check + test feedback loop until both are green, then a runtime smoke check with separate paths for servers (start, hit endpoint, read logs) and CLIs/libraries/pipelines (representative invocation, exit code 0).
- **PR hygiene** — draft PR within the first commits, repo PR template if present, a `code-review` pass on the diff, Summary + Test plan in the body, marks ready for review but never merges.
- **Stop conditions** — ambiguous criteria, scope labels, unstarted blockers, or three failed fix attempts → push the WIP branch, comment findings on the ticket, and hand back to the human.
- **Orchestrated dispatch** — a sanctioned override contract (`base_branch`, `open_pr: false`, blockers pre-merged) so a feature orchestrator like `implement-feature` can run it per-ticket against an integration branch without per-ticket PRs.

## Conventions it expects

The auto-pick path assumes a light triage vocabulary: `ready-for-agent` marks
tickets an agent may take, and `spec` (`prd` on older repos) marks spec
documents that should be broken into tickets first. Without those labels you
can still invoke it with an explicit ticket number.

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

It activates when you say "implement ticket #N", "implement issue #N", or
"grab the next ready ticket".

## Files

- `SKILL.md` — the full workflow: selection, claiming, branching, implementation, tests, smoke check, PR finalisation, stop conditions.
- `plugin.json` — Claude Code plugin manifest.

## Requirements

- `git` and the [`gh` CLI](https://cli.github.com/), authenticated against the target repo.
- Network access to GitHub — `gh` and `git fetch`/`pull`/`push` must run
  outside any sandboxed shell, or they fail with misleading DNS/connection
  errors.
