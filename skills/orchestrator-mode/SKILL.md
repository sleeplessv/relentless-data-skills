---
name: orchestrator-mode
description: Forces the main thread to act as an orchestrator and delegate ALL work to subagents instead of doing it itself. Use when the user says "orchestrator mode", "use subagents", "delegate everything", "swarm this", or otherwise asks the main thread to coordinate rather than execute.
---

# Orchestrator Mode

The main thread is a **coordinator**, not a worker. Every concrete task — reading
files, searching code, running SQL, editing, verifying — is delegated to a
subagent. The main thread only plans, dispatches, and synthesizes.

**Role, not tool/name.** This skill names *roles and capabilities* (search agent, coding
agent) — never a fixed tool or subagent name, since rosters differ per agent. Map each
role to your agent's concrete tool — see [references/reference.md](references/reference.md#tool-mapping).

## Hard Rules

1. **The main thread may only call** the delegation tool, the plan/todo tool, and
   user-facing question/report tools. Every file / search / shell / web / edit tool is
   forbidden in the main thread — delegate it.
2. **Every** user request is decomposed into one or more subagent dispatches — but batch,
   don't atomize: one dispatch carries several atomic tasks in the same area. Never an
   agent per file.
3. **Parallelize when independent.** Dispatch data-independent subtasks together in one
   message; collect each result (returned inline, or via background output files).
4. **Pick the right subagent** — a specialist if your agent offers one, else general-purpose. See [Subagent Selection](#subagent-selection).
5. **Match model tier to task complexity** — leave the model unset by default (the
   dispatch inherits the session model). Reach for the strongest coding tier when
   write-intent work spans multiple files, changes schema or data, or carries
   architectural impact; drop to a cheaper tier for simple or mechanical dispatches
   (single-file edits, read-only fan-outs). Verification dispatches always inherit.
   Reasoning effort is a separate dial from model tier — leave it at the agent/user
   default.
6. **Verify separately when blast radius is real** — write-intent work that merges to a
   shared branch, changes a schema or data, or spans multiple files gets its own
   verification dispatch. Read-only lookups, single-file edits, and search results do
   not: the returning agent's own output is the evidence.
7. **Isolated worktrees for parallel writers.** When two or more write-intent dispatches
   run in parallel, each gets its own worktree + branch, and integration is a separate
   dispatch — see [Parallel Writes (Worktrees)](references/reference.md#parallel-writes-worktrees).

## Workflow

1. **Plan** — write a TODO list enumerating the subagent dispatches, scoped to what was
   asked; problems surfaced outside that scope get reported, not queued as extra dispatches.
2. **Dispatch** — call the delegation tool with a fully self-contained prompt (subagents are stateless).
3. **Fan out** — independent subtasks go in one message as parallel dispatches; collect each result before the dependent step.
4. **Synthesize** — read reports, update TODOs, dispatch follow-ups.
5. **Verify** — dispatch a verification subagent (reviewer, or a build / SQL check) when the
   work clears the Hard Rule 6 threshold; below it, the returned reports are the evidence.
6. **Report** — lead with the outcome, then artifact paths/IDs returned; 1–3 sentences total.

## Subagent Selection

Pick by capability:

- **Find files, search code, "where is X", read many files** → read-only search/explore agent.
- **Web research, fetch and summarize pages** → general-purpose agent with web tools.
- **Run SQL, explore a warehouse, check row counts** → SQL/data specialist if you have one, else general-purpose.
- **Build / verify code, run tests** → shell/build agent, else general-purpose.
- **Multi-step coding, refactors, anything else** → general-purpose agent.
- **Review / verify another agent's output** (Rule 6 cases only) → a *separate* general-purpose reviewer.

**Prefer custom specialists** (SQL runner, BI agent, CI investigator, docs agent) if your
environment defines them. **Never invent a subagent type** — it must be one your agent
offers. Mark research / review dispatches read-only where supported.

## Prompt Requirements for Subagents

Subagents are **stateless** — they cannot see the parent conversation, prior reports, or
ask follow-ups. The dispatch prompt is their entire world; treat each as a **mini handoff
document**. **Default to lightweight; escalate to rich when the next subagent depends on
prior output, implementation has architectural impact, or verification needs rationale.**

**Tier 1 — Lightweight (default)** for atomic tasks (lookups, single searches, trivial
edits): precise single-sentence **task**; **context** (paths, IDs, prior findings pasted
verbatim — no lossy summary); **constraints** (conventions, files to leave untouched);
**return contract** (exact fields/paths to report).

**Tier 2 — Rich handoff** (implementation, verification, or dependent subagents) adds:

- **Goal & intent** — *why*, not just *what*.
- **Prior findings** — verbatim excerpts from earlier reports, citing which agent (never paraphrase).
- **Decisions made & rationale** — choices already locked in, so this subagent does not relitigate them.
- **Artifacts so far** — files/IDs/branches/query results, with paths; **known unknowns** — what is *not* decided, so it flags rather than assumes (it cannot ask).
- **Suggested skills** to invoke; **sensitive-data note** — redact secrets/PII before pasting.
- **Return contract** — structured fields like `files_changed`, `tests_run`, `decisions_made`, `open_questions`, `next_steps`.

**Continuity discipline:** quote prior findings verbatim (lossy summaries are the #1
cause of rework); reference long artifacts by path/URL but name the specific lines to
read; carry a cumulative "Decisions made" block into every dispatch after the first.

## Parallel Writes (Worktrees)

Procedure for the Hard Rule 7 case (two or more parallel writers) — precondition,
dispatch, integrate, verify: see [references/reference.md](references/reference.md#parallel-writes-worktrees).

## Worked Example (agent-neutral)

Refactor a function and verify it — the canonical good-practice shape:

1. **Plan** TODO: find callers, list configs, refactor, verify.
2. **Parallel dispatch** (one message, independent search agents): *"List callers of `foo()` as
   `file:line`"* and *"List config files setting DB timeouts; return path + value"*.
3. **Synthesize**, then **dispatch a coding agent** (strongest tier — multi-file refactor):
   *"Refactor `foo()` per <findings pasted verbatim>; Decisions made: <…>; touch only <files>;
   return `files_changed`."*
4. **Verify** in a *separate* read-only dispatch (model unset): *"Run tests for the changed
   files; report pass/fail and failing test names."* A multi-file refactor clears the Rule 6
   threshold; a lookup would not.

(Two parallel writers instead of one? Each gets a worktree + branch, and an integration
dispatch precedes verification — see [Parallel Writes (Worktrees)](references/reference.md#parallel-writes-worktrees).)

## Anti-Patterns

- Reading a file in the main thread "just to check something" — delegate.
- A single megaprompt asking one subagent to do everything — split it.
- Sequential dispatch of independent tasks — parallelize.
- A verification dispatch for work whose correctness is already visible in the previous
  agent's returned output — read the report instead.
- One agent per trivial task where one agent could have carried five — batch them.
- Two write-intent subagents sharing one working tree in parallel — isolate in worktrees.
- Upgrading every write dispatch to the strongest tier regardless of complexity — match
  the tier instead.
- Summarizing prior findings instead of quoting verbatim — loss compounds.
- Tier 1 prompts for verification/implementation subagents — they need intent + rationale.

## Activation & Exit

A single named delegation ("use a subagent to check X") is one dispatch, not this mode;
the mode engages when delegation is asked for as a way of working, then applies for the
whole session unless the user says "exit orchestrator mode" or "stop delegating".
