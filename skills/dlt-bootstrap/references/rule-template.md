---
managed_by: dlt-bootstrap
bootstrapped: <YYYY-MM-DD>
source_types: [<rest_api | sql_database | filesystem>]
toolkits_installed: [init, <toolkit>]
pipeline_name: <pipeline-name>
destination: <snowflake>
dev_destination: duckdb
orchestration: prefect
---

# dlt house conventions (Relentless Data)

Always-on rules for dlt pipeline work in this project. They apply to every
session, including work driven by the dltHub AI Workbench's own skills and
commands (`/find-source`, `/create-rest-api-pipeline`, ...). The frontmatter
above is bookkeeping owned by the `dlt-bootstrap` skill; update it when
toolkits or source types change; do not delete it.

## Development loop

- Develop locally against **DuckDB** with `dev_mode=True` and `.add_limit(1)`
  on resources until the schema and data look right. The limit counts yielded
  items or batches, not necessarily individual rows.
- Validate after every change: row counts, primary keys, nested-object
  handling. Use the workbench's validation skills and the local dashboard.

## Secrets

- CRITICAL: never ask for credentials in chat. Always let the user edit
  secrets directly and do not attempt to read them.
- Local credentials live in `.dlt/secrets.toml` (must be gitignored; verify
  before any commit). Deployed pipelines read credentials from environment
  variables, never from committed files or code.

## Hardening and shipping

- Production pipelines are wrapped in a **Prefect flow** and deployed per the
  `prefect` conventions when that skill is available. Otherwise use the project's
  deployment workflow and current Prefect docs. Do **not** use dltHub-platform deployment
  (`setup-runtime`) in this project.
- Select a load strategy from the source's update and deletion semantics.
  Use incremental loading with a reliable cursor or change feed. Use full
  replacement for current-state snapshots when incremental capture is unsuitable.
- Before promotion, set `dev_mode=False`, remove resource limits, and select
  the production destination. Verify repeated runs keep a stable dataset and
  handle new rows, updates, and deletions as the chosen strategy requires.
- Use `/ship` when available. Otherwise follow the project's commit and PR
  workflow within the user's requested scope.

## Warehouse inspection

- <warehouse-inspection>

## Naming conventions

<!-- Placeholder: encode dataset/schema/pipeline naming rules here as real
projects establish them. Until then, follow dlt defaults and keep names
lowercase snake_case. -->
