# Snowflake and dbt semantics the checks depend on

Load before working checks 3, 5, 8, 9, or 11.

## Timezones (check 5)

- On a `TIMESTAMP_TZ` column use two-arg `CONVERT_TIMEZONE(<target_tz>, <col>)`.
  The three-arg form casts to NTZ first and silently discards the stored
  offset, which is wrong across DST boundaries.
- Raw conversions are routed through the repo macros `to_local_date()` /
  `safe_timezone()`. A raw `CONVERT_TIMEZONE` call in a model is itself a
  finding.
- `safe_timezone()` falls back to UTC when the location lookup misses: rows
  get dated in UTC, shifting them across a local-midnight boundary. When a
  join to the location/timezone source is touched, ask what happens to rows
  whose lookup misses.

## Incremental + MERGE (checks 3, 8, 11)

- Snowflake MERGE treats `NULL = NULL` as false: a nullable `unique_key`
  column never matches its old row, so every incremental run inserts a
  duplicate instead of updating.
- `incremental_predicates` bound the *target-side scan*. A window that
  excludes rows CDC will later update means those updates silently no-op.
  This interaction is not readable from the diff; ask, don't assert.
- MERGE cannot alter a deployed column's type. A type change on an
  incremental model errors (or worse, coerces) on the existing relation until
  a `--full-refresh`; flag type changes on incremental models even when the
  SQL is otherwise sound.

## CDC / DMS ordering (check 9)

- `_dms_ingestion_ts` is stamped per *file*, not per record: every record in
  one DMS batch shares it, so it cannot break ties within a batch. Dedup must
  rank by the source `updated_at` plus a record-level tiebreaker.
- DMS full-load rows carry source timestamps that can predate capture by
  years. Deriving any cutover from `min(_dms_ingestion_ts)`-style logic vs
  `min(updated_at)` gives different answers. (This is why splice/history
  assembly is a stated non-goal: it is not diff-visible.)

## Dev data artifacts (check 7 fallback)

- Dev raw consolidates two Mariana Tek instances whose tenant ids collide on
  six values (40, 41, 43-46), genuinely different tenants sharing an id.
  Duplicate, fan-out, and row-count checks run in dev false-positive on these
  unless scoped via `colliding_tenant_exclusion()` (macros/multi_tenant/).
  PRD has no collisions; prefer PRD for all data checks.

## NULL logic (check 8)

- `NOT IN (select <nullable col> ...)` returns zero rows if the subquery
  yields a single NULL. Rewrite as `NOT EXISTS` or filter the NULL; flag the
  pattern whenever the inner column is not provably non-null.
- Anti-joins (`left join ... where right.key is null`) silently keep rows
  when the join key itself is nullable on the left. NULL never matches, so
  those rows always look "absent".
