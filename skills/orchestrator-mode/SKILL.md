---
name: orchestrator-mode
description: Forces the main thread to act as an orchestrator and delegate ALL work to subagents instead of doing it itself. Use when the user says "orchestrator mode", "use subagents", "delegate everything", "swarm this", or otherwise asks the main thread to coordinate rather than execute. Agent-neutral — works on Claude Code, Cursor, Cortex Code, and any agent with a delegation tool.
---

# Orchestrator Mode

The main thread is a **coordinator**, not a worker. Every concrete task — reading
files, searching code, running SQL, editing, verifying — is delegated to a
subagent. The main thread only plans, dispatches, and synthesizes.

Agent-neutral: it names *roles* (search agent, coding agent), not tools — map each to your agent's concrete tool via [Tool Mapping](#tool-mapping).

## Hard Rules

1. **The main thread may only call** the delegation tool, the plan/todo tool, and
   user-facing question/report tools. Every file / search / shell / web / edit tool is
   forbidden in the main thread — delegate it.
2. **Every** user request is decomposed into one or more subagent dispatches.
3. **Parallelize when independent.** Dispatch data-independent subtasks together in one
   message; collect each result (returned inline, or via background output files).
4. **Pick the right subagent** — a specialist if your agent offers one, else general-purpose. See [Subagent Selection](#subagent-selection).
5. **Highest-effort coding model for any subagent that writes code.** Write-intent
   dispatches (models, SQL, refactors, file edits) get the best coding model your agent
   allows; research / verification dispatches inherit the parent (leave model unset).
6. **Verify with a separate subagent** — implementation and verification are always separate dispatches.
7. **Isolated worktrees for parallel writers.** When two or more write-intent dispatches
   run in parallel, each gets its own worktree + branch, and integration is a separate
   dispatch — see [Parallel Writes (Worktrees)](#parallel-writes-worktrees).

## Workflow

1. **Plan** — write a TODO list enumerating the subagent dispatches.
2. **Dispatch** — call the delegation tool with a fully self-contained prompt (subagents are stateless).
3. **Fan out** — independent subtasks go in one message as parallel dispatches; collect each result before the dependent step.
4. **Synthesize** — read reports, update TODOs, dispatch follow-ups.
5. **Verify** — before marking done, dispatch a verification subagent (reviewer, or a build / SQL check).
6. **Report** — summarize to the user in 1–3 sentences, including any artifact paths/IDs returned.

## Subagent Selection

Pick by *capability*, not a fixed name — built-in rosters are small and differ per tool:

- **Find files, search code, "where is X", read many files** → read-only search/explore agent.
- **Web research, fetch and summarize pages** → general-purpose agent with web tools.
- **Run SQL, explore a warehouse, check row counts** → SQL/data specialist if you have one, else general-purpose.
- **Build / verify code, run tests** → shell/build agent, else general-purpose.
- **Multi-step coding, refactors, anything else** → general-purpose agent.
- **Review / verify another agent's output** → a *separate* general-purpose reviewer.

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

Read-only fan-outs and single writers skip this — isolation pays off only when two
or more writers would otherwise share one working tree.

1. **Precondition** — fold a `git status` check into the planning fan-out's read-only
   dispatch. Dirty tree → ask the user (commit / stash / proceed): worktrees branch
   from HEAD, so uncommitted changes are invisible to the writers. Not a git repo, or
   no worktree mechanism available → fall back to sequential writes.
2. **Dispatch** — partition tasks so writers touch disjoint files where possible. Each
   writer works in an isolated worktree and commits to its own branch (native isolation,
   or worktree creation as the prompt's first step — see [Tool Mapping](#tool-mapping)).
3. **Integrate** — after all writers return, one dedicated dispatch merges the branches:
   it resolves mechanical conflicts (imports, lockfiles, formatting) itself and
   **escalates semantic ones**, reporting the conflicting branches/files/hunks so the
   orchestrator can dispatch a resolver with both writers' goals and decisions pasted
   verbatim. On success it removes worktrees and merged branches; on escalation it
   leaves everything in place, and the resolver performs the same cleanup once its
   merge succeeds. Return contract: `conflicts_found`, `worktrees_cleaned`.
4. **Verify** — on the unified tree, as a separate dispatch (Hard Rule 6); mandatory
   whenever any conflict was resolved, by anyone.

## Tool Mapping

Map the roles above to concrete tools (built-in rosters are minimal — custom agents fill the rest):

| Role (body language) | Claude Code | Cursor | Cortex Code |
|---|---|---|---|
| Spawn a subagent | `Agent` (formerly `Task`) | `Task` (in modes that grant it) | `RunSubagent` |
| Plan / todo tool | `TaskCreate`/`TaskUpdate` (or `TodoWrite`) | todo tool | `EnterPlanMode`/`ExitPlanMode` (no todo tool — track in replies) |
| Read-only search / explore agent | `Explore` | `explore` | `Explore` |
| Implementation / general agent | `general-purpose` | general / custom agent | `general-purpose` |
| Coding model for write intent | `model: opus` (research: `inherit`/unset) | highest-effort coding model | `model:` in a custom subagent's frontmatter (no per-dispatch override) |
| Isolated worktree per parallel writer | `isolation: "worktree"` on `Agent` | prompt's first step: `git worktree add ../wt-<task> -b <branch>` | request worktree isolation in the dispatch (branch `agent/<agentId>`) |
| Forbidden in main thread (examples) | `Read Grep Glob Edit Write Bash WebFetch WebSearch` | `Read Grep Shell` + edit/search tools | `Read Grep Glob Edit Write Bash WebFetch WebSearch SnowflakeSqlExecute` |

Built-in specialists are minimal (Claude Code → `Explore`, `Plan`, `general-purpose`;
Cursor → `explore`, `bash`, `browser`; Cortex Code → `Explore`, `Plan`, `general-purpose`,
all with native Snowflake SQL tools). Everything else (SQL, BI, CI, docs agents) is
custom to your setup — use it if present, else route to general-purpose.

## Worked Example (agent-neutral)

Refactor a function and verify it — the canonical good-practice shape:

1. **Plan** TODO: find callers, list configs, refactor, verify.
2. **Parallel dispatch** (one message, independent search agents): *"List callers of `foo()` as
   `file:line`"* and *"List config files setting DB timeouts; return path + value"*.
3. **Synthesize**, then **dispatch a coding agent** (write intent → highest-effort model):
   *"Refactor `foo()` per <findings pasted verbatim>; Decisions made: <…>; touch only <files>;
   return `files_changed`."*
4. **Verify** in a *separate* read-only dispatch (model unset): *"Run tests for the changed
   files; report pass/fail and failing test names."* The implementer never self-certifies.

(Two parallel writers instead of one? Each gets a worktree + branch, and an integration
dispatch precedes verification — see [Parallel Writes (Worktrees)](#parallel-writes-worktrees).)

## Anti-Patterns

- Reading a file in the main thread "just to check something" — delegate.
- A single megaprompt asking one subagent to do everything — split it.
- Sequential dispatch of independent tasks — parallelize.
- Two write-intent subagents sharing one working tree in parallel — isolate in worktrees.
- Summarizing prior findings instead of quoting verbatim — loss compounds.
- Tier 1 prompts for verification/implementation subagents — they need intent + rationale.

## Exit Criteria

Mode applies for the whole session unless the user says "exit orchestrator mode" or
"stop delegating".
