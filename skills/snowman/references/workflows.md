# snowman workflows

Use the playbook matching the request. Run SQL through
`python3 <skill-dir>/scripts/snowman.py "<SQL>"`. Start from the narrowest known
scope and inspect saved result artifacts when a preview truncates.

## Explore objects

1. Discover only missing names. Use `SHOW TERSE DATABASES`, then
   `SHOW TERSE SCHEMAS IN DATABASE <db> LIMIT 50`, or
   `SHOW TERSE TABLES IN SCHEMA <db>.<schema> LIMIT 50` as needed.
   Add `STARTS WITH '<prefix>'` when a prefix is known.
2. Project metadata in the same statement:
   `SHOW TABLES IN SCHEMA <db>.<schema> LIMIT 50 ->> SELECT "name","rows","bytes" FROM $1`.
   SHOW and DESCRIBE columns are lowercase and require double quotes.
   Use `$1` in `FROM`. TERSE omits `rows` and `bytes`, so size queries need
   plain `SHOW`. For a database-wide size comparison:
   `SHOW TABLES IN DATABASE <db> ->> SELECT "schema_name","name","rows","bytes" FROM $1 ORDER BY "bytes" DESC`.
3. Inspect a known table:
   `DESCRIBE TABLE <db>.<schema>.<table> ->> SELECT "name","type","null?" FROM $1`.
4. Sample the columns needed:
   `SELECT <col1>, <col2> FROM <db>.<schema>.<table> SAMPLE (20 ROWS)`.
5. For the definition, use `SELECT GET_DDL('TABLE', '<db>.<schema>.<table>')`.
   If truncated, read the full value from the reported JSON artifact.

Use `INFORMATION_SCHEMA` for metadata across many objects instead of describing
tables one by one. Check query cost before expanding a discovery query.

## Profile a table

For exact metrics, aggregate over the requested population. For exploration or
estimates, sample and label the reported metrics as estimates.
Use known row counts and bytes to assess cost. If size is unknown and changes
the query plan, project `rows` and `bytes` from `SHOW TABLES` for the target.
Choose filters and sampling from that evidence and the user's cost constraints.
If those constraints prevent an exact answer, explain the limit before sampling.
These examples use `<t>` for the selected table or sample:

- Row count: `SELECT COUNT(*) AS n FROM <t>`.
- Null fraction: `SELECT COUNT(*) AS n, COUNT(<col>) AS non_null, 1 - COUNT(<col>)/NULLIF(COUNT(*), 0) AS null_frac FROM <t>`.
  An empty table returns NULL for the fraction.
- Distinct count: `SELECT COUNT(DISTINCT <col>) FROM <t>`.
- Distribution: `SELECT <col>, COUNT(*) FROM <t> GROUP BY <col> ORDER BY 2 DESC LIMIT 50`.
- Numeric or temporal range: `SELECT MIN(<col>), MAX(<col>) FROM <t>`.
- Numeric average: `SELECT AVG(<numeric_col>) FROM <t>`.

## Test a transformation hypothesis

Express the transformation as a CTE or SELECT and inspect a sample before
implementing it in dbt or a pipeline.

- Compare source and result counts to detect dropped rows or join fan-out.
- Check repeated keys:
  `SELECT <key>, COUNT(*) FROM <joined> GROUP BY <key> HAVING COUNT(*) > 1 LIMIT 50`.
- Check aggregates and window functions against known rows before scaling up.

## Investigate data quality

Start with a count or distribution, then fetch filtered examples:

- Unexpected NULLs: `SELECT COUNT(*) FROM <t> WHERE <col> IS NULL`.
- Duplicates: `SELECT <key>, COUNT(*) FROM <t> GROUP BY <key> HAVING COUNT(*) > 1 ORDER BY 2 DESC LIMIT 50`.
- Referential gaps: `SELECT COUNT(*) FROM <child> c LEFT JOIN <parent> p ON c.fk = p.pk WHERE p.pk IS NULL`.
- Freshness: `SELECT MAX(<loaded_at>) AS latest FROM <t>`.
- Outliers: inspect the distribution, then sample surprising buckets with a filter.

Return the finding with the counts or example rows that support it.

## Investigate query history

Use this for slow queries, warehouse load, or what ran at a given time.

- `<db>.INFORMATION_SCHEMA.QUERY_HISTORY`, `QUERY_HISTORY_BY_USER`,
  `_BY_WAREHOUSE`, and `_BY_SESSION` are table functions. Call them as
  `SELECT ... FROM TABLE(<db>.INFORMATION_SCHEMA.QUERY_HISTORY(END_TIME_RANGE_START => ..., RESULT_LIMIT => 10000))`.
  They return at most 100 rows unless `RESULT_LIMIT` is set, up to 10,000.
- These functions cover only the last 7 days. An older range fails with
  `Cannot retrieve data from more than 7 days ago`.
- They omit spill, pruning, and DML row columns such as
  `BYTES_SPILLED_TO_LOCAL_STORAGE`, `PARTITIONS_SCANNED`, and `ROWS_UPDATED`.
  Query `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` for those or for anything
  older than 7 days. Its rows can lag up to 45 minutes behind.
- For one query's plan, use
  `SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS('<query_id>'))` and project the
  `OPERATOR_STATISTICS` fields needed.
- Before writing a query against an unfamiliar view, check its columns:
  `DESCRIBE VIEW SNOWFLAKE.ACCOUNT_USAGE.<view> ->> SELECT "name" FROM $1`.

## Stage a change

Follow [the staging policy](../SKILL.md#stage-requested-changes). Reuse the target
environment the user named. If unresolved in a multi-account project, ask first.

1. Inspect the target table or, for a new table, its schema. For data changes,
   preview or count affected rows with a SELECT in the target environment.
   For new roles, users, or schemas, take names and the grant topology from
   existing peers in the target account (`SHOW ROLES`, `SHOW GRANTS TO ROLE`,
   `SHOW GRANTS OF ROLE`) and cite the precedent in the script. Record any
   convention the user confirms in the context body.
2. Stage the script with a purpose-specific `--name` and the required `--env`.
3. Return the path and manual command, plus any destructive-keyword warning.
4. Once the user reports execution and requests verification, check the effect
   with counts, DESCRIBE, or samples. Leave script cleanup to the user.
