# snowman workflows

Playbooks: pull the one matching the user's intent. Every query runs through
the wrapper: `python3 <skill-dir>/scripts/snowman.py "<SQL>"`. Start broad,
narrow fast, keep queries small.

## Exploration: discover what's there

1. `SHOW DATABASES` → `SHOW SCHEMAS IN DATABASE <db>` → `SHOW TABLES IN SCHEMA <db>.<schema>`
2. `DESCRIBE TABLE <db>.<schema>.<table>`: columns and types.
3. `SELECT * FROM <db>.<schema>.<table> SAMPLE (100 ROWS)`: eyeball real data.
4. `SELECT GET_DDL('TABLE', '<db>.<schema>.<table>')`: full definition.
5. Use `INFORMATION_SCHEMA` for metadata at scale (e.g. all columns in a
   schema) instead of describing tables one by one.

## Profiling: understand a table's shape

- **Row count:** `SELECT COUNT(*) FROM <t>`
- **Null %:** `SELECT COUNT(*) AS n, COUNT(<col>) AS non_null, 1 - COUNT(<col>)/COUNT(*) AS null_frac FROM <t>`
- **Distinct count / cardinality:** `SELECT COUNT(DISTINCT <col>) FROM <t>`
- **Categorical distribution:** `SELECT <col>, COUNT(*) FROM <t> GROUP BY <col> ORDER BY 2 DESC LIMIT 50`
- **Numeric/temporal range:** `SELECT MIN(<col>), MAX(<col>), AVG(<col>) FROM <t>`
- Profile a sample first on large tables; scale up only if needed.

## Hypothesis testing: validate a theory as a SELECT

Run the transformation logic as a read-only query *before* anyone builds it in
dbt or a pipeline.

- Express the candidate transform as a **CTE / SELECT** and inspect the output
  on a sample.
- **Source vs target counts:** confirm a join/filter doesn't drop or fan out
  rows unexpectedly. `SELECT COUNT(*)` before and after.
- **Join fan-out check:** `SELECT <key>, COUNT(*) FROM <joined> GROUP BY <key> HAVING COUNT(*) > 1`
- Confirm aggregations and window functions return what you expect on known
  rows before trusting them at scale.

## Investigation: chase a data-quality issue

- **Nulls where there shouldn't be:** `SELECT COUNT(*) FROM <t> WHERE <col> IS NULL`
- **Duplicates:** `SELECT <key>, COUNT(*) FROM <t> GROUP BY <key> HAVING COUNT(*) > 1 ORDER BY 2 DESC`
- **Referential gaps:** `SELECT COUNT(*) FROM <child> c LEFT JOIN <parent> p ON c.fk = p.pk WHERE p.pk IS NULL`
- **Freshness:** `SELECT MAX(<loaded_at>) AS latest FROM <t>`
- **Outliers / unexpected values:** distribution query (above) then drill into
  the surprising buckets with a filtered `SAMPLE`.
- Narrow with `WHERE` and `SAMPLE` before pulling detail rows; quote concrete
  example rows back to the user.

## Staging a change: write the script, never run it

When the user asks for DML/DDL ("add a column", "backfill X", "create a
table"), produce the script and stage it for their manual execution:

1. **Verify read-only first.** Confirm the target exists (`DESCRIBE`), and
   where the change is data-bearing, dry-run the logic as a `SELECT`, e.g.
   preview the rows an `UPDATE` would touch, or count them. In a
   multi-environment project, run these checks with the same `--env` the
   change targets.
2. **Stage it:**
   `python3 <skill-dir>/scripts/snowman.py --stage "<SQL>" --name <purpose-slug>`
   Multi-statement is fine; pick a `--name` that says what the script does.
   Multi-environment projects also require `--env <name>`; if the user didn't
   say which environment the change targets, ask first. Never infer.
3. **Hand it over.** Relay the staged file path and the `run with:` command
   from the wrapper's output. If the header carries a `WARNING:` line
   (destructive keywords), point it out explicitly.
4. **Verify after, on request.** Once the user says they've run it, offer
   read-only follow-ups to confirm the effect (counts, DESCRIBE, samples).
   Don't delete the staged file; cleanup is the user's.
