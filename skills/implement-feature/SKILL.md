---
name: implement-feature
argument-hint: "[spec#] [ticket#...]"
disable-model-invocation: true
description: "Implement a feature as one PR by dispatching ready tickets and integrating completed work. Use when implementing a spec and its tickets, or an explicit ticket set, end-to-end."
---

# Implement feature

Deliver one reviewed feature PR into the default branch. Use `orchestrator-mode` to
coordinate and `implement-ticket` for each ticket. Communicate through spec, ticket,
research, commit, and handoff pointers. Keep detailed evidence in durable artifacts.

## Scope and ownership

- Spec-only input promises the whole spec. An explicit ticket list defines the work-set;
  its parent spec supplies context. Record the completion mode and coverage gaps.
- The **frontier** contains tickets with no active implementer whose blockers are satisfied
  in the verified, preserved integration tip. Assignment to the authenticated actor is
  advisory. Each dispatch pins that tip as its immutable `base_sha`.
- Each ticket has its own branch and isolated worktree, even when only one is ready.
  The integration branch collects verified work. Preserve its identity on resume and
  keep the original baseline SHA and failures separate from later integration failures.
- The coordinator owns eligibility, claims, issue comments, labels, and the feature PR
  through its tracker worker. Ticket workers implement and return evidence. Follow
  implement-ticket's [Ticket lifecycle comments](../implement-ticket/SKILL.md#ticket-lifecycle-comments)
  for every attempt, within existing authorization and configured permissions.
- Count the root and all active descendants against capacity. Use transient setup,
  tracker, and integration roles. One worker owns each ticket without helper fan-out.

## Workflow

### 0. Resolve scope and prepare

Dispatch setup using [Work-set resolution](references/reference.md#work-set-resolution).
Announce the work-set, completion mode, and any missing spec coverage before continuing
with [Tree preparation](references/reference.md#tree-preparation). Preserve unrelated dirty
work through isolation. Resolve cycles, outside blockers, ambiguous ownership, and scope
questions while continuing independent authorized work where possible.

Only a fresh tickets-only run with one selected ticket and no whole-spec promise uses a
solo `implement-ticket` dispatch. A spec invocation or resumed integration branch keeps
this workflow. An empty work-set still needs scope reconciliation or existing-branch gates
before claiming completion.

When several tickets need the same investigation, use an optional exploration worker.
Save source-linked notes in the shared run directory and pass relevant paths to consumers.
Ready tickets can proceed without exploration they do not need.

Done when the dependency graph, scope, check commands, original baseline, integration
checkout, and durable run record are available by path. Prepare the draft body now; follow
[Feature PR](references/reference.md#feature-pr) when the branch has a publishable diff.

### 1. Dispatch, integrate, and refresh the frontier

Follow [Frontier scheduling](references/reference.md#frontier-scheduling) throughout this loop.

1. Pin each ready ticket's dispatch SHA and record its worktree, branch, and prerequisite
   evidence. Have the tracker worker claim it and post its start comment before dispatch.
2. Run ticket workers in the background within capacity. Pass snapshot and handoff paths,
   dispatch metadata, and the [Orchestrated ticket contract](../implement-ticket/references/orchestrated.md).
3. On each return or interruption, record the result and have the tracker post the stop
   comment. Send completed results to one integration worker using
   [Ticket integration](references/reference.md#ticket-integration), without waiting for
   unrelated running tickets. Conflict resolutions and fixes require
   [Post-resolution tests](references/reference.md#post-resolution-tests).
4. After the merged tree passes checks and is preserved, update the frontier and dispatch
   newly ready tickets. Create or update the feature draft PR as verified work accumulates.
   Retain failed WIP and continue independent tickets. Clean up only preserved, owned resources.

Report verified integrations, newly ready work, and concrete blockers without repeating
worker logs. Done when all work-set tickets have evidence on the integration tip or are
recorded as failed or blocked. Every started attempt has a stop-comment URL or a reported
posting failure. Partial work stays draft and retains its remaining obligations.

### 2. Verify and review the feature

Use fresh workers for Verify and [Integration review](references/reference.md#integration-review)
on a fixed integration SHA. Verify runs configured lint, type checks, tests, and the applicable
runtime or artifact check. Review uses that SHA as its immutable review head with the recorded
completion mode, authoritative scope sources, and fixed PR-base commit.

On a four-slot runtime, finish Verify before a `code-review` worker that needs two children,
or flatten its standards and criteria axes into root-owned workers. Use equivalent independent
reviews if `code-review` is unavailable. Readers of a fixed SHA share no concurrent writer.

Send actionable in-scope findings to one fix worker, then rerun affected gates on the new SHA.
Resolve whole-spec coverage gaps before final completion. Report requirements outside an
explicit ticket list without implementing them. Diagnose repeated failures or change approach.
For partial work, verify the preserved integration and report incomplete gates with the draft PR.

Done when both gates pass on the preserved head and the recorded completion obligations are met.

### 3. Finalize the feature PR

One worker authors and executes the [Verification plan](references/reference.md#verification-plan),
then finalizes the [Feature PR](references/reference.md#feature-pr). Pass the verified SHA,
coverage evidence, run record, and reports. A newly discovered defect returns to the fix and
verification loop. Refresh tracker coverage before claiming the entire spec is complete.

Update the same draft with actual results and evidence-backed closing lines, then mark it
ready. Never merge it. Report the URL and any unexecuted checks. If publication is blocked,
preserve the completed branch and PR body and report that limitation.

## Failure and resume

Keep original baseline evidence, decisions, ownership records, and WIP across invocations.
An interrupted merge is not proof the tree equals the last pushed tip. Return actual HEAD,
merge state, integrated tickets, dirty paths, and preservation status. Push only verified
integration states, or explicitly authorized WIP to a separate recovery branch. Resume from
that record; never relabel a current integration regression as a pre-existing baseline failure.
Before pausing, cancelling, or handing off, stop active ticket workers and post each started
attempt's stop comment. Reconcile missing comments from interrupted runs before resuming.
