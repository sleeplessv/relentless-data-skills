# Orchestrator reference

Read the section the current dispatch needs.

- [Harness notes](#harness-notes): limits and defaults that tool schemas leave out.
- [Nesting sub-orchestrators](#nesting-sub-orchestrators): when and how a subtree gets its
  own coordinator.
- [Parallel writes worktrees](#parallel-writes-worktrees): isolation, integration, and
  cleanup for parallel writers.
- [Worked example](#worked-example): a refactor from search through verification.

## Harness notes

Facts the tool schemas leave out, checked against vendor docs in September 2026. The
named settings are the durable handle; check them when a number matters.

- **Questions.** Claude Code withholds `AskUserQuestion` from every subagent. Treat workers
  in any harness as unable to ask; their questions come back in `open_questions`.
- **Concurrency.** Claude Code runs up to 20 subagents
  (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`). Codex V2 defaults to 4 open threads
  (`agents.max_concurrent_threads_per_session`). Cortex Code allows 50 background agents.
  Cursor documents no cap.
- **Depth.** Claude Code allows 3 layers below the main thread
  (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`). Cursor allows 2; a grandchild cannot spawn.
  Codex V1 allows 1 (`agents.max_depth`); V2 has no depth setting. A Cortex Code
  background agent cannot spawn background agents.
- **Forks.** A Claude Code fork runs the parent's model and ignores a model override; use a
  clean worker when the task needs another model. A Codex spawn inherits the whole
  conversation by default; pass `fork_turns: "none"` for a clean worker.
- **Permission.** Codex's spawn tool does not count a request for depth or thoroughness as
  permission to spawn. Activating this skill is that permission; say so in the dispatch.
- **Worktree base.** Claude Code's native worktree isolation starts from `origin/<default>`
  unless the `worktree.baseRef` setting is `head`.
- **Completion.** Claude Code workers run in the background and report through completion
  notifications, so the coordinator waits for those notifications.

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

Designate a coordinator with a general worker; read-only search agents cannot dispatch.
Open its handoff with "Load the orchestrator-mode skill and coordinate this scope". Where
workers cannot load skills, paste this skill's SKILL.md into the handoff instead. The
coordinator returns its verification evidence with its other return fields.

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
   earlier successful merges intact; do not claim it restored the last pushed tip. A separate
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

For a refactor of `foo()` across several files, choose a run directory, then dispatch two
read-only search workers in one message. One lists callers of `foo()` as `file:line`; the
other lists configuration that sets the related timeouts. Each writes its findings to the
run directory and returns a short index. Send one writer the quoted index entries, the
agreed scope, and the decisions so far. A separate verifier runs the affected tests and
reviews the diff. A failing check goes back to the writer, then to a verifier again. A
single-file change keeps the same evidence, but its writer's diff and test output can
stand as the verification.
