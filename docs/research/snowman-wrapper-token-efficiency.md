# snowman wrapper: token efficiency of what the agent reads back

Research date: 2026-09-03. Installed Snowflake CLI: 3.25.0 (Homebrew). Local source read as a primary source at
`/opt/homebrew/Cellar/snowflake-cli/3.25.0/libexec/lib/python3.13/site-packages/snowflake/cli/`; the same files exist on GitHub at tag `v3.25.0`
(https://github.com/snowflakedb/snowflake-cli/tree/v3.25.0/src/snowflake/cli). Measurements marked "measured" were taken in this session with
`snow sql` against a real account; they are byte counts of stdout, not token counts (no first-party tokenizer was run).

## Summary

1. `--format JSON` (what `snowman.py` uses today) is the most verbose stdout the CLI can emit for a result set: a pretty-printed array of objects with `indent=4`, every key repeated per row, `null` cells included. Measured: `DESCRIBE VIEW` on an 85-column view is 32,333 bytes as JSON, 17,852 as TABLE, 4,836 as CSV (6.7x smaller than JSON). `SHOW VIEWS ... LIMIT 5` is 2,027 bytes JSON vs 612 CSV. Switching the wrapper to `--format CSV` is the single biggest win with zero SQL changes.
2. SQL-side pruning beats any client-side formatting for metadata: `SHOW TERSE` cuts SHOW output to 5 columns; the pipe operator `->> SELECT "name" FROM $1` projects any SHOW/DESCRIBE to only the needed columns in a single statement (so it passes snowman's single-statement guardrail, unlike `RESULT_SCAN(LAST_QUERY_ID())`, which needs two statements in one session). Measured: the 85-column DESCRIBE reduced to one `LISTAGG` row is 3,011 bytes (10.7x smaller than the JSON form).
3. The CLI's error path is already compact (one Rich "Error" panel on stderr, no traceback unless `--debug`), but the panel's box-drawing characters and 80-column wrapping add pure noise. Stripping the box and unwrapping is a small, cheap win.
4. Claude Code hard limits bound the damage but do not save tokens: a Bash result over roughly 30,000 characters is written to a file and only a preview reaches the model; a failing command gets a 10,000-character head-and-tail excerpt. Anthropic's own guidance is to paginate, filter, truncate, and offer a concise/detailed switch inside the tool rather than rely on those limits.
5. Prior art is thin: the deprecated Snowflake-Labs MCP server returns `cur.fetchall()` with no cap; the Snowflake-managed MCP server truncates SQL tool responses at 250 KB; dbt-mcp's `show` tool defaults to `--limit 5` and `--output json`. None of them caps columns or truncates cells.

## 1. Snowflake CLI output formats (3.25.0)

Formats. `OutputFormat` has exactly four members: `TABLE`, `JSON`, `JSON_EXT`, `CSV`
(`api/output/formats.py`, https://github.com/snowflakedb/snowflake-cli/blob/v3.25.0/src/snowflake/cli/api/output/formats.py). The docs list the same set:
`--format [TABLE|JSON|JSON_EXT|CSV]`, "Specifies the output format. Default: TABLE."
(https://docs.snowflake.com/en/developer-guide/snowflake-cli/command-reference/sql-commands/sql). There is no NDJSON, compact-JSON, columnar, or TSV option.

How JSON renders. A query result is a `CollectionResult` streamed as a JSON array with `indent=4` (`_app/printing.py`,
https://github.com/snowflakedb/snowflake-cli/blob/v3.25.0/src/snowflake/cli/_app/printing.py):

```python
def _print_json_result_streaming(result: CommandResult):
    if isinstance(result, CollectionResult):
        _stream_collection_as_json(result, indent=4)
```

`_print_json_item_with_array_indentation` has a compact branch (`separators=(",", ":")`) that is only reached when `indent` is 0, and no caller passes 0, so compact output is unreachable from the CLI. Each row is a dict built by `zip(self.column_names, row)` (`api/output/types.py`, `QueryResult._prepare_payload`), so keys repeat on every row. `null` cells are emitted as `null`. Dates go through `isoformat()`, Decimals become strings.
Measured `select 1 as a, 'x' as b, current_timestamp() as ts, object_construct('k',1) as o`:

```
[
    {
        "A": 1,
        "B": "x",
        "TS": "2026-09-03T10:28:09.893000-07:00",
        "O": "{\n  \"k\": 1\n}"
    }
]
```

What JSON_EXT adds. Only one thing: `RespectingColumnTypesRowMapper.map_row` runs `json.loads` on VARIANT/OBJECT/ARRAY columns (type codes 5, 9, 10) when the format is `JSON_EXT`, so nested values are real JSON instead of an escaped string (`api/output/types.py`). Everything else is identical, including `indent=4`. Docs: JSON "Returns JSON as quoted strings", JSON_EXT "Returns JSON as JSON objects" (sql command page above). For VARIANT-heavy results JSON_EXT removes the `\"` escaping overhead; for scalar results it changes nothing.

How CSV renders. `csv.DictWriter` with header row, `lineterminator="\n"`, `None` written as empty string, dates as ISO (`_stream_collection_as_csv`, `_write_csv_row`). No quoting unless a cell needs it. This is the only format with no per-row key repetition and no indentation.

How TABLE renders. Rich ASCII box table. When stdout is not a terminal (always the case under a wrapper) the render width is forced to 1,000,000 so every column takes its natural width: "Use an effectively unlimited width for non-terminal destinations" (`_NON_TERMINAL_RENDER_WIDTH`, printing.py). Cells are padded with spaces to column width, so TABLE is wide and padding-heavy. TABLE also echoes the SQL text before the result (measured: first line of stdout is the statement), because `VerboseCursor.execute` calls `cli_console.message(command)` (`api/sql_execution.py`); that echo is muted for JSON/CSV by `_should_force_mute_intermediate_output` (`api/cli_global_context.py`).

Measured sizes on the same account (bytes of stdout):

| statement | TABLE | JSON | CSV |
|---|---|---|---|
| `SHOW TERSE VIEWS IN SCHEMA snowflake.account_usage LIMIT 5` | 986 | 1,057 | 456 |
| `SHOW VIEWS IN SCHEMA snowflake.account_usage LIMIT 5` | 1,835 | 2,027 | 612 |
| `DESCRIBE VIEW snowflake.account_usage.query_history` (85 rows, 13 cols) | 17,852 | 32,333 | 4,836 |

Multiple statements. `snow sql` returns `MultipleResults((QueryResult(c) for c in cursors))` when more than one statement is executed (`_plugins/sql/commands.py`). In JSON this goes through `_stream_json`, which nests each result set as an inner array inside an outer array and, because of its custom indenting writer, emits oddly spaced keys (measured: `"A"  :   1`). In CSV each result set is printed as its own header+rows block separated by a blank line. Docs: "The snow sql command can also execute multiple statements; in that case, multiple result sets are returned" (https://docs.snowflake.com/en/developer-guide/snowflake-cli/sql/execute-sql). Not relevant to snowman today because the wrapper enforces one statement.

Query id and row counts. For a successful query in JSON or CSV mode nothing but the result set is printed: no query id, no "N rows" line. The only query id the CLI prints is for `EXECUTE ... ASYNC` statements (`scheduled query ID`, `_plugins/sql/manager.py`). On error the query id appears inside the connector message (see section 4). Statements with no result rows print `[]` (JSON) or nothing at all (CSV); TABLE prints "No data".

Global flags (`api/commands/flags.py`, https://github.com/snowflakedb/snowflake-cli/blob/v3.25.0/src/snowflake/cli/api/commands/flags.py):

- `--silent`: "Turns off intermediate output to console." It gates `cli_console._print` (`api/console/abc.py`). Since structured formats already force-mute intermediate output, `--silent` changes nothing for JSON/CSV. It does not suppress the error panel (measured: identical panel on stderr with `--silent`).
- `--verbose` / `-v`: "Displays log entries for log levels info and higher." Adds INFO log lines from `snowflake.cli` and the connector to the console handler (`_app/loggers.py`, `create_loggers`). Default console handler level is ERROR, so without `-v` no log lines reach stderr.
- `--debug`: "Displays log entries for log levels debug and higher" and sets `enable_tracebacks`, which makes the top-level handler re-raise instead of printing a one-line message (`_app/main_typer.py`, `_handle_exception`).
- `--enhanced-exit-codes` (env `SNOWFLAKE_ENHANCED_EXIT_CODES`): exit 5 for SQL errors, 2 for argument errors (measured: exit 5 on a compilation error). Useful for the wrapper to distinguish SQL failures from CLI failures without parsing stderr.

## 2. SQL-side ways to shrink the payload

- `SHOW TERSE ...` returns only `created_on`, `name`, `kind`, `database_name`, `schema_name` (SHOW TABLES: https://docs.snowflake.com/en/sql-reference/sql/show-tables; SHOW OBJECTS: https://docs.snowflake.com/en/sql-reference/sql/show-objects). Non-terse SHOW TABLES has 23 columns. Measured: TERSE cut JSON output by 48% and CSV by 25% on SHOW VIEWS.
- `LIMIT <rows> [FROM '<name_string>']` caps rows and paginates lexicographically; "The value for LIMIT rows can't exceed 10000. If LIMIT rows is omitted, the command results in an error if the result set is larger than ten thousand rows." (show-tables page). `STARTS WITH '<name_string>'` and `LIKE '<pattern>'` filter server-side. SHOW needs no running warehouse (same page).
- Pipe operator `->>`: "SHOW WAREHOUSES ->> SELECT "name", "state", "type", "size" FROM $1;" produces the same as `RESULT_SCAN(LAST_QUERY_ID(-1))` "but with simpler syntax"; `$n` is only valid in a FROM clause; column names from SHOW/DESCRIBE are lowercase and must be double-quoted (https://docs.snowflake.com/en/sql-reference/operators-flow). This is one statement, so it passes snowman's single-statement rule. Measured: `SHOW TERSE VIEWS ... LIMIT 5 ->> SELECT "name" FROM $1` in CSV is 6 lines, 100 bytes.
- `RESULT_SCAN(LAST_QUERY_ID())`: documented pattern `SELECT "property", "value" FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())) WHERE ...` (https://docs.snowflake.com/en/sql-reference/functions/result_scan). `LAST_QUERY_ID` is session-scoped (https://docs.snowflake.com/en/sql-reference/functions/last_query_id) and each `snow sql` call is a new session, so this needs two statements in one call, which snowman refuses. `RESULT_SCAN('<query_id>')` works for 24 hours for the same user, but the CLI does not print the query id of a successful statement (section 1), so the wrapper would have to capture it another way. Prefer `->>`.
- DESCRIBE: `DESCRIBE TABLE <name> [TYPE = COLUMNS | STAGE]` returns 13 columns (`name, type, kind, null?, default, primary key, unique key, check, expression, comment, policy name, privacy domain, schema_evolution_record`), most of which are null for ordinary columns; the docs say to use `->>` or RESULT_SCAN to post-process (https://docs.snowflake.com/en/sql-reference/sql/desc-table). `SHOW COLUMNS` is an alternative that spans many tables at once but is also capped at ten thousand records (https://docs.snowflake.com/en/sql-reference/sql/show-columns).
- INFORMATION_SCHEMA: `TABLES` has 29 columns, `COLUMNS` has 53, but you choose columns with a normal SELECT so the payload is whatever you project (https://docs.snowflake.com/en/sql-reference/info-schema/tables, https://docs.snowflake.com/en/sql-reference/info-schema/columns). Costs: "Warehouse must be running and currently in use to query the views" and insufficiently selective queries fail with "Information schema query returned too much data" (https://docs.snowflake.com/en/sql-reference/info-schema). SHOW needs no warehouse; INFORMATION_SCHEMA gives free projection. Both are fine; `SHOW ... ->>` gives projection without a warehouse.
- One-row compaction: `OBJECT_CONSTRUCT(*)` builds an object per row and "If the key or value is NULL ... the key-value pair is omitted" (https://docs.snowflake.com/en/sql-reference/functions/object_construct), so nulls vanish. `ARRAY_AGG(expr) [WITHIN GROUP (ORDER BY ...)]` pivots rows into one array, max 128 MB per call (https://docs.snowflake.com/en/sql-reference/functions/array_agg). With `--format JSON_EXT` the array comes back as real JSON (measured: `->> SELECT ARRAY_AGG("name") FROM $1` returned one row holding a 5-element array). `LISTAGG` gives a single string (measured: 85 column names plus types in 3,011 bytes).

## 3. Token-cost evidence and Anthropic guidance

Format comparisons. No first-party (Anthropic or Snowflake) benchmark of JSON vs CSV vs Markdown was found. The best documented third-party source is the TOON project's benchmark page, which is secondary and self-interested (it promotes TOON) but states its method: GPT-5 `o200k_base` tokenizer via `gpt-tokenizer`, flat tabular datasets (https://toonformat.dev/guide/benchmarks). Its numbers for uniform employee records (100 rows): CSV 47,153; JSON compact 79,057; JSON pretty 127,061; YAML 100,054. Ratio JSON-pretty to CSV is 2.7x, which is consistent in direction with the 6.7x byte ratio measured above for a null-heavy DESCRIBE (nulls and repeated keys make pretty JSON worse). Blog posts found by search (Medium, personal blogs) reach the same ordering but were not used as evidence. Claude's tokenizer differs from o200k, so treat these as directional only.

Anthropic guidance (first-party):

- "Writing tools for agents": "We restrict tool responses to 25,000 tokens by default" (Claude Code); implement "pagination, range selection, filtering, and/or truncation with sensible default parameter values"; expose a `response_format` enum so the agent can pick "concise" or "detailed" (their Slack example: 206 vs 72 tokens); prefer high-signal fields over "low-level technical identifiers"; when truncating, "clearly communicate specific and actionable improvements" (https://www.anthropic.com/engineering/writing-tools-for-agents).
- "Effective context engineering for AI agents": "Context ... must be treated as a finite resource with diminishing marginal returns"; tools should return lean outputs; keep "lightweight identifiers (file paths, stored queries, web links, etc.)" and load data just in time; clearing old tool results is "one of the safest lightest touch forms of compaction" (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
- Context editing API: strategy `clear_tool_uses_20250919`, defaults trigger 100,000 input tokens, keep 3 tool uses; cleared results are replaced with placeholder text (https://platform.claude.com/docs/en/docs/build-with-claude/context-editing). This helps long sessions but does nothing for the first read of a large result.

Claude Code behaviour on large Bash output (first-party, https://code.claude.com/docs/en/tools-reference, "Output limits"): output streams to a working file; a valid result arrives "Inline up to roughly 30,000 characters; past that, the path of a file saved to the session directory ... plus a short preview from the start"; a failure arrives "Inline up to roughly 10,000 characters; past that, a head-and-tail excerpt". Any non-zero exit other than the listed benign cases counts as a failure, so a `snow` error over 10k characters gets head-and-tail cut. `BASH_MAX_OUTPUT_LENGTH` (default 30,000, max 150,000) widens the read-back window but "does not raise the inline ceilings" (https://code.claude.com/docs/en/env-vars). Observed in this session: a 56.7 KB tool result was replaced by "Output too large (56.7KB). Full output saved to: .../tool-results/toolu_....txt Preview (first 2KB)". For MCP tools the limit is 25,000 tokens with a warning at 10,000, adjustable via `MAX_MCP_OUTPUT_TOKENS` (https://code.claude.com/docs/en/mcp). Implication: anything the wrapper emits under ~30k characters lands in context in full, so the wrapper, not the harness, has to do the shrinking.

## 4. Error output and verbosity

Path of a SQL error (all in local source): the connector raises `ProgrammingError` (a `DatabaseError`); `SnowTyper._cli_base_exception_migration_dispatcher` converts any `DatabaseError` to `CliSqlError(exception.msg)` (`api/commands/snow_typer.py`); `CliSqlError` is a `click.ClickException` subclass with `exit_code = 5` (`api/exceptions.py`); Typer 0.17.3 (bundled) renders ClickExceptions through `rich_format_error`, which prints to a stderr console inside a Rich panel titled "Error". Measured stderr:

```
╭─ Error ──────────────────────────────────────────────────────────────────────╮
│ 002003 (42S02): 01c6d3f7-020b-2af1-0004-fc4708a01dca: SQL compilation error: │
│ Object 'NONEXISTENT_TABLE_XYZ' does not exist or not authorized.             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

So the message is already one connector line (error code, SQLSTATE, query id, text); the panel wraps it at 80 columns and adds 4 box characters per line plus two border lines. No traceback is printed. Non-Click exceptions go through `_handle_exception`, which prints "An unexpected exception occurred. Use --debug option to see the traceback. Exception message: ..." and exits 1 (`_app/main_typer.py`); with `--debug` the full traceback is re-raised. Nothing is written to stdout on error (measured: stdout empty).

Ways to make it more concise: none inside the CLI. `--silent` does not affect the panel (measured). The `[cli.logs]` config (`save_logs`, `path`, `level`, default `info`) only governs the log file (`api/config.py`, `_get_default_logs_config`); no `SNOWFLAKE_CLI_*` variable controls console error rendering (the only ones in source are `SNOWFLAKE_CLI_CONFIG_V2_ENABLED`, `..._ENCODING_*`, `..._FEATURES_*`, `..._SQL_*`, `..._STAGE_UPLOAD_WORKERS`, `..._PRIVILEGE_CHECK`). Options the wrapper has: strip `╭ ╮ ╰ ╯ │ ─` and re-join wrapped lines itself; or set `COLUMNS` very wide in the subprocess env so Rich does not wrap (not verified with `snow`; Rich honours `COLUMNS` in general). Use `--enhanced-exit-codes` to classify failures by exit code instead of regex.

## 5. Prior art in agent-facing Snowflake wrappers

- Snowflake-Labs/mcp (now marked deprecated in its README in favour of the managed server): `run_snowflake_query` executes with a dict cursor and `return cur.fetchall()`, no row cap, no column cap, no cell truncation; FastMCP serialises the list of dicts (https://github.com/Snowflake-Labs/mcp/blob/main/mcp_server_snowflake/query_manager/tools.py). Statement types are allow-listed via sqlglot in config (README: https://github.com/Snowflake-Labs/mcp).
- Snowflake-managed MCP server (Cortex Agents): "Tool responses are subject to size limits to prevent LLM context window saturation: Generic tools: Responses are truncated at 250 KB. SQL execution tool: Responses are truncated at 250 KB." Results are JSON in a `content` array; Cortex Search takes a `limit` parameter; agent responses "can result in large response payloads (200 KB or more)" (https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp). A 250 KB cap is far above Claude Code's 25k-token MCP limit, so it is a safety net, not a token budget.
- dbt-mcp: the `show` tool runs `dbt show` with `--limit` defaulting to 5 (`limit: int = Field(default=5, ...)`) and `--output json`; the prompt tells the model "Do not add a limit to this query. Use the limit argument instead"; unrelated commands get `--quiet` "to reduce context window usage" (https://github.com/dbt-labs/dbt-mcp/blob/main/src/dbt_mcp/dbt_cli/tools.py, https://github.com/dbt-labs/dbt-mcp/blob/main/src/dbt_mcp/prompts/dbt_cli/args/sql_query.md). Semantic Layer results are formatted as "array of objects (records), 2-space indentation, ISO date strings" (`DEFAULT_RESULT_FORMATTER`, https://github.com/dbt-labs/dbt-mcp/blob/main/src/dbt_mcp/semantic_layer/client.py) and `dimension_values` truncates client-side to `limit` (default 100) with a `truncated` flag. The platform-hosted `execute_sql`/`text_to_sql` tools are proxied to a remote MCP (`src/dbt_mcp/proxy/tools.py`); their shaping is not visible in the repo and could not be verified.

Not verified: whether the Snowflake-managed server's 250 KB truncation cuts on a row boundary; the internal format of Cortex Agent SQL tool results beyond "JSON".

## Recommendations for snowman.py (ranked by expected saving)

1. Run `snow sql` with `--format CSV` instead of `JSON`. Evidence: printing.py (`indent=4`, repeated keys, unreachable compact branch); measured 6.7x on DESCRIBE, 3.3x on SHOW, 2.3x on TERSE SHOW; TOON benchmark direction. Keep JSON_EXT available behind a flag (for example `--json`) for VARIANT-heavy results where CSV would embed escaped JSON. CSV loses the `null` vs empty-string distinction (`_write_csv_row` writes `""` for None); document that in `references/guardrails.md` or emit a one-line note only when the result has nulls, which the wrapper can detect by parsing the CSV it forwards.
2. Cap and label rows in the wrapper. Parse the CSV, forward at most N rows (dbt-mcp uses 5; 50 is a reasonable default for exploration), and append one line such as `# 50 of 1,203 rows shown; add LIMIT or a WHERE filter` in the style Anthropic recommends ("specific and actionable improvements"). Keep the full output in a file under `.snowman/results/` and print its path, mirroring Claude Code's own over-30k behaviour but at a much lower threshold so the inline copy stays small. Do not rely on `BASH_MAX_OUTPUT_LENGTH`: it only kicks in at ~30,000 characters and a failure gets cut to 10,000.
3. Truncate wide cells. Add a per-cell cap (for example 200 characters, with `...(+N chars)`), because `QUERY_TEXT`-style VARCHAR(16777216) columns dominate size and are rarely needed in full; the wrapper is the only layer that can do this without changing the SQL. Evidence: writing-tools-for-agents "truncation with sensible default parameter values".
4. Teach the skill to prune server-side: prefer `SHOW TERSE`, always add `LIMIT`, use `STARTS WITH`/`LIKE`, and use `->> SELECT "col1","col2" FROM $1` to project SHOW/DESCRIBE columns in one statement. Add `->>` examples to `references/workflows.md`. Evidence: show-tables, operators-flow, desc-table docs; measured 10.7x on DESCRIBE via `LISTAGG`. Verify that `enforce_read_only` accepts `->>` (it did in this session's manual runs; the wrapper's regex was not exercised).
5. Add a `--concise` / `--detailed` style switch (writing-tools-for-agents `response_format`): concise = CSV, row cap, cell cap; detailed = JSON_EXT, no caps, still row-limited by a hard ceiling. Default concise.
6. Clean error output: pass `--enhanced-exit-codes` and, when exit is 5, strip the Rich box characters from stderr and re-join wrapped lines into a single `ERROR <code> (<sqlstate>) <query_id>: <message>` line. Evidence: snow_typer.py and Typer `rich_format_error`; measured panel. Saves ~120 characters per error and removes non-ASCII box glyphs that tokenize poorly.
7. Do not add `--silent` or `--verbose`; they change nothing for structured formats (silent) or add log noise (verbose). Do not pass `--debug` except when the user asks for a traceback.
8. Optional: for "profile this table" flows, teach `SELECT OBJECT_CONSTRUCT(*)` or `ARRAY_AGG` over a small aggregate to return one row instead of many; null keys drop out automatically (object_construct docs). Gains depend on null density, so rank last.

## Appendix: measured token counts on a real dev account

Taken in the same session as the research above, against the `xplor-uswe-aws-corp-dev` connection, with the `o200k_base` tokenizer via `tiktoken` (a proxy; Claude's tokenizer differs, so read the ratios, not the absolutes). "current" is what `snowman.py` forwards today (`--format JSON`, indent 4). The other renderings were produced from the same parsed rows. Script: `measure.py` in the session scratchpad, not committed.

| query | rows | cols | current JSON | compact JSON | columns+rows JSON | CSV | TSV | markdown | CSV vs current |
|---|---|---|---|---|---|---|---|---|---|
| SHOW DATABASES | 23 | 14 | 3,154 | 2,167 | 1,253 | 1,066 | 1,079 | 1,478 | 3.0x |
| SHOW SCHEMAS IN DATABASE | 7 | 15 | 1,066 | 752 | 479 | 405 | 399 | 557 | 2.6x |
| SHOW TABLES IN SCHEMA | 10 | 27 | 2,704 | 1,875 | 1,079 | 925 | 923 | 1,197 | 2.9x |
| SHOW TERSE TABLES IN SCHEMA | 10 | 5 | 779 | 590 | 487 | 452 | 450 | 492 | 1.7x |
| SHOW WAREHOUSES | 16 | 38 | 5,987 | 4,163 | 2,368 | 2,158 | 2,131 | 2,864 | 2.8x |
| DESCRIBE TABLE | 19 | 13 | 1,888 | 1,214 | 567 | 357 | 326 | 682 | 5.3x |
| SELECT * ... SAMPLE (100 ROWS) | 100 | 19 | 27,942 | 21,856 | 12,258 | 11,984 | 11,986 | 13,137 | 2.3x |
| SELECT COUNT(*) | 1 | 1 | 14 | 7 | 13 | 5 | 4 | 11 | 2.8x |

Observations:

- `snow --format CSV` output tokenized identically to the CSV rendering above (it is the same `csv` module), so the CSV column is what recommendation 1 delivers with no other change.
- CSV and TSV are within 1% of each other; markdown tables cost 10 to 40% more than CSV; compact JSON still costs roughly 1.8x CSV because keys repeat per row.
- The 100-row sample is the case that matters: 28k tokens today, over Anthropic's 25k-token tool-result guideline, and close to the Claude Code 30k-character file-spill threshold. A 64-character hashed email column alone was 3,670 of the 10,055 cell tokens; a 40-character cell cap plus rounding floats to 4 decimals brought the TSV from 11,986 to 9,874 tokens.
- Column projection dominates for SHOW output. Keeping only name/owner/comment (databases), name/kind/rows/bytes/comment (tables) or name/state/size/auto_suspend/owner/comment (warehouses) in TSV gives 297, 179 and 367 tokens against 3,154, 2,704 and 5,987 today: a 10x to 16x reduction, which is why teaching `SHOW TERSE` and `->> SELECT ... FROM $1` matters more than the client-side format for metadata.
- Errors: the Rich panel for a missing-table error is 104 tokens; the same message with box glyphs stripped and lines re-joined is 66 tokens.
- The wrapper's `enforce_read_only` accepts `SHOW ... ->> SELECT "name" FROM $1` and `DESCRIBE ... ->> SELECT ... FROM $1` (checked by calling the function directly), so recommendation 4 needs no guardrail change.
- Skill instruction cost, for completeness: `SKILL.md` 1,776 tokens, `references/install.md` 2,035, `references/guardrails.md` 1,436, `references/workflows.md` 978. These are loaded once per session and are small next to a single unbounded result, so result shaping is where the budget goes.
