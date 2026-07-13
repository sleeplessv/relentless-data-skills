---
name: snowman
description: Use for any Snowflake work — running a query, exploring data, profiling tables, testing hypotheses, investigating data-quality issues, discovering schemas and warehouses, or staging a data/schema change. Every snow CLI call goes through this skill.
---

# snowman

Read-only Snowflake exploration via the `snow` CLI — schema discovery, data
profiling, hypothesis testing, and data-quality investigation. **It never
executes writes and never mutates production.** Every executed query runs
through a guardrail wrapper that hard-rejects anything that isn't a single
read-only statement. When the user asks for a change, the DML/DDL is *staged*
as a script for them to run manually — snowman itself never runs it.

## First action, every invocation

Check for **`.snowman/context.md`** in the project root.

- **Absent** → this is a first run. Read [references/install.md](references/install.md),
  run the bootstrap (discovers connection, databases, warehouses, roles →
  writes `.snowman/context.md` and offers a Snowflake routing rule for the
  project's `AGENTS.md`/`CLAUDE.md`), then continue.
- **Present** → load it; it is the source of truth for this project's
  Snowflake architecture. Continue with the user's request.

**Refuse to run queries when no context file exists.** The context is
per-project and committed to the repo (names only, never secrets — see
[references/install.md](references/install.md)).

## Running queries — always via the wrapper

Never call `snow sql` directly. Every query goes through the wrapper, which
injects the connection + `--format JSON` and enforces read-only:

```bash
python3 <skill-dir>/scripts/snowman.py "<SQL>"
```

`<skill-dir>` is this skill's directory. The wrapper reads the connection
from `.snowman/context.md`, so you never pass `--connection` yourself (the
only exception is the bootstrap, before the context file exists — see
[references/install.md](references/install.md)).

The wrapper also relays the project root `.env` (if present) into the `snow`
subprocess — this is how key-pair connections with an encrypted private key
get their passphrase. Never source `.env` yourself, and never print its
contents.

**Run outside the sandbox.** The `snow` CLI needs network access to reach
Snowflake; a sandboxed shell blocks it, and the failure surfaces as a
DNS/connection error that looks like a broken connection config. Run every
wrapper (and `snow`) command with sandboxing disabled. If a query fails with
a connection/DNS error, suspect the sandbox first — do not start debugging
the connection setup.

On an auth-looking failure (private key, passphrase, JWT, OAuth, token) the
wrapper looks up the connection's authenticator and prints a hint matched to
it: browser auth (OAuth/SSO) needs the user to run
`snow connection test -c <name>` in their own terminal once — a browser
opens and `snow` caches the token; key-pair auth needs the passphrase in the
project root `.env` (e.g. `PRIVATE_KEY_PASSPHRASE=...`). Relay the hint to
the user; do not debug `connections.toml`, ask for the passphrase, or try to
drive the browser flow from inside the session.

If the wrapper exits with `BLOCKED: …`, **do not work around it** — the
statement was non-read-only. If the user asked a read-only question, rephrase
the query. If the user genuinely asked for a data/schema change, use staging
(below). **Never stage SQL the user didn't ask to have run** — staging is
driven by the user's stated intent, not by a block you want to get past.

## Environments (dev/prod in separate accounts)

When the context frontmatter has an `environments:` map (one entry per
account, each with its own connection — see
[references/install.md](references/install.md)), selection is **stateless and
per-query**:

- Queries hit `default_env` unless you pass `--env <name>`. Do that only when
  the user explicitly asks about another environment, and say which
  environment you're querying when it isn't the default.
- **Staging requires explicit `--env`** in these projects. If the user didn't
  say which environment a change targets, **ask** — never infer. The env
  lands in the staged filename and header so the reviewer sees the target.
- Single-account projects keep the plain `connection:` form; `--env` is
  rejected there.

## Staging writes (DML/DDL) — never executed

When the user explicitly asks for a change (add a column, backfill, create a
table…), write the SQL but **stage it instead of running it**:

```bash
python3 <skill-dir>/scripts/snowman.py --stage "<SQL>" --name <purpose-slug>
```

- The wrapper writes `.snowman/staged/<timestamp>__<slug>.sql` (gitignored,
  multi-statement fine, any keywords allowed) with a header containing the
  exact `snow sql -f … --connection …` command to run it.
- **Nothing is executed** — relay the file path and run command to the user;
  executing, and deleting the file afterwards, is entirely their business.
- `--name` is the purpose in kebab-case; it becomes the filename the user
  reviews, so make it say what the script does.
- Staging still requires `.snowman/context.md` (bootstrap first).

## Guardrails (summary)

The wrapper makes these **ironclad** (see [references/guardrails.md](references/guardrails.md)
for the full policy and refusal messages):

- **Read-only only** — leading keyword must be `SELECT` / `WITH` / `SHOW` /
  `DESCRIBE` / `EXPLAIN`; any write/DDL keyword anywhere → refused.
- **Single statement** — `;`-separated multi-statements → refused.
- **Comment- and string-safe** — comments and string literals are stripped
  before the check, so a hidden `DROP` can't slip through.

These are **taught, not hard-blocked** (apply them yourself):

- **Cost hygiene** — bound exploratory `SELECT *` with `LIMIT`/`SAMPLE`;
  avoid full scans on large tables; surface the target warehouse first.
- **Start broad, then narrow** — databases → schemas → tables → DESCRIBE →
  SAMPLE; prefer several focused queries over one large one.
- **Database scope** is an advisory focus hint in the context file, not a
  hard wall — Snowflake roles already gate real read access.

## Workflows

Load [references/workflows.md](references/workflows.md) for the playbooks:
exploration, profiling, hypothesis testing, and investigation. Pull the one
matching the user's intent; don't load all of it pre-emptively.

## When to use / not use

**Use for:** exploring schemas, profiling tables, validating a transformation
hypothesis as a SELECT before building it in dbt, investigating data-quality
issues, discovering Snowflake objects, staging user-requested DML/DDL as
scripts for manual execution.

**Don't use for:** *executing* writes (there is no execute path for DML/DDL —
only staging), creating connections or storing credentials (the user does
that with `snow connection add`), or non-Snowflake databases. The only
credential handling snowman does is relaying the project root `.env` to the
`snow` subprocess, opaquely.
