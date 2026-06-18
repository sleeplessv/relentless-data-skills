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

Search the project for a committed `dlt-house-conventions.md`.

- **Present** → incremental mode: read its frontmatter (`source_types`,
  `toolkits_installed`), then do only what's missing — typically installing an
  additional toolkit for a new source type and updating the frontmatter.
- **Absent** → full bootstrap (below).

If invoked proactively (the user was working on something else and the rule is
merely missing), don't start the bootstrap — note that the project lacks
`dlt-house-conventions.md`, offer to run the setup, and return to the user's
actual task unless they accept.

## Detect, never ask

Establish by inspection, creating what's missing in the install step:

- `pyproject.toml` / venv — greenfield vs existing project (same path either way).
- `dlt[hub]` already a dependency? `uv run dlthub --version` succeeds?
- Which agent is in use (Claude Code / Cursor / Codex) — usually obvious from
  the session; pass it explicitly to `--agent` rather than relying on detection.
- Existing `.dlt/` directory, existing pipelines, git repo state.
- Where `dlthub ai init` placed its rules (see "Write the house rule").

## Interview (three questions max, as plain prose)

1. **Source type(s)** this project ingests — REST API, SQL database, or files?
   Drives toolkit selection. Multiple is fine.
2. **Pipeline / dataset name** — only ask if not derivable from the repo name.
3. **Destination** — Snowflake is the house default; confirm, allowing a
   per-client override (e.g. BigQuery) without editing this skill.

## Install (verified fast path)

```bash
uv init                          # only if no pyproject.toml
uv add "dlt[hub]"
uv add "dlthub[mcp]"             # MCP server deps — without this the workspace MCP never starts
uv run dlthub init               # workspace init; follow its instructions (uv sync)
uv run dlthub ai init --agent claude
uv run dlthub ai toolkit install <toolkit> --agent claude   # per source type
uv run dlthub ai status          # verify: agent detected, toolkits + entry skills listed
```

If any command fails or a flag is rejected, suspect upstream drift before
debugging: consult [references/docs-map.md](references/docs-map.md) (start at
the workbench README) and re-derive the command — never invent flags.

Known upstream trap (verified 2026-06): if `dlthub ai status` warns to
`pip install "dlt[workspace]"`, ignore it — that extra does not exist; the
correct fix is `uv add "dlthub[mcp]"` (already in the fast path above).

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
  request — note that the last two require a dltHub sign-up; flag that before
  installing and skip gracefully if the user has no account.
- Record every installed toolkit in the house rule's frontmatter.

## Write the house rule

1. Copy [references/rule-template.md](references/rule-template.md) into the
   project and fill every `<placeholder>` from the interview + detection.
   Then re-read the frontmatter: every key from the template present, one per
   line, no `<` left (easy to mangle `destination` / `dev_destination`).
2. Name it `dlt-house-conventions.md` and place it **in the same location
   where `dlthub ai init` installed its own rules** (find its
   `dlthub-workspace.md`) so it is always-on for the same agent. If that agent
   merges rules into a memory file (`CLAUDE.md` / `AGENTS.md`), append the
   filled template as a clearly delimited managed section instead.
3. Ensure the agent memory file carries dltHub's credential-safety line (it is
   in the template) — their installer does not add it for Claude Code.
4. Commit the rule and the workbench-installed files. Never commit
   `.dlt/secrets.toml` — neither `uv init` nor `dlthub ai init` gitignores it
   (the latter only writes `.claudeignore`). Add `secrets.toml` to
   `.gitignore` if absent, then verify: `git check-ignore .dlt/secrets.toml`.

## Verify, then hand off

- `uv run dlthub ai status` shows the agent and pipeline toolkits — it omits
  `init`; use `uv run dlthub ai toolkit list` to confirm the full set.
- MCP: confirm `dlt-workspace-mcp` is registered for the agent (for Claude
  Code, check the project `.mcp.json`).
- Tell the user to **restart their agent session now** — the workbench skills
  (`/find-source`, ...) and the MCP server are not active until they do.
- Tell the user the working loop: `/find-source` → scaffold → secrets via the
  MCP secrets tools → debug → validate on DuckDB → harden (incremental
  loading, remove dev limits) → wrap in a Prefect flow (`prefect`) →
  ship via `/ship` → inspect what landed in Snowflake with `snowman`.

## Guardrails

- This skill **sets up**; it does not build pipelines, and it does not fork or
  re-teach workbench skill content — upstream owns that. If asked to build a
  pipeline before bootstrap, bootstrap first, then route to the workbench's
  skills.
- Credential safety is enforced at runtime by the house rule's Secrets section;
  see [references/rule-template.md](references/rule-template.md).
- Incremental re-runs must be idempotent: re-installing an existing toolkit or
  re-writing an unchanged rule is a no-op, not an error.
