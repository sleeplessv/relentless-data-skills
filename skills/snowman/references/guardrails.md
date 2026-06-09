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
   file**.

On refusal the wrapper prints `BLOCKED: <reason>` to stderr and **exits
non-zero**. When you see that, do **not** work around it — the request was not
read-only. Rephrase as a read-only query, or tell the user this skill can't
serve a write/DDL request (that's by design; snowman has no write path in v1).

### Note on the keyword scan

The check matches whole words against the comment/string-stripped SQL.
Identifiers like `update_date` or `created_at` do **not** trigger it (the `_`
keeps them part of the same word). If a *legitimate* read-only query is
wrongly blocked because a write keyword appears as a bare word, rephrase it —
do not bypass the wrapper.

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
  treat `env: prod` databases with extra care: smaller samples, tighter
  filters, no expensive scans.

## Database scope

The context file lists in-scope databases as a **focus hint**, not a wall.
The wrapper does not block queries to out-of-scope databases — Snowflake roles
already gate real read access. If the user needs a database that isn't in the
context, just query it (read-only) and offer to re-run the bootstrap to record
it.
