# metabase — the mutation playbook

Load this before any write: editing a card, creating or editing a dashboard,
repointing either at another database, or verifying that a change landed.
Request shapes and endpoint behaviour live in
[api-reference.md](api-reference.md); this file is the procedure.

**A card is not a file — it is live.** Editing card *N* changes what every
dashboard viewer sees, immediately, with no deploy step and no undo in the UI.

## Editing a card — restore point, then verify

1. **Establish blast radius.** `mb deps <id> --deep` — which dashboards show
   this card, which cards are built on it, which may be frozen copies. Report it
   before editing.
2. **Capture a restore point.** `mb update-card` does this automatically into
   `.metabase/restore-points/`. Never bypass it with raw `curl`.
3. **Send only the fields you are changing.** `mb update-card <id> --file f.json`
   where the JSON holds just those fields; it refuses unknown fields.
4. **Verify against a number you predicted.** Re-run the card and reconcile row
   counts and group totals against what you expected *before* the edit. "It
   returned rows" is not verification.

Undo is `mb restore <id> --file <restore-point>`, which restores the same field
set `update-card` can change — including `archived` and `collection_id`, so an
accidental archive or collection move is recoverable.

Creating a card is additive — a new card appears on no dashboard until someone
places it there. `create-card` still refuses to land it in the root collection
(the instance front page) unless you pass `--allow-root` deliberately.

## Dashboards mutate through the wrapper too

`mb create-dashboard`, `mb update-dashboard` and `mb restore <id> --dashboard`
carry the same restore-point gate as their card equivalents; `mb backup <id>
--dashboard` snapshots one on its own. Restore-point filenames encode the kind
(`…__card139.json` vs `…__dashboard19.json`) and `restore` refuses a mismatch,
because the two shapes are not interchangeable and the damage would be silent.

**A `PUT` replaces the entire `dashcards` list**, so omitting a dashcard removes
that card from the dashboard. That is the right way to unplace a card without
touching the card itself — but it means a partial list silently deletes the
rest, so `update-dashboard` refuses a shorter list without `--allow-removal`.

Creating a dashboard is two calls (`POST` bare, then `PUT` the parameters and
dashcards); `create-dashboard` does both from one file.

Dashboard parameters may carry a non-null `default`, which silently changes what
every wired card returns. Read the defaults before reconciling any dashboard
number against a bare card run.

## Repointing a card or dashboard at another database

Ids are per-database — the same column has a different field id in each
database, and the same table a different table id. Build the id map from
`GET /api/database/<id>/metadata` on **both** sides, matching on table+column
*name*, then remap all six carriers:

| Carrier | Where |
| ------- | ----- |
| `database` | `dataset_query.database` |
| `source-table` | MBQL source (an id, not a name) |
| field ids | positional — in **both** argument orders |
| `source-field` | the FK column id behind an implicit join; a value under a key |
| `source-card` | card-on-card |
| `parameter_mappings[].target` | the dashboard's wiring, separate from the card |

`source-card` is the one that bites. A cloned card still pointing at the prod
upstream renders perfectly and shows prod data on a dashboard labelled test.

Before promising a repoint, confirm:

- the target exposes the **same column names** — name-bound mappings
  (`["field", "backup_key", …]`) break otherwise;
- FK metadata exists there (`fk_target_field_id`), or MBQL implicit joins will
  not compile;
- the target actually holds rows for the entity being filtered on — an empty
  result reads identically to a broken query.

Then verify, in this order:

1. `mb wiring <new dashboard>` — zero cross-database ids, exit 0.
2. Assert no source-database id survives anywhere in each new card's
   `dataset_query`, and that `source-card` points at the *new* upstream.
3. Reconcile row counts and group breakdowns against independent
   `mb sql --db <target>` — not against "it returned rows".
4. Exercise **every** mapped filter, not one.

## Verifying a dashboard, specifically

Card-level checks do not cover dashboards. Three failures this skill has
actually shipped, and the check for each:

- **Clean card, broken wiring.** A card's `dataset_query` can be perfect while
  its `parameter_mappings` reference another database. Audit the wiring
  separately: `mb wiring <id>`.
- **One filter proves nothing.** Filters bind by four different mechanisms
  (template tag, column name, expression name, physical field id) that fail
  independently. Exercise *every* mapped parameter with a real value, and
  reconcile each filtered count against independent `mb sql`. Confirm the
  unmapped ones match the original's gaps rather than being quietly widened.
- **A diff that normalises away the bug.** If your comparison applies the same
  transformation to both sides, a flaw in it reports "identical". Check against
  an independent oracle, not against your own normaliser.

**Source tables are usually live.** Row counts drift between two runs because
real rows land in between. Reconcile against a *freshly re-read* baseline, and
when a count moves, check for an insert before suspecting your change.
