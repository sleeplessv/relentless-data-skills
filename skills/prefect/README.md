# prefect

The **`prefect`** agent skill for **Prefect 3**. It encodes only what an agent
gets wrong by default: stale 3.x knowledge, unqueried instance state, and house
standards. Everything else is fetched from the live Prefect docs, so advice
tracks the latest docs instead of training data.

## What it does

- **Doc-lookup protocol** — resolves a topic via `docs.prefect.io/llms.txt`,
  then fetches the page as markdown (`<page>.md`); never invents URLs; web
  search is fallback only. Works under network sandboxing (uses the agent's
  web-fetch, not shell `curl`). Every answer names the doc page consulted — or
  says "baseline knowledge" explicitly.
- **CLI-first protocol** — queries the live instance (`uv run prefect
  deployment ls`, `flow-run inspect`, …) instead of guessing state; checks auth
  via `prefect config view` first. Read-only commands run eagerly;
  destructive/hard-to-reverse ones are surfaced before running.
- **Standards** — ~10 house opinions (lockfile-pinned 3.x, dev/prod split by
  pools and manifests, CI deploys, schedules on the deployment, secrets in
  blocks) plus three battle-tested patterns, each with its applicability
  condition.
- **Guardrails** — the classic stale-knowledge traps: workers not agents, no
  `Deployment` object, changed 3.x caching/results/transactions semantics.

Targets the **Prefect 3.x** generation (no patch pin). Prefect 2.x is out of scope.

## How it works

The whole skill is a single SKILL.md (~100 lines, no `references/`). The
durable contract is the lookup protocol (`llms.txt` → `<page>.md`); the only
URLs it ships are five guardrail anchors, with a 404-means-re-resolve rule
instead of a CI-checked URL cache.

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

- `SKILL.md` — everything: doc-lookup + CLI-first protocols, standards, guardrails.

## Maintenance / CI

Repo CI lints this skill via **`scripts/lint_skill.py`** (frontmatter, "Use
when" trigger in the description, line budget). There is deliberately no
doc-URL liveness check: the skill carries no URL cache to rot, and its 404
rule (re-fetch `llms.txt`, re-resolve) handles upstream page moves at use time.
