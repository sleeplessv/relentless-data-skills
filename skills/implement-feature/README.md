# implement-feature

The **`implement-feature`** agent skill: implement a whole feature — a spec plus the
tickets it was broken into (via `to-spec` → `to-tickets`) — as **one PR**. The main
thread runs in `orchestrator-mode`, subagents implement each ticket via
`implement-ticket`'s orchestrated-dispatch contract, and everything converges on a
single integration branch pointing at `main`.

It is **user-invoked only** (`disable-model-invocation: true`): you always initiate
a feature run yourself, so it pays zero always-on context load.

## What it does

- **Work-set resolution** — accepts a spec number, a ticket list/range, or both. Spec
  alone → discovers its open tickets (`## Parent` scan plus native sub-issues); tickets alone → resolves the parent spec for
  context; both → the explicit list wins. The spec is always context, never a work
  item. The resolved work-set is announced before any branch is created; closed
  tickets are silently skipped; a cycle in the blocking graph stops the run. A
  fresh work-set of exactly one ticket skips the orchestration entirely and hands
  off to `implement-ticket` directly.
- **One integration branch** — `feat/spec-<N>-<slug>` off the default branch; all
  ticket work merges here, and it is the only branch that ever points at `main`.
- **Topological waves** — every currently-unblocked ticket is dispatched in parallel
  (worktree-isolated ticket branches cut from the integration tip); a dedicated
  integration dispatch merges each wave, so blockers are always merged before their
  dependants start.
- **Gates at both levels** — each ticket subagent keeps `implement-ticket`'s
  types+tests loop and runtime smoke check, and each wave gets a targeted
  verification after its merge; after the last wave, a separate verification
  dispatch (full suite + smoke) and a separate `code-review` dispatch (whole
  feature diff, spec as intent) run on the unified integration branch, with fix
  dispatches looping until green or stopping after three strikes.
- **One feature PR** — created ready-for-review only when everything is green, with
  Summary, Test plan, and `Closes #n` lines for every implemented ticket — plus the
  spec, but only once every open ticket of the spec is covered. Never merged by the agent.
- **Drain-around-failure + resume** — a three-strikes ticket pushes its WIP branch
  and comments findings; its dependants are skipped, independent tickets continue,
  and the run verifies the integration branch, then stops before Review and the PR
  with a full report. Re-invoking resumes from the pushed integration branch
  (legacy `feat/prd-<N>-*` / `feat/issue-<N>-*` branch names are recognised too).

## Conventions it expects

Tickets produced by `to-tickets`: parent spec referenced in a `## Parent` body
section (native sub-issue linkage is used too where present, but current
`to-tickets` doesn't dependably create it; wayfinder's `Part of #<n>` fallback
is also recognised) and blockers as native blocking edges unioned with body
declarations (`## Blocked by` sections, inline `Blocked by #n`, `Depends on #n`
— either source alone may carry an edge).

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

Install `orchestrator-mode`, `implement-ticket`, and (ideally) `code-review`
alongside it — this skill composes them rather than restating them. It also
references `principle-laziness-protocol`, `unslop`, and `technical-writing` for
its code-frugality and prose standards; without them it falls back to the
one-line minimums baked into the skill.

## Files

- `SKILL.md` — the full workflow: work-set resolution, integration branch, waves,
  integration gates, feature PR, stop conditions.
- `references/reference.md` — per-dispatch contracts disclosed from the workflow:
  resolver commands and evidence rules, the wave-integration contract, the review
  spec-source override, the Verification plan authoring contract, the feature PR
  body contract. Dispatch prompts pass its absolute path and section anchor.

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget) — see the
[root README](../../README.md#maintenance--ci).
