# Orchestrator Mode, Reference

## Contents

- [Tool Mapping](#tool-mapping): roles in SKILL.md mapped to Claude Code, Cursor, Cortex Code, and Codex tools.
- [Nesting (Sub-orchestrators)](#nesting-sub-orchestrators): Rule 8 mechanics, per-harness depth and concurrency limits, background execution.
- [Parallel Writes (Worktrees)](#parallel-writes-worktrees): Rule 7 procedure, base-branch guard, integration and cleanup.
- [Worked Example](#worked-example): the canonical refactor-and-verify shape.
- [Anti-Patterns](#anti-patterns): ten failure shapes and their fixes.

## Tool Mapping

Map the roles in SKILL.md to concrete tools (built-in rosters are minimal; custom agents fill the rest).
Facts below come from each vendor's docs; where a doc is silent, the cell says so.

| Role (body language) | Claude Code | Cursor | Cortex Code | Codex |
|---|---|---|---|---|
| Spawn a subagent | `Agent` (formerly `Task`): `subagent_type`, `prompt`, `model`, `isolation`; runs in the background by default, result arrives as a completion notification | `Task` (`subagent_type`, `prompt`) or `/name`; needs Task access in the current mode; hooks and tool policies can block it | `RunSubagent` (changelog alias `task`); "Run a background agent ..." returns an agent ID | `spawn_agent` (`task_name`, `message`, `agent_type`, `fork_turns`, `model`, `reasoning_effort`); on by default in app, CLI, IDE |
| Plan / todo tool | `TaskCreate`/`TaskUpdate` (or `TodoWrite`); absent by default on current models unless `CLAUDE_CODE_ENABLE_TODO_TOOLS=1`; else track in the reply | Plan Mode plan/to-do tools only; in Agent mode track in the reply | `EnterPlanMode`/`ExitPlanMode`; a todo viewer exists (Alt-T) but no todo tool; track in the reply | `update_plan` (checklist); `/plan` is a separate read-only mode |
| Read-only search / explore agent | `Explore` | `Explore` (built-in, faster model) | `explore` (depth quick / medium / very thorough) | `explorer` |
| Implementation / general agent | `general-purpose` (or `claude`) | custom subagent in `.cursor/agents/` (also reads `.claude/agents/` and `.codex/agents/`); no general built-in | `general-purpose`; custom in `.cortex/agents/` or `.claude/agents/` | `worker` (writes), `default` (general); custom TOML in `.codex/agents/` |
| Verification agent (Rule 6) | separate `general-purpose` reviewer | `Bash` built-in for tests; custom `readonly: true` reviewer | `Review` tool, else `general-purpose` | custom agent with read-only `sandbox_mode`, else `default` |
| Model tier per dispatch | `model:` on `Agent`, unset by default; strongest coding tier is `opus`; an org allowlist or `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` may override | `model:` in the subagent definition (`inherit` default); no per-call override; admin and plan limits override | `model:` on the tool (at least `inherit`) and in frontmatter (`auto`, model ID, `inherit`) | `model` / `reasoning_effort` on `spawn_agent` when exposed, else per-agent TOML; inherit by default |
| Isolated worktree per parallel writer | `isolation: "worktree"`; base is `origin/<default>` unless `worktree.baseRef` is `head`; writer returns `base_sha` | ask in the prompt ("each in its own environment"): native worktree and branch, parent merges; base undocumented, return `base_sha`; fallback `git worktree add` | "with worktree isolation" in the prompt; branch `agent/<agentId>`; base undocumented, return `base_sha` | no native subagent isolation: prompt's first step `git worktree add ../wt-<task> -b <branch>` inside the sandboxed workspace |
| Ask the user a question | `AskUserQuestion` (never available to subagents) | Ask questions tool | `AskUserQuestion` | ask in the reply (Plan mode prompts natively) |
| Continue / wait on / stop a dispatch | `SendMessage` (resume by ID), `TaskStop`; load schemas via `ToolSearch`; results arrive as notifications, do not poll (`Monitor` watches commands, not agents) | resume by agent ID (state under `~/.cursor/subagents/`); foreground blocks; stopping the parent stops children | get output, wait on, or resume by agent ID (`/agents`, Ctrl-S) | `wait_agent`, `followup_task` (V2) or `resume_agent` (V1), `send_message`, `close_agent` |
| Context-inheriting dispatch | `subagent_type: "fork"`, skips the handoff, always runs the parent model (a `model:` override is ignored) | n/a (always clean context) | n/a | the default (`fork_turns: "all"`); pass `fork_turns: "none"` for the stateless handoff |
| Skill install path | `.claude/skills/` or `~/.claude/skills/` | `.cursor/skills/` or `.agents/skills/` (project-level so Cloud Agents see it) | `.cortex/skills/`, `.claude/skills/`, `~/.snowflake/cortex/skills/` (Desktop: `.snowflake/cortex/skills/`) | `.agents/skills/` (cwd, repo root, `$HOME`); `$name` to invoke |
| Forbidden in main thread (examples) | `Read Grep Glob Edit Write Bash WebFetch WebSearch NotebookEdit` | Read files, Edit files, Run shell commands, Search files and folders, Web, Browser | `Read Grep Glob Edit Write Bash WebFetch WebSearch SnowflakeSqlExecute` and the other Snowflake, Notebook, and Data tools | shell / command execution, file edits, web search, MCP tools |

All continue / wait / stop companions count as the delegation tool under Rule 1. Model caveats for
Rule 5: the floor applies to escalation only (an escalated dispatch never runs below the session
model; if the session model is already the strongest tier, leave it unset); leave reasoning effort
at the default; correctness comes from verification, not from the tier, because allowlists or a
forced subagent model can silently replace it.
Built-in specialists are minimal (Claude Code: `Explore`, `Plan`, `general-purpose`, `claude`, `fork`;
Cursor: `Explore`, `Bash`, `Browser`; Cortex Code: `general-purpose`, `explore`, `plan`,
`feedback`, with the Snowflake tools on `general-purpose`; Codex: `default`, `worker`,
`explorer`). Everything else (SQL, BI, CI, docs agents) is custom to your setup; use it if
present, else route to general-purpose. `.agents/skills/` serves Cursor and Codex; `.claude/skills/`
serves Claude Code and the Cortex Code CLI.

## Nesting (Sub-orchestrators)

Mechanics for Hard Rule 8. The designation is a Tier 2 dispatch prompt that opens with:
*"Invoke the orchestrator-mode skill; you are the coordinator for this scope"* (if
subagents cannot load skills in your harness, paste this skill's body verbatim into the
prompt instead), followed by the usual rich handoff (goal, prior findings verbatim,
decisions made, return contract including `verification_evidence`, and the remaining
spawn depth as `depth_remaining`, which the parent tracks by hand and decrements, since no
harness exposes it; at 0, do the work directly rather than invoking this skill). A designated
coordinator that finds it has no delegation tool does the work directly and says so in its report.

Harness limits (env var and config names are the durable handle; check them, not this file, when in doubt):

- **Claude Code.** Depth: 3 layers below the main thread (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`).
  Concurrency: 20 running (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`); a spawn past the cap
  fails with "Concurrent subagent limit reached" and must not be retried until one returns,
  so dispatch a large fan-out in batches. No per-session budget. At the depth limit the
  `Agent` tool is withheld from every subagent except a fork, whose `Agent` returns an
  error. Read-only built-ins (`Explore`, `Plan`) are not coordinators; designate
  `general-purpose` (or `claude`). Forks inherit context and are expected to execute rather
  than re-delegate. Dispatches run in the background by default and return as completion
  notifications (the same dispatch can notify more than once if it is resumed); `Agent` and
  `Skill` survive backgrounding, so a sub-orchestrator works as a background worker;
  `AskUserQuestion` never reaches a subagent. A worker inside a harness worktree is blocked
  from running git against the main checkout, so ask it about its own tree only. Workers still receive
  CLAUDE.md, a git status snapshot, and preloaded skills, which is why "Invoke the
  orchestrator-mode skill" works in a designation prompt.
- **Cursor.** Two layers: the main agent and its direct subagents can spawn; a grandchild
  cannot. Nested launches need `Task` access in the current mode. No documented concurrency cap.
  Whether subagents can invoke skills is undocumented, so keep the paste-the-body fallback.
- **Cortex Code.** Background agents cannot spawn background agents; at most 50 concurrent
  background agents; foreground nesting is undocumented. A sub-orchestrator whose children
  must run in the background is itself a foreground dispatch. Subagents inherit skill paths.
- **Codex.** V1: one layer (`agents.max_depth`, default 1; at the limit the spawn tool says
  "Solve the task yourself"). V2: no depth key; concurrency `agents.max_concurrent_threads_per_session`
  (default 4 in source). Subagents inherit skills and sandbox. The spawn tool treats requests
  for depth or thoroughness as no licence to spawn; the orchestrator-mode prompt is the explicit permission.

## Parallel Writes (Worktrees)

Read-only fan-outs and single writers skip this; isolation pays off only when two
or more writers would otherwise share one working tree.

1. **Precondition.** Fold a `git status` and `git rev-parse HEAD` check into the planning
   fan-out's read-only dispatch. Dirty tree → ask the user (commit / stash / proceed) and
   let the next dispatch run the chosen git command; a nested coordinator, which cannot
   ask, proceeds only if no writer touches a dirty path, else serializes and reports the
   dirty tree upward. Uncommitted changes are invisible to the writers. Then pin the base:
   a Claude Code `isolation: "worktree"` dispatch starts on `origin/<default>` (observed:
   one commit ahead of the coordinator's HEAD), not the session's HEAD, unless
   `worktree.baseRef` is `head` in settings; Cursor and Cortex Code do not document the
   base. So every writer's prompt names the intended base tip (branch and SHA), and the
   writer's first action is to note the branch it started on, then confirm or cut to the
   base (`git switch -c <branch> <base>`). Not a git repo, or no worktree mechanism
   available → fall back to sequential writes.
2. **Dispatch.** Partition tasks so writers touch disjoint files where possible. Each
   writer works in an isolated worktree and commits to its own branch (native isolation,
   or worktree creation as the prompt's first step; see [Tool Mapping](#tool-mapping)).
   Each writer's return contract includes `branch`, `base_sha`, `harness_branch` (the
   branch the worktree started on, or `none`), and `worktree_path` (`git rev-parse --show-toplevel`).
3. **Integrate.** After all writers return, one dedicated dispatch checks every `base_sha`
   against the intended tip (a mismatch is escalated, not merged; a consumer skill that
   pins a baseline SHA and cuts every branch from it may drop this check by naming it),
   then merges the branches. It resolves mechanical conflicts (imports, lockfiles,
   formatting) itself and **escalates semantic ones**, reporting the conflicting
   branches/files/hunks so the orchestrator can dispatch a resolver with both writers'
   goals and decisions pasted verbatim (integration inherits the session model; a resolver
   takes the strongest coding tier, since semantic conflicts cross two writers' intents).
   On success it removes the writers' worktrees (their harness locks release when the
   writer finishes), the merged writer branches, and each returned `harness_branch`
   once it confirms that branch has no worktree, no `origin/` counterpart, and no commits
   beyond the base; a `git worktree list --porcelain` taken after the writers switched
   branches no longer shows the harness branches, so the returned field is the evidence.
   Delete only branches identified those two ways. On escalation it leaves everything in
   place, and the resolver performs the same cleanup once its merge succeeds. Return
   contract: `conflicts_found`, `worktrees_cleaned`.
4. **Verify.** On the unified tree, as a separate dispatch: merged parallel writers always
   clear the Hard Rule 6 threshold. Mandatory whenever any conflict was resolved, by anyone.

## Worked Example

Refactor a function and verify it, the canonical good-practice shape (plan, parallel
search fan-out, one strongest-tier coding dispatch, separate model-unset verification):

1. **Plan** TODO: find callers, list configs, refactor, verify.
2. **Parallel dispatch** (one message, independent search agents): *"List callers of `foo()` as
   `file:line`"* and *"List config files setting DB timeouts; return path + value"*.
3. **Synthesize**, then **dispatch a coding agent** (strongest tier, for a multi-file refactor):
   *"Refactor `foo()` per <findings pasted verbatim>; Decisions made: <…>; touch only <files>;
   return `files_changed`."*
4. **Verify** in a *separate* read-only dispatch (model unset): *"Run tests for the changed
   files; report pass/fail and failing test names."* A multi-file refactor clears the Rule 6
   threshold; a lookup would not.

(Two parallel writers instead of one? Each gets a worktree + branch, and an integration
dispatch precedes verification; see [Parallel Writes (Worktrees)](#parallel-writes-worktrees).)

## Anti-Patterns

- Reading a file in the main thread "just to check something": delegate.
- A single megaprompt asking one subagent to do everything, or one agent per trivial
  task: split across areas, batch within them.
- Sequential dispatch of independent cross-area tasks: parallelize.
- A verification dispatch for work whose correctness is visible in the returned output: read the report.
- Two write-intent subagents sharing one working tree in parallel: isolate in worktrees.
- Upgrading every write dispatch to the strongest tier: match tier to complexity.
- A worker that starts coordinating mid-flight: designation happens at dispatch time.
- Re-verifying a child's already-verified internals: the parent checks the seams.
- Summarizing prior findings instead of quoting verbatim: loss compounds.
- Tier 1 prompts for verification or multi-step implementation subagents: they need intent + rationale.
