---
name: metabase
description: Use when working with Metabase, reading or editing a question/card, tracing where a dashboard number comes from, extracting the SQL behind a card, running ad-hoc SQL against a Metabase-connected database, or auditing dashboards. Every Metabase API call goes through this skill.
---

# metabase

Operate a Metabase instance through its REST API via the `mb` wrapper.

**A card is not a file, it is live.** Editing card *N* changes what every
dashboard viewer sees, immediately, with no deploy step and no undo in the UI.
So reads run freely, and every mutation captures a **restore point** first.

## First action, every invocation

Check for **`.metabase/context.md`** in the project root.

- **Absent** → run `python3 <skill-dir>/scripts/mb.py bootstrap`. It writes the
  instance URL, the API key's identity, and the database id→name table, then
  continue.
- **Present** → load it. It is the source of truth for the instance URL and
  which database id is which. **Never guess a database id.** `--db 8` means
  nothing until you know 8 is production Postgres.

## Invocation, always via the wrapper

```bash
python3 <skill-dir>/scripts/mb.py <command> [args]
```

`METABASE_URL` resolves from the process environment, then the `url:`
frontmatter in `.metabase/context.md`, then `.env` files. `METABASE_API_KEY`
resolves from the environment or a `.env` only. **`context.md` never holds the
key.** Both lookups are anchored at the project root, so every command behaves
the same from any subdirectory.

**Never echo a secret.** Don't source a `.env` yourself, don't print its
contents, and don't test for a variable with a shell idiom that can expand it.
`${VAR:-no}` prints the *value* when set. Use `[ -n "$VAR" ] && echo set`.

**Run outside the sandbox, and expect the VPN to matter.** The API is usually
behind a corporate VPN; a sandboxed shell or a dropped VPN both surface as a
connection error. Host did not resolve → suspect a typo'd URL; resolved then
timed out → suspect the VPN or the sandbox.

Full command list, request shapes, and doc citations:
[references/api-reference.md](references/api-reference.md). Read it before
hand-rolling a `curl`. The wrapper already covers the common paths, and the
reference records the request envelopes that are easy to get wrong. Doc URLs to
fetch when it falls short: [references/docs-map.md](references/docs-map.md).

## Reading a card

A card holds **either** native SQL **or** MBQL (Metabase's query language, what
the graphical editor produces). `mb sql-of <id>` handles both: it prints native
SQL verbatim, and **compiles** MBQL to the real SQL Metabase sends to the
database. When a user asks "what SQL does this question run?", MBQL means the
card JSON alone does not answer it, so compile it. Native SQL printed verbatim
is **not runnable as-is** either: `{{tag}}` and `[[…]]` are Metabase syntax,
not SQL. `mb sql-of <id> --compiled` substitutes them.

## The source chain

Cards stack: a card's source can be a table **or another card**, so a dashboard
number may sit three cards from the tables. Trace the whole chain before
concluding anything about where a number comes from. `mb deps <id>` walks it
downward; `--deep` adds transitive dependents and a SQL-similarity scan. Use it
before any edit. Two traps live in this chain:

- **A frozen copy.** Some cards inline a *compiled snapshot* of an upstream
  card's SQL as native text rather than holding a live reference. It looks
  identical in the UI and silently stops inheriting upstream edits. Plain `deps`
  sees only live references; `--deep` surfaces likely frozen copies by SQL
  similarity. Say plainly which dependents will *not* inherit a change.
- **Filters bind by name.** A dashboard filter maps onto a card by template tag,
  column name, expression name, or physical field id. Only the field-id form is
  immune to renaming, and column-name mappings survive a source swap **only if
  the new source keeps the same column names**. Check `mb dashboard <id>` before
  and after any repointing.

## Field references come in two argument orders

Inside a card's `dataset_query` a field is `["field", {opts}, <id>]`; inside a
dashcard's `parameter_mappings` it is `["field", <id>, {opts}]`. **Id and opts
swap places.** Code that rewrites ids must key off which position holds the
integer and handle both, plus `source-field` (the FK behind an implicit join)
and `source-table`, which hide as values under a key. Miss one and the card is
fixed while the dashboard wiring still points at the old database. It renders,
the card runs, only the filter is dead, and a naive prod-vs-copy diff reports
"identical", because the same blind spot ran on both sides. `mb wiring
<dashboard-id>` resolves every id in every mapping and flags any belonging to a
different database than its card; run it after any edit that touches dashboard
filters, and treat a non-zero exit as a stop.

## Mutating anything, restore point then verify

Every write goes through the wrapper, which captures a restore point into
`.metabase/restore-points/` first. Never bypass it with raw `curl`.

1. **Establish blast radius.** `mb deps <id> --deep` shows which dashboards
   display it, which cards are built on it, and which may be frozen copies.
   Report it first.
2. **Send only the fields you are changing.** `mb update-card <id> --file f.json`
   holds just those; it refuses unknown ones. Same for `update-dashboard`, except
   a dashboard `PUT` replaces the *entire* `dashcards` list, so a short list
   deletes the rest, and it refuses one without `--allow-removal`.
3. **Verify against a number you predicted**, before the edit, not "it returned
   rows". Dashboards need their own checks: `mb wiring <id>`, plus every mapped
   parameter exercised, because the four binding mechanisms fail independently.

Undo is `mb restore <id> --file <restore-point>` (`--dashboard` for a
dashboard), restoring the same field set the update commands can change,
including `archived` and `collection_id`, so an accidental archive or collection
move is recoverable.

For repointing at another database (six id carriers to remap), the dashboard
verification failures this skill has actually shipped, and the drift caused by
live source tables, see [references/mutations.md](references/mutations.md).
Read it before any write.

## Ad-hoc SQL is read-only

`mb sql "<SQL>" --db <id>` runs one statement. The wrapper strips comments and
string literals (including dollar-quoted and `E''` forms), then rejects
multi-statements, non-read-only leading keywords, write/DDL keywords anywhere,
`SELECT … INTO`, and functions with side effects.

**This is a speed bump, not a sandbox.** A string-level check cannot cover every
volatile function or user-defined write. The durable control is a **read-only
database role** on the Metabase connection; recommend that rather than implying
the wrapper is airtight. On `BLOCKED: …`, **do not work around it.** Rephrase
the read-only question. Metabase is a reporting layer; schema and data changes
belong in the owning system's migrations, never here.

Bound exploration with `LIMIT`, aggregate server-side rather than pulling rows
to count them, and treat any database whose context-file name marks it
production with extra care. **Project to the columns you need.** Reporting
databases carry payload columns (key material, blob/`data` columns, signed
URLs) that a `SELECT *` or a bare `mb run <id>` will dump into the transcript.
Name your columns, and use `mb run <id> --count` when the row count is the answer.

## When to use / not use

**Use for:** extracting the SQL behind a question, tracing a dashboard number to
its source tables, ad-hoc read-only SQL, auditing which dashboards use a card,
repointing cards or dashboards at another database, and creating or editing them
under the restore-point gate. **Don't use for:** executing DML/DDL (no path
exists, use the owning system's migrations), managing users/permissions/API
keys, or modelling work that belongs in dbt: a transformation several questions
need is a dbt model, not a fourth card in a source chain.
