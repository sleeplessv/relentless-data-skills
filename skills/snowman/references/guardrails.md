# snowman — guardrails

Two tiers: what the **wrapper hard-enforces** (cannot be talked out of), and
what **you apply** as discipline (taught, not blocked).

## Hard-enforced by `scripts/snowman.py`

Every query runs through the wrapper. Before anything reaches Snowflake it:

1. **Strips comments and string literals** (`/* */`, `--`, `//`, `'…'`) so
   nothing hidden in a comment or quoted string can smuggle past the checks.
2. **Rejects multiple statements** — `;`-separated statements are refused;
   submit one statement at a time.
3. **Checks the leading keyword** — must be one of
   `SELECT`, `WITH`, `SHOW`, `DESCRIBE`/`DESC`, `EXPLAIN`. Anything else is
   refused.
4. **Scans for write/DDL keywords anywhere** — `INSERT, UPDATE, DELETE,
   MERGE, TRUNCATE, DROP, CREATE, ALTER, REPLACE, GRANT, REVOKE, CALL,
   EXECUTE, COPY, PUT, REMOVE, UNDROP, USE, SET, …`. This catches
   `WITH … INSERT` and similar. Present → refused.
5. **Injects** `--connection <from context>` and `--format JSON`; reads the
   connection from `.snowman/context.md` and **refuses to run with no context
   file**. In a multi-environment context (`environments:` map, separate
   dev/prod accounts) it resolves `--env <name>`, falling back to
   `default_env` — and blocks an unknown environment name, `--env` against a
   single-`connection:` context, a context defining both forms, and a
   multi-environment context with no `default_env` when no `--env` is given.
   Environment selection is per-query; there is no sticky "current
   environment" state.

On refusal the wrapper prints `BLOCKED: <reason>` to stderr and **exits
non-zero**. When you see that, do **not** work around it — the request was not
read-only. If the user asked a read-only question, rephrase the query. If the
user explicitly asked for a data/schema change, stage it (below).

### Note on the keyword scan

The check matches whole words against the comment/string-stripped SQL.
Identifiers like `update_date` or `created_at` do **not** trigger it (the `_`
keeps them part of the same word). If a *legitimate* read-only query is
wrongly blocked because a write keyword appears as a bare word, rephrase it —
do not bypass the wrapper.

## Staging writes — `--stage` (never executed)

`python3 scripts/snowman.py --stage "<SQL>" --name <purpose-slug>` writes the
SQL to `.snowman/staged/<timestamp>__<slug>.sql` instead of running it.
Execution is **always** the user's manual act — snowman has no execute path
for writes, by design.

What stage mode enforces and what it deliberately doesn't:

- **Requires the context file**, same as the execute path — the staged file's
  header embeds the exact `snow sql -f <file> --connection <conn>` run
  command, which needs the connection name from `.snowman/context.md`.
- **Multi-environment projects require an explicit `--env`** — no
  `default_env` fallback for staging, because the header's run command
  targets a real account. The environment lands in the filename
  (`<timestamp>__<env>__<slug>.sql`) and in a `-- target environment:` header
  line, so the reviewing human sees the target twice before the run command.
  If the user didn't say which environment a change targets, ask — never
  infer.
- **No read-only check, no single-statement check.** A real migration is
  several statements; the execute-path rules exist to protect execution, and
  nothing executes here. Only an empty script is refused.
- **Destructive keywords warn, never block.** `DROP`, `TRUNCATE`, `DELETE`,
  `REPLACE`, `GRANT`, `REVOKE`, `REMOVE` add a `-- WARNING:` line to the file
  header so the reviewing human sees the dangerous bits flagged.
- **Gitignored scratch.** The wrapper maintains `.snowman/staged/.gitignore`
  (`*`), so staged scripts never land in the repo. There is no lifecycle
  machinery — after the user runs a script, cleanup is theirs. Never delete a
  staged file yourself.

The intent rule (also in SKILL.md): stage **only** when the user explicitly
asked for a change. A `BLOCKED` execute is not an invitation to stage.

## Applied by you (taught, not blocked)

The wrapper deliberately does **not** enforce cost rules — reliably telling a
runaway scan from a cheap aggregate needs real parsing, and false rejects on
`COUNT(*)` would be worse than the cost. So apply these yourself:

- **Bound exploration.** Put `LIMIT` or `SAMPLE` on exploratory `SELECT *`
  against unknown tables. `SELECT * FROM big_table` with no bound is a
  mistake, not a guardrail violation — don't do it.
- **Avoid full scans.** Prefer `INFORMATION_SCHEMA` / `SHOW` / `GET_DDL` for
  metadata. Filter and aggregate server-side; don't pull rows to count them.
- **Mind the warehouse.** Surface the target warehouse before a heavy query;
  prefer the small ad-hoc/analytics warehouse from the context file.
- **Start broad, narrow fast.** databases → schemas → tables → DESCRIBE →
  SAMPLE. Several focused queries beat one sprawling one.
- **Production is read-only forever.** Even though everything is read-only,
  treat `env: prod` databases — and prod *environments* in multi-account
  projects — with extra care: smaller samples, tighter filters, no expensive
  scans.
- **Say when you're on prod.** Querying a non-default environment is taught
  etiquette, not wrapper-enforced: mention it ("querying **prod**") so the
  user always knows which account answered. The wrapper stays silent because
  prod reads are safe by construction — the discipline is yours.

## Database scope

The context file lists in-scope databases as a **focus hint**, not a wall.
The wrapper does not block queries to out-of-scope databases — Snowflake roles
already gate real read access. If the user needs a database that isn't in the
context, just query it (read-only) and offer to re-run the bootstrap to record
it.
