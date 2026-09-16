# prefect

The **`prefect`** agent skill for **Prefect 3**. It encodes only what an agent
gets wrong by default: stale 3.x knowledge, unqueried instance state, and house
standards. It checks version-sensitive advice against fetched Prefect docs
or local API and CLI evidence for the project's installed version.

## What it does

- **Doc-lookup protocol.** Fetches the exact Markdown URL in
  `docs.prefect.io/llms.txt`, with an HTML fallback when the fetch tool rejects
  Markdown. Re-resolves missing pages through the index and uses web search
  when direct lookup fails. Advice cites docs or local evidence and states
  what remains unverified.
- **CLI-first protocol.** Queries the live instance through the project's
  established environment. An already-connected Prefect MCP server can also
  provide read-only evidence. Checks effective settings and confirms access
  with a read-only query, using the relevant Cloud or self-hosted auth path.
  Destructive or hard-to-reverse actions are surfaced before running.
- **Run diagnosis.** Uses state transitions and logs to identify the cause,
  with separate checks for worker-backed pools, push and Managed pools, and
  `serve()`. Startup code errors can produce `Crashed` runs too.
- **Standards.** Covers version pinning, environment separation, CI deployments,
  deployment schedules, and secrets in blocks. Patterns state when they apply.
- **Guardrails.** The classic stale-knowledge traps: workers not agents, no
  `Deployment` object, changed 3.x caching/results/transactions semantics.

Targets the **Prefect 3.x** generation (no patch pin). Prefect 2.x is out of scope.

## How it works

The whole skill is a single `SKILL.md`, with no `references/` directory.
The lookup protocol uses exact URLs from `llms.txt` and accepts fetched
Markdown or HTML. Five guardrail anchors point to common topics; the skill
re-resolves them through the index if they move.

## Install

See the [repo root README](../../README.md) for the general install patterns
(`npx skills`, Claude Code plugin, manual clone). For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/prefect
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install prefect@relentless-data-skills
```

It activates automatically when you do Prefect 3 work or ask about Prefect.

## Files

- `SKILL.md`: everything, including doc-lookup + CLI-first protocols, standards, and guardrails.

## Maintenance / CI

Repo CI lints this skill via **`scripts/lint_skill.py`** (frontmatter, "Use
when" trigger in the description, line budget). There is no automated
doc-URL liveness check for this skill. Its lookup protocol handles upstream
page moves at use time; the linter does not validate Prefect API behavior.
