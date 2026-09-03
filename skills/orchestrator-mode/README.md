# orchestrator-mode

The **`orchestrator-mode`** agent skill turns the main thread into a pure
**coordinator**: it never reads, searches, edits, or runs anything itself.
Every concrete task is delegated to a subagent. The main thread only plans,
dispatches, verifies, and synthesizes.

It is **agent-neutral**: the body talks in roles ("delegate", "search agent",
"coding agent") and a single mapping table maps those roles to the concrete
tools on **Claude Code**, **Cursor**, **Cortex Code** (Snowflake's `cortex`
CLI), and **Codex**. Custom specialists in your own setup slot in wherever you have them.

## What it does

- **Hard delegation rule.** The main thread may only call the delegation tool,
  the plan/todo tool, and user-facing question/report tools; everything else is
  a dispatch, batched by area and fanned out in parallel across areas.
- **Model, verification, and worktree discipline.** Dispatches inherit the
  session model unless complexity clears the escalation bar; work with real
  blast radius gets a separate verification dispatch; parallel writers get
  isolated worktrees with a pinned base commit and a dedicated integration
  dispatch.
- **Handoff-grade prompts.** Subagents are stateless, so dispatch prompts are
  mini handoff documents (lightweight or rich) with a quote-don't-summarize
  continuity discipline, plus a failure-and-resume policy and effort scaling.

The rules themselves live in `SKILL.md`; this list is a pointer, not a copy.

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
- `references/reference.md`: the Claude Code / Cursor / Cortex Code / Codex
  tool-mapping table (including skill install paths and per-harness nesting and
  concurrency limits), sub-orchestrator nesting mechanics, the parallel-writes worktree
  procedure, a worked example, and the anti-pattern list. Rule 1 counts reading
  this file as skill loading, so the main thread may consult it while the mode
  is active.

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget); see the
[root README](../../README.md#maintenance--ci).
