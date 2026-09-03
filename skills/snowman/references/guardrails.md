# snowman guardrails

Two tiers: rules the wrapper enforces, which no prompt can talk it out of,
and rules you apply as discipline (taught, not blocked). This file describes
the enforced tier. The taught rules live in SKILL.md under "Guardrails
(summary)".

## Hard-enforced by `scripts/snowman.py`

Every query runs through the wrapper. Before anything reaches Snowflake, the
wrapper:

1. **Strips comments and string literals** (`/* */`, `--`, `//`, `'...'`,
   and dollar-quoted `$$...$$`) so nothing hidden in a comment or quoted
   string can smuggle past the checks.
2. **Rejects multiple statements.** `;`-separated statements are refused. A
   single trailing `;` is fine.
3. **Checks the leading keyword.** It must be `SELECT`, `WITH`, `SHOW`,
   `DESCRIBE` (or `DESC`), or `EXPLAIN`. Anything else is refused.
4. **Scans for write and DDL keywords anywhere.** The list includes `INSERT,
   UPDATE, DELETE, MERGE, TRUNCATE, DROP, CREATE, ALTER, REPLACE, GRANT,
   REVOKE, CALL, EXECUTE, COPY, PUT, REMOVE, UNDROP, USE, SET` and more. This
   scan catches `WITH ... INSERT` and similar. If any of them appears, the
   wrapper refuses the query.
5. **Injects** `--connection <from context>` and `--format JSON_EXT`, then
   renders the result itself (see "Output shaping" below). It reads the
   connection from `.snowman/context.md` and refuses to run with no context
   file. In a multi-environment context (`environments:` map, separate dev
   and prod accounts) it resolves `--env <name>`, falling back to
   `default_env`. It blocks an unknown environment name, `--env` against a
   single-`connection:` context, a context defining both forms, and a
   multi-environment context with no `default_env` when no `--env` is given.
   Environment selection is per-query. There is no sticky "current
   environment" state.

On refusal the wrapper prints `BLOCKED: <reason>` to stderr and exits with
code 2. Nothing has reached Snowflake at that point.

### Output shaping

The wrapper parses snow's JSON and prints it as CSV. The header row comes
first. An empty cell is NULL. VARIANT, OBJECT, and ARRAY cells are compact
JSON. Numbers are untouched. Lines starting with `# ` are wrapper footers,
never data, in this order:

- `# empty cells are NULL` when any shown cell was NULL.
- `# some cells truncated to 200 chars; pass --max-cell 0 for full values`
  when a string or nested-JSON cell exceeded `--max-cell N` (default 200)
  and was cut to `<prefix>…(+K chars)`.
- `# showing 50 of 1203 rows; full result: .snowman/results/<timestamp>__<sha1-8>.csv; add LIMIT or a WHERE filter to narrow, or pass --max-rows 0`
  when the result exceeded `--max-rows N` (default 50). The spill file holds
  every row, untruncated. It is gitignored through a `.gitignore` the wrapper
  maintains in `.snowman/results/`, like staged files, and cleanup is the
  user's. In bootstrap mode (`--connection`, no context file) nothing is
  saved and the footer says so.
- `# 0 rows` for an empty result.

`--json` prints the same capped rows as a compact JSON array instead (NULL
stays `null`), for VARIANT-heavy results you want to `json.loads`. `--json`
output keeps the row cap and truncates string cells only. In that mode
NUMBER columns with a scale arrive as quoted strings, for example `"1.50"`,
while integer values are bare. That is snow's JSON encoder behaviour, so
parse them rather than expecting bare numbers.

SQL errors arrive on stderr as one
`ERROR: <code> (<sqlstate>): <query id>: <message>` line, with snow's exit
code forwarded (5 = SQL error). Other errors, such as an unknown connection
name, arrive as a one-line `ERROR: <message>` with snow's exit code (1 for an
unknown connection).

### Note on the keyword scan

The check matches whole words against the comment-stripped and
string-stripped SQL. Identifiers like `update_date` or `created_at` do not
trigger it, because the `_` keeps them part of the same word. A read-only
query that uses one of the listed words as a bare word (for example an alias
named `set`) is blocked too.

## Staging writes: `--stage` (never executed)

`python3 scripts/snowman.py --stage "<SQL>" --name <purpose-slug>` writes the
SQL to `.snowman/staged/<timestamp>__<slug>.sql` instead of running it.
Execution is always the user's manual act. snowman has no execute path for
writes, by design.

What stage mode enforces and what it deliberately does not:

- **Requires the context file**, same as the execute path. The staged file's
  header embeds the exact `snow sql -f <file> --connection <conn>` run
  command, which needs the connection name from `.snowman/context.md`.
- **Multi-environment projects require an explicit `--env`.** There is no
  `default_env` fallback for staging, because the header's run command
  targets a real account. The environment lands in the filename
  (`<timestamp>__<env>__<slug>.sql`) and in a `-- target environment:` header
  line, so the reviewing human sees the target twice before the run command.
- **No read-only check, no single-statement check.** A real migration is
  several statements. The execute-path rules exist to protect execution, and
  nothing executes here. Only an empty script is refused.
- **Destructive keywords warn, never block.** `DROP`, `TRUNCATE`, `DELETE`,
  `REPLACE`, `GRANT`, `REVOKE`, and `REMOVE` add a `-- WARNING:` line to the
  file header so the reviewing human sees the dangerous bits flagged.
- **Gitignored scratch.** The wrapper maintains `.snowman/staged/.gitignore`
  (`*`), so staged scripts never land in the repo. There is no lifecycle
  machinery. After the user runs a script, cleanup is theirs.

## Applied by you (taught, not blocked)

The wrapper deliberately does not enforce cost rules. Reliably telling a
runaway scan from a cheap aggregate needs real parsing, and false rejects on
`COUNT(*)` would be worse than the cost. The taught list (cost hygiene, lean
metadata, broad then narrow, reporting, database scope) lives in SKILL.md
under "Guardrails (summary)". One rule lives only here:

- **Production gets extra care.** Even though everything is read-only, treat
  `env: prod` databases, and prod environments in multi-account projects,
  with extra care: smaller samples, tighter filters, no expensive scans.

## Database scope

The context file lists in-scope databases as a focus hint, not a wall. The
wrapper does not block queries to out-of-scope databases. Snowflake roles
already gate real read access.
