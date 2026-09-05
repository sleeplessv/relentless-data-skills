---
name: orchestrator-mode
description: Coordinate work through subagents while keeping bulk findings out of the main context. Use when the user requests orchestrator mode, delegation of named tasks, or coordination rather than direct execution.
---

# Orchestrator mode

Delegate repository exploration, research, edits, commands, and verification. The main
thread loads relevant skills, plans, dispatches, handles user decisions, and synthesizes
compact reports. System and developer instructions and the user's scope still govern.

## Scope and tools

A request such as "use subagents to check X and Y" delegates those tasks. Explicit
"orchestrator mode" or "delegate everything" applies until the user changes that
instruction. Honor a request to work directly without requiring an exact exit phrase.

Use the active tool schemas to identify spawn, message, resume, wait, stop, and optional
planning capabilities. Omit unsupported fields and use a general worker when no
specialist is exposed. Loading a skill or its relevant reference through a file or
shell read is allowed; delegate ordinary repository reads. If delegation is unavailable,
report that limitation and follow any already-authorized direct-work fallback.

Leave model and reasoning effort unset by default. Override only when the user or an
applicable instruction calls for it and the active schema supports the combination.
Check context inheritance before dispatch. For a self-contained task, use a clean or
bounded context when supported; use a full fork only when it needs conversation history.
Model overrides may require a non-full fork. Runtime schemas decide this, not vendor names.

## Workflow

1. **Plan by area.** Batch related work into a bounded dispatch with a checkable outcome.
   Keep a short plan in the available plan tool or conversation. Report changes to the
   plan rather than repeating the whole list. Report adjacent problems without expanding
   the user's scope.
2. **Dispatch independent work.** Assign each worker its task, owned files or resources,
   inputs, constraints, and return contract. Parallelize only within available capacity.
   Count the root, siblings, and descendants; keep a slot for executable leaf work.
   Prefer flat waves. For a subtree that earns separate coordination, read
   [Nesting](references/reference.md#nesting-sub-orchestrators) first.
3. **Collect and continue.** Use completion notifications and available wait tools according
   to their actual semantics. Keep the turn active while required work remains. Resume an
   existing worker with the specific gap rather than restarting its investigation. An
   unchanged failure calls for diagnosis or another approach, not repeated identical retries.
   Continue independent work while a blocked dependency waits for user or external input.
4. **Integrate.** Serialize writers sharing a checkout or external resource. Parallel code
   writers use separate worktrees and branches with an immutable base SHA and a dedicated
   integration worker. Small edits can simply use one writer. Before creating worktrees,
   read [Parallel writes](references/reference.md#parallel-writes-worktrees).
5. **Verify.** Every implementer inspects its actual diff and runs proportionate checks.
   Add a separate verification dispatch for merged parallel work, schema or data changes,
   architectural changes, or multi-file changes requiring different decisions per site.
   A small edit may not need an independent reviewer; it still needs artifact evidence.
   Verify the integrated seams, reusing child evidence for unchanged internals. A verifier
   that fixes code sends those fixes to another worker for verification.
6. **Report.** Lead with the outcome and returned artifact paths or IDs. Include relevant
   verification results and unresolved limitations. Finish only when the requested work
   is complete or a concrete blocker prevents further useful authorized progress.

## Handoffs

Give a worker only the context it needs:

- Task and completion criterion, scope, owned paths, and permissions already established.
- Relevant decisions and rationale, unresolved questions, and applicable skill paths.
- Input artifact paths with section names or line locations. Quote exact text when wording
  is binding; otherwise use a faithful concise summary with source locations.
- Return fields appropriate to the work, such as `status`, `files_changed`, `tests_run`,
  `verification_evidence`, `decisions_made`, `open_questions`, and `artifact_path`.

Workers put large findings and command output in artifacts and return a compact summary
plus an index. The main thread forwards those paths to consumers. Keep cumulative decisions
in one handoff artifact and pass only relevant updates, including on inherited forks.
Workers surface decisions requiring the user to the coordinator and continue independent
work. Reuse guidance already loaded; explicit skill requirements remain in force.

## Composition

A consumer skill may refine this workflow for its task, for example requiring isolation
for a single ticket or using an integration worker as the independent verifier when it
wrote none of the changes. Resolve actual conflicts against scope, permission, ownership,
and verification evidence. Tool availability and higher-priority instructions still apply.
