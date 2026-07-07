# implement-feature

The **`implement-feature`** agent skill: implement a whole feature — a PRD plus the
issues it was broken into (via `to-prd` → `to-issues`) — as **one PR**. The main
thread runs in `orchestrator-mode`, subagents implement each issue via
`implement-issue`'s orchestrated-dispatch contract, and everything converges on a
single integration branch pointing at `main`.

It is **user-invoked only** (`disable-model-invocation: true`): you always initiate
a feature run yourself, so it pays zero always-on context load.

## What it does

- **Work-set resolution** — accepts a PRD number, an issue list/range, or both. PRD
  alone → discovers its open sub-issues; issues alone → resolves the parent PRD for
  context; both → the explicit list wins. The PRD is always context, never a work
  item. The resolved work-set is announced before any branch is created; closed
  issues are silently skipped; a cycle in the blocking graph stops the run.
- **One integration branch** — `feat/prd-<N>-<slug>` off the default branch; all
  issue work merges here, and it is the only branch that ever points at `main`.
- **Topological waves** — every currently-unblocked issue is dispatched in parallel
  (worktree-isolated issue branches cut from the integration tip); a dedicated
  integration dispatch merges each wave, so blockers are always merged before their
  dependants start.
- **Gates at both levels** — each issue subagent keeps `implement-issue`'s
  types+tests loop and runtime smoke check; after the last wave, a separate
  verification dispatch (full suite + smoke) and a separate `code-review` dispatch
  (whole feature diff, PRD as intent) run on the unified integration branch, with
  fix dispatches looping until green.
- **One feature PR** — created ready-for-review only when everything is green, with
  Summary, Test plan, and `Closes #n` lines for every implemented issue **and the
  PRD**. Never merged by the agent.
- **Drain-around-failure + resume** — a three-strikes issue pushes its WIP branch
  and comments findings; its dependants are skipped, independent issues continue,
  and the run stops before the PR with a full report. Re-invoking resumes from the
  pushed integration branch.

## Conventions it expects

Issues produced by `to-issues`: parent PRD linked as a native sub-issue (`## Parent`
body fallback) and blockers as native blocking edges (`## Blocked by` fallback).
The PRD carries a `prd` label.

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

Install `orchestrator-mode`, `implement-issue`, and (ideally) `code-review`
alongside it — this skill composes them rather than restating them.

## Files

- `SKILL.md` — the full workflow: work-set resolution, integration branch, waves,
  integration gates, feature PR, stop conditions.

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget) — see the
[root README](../../README.md#maintenance--ci).
