# dlt-bootstrap

The **`dlt-bootstrap`** agent skill: set a project up for [dlt](https://dlthub.com)
pipeline development by installing dltHub's official
[AI Harness](https://github.com/dlt-hub/dlthub-ai-harness) project-scoped,
then layering Relentless Data house conventions (Snowflake destination, Prefect
orchestration, DuckDB dev loop) on top as an always-on rule.

The dltHub toolkits provide the procedures for building, debugging, and
validating pipelines. This skill handles project setup and conventions.

## What it does

- **Detect, then interview.** Establishes venv/`dlt[hub]`/agent/git state by
  inspection, then asks at most three questions (source types, pipeline name,
  destination confirm).
- **Install the workbench.** Installs the workbench and its MCP dependency,
  configures the detected agent, and selects toolkits for the project's source
  types. The [installation procedure](SKILL.md#install-verified-fast-path)
  contains the commands and toolkit policy.
- **Write the house rule.** Fills `references/rule-template.md` and commits it
  as `dlt-house-conventions.md` next to dltHub's own installed rules, so the
  conventions are always-on and apply even when the workbench's `/find-source`
  etc. are invoked directly. Frontmatter holds the install state for
  idempotent incremental re-runs (for example, adding a second source type later).
- **Verify and hand off.** Runs `dlthub ai status` plus an MCP registration check;
  day-to-day work then runs through the workbench's own commands, and hardening
  composes with `prefect`, `/ship`, and `snowman`.

## How it works

The skill follows the installation procedure in `SKILL.md`. If a command
fails, it consults the workbench README and documentation indexes linked in
`references/docs-map.md`. CI checks the marked URLs weekly.

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

Use it to set up dlt in a project or add a source type. When it notices a
missing house-conventions rule during another task, it offers setup and
continues the original task unless you accept.

## Files

- `SKILL.md` has the detection list, interview, verified install sequence, toolkit
  policy, rule-placement procedure, and guardrails.
- `references/rule-template.md` is the house-conventions rule the bootstrap
  fills and commits into each project (frontmatter holds re-entry state).
- `references/docs-map.md` has durable doc entry points plus a topic-to-URL cache
  (CI-checked).

## Maintenance / CI

- **`scripts/check_doc_urls.py`** fetches every URL in this skill's docs map
  weekly and fails if any no longer resolves (catches dltHub moving pages or
  the workbench README changing branches).
- **`scripts/lint_skill.py`** verifies SKILL.md frontmatter, the "Use when"
  trigger, and the line budget.
- **`tests/test_dlt_bootstrap.py`** validates the rule template's
  frontmatter and required sections, and the docs map's durable entries.
