---
name: dlt-bootstrap
description: Bootstrap a dlt ingestion project with the dltHub AI Harness plus Relentless Data house conventions (Snowflake destination, Prefect orchestration, DuckDB dev loop). Use when setting up dlt in a new or existing project, or when adding a new source type or harness toolkit to a dlt project; also fires proactively when a dlt project lacks the house-conventions rule.
metadata:
  dlt: "dlt[hub]"
---

# dlt-bootstrap

Set a project up for dlt pipeline development the house way: install dltHub's
official **AI Harness** project-scoped, then layer Relentless Data
conventions on top as an always-on rule. The harness's toolkits own pipeline
building. After bootstrap, step aside: day-to-day work runs through the
harness's own entry points (`/find-source`, `/explore-data`, ...), with the
house rule applying automatically because it is a rule, not skill-mediated.

## First: check for the house rule

Set `project_root` to the absolute path of the selected project. Create the
directory first for a requested new project. Run `cd -- "$project_root" || exit 1`
before discovery and use that working directory for every project command and rule edit.

Use [rule discovery and placement](references/rule-installation.md) to find
standalone rules or managed memory sections, including uncommitted setup.

- If present, read `source_types` and `toolkits_installed`. Reconcile that
  record with installed toolkit files, MCP configuration, and the active agent.
  Repair missing setup or add the requested source type without repeating completed work.
- If absent, bootstrap below. Preserve existing harness files and project configuration.

If invoked proactively (the user was working on something else and the rule is
merely missing), don't start the bootstrap. Note that the project lacks
the house rule, offer to run the setup, and return to the user's
actual task unless they accept.

## Detect, never ask

Establish by inspection, creating what's missing in the install step:

- `pyproject.toml` / venv: new project or existing environment.
- Does the project's own `pyproject.toml` declare `dlt[hub]`?
- Which agent is in use (Claude Code / Cursor / Codex), usually obvious from
  the session. Use that agent when wiring the harness.
- Existing `.dlt/.workspace` marker, existing pipelines, git repo state.
- Where `dlthub ai init` placed its rules (see "Write the house rule").

## Resolve project choices

Use choices already supplied by the user or project. Ask only for missing information:

1. **Source type(s)** this project ingests: REST API, SQL database, or files?
   Drives toolkit selection. Multiple is fine.
2. **Pipeline / dataset name.** Only ask if not derivable from the repo name.
3. **Destination.** Snowflake is the house default; confirm, allowing a
   per-client override (e.g. BigQuery) without editing this skill.

## Install

State what you will install. Check the
[upstream installation sources](references/docs-map.md) and installed CLI help
before changing dependencies. Record the versions used.

1. **Create the workspace.** If `.dlt/.workspace` already exists, keep it and continue
   to step 2. Otherwise run `uvx dlthub-init@latest` in place.
   Use `--merge` on this first run to add
   missing scaffold ignores to an existing `.gitignore`. A fresh scaffold includes `pyproject.toml`,
   `uv.lock` and the base skills linked for Claude. If the initializer is unavailable,
   continue with the manual setup in step 2.
2. **Check what was installed.** The initializer can skip an existing
   `pyproject.toml` and leave the project without a bundled lock. If this directory
   lacks `pyproject.toml`, run `uv init --no-workspace`. If `dlt[hub]` is missing,
   run `uv add "dlt[hub]"`. If the workspace marker is still missing, run
   `uv run dlthub init`. Follow any requested `uv sync` and verify `uv run dlthub --version` succeeds.
3. **Wire the active agent.** If `.dlt/.toolkits` lacks `init` for the active agent, run
   `uv run dlthub ai init --agent <agent>`, using `claude`, `cursor`, or `codex`.
   Inspect `uv run dlthub ai status`. If it reports missing MCP dependencies
   and the installed `dlthub` package declares the `mcp` extra, run
   `uv add "dlthub[mcp]"` and check that the warning clears.
4. **Install each unrecorded source toolkit** for this agent with
   `uv run dlthub ai toolkit install <toolkit> --agent <agent>`. Use the table
   below for `<toolkit>`. Check the exit code and the recorded files.
5. **Repair missing files in a recorded toolkit.** A normal install can exit 0
   with “already installed” even when files are missing. In a temporary copy of
   the workspace, rerun the matching step 3 or 4 command with `--overwrite`.
   Copy back only the missing files whose SHA3-256 matches the project's
   `.dlt/.toolkits` record. If a hash differs, resolve the version difference
   before updating the project. This preserves customized files and agent settings.

## Toolkit policy

Install `init` (automatic dependency) plus **only** the pipeline toolkits
matching the selected source types:

| Source type | Toolkit |
| --- | --- |
| REST API | `rest-api-pipeline` |
| SQL database | `sql-database-pipeline` |
| Files (CSV/Parquet/JSONL) | `filesystem-pipeline` (requires dltHub sign-up) |

- **Never install** `quick-start` (this skill is the entry point) or
  `dlthub-platform` (we deploy via Prefect, not the dltHub platform).
- `data-exploration`, `data-quality`, `transformations` only on explicit
  request. The last two require a dltHub sign-up; flag that before
  installing and skip gracefully if the user has no account.
- Record every installed toolkit in the house rule's frontmatter.

## Write the house rule

1. Fill [references/rule-template.md](references/rule-template.md) from the
   resolved choices. Preserve every frontmatter key and replace every placeholder.
   Set `<warehouse-inspection>` to read-only inspection of the chosen destination.
   For Snowflake, use `snowman` if available. For other destinations, name an
   available connector or CLI and verify its inspection commands before use.
   If none is available, state that inspection requires destination access.
2. Apply [rule placement and verification](references/rule-installation.md).
   Keep the template concise and preserve project-specific additions on re-entry.
3. Add `secrets.toml` to `.gitignore` if absent before any commit.
   Verify `git check-ignore .dlt/secrets.toml` and inspect the staged file list.
   Never commit `.dlt/secrets.toml`. Commit the rule and intended setup files.

## Verify, then hand off

- Compare `uv run dlthub ai status` with `.dlt/.toolkits` and installed files,
  including `init`. A toolkit catalog listing does not prove installation.
- Check MCP registration and enablement for the active agent. After session
  restart, verify a non-secret read-only MCP call and the selected toolkit's entry skill.
  If restart is still needed, report setup written and runtime readiness pending.
- Get each toolkit's entry skill from installed metadata or current upstream docs.
  Hand off through that entrypoint, DuckDB validation, production hardening,
  Prefect orchestration, shipping, and inspection of the selected destination.
- Check whether `prefect`, `land`, and destination-specific companions are available.
  Name missing companions and give an available docs or CLI fallback.
  Do not promise unavailable slash commands or install companions without a request.

## Guardrails

- This skill **sets up**; it does not build pipelines, and it does not fork or
  re-teach harness skill content, since upstream owns that. If asked to build a
  pipeline before bootstrap, bootstrap first, then route to the harness's
  skills. When the bootstrap surfaces adjacent problems, such as missing tests, an
  untidy `pyproject.toml`, or a stale dependency, report them and finish the
  bootstrap; don't fix them on the way through.
- Bootstrap is a linear install sequence: each command depends on the files
  the previous one wrote, so run it in one thread, in order.
- Credential safety is enforced at runtime by the house rule's Secrets section;
  see [references/rule-template.md](references/rule-template.md).
- Incremental re-runs must be idempotent: re-installing an existing toolkit or
  re-writing an unchanged rule is a no-op, not an error.
