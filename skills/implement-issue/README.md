# implement-issue

The **`implement-issue`** agent skill: take a GitHub issue from open →
feature branch → working code → green tests + runtime smoke check → draft PR,
with explicit stop conditions instead of improvising when something is off.

## What it does

- **Issue selection** — works a given `#N`, or auto-picks the lowest-numbered open issue labelled `ready-for-agent` (excluding PRDs, which carry a `prd` label).
- **Claiming** — assigns itself and comments on the issue so two agents never grab the same ticket.
- **Safe branching** — refuses to branch over a dirty working tree, honours repo naming conventions, and handles blocked-by chains (branches off the blocker's branch, or stops if the blocker hasn't started).
- **Verification before "done"** — baselines the test suite before editing, requires it green after, then runs a runtime smoke check with separate paths for servers (start, hit endpoint, read logs) and CLIs/libraries/pipelines (representative invocation, exit code 0).
- **PR hygiene** — draft PR within the first commits, repo PR template if present, Summary + Test plan in the body, marks ready for review but never merges.
- **Stop conditions** — ambiguous criteria, scope labels, unstarted blockers, or three failed fix attempts → push the WIP branch, comment findings on the issue, and hand back to the human.

## Conventions it expects

The auto-pick path assumes a light triage vocabulary: `ready-for-agent` marks
issues an agent may take, and `prd` marks spec documents that should be broken
into issues first. Without those labels you can still invoke it with an
explicit issue number.

## Install

See the [repo root README](../../README.md) for the general install patterns
(`npx skills`, Claude Code plugin, manual clone). For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/implement-issue
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install implement-issue@relentless-data-skills
```

It activates when you say "implement issue #N", "ship issue #N", or "grab the
next ready issue".

## Files

- `SKILL.md` — the full workflow: selection, claiming, branching, implementation, tests, smoke check, PR finalisation, stop conditions.
- `plugin.json` — Claude Code plugin manifest.

## Requirements

- `git` and the [`gh` CLI](https://cli.github.com/), authenticated against the target repo.
- Network access to GitHub — `gh` and `git fetch`/`pull`/`push` must run
  outside any sandboxed shell, or they fail with misleading DNS/connection
  errors.
