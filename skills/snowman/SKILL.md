---
name: snowman
description: Use when exploring Snowflake data, profiling tables, testing hypotheses, investigating data-quality issues, or discovering schemas and warehouses via the snow CLI. Strictly read-only - never writes, never mutates production.
---

# snowman

Read-only Snowflake exploration via the `snow` CLI — schema discovery, data
profiling, hypothesis testing, and data-quality investigation. **It never
writes and never mutates production.** Every query runs through a guardrail
wrapper that hard-rejects anything that isn't a single read-only statement.

## First action, every invocation

Check for **`.snowman/context.md`** in the project root.

- **Absent** → this is a first run. Read [references/install.md](references/install.md),
  run the bootstrap (discovers connection, databases, warehouses, roles →
  writes `.snowman/context.md`), then continue.
- **Present** → load it; it is the source of truth for this project's
  Snowflake architecture. Continue with the user's request.

**Refuse to run queries when no context file exists.** The context is
per-project and committed to the repo; it holds *names only*, never secrets.

## Running queries — always via the wrapper

Never call `snow sql` directly. Every query goes through the wrapper, which
injects the connection + `--format JSON` and enforces read-only:

```bash
python3 <skill-dir>/scripts/snowman.py "<SQL>"
```

`<skill-dir>` is this skill's directory. The wrapper reads the connection
from `.snowman/context.md`, so you never pass `--connection` yourself.

If the wrapper exits with `BLOCKED: …`, **do not work around it** — the
statement was non-read-only. Rephrase as a read-only query or tell the user
why their request can't be served by this skill.

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
issues, discovering Snowflake objects.

**Don't use for:** anything that writes (DML/DDL), creating connections or
handling credentials (the user does that with `snow connection add`), or
non-Snowflake databases.
