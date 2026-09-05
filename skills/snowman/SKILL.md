---
name: snowman
description: Use when querying Snowflake, discovering objects, profiling data, testing transformation hypotheses, investigating data quality, or staging SQL changes. Every snow CLI call goes through this skill.
---

# snowman

Use `scripts/snowman.py` for Snowflake queries and stage user-requested changes
for manual execution. Its lexical filter rejects write statements and known
side-effecting constructs. It cannot prove that UDFs or external functions are
read-only. Use a least-privilege connection and trusted read functions.

## Load project context

Find and load `.snowman/context.md` by walking up from the current directory.
If absent, follow [the bootstrap](references/install.md) before proceeding.
Queries require context, except bootstrap discovery with `--connection <name>`.
Once context exists, let the wrapper resolve the connection from it.

Context records project architecture and connection names, never credentials.
Keep it in version control. Database scope is a focus hint, not an access
restriction. Query other databases when the user's question requires them.

## Run queries

Every SQL query goes through the wrapper:

```bash
python3 <skill-dir>/scripts/snowman.py "<SQL>"
```

`<skill-dir>` is this skill's directory. Submit one statement per call.
The wrapper appends `DESCRIBE RESULT` to obtain column types in the same session.
It applies `default_warehouse` from the selected context. If absent, the named
connection's warehouse setting applies.

Stdout contains only CSV data, or a compact JSON array with `--json`.
Types, truncation notices, and artifact paths go to stderr. Keep the streams
separate when parsing. CSV cells can contain newlines or lines beginning `#`.
An empty CSV cell represents NULL, `""` represents an empty string, and nested
values are compact JSON. Empty results retain available column names and types
on stderr, with a CSV header or JSON `[]` on stdout, subject to preview limits.

Defaults are 50 rows, 200 retained characters per cell plus a truncation marker,
and 16,000 UTF-8 bytes of data output. Change them with `--max-rows`, `--max-cell`,
and `--max-output`. `0` lifts the corresponding limit. JSON preserves nested
objects and arrays unless truncated, when the cell becomes shortened JSON text.

Any truncated result saves full rows and schema as JSON. Follow the stderr
`# full result:` path and inspect the needed fields locally instead of rerunning
the query or loading the whole file into context. See
[output details](references/guardrails.md#output) when parsing or recovering results.

## Handle failures

Read the reason after `BLOCKED:`. It describes a refusal before querying,
including SQL, context, or configuration problems. Fix setup failures or
reformulate an authorized read. Stage changes only when
the user requested them. Never bypass the wrapper to evade a refusal.
If `snow` is missing from PATH, install Snowflake CLI before retrying.

After a query-processing failure, inspect the reported `# raw CLI stdout:` file
locally. It preserves received output for recovery. Do not rerun automatically.

Queries need network access. Use the environment's permitted execution mode.
If diagnostics identify a sandbox network restriction, use its approval flow
for network access. DNS errors alone do not establish the cause.

For authentication failures, relay the wrapper's hint and follow
[authentication setup](references/install.md#authentication).
The wrapper relays the nearest `.env` at or above the project root to `snow`.
Never source or print that file, request secrets, or edit connection credentials.

## Select an environment

With an `environments:` map, queries use `default_env`. Pass `--env <name>`
when the user requests another environment, and identify it in the update.
Selection is per-query. Single-account contexts use `connection:` and reject `--env`.

Staging in multi-environment projects requires an explicit `--env`.
If the user has not named the change's target environment, ask before staging.
Reuse an already stated target without another confirmation.

## Stage requested changes

When the user asks for DML or DDL, prepare the SQL and stage it:

```bash
python3 <skill-dir>/scripts/snowman.py --stage "<SQL>" --name <purpose-slug>
```

Add the chosen `--env` for multi-environment projects. Staging requires context
and accepts several statements. Name the script for its purpose in kebab-case.
The wrapper writes a gitignored file under `.snowman/staged/` and prints its path
and manual run command, including the connection and configured warehouse.
Relay both and any destructive-keyword warning. The user executes and cleans up
the script. Snowman does neither.

## Explore efficiently

- Start from the narrowest known scope. For an exact table, inspect that table.
  Discover databases or schemas only when their names are missing.
- Bound exploratory reads with filters, `LIMIT`, or `SAMPLE`. Preview limits
  reduce output, not query cost. Use smaller samples and tighter filters in prod.
  Before a heavy query, state the configured warehouse or verify
  `CURRENT_WAREHOUSE()` when no warehouse is configured in context.
- Prefer `SHOW TERSE` and project metadata with `->> SELECT "col" FROM $1`.
  Use plain `SHOW` for `rows` and `bytes`, which TERSE omits. Project columns
  explicitly when TERSE does not shrink an object's output.
- Select the columns needed for the question. Investigate incidental anomalies
  only when relevant. Otherwise mention them briefly in the answer.
- Run related queries together in your investigation. Delegate only broad,
  independent work, not each query or table.
- State the first query's purpose, update when findings change direction, and
  lead the answer with the finding rather than a dump of rows.

Load [workflows](references/workflows.md) for exploration, profiling, hypothesis
testing, investigation, or staging examples. Read
[guardrail details](references/guardrails.md) when a SQL refusal needs explanation.
