# metabase

The **`metabase`** agent skill operates a Metabase instance through its **REST
API** via the `mb` wrapper. It reads the SQL behind a question, traces where a
dashboard number actually comes from, runs read-only ad-hoc SQL against a
connected database, audits dashboard filter wiring, and edits cards and
dashboards under a restore-point gate.

The framing the whole skill hangs off: **a card is not a file, it is live.**
Editing card *N* changes what every dashboard viewer sees immediately, with no
deploy step and no undo in the UI. So reads run freely, and every mutation
captures a restore point first.

## What it does

- **Per-project bootstrap.** On first use there is no `.metabase/context.md`, so
  the skill runs `mb bootstrap`. It records the instance URL, the API key's
  identity (an API key user is **not** automatically a superuser, so a 403 can
  be a real permission boundary), and the database id→name table. Committed, so
  the agent never guesses which database `--db 8` is.
- **Reads the SQL a question really runs.** A card holds either native SQL or
  MBQL (what the graphical editor produces). `mb sql-of <id>` prints native
  verbatim and **compiles** MBQL through `POST /api/dataset/native`, the only
  practical way to answer "what SQL does this question run?". `--compiled`
  substitutes `{{tag}}` / `[[…]]`, which are Metabase syntax and not runnable
  SQL.
- **Source-chain and blast-radius tracing.** Cards stack on cards, so a
  dashboard number can sit three cards from the tables. `mb deps <id>` walks the
  chain downward; `--deep` adds transitive dependents plus a SQL-similarity scan
  for **frozen copies**, cards holding an inlined compiled snapshot of an
  upstream card, which look identical in the UI but silently stopped inheriting
  upstream edits.
- **Dashboard wiring audit.** Metabase serialises the same field reference in
  **two argument orders**: `["field", {opts}, id]` inside a card,
  `["field", id, {opts}]` inside a dashcard's `parameter_mappings`. Code that
  knows only one order fixes the card and leaves the dashboard filter pointing
  at the old database. The dashboard renders, the card runs, only the filter is
  dead. `mb wiring <dashboard-id>` resolves every id in every mapping, flags any
  belonging to another database than its card, and exits 1 on a finding.
- **Read-only ad-hoc SQL.** `mb sql "<SQL>" --db <id>` strips comments and
  string literals (dollar-quoted and `E''` forms included), then rejects
  multi-statements, non-read-only leading keywords, write/DDL keywords anywhere,
  `SELECT … INTO`, and side-effecting functions. It is documented honestly as a
  **speed bump, not a sandbox**. The durable control is a read-only database
  role on the Metabase connection.
- **Restore-point-gated mutations.** `update-card`, `update-dashboard`,
  `create-*` and `restore` all go through the wrapper, which snapshots to
  `.metabase/restore-points/` (gitignored) before every write. Filenames encode
  the kind (`…__card139.json` vs `…__dashboard19.json`) and `restore` refuses a
  mismatch. Updates refuse unknown fields, `create-*` refuses the root
  collection without `--allow-root`, and `update-dashboard` refuses a shorter
  `dashcards` list without `--allow-removal` (a dashboard `PUT` replaces the
  whole list, so a partial one deletes the rest).
- **No DML/DDL path at all.** Metabase is a reporting layer; schema and data
  changes belong in the owning system's migrations.

## Credentials

Two values, and the wrapper never stores either.

- `METABASE_URL`: process environment, then the `url:` frontmatter in
  `.metabase/context.md`, then a `.env`.
- `METABASE_API_KEY`: process environment or a `.env` **only**; `context.md`
  never holds the key. Create it in the Metabase UI under
  Admin → Authentication → API keys.

Both lookups are anchored at the project root (nearest ancestor with `.git`), so
commands behave identically from any subdirectory. The skill's own rule is never
to echo a secret. That includes not testing for one with `${VAR:-no}`, which
prints the value when set.

The API usually sits behind a corporate VPN, so a sandboxed shell and a dropped
VPN both surface as a connection error; the wrapper's error message tells the
two apart by whether the host resolved.

## Install

See the [repo root README](../../README.md) for the general install patterns.
For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/metabase
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install metabase@relentless-data-skills
```

It activates when you ask about a Metabase question, card, or dashboard, or ask
for the SQL behind one.

## Files

- `SKILL.md`: the core doc, covering first-run routing, wrapper invocation, the
  source chain, the two field-reference orders, the mutation gate, and
  read-only SQL discipline.
- `references/api-reference.md`: every command, request shape, and endpoint
  behaviour, executed against a live instance (v0.57.3) and independently
  re-verified. Claims that could not be observed are marked as such.
- `references/mutations.md`: the mutation playbook, covering editing, dashboard
  writes, repointing at another database, and the verification recipe.
- `references/docs-map.md`: upstream doc URLs, validated weekly by CI.
- `scripts/mb.py`: the wrapper (stdlib only), covering config resolution,
  transport, the read-only SQL check, restore points, and the wiring audit.

## Maintenance / CI

Repo CI runs `scripts/lint_skill.py` against this skill's `SKILL.md`
(frontmatter, "Use when" trigger, line budget), `scripts/check_doc_urls.py`
against `references/docs-map.md`, and `tests/test_metabase.py` against
`scripts/mb.py`. See the [root README](../../README.md#maintenance--ci).
