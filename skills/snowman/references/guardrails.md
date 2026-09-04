# snowman guardrails and output

## SQL filtering

`scripts/snowman.py` applies a conservative lexical check before query execution:

1. Mask comments, string literals, and quoted identifiers before checking
   keywords and statement separators. Comment and quote boundaries share one pass.
2. Reject multiple statements. One trailing semicolon is accepted.
3. Require `SELECT`, `WITH`, `SHOW`, `DESCRIBE`, `DESC`, or `EXPLAIN` first.
4. Reject write and DDL keywords such as `INSERT`, `CREATE`, `DROP`, and `CALL`,
   including after `WITH`. `REPLACE(...)` and `GET(...)` are allowed function
   calls. Their statement forms are still rejected.
5. Reject all `SYSTEM$...(...)` calls, including quoted names, and sequence
   advancement through `.NEXTVAL` or `GETNEXTVAL(...)`.

This is not a SQL parser or a universal side-effect boundary. UDFs and external
functions can perform actions the filter cannot detect. A least-privilege
Snowflake role and trusted read functions are still required. The check also
rejects some valid reads. Bare aliases named `set`, for example, match a blocked
keyword, while `update_date` does not. `SYSTEM$` reads are blocked as a group.

After validation, the wrapper resolves the connection and `default_warehouse`
from project context. An explicit environment selects its own settings.
Queries fall back to `default_env`. Unknown environments, mixed context forms,
and `--env` with a single-account context are rejected. `--connection` bypasses
context for bootstrap and retains the named connection's warehouse setting.

The CLI call uses `--format JSON_EXT --enhanced-exit-codes` and appends
`DESCRIBE RESULT LAST_QUERY_ID()` to the query in the same session. This second
statement provides schema metadata for the preview and saved result.

## Output

Successful query stdout contains data only. All type, NULL, truncation, and
recovery notes go to stderr as `# ...` lines. Preserve the separate streams
when parsing. A physical CSV line beginning `#` can be part of a quoted cell.

CSV has a header, with these cell representations:

| Value | CSV representation |
| --- | --- |
| NULL | Empty unquoted field |
| Empty string | `""` |
| Boolean | `true` or `false` |
| Object or array | Compact JSON, CSV-quoted as needed |

Multiline cells follow CSV quoting. Standard readers may collapse NULL and an
empty string. Use a reader that preserves quoted-empty fields when the
distinction matters, or use `--json`.

`--json` produces one compact JSON array. Empty results are `[]` plus a newline.
CSV empty results have no data output. Both emit `# 0 rows` on stderr.
Complete nested objects and arrays retain their JSON types. Scaled NUMBER
values may arrive from the CLI as strings such as `"1.50"`. Schema metadata
identifies their Snowflake type.

### Preview limits and recovery

| Option | Default | Bound |
| --- | ---: | --- |
| `--max-rows N` | 50 | Rows shown |
| `--max-cell N` | 200 | Retained characters of rendered cell text |
| `--max-output N` | 16000 | UTF-8 data bytes on stdout |

`0` removes an individual bound. Negative values are rejected. A positive JSON
byte limit must be at least 3 to fit `[]` and its newline. These limits bound
output, not query work or the size of the result fetched from Snowflake.

Cell truncation appends `…(+K chars)` after the retained prefix. In JSON mode,
a truncated cell becomes a string. Truncated objects and arrays contain
shortened compact JSON text, with an explicit stderr notice. Complete rows are
omitted to meet the byte limit, keeping JSON and CSV valid. A CSV header that
alone exceeds the byte limit is omitted with all rows.

A `# types:` note lists types that plain text cannot convey, such as scaled
NUMBER, FLOAT, DATE, TIMESTAMP, and VARIANT. The type note has a separate
1,024-byte cap. Other diagnostics and recovery notices are outside the data
byte limit.

Any row, cell, data-byte, or type-note truncation saves the complete CLI result:

```json
{"rows":[{"AMOUNT":"1.50"}],"types":[{"name":"AMOUNT","type":"NUMBER(10,2)"}]}
```

The artifact preserves all returned rows and `DESCRIBE RESULT` records.
Project queries save to gitignored `.snowman/results/<timestamp>__<sql-hash>.json`.
Bootstrap saves to a private `snowman-results-*` temporary directory.
The stderr `# full result:` notice gives the path relative to the current
working directory for project results, or an absolute bootstrap path.
Inspect only needed fields locally. The wrapper does not delete artifacts.

## Failures

`BLOCKED: <reason>` on stderr exits with code 2 before querying. The reason
can describe SQL, context, configuration, or invalid limits. It does not imply
that the submitted SQL was a write.

Unexpected CLI output and artifact-save failures occur after a query. They
produce `ERROR:` diagnostics that state the query already ran. The wrapper
emits no data stdout for these failures. It rejects inconsistent row shapes
rather than silently dropping fields.

CLI errors retain their exit code. Rich error panels become `ERROR: ...` lines
on stderr. Failed-query stdout is suppressed. Authentication failures may add
a hint matched to the connection's authenticator. See
[authentication](install.md#authentication) for the corresponding setup.

## Staging

`--stage "<SQL>" --name <purpose-slug>` writes SQL for manual execution.
It requires context and, for multiple environments, an explicit `--env`.
It accepts DML, DDL, and multiple statements. Empty scripts are rejected.

Files are gitignored under `.snowman/staged/<timestamp>__<slug>.sql`.
Multi-environment filenames also contain the environment. The header identifies
the target and includes a shell-quoted `snow sql -f ... --connection ...` command
with `--warehouse` when context specifies one. Run commands use paths relative
to the project root.

Destructive keywords add a `-- WARNING:` header, but do not prevent staging.
Stage mode prints `STAGED (not executed): <path>` and `run with: <command>`.
It does not execute or clean up scripts.
