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

### Blocked reads and substitutes

| Blocked | Read-only substitute |
| --- | --- |
| `LIST @stage/path` | `SELECT RELATIVE_PATH, SIZE, LAST_MODIFIED FROM DIRECTORY(@stage) WHERE STARTSWITH(RELATIVE_PATH, 'path')` where the stage has a directory table enabled. Like `LIST`, it matches `path` as a plain prefix, so keep a trailing slash only when the `LIST` path has one. It lists the files as of the table's last refresh. Without a directory table, `SELECT METADATA$FILENAME, METADATA$FILE_LAST_MODIFIED, COUNT(*) FROM @stage/path (FILE_FORMAT => '<db>.<schema>.<format>') GROUP BY 1, 2` scans the data and lists only files that yield rows. The row scan omits empty files. |
| `SYSTEM$TYPEOF(col)` | `DESCRIBE TABLE` for a column's declared type; the stderr `# types:` note names a result's VARIANT, OBJECT and ARRAY columns. |
| `SYSTEM$CLUSTERING_INFORMATION`, other `SYSTEM$` reads | `SHOW TABLES LIKE '<t>' IN SCHEMA <db>.<schema> ->> SELECT "cluster_by", "automatic_clustering" FROM $1` for clustering; otherwise stage the statement for the user. |
| `USE WAREHOUSE`, `USE ROLE`, `USE DATABASE` | `--warehouse <name>` for one call; the role comes from the connection, so pick the `--env` whose connection holds the access, or stage the check for the user. Qualify object names fully instead of `USE DATABASE`. |

### Connection resolution

After validation, the wrapper resolves the connection and `default_warehouse`
from project context. An explicit environment selects its own settings.
Queries fall back to `default_env`. `prd` and `prod` are aliases: when the
context defines only one, the other resolves to it and a `# environment:` note
on stderr names both. Unknown environments, mixed context forms,
and `--env` with a single-account context are rejected.

`--connection <name>` is for bootstrap only. It bypasses context and uses the
named connection's warehouse setting. It works only when executing a query
without `--env`, and it blocks when a `.snowman/context.md` exists at or above
the working directory.

The CLI call uses `--format JSON_EXT --enhanced-exit-codes --enable-templating NONE`
and appends `DESCRIBE RESULT LAST_QUERY_ID()` to the query in the same session. This second
statement provides schema metadata for the preview and saved result. With templating off,
the CLI sends `&name` and `<% name %>` text, such as `'F&W'`, unchanged.

## Direct snow calls

Agents never run `snow` or `snowsql` themselves. The only direct calls are
`snow connection list`, `snow connection test`, `snow --version` and `snow --help` or `-h`.
A staged script is run by the user, not the agent.

A `PreToolUse` hook, [`hooks/snow_guard.py`](../hooks/snow_guard.py), refuses
any other direct call, including after `&&`, `;` or a pipe, inside `$(...)`,
`bash -c` or `eval`, and behind wrappers such as `env`, `uvx` or `xargs`.
Where it runs:

| Harness | How the hook is registered |
| --- | --- |
| Claude Code | Comes with the plugin install (`/plugin install snowman@relentless-data-skills`) and fires inside helpers. `npx skills add` does not register it. |
| Cortex Code CLI | Add the entry below to `~/.snowflake/cortex/hooks.json`, or to `~/.claude/settings.json`, which Cortex also reads. Its shell tool is lowercase `bash`. |
| Codex | Add the entry below to `~/.codex/hooks.json`, then trust it in `/hooks`. Snowman ships no Codex plugin. |
| Cursor and others | No hook; this rule alone applies. |

For a manual entry, set `<skill-dir>` to the installed skill's directory:

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash|bash", "hooks": [
  {"type": "command", "command": "python3 \"<skill-dir>/hooks/snow_guard.py\""}]}]}}
```

Merge it into any `hooks` already in the file, and re-point it if the skill moves.

The hook catches a mistake, such as running the printed staged command. It does
not stop a deliberate bypass, such as Python with the Snowflake connector. The
connection's role is the real limit, so use a least-privilege role.

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
Empty CSV results retain the header when schema is available and fits the byte
limit. Both formats emit `# 0 rows` and all available column names and types on
stderr, subject to the type-note cap below.
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
NUMBER, FLOAT, DATE, TIMESTAMP, and VARIANT. Empty results include plain types
too. The type note has a separate 1,024-byte cap. Other diagnostics and recovery
notices are outside the data byte limit.

Any row, cell, data-byte, or type-note truncation saves the complete CLI result:

```json
{"rows":[{"AMOUNT":"1.50"}],"types":[{"name":"AMOUNT","type":"NUMBER(10,2)"}]}
```

The artifact preserves all returned rows and `DESCRIBE RESULT` records.
Project queries save to gitignored `.snowman/results/<timestamp>__<sql-hash>.json`.
Bootstrap saves to a private `snowman-results-*` temporary directory.
[Saved files](#saved-files) covers their `.gitignore`, permissions, and failed writes.
The stderr `# full result:` notice gives the path relative to the current
working directory for project results, or an absolute bootstrap path.
Inspect only needed fields locally. The wrapper does not delete artifacts.

## Failures

`BLOCKED: <reason>` on stderr exits with code 2 before querying. The reason
can describe SQL, context, configuration, or invalid limits. It does not imply
that the submitted SQL was a write.

Unexpected CLI output, preview-processing failures, and artifact-save failures
exit with code 1 and `ERROR: query already ran; ...`. Stdout stays empty.
The wrapper rejects inconsistent row shapes rather than dropping fields.
Query result stdout that is not valid UTF-8 is unexpected output, even inside a JSON string.

For these failures, the wrapper saves received CLI stdout unchanged to a private
temporary file with mode `0600`. The `# raw CLI stdout:` notice gives its absolute
path. Inspect the file locally as JSON_EXT if valid, or as unparsed text.
This recovery file differs from the normalized full-result JSON above.
Do not rerun automatically. If no output arrived or recovery storage also fails,
the diagnostic states that no output or complete artifact is available.

CLI errors retain their exit code. Rich error panels become `ERROR: ...` lines
on stderr. Failed-query stdout is suppressed. Authentication failures may add
a hint matched to the connection's authenticator. See
[authentication](install.md#authentication) for the corresponding setup.

## Staging

`--stage "$SQL" --name <purpose-slug>` writes SQL for manual execution. Set `SQL`
with the [Run queries](../SKILL.md#run-queries) heredoc in the same shell call.
It requires context and, for multiple environments, an explicit `--env`.
It accepts DML, DDL, and multiple statements. Empty scripts are rejected.

Files are gitignored under `.snowman/staged/<timestamp>__<slug>.sql`, as
[Saved files](#saved-files) describes.
Multi-environment filenames also contain the environment name, slugged like the
purpose, when that slug is not empty. The header identifies the target, with the
environment name unchanged, and includes a shell-quoted `snow sql -f ... --connection ... --enable-templating NONE`
command, with `--warehouse` from the flag, or from context when it specifies one.
Templating stays off, so the file runs as reviewed. The path and run command use
the file's absolute path, so they work from any directory.

Destructive keywords add a `-- WARNING:` header and print the same warning to
stderr, but do not prevent staging.
Stage mode prints `STAGED (not executed): <path>` and `run with: <command>`.
It does not execute or clean up scripts.

## Saved files

`.snowman/results/` and `.snowman/staged/` each hold a `.gitignore`. The wrapper
creates it as `*`. If one already exists, the wrapper keeps its rules and appends
a `*` line unless the last line is exactly `*`. Git applies the last matching
rule, so the appended line wins over an earlier `!*.json`.
Git does not read a `.gitignore` that is a symbolic link. A query blocks before
it runs when `.snowman/results/.gitignore` is a link. Staging blocks before it
writes when `.snowman/staged/.gitignore` is a link. Neither changes the link.
Replace the link with a regular file that contains `*`.
Git drops every rule in a `.gitignore` of 100 MiB or more, the appended `*`
included. The wrapper does not check the size, so keep each `.gitignore` small.
Each run sets the directory to `0700`. Every saved file, bootstrap results
included, is created `0600`. A write that fails removes the file, so no partial
artifact keeps the final name.
