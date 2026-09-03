# orchestrator-mode

The **`orchestrator-mode`** agent skill turns the main thread into a pure
**coordinator**: it never reads, searches, edits, or runs anything itself.
Every concrete task is delegated to a subagent. The main thread only plans,
dispatches, verifies, and synthesizes.

It is **agent-neutral**: the body talks in roles ("delegate", "search agent",
"coding agent") and a single mapping table maps those roles to the concrete
tools on **Claude Code**, **Cursor**, and **Cortex Code** (Snowflake's `cortex`
CLI). Custom specialists in your own setup slot in wherever you have them.

## What it does

- **Hard delegation rule.** The main thread may only call the delegation tool,
  the plan/todo tool, and user-facing question/report tools. Every file /
  search / shell / web / edit tool is forbidden; it gets delegated.
- **Parallel fan-out, with a floor.** Independent subtasks are dispatched together
  in one message and collected, instead of run sequentially, but small related
  tasks are batched into one dispatch rather than one agent per file.
- **Capability-based subagent selection.** Pick the agent by what the task
  needs (search, web research, SQL, build, coding, review), preferring a custom
  specialist if you have one and falling back to general-purpose.
- **Model discipline.** Dispatches inherit the session model by default. The
  strongest coding tier is reserved for write-intent work with real complexity
  (multi-file, schema or data changes, architectural impact); simple or
  mechanical dispatches drop to a cheaper tier; verification and coordination
  dispatches always inherit. This governs model tier, not reasoning budget; leave thinking
  at the default. Skipped automatically if your agent has no per-subagent
  model control.
- **Worktree-isolated parallel writes.** When two or more write-intent subagents
  run in parallel, each works in its own git worktree + branch (native isolation
  on Claude Code, requested worktree isolation on Cortex Code, prompt-driven
  `git worktree add` elsewhere). A dedicated
  integration dispatch merges the branches back, resolving mechanical conflicts
  and escalating semantic ones, and verification then runs on the unified tree.
- **Separate verification where the blast radius is real.** Work that merges to a
  shared branch, changes a schema or data, or spans multiple files gets its own
  verification dispatch, so "the implementer said it worked" is never the last word. Read-only lookups,
  single-file edits, and search results are not re-checked by a second agent.
- **Handoff-grade prompts.** Subagents are stateless, so dispatch prompts are
  treated as mini handoff documents (two tiers: lightweight vs. rich), with a
  quote-don't-summarize continuity discipline.

## When it activates

Triggers on "orchestrator mode", "use subagents", "delegate everything", "swarm
this", or any request for the main thread to coordinate rather than execute.
A single named delegation ("use a subagent to check X") gets one dispatch, not
the mode. Once on, it stays on for the whole session until you say "exit
orchestrator mode" or "stop delegating."

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/orchestrator-mode
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install orchestrator-mode@relentless-data-skills
```

## Files

- `SKILL.md`: the orchestration policy. Hard rules, workflow, capability-based
  subagent selection, model discipline, and the two-tier prompt requirements.
- `references/reference.md`: the Claude Code / Cursor / Cortex Code tool-mapping
  table, sub-orchestrator nesting mechanics, the parallel-writes worktree
  procedure, a worked example, and the anti-pattern list. Rule 1 counts reading
  this file as skill loading, so the main thread may consult it while the mode
  is active.

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget); see the
[root README](../../README.md#maintenance--ci).
