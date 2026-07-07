---
name: implement-feature
argument-hint: "[prd#] [issue#...]"
disable-model-invocation: true
description: "Implement a whole feature as one PR: orchestrate subagent waves over a PRD's issues on a shared integration branch. Use when you have a PRD and/or its issues (from to-prd / to-issues) to implement end-to-end."
---

# Implement Feature

Take a PRD and its issues from open → integration branch → parallel issue branches →
integrated review + tests → **one feature PR** into the default branch.

Operate under the `orchestrator-mode` skill for the whole run — every git / gh /
file / test action below is a subagent dispatch. Per-issue work composes the
`implement-issue` skill via its **Orchestrated dispatch** contract.

## Vocabulary

- **Work-set** — the resolved list of issues this run will implement.
- **Integration branch** — `feat/prd-<N>-<slug>`, cut from the default branch; all issue work merges here. The main tree stays checked out on it for the whole run.
- **Issue branch** — `feat/issue-<N>-<slug>`, cut from the integration-branch tip.
- **Wave** — the currently-unblocked issues, dispatched in parallel.
- **Feature PR** — the single PR from integration branch to default branch.

## Rules

- **No em dashes (—) in anything published to git or GitHub** — use commas, colons, or parentheses.
- **Network `gh` / `git fetch|pull|push` run outside the sandbox** — every dispatch prompt says so.
- The PRD is context, never a work item.
- Dispatch prompts tell the subagent to invoke `implement-issue`; if subagents cannot load skills, paste its body verbatim into the prompt.
- **Every issue dispatch gets worktree isolation, even a one-issue wave** — deliberately stricter than orchestrator-mode's two-writer rule, so the main tree never leaves the integration branch.

## Workflow

### 0. Resolve the work-set

One read-only dispatch (general-purpose — it runs networked `gh`) gathers:

- **Args** — PRD number, issue list/range, or both. PRD-only → list its open sub-issues (native sub-issue API via `gh api`, `## Parent` body fallback). List-only → resolve the shared parent PRD for context. Both → the explicit list is the authoritative work-set.
- Closed issues: silently skip. PRD body + acceptance criteria: capture verbatim for later handoffs.
- Blocking edges between work-set issues (native dependency API, `## Blocked by` body fallback) → the dependency graph.
- The **feedback-loop commands** — install/setup, type-check, test, and run commands (same sources as `implement-issue` step 4) — for the dispatch handoffs and the step 3 gates.
- `git status --porcelain`; whether the integration branch exists (`feat/prd-<N>-*`, or the `feat/<slug>` a prior no-PRD run named — probe origin with `git ls-remote origin 'feat/*'`, not a fetch). If it does, the **resume state** per work-set issue: **merged** iff it carries a "merged into `<integration branch>`" comment, or a commit on `<default>..<integration branch>` matches `#<N>\b` or `issue-<N>` (a human may have fixed it by hand); any pushed `feat/issue-<N>-*` WIP branch.

Then, in the main thread:

- **Announce the work-set** (numbers + titles) and the wave plan before any branch is created.
- **Cycle in the graph → stop** and surface it.
- **Dirty tree → stop and ask** (stash / commit / abort).
- Existing integration branch → **resume**: merged issues leave the work-set; WIP branches go to their wave's dispatch as `resume_branch`.

Done when: work-set announced, graph acyclic, tree clean, resume state known.

### 1. Integration branch

Dispatch (git plumbing — inherits the parent model): `git switch <default> && git pull --ff-only`,
create `feat/prd-<N>-<slug>` (slug = kebab of the PRD title, ≤5 words, drop filler),
push with `-u origin`. No PRD in play → ask the user for a slug, use `feat/<slug>`.
On resume the branch exists: skip creation, switch to it, `git pull --ff-only`, and
push if the local branch is ahead of origin (a manual fix may be local-only).

Done when: the integration branch tips match on origin and in the main tree, and it is checked out.

### 2. Implement in waves

Repeat until the work-set drains:

1. **Wave** = every remaining issue whose blockers are all merged into the integration branch.
2. Dispatch the wave in parallel — one worktree-isolated coding subagent per issue
   (model per orchestrator-mode). Each prompt is a rich handoff: issue body verbatim,
   PRD excerpts, decisions so far, the step-0 feedback-loop commands (worktrees start
   without installed dependencies — install before baselining), and the
   `implement-issue` **Orchestrated dispatch** overrides:
   `base_branch: <integration branch>`, `open_pr: false`, blockers pre-merged,
   `resume_branch` when step 0 found a WIP branch for it.
3. **Integrate**: a dedicated dispatch merges the branches returned by the wave's
   *successful* dispatches into the integration branch (mechanical conflicts resolved,
   semantic ones escalated to one resolver dispatch, per orchestrator-mode), pushes it,
   comments "merged into `<integration branch>`" on each merged issue, then removes
   every returned `worktree_path` (failed ones too — their WIP is pushed), each
   worktree's harness auto-branch, and the merged branches. **On escalation the
   resolver inherits those duties** for what it merges; the orchestrator confirms the
   origin tip advanced before opening the next wave. If any conflict was resolved,
   run a targeted verification dispatch (the affected tests) before the next wave.
4. A failed issue (three strikes) keeps `implement-issue`'s stop behaviour — WIP
   branch pushed, findings commented — and returns `status: failed` with the WIP
   branch, `worktree_path`, and root cause. **Its dependants leave the work-set**;
   independent issues continue (drain-around-failure). Failed issues' WIP branches
   are never merged. `status: already_satisfied` → post its "merged into" comment
   and treat as merged.

Done when: every work-set issue is merged, or recorded as failed / skipped-as-downstream.

### 3. Integration gates

After the last wave, two separate dispatches by fresh subagents (no self-certification,
per orchestrator-mode):

1. **Verify** — the step-0 feedback-loop commands: full type-check + test suite + runtime smoke check on the integration branch.
2. **Review** — the `code-review` skill over `git diff <default>...<integration branch>`, with the PRD pasted in as the intent to review against.

Findings → sequential write-intent fix dispatches on the integration branch, then
re-verify; three strikes stops the run. On a partial work-set (anything failed or
skipped) run Verify so the pushed branch is known-green, skip Review and the PR, and stop.

Done when: Verify and Review are clean on the pushed integration branch (partial work-set: Verify clean, then stop).

### 4. Feature PR

One dispatch:

- Repo PR template if present; body carries a **Summary**, a **Test plan** (what the
  verification dispatch ran and observed), and rebuilt `Closes #<n>` lines: scan every
  issue from any run's work-set plus every open sub-issue of the PRD, and include each
  one covered by a "merged into" comment or a `#<N>\b` / `issue-<N>` commit — whichever
  run or human put it there. Add `Closes #<prd>` only when every open sub-issue is
  covered; otherwise comment progress on the PRD.
- Create it **ready-for-review** (not draft). Report the PR URL. Merging is the human's.

Done when: the PR URL is reported.

## Stop conditions

A strike-out never halts mid-wave: drain the independent issues (step 2.4), run step 3's
Verify, then stop before Review and the PR. Stop the same way when a semantic merge
conflict survives its one resolver dispatch.

When stopping, leave the integration branch pushed and report — superseding
orchestrator-mode's 1–3-sentence rule — what merged, what failed (root cause + WIP
branch names), what was skipped as downstream, and that re-invoking resumes from step 0.
