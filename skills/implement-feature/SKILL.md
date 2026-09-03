---
name: implement-feature
argument-hint: "[spec#] [ticket#...]"
disable-model-invocation: true
description: "Implement a whole feature as one PR: orchestrate subagent waves over a spec's tickets on a shared integration branch. Use when you have a spec (PRD) and/or its tickets (from to-spec / to-tickets) to implement end-to-end."
---

# Implement Feature

Take a spec and its tickets from open → integration branch → parallel ticket branches →
integrated review + tests → verification plan → **one feature PR** into the default branch.

Operate under the `orchestrator-mode` skill for the whole run — every git / gh / file /
test action below is a subagent dispatch (its 1–3-sentence report rule yields to this
skill's per-wave and close-out reports). Per-ticket work composes the `implement-ticket`
skill via its **Orchestrated dispatch** contract.

## Vocabulary

- **Work-set** — the resolved list of tickets this run will implement.
- **Integration branch** — `feat/spec-<N>-<slug>`, cut from the default branch; all ticket work merges here. The main tree stays checked out on it for the whole run. (Legacy runs named it `feat/prd-<N>-<slug>` — treat that as equivalent.)
- **Ticket branch** — `feat/ticket-<N>-<slug>`, cut from the integration-branch tip. (Legacy: `feat/issue-<N>-<slug>`.)
- **Wave** — the currently-unblocked tickets, dispatched in parallel.
- **Feature PR** — the single PR from integration branch to default branch.
- **Verification plan** — the human-facing walkthrough of the delivered feature (see `CONTEXT.md`): using the application and inspecting the data, not re-running tests. Authored after the gates, embedded in the feature PR body.

## Rules

- **Before writing any prose published to git or GitHub (PR body, ticket and spec comments, commit messages), invoke the `technical-writing` and `unslop` skills if installed, and write that prose to their standard; baked-in minimum either way: plain words, active voice, and no em dashes** (use commas, colons, or parentheses). Dispatch prompts that write such prose carry this rule, and tell the subagent to invoke both skills itself (subagents may not have them loaded already).
- **Network `gh` / `git fetch|pull|push` run outside the sandbox** — every dispatch prompt says so.
- The spec is context, never a work item.
- **Implement the work-set at the scope its tickets ask for, as the smallest change that solves it** — adjacent bugs, refactors, and cleanups get reported in the feature PR body, not fixed. Ticket dispatches inherit the frugality bar via `implement-ticket`; steps 3–4 fix dispatch prompts carry it explicitly (the `principle-laziness-protocol` skill when installed): prefer deletion over addition and the smallest diff that fixes it.
- **One dispatch per ticket per wave** — no helper or double-check agents alongside it, none to re-read what a dispatch already returned. Only the dispatches steps 0-5 already prescribe (integration, resolver, targeted tests, gates, fixes, verification plan, PR) run beside it.
- Dispatch prompts tell the subagent to invoke `implement-ticket`; if subagents cannot load skills, paste its body verbatim into the prompt. Per-dispatch contracts live in [references/reference.md](references/reference.md) — a prompt that cites one carries that file's **absolute path** plus the section anchor (subagents cannot resolve skill-relative links) and tells the subagent to read it first.
- **Every ticket dispatch gets worktree isolation, even a one-ticket wave** — deliberately stricter than orchestrator-mode's two-writer rule, so the main tree never leaves the integration branch. Use the delegation tool's native worktree isolation (orchestrator-mode reference, Tool Mapping); none available → stop and say so rather than sharing the main tree.

## Workflow

### 0. Resolve the work-set

One read-only dispatch (general-purpose — it runs networked `gh`; inherit the session model, this is read-only but not mechanical) follows [references/reference.md#work-set-resolution](references/reference.md#work-set-resolution) — the exact commands and evidence rules — to gather:

- **Args** — spec number, ticket list/range, or both. Spec-only → list its open tickets (the anchored `## Parent` body scan unioned with native sub-issues, per the reference). List-only → resolve the shared parent spec for context. Both → the explicit list is the authoritative work-set — but a listed ticket whose `## Parent` names a different spec, or a list spanning two specs, is a stop-and-ask (likely a typo, and step 3 reviews against one spec).
- Closed tickets: skip, naming them in the announcement. Spec body + acceptance criteria: capture verbatim for later handoffs.
- Blocking edges → the dependency graph: for **every** work-set ticket, the native dependency API unioned with the anchored body scan — either source alone may carry an edge. An edge to an open issue outside the work-set → stop and ask (a resume-merged ticket of this feature counts as satisfied, not outside); to a closed one → ignore.
- The **feedback-loop commands** — install/setup, type-check, test, and run commands (same sources as `implement-ticket` step 4) — for the dispatch handoffs and the step 3 gates.
- `git status --porcelain`; whether the integration branch exists under any accepted name (probed on origin per the reference); if it does, the **resume state** per work-set ticket — **merged** per the reference's merged-evidence rule, plus any pushed WIP ticket branch.

Then, in the main thread:

- **Announce the work-set** (numbers + titles) and the wave plan before any branch is created.
- **Work-set of one, no existing integration branch → do not orchestrate.** Say so, hand the ticket to `implement-ticket` in a single dispatch on its solo defaults (own branch, own PR, no overrides), and stop: the machinery below only pays off across several tickets. On resume, stay here — that ticket belongs to the feature PR.
- **Work-set of zero → no waves.** With an existing integration branch, the branch is merged-but-ungated: go straight to step 3's gates, then steps 4-5. With none, report there is nothing to implement and stop.
- **Cycle in the graph → stop** and surface it.
- **Dirty tree → stop and ask** (stash / commit / abort).
- Existing integration branch → **resume**: keep its discovered name verbatim everywhere (never rename or re-create it); merged tickets move to a resolved set — they satisfy blocker edges and step 5's `Closes` scan but are not re-dispatched; WIP branches go to their wave's dispatch as `resume_branch`. A `needs-info` label beside a WIP branch is a ticket a prior run parked, not human triage: name it in the announcement and dispatch it (the contract swaps the label back). `needs-info` with no WIP branch, `wontfix`, or `needs-triage` still stops. `awaiting-verification` on the spec or on a work-set ticket (a prior run's PR awaits human verification) is not a stop: name it in the announcement and proceed — this run's Verification plan supersedes the old one.

Done when: work-set announced, graph acyclic, tree clean, resume state known.

### 1. Integration branch

Dispatch (git plumbing with judgement forks — inherit the session model): `git switch <default> && git pull --ff-only`, create `feat/spec-<N>-<slug>` (slug = kebab of the spec title, ≤5 words, drop filler), push with `-u origin`. No spec in play → ask the user for a slug, use `feat/<slug>`. On resume: skip creation, switch to the **step-0 discovered name** (legacy names stay), `git pull --ff-only`, and push if local is ahead (a manual fix may be local-only).

Done when: the dispatch reports the branch pushed, checked out in the main tree, and its origin tip SHA.

### 2. Implement in waves

Repeat until the work-set drains, reporting once per wave (what merged, what is next), not per dispatch:

1. **Wave** = every remaining ticket whose blockers are all merged into the integration branch.
2. Dispatch the wave in parallel — one worktree-isolated coding subagent per ticket
   (model per orchestrator-mode). Each prompt is a rich handoff: ticket number, title, and body verbatim,
   spec excerpts, decisions so far, the step-0 feedback-loop commands (worktrees start
   without installed dependencies — install before baselining), and the
   `implement-ticket` **Orchestrated dispatch** overrides:
   `base_branch: <integration branch>`, `open_pr: false`, blockers pre-merged,
   `resume_branch` when step 0 found a WIP branch for it.
3. **Integrate**: a dedicated dispatch merges the wave's `status: success` branches
   into the integration branch, pushes it, comments "merged into" on the merged
   tickets, cleans up worktrees, and deletes the merged ticket branches locally **and
   on origin** — its full contract (merge order, conflict escalation to one resolver,
   comment-after-push, deletion rules, return fields) is
   [references/reference.md#wave-integration](references/reference.md#wave-integration).
   The wave report names branch-deletion failures only, never the successes.
   A semantic conflict that survives the resolver leaves the main tree clean at the
   last pushed tip and stops the run per Stop conditions. The orchestrator opens the
   next wave only on a returned `integration_tip`, after a targeted test dispatch —
   the affected tests when a conflict was resolved, otherwise the merged tickets'
   tests (merged parallel writers always clear orchestrator-mode's Rule 6 bar).
4. A failed ticket (three strikes) keeps `implement-ticket`'s orchestrated stop
   behaviour and returns `status: failed` with the WIP branch, `worktree_path`, and
   root cause. **Its dependants leave the work-set**; independent tickets continue
   (drain-around-failure); returned `open_questions` go into the wave report. Failed
   tickets' WIP branches are never merged. `status: already_satisfied` → treat as
   merged; its "merged into" comment is the integrate dispatch's duty.

Done when: every work-set ticket is merged, or recorded as failed / skipped-as-downstream.

### 3. Integration gates

After the last wave, two separate dispatches by fresh subagents (no self-certification,
per orchestrator-mode: the first look at the *merged* result of many agents' work):

1. **Verify** — the step-0 feedback-loop commands: full type-check + test suite + runtime smoke check on the integration branch.
2. **Review** — the `code-review` skill with `<default>` as its fixed point (the main tree has the integration branch checked out, so HEAD is its tip). The dispatch prompt carries the step-0 spec body verbatim plus [references/reference.md#integration-review](references/reference.md#integration-review) — the scratch-file spec-source override that keeps code-review off the tickets. Dispatch it as a plain worker, not a sub-orchestrator: `code-review` carries its own fan-out.

Findings → sequential write-intent fix dispatches on the integration branch, then
re-verify; three strikes stops the run. On a partial work-set (anything failed or
skipped) run Verify so the pushed branch is known-green, skip Review, the Verification
plan, and the PR, and stop.

Done when: Verify and Review are clean on the pushed integration branch (partial work-set: Verify clean, then stop).

### 4. Verification plan

One dispatch (it runs the delivered software — inherit the session model) authors the **Verification plan** per its full contract in [references/reference.md#verification-plan](references/reference.md#verification-plan) (the three-scenario cap and selection rule, shape, execute-before-publishing, the waiver form). Its prompt carries the step-0 spec body and acceptance criteria verbatim, the work-set tickets' criteria, the step-0 feedback-loop and run commands, and that reference. **Evidently broken** (a step errors, or the data plainly contradicts a criterion) → back into step 3's fix machinery (sequential fix dispatches, re-run Verify, re-author the plan; the same three strikes) — the plan never walks the human into a known defect.

Done when: the dispatch returns the plan (or its waiver) as a markdown section, every runnable step executed.

### 5. Feature PR

One dispatch, per the full body contract in
[references/reference.md#feature-pr](references/reference.md#feature-pr) (the `Closes`
evidence scan, body sizing, `awaiting-verification` mechanics): repo PR template if
present; body carries a **Summary**, a **Test plan** (what the step-3 Verify gate ran
and observed), the step-4 **Verification plan** verbatim, and rebuilt `Closes #<n>`
lines — `Closes #<spec>` only when every open ticket of the spec is covered, otherwise
comment progress on the spec. Create it **ready-for-review** (not draft); a prior run's
feature PR gets its body updated instead. Merging, and removing `awaiting-verification`
after working the plan, are the human's — never yours. Close out leading with the
outcome (PR URL + what landed), detail after.

Done when: the PR URL is reported.

## Stop conditions

A strike-out never halts mid-wave: drain the independent tickets (step 2.4), run step 3's
Verify, then stop before Review, the Verification plan, and the PR. A three-strikes
stop in step 3's or step 4's fix loop halts the same way: no PR, the plan's findings
reported. A semantic merge conflict surviving its one resolver dispatch stops
immediately instead — no further waves, no Verify; unmerged tickets are reported and
their dependants leave the work-set as in step 2.4. When stopping, push the integration
branch if it is ahead of origin, and report leading with the outcome (what merged and
what did not), then the detail: what failed (root cause + WIP branch names), what was
skipped as downstream, and that re-invoking resumes from step 0.
