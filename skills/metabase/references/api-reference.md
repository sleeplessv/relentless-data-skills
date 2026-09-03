# metabase: verified API reference

Every command and request shape below was **executed** against a live Metabase
instance (v0.57.3) and re-verified by an independent audit. Claims that could
not be observed are marked as such rather than asserted.

Sources are listed at the bottom. When something here is missing or an endpoint
behaves unexpectedly, **fetch the live docs** rather than guessing. Metabase's
API is versioned with the app and changes between releases.

`M=<skill-dir>/scripts/mb.py` throughout.

## Wrapper commands

| Command | Does |
| ------- | ---- |
| `python3 $M bootstrap [--force]` | Write `.metabase/context.md`. Refuses to clobber a file with no generated marker; `--force` keeps a copy first |
| `python3 $M sql "<SQL>" --db <id> [--limit N]` | Run one **read-only** statement, rows as JSON (default 200-row print cap) |
| `python3 $M card <id>` | Full card definition JSON |
| `python3 $M sql-of <id> [--compiled]` | Card's SQL, native verbatim, MBQL compiled. `--compiled` substitutes template tags so the output is runnable |
| `python3 $M run <id> [--count] [--limit N]` | Execute card. `--count` counts **server-side** where possible, falling back to client-side |
| `python3 $M deps <id> [--deep]` | Blast radius. `--deep` adds transitive dependents + likely frozen copies |
| `python3 $M search "<q>" [--model …] [--limit N]` | Find by name |
| `python3 $M dashboard <id> [--full]` | Dashboard summary: parameters (with type + default), filter wiring, series, tabs |
| `python3 $M wiring <id>  [--all]` | Audit a dashboard's filter wiring for field ids belonging to another database. Exits 1 on a finding |
| `python3 $M backup <id…> [--dashboard]` | Write restore point(s) for cards, or dashboards with `--dashboard` |
| `python3 $M update-card <id> --file f.json` | PUT changed fields (auto restore point) |
| `python3 $M create-card --file f.json [--allow-root]` | POST a new card; requires `collection_id` unless `--allow-root` |
| `python3 $M create-dashboard --file f.json [--allow-root]` | POST a new dashboard, then PUT `parameters`/`dashcards` if present |
| `python3 $M update-dashboard <id> --file f.json [--allow-removal]` | PUT changed fields (auto restore point). Refuses a shorter `dashcards` list without `--allow-removal` |
| `python3 $M restore <id> --file <rp> [--dashboard] [--force]` | PUT a card (or dashboard) back. Refuses another object's snapshot without `--force` |

`update-card` and `restore` share one field set, so anything the wrapper can
change it can also undo: `dataset_query`, `name`, `description`, `display`,
`visualization_settings`, `collection_id`, `collection_position`, `archived`,
`result_metadata`, `type`, `parameters`, `cache_ttl`.

`update-dashboard` and `restore --dashboard` share theirs: `name`,
`description`, `parameters`, `dashcards`, `tabs`, `collection_id`,
`collection_position`, `archived`, `cache_ttl`, `auto_apply_filters`, `width`.

Restore-point filenames encode the kind (`…__card139.json`,
`…__dashboard19.json`) because the two shapes are not interchangeable and
restoring one over the other would be silent damage.

## Auth

Header `x-api-key: <key>` on every request. Keys are created in the Metabase UI
(Admin → Authentication → API keys) and inherit a group's permissions. An API
key user is **not** automatically a superuser (verified: `is_superuser: false`),
so a 403 can be a real permission boundary rather than a bad key.

```bash
curl -s -H "x-api-key: $METABASE_API_KEY" "$URL/api/user/current"
```

Session auth (`POST /api/session` → `X-Metabase-Session`) also exists but is not
used here; API keys don't expire mid-task.

## Running queries

### A failed query is still a 2xx: read `status`, never the HTTP code

| endpoint | success | failure |
| -------- | ------- | ------- |
| `POST /api/dataset` | **202** | **202** + `{"status":"failed","error":…}` |
| `POST /api/card/<id>/query` | **202** | **202** + `status: failed` |
| `POST /api/dataset/json` | 200 | 200 |
| `POST /api/card/<id>/query/json` | 200 | 200 |

Branching on `== 200` gets `/api/dataset` backwards. Always inspect `status`.

### Ad-hoc SQL: `POST /api/dataset`

JSON body. Returns a column/row envelope, **not** objects.

```bash
curl -s -X POST -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  "$URL/api/dataset" \
  -d '{"database":8,"type":"native","native":{"query":"SELECT 1 AS a"}}'
```

Response: `.data.cols[]` + `.data.rows[][]`. **Key rows off `cols[].name`, not
`display_name`.** Metabase de-duplicates `name` (`id`, `id_2`) but leaves
`display_name` duplicated, so building a dict on `display_name` silently drops
columns and keeps the *last* value. (`SELECT 1 AS a, 2 AS a` → one key, value 2.)

### Ad-hoc SQL as objects: `POST /api/dataset/json`

Same query, rows as JSON objects. **This endpoint takes a form-encoded `query`
parameter, not a JSON body**, the single easiest mistake to make here.

```bash
# WORKS
curl -s -X POST -H "x-api-key: $KEY" \
  --data-urlencode 'query={"database":8,"type":"native","native":{"query":"SELECT 1 AS a"}}' \
  "$URL/api/dataset/json"

# REJECTED: {"specific-errors":{"query":["missing required key, received: nil"]}}
curl -s -X POST -H "Content-Type: application/json" \
  "$URL/api/dataset/json" -d '{"database":8,...}'
```

`/csv` and `/xlsx` variants take the same form encoding (both verified 200).

### Compile MBQL to SQL: `POST /api/dataset/native`

Post a card's `dataset_query` and get back the real SQL Metabase sends to the
database. This is the only practical way to answer "what SQL does this MBQL
question run?".

```bash
curl -s -X POST -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  "$URL/api/dataset/native" -d @q.json
# -> {"query":"SELECT …","params":null,"lib/type":…}
```

Observed for `display: pivot` (card 142): this returns the plain tabular
compilation, with no `GROUPING SETS`. The pivot UI computes subtotals separately
(`POST /api/dataset/pivot` returns pivoted rows), so the compiled SQL matches the
data but is not necessarily what the browser fires. The browser request itself
was not observed.

### Run a saved card: `POST /api/card/<id>/query/json`

```bash
curl -s -X POST -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  "$URL/api/card/142/query/json" -d '{}'      # -> [{col: val, …}, …]
```

`/query` (202 envelope form), `/query/csv`, `/query/xlsx` also exist. Cards with
required parameters need them in the body; `mb run` always sends `{}` and has no
flag to pass parameters, so use `curl` for a parameterised card.

## Cards

| Endpoint | Purpose |
| -------- | ------- |
| `GET /api/card/<id>` | Full definition (53 keys, 7–17 KB) |
| `GET /api/card` | **All** cards, 797 KB / 2.5 s for 85 cards; prefer `/api/search`. `mb deps` must use it, since search cannot match on `source_card_id` |
| `GET /api/card/<id>/dashboards` | Which dashboards embed this card (50 B / 0.25 s) |
| `GET /api/card/<id>/series` | Combinable cards. **400** unless display is `bar`/`scalar`/`line`/`area`; 200 with a card list otherwise. Not a dependency endpoint |
| `POST /api/card` | Create |
| `PUT /api/card/<id>` | Update (send only changed fields) |

`DELETE` exists but archiving (`PUT` with `{"archived":true}`) is the reversible
move; prefer it. Note Metabase also reassigns an archived card's `collection_id`
to the Trash collection, so restoring one means un-archiving *before* setting
`collection_id`.

### Card JSON: the fields that matter

- `dataset_query`: the query itself. Two shapes:
  - **native**: `stages[0].native` holds the SQL string. A legacy
    `dataset_query.native.query` shape exists in older instances.
  - **MBQL**: `stages[0]` with `breakout` / `aggregation` / `source-card`.
  - A card can have several stages: native stage 0 with an MBQL stage 1 on top.
    Reading `stages[0].native` alone would then be **wrong**; compile instead.
- `source_card_id`: the card this card is built on. **The source chain.** Not
  sufficient on its own: a `source-card` can appear nested inside a join, and a
  card referencing two sources reports only one here. Walk `dataset_query`
  recursively for every `source-card` / `source-table: "card__N"`.
- `display`: `table`, `pivot`, `bar`, and others. The API accepts an unknown
  value and stores it, producing an unrenderable card; validate before sending.
- `result_metadata`: column metadata including user-set display names and
  semantic types. Metabase recomputes it on save; send it only when restoring.
- `template-tags`: declared `{{tag}}` parameters for native cards.

### Creating a card: required vs recommended

`POST /api/card` rejects a body missing any of **`name`**, **`display`**,
**`dataset_query`**, **`visualization_settings`** (observed:
`{"<field>": ["missing required key, received: nil"]}`).

`type` and `collection_id` are **optional**, but omitting `collection_id` lands
the card in the **root collection**, the instance front page, which usually has
broader read access than a scoped collection. Always send it.

```json
{
  "name": "…",
  "display": "table",
  "collection_id": 42,
  "dataset_query": {"database": 8, "type": "native",
                    "native": {"query": "SELECT …", "template-tags": {}}},
  "visualization_settings": {}
}
```

A newly created card appears on no dashboard until someone adds it (card 190:
`dashboard_count: 0` after creation), so creation is additive; only `PUT`
changes what people currently see.

## Optional filters in native SQL

Metabase native SQL uses `{{tag}}` for a variable and `[[ … {{tag}} … ]]` for an
optional clause dropped when the tag is unset. In compiled output an unset
optional block collapses to a bare `--` comment, so **compiled SQL shows the
unparameterised query**, and supplying parameters changes its shape.

```sql
WHERE TRUE
  [[and customer_drs_id ILIKE '%' || {{customer_drs_id}} || '%']] --
```

A `dimension` tag (field filter) carries `widget-type` and a `dimension` field
reference; a plain `text`/`number`/`date` tag substitutes a value.

## Dashboards

| Endpoint | Purpose |
| -------- | ------- |
| `GET /api/dashboard` | List: a **bare JSON array** (not `{"data":…}`) of full dashboard metadata incl. `parameters`; **no `dashcards`** |
| `GET /api/dashboard/<id>` | Full, **including `dashcards`** |
| `POST /api/dashboard` | Create. Takes `name` (+ `description`, `collection_id`); **ignores `parameters`/`dashcards`** |
| `PUT /api/dashboard/<id>` | Update, including `parameters` and the `dashcards` layout |
| `POST /api/dashboard/<id>/copy` | Duplicate. `is_deep_copy: true` also clones the cards |

### Creating a dashboard is two calls

`POST` makes a bare dashboard; content lands on the follow-up `PUT`. New
dashcards take **negative placeholder `id`s**, which Metabase replaces with
real ones in the response.

```jsonc
// 1. POST /api/dashboard
{"name": "… (DAS-TST)", "collection_id": 42}
// 2. PUT /api/dashboard/<new id>
{"parameters": [ …copied verbatim… ],
 "dashcards": [{"id": -1, "card_id": 196, "row": 0, "col": 0,
                "size_x": 24, "size_y": 4,
                "parameter_mappings": [...], "visualization_settings": {},
                "series": []}]}
```

**A `PUT` replaces the whole `dashcards` list.** Omitting a dashcard removes
that card from the dashboard. That is the supported way to unplace one
without touching the card itself. `mb update-dashboard` refuses a shorter list
unless you pass `--allow-removal`.

`POST /api/dashboard/<id>/copy` is the alternative to building fresh, but note
what it does **not** solve: a copied card whose query has `source-card: N`
still needs that reference repointed at the copy of *N*. Verify, don't assume.

"Which dashboards use card N" is `GET /api/card/<id>/dashboards`, cheap and
direct. Iterating every dashboard also works but is slow.

Dashboard parameters carry a `type` and may carry a `default`. **A non-null
default silently changes what every wired card returns**, so read defaults
before reconciling any number against a card run.

### Filter wiring: `parameter_mappings`

Each dashcard maps dashboard parameters onto its card. Four target forms, and
the difference decides what survives an edit:

```jsonc
["variable",  ["template-tag", "customer_drs_id"]]                 // native: binds to {{tag}}
["dimension", ["template-tag", "created_at_filter"], {…}]          // native FIELD FILTER: binds to {{tag}}
["dimension", ["field", "backup_type", {…}], {"stage-number": 0}]  // binds by COLUMN NAME
["dimension", ["expression", "customer_drs_id", {…}], {…}]         // binds by EXPRESSION NAME
["dimension", ["field", 18607, {…}], {"stage-number": 0}]          // binds by physical FIELD ID
```

Template-tag forms break on tag rename. Column-name forms survive changing a
card's source **iff the new source exposes the same column name**. Only the
field-id form is immune to renaming.

### Field references come in TWO argument orders

This has bitten real work. The same logical reference is serialised
differently depending on where it lives:

```jsonc
// pMBQL: inside a card's dataset_query (stages[].fields, filters, expressions…)
["field", {"base-type": "type/DateTime"}, 18607]      // opts SECOND, id THIRD

// legacy: inside a dashcard's parameter_mappings target
["field", 18607, {"base-type": "type/DateTime"}]      // id SECOND, opts THIRD
```

Any code that walks the JSON rewriting ids **must handle both**, keyed on
*which position holds the int*, not on position alone. A remapper that knows
only the pMBQL form rewrites the card correctly and leaves the dashboard
mappings pointing at the old ids. Nothing surfaces: the dashboard renders, the
card runs, the filter is simply dead. A normalising diff of prod vs copy
reports "identical" because the same blind spot ran on both sides.

`mb wiring <dashboard-id>` exists for exactly this: it resolves every id in
every mapping and flags any that belongs to a different database than the card
it is attached to. Exit code 1 on a finding.

The wrapper's `walk_field_ids()` is the reference implementation; note also
that `source-field` (the FK on an implicit join) and `source-table` are plain
integer *values under a key*, not positional, so they need their own branch.

## Repointing a card or dashboard at another database

Cloning a prod dashboard against a test database is a routine ask. Ids are
**per-database**: DAS-PRD's `publics` is table 1003, DAS-TST's is 995, and the
same column has a different field id in each. Build the id map from
`GET /api/database/<id>/metadata` on **both** databases and match on
table+column *name*.

Five independent things carry an id. Miss any one and the copy silently reads
the wrong database:

| Where | Key | Notes |
| ----- | --- | ----- |
| `dataset_query.database` | `database` | The obvious one |
| MBQL source | `source-table` | Table id, not a name |
| Field references | positional | **Both argument orders**, see the two-orders section |
| Implicit-join filters | `source-field` | The FK column id; easy to miss, it is a value under a key |
| Card-on-card | `source-card` | **The dangerous one.** A clone still pointing at the prod upstream renders perfectly while showing prod data |
| Dashboard wiring | `parameter_mappings[].target` | Separate from the card; legacy field order |

Preconditions worth checking before promising anything:

- Do the tables exist in the target with the **same column names**? Column-name
  mappings (the `["field", "backup_key", …]` form) bind by name and break
  otherwise.
- Is FK metadata set on the target database? MBQL implicit joins
  (`organisations__via__organisation_id`) resolve through
  `fk_target_field_id`; without it the join does not compile.
- Does the target actually hold rows for the entity being filtered on? An
  empty result reads identically to a broken query.

Verification that actually catches the failures above:

1. `mb wiring <new dashboard>`: zero cross-database ids.
2. Assert no source-database id survives anywhere in each new card's
   `dataset_query`, and that `source-card` points at the *new* upstream.
3. Reconcile row counts and group breakdowns against independent
   `mb sql --db <target>`, not against "it returned rows".
4. **Exercise every mapped filter**, not one. Filters bind by four different
   mechanisms and they fail independently; a passing template-tag filter says
   nothing about a field-id filter on the same dashboard.

## Search

```bash
curl -s -G -H "x-api-key: $KEY" "$URL/api/search" \
  --data-urlencode "q=Secure File" --data-urlencode "models=card"
```

`models`: `card`, `dashboard`, `dataset` (models), `collection`, `table` (all
verified). Response is `{"data":[…], "total": N}`. 8 KB / 0.6 s vs 797 KB /
2.5 s for `GET /api/card`.

For `--model table`, keep `database_name` / `table_name` / `table_schema`: two
tables on different databases can share a display name, and the database name is
the only thing distinguishing PROD from TST.

**Search is best-effort.** The appdb index can lag. A card present in
`GET /api/card` was invisible to `/api/search`. Treat `GET /api/card` as
authoritative when completeness matters.

## Other useful reads

| Endpoint | Purpose |
| -------- | ------- |
| `GET /api/database` | Databases + ids (`{"data":[…]}`), the id for `--db` |
| `GET /api/database/<id>/metadata` | Tables + fields; 124 KB for db 8 |
| `GET /api/collection/<id>` | Collection name + location |
| `GET /api/collection/<id>/items` | Cards/dashboards inside |
| `GET /api/user/current` | Identity + `is_superuser`, confirms the key works |
| `GET /api/session/properties` | Instance settings incl. `version.tag`. 112 KB, sub-second; fetch only for the version |

## Gotchas observed

- **Ambiguous column errors** when joining `organisations`: qualify every column
  (`s.created_at`), since both sides commonly carry `created_at` and
  `updated_at`.
- **Postgres `Position: N` offsets** in error messages are against Metabase's
  wrapped query (~130 chars of preamble), so they do not line up with the SQL you
  typed.
- **`GET /api/card/<id>/series` returns 400** for a non-combinable display. It
  is not a general dependency endpoint.
- **A bare `SELECT *` on a reporting table** may return key material: columns
  like `backup_key`, `data` or `s3_link` hold public keys, blobs and signed
  URLs. Project explicit columns.

## Sources

Fetch these when something here is missing or behaves unexpectedly. The same
list lives in [docs-map.md](docs-map.md), where repo CI re-checks every URL
weekly; if one has moved, fix it there.

- API index (all endpoints, generated per version):
  <https://www.metabase.com/docs/latest/api-documentation>
- Card endpoints: <https://www.metabase.com/docs/latest/api/card>
- Dataset / query endpoints: <https://www.metabase.com/docs/latest/api/dataset>
- Dashboard endpoints: <https://www.metabase.com/docs/latest/api/dashboard>
- Search endpoint: <https://www.metabase.com/docs/latest/api/search>
- API keys & auth: <https://www.metabase.com/docs/latest/people-and-groups/api-keys>
- SQL parameters / `{{tag}}` / `[[optional]]`:
  <https://www.metabase.com/docs/latest/questions/native-editor/sql-parameters>
- Working with the API (guide):
  <https://www.metabase.com/learn/metabase-basics/administration/administration-and-operation/metabase-api>

Version-pin a doc URL by replacing `latest` with the instance's tag (e.g.
`/docs/v0.57/api/card`, verified 200); get the tag from
`GET /api/session/properties` → `version.tag`.
