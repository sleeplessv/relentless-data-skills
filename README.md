# relentless-data-skills-prefect

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

This is a standard agent skill (a directory containing a `SKILL.md`). Install it
where your agent discovers skills:

```bash
git clone https://github.com/sleeplessv/relentless-data-skills-prefect.git \
  ~/.claude/skills/relentless-data-skills-prefect
# or symlink an existing checkout:
ln -s "$(pwd)" ~/.claude/skills/relentless-data-skills-prefect
```

It activates automatically when you do Prefect 3 work or ask about Prefect.

## Files

- `SKILL.md` — core: response contract, lookup protocol, routing table, greenfield + audit workflows, guardrails, portable patterns.
- `references/greenfield-checklist.md` — the four-area standards / audit rubric.
- `references/docs-map.md` — durable doc entry points + a topic→URL cache (CI-checked).
- `scripts/` — CI integrity checks (doc-URL liveness, SKILL.md lint).
- `PRD.md` — the originating spec.

## Maintenance / CI

Two GitHub Actions integrity checks run on push, PR, and weekly:

- **`scripts/check_doc_urls.py`** — fetches `llms.txt` and every URL in the docs map, failing if any no longer resolves (catches Prefect moving/renaming pages).
- **`scripts/lint_skill.py`** — verifies SKILL.md frontmatter, that the description carries a "Use when" trigger, and that the file stays within its line budget.

Both use the Python standard library only — no dependencies to install.

## License

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
