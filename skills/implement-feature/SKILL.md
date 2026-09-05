---
name: implement-feature
argument-hint: "[spec#] [ticket#...]"
disable-model-invocation: true
description: "Implement a whole feature as one PR through ticket waves on an integration branch. Use when implementing a spec and its tickets, or an explicit ticket set, end-to-end."
---

# Implement feature

Deliver the selected tickets as one reviewed feature PR into the default branch. Use
`orchestrator-mode` for this run and `implement-ticket` for each ticket. Delegate git,
tracker, file, and test work; keep bulk evidence in handoff artifacts.

## Scope and contracts

- The **work-set** is the selected tickets. An explicit list controls implementation and
  review scope; a larger spec provides context, not additional completion obligations.
- The **integration branch** collects verified ticket work. Keep its name on resume.
  Follow environment branch conventions, using `spec-<N>-<slug>` or a descriptive slug.
  Recognize prior `feat/spec-*`, `feat/prd-*`, `feat/ticket-*`, and `feat/issue-*` names.
- A **wave** contains tickets whose blockers are satisfied in the current integration tip.
  Dispatch within available capacity, allocating separate external resources or serializing
  checks that share ports, databases, or output paths. Each ticket has an isolated worktree,
  including single-ticket waves. A setup worker can create it manually in a writable location
  when native isolation is unavailable. If isolation cannot be established, report the blocker.
- Pin each wave's immutable `base_sha`; return and verify it. The integration branch name is
  destination metadata, not a substitute for the SHA. Preserve the **original baseline** SHA
  and failures across resumes; the wave base advances only after verification.
- The coordinator owns ticket eligibility and lifecycle. Workers do not claim tickets,
  comment, relabel issues, or create per-ticket PRs. Existing authorization and configured
  permissions govern external actions; comments require explicit messaging authorization.
  Store proposed comments locally when absent. Do not prescribe blanket sandbox bypasses.
- Pass absolute artifact paths, relevant decisions, and compact return summaries. Reuse
  loaded skills and honor explicit prose and testing guidance. One worker owns each ticket;
  reserve capacity for leaf work and review children instead of spawning helpers inside it.

## Workflow

### 0. Resolve the work-set and prepare the tree

Dispatch setup using [Work-set resolution](references/reference.md#work-set-resolution).
It resolves spec-only, tickets-only, or combined inputs, checks every selected ticket's
eligibility, snapshots bodies and criteria, and builds the dependency graph. The setup return
contains a compact work-set/index and proposed branch or resume state. Announce the work-set
before branch creation, then continue setup with
[Tree preparation](references/reference.md#tree-preparation).

A fresh one-ticket work-set uses one solo `implement-ticket` dispatch. A resumed integration
branch keeps its feature workflow even if one ticket remains. Zero tickets without an existing
branch means nothing to implement; a completed existing integration branch still needs its gates.
Surface dependency cycles, mismatched parent specs, unresolved outside blockers, ambiguous
ownership, or required overlapping dirty inputs. Preserve unrelated dirty work through isolation.
Infer a short slug from the selected scope when no spec is present.

Done when the work-set is announced, dependencies resolved, integration checkout and SHAs known,
and the original baseline, ticket snapshots, and durable run record are available by path.

### 1. Implement in waves

1. Select the ready tickets and pin `base_sha` to the verified integration tip. A setup
   worker records each assigned worktree and task-created branch before implementation.
2. Dispatch one worker per ticket within capacity. Supply its snapshot, handoff and run-record
   paths, `base_branch`, `base_sha`, original baseline, resource allocation, `open_pr: false`,
   and any evidence-backed `resume_branch`. Tell it to read implement-ticket's
   [Orchestrated dispatch contract](../implement-ticket/references/orchestrated.md).
3. A dedicated integration worker follows
   [Wave integration](references/reference.md#wave-integration). It checks the result SHAs,
   merges successes, tests the merged tree, records decisions, and reports actual merge state.
   Any conflict resolution or subsequent fix goes through a separate verification worker
   using [Post-resolution tests](references/reference.md#post-resolution-tests). Repeat fix
   then verification until green or a concrete blocker. Release dependants and clean up only
   after the tested integration tip is preserved. An integrator that authored no code can
   supply the independent wave verification; the final gates still check the whole feature.
4. A failed ticket keeps its WIP. Record its dependants as blocked, continue independent
   tickets, and report the failure. Accept `already_satisfied` only with evidence for every
   criterion at the pinned base. This marks behavior resolved, not WIP safe to delete.

Report what merged and what is next once per wave, including unresolved preservation or cleanup
failures. Done when every selected ticket is satisfied or recorded as failed or blocked downstream.

### 2. Integration gates

Use fresh workers to verify the fixed integration SHA and review its diff from the recorded
PR base. Verify runs configured lint/type checks, tests, and the applicable artifact or runtime
check. Review checks standards and the selected tickets' criteria, using the full spec only
as context. See [Integration review](references/reference.md#integration-review).

Schedule according to total capacity. On a four-slot runtime, finish Verify before starting a
`code-review` worker that needs two children, or flatten its review axes into root-owned workers.
Use `code-review` when available; otherwise dispatch equivalent independent standards and
criteria reviews. No verifier or reviewer mutates the checkout while another reads its fixed SHA.

Send actionable in-scope findings to one fix worker, then rerun the affected gates on the new SHA.
Unselected requirements and adjacent problems remain reported, not implemented. Repeated failures
require diagnosis or another approach; stop only at a concrete blocker. For a partial work-set,
run Verify on preserved integration work and report the incomplete state without opening a PR.

Done when both gates pass on the preserved integration head and every selected ticket is satisfied.

### 3. Verification plan and feature PR

One worker authors and executes the [Verification plan](references/reference.md#verification-plan),
then creates or updates the [Feature PR](references/reference.md#feature-pr). Pass the verified SHA,
selected-scope evidence, run record, and verification report paths. A newly discovered defect returns
to the fix and gate loop. Refresh tracker coverage before claiming the entire spec is complete.

Open one ready-for-review PR with explicit base and head, Summary, Test plan, Verification plan,
and evidence-backed closing lines. Never merge it. Report its URL and any unexecuted checks.
If publication is blocked, preserve the completed branch and draft body and report that limitation.

## Failure and resume

Keep original baseline evidence, decisions, ownership records, and WIP across invocations.
An interrupted merge is not proof the tree equals the last pushed tip. Return actual HEAD,
merge state, integrated tickets, dirty paths, and preservation status. Push only verified
integration states, or explicitly authorized WIP to a separate recovery branch. Resume from
that record; never relabel a current integration regression as a pre-existing baseline failure.
