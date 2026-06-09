# orchestrator-mode

The **`orchestrator-mode`** agent skill turns the main thread into a pure
**coordinator**: it never reads, searches, edits, or runs anything itself —
every concrete task is delegated to a subagent. The main thread only plans,
dispatches, verifies, and synthesizes.

It is **agent-neutral**: the body talks in roles ("delegate", "search agent",
"coding agent") and a single mapping table maps those roles to the concrete
tools on **Claude Code** and **Cursor**. Custom specialists in your own setup
slot in wherever you have them.

## What it does

- **Hard delegation rule.** The main thread may only call the delegation tool,
  the plan/todo tool, and user-facing question/report tools. Every file /
  search / shell / web / edit tool is forbidden — it gets delegated.
- **Parallel fan-out.** Independent subtasks are dispatched together in one
  message and collected, instead of run sequentially.
- **Capability-based subagent selection.** Pick the agent by what the task
  needs (search, web research, SQL, build, coding, review), preferring a custom
  specialist if you have one and falling back to general-purpose.
- **Model discipline.** Subagents with write/implementation intent get the
  highest-effort coding model available; research and verification dispatches
  inherit the parent model. Skipped automatically if your agent has no
  per-subagent model control.
- **Separate verification.** Implementation and verification are always
  different subagent calls — no "the implementer said it worked".
- **Handoff-grade prompts.** Subagents are stateless, so dispatch prompts are
  treated as mini handoff documents (two tiers: lightweight vs. rich), with a
  quote-don't-summarize continuity discipline.

## When it activates

Triggers on "orchestrator mode", "use subagents", "delegate everything", "swarm
this", or any request for the main thread to coordinate rather than execute.
It stays on for the whole session until you say "exit orchestrator mode" or
"stop delegating".

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
  Cursor tool-mapping table.

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget) — see the
[root README](../../README.md#maintenance--ci).
