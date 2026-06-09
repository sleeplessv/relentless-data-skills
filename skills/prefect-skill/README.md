# prefect-skill

The **`prefect-skill`** agent skill for **Prefect 3**: scaffolding greenfield
projects against current best practice, auditing existing projects for drift,
and looking up the live Prefect docs whenever the agent is unsure — so advice
tracks the latest docs instead of stale training data.

## What it does

- **Greenfield mode** — an opinionated workflow plus a four-area standards checklist (scaffolding · authoring + reliability · deployment + execution · config/secrets/observability/testing).
- **Audit mode** — runs the same checklist as a rubric against an existing project and flags drift, including Prefect 2.x leftovers.
- **Doc-lookup protocol** — resolves a topic via `docs.prefect.io/llms.txt`, then fetches the page as markdown (`<page>.md`); web search is fallback only. Works under network sandboxing (uses the agent's web-fetch, not shell `curl`).
- **Response contract** — every answer states its assumptions/target, the recommendation + tradeoff, the doc page consulted, and a validation step.

Targets the **Prefect 3.x** generation (no patch pin). Prefect 2.x is out of scope.

## How it works

The skill is intentionally thin: it carries opinions, a workflow, a checklist,
and a docs map, and delegates topic *detail* to the live docs so it never goes
stale. The durable contract is the lookup protocol (`llms.txt` → `<page>.md`);
specific URLs in the docs map are a CI-checked convenience cache.

## Install

See the [repo root README](../../README.md) for the general install patterns
(`npx skills`, Claude Code plugin, manual clone). For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/prefect-skill
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install prefect-skill@relentless-data-skills
```

It activates automatically when you do Prefect 3 work or ask about Prefect.

## Files

- `SKILL.md` — core: response contract, lookup protocol, routing table, greenfield + audit workflows, guardrails, portable patterns.
- `references/greenfield-checklist.md` — the four-area standards / audit rubric.
- `references/docs-map.md` — durable doc entry points + a topic→URL cache (CI-checked).

## Maintenance / CI

Repo CI runs two integrity checks relevant to this skill (see the [root README](../../README.md#maintenance--ci)):

- **`scripts/check_doc_urls.py`** — fetches `llms.txt` and every URL in this skill's docs map, failing if any no longer resolves (catches Prefect moving/renaming pages).
- **`scripts/lint_skill.py`** — verifies SKILL.md frontmatter, that the description carries a "Use when" trigger, and that the file stays within its line budget.
