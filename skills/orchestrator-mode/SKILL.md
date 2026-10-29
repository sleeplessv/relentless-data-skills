---
name: orchestrator-mode
description: Coordinate work through subagents so bulk output stays out of the main context. Use when the user asks for orchestrator mode or asks to hand specific tasks to subagents.
---

# Orchestrator mode

The main thread coordinates; workers read, search, edit, run commands, and verify. Every
file, search result, and command output that enters the main thread stays there for the
rest of the session, so bulk material lives in worker contexts and the coordinator holds
plans, decisions, and compact reports.

## Activation

- **Scoped.** "Use subagents to check X and Y" dispatches X and Y. Outside those tasks the
  main thread works normally.
- **Standing.** "Orchestrator mode", `/orchestrator-mode` appended to a request, or "delegate
  everything" covers every later request in the session, a one-line edit or a `git status`
  included: each is a new dispatch. The user ends or pauses it in words such as "end
  orchestration" or "do this one yourself"; after a one-off the mode resumes.

Each dispatch pays for a fresh start and returns only a summary. When the request that
starts the mode is too small to repay that, say so and offer to answer directly.

## What the coordinator does itself

In standing mode, and for the named tasks in scoped mode, the coordinator calls only:

- spawn, message, resume, wait, and stop tools for workers;
- the plan or todo tool;
- skill loading, including a file read of a skill's SKILL.md or a reference it points to;
- tools that ask the user a question or report to them.

Every other action is a dispatch, including a quick look at one file, a `git` or `gh`
status check, a commit, push, or worktree command, and starting an app. The rule holds
after a consumer skill loads. A compaction drops this skill from context, so keep
`Orchestrator mode: standing; coordinator dispatches only` as the first plan item, and
reload this skill before the first action after a compaction notice. A returned artifact
path goes to the next worker that needs it; the coordinator acts on the returned summary
and, when the summary falls short, resumes that worker with the specific gap. Environment
hints that steer toward shell or file tools ("use Bash wherever it can do the job")
describe how workers act; pass them on in handoffs.

## Choosing workers

- **Locate** files or code, answer "where is X", or skim many files: the read-only search
  agent. It finds code; reviews and audits go to a general worker.
- **Change or run** anything (edits, commands, tests, queries, web research): the general
  worker, or a specialist the roster lists for that domain, such as SQL or CI.
- **Verify** another worker's output: a different worker from the writer, read-only where
  the harness supports it.
- **Fork** (a worker that inherits this conversation) only when the task needs that
  history. It still gets a task, owned paths, and a return contract.

Leave model and reasoning effort unset unless the user or a consumer skill sets them.

## Sizing

- A lookup is one dispatch.
- A comparison, or a change across two areas, is two to four parallel dispatches.
- Feature-sized work runs in waves, one per dependency level.

Give one worker several related tasks in the same area; run different areas in parallel.
Keep at most four workers running, nested ones included, unless
[Harness notes](references/reference.md#harness-notes) gives this environment a higher
limit. A spawn past the limit fails rather than queues: wait for a
completion, then dispatch it. Keep dispatches flat; before giving a subtree its own
coordinator, read [Nesting](references/reference.md#nesting-sub-orchestrators).

## Workflow

1. **Plan.** Split the request into dispatches by area, scoped to what the user asked.
   Report problems found outside that scope to the user and leave them out of the plan.
   Choose one run directory at an absolute path every worker can write, outside the
   repository (the session scratchpad when one exists). Keep the plan in the plan tool or
   as a numbered list in the reply, and report changes rather than repeating it. When the
   request changes a branch or PR, state its end state (uncommitted, committed, or pushed)
   and ask once if the user hasn't said. Done when every dispatch has a task, owned paths,
   and a done-when, and the run directory is named.
2. **Dispatch.** Launch independent dispatches together in one message, each with a full
   [handoff](#handoffs). Done when every dispatch in the current wave is running.
3. **Collect.** Wait through completion notifications or the wait tool. Resume a worker
   only for a narrow gap in the task it just did, at most twice: the coordinator cannot
   see a worker's context, and a third resume usually lands past 110k tokens. A new
   phase (integration, fixes, verification, the PR) or a third need gets a fresh worker
   briefed by artifact path. When a retry fails the same way, diagnose or change
   approach; after three failed attempts on one dispatch, report it as blocked. Keep
   independent work moving while a dependency waits on the user. Done when every worker
   in the wave has returned or is reported blocked.
4. **Integrate.** One writer handles small edits. Writers that share a checkout or an
   external resource run one after another. Parallel code writers each get a worktree and
   branch from a pinned base SHA, and one integration worker merges them; read
   [Parallel writes](references/reference.md#parallel-writes-worktrees) before creating
   worktrees. Done when all accepted work sits in one tree and, for parallel writers, each
   branch and head SHA is recorded.
5. **Verify.** Each writer reviews its own diff and runs the checks that cover its change.
   Dispatch a separate verifier for merged parallel work, schema or data changes,
   architectural changes, or multi-file changes that need a different decision at each
   site. The verifier reports problems, the writer fixes them, and a verifier checks again.
   In a nested run, verify the seams between children and reuse their evidence for the
   parts they own. Done when every change has evidence: a verifier's pass or, for a small
   edit, the writer's diff and check output.
6. **Report.** Lead with the outcome, then returned artifact paths or IDs, verification
   results, and open limitations, at the length the user needs to act on them. When the
   request was a question, the answer is the deliverable. The run directory
   dies with the session, so when a run produced research worth reusing, have a worker
   save it to the repo's `docs/research/` (or the project's equivalent) and report that
   path. Once the run's PRs merge, offer to remove its worktrees and branches, following
   [Clean up](references/reference.md#parallel-writes-worktrees) or a branch-cleanup skill
   such as `cleanup-merged-branches` when installed. Done when the requested work is
   complete or a concrete blocker stops further authorized progress.

## Handoffs

A worker sees its dispatch prompt and the project instructions its harness loads, such as
CLAUDE.md or AGENTS.md. It cannot see this conversation, earlier reports, or files other
workers read, and it cannot ask the user. Write each handoff as its complete briefing:

- **Task** with its done-when, owned paths or resources, and permissions already granted.
- **Goal**: why the work matters, for implementation and verification tasks.
- **Decisions** so far with their reasons, and open questions to flag rather than guess.
- **Prior findings**, quoted word for word from the returned summaries. Paste the parts
  this task needs and name what was left out; for a long artifact, give its path and the
  lines or section to read. Redact secrets and personal data.
- **Run directory** path, to create if missing, and the skills to load, by path.
- **Return contract**: fields such as `status`, `files_changed`, `tests_run`,
  `verification_evidence`, `decisions_made`, `open_questions`, and `artifact_path`.

Workers send long command output (test runs, logs, query results) to a file in the run
directory and read back only the lines the task needs (failures, errors, the counted
result); large findings go there too, with a short summary and one index line per
artifact entry returned. Those files and the harness's task-output file are for the next
worker. Split findings meant for several workers into one artifact per recipient, so
none reads the whole file. Carry a running list of decisions into every handoff after
the first, trimmed to what that task touches. Workers put questions for the user in
`open_questions` and continue independent work. The coordinator settles each returned
question it can from the user's earlier decisions, the repo's conventions, or one more
worker check, records the answer in the decision list, and brings the user only what
needs their authority (business choices, scope changes, destructive or paid actions),
each with a recommended default.

## Composition

A consumer skill may tighten these rules for its task, such as isolating even a single
ticket in a worktree, or replace one where it says so, such as letting an integration
worker that wrote none of the changes act as the verifier. Where it says nothing, this
skill applies.
