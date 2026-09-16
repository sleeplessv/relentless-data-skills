# dlt-bootstrap

The **`dlt-bootstrap`** agent skill: set a project up for [dlt](https://dlthub.com)
pipeline development by installing dltHub's official
[AI Harness](https://github.com/dlt-hub/dlthub-ai-harness) project-scoped,
then layering Relentless Data house conventions (Snowflake destination, Prefect
orchestration, DuckDB dev loop) on top as an always-on rule.

The dltHub toolkits provide the procedures for building, debugging, and
validating pipelines. This skill handles project setup and conventions.

## What it does

- **Detect project state.** Finds standalone rules and managed memory sections,
  reconciles recorded toolkits with installed files, and asks only for missing choices.
- **Install the workbench.** Installs the workbench and its MCP dependency,
  configures the detected agent, and selects toolkits for the project's source
  types. The [installation procedure](SKILL.md#install)
  contains the commands and toolkit policy.
- **Write the house rule.** Uses a Claude project rule, a Cursor `.mdc` rule,
  or a managed `AGENTS.md` section for Codex. Re-entry updates the existing rule
  and preserves other project instructions. Warehouse guidance follows the chosen destination.
- **Verify and hand off.** Checks installed files and MCP configuration, then
  distinguishes completed setup from readiness after restart. Uses the selected
  toolkit's entrypoint and available companion skills. Production guidance covers
  snapshot and incremental strategies, development-mode removal, and repeated runs.

## How it works

The skill checks the manual installation procedure against current upstream
guidance and installed CLI help. The sources are linked in `references/docs-map.md`.
CI checks marked URLs weekly for liveness, not installation behavior.

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

- `SKILL.md` has the detection list, project choices, install sequence, toolkit
  policy, rule-placement procedure, and guardrails.
- `references/rule-template.md` is the house-conventions rule the bootstrap
  fills and commits into each project (frontmatter holds re-entry state).
- `references/rule-installation.md` covers agent-specific output, discovery,
  migration, and verification.
- `references/docs-map.md` has official doc entry points plus a topic-to-URL cache
  (CI-checked).

## Maintenance / CI

- **`scripts/check_doc_urls.py`** fetches every URL in this skill's docs map
  weekly and fails if any no longer resolves (catches dltHub moving pages or
  the workbench README changing branches).
- **`scripts/lint_skill.py`** verifies SKILL.md frontmatter, the "Use when"
  trigger, and the line budget.
- **`tests/test_dlt_bootstrap.py`** validates the rule template's
  frontmatter and required sections, and the docs map's durable entries.
- [Behavior scenarios](../../tests/dlt-prefect-scenarios.md) cover generated rules,
  re-entry, overrides, and Prefect inspection. Run these separately in isolated fixtures;
  the automated checks above do not establish agent behavior.
