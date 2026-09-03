---
name: implement-feature
argument-hint: "[spec#] [ticket#...]"
disable-model-invocation: true
description: "Implement a whole feature as one PR: orchestrate subagent waves over a spec's tickets on a shared integration branch. Use when you have a spec (PRD) and/or its tickets (from to-spec / to-tickets) to implement end-to-end."
---

# Implement Feature

Take a spec and its tickets from open → integration branch → parallel ticket branches →
integrated review + tests → verification plan → **one feature PR** into the default branch.

Operate under the `orchestrator-mode` skill for the whole run. Every git / gh / file /
test action below is a subagent dispatch (its 1-3-sentence report rule yields to this
skill's per-wave and close-out reports). Per-ticket work composes the `implement-ticket`
skill via its **Orchestrated dispatch** contract.

## Vocabulary

- **Work-set**: the resolved list of tickets this run will implement.
- **Integration branch**: `feat/spec-<N>-<slug>`, cut from the default branch; all ticket work merges here. The main tree stays checked out on it for the whole run. (Legacy runs named it `feat/prd-<N>-<slug>`; treat that as equivalent.)
- **Ticket branch**: `feat/ticket-<N>-<slug>`, cut from the integration-branch tip. (Legacy: `feat/issue-<N>-<slug>`.)
- **Wave**: the currently-unblocked tickets, dispatched in parallel.
- **Handoff files**: `spec.md` (spec body and acceptance criteria verbatim) and `handoff.md` (spec number, work-set with criteria, feedback-loop commands, integration branch and baseline, a cumulative Decisions log; shape in the reference's Tree preparation) in the session scratchpad. Step 0 writes them; each integrate dispatch appends to the log. Long context travels by their absolute paths: the main thread never re-emits it into a prompt.
- **Baseline**: the integration tip SHA plus the pre-existing type and test failures step 0 recorded. The SHA advances with each wave; the failure list stays step 0's. Ticket dispatches inherit it instead of running the suite before editing.
- **Feature PR**: the single PR from integration branch to default branch.
- **Verification plan**: the human-facing walkthrough of the delivered feature (see `CONTEXT.md`), using the application and inspecting the data, not re-running tests. Authored after the gates, embedded in the feature PR body.

## Rules

- **Prose published to git or GitHub (the PR body, spec and ticket comments) meets the `technical-writing` and `unslop` skills' standard when they are installed; baked-in minimum either way: plain words, active voice, and no em dashes** (use commas, colons, or parentheses). Only the step 3 dispatch writes free prose: its prompt carries this rule and tells the subagent to invoke both skills itself (subagents may not have them loaded). Ticket dispatches write commit messages, a fixed claim comment, and on a stop a findings comment, and skip both skills per `implement-ticket`'s Orchestrated dispatch; the integrate dispatch's "merged into" comment is fixed text.
- **Network `gh` / `git fetch|pull|push`, and install commands, run outside the sandbox.** Every dispatch prompt says so.
- **Every dispatch prompt carries the session scratchpad's absolute path** (the handoff files' parent) and pastes the prior returns it depends on verbatim, per orchestrator-mode's handoff discipline.
- The spec is context, never a work item.
- **Implement the work-set at the scope its tickets ask for, as the smallest change that solves it.** Adjacent bugs, refactors, and cleanups get reported in the feature PR body, not fixed. Ticket dispatches inherit the frugality bar via `implement-ticket`; step 2 fix dispatch prompts carry it explicitly (the `principle-laziness-protocol` skill when installed): prefer deletion over addition and the smallest diff that fixes it.
- **One dispatch per ticket per wave.** No helper or double-check agents alongside it, none to re-read what a dispatch already returned. Only the dispatches steps 0-3 already prescribe (setup, integration, resolver, post-resolution tests, gates, fixes, plan + PR) run beside it.
- Dispatch prompts tell the subagent to invoke `implement-ticket`; if subagents cannot load skills, paste its body verbatim into the prompt. Per-dispatch contracts live in [references/reference.md](references/reference.md). A prompt that cites a contract or a handoff file carries its **absolute path** (plus the section anchor for a contract; subagents cannot resolve skill-relative links) and tells the subagent to read it first.
- **Every ticket dispatch gets worktree isolation, even a one-ticket wave.** This is deliberately stricter than orchestrator-mode Rule 7, so the main tree never leaves the integration branch. Use the delegation tool's native worktree isolation (orchestrator-mode reference, Tool Mapping); none available → stop and say so rather than sharing the main tree. The harness worktree may branch from the remote default branch rather than the integration tip (Claude Code does unless `worktree.baseRef` is `head`), which is why every ticket dispatch cuts its own branch from `base_branch` per `implement-ticket` and never commits to the harness branch. That pinned cut supersedes Parallel Writes step 3's `base_sha` check, so ticket returns carry no `base_sha`.

## Workflow

### 0. Resolve the work-set and prepare the tree

One dispatch (general-purpose, it runs networked `gh`; inherit the session model) follows [references/reference.md#work-set-resolution](references/reference.md#work-set-resolution), the exact commands and evidence rules, to gather:

- **Args**: spec number, ticket list/range, or both. Spec-only → list its open tickets (the anchored `## Parent` body scan unioned with native sub-issues, per the reference). List-only → resolve the shared parent spec for context. Both → the explicit list is the authoritative work-set, but a listed ticket whose `## Parent` names a different spec, or a list spanning two specs, is a stop-and-ask (likely a typo, and step 2 reviews against one spec).
- Closed tickets: skip, naming them. When a spec is in play, list **all** its open tickets whatever the args (`spec_open_tickets`; step 3 needs them to decide `Closes #<spec>`). Spec body + acceptance criteria, and each work-set ticket's title and criteria: captured verbatim for the handoff files.
- Blocking edges → the dependency graph: for **every** work-set ticket, the native dependency API unioned with the anchored body scan. Either source alone may carry an edge. An edge to an open issue outside the work-set → stop and ask (a resume-merged ticket of this feature counts as satisfied, not outside); to a closed one → ignore.
- The **feedback-loop commands**: install/setup, type-check, test, and run commands (sources per the reference), for the handoff file and the step 2 gates.
- `git status --porcelain`; the default branch; whether the integration branch exists under any accepted name (probed on origin per the reference); if it does, the **resume state** per work-set ticket, **merged** per the reference's merged-evidence rule, plus any pushed WIP ticket branch.

It then applies the gates below (every stop-and-ask in the list above is also a gate) and, unless one fires, **prepares the tree** per [references/reference.md#tree-preparation](references/reference.md#tree-preparation): cuts or resumes the integration branch and pushes it, installs dependencies, records the baseline, and writes the handoff files. It returns the reference's step 0 return contract: work-set, `skipped_closed`, `spec_open_tickets`, graph, resume state, default branch, integration branch and origin tip SHA, baseline, handoff paths, and the gate that fired, if any. Gates (a firing gate prepares nothing; the main thread surfaces it):

- **Work-set of one, no existing integration branch → do not orchestrate.** The main thread says so, hands the ticket to `implement-ticket` in a single dispatch on its solo defaults (own branch, own PR, no overrides), and stops: the machinery below only pays off across several tickets. On resume, orchestrate; that ticket belongs to the feature PR.
- **Work-set of zero, no integration branch → nothing to implement**; report and stop. (Zero with an existing branch is not a gate: the run is merged-but-ungated; prepare the tree, then go straight to step 2, then step 3.)
- **Cycle in the graph → stop** and surface it. **Dirty tree → stop and ask** (stash / commit / abort). **No spec in play and no slug in the prompt → stop and ask** the user for a slug, then re-dispatch with it (branch `feat/<slug>`).
- Existing integration branch → **resume**: keep its discovered name verbatim everywhere (never rename or re-create it); merged tickets move to a resolved set; they satisfy blocker edges and step 3's `Closes` list but are not re-dispatched; WIP branches go to their wave's dispatch as `resume_branch`. A `needs-info` label beside a WIP branch is a ticket a prior run parked, not human triage: name it in the announcement and dispatch it (the contract swaps the label back). `needs-info` with no WIP branch, `wontfix`, or `needs-triage` still stops. `awaiting-verification` on the spec or on a work-set ticket (a prior run's PR awaits human verification) is not a stop: name it in the announcement and proceed. This run's Verification plan supersedes the old one.

Then, in the main thread, **announce the work-set** (numbers + titles, skipped closed tickets, resume state) and the wave plan.

Done when: work-set announced, graph acyclic, integration branch checked out in the main tree with its origin tip known, baseline recorded, handoff paths in hand.

### 1. Implement in waves

Repeat until the work-set drains, reporting once per wave (what merged, what is next), not per dispatch:

1. **Wave** = every remaining ticket whose blockers are all merged into the integration branch.
2. Dispatch the wave in parallel: one worktree-isolated coding subagent per ticket
   (model per orchestrator-mode). Each prompt is a rich handoff: ticket number, title, and body verbatim,
   the handoff files' absolute paths (read both first; worktrees start without installed
   dependencies, so install before editing), and the `implement-ticket` **Orchestrated dispatch**
   overrides: `base_branch: <integration branch>`, `open_pr: false`, `baseline` (the current
   integration tip and step 0's pre-existing failures), blockers pre-merged, `resume_branch` when
   step 0 found a WIP branch for it.
3. **Integrate**: a dedicated dispatch whose prompt pastes every ticket return of the wave
   verbatim (`status`, `branch`, `worktree_path`, `files_changed`, `tests_run`, `decisions_made`,
   `open_questions`), the integration branch name, the baseline, and `handoff.md`'s path. It
   merges the wave's `status: success` branches into the integration branch, runs the merged
   tickets' tests plus tests covering any conflict-resolution hunk on the merged tree, pushes
   it, comments "merged into" on the merged tickets, appends the wave's decisions and open
   questions to `handoff.md`, cleans up worktrees and harness branches, and deletes the merged
   ticket branches locally **and on origin**. Its full contract (ordered steps, mechanical vs
   semantic conflicts, red merged tree as a semantic conflict, escalation to one resolver,
   deletion rules, return fields) is
   [references/reference.md#wave-integration](references/reference.md#wave-integration).
   The wave report names branch-deletion failures only, never the successes.
   A semantic conflict that survives the resolver leaves the main tree clean at the
   last pushed tip and stops the run per Stop conditions.
   **This narrows orchestrator-mode Rule 6 and Parallel Writes step 4**: for a wave with no
   hunk resolved, the integrate dispatch's merged-tree test run is the verification (it
   authored none of the code), and step 2's Verify is the fresh-eyes run on the unified tree.
   Whenever any hunk was resolved, by the integrate dispatch or a resolver, a separate dispatch
   re-runs the tests covering it before the next wave (contract: the reference's Post-resolution
   tests); a red result there is a fix dispatch on the integration branch, not a revert, and it
   commits, pushes, and returns the new `integration_tip`. The orchestrator opens the next wave
   only on the latest returned `integration_tip`, which becomes the next wave's baseline SHA.
4. A failed ticket (three strikes) keeps `implement-ticket`'s orchestrated stop
   behaviour and returns `status: failed` with the WIP branch, `worktree_path`, and
   root cause. **Its dependants leave the work-set**; independent tickets continue
   (drain-around-failure); returned `open_questions` go into the wave report. Failed
   tickets' WIP branches are never merged. `status: already_satisfied` → treat as
   merged; its "merged into" comment is the integrate dispatch's duty.

Done when: every work-set ticket is merged, or recorded as failed / skipped-as-downstream.

### 2. Integration gates

After the last wave, two fresh subagents, **dispatched in parallel in one message** (no
self-certification, per orchestrator-mode: the first look at the *merged* result of many agents' work):

1. **Verify** is the handoff file's feedback-loop commands: full type-check + test suite + runtime smoke check on the integration branch.
2. **Review** is the `code-review` skill with `<default>` as its fixed point (the main tree has the integration branch checked out, so HEAD is its tip). The dispatch prompt carries `spec.md`'s absolute path plus [references/reference.md#integration-review](references/reference.md#integration-review), the spec-source override that keeps code-review off the tickets. Dispatch it as a plain worker, not a sub-orchestrator (an override of orchestrator-mode Rule 8: `code-review` carries its own fan-out).

Findings → **one write-intent fix dispatch per strike, carrying every finding from both
gates**, on the integration branch (the main tree), committing and pushing, then re-run both gates; three strikes
stops the run. On a partial work-set (anything failed or skipped) run Verify only, so the
pushed branch is known-green, and stop.

Done when: Verify and Review are clean on the pushed integration branch (partial work-set: Verify clean, then stop).

### 3. Verification plan and feature PR

One dispatch (it runs the delivered software, inherit the session model) authors the **Verification plan** per [references/reference.md#verification-plan](references/reference.md#verification-plan) (the three-scenario cap and selection rule, shape, execute-before-publishing, the waiver form), then opens the feature PR per [references/reference.md#feature-pr](references/reference.md#feature-pr) (body sizing, `Closes` lines, `awaiting-verification` mechanics). Its prompt carries the handoff files' paths, the step 2 Verify report verbatim (the Test plan's source), and the **`Closes` list** the orchestrator computes: the step-0 resolved set plus every ticket this run merged or found `already_satisfied`, and whether that list covers step 0's `spec_open_tickets`. Body: repo PR template if present; a **Summary**, a **Test plan**, the **Verification plan** verbatim, and `Closes #<n>` lines; `Closes #<spec>` only when every open ticket is covered, otherwise comment progress on the spec. Create it **ready-for-review** (not draft); a prior run's feature PR gets its body updated instead. **Evidently broken** while executing the plan (a step errors, or the data plainly contradicts a criterion) → no PR: return the findings, which go into step 2's fix machinery (fix dispatch, re-run both gates, re-dispatch this step; the same three strikes). The plan never walks the human into a known defect. Merging, and removing `awaiting-verification` after working the plan, are the human's, never yours. Close out leading with the outcome (PR URL + what landed), detail after.

Done when: the PR URL is reported, every runnable plan step executed.

## Stop conditions

A strike-out never halts mid-wave: drain the independent tickets (step 1.4), run step 2's
Verify, then stop before Review and the plan + PR dispatch. A three-strikes stop in step 2's
or step 3's fix loop halts the same way: no PR, the plan's findings reported. A semantic
merge conflict surviving its one resolver dispatch stops immediately instead: no further
waves, no Verify; unmerged tickets are reported and their dependants leave the work-set as
in step 1.4. When stopping, push the integration branch if it is ahead of origin, and report
leading with the outcome (what merged and what did not), then the detail: what failed (root
cause + WIP branch names), what was skipped as downstream, and that re-invoking resumes from
step 0.
