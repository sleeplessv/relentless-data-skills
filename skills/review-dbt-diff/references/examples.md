# Worked example and real before/after SQL

Every example below is from this repo's actual fix history. Load the section
for the check that fired; don't read the whole file pre-emptively.

## The finding format — worked example

JimXplor on PR #450, the bar every finding imitates (named invariant, dated
data check, proposed dbt test):

> This relies on an unenforced assumption: that partner_id maps 1:1 to
> location_id within a tenant. If any partner ever owns more than one
> location, this join will fan out and duplicate membership_instance rows
> downstream... Data check (PRD, checked 2026-08-03): Verified this is not
> currently causing duplication... Suggested fix: Either dedupe dim_location
> to one row per (tenant_id, partner_id)... and/or add a
> unique_combination_of_columns test on fct_all_memberships(tenant_id,
> membership_instance_id)

## Check 2 — join cardinality (SCD2 without temporal qualification)

```sql
-- BEFORE  (commit bd4c26a): SCD2 right side, every historical row matches
left join locations loc
    on  mi.fulfillment_partner_id = loc.partner_id
    and mi.tenant_id              = loc.tenant_id
-- AFTER: qualified to the row current as of the event
    and {{ scd2_as_of('loc', 'mi.membership_start_datetime') }}
```

## Check 3 — incremental coherence (filtered lookup CTE)

```sql
-- BEFORE  (commit 1604825): incremental filter on a lookup table starves
-- the join of unchanged-but-needed rows
class_sessions as (
    select * from {{ ref('stg_reservation_core__classsession') }}
    {% if is_incremental() %} where {{ incremental_predicate('updated_at') }} {% endif %}
),
-- AFTER: lookup tables are read whole
class_sessions as ( select * from {{ ref('stg_reservation_core__classsession') }} ),
```

## Check 4 — determinism (missing tiebreaker)

```sql
-- BEFORE  (commit abd2fe1): ties resolved arbitrarily per run
order by convert_timezone(...) desc
-- AFTER: partition-unique tiebreaker
order by convert_timezone(...) desc, order_line_id desc
```

## Check 1 / tenant scoping — the canonical fix

`fix: change deduplicate('id') to deduplicate('tenant_name, id') in 7 staging
sites (#75)`. A dedup or join key without the tenant column merges rows
across tenants. Grain in this repo is almost always tenant-qualified.

## Check 10 — literal filters

`'COMPLETE'` vs `'COMPLETED'` after an upstream `UPPER(TRIM())` silently
empties the filter. Verify with `select distinct <col>` on the source via
snowman before flagging or clearing.

## Check 12 — the cautionary tale

`fct_memberships_by_type`: six fixes in eight days; the first four shipped no
test, the fifth added a uniqueness assertion at `severity: warn`. A proposed
test in the finding is what breaks this cycle; name columns and severity.
