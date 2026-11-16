---
name: implement-feature
argument-hint: "[spec#] [ticket#...]"
disable-model-invocation: true
description: "Implement a feature as one PR by dispatching ready tickets and integrating completed work."
---

# Implement feature

Deliver one reviewed feature PR into the default branch. Use `orchestrator-mode` to
coordinate and `implement-ticket` for each ticket. Communicate through spec, ticket,
research, commit, and handoff pointers. Keep detailed evidence in durable artifacts.

Apply [Writing](../implement-ticket/references/setup.md#writing) using `technical-writing` and
`unslop` for coordinator and worker prose. Pass the resolved references in every worker brief.

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

Copy this checklist into `handoff.md` at step 0, with the per-ticket lines once per work-set
ticket, and tick each item when its evidence is recorded. On resume, reconcile it against the run record and continue from the first open item.

```text
- [ ] 0. Work-set, completion mode, door, and coverage gaps announced
- [ ] 0. Original baseline recorded; integration branch and run record paths saved
- [ ] 1. Per ticket: dispatch base pinned, claimed, start comment URL recorded
- [ ] 1. Per ticket: result integrated or satisfied, VERIFIED_TIP pushed, stop comment URL recorded
- [ ] 1. Owned worktrees and branches cleaned or retained with a reason
- [ ] 2. Check wave returned on the fixed integration SHA (Standards, Spec, final review); every finding dispositioned
- [ ] 2. Fix rounds closed or spent; open findings recorded with their door outcome
- [ ] 3. Verify passed on the final integration SHA
- [ ] 3. Tracker coverage refreshed; closing lines backed by current evidence
- [ ] 3. Feature PR body published and the door outcome applied; every started attempt has a stop comment
```

### 0. Resolve scope and prepare

Locate `implement-ticket`'s installed root by path (it sets `disable-model-invocation`, so it
is absent from the invocable list) and read its `references/setup.md`.
Complete [Setup](../implement-ticket/references/setup.md) before dispatching setup workers.
If the file is missing, report the paired update needed and continue scope discovery without ticket dispatch.
Resolve cross-skill references from each installed skill's own root and pass absolute paths to workers.

Dispatch setup using [Work-set resolution](references/reference.md#work-set-resolution).
Announce the work-set, completion mode, door, and any missing spec coverage before continuing
with [Tree preparation](references/reference.md#tree-preparation). Preserve unrelated dirty
work through isolation. Resolve cycles, outside blockers, ambiguous ownership, and scope
questions while continuing independent authorized work where possible.

Only a fresh tickets-only run with one selected ticket and no whole-spec promise uses a
solo `implement-ticket` dispatch; its brief gives the absolute path to implement-ticket's
`SKILL.md` and tells the worker to read it. A spec invocation or resumed integration branch keeps
this workflow. An empty work-set still needs scope reconciliation or existing-branch gates
before claiming completion.

When several tickets need the same investigation, use an optional exploration worker.
Save source-linked notes in the shared run directory and pass relevant paths to consumers.
Ready tickets can proceed without exploration they do not need.

Done when skill dependency results, the ticket graph, scope, check commands, original baseline,
integration checkout, and durable run record are available by path. Prepare the draft body now; follow
[Feature PR](references/reference.md#feature-pr) when the branch has a publishable diff.

### 1. Dispatch, integrate, and refresh the frontier

Follow [Frontier scheduling](references/reference.md#frontier-scheduling) throughout this loop.

1. Pin each ready ticket's dispatch SHA and record its worktree, branch, and prerequisite
   evidence. Have the tracker worker claim it and post its start comment before dispatch.
2. Run ticket workers in the background within capacity. Pass snapshot and handoff paths,
   dispatch metadata, the absolute path to implement-ticket's `SKILL.md` to read, and the
   [Orchestrated ticket contract](../implement-ticket/references/orchestrated.md).
3. On each return or interruption, record the result and have the tracker post the stop
   comment. Send completed results to one integration worker using
   [Ticket integration](references/reference.md#ticket-integration) and its exact
   [Integration commands](references/reference.md#integration-commands), without waiting for
   unrelated running tickets. Conflict resolutions and fixes require
   [Post-resolution tests](references/reference.md#post-resolution-tests).
4. After the merged tree passes checks and is preserved, update the frontier and dispatch
   newly ready tickets. Update the local PR body as verified work accumulates; open an early
   draft PR only on request ([Feature PR](references/reference.md#feature-pr)).
   Retain failed WIP and continue independent tickets. Clean up only preserved, owned resources
   with the exact [Cleanup](references/reference.md#cleanup) commands.

Report verified integrations, newly ready work, and concrete blockers without repeating
worker logs. Done when all work-set tickets have evidence on the integration tip or are
recorded as failed or blocked. Every started attempt has a stop-comment URL or a reported
posting failure. Partial work stays draft and retains its remaining obligations.

### 2. Review the feature

Dispatch the check wave on a fixed integration SHA as
[Integration review](references/reference.md#integration-review) describes: fresh Standards,
Spec, and final reviewers together, each in an isolated checkout at that SHA, with the
materialized `scope.md` as the one originating spec plus the fixed PR-base commit. The
integration worker's recorded checks on that SHA are the wave's check evidence. Readers of a
fixed SHA share no concurrent writer.

Triage the findings into one list and send accepted fixes to one fix worker, through the fix
rounds that section sets. Resolve whole-spec coverage gaps before final completion. Report
requirements outside an explicit ticket list without implementing them.

Done when every finding has a disposition, the fix rounds are closed or spent, each finding
still open is recorded with its door outcome, and the recorded completion obligations are met.

### 3. Verify and finalize the feature PR

Dispatch two fresh workers together on the final integration SHA. Verify is the feature's
closing verification: it runs configured lint, type checks, tests, and the applicable runtime
or artifact check, reruns the smoke commands recorded in each ticket's evidence artifact, and
checks the PR base for drift. The PR worker uses `pr` to author the body and finalizes the
[Feature PR](references/reference.md#feature-pr). Pass both the SHA, coverage evidence, run
record, and reports. A failed Verify or a newly discovered defect takes a late fix
(implement-ticket's Fix rounds) and a fresh Verify. Refresh tracker coverage before claiming the entire spec is complete. For partial
work, run Verify on the preserved integration and report the incomplete gates in the draft PR body.

Update the same draft with actual results and evidence-backed closing lines, then apply the
door outcome as [Feature PR](references/reference.md#feature-pr) describes. Never merge it.
Report the URL, any unexecuted checks, and the
friction workers returned, grouped by cause, as proposed follow-ups. If publication is blocked,
preserve the completed branch and PR body and report that limitation.

## Failure and resume

Keep original baseline evidence, decisions, ownership records, and WIP across invocations.
An interrupted merge is not proof the tree equals the last pushed tip. Return actual HEAD,
merge state, integrated tickets, dirty paths, and preservation status. Push only verified
integration states, or explicitly authorized WIP to a separate recovery branch. Resume from
that record; never relabel a current integration regression as a pre-existing baseline failure.
Before pausing, cancelling, or handing off, stop active ticket workers and post each started
attempt's stop comment. Reconcile missing comments from interrupted runs before resuming.
