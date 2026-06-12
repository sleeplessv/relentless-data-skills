# dlt-bootstrap

The **`dlt-bootstrap`** agent skill: set a project up for [dlt](https://dlthub.com)
pipeline development by installing dltHub's official
[AI Workbench](https://github.com/dlt-hub/dlthub-ai-workbench) project-scoped,
then layering Relentless Data house conventions (Snowflake destination, Prefect
orchestration, DuckDB dev loop) on top as an always-on rule.

It is deliberately a **hybrid**: the heavy procedural knowledge — scaffolding,
debugging, and validating pipelines — stays upstream in dltHub's nine toolkits,
which this skill never forks or re-teaches. What it owns is the repeatable
bootstrap and the per-project conventions layer.

## What it does

- **Detect, then interview** — establishes venv/`dlt[hub]`/agent/git state by
  inspection; asks at most three questions (source types, pipeline name,
  destination confirm).
- **Install the workbench** — `uv add "dlt[hub]"` → `uv run dlthub init` →
  `uv run dlthub ai init --agent claude` → `dlthub ai toolkit install` for
  *only* the pipeline toolkits matching the project's source types. Never
  `quick-start` (this skill is the entry point) or `dlthub-platform` (we ship
  via Prefect).
- **Write the house rule** — fills `references/rule-template.md` and commits it
  as `dlt-house-conventions.md` next to dltHub's own installed rules, so the
  conventions are always-on and apply even when the workbench's `/find-source`
  etc. are invoked directly. Frontmatter holds the install state for
  idempotent incremental re-runs (e.g. adding a second source type later).
- **Verify and hand off** — `dlthub ai status` + MCP registration check, then
  day-to-day work runs through the workbench's own commands; hardening
  composes with `prefect`, `/ship`, and `snowman`.

## How it works

The skill is intentionally thin: verified-today CLI commands are the fast
path, and on any command failure it consults `references/docs-map.md` (rooted
at the workbench's raw README and the two `llms.txt` docs indexes) instead of
debugging blind — so upstream renames degrade to a doc lookup, not a broken
bootstrap. The docs map is CI-checked weekly.

## Install

This skill is meant to be installed **user-level** (it must exist before a
fresh project has any agent config); everything it *installs* is
project-scoped. See the [repo root README](../../README.md) for the general
patterns. For this skill specifically:

```bash
npx skills add -g sleeplessv/relentless-data-skills/skills/dlt-bootstrap
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install dlt-bootstrap@relentless-data-skills
```

It activates when you set up dlt in a project, add a new source type, or work
in a dlt project that lacks the house-conventions rule.

## Files

- `SKILL.md` — detection list, interview, verified install sequence, toolkit
  policy, rule-placement procedure, guardrails.
- `references/rule-template.md` — the house-conventions rule the bootstrap
  fills and commits into each project (frontmatter = re-entry state).
- `references/docs-map.md` — durable doc entry points + a topic→URL cache
  (CI-checked).

## Maintenance / CI

- **`scripts/check_doc_urls.py`** — fetches every URL in this skill's docs map
  weekly, failing if any no longer resolves (catches dltHub moving pages or
  the workbench README changing branches).
- **`scripts/lint_skill.py`** — verifies SKILL.md frontmatter, the "Use when"
  trigger, and the line budget.
- **`tests/test_dlt_bootstrap.py`** — validates the rule template's
  frontmatter and required sections, and the docs map's durable entries.
