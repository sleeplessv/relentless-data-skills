---
name: snowman
description: Use when doing any Snowflake work, including running a query, exploring data, profiling tables, testing hypotheses, investigating data-quality issues, discovering schemas and warehouses, or staging a data/schema change. Every snow CLI call goes through this skill.
---

# snowman

Read-only Snowflake exploration via the `snow` CLI: schema discovery, data
profiling, hypothesis testing, and data-quality investigation. **It never
executes writes and never mutates production.** Every executed query runs
through a guardrail wrapper that hard-rejects anything that isn't a single
read-only statement. When the user asks for a change, the DML/DDL is *staged*
as a script for them to run manually. snowman itself never runs it.

## First action, every invocation

Check for **`.snowman/context.md`** in the project root.

- **Absent** → this is a first run. Read [references/install.md](references/install.md),
  run the bootstrap (discovers connection, databases, warehouses, roles →
  writes `.snowman/context.md` and offers a Snowflake routing rule for the
  project's `AGENTS.md`/`CLAUDE.md`), then continue.
- **Present** → load it; it is the source of truth for this project's
  Snowflake architecture. Continue with the user's request.

**Refuse to run queries when no context file exists.** The context is
per-project and committed to the repo (names only, never secrets; see
[references/install.md](references/install.md)).

## Running queries, always via the wrapper

Never call `snow sql` directly. Every query goes through the wrapper, which
injects the connection, enforces read-only, and returns CSV:

```bash
python3 <skill-dir>/scripts/snowman.py "<SQL>"
```

`<skill-dir>` is this skill's directory. The wrapper reads the connection
from `.snowman/context.md`; never pass `--connection` yourself except during
the bootstrap, before the context exists ([references/install.md](references/install.md)).

Output is CSV (header row; empty cell = NULL; nested values as compact JSON)
plus `#` footer lines, which are notes, never data. 50 rows are shown
(`--max-rows N`, `0` = all) and an overflowing result is saved in full to
`.snowman/results/*.csv`; string and nested-JSON cells are cut at 200 chars (`--max-cell N`).
`--json` prints a compact JSON array instead, for VARIANT-heavy results.

The wrapper also relays the project root `.env` (if present) into the `snow`
subprocess, which is how encrypted key-pair connections get their
passphrase. Never source `.env` yourself, and never print its contents.

**Run outside the sandbox.** The `snow` CLI needs network access; a
sandboxed shell blocks it and the failure surfaces as a DNS/connection error
that looks like a broken connection config. Run every wrapper (and `snow`)
command with sandboxing disabled. If a query fails with a connection/DNS
error, suspect the sandbox first, not the connection setup.

On an auth-looking failure the wrapper prints a hint matched to the
connection's authenticator: browser auth (OAuth/SSO) needs the user to run
`snow connection test -c <name>` in their own terminal once (`snow` caches
the token); key-pair auth needs the passphrase in the project root `.env`
(e.g. `PRIVATE_KEY_PASSPHRASE=...`). Relay the hint; do not debug
`connections.toml`, ask for the passphrase, or drive the browser flow.

If the wrapper exits with `BLOCKED: …`, **do not work around it**: the
statement was non-read-only. Rephrase a read-only question; stage (below) a
change the user genuinely asked for. **Never stage SQL the user didn't ask
to have run.** Staging follows stated intent, not a block you want past.

## Environments (dev/prod in separate accounts)

When the context frontmatter has an `environments:` map (one entry per
account, each with its own connection; see
[references/install.md](references/install.md)), selection is **stateless and
per-query**:

- Queries hit `default_env` unless you pass `--env <name>`. Do that only when
  the user explicitly asks about another environment, and say which
  environment you're querying when it isn't the default.
- **Staging requires explicit `--env`** in these projects. If the user didn't
  say which environment a change targets, **ask**. Never infer. The env
  lands in the staged filename and header so the reviewer sees the target.
- Single-account projects keep the plain `connection:` form; `--env` is
  rejected there.

## Staging writes (DML/DDL), never executed

When the user explicitly asks for a change (add a column, backfill, create a
table…), write the SQL but **stage it instead of running it**:

```bash
python3 <skill-dir>/scripts/snowman.py --stage "<SQL>" --name <purpose-slug>
```

- The wrapper writes `.snowman/staged/<timestamp>__<slug>.sql` (gitignored,
  multi-statement fine, any keywords allowed) with a header containing the
  exact `snow sql -f … --connection …` command to run it.
- **Nothing is executed.** Relay the file path and run command to the user;
  executing, and deleting the file afterwards, is entirely their business.
- `--name` is the purpose in kebab-case; it becomes the filename the user
  reviews, so make it say what the script does.
- Staging still requires `.snowman/context.md` (bootstrap first).

## Guardrails (summary)

The wrapper makes these **ironclad** (see [references/guardrails.md](references/guardrails.md)
for the full policy and refusal messages):

- **Read-only only.** Leading keyword must be `SELECT` / `WITH` / `SHOW` /
  `DESCRIBE` / `EXPLAIN`; any write/DDL keyword anywhere is refused.
- **Single statement.** `;`-separated multi-statements are refused.
- **Comment- and string-safe.** Comments and string literals are stripped
  before the check, so a hidden `DROP` can't slip through.

These are **taught, not hard-blocked** (apply them yourself):

- **Cost hygiene.** Bound exploratory reads with `LIMIT`/`SAMPLE`; avoid
  full scans on large tables; surface the target warehouse first.
- **Lean metadata.** Prefer `SHOW TERSE`, `LIMIT`, `STARTS WITH`, and
  `->> SELECT "col",... FROM $1` to project SHOW/DESCRIBE output; never
  `SELECT *` on a wide table without a column list or a small `SAMPLE`.
- **Start broad, then narrow.** Databases, then schemas, then tables, then
  DESCRIBE, then SAMPLE; prefer several focused queries over one large one.
  Narrow toward the question asked: an anomaly you pass on the way gets a
  sentence in the answer, not an investigation of its own.
- **Run the queries yourself.** No subagent per query or per table, and none
  to re-check a result you have; one only for a wide, independent investigation.
- **Report, don't narrate.** One sentence on what you're looking for before
  the first query, then updates only when a result changes direction. Lead
  with the finding, rows after, large result sets truncated to what matters.
- **Database scope** is an advisory focus hint in the context file, not a
  hard wall. Snowflake roles already gate real read access.

## Workflows

Load [references/workflows.md](references/workflows.md) for the playbook
matching the user's intent: exploration, profiling, hypothesis, investigation.

## When to use / not use

**Use for:** exploring schemas, profiling tables, validating a transformation
hypothesis as a SELECT before building it in dbt, investigating data-quality
issues, discovering Snowflake objects, staging user-requested DML/DDL as
scripts for manual execution.

**Don't use for:** *executing* writes (there is no execute path for DML/DDL,
only staging), creating connections or storing credentials (the user does
that with `snow connection add`), or non-Snowflake databases. Its only
credential handling is relaying the project root `.env` to `snow`, opaquely.
