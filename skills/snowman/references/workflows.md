# snowman workflows

Playbooks: pull the one matching the user's intent. Every query runs through
the wrapper: `python3 <skill-dir>/scripts/snowman.py "<SQL>"`. Start broad,
narrow fast, keep queries small.

## Exploration: discover what's there

1. Run `SHOW TERSE DATABASES`, then `SHOW TERSE SCHEMAS IN DATABASE <db> LIMIT 50`,
   then `SHOW TERSE TABLES IN SCHEMA <db>.<schema> LIMIT 50` (add
   `STARTS WITH '<prefix>'` to narrow). Project the columns you need in the
   same statement with the pipe operator:
   `SHOW TABLES IN SCHEMA <db>.<schema> LIMIT 50 ->> SELECT "name","rows","bytes" FROM $1`.
   SHOW and DESCRIBE column names are lowercase and must be double-quoted.
   `$1` is valid only in `FROM`. `IN DATABASE <db>` works for both the TERSE
   and the projected forms when you want every schema at once. `SHOW TERSE`
   omits `rows` and `bytes`, so for table sizes across a database run
   `SHOW TABLES IN DATABASE <db> ->> SELECT "schema_name","name","rows","bytes" FROM $1 ORDER BY "bytes" DESC`
   with `--max-rows N`.
2. `DESCRIBE TABLE <db>.<schema>.<table> ->> SELECT "name","type","null?" FROM $1`:
   columns and types without the ten mostly-null DESCRIBE columns.
3. `SELECT <col1>, <col2>, ... FROM <db>.<schema>.<table> SAMPLE (20 ROWS)`:
   eyeball real data with a column list, or `SAMPLE (20 ROWS)` on a narrow
   table. The wrapper shows 50 rows and saves the rest to a file.
   `--max-rows N` changes the cap.
4. `SELECT GET_DDL('TABLE', '<db>.<schema>.<table>')`: full definition.
5. Use `INFORMATION_SCHEMA` for metadata at scale (for example all columns in
   a schema) instead of describing tables one by one.

## Profiling: understand a table's shape

- **Row count:** `SELECT COUNT(*) FROM <t>`
- **Null fraction:** `SELECT COUNT(*) AS n, COUNT(<col>) AS non_null, 1 - COUNT(<col>)/COUNT(*) AS null_frac FROM <t>`
- **Distinct count:** `SELECT COUNT(DISTINCT <col>) FROM <t>`
- **Categorical distribution:** `SELECT <col>, COUNT(*) FROM <t> GROUP BY <col> ORDER BY 2 DESC LIMIT 50`
- **Numeric or temporal range:** `SELECT MIN(<col>), MAX(<col>), AVG(<col>) FROM <t>`
- Profile a sample first on large tables. Scale up only if needed.

## Hypothesis testing: validate a theory as a SELECT

Run the transformation logic as a read-only query before anyone builds it in
dbt or a pipeline.

- Express the candidate transform as a CTE or SELECT and inspect the output
  on a sample.
- **Source and target counts:** confirm a join or filter does not drop or fan
  out rows unexpectedly. Run `SELECT COUNT(*)` before and after.
- **Join fan-out check:** `SELECT <key>, COUNT(*) FROM <joined> GROUP BY <key> HAVING COUNT(*) > 1`
- Confirm aggregations and window functions return what you expect on known
  rows before trusting them at scale.

## Investigation: chase a data-quality issue

- **Nulls where there should be none:** `SELECT COUNT(*) FROM <t> WHERE <col> IS NULL`
- **Duplicates:** `SELECT <key>, COUNT(*) FROM <t> GROUP BY <key> HAVING COUNT(*) > 1 ORDER BY 2 DESC`
- **Referential gaps:** `SELECT COUNT(*) FROM <child> c LEFT JOIN <parent> p ON c.fk = p.pk WHERE p.pk IS NULL`
- **Freshness:** `SELECT MAX(<loaded_at>) AS latest FROM <t>`
- **Outliers and unexpected values:** run the distribution query (above),
  then drill into the surprising buckets with a filtered `SAMPLE`.
- Narrow with `WHERE` and `SAMPLE` before pulling detail rows. Quote concrete
  example rows back to the user.

## Staging a change: write the script, never run it

When the user asks for DML or DDL ("add a column", "backfill X", "create a
table"), produce the script and stage it for their manual execution:

1. **Verify read-only first.** Confirm the target exists (`DESCRIBE`). Where
   the change is data-bearing, dry-run the logic as a `SELECT`, for example
   by previewing the rows an `UPDATE` would touch, or counting them. In a
   multi-environment project, run these checks with the same `--env` the
   change targets.
2. **Stage it:**
   `python3 <skill-dir>/scripts/snowman.py --stage "<SQL>" --name <purpose-slug>`
   Several statements are fine. Pick a `--name` that says what the script does.
   Multi-environment projects also require `--env <name>`. If the user did not
   say which environment the change targets, ask first. Never infer.
3. **Hand it over.** Relay the staged file path and the `run with:` command
   from the wrapper's output. If the header carries a `WARNING:` line
   (destructive keywords), point it out.
4. **Verify after, on request.** Once the user says they have run it, offer
   read-only follow-ups to confirm the effect (counts, DESCRIBE, samples).
   Don't delete the staged file. Cleanup is the user's.
