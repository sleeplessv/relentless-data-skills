# orchestrator-mode

The **`orchestrator-mode`** agent skill turns the main thread into a pure
**coordinator**: it never reads, searches, edits, or runs anything itself —
every concrete task is delegated to a subagent. The main thread only plans,
dispatches, verifies, and synthesizes.

It is **agent-neutral**: the body talks in roles ("delegate", "search agent",
"coding agent") and a single mapping table maps those roles to the concrete
tools on **Claude Code**, **Cursor**, and **Cortex Code** (Snowflake's `cortex`
CLI). Custom specialists in your own setup slot in wherever you have them.

## What it does

- **Hard delegation rule.** The main thread may only call the delegation tool,
  the plan/todo tool, and user-facing question/report tools. Every file /
  search / shell / web / edit tool is forbidden — it gets delegated.
- **Parallel fan-out, with a floor.** Independent subtasks are dispatched together
  in one message and collected, instead of run sequentially — but small related
  tasks are batched into one dispatch rather than one agent per file.
- **Capability-based subagent selection.** Pick the agent by what the task
  needs (search, web research, SQL, build, coding, review), preferring a custom
  specialist if you have one and falling back to general-purpose.
- **Model discipline.** Subagents with write/implementation intent get the
  strongest (most capable) coding model available — that's the model *tier*, not
  a cue to raise the reasoning/thinking budget (leave that at the agent/user default);
  research and verification dispatches inherit the parent model. Skipped automatically if your agent has no
  per-subagent model control.
- **Worktree-isolated parallel writes.** When two or more write-intent subagents
  run in parallel, each works in its own git worktree + branch (native isolation
  on Claude Code, requested worktree isolation on Cortex Code, prompt-driven
  `git worktree add` elsewhere). A dedicated
  integration dispatch merges the branches back — resolving mechanical conflicts,
  escalating semantic ones — and verification then runs on the unified tree.
- **Separate verification where the blast radius is real.** Work that merges to a
  shared branch, changes a schema or data, or spans multiple files gets its own
  verification dispatch — no "the implementer said it worked". Read-only lookups,
  single-file edits, and search results are not re-checked by a second agent.
- **Handoff-grade prompts.** Subagents are stateless, so dispatch prompts are
  treated as mini handoff documents (two tiers: lightweight vs. rich), with a
  quote-don't-summarize continuity discipline.

## When it activates

Triggers on "orchestrator mode", "use subagents", "delegate everything", "swarm
this", or any request for the main thread to coordinate rather than execute.
A single named delegation ("use a subagent to check X") gets one dispatch, not
the mode. Once on, it stays on for the whole session until you say "exit
orchestrator mode" or "stop delegating".

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

- `SKILL.md` — the orchestration policy: hard rules, workflow, capability-based
  subagent selection, model selection, prompt tiers, and the Claude Code /
  Cursor / Cortex Code tool-mapping table.

  `SKILL.md` is **intentionally self-contained** (no `REFERENCE.md`): orchestrator
  mode forbids `Read` in the main thread, so a reference file would be unreadable
  the moment the mode activates. Don't "fix" the length by splitting it.

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget) — see the
[root README](../../README.md#maintenance--ci).
