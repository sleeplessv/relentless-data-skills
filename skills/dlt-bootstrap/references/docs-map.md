# dltHub AI Harness / dlt docs map

**Official entry points:**
- OSS dlt docs index => https://dlthub.com/docs/llms.txt
- dltHub (platform + harness) docs index => https://dlthub.com/docs/hub/llms.txt
- Any docs page as clean markdown: append `.md` to its URL.
- Read the harness README and toolkit reference alongside installed-version
  CLI help. Resolve conflicting guidance against actual installed artifacts.

CI checks the URLs below for liveness, not content freshness or command behavior.
**If any fails or a
CLI command is rejected, re-fetch the relevant index / raw README and
re-resolve. Do not invent URLs or flags.**

## AI Harness (setup, toolkits, CLI)
- Cursor rule format and activation => https://cursor.com/docs/rules
- AI Harness installation (workspace, agent setup, verification) => https://dlthub.com/docs/hub/ai-harness/installation
- harness README (commands, toolkit table, agent notes) => https://raw.githubusercontent.com/dlt-hub/dlthub-ai-harness/master/README.md
- toolkit packaging + `dlthub ai` CLI reference => https://raw.githubusercontent.com/dlt-hub/dlthub-ai-harness/master/TOOLKITS.md
- dlt[hub] installation => https://dlthub.com/docs/hub/getting-started/installation.md
- dlthub CLI full reference => https://dlthub.com/docs/hub/command-line-interface.md
- REST API source with the harness (workflow walkthrough) => https://dlthub.com/docs/hub/ingestion/rest-api-source.md
- dltHub context (9,700+ source definitions) => https://dlthub.com/context

## Building pipelines (OSS dlt)
- REST API tutorial => https://dlthub.com/docs/tutorial/rest-api.md
- SQL database tutorial => https://dlthub.com/docs/tutorial/sql-database.md
- filesystem tutorial => https://dlthub.com/docs/tutorial/filesystem.md
- run a pipeline => https://dlthub.com/docs/walkthroughs/run-a-pipeline.md
- incremental loading => https://dlthub.com/docs/general-usage/incremental-loading.md

## Config, secrets, destinations
- credentials / secrets setup => https://dlthub.com/docs/general-usage/credentials/setup.md
- Snowflake destination => https://dlthub.com/docs/dlt-ecosystem/destinations/snowflake.md
- DuckDB destination => https://dlthub.com/docs/dlt-ecosystem/destinations/duckdb.md
