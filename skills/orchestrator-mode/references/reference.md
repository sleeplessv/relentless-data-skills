# Orchestrator reference

Read the section needed for the current dispatch. Tool schemas and environment permissions
are authoritative; this file defines coordination invariants rather than vendor inventories.

## Tool mapping

Use exposed spawn and management tools. Check accepted arguments, context inheritance,
model restrictions, completion behavior, and concurrency before relying on them. A specialist
is an option only if the current roster exposes it. Track a plan in prose when no plan tool
exists. File or shell reads used solely to load applicable skill instructions are skill loading.

## Nesting sub-orchestrators

Prefer flat dispatches. A sub-orchestrator earns its slot when it can own an independent
subtree and return decisions and evidence without sending its internal reports to the root.
Pass the scope, artifact paths, return contract, and allocated depth and slot budget. Decrement
that budget for descendants and respect any stricter runtime limit.

Reserve capacity for workers before spawning coordinators. With four total slots, a root,
a verifier, and a reviewer that needs two children cannot all run together. Finish the
verifier first, then run the reviewer and its two children, or flatten the review axes into
root-owned workers. A coordinator at its depth limit executes as a leaf only when that
fallback is authorized; otherwise it returns the missing capability for the parent to flatten.

## Parallel writes worktrees

1. **Prepare.** A setup worker records git status, intended base SHA, branch conventions,
   and existing worktrees. Preserve unrelated dirty files. Isolate work that does not need
   them; if required uncommitted inputs or overlapping edits have ambiguous ownership,
   surface that specific decision before touching them. Serialization alone does not resolve
   an overlapping dirty file. No automatic stash, commit, reset, or checkout of user changes.
2. **Create.** Use native isolation if exposed, or have a worker run
   `git worktree add -b <task-branch> <absolute-writable-path> <base_sha>`.
   Choose a permitted path rather than assuming a sibling directory is writable. Honor the
   environment's branch prefix. Confirm the writer's initial HEAD equals the intended SHA.
   Record exact created paths and branches, including any native initial branch, with ownership
   evidence. Native isolation may start at a different base; cut the working branch from the
   supplied SHA before editing. Allocate ports, databases, and output paths separately, or
   serialize operations using shared external state.
3. **Return.** Each writer reports `branch`, `base_sha`, `head_sha`, `worktree_path`,
   `initial_branch`, task-created resources, dirty status, verification evidence, and any
   push outcome with the remote SHA. A failed push is local WIP, not preserved remote WIP.
4. **Integrate and verify.** One worker checks returned SHAs against the pinned base and
   merges only successful work. Resolve conflicts with both writers' intent available.
   Preserve the pre-merge tip and report actual state on failure. Aborting a merge may leave
   earlier merges in the wave intact; do not claim it restored the last pushed tip. A separate
   worker verifies any conflict resolution. Repeat fix then verification before releasing
   dependants or cleaning up.
5. **Clean up.** Remove only resources explicitly recorded as task-created and still in their
   expected state. Check worktrees for uncommitted and untracked work first. Retain failed WIP
   unless every change is durably preserved and removing its checkout is authorized. Before
   deleting a local or remote branch, prove its current tip is included in the verified,
   preserved integration history; unique WIP remains even if its behavior was superseded.
   Recheck the remote tip immediately before deletion and use an expected-tip lease where
   supported. Branch names, absence of an origin counterpart, and matching base tips do not
   prove ownership. Report retained resources and cleanup failures with paths.

## Worked example

For a multi-file refactor, dispatch one reader to locate callers and another to identify
configuration dependencies. Each writes detailed findings to an artifact and returns a
short index. Send one writer the relevant paths and agreed scope. A separate worker checks
the resulting behavior and diff. Send any failing check back to the writer, then verify the
fix. A single-file change follows the same evidence discipline without necessarily needing
an independent reviewer.
