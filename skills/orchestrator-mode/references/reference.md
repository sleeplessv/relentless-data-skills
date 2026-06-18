# Orchestrator Mode — Reference

## Tool Mapping

Map the roles in SKILL.md to concrete tools (built-in rosters are minimal — custom agents fill the rest):

| Role (body language) | Claude Code | Cursor | Cortex Code |
|---|---|---|---|
| Spawn a subagent | `Agent` (formerly `Task`) | `Task` (in modes that grant it) | `RunSubagent` |
| Plan / todo tool | `TaskCreate`/`TaskUpdate` (or `TodoWrite`) | todo tool | `EnterPlanMode`/`ExitPlanMode` (no todo tool — track in replies) |
| Read-only search / explore agent | `Explore` | `explore` | `Explore` |
| Implementation / general agent | `general-purpose` | general / custom agent | `general-purpose` |
| Coding model for write intent | `model:` = strongest coding model available; don't raise thinking (research: unset) | strongest coding model | `model:` in a custom subagent's frontmatter (no per-dispatch override) |
| Isolated worktree per parallel writer | `isolation: "worktree"` on `Agent` | prompt's first step: `git worktree add ../wt-<task> -b <branch>` | request worktree isolation in the dispatch (branch `agent/<agentId>`) |
| Forbidden in main thread (examples) | `Read Grep Glob Edit Write Bash WebFetch WebSearch` | `Read Grep Shell` + edit/search tools | `Read Grep Glob Edit Write Bash WebFetch WebSearch SnowflakeSqlExecute` |

Built-in specialists are minimal (Claude Code → `Explore`, `Plan`, `general-purpose`;
Cursor → `explore`, `bash`, `browser`; Cortex Code → `Explore`, `Plan`, `general-purpose`,
all with native Snowflake SQL tools). Everything else (SQL, BI, CI, docs agents) is
custom to your setup — use it if present, else route to general-purpose.

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
