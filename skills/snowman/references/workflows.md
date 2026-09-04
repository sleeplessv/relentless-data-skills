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

Profile a sample first on large tables. Expand only when the question requires it.
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

## Stage a change

Follow [the staging policy](../SKILL.md#stage-requested-changes). Reuse the target
environment the user named. If unresolved in a multi-account project, ask first.

1. Inspect the target table or, for a new table, its schema. For data changes,
   preview or count affected rows with a SELECT in the target environment.
2. Stage the script with a purpose-specific `--name` and the required `--env`.
3. Return the path and manual command, plus any destructive-keyword warning.
4. Once the user reports execution and requests verification, check the effect
   with counts, DESCRIBE, or samples. Leave script cleanup to the user.
