---
name: snowman
description: Use when doing any Snowflake work, including running a query, exploring data, profiling tables, testing hypotheses, investigating data-quality issues, discovering schemas and warehouses, or staging a data or schema change. Every snow CLI call goes through this skill.
---

<!-- SKILL.md sits at the 150-line budget that scripts/lint_skill.py enforces, so the long lines are deliberate. -->
# snowman

snowman is read-only Snowflake exploration through the `snow` CLI: schema
discovery, data profiling, hypothesis testing, and data-quality investigation.
**snowman never executes writes and never mutates production.** Every query
runs through a guardrail wrapper, `scripts/snowman.py`, which rejects anything
that is not a single read-only statement. When the user asks for a change, the
wrapper stages the DML or DDL as a script for the user to run. snowman never runs it.

## First action, every invocation

Check for `.snowman/context.md` in the project root (the wrapper finds it by walking up from the current directory).

- If the file is absent, this is a first run. Read
  [references/install.md](references/install.md) and run the bootstrap, which
  discovers the connection, databases, warehouses, and roles, writes
  `.snowman/context.md`, and offers a Snowflake routing rule for the project's
  `AGENTS.md` or `CLAUDE.md`. Then continue.
- If the file is present, load it. The context file is the source of truth
  for this project's Snowflake architecture. Continue with the user's request.

**Refuse to run queries when no context file exists.** The context file is
per-project and committed to the repo. It holds names only, never secrets
(see [references/install.md](references/install.md)).

## Running queries, always through the wrapper

Never call `snow sql` directly. Every query goes through the wrapper, which
injects the connection, enforces read-only, and returns CSV:

```bash
python3 <skill-dir>/scripts/snowman.py "<SQL>"
```

`<skill-dir>` is this skill's directory. The wrapper reads the connection
from `.snowman/context.md`. Never pass `--connection` yourself, except during
the bootstrap, before the context file exists ([references/install.md](references/install.md)).

Output is CSV (header row, empty cell for NULL, nested values as compact JSON)
plus `#` footer lines, which are notes, never data. The wrapper shows 50 rows
(`--max-rows N`, `0` for all). When a context file exists, it saves an overflowing
result in full to `.snowman/results/*.csv`. Before bootstrap nothing is saved, so
narrow the query or pass `--max-rows 0`. String and nested-JSON cells are cut at 200 chars
(`--max-cell N`, `0` for full values). `--json` prints a compact JSON array instead, for VARIANT-heavy results.

The wrapper also relays the nearest `.env` at or above the project root, if
any, into the `snow` subprocess. That relay is how encrypted key-pair connections get their passphrase.
Never source `.env` yourself, and never print its contents.

**Run outside the sandbox.** The `snow` CLI needs network access. A sandboxed
shell blocks it, and the failure surfaces as a DNS or connection error that
looks like a broken connection config. Run every wrapper and `snow` command
with sandboxing disabled. If a query fails with a connection or DNS error,
suspect the sandbox first, not the connection setup.

On an auth-looking failure the wrapper prints a hint matched to the
connection's authenticator. Browser auth (OAuth or SSO) needs the user to run
`snow connection test -c <name>` in their own terminal once, after which `snow`
caches the token. Key-pair auth with an encrypted key needs the passphrase in
the project root `.env` (for example `PRIVATE_KEY_PASSPHRASE=...`). Relay the
hint. Do not debug `connections.toml`, ask for the passphrase, or drive the browser flow.

If the wrapper exits with `BLOCKED: ...`, **do not work around it**. The
statement was not read-only. If the user asked a read-only question, rephrase
the query. If the user explicitly asked for a change, stage it (below). **Never
stage SQL the user did not ask to have run.** Staging follows stated intent,
not a block you want past.

## Environments (dev and prod in separate accounts)

When the context frontmatter has an `environments:` map (one entry per
account, each with its own connection, as described in
[references/install.md](references/install.md)), selection is stateless and per-query:

- Queries hit `default_env` unless you pass `--env <name>`. Pass it only when
  the user explicitly asks about another environment, and say which
  environment you are querying when it is not the default.
- **Staging requires an explicit `--env`** in these projects. If the user did
  not say which environment a change targets, **ask**. Never infer. The
  environment name lands in the staged filename and header so the reviewer sees the target.
- Single-account projects keep the plain `connection:` form. The wrapper
  rejects `--env` there.

## Staging writes, never executed

When the user explicitly asks for a change (add a column, backfill, create a
table, or similar), write the SQL but **stage it instead of running it**:

```bash
python3 <skill-dir>/scripts/snowman.py --stage "<SQL>" --name <purpose-slug>
```

- The wrapper writes `.snowman/staged/<timestamp>__<slug>.sql` with a header
  that holds the exact `snow sql -f ... --connection ...` command to run it.
  The file is gitignored, may hold several statements, and may use any keyword.
- **Nothing is executed.** Relay the file path and run command to the user.
  Running the file, then deleting it, is their business.
- `--name` is the purpose in kebab-case. It becomes the filename the user
  reviews, so make it say what the staged script does.
- Staging still requires `.snowman/context.md` (bootstrap first).

## Guardrails (summary)

The wrapper hard-enforces these (see [references/guardrails.md](references/guardrails.md) for the full policy and refusal messages):

- **Read-only only.** The leading keyword must be `SELECT`, `WITH`, `SHOW`,
  `DESCRIBE`, `DESC`, or `EXPLAIN`. Any write or DDL keyword anywhere is refused.
- **Single statement.** `;`-separated multi-statements are refused. A single trailing `;` is fine.
- **Comment- and quote-safe.** The wrapper strips comments, string literals,
  and quoted identifiers before the check, so a hidden `DROP` cannot slip through.

These are taught, not hard-blocked. Apply them yourself:

- **Cost hygiene.** Bound exploratory reads with `LIMIT` or `SAMPLE`. Avoid
  full scans on large tables. State which warehouse the queries will use, from
  `CURRENT_WAREHOUSE()` or the context file, before the first heavy query.
- **Lean metadata.** Prefer `SHOW TERSE`, `LIMIT`, `STARTS WITH`, and `->> SELECT "col",... FROM $1` to project SHOW and DESCRIBE output.
  `SHOW TERSE` omits `rows` and `bytes`, so for sizes project the plain `SHOW` (example in [references/workflows.md](references/workflows.md)). Snowflake ignores TERSE for some objects, such as warehouses, and there projection is what shrinks the output. Never `SELECT *` on a wide table without a column list or a small `SAMPLE`.
- **Start broad, then narrow.** Databases, then schemas, then tables, then
  DESCRIBE, then SAMPLE. Prefer several focused queries over one large one.
  Narrow toward the question asked. An anomaly you pass on the way gets a
  sentence in the answer, not an investigation of its own.
- **Run the queries yourself.** No subagent per query or per table, and none
  to re-check a result you have. Use one only for a wide, independent investigation.
- **Report, don't narrate.** One sentence on what you are looking for before
  the first query, then updates only when a result changes direction. Lead with
  the finding, rows after, large result sets truncated to what matters.
- **Database scope** is an advisory focus hint in the context file, not a
  hard wall. Snowflake roles already gate real read access. If the user needs a
  database that is not listed, query it and offer to re-run the bootstrap to record it.

## Workflows

Load [references/workflows.md](references/workflows.md) for the playbook matching the user's intent: exploration, profiling, hypothesis, investigation.

## When to use and when not to

Use snowman for exploring schemas, profiling tables, validating a transformation hypothesis as a SELECT before
building it in dbt, investigating data-quality issues, discovering Snowflake objects, and staging user-requested DML or DDL as scripts for manual execution.

Do not use snowman for executing writes (there is no execute path, only staging), for creating connections or
storing credentials (the user does that with `snow connection add`), or for non-Snowflake databases.
snowman's only credential handling is relaying the nearest `.env` at or above the project root to `snow`. It never prints or stores what it finds there.
