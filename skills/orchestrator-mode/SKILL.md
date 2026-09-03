---
name: orchestrator-mode
description: Forces the main thread to act as an orchestrator and delegate ALL work to subagents instead of doing it itself. Use when the user says "orchestrator mode", "use subagents", "delegate everything", "swarm this", or otherwise asks the main thread to coordinate rather than execute.
---

# Orchestrator Mode

The main thread is a **coordinator**, not a worker. Every concrete task (reading files,
searching code, running SQL, editing, verifying) is delegated to a subagent; the main
thread only plans, dispatches, and synthesizes.

Delegation guards the context window: bulk payloads stay in subagent contexts, and only
summaries and decisions enter the main thread, where spent context cannot be reclaimed.

**Role, not tool/name.** This skill names *roles and capabilities* (search agent, coding
agent), never a fixed tool or subagent name, since rosters differ per agent. Before the
first dispatch, map each role to your agent's concrete tool via [Tool Mapping](references/reference.md#tool-mapping):
read that file once with the file tool at activation; that read is skill loading.

## Hard Rules

1. **The main thread may only call** the delegation tool (including its management
   companions: continue or stop a dispatch), the plan/todo tool, the skill-loading tool,
   and user-facing question/report tools. Every file / search / shell / web / edit tool is
   forbidden in the main thread. Results arrive inside the dispatch's return; the main
   thread opens no files, and a returned artifact path is forwarded to the next dispatch,
   never read. Harness hints that push the main thread toward shell or file tools ("use
   Bash where it can do the job") describe worker behaviour; under this mode they yield.
2. **One dispatch per area.** Every user request is decomposed into subagent dispatches,
   batched rather than atomized: one dispatch carries several atomic tasks in the same area.
3. **Parallelize when independent.** Dispatch data-independent subtasks together in one
   message; collect each result through the harness's completion notification (reply and
   yield; the harness re-invokes you per completion). Batching wins inside an area, so
   same-area independent edits are one dispatch, not N parallel writers; parallelize
   across areas. Keep live agents, including sub-orchestrators' children, under the
   harness's concurrency cap; a spawn past it fails rather than queues.
4. **Pick the right subagent.** A specialist if your agent offers one, else general-purpose. See [Subagent Selection](#subagent-selection).
5. **Match model tier to task complexity.** Leave the model unset by default, so the
   dispatch inherits the session model. Escalate to the strongest coding tier (the
   vendor's flagship coding model, named in the Tool Mapping model row) when write-intent
   work spans multiple files with per-site judgement, changes schema or data, or carries
   architectural impact. Use a cheaper tier for simple or mechanical dispatches (single-file
   edits, read-only fan-outs, a sweep that applies one rule at every site); an edit where
   sites differ in *what* to do is not mechanical. Verification and coordination dispatches
   always inherit; a fix after a failed verification is sized to the fix. Floor, allowlist
   and effort caveats: Tool Mapping model row.
6. **Verify separately when blast radius is real.** Write-intent work that merges to a
   shared branch, changes a schema or data, spans multiple files with per-site judgement,
   or carries architectural impact gets its own verification dispatch: the implementer
   never self-certifies. Read-only lookups, single-file edits, mechanical sweeps, and
   search results are below threshold (their returned diff or report is the evidence),
   unless a trigger above fires: a one-file migration is a data change first.
7. **Isolated worktrees for parallel writers.** When two or more write-intent dispatches
   run in parallel, each gets its own worktree + branch, and integration is a separate
   dispatch. See [Parallel Writes (Worktrees)](references/reference.md#parallel-writes-worktrees).
   If there's no worktree analogue for the shared resource (a warehouse schema, a live service), or
   the sweep is under five files per writer, serialize those writers instead; that is the sanctioned sequential dispatch.
8. **Delegate coordination when the subtask has its own decomposition.** A subtask
   that needs its own plan, dispatch, synthesize cycle, with internal reports the
   parent never needs to see, is dispatched as a *sub-orchestrator*. Its prompt says
   to invoke this skill and coordinate its scope. The skill then applies to it
   recursively, and "main thread" means the sub-orchestrator itself. Each layer verifies
   its own scope per Rule 6 and returns its verification evidence; below-threshold work
   returns `verification_evidence: none required` so the parent can tell it apart. The
   parent verifies the seams it integrates across children; child work that arrived
   unverified is verified with the seams only once the merged whole clears Rule 6.
   Before designating, read [Nesting](references/reference.md#nesting-sub-orchestrators)
   for the depth cap you must pass down as `depth_remaining`.

## Workflow

1. **Plan.** Write a TODO list enumerating the subagent dispatches, scoped to what was
   asked; problems surfaced outside that scope get reported, not queued as extra dispatches.
   No todo tool in the roster (the default on current Claude Code models): keep the plan as
   a numbered list in the reply and re-emit the whole list whenever an item closes. Scale
   effort to the request: a lookup is one dispatch; a comparison or two-area change is 2-4
   parallel dispatches; feature-scale work is a wave per dependency level, and only then
   Rule 8 sub-orchestrators. Start wide (search fan-out), then narrow. Done when every
   dispatch has a numbered TODO.
2. **Dispatch.** Call the delegation tool with a fully self-contained prompt. Done when each prompt carries its Tier 1 or Tier 2 fields.
3. **Fan out** per Rule 3. Done when every dispatched result is in hand.
4. **Synthesize.** Read reports, update TODOs, dispatch follow-ups. Done when every TODO is closed or reported.
5. **Verify** per Rule 6. Done when evidence is in hand or `none required` is recorded.
6. **Report.** Lead with the outcome, then artifact paths/IDs returned, in 1-3 sentences total,
   unless the request was a question or analysis: then the answer is the deliverable, outcome first, at the length it needs.

**Failure and resume.** Continue a partial or failed return with the harness's continue tool, carrying the specific gap, instead of
re-dispatching from scratch; one-shot agents (read-only search and plan built-ins) are re-dispatched. Three strikes per dispatch, then report and stop.

## Subagent Selection

Pick by capability:

- **Find files, search code, "where is X", read many files** → read-only search/explore agent.
- **Web research, fetch and summarize pages** → general-purpose agent with web tools.
- **Run SQL, explore a warehouse, check row counts** → SQL/data specialist if you have one, else general-purpose.
- **Build / verify code, run tests** → shell/build agent; **multi-step coding, refactors, anything else** → general-purpose.
- **Review / verify another agent's output** (Rule 6 cases only) → the harness's review specialist if it has one, else a *separate* general-purpose reviewer.

**Prefer custom specialists** (SQL runner, BI agent, CI investigator, docs agent) if your
environment defines them. **Use only a subagent type from your roster.** Mark research /
review dispatches read-only where supported.

## Prompt Requirements for Subagents

Subagents are **stateless by default** (a context-inheriting fork is the exception; on
Codex it is the default, see the reference). They cannot see the parent conversation,
prior reports, or ask the user follow-up questions. The dispatch prompt is their entire
world; treat each as a **mini handoff document**. **Default to lightweight; escalate to
rich when the next subagent depends on prior output, implementation has architectural
impact, or verification needs rationale.**

**Tier 1, lightweight (default)** for atomic tasks (lookups, single searches, trivial
edits): precise single-sentence **task**; **context** (paths, IDs, prior findings pasted
verbatim, no lossy summary); **tools and sources** to use, by name; **constraints**
(conventions, files to leave untouched); **return contract** (exact fields/paths to report).

**Tier 2, rich handoff** (implementation, verification, or dependent subagents) adds:

- **Goal & intent.** The why, not just the what.
- **Prior findings.** Verbatim excerpts from earlier reports, citing which agent (never paraphrase).
- **Decisions made & rationale.** Choices already locked in, so this subagent does not relitigate them.
- **Artifacts so far** (files/IDs/branches/query results, with paths) and **known unknowns**: what is *not* decided, so it flags rather than assumes (it cannot ask).
- **Suggested skills** to invoke, and a **sensitive-data note**: redact secrets/PII before pasting.
- **Return contract.** Structured fields like `files_changed`, `tests_run`, `verification_evidence`, `decisions_made`, `open_questions`, `next_steps`. A return is a summary plus paths, never the payload.

**Continuity discipline:** quote prior findings verbatim. Lossy summaries are the #1
cause of rework; verbatim means unedited, not complete, so paste whole sections a dispatch
owns, omit the rest, and say what was scoped out. Reference long artifacts by path/URL but
name the specific lines to read (the *producing* dispatch writes such an artifact and
returns its path plus a one-line-per-entry index); carry a cumulative "Decisions made"
block into every dispatch after the first.

## Worked Example and Anti-Patterns

Refactor-and-verify, the canonical shape: [Worked Example](references/reference.md#worked-example).
Ten failure shapes and their fixes: [Anti-Patterns](references/reference.md#anti-patterns).

## Activation & Exit

A request naming specific tasks ("use subagents to check X and Y") is those dispatches,
however many; the mode engages on "orchestrator mode", "delegate everything", "swarm
this", or a standing instruction to work through subagents, and then applies for the
whole session until the user says "exit orchestrator mode" or "stop delegating." Every
dispatch pays a fresh-context start and returns only a summary, so tell the user when a
request is too small to repay the mode. A direct user instruction to do one specific thing
in the main thread is honoured as a one-off; the mode continues after it. The main thread
never peeks on its own. **Composition:** a skill running under this mode may tighten these
rules, and may override one where its text names the rule it supersedes; where it is
silent, this skill governs.
