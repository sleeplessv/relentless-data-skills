---
name: orchestrator-mode
description: Forces the main thread to act as an orchestrator and delegate ALL work to subagents instead of doing it itself. Use when the user says "orchestrator mode", "use subagents", "delegate everything", "swarm this", or otherwise asks the main thread to coordinate rather than execute.
---

# Orchestrator Mode

The main thread is a **coordinator**, not a worker. Every concrete task (reading files,
searching code, running SQL, editing, verifying) is delegated to a subagent; the main
thread only plans, dispatches, and synthesizes.

**Role, not tool/name.** This skill names *roles and capabilities* (search agent, coding
agent) — never a fixed tool or subagent name, since rosters differ per agent. Map each
role to your agent's concrete tool — see [references/reference.md](references/reference.md#tool-mapping).

## Hard Rules

1. **The main thread may only call** the delegation tool (including its management
   companions: continue, wait on, or stop a dispatch), the plan/todo tool, the
   skill-loading tool, and user-facing question/report tools. Every file / search /
   shell / web / edit tool is forbidden in the main thread — delegate it.
2. **Every** user request is decomposed into one or more subagent dispatches — but batch,
   don't atomize: one dispatch carries several atomic tasks in the same area. Never an
   agent per file.
3. **Parallelize when independent.** Dispatch data-independent subtasks together in one
   message; collect each result (returned inline, or via output files — reading a
   dispatch's returned output file is collecting its result, not forbidden work).
   Batching wins inside an area: same-area independent edits are one dispatch, not N
   parallel writers; parallelize across areas.
4. **Pick the right subagent** — a specialist if your agent offers one, else general-purpose. See [Subagent Selection](#subagent-selection).
5. **Match model tier to task complexity** — leave the model unset by default (the
   dispatch inherits the session model). Reach for the strongest coding tier when
   write-intent work spans multiple files, changes schema or data, or carries
   architectural impact; drop to a cheaper tier for simple or mechanical dispatches
   (single-file edits, read-only fan-outs). Mechanical trumps file count — but never
   the schema/data or architectural triggers, and an edit needing per-site judgement is
   not mechanical. Tiers are relative to the session model: escalation is a floor, so
   if the session model already is the strongest tier, leave the model unset — never
   pass a tier below it. Verification dispatches always inherit; a fix dispatch after a
   failed verification is sized to the fix. Reasoning effort is a separate dial — leave it at the default.
6. **Verify separately when blast radius is real** — write-intent work that merges to a
   shared branch, changes a schema or data, spans multiple files, or carries
   architectural impact gets its own verification dispatch. Read-only lookups,
   single-file edits, and search results do not — unless a trigger above fires (a
   one-file migration is a data change first): the returning agent's own output is the evidence.
7. **Isolated worktrees for parallel writers.** When two or more write-intent dispatches
   run in parallel, each gets its own worktree + branch, and integration is a separate
   dispatch — see [Parallel Writes (Worktrees)](references/reference.md#parallel-writes-worktrees).
   No worktree analogue for the shared resource (a warehouse schema, a live service), or
   a sweep too short to repay the isolation overhead → serialize those writers instead; that is the sanctioned sequential dispatch.
8. **Delegate coordination when the subtask has its own decomposition** — a subtask
   needing its own plan → dispatch → synthesize cycle (internal reports the parent never
   needs to see) is dispatched as a *sub-orchestrator*: its prompt says to invoke this
   skill and coordinate its scope, and the skill applies to it recursively ("main
   thread" then means the sub-orchestrator itself). Coordinators, like verifiers,
   always inherit the session model. Each layer verifies its own scope per Rule 6 and
   returns its verification evidence — below-threshold work returns
   `verification_evidence: none required` so the parent can tell it apart; the parent
   verifies what it integrates across children, plus any child work that arrived
   unverified once the merged whole clears Rule 6. Harness limits and caveats: see
   [Nesting (Sub-orchestrators)](references/reference.md#nesting-sub-orchestrators).

## Workflow

1. **Plan** — write a TODO list enumerating the subagent dispatches, scoped to what was
   asked; problems surfaced outside that scope get reported, not queued as extra dispatches.
2. **Dispatch** — call the delegation tool with a fully self-contained prompt (subagents are stateless).
3. **Fan out** — independent subtasks go in one message as parallel dispatches; collect each result before the dependent step.
4. **Synthesize** — read reports, update TODOs, dispatch follow-ups.
5. **Verify** — dispatch a verification subagent (reviewer, or a build / SQL check) when the
   work clears the Hard Rule 6 threshold; below it, the returned reports are the evidence.
6. **Report** — lead with the outcome, then artifact paths/IDs returned; 1–3 sentences total —
   unless the request was a question or analysis: then the answer is the deliverable, outcome first, at the length it needs.

## Subagent Selection

Pick by capability:

- **Find files, search code, "where is X", read many files** → read-only search/explore agent.
- **Web research, fetch and summarize pages** → general-purpose agent with web tools.
- **Run SQL, explore a warehouse, check row counts** → SQL/data specialist if you have one, else general-purpose.
- **Build / verify code, run tests** → shell/build agent; **multi-step coding, refactors, anything else** → general-purpose.
- **Review / verify another agent's output** (Rule 6 cases only) → a *separate* general-purpose reviewer.

**Prefer custom specialists** (SQL runner, BI agent, CI investigator, docs agent) if your
environment defines them. **Never invent a subagent type** — it must be one your agent
offers. Mark research / review dispatches read-only where supported.

## Prompt Requirements for Subagents

Subagents are **stateless by default** (a context-inheriting fork is the exception — see
the reference) — they cannot see the parent conversation, prior reports, or ask follow-ups. The dispatch prompt is their entire world; treat each as a **mini handoff
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
- **Return contract** — structured fields like `files_changed`, `tests_run`, `verification_evidence`, `decisions_made`, `open_questions`, `next_steps`.

**Continuity discipline:** quote prior findings verbatim (lossy summaries are the #1
cause of rework) — verbatim means unedited, not complete: paste the subset a dispatch
owns and say what was scoped out. Reference long artifacts by path/URL but name the
specific lines to read (the *producing* dispatch writes such an artifact and returns
its path plus a one-line-per-entry index); carry a cumulative "Decisions made" block
into every dispatch after the first.

## Parallel Writes (Worktrees)

Procedure for the Hard Rule 7 case (two or more parallel writers): see [references/reference.md](references/reference.md#parallel-writes-worktrees).

## Worked Example (agent-neutral)

Refactor-and-verify, the canonical shape (plan → parallel search fan-out → one
strongest-tier coding dispatch → separate model-unset verification): see
[references/reference.md](references/reference.md#worked-example).

## Anti-Patterns

- Reading a file in the main thread "just to check something" — delegate.
- A single megaprompt asking one subagent to do everything, or one agent per trivial
  task — split across areas, batch within them.
- Sequential dispatch of independent cross-area tasks — parallelize.
- A verification dispatch for work whose correctness is visible in the returned output — read the report.
- Two write-intent subagents sharing one working tree in parallel — isolate in worktrees.
- Upgrading every write dispatch to the strongest tier — match tier to complexity.
- A worker that starts coordinating mid-flight — designation happens at dispatch time.
- Re-verifying a child's already-verified internals — the parent checks the seams.
- Summarizing prior findings instead of quoting verbatim — loss compounds.
- Tier 1 prompts for verification or multi-step implementation subagents — they need intent + rationale.

## Activation & Exit

Naming the work makes it dispatches, however many ("use subagents to check X and Y" is
two dispatches, not this mode); the mode engages when delegation is asked for as a
standing way of working, then applies for the whole session unless the user says "exit
orchestrator mode" or "stop delegating". A direct user instruction to do one specific
thing in the main thread is honoured as a one-off, not an exit — the anti-pattern is the
main thread deciding on its own to peek. **Composition:** a skill running under this
mode may tighten these rules, and may override one where its text names the rule it
supersedes; where it is silent, this skill governs.
