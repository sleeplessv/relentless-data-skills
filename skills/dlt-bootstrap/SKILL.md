---
name: dlt-bootstrap
description: Bootstrap a dlt ingestion project with the dltHub AI Workbench plus Relentless Data house conventions (Snowflake destination, Prefect orchestration, DuckDB dev loop). Use when setting up dlt in a new or existing project, or when adding a new source type or workbench toolkit to a dlt project; also fires proactively when a dlt project lacks the house-conventions rule.
metadata:
  dlt: "dlt[hub]"
---

# dlt-bootstrap

Set a project up for dlt pipeline development the house way: install dltHub's
official **AI Workbench** project-scoped, then layer Relentless Data
conventions on top as an always-on rule. The workbench's toolkits own pipeline
building. After bootstrap, step aside: day-to-day work runs through the
workbench's own entry points (`/find-source`, `/explore-data`, ...), with the
house rule applying automatically because it is a rule, not skill-mediated.

## First: check for the house rule

Use [rule discovery and placement](references/rule-installation.md) to find
standalone rules or managed memory sections, including uncommitted setup.

- If present, read `source_types` and `toolkits_installed`. Reconcile that
  record with installed toolkit files, MCP configuration, and the active agent.
  Repair missing setup or add the requested source type without repeating completed work.
- If absent, bootstrap below. Preserve existing workbench files and project configuration.

If invoked proactively (the user was working on something else and the rule is
merely missing), don't start the bootstrap. Note that the project lacks
the house rule, offer to run the setup, and return to the user's
actual task unless they accept.

## Detect, never ask

Establish by inspection, creating what's missing in the install step:

- `pyproject.toml` / venv: greenfield vs existing project (same path either way).
- `dlt[hub]` already a dependency? `uv run dlthub --version` succeeds?
- Which agent is in use (Claude Code / Cursor / Codex), usually obvious from
  the session. Pass it explicitly to `--agent` rather than relying on detection.
- Existing `.dlt/` directory, existing pipelines, git repo state.
- Where `dlthub ai init` placed its rules (see "Write the house rule").

## Resolve project choices

Use choices already supplied by the user or project. Ask only for missing information:

1. **Source type(s)** this project ingests: REST API, SQL database, or files?
   Drives toolkit selection. Multiple is fine.
2. **Pipeline / dataset name.** Only ask if not derivable from the repo name.
3. **Destination.** Snowflake is the house default; confirm, allowing a
   per-client override (e.g. BigQuery) without editing this skill.

## Install

Say what you will install. Run the sequence with the detected agent in place
of `claude` and the selected toolkit in place of `<toolkit>`.
Check the current upstream README and installed CLI help before changing dependencies.
Record the package versions used.

```bash
uv init                          # only if no pyproject.toml
uv add "dlt[hub]"
uv add "dlthub[mcp]"             # MCP dependency choice; check installed-version requirements
uv run dlthub init               # workspace init; follow its instructions (uv sync)
uv run dlthub ai init --agent claude
uv run dlthub ai toolkit install <toolkit> --agent claude   # per source type
uv run dlthub ai status          # verify: agent detected, toolkits + entry skills listed
```

If any command fails or a flag is rejected, suspect upstream drift before
debugging: consult [references/docs-map.md](references/docs-map.md) (start at
the workbench README) and re-derive the command. Never invent flags.

The June 2026 bootstrap needed `dlthub[mcp]` despite a warning naming
`dlt[workspace]`. For another version, resolve warnings against package metadata
and current CLI guidance before applying or removing that workaround.

## Toolkit policy

Install `init` (automatic dependency) plus **only** the pipeline toolkits
matching the interview answer:

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
- Check whether `prefect`, `ship`, and destination-specific companions are available.
  Name missing companions and give an available docs or CLI fallback.
  Do not promise unavailable slash commands or install companions without a request.

## Guardrails

- This skill **sets up**; it does not build pipelines, and it does not fork or
  re-teach workbench skill content, since upstream owns that. If asked to build a
  pipeline before bootstrap, bootstrap first, then route to the workbench's
  skills. When the bootstrap surfaces adjacent problems, such as missing tests, an
  untidy `pyproject.toml`, or a stale dependency, report them and finish the
  bootstrap; don't fix them on the way through.
- Bootstrap is a linear install sequence. Run every step inline, never fanned
  out to subagents.
- Credential safety is enforced at runtime by the house rule's Secrets section;
  see [references/rule-template.md](references/rule-template.md).
- Incremental re-runs must be idempotent: re-installing an existing toolkit or
  re-writing an unchanged rule is a no-op, not an error.
