# Token usage sources for Cortex Code and Cursor outside the session transcript

Research date: 2026-11-21. Question: Cortex Code (Snowflake's coding agent CLI, binary
`cortex`) and Cursor (terminal agent `cursor-agent`, and the Cursor IDE) write session
transcripts with no token counts. Does either vendor expose token usage per session or per
request some other way, and can one agent run be matched to it? The answer decides whether
these two harnesses can join a per-harness token-cost comparison next to Claude Code and
Codex, whose logs carry token counts.

Primary sources only: Snowflake documentation, Cursor documentation, the two CLIs' own
`--help` output, and the names of local files and of the keys inside them. No agent session
was started, no Snowflake query was run, and no authenticated API was called, so nothing
below was tested end to end. Each claim is marked as **read** (stated in a primary source),
**observed** (seen in local file or key names on one macOS machine), or **inferred** (my
reasoning, not stated anywhere).

## Verdict

| Harness | Source found | Best source | Grain | Match key | Access |
|---|---|---|---|---|---|
| Cortex Code | Yes | `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY` (server side); `~/.snowflake/cortex/stats/usage.json` (local) | Request (view); session and model (local file) | `REQUEST_ID`, or user plus time window (view); session id (local file) | Read access to the `SNOWFLAKE` database (view); none (local file) |
| Cursor terminal agent | Yes, for headless runs on a current CLI; otherwise only through team admin sources | `usage` in `--output-format stream-json` / `json` output, captured at run time | Turn and run | `session_id` in the same output | CLI login; a CLI newer than the 2025.09.12 build checked here |
| Cursor IDE | No local or individual-plan source; team admin sources only | Admin API `POST /teams/filtered-usage-events` | Request (usage event) | `conversationId`, plus user and timestamp | Team admin API key; the API overview lists the Admin API for Enterprise teams |

- **Cortex Code can be included.** Snowflake records every CLI request with input, output,
  cache-read and cache-write tokens and credits, per model, with up to one hour of latency
  and one year of retention (read). The view has no session column, so a run is matched by
  request id or by user and time window. A local stats file keyed by session id also holds
  the four token counts per model (observed), but its schema is undocumented and on the
  machine checked it held only the two most recent days of use.
- **The Cursor terminal agent can be included only going forward, and only for headless
  runs.** The CLI changelog says headless output carries per-turn and total token usage
  (read), but the output-format reference page does not list the field, and the build
  installed on the machine checked predates the feature (inferred from its version date).
  Transcripts already on disk cannot be costed after the fact without a team admin source.
- **The Cursor IDE has no per-session token source for an individual account.** The local
  state database has token fields that are all zero (observed). Per-request tokens exist
  only server side, through the Admin API or the OpenTelemetry export, both team-admin
  features.

## Versions checked

| Harness | Version or ref | Sources |
|---|---|---|
| Cortex Code | CLI 1.2.46 (installed; changelog entry dated 2026-11-16) | docs.snowflake.com pages listed under [Sources](#sources), fetched 2026-11-21; `cortex --help`, `cortex exec --help`, `cortex conversations --help` |
| Cursor terminal agent | `cursor-agent` 2025.09.12 (installed); CLI changelog to v2026.11.17 | cursor.com/docs pages listed under [Sources](#sources), fetched 2026-11-21; `cursor-agent --help` and subcommand help |
| Cursor IDE | docs as fetched 2026-11-21; local state database as found | same Cursor docs; key names in the local state database |

## Cortex Code

### Sources

| Source | Reports | Grain | Match to a run | Access | Freshness | Status |
|---|---|---|---|---|---|---|
| `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY` | `TOKENS`, `TOKEN_CREDITS`; `TOKENS_GRANULAR` and `CREDITS_GRANULAR` per model with `input`, `cache_read_input`, `cache_write_input`, `output` | One row per request | `REQUEST_ID`, `PARENT_REQUEST_ID`; else `USER_NAME` and `USAGE_TIME` window. No session column | `IMPORTED PRIVILEGES` on the `SNOWFLAKE` database, or a `SNOWFLAKE` database role | Latency up to 1 hour; 365 days retained | read |
| `SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COCO_USAGE_HISTORY` | Same columns plus `INTERFACE` (`cli`, `desktop`, `snowsight`) | One row per request | Same | Same; the role table maps it to `USAGE_VIEWER` | Same | read |
| `ORGANIZATION_USAGE` copies of both views | Same | Same | Same | Premium views, available in the organization account | Latency 24 hours; 1 year retained | read |
| `SNOWFLAKE.LOCAL.AI_OBSERVABILITY_EVENTS` | Spans per prompt; the `CodingAgent.Step-0` span holds token counts, model, latency and a `request_id` | Span; one trace (`trace_id`) per user prompt | `request_id` joins to the usage views; `trace_id` groups one turn | `SNOWFLAKE.AI_OBSERVABILITY_READER` application role | Best effort; latency not stated | read |
| `~/.snowflake/cortex/stats/usage.json` | `inputTokens`, `outputTokens`, `cacheReadTokens`, `cacheWriteTokens`. No credits or cost | Session and model; also day and model | Top-level key is the session id, the same id as the conversation file name | Local file | Written within minutes of session activity; retention looks short | observed; existence read |
| `/stats`, `/status`, status bar | Session statistics; 24-hour usage against a daily credit limit; an estimated token count while thinking | Session; rolling 24 hours | Interactive only | None | Live | read; contents not documented |
| Headless output and Agent SDK | Python `ResultMessage.usage` (untyped dict) and `total_cost_usd` | Turn | `session_id` on the same message | CLI plus SDK | Live | read for the Python type; contents not documented |

### Account Usage views

The view description says "Each row in the view represents a single request and provides
detail about the aggregated tokens and credits as well as a granular breakdown by model."
Columns are `USER_ID`, `USER_NAME`, `USER_TAGS`, `REQUEST_ID`, `PARENT_REQUEST_ID`,
`USAGE_TIME`, `TOKEN_CREDITS`, `TOKENS`, `TOKENS_GRANULAR`, `CREDITS_GRANULAR` and
`METADATA` (`role_id`, `role_name`, `inference_region`). Usage notes: "Latency for the view
may be up to 1 hour" and "within the last 365 days (1 year)". The CLI view excludes Snowsight
and desktop requests; `SNOWFLAKE_COCO_USAGE_HISTORY` covers all three and adds `INTERFACE`.
Source: [CORTEX_CODE_CLI_USAGE_HISTORY](https://docs.snowflake.com/en/sql-reference/account-usage/cortex_code_cli_usage_history),
[SNOWFLAKE_COCO_USAGE_HISTORY](https://docs.snowflake.com/en/sql-reference/account-usage/snowflake_coco_usage_history).

Three facts shape how a run is matched:

- **No session column.** Neither view has a session, conversation or thread id (read). A run
  is a set of requests, so it has to be assembled from request ids or from a user and time
  window.
- **Which account holds the rows.** The settings page says token credits "are billed to the
  account for this connection", meaning the connection named by `cortexAgentConnectionName`,
  "not to the active SQL working connection" (read). Query the account of the inference
  connection.
- **Request ids exist locally, but the join is untested.** The conversation file has a
  `last_request_id` key, and the local stats file lists `recentRequestIds` per session
  (observed). No Snowflake page says these equal `REQUEST_ID` in the views (inferred that
  they do). The list is named "recent", so it may not hold every request of a long session
  (inferred). The fallback is `USER_NAME` plus a `USAGE_TIME` window taken from the
  conversation file's `created_at` and `last_updated` keys, or from the `user_sent_time` and
  `assistant_sent_time` keys on its history lines (observed keys). That window is ambiguous
  when the same user runs two sessions at once.

Access: the Account Usage page says to grant `IMPORTED PRIVILEGES` on the `SNOWFLAKE`
database or to use `SNOWFLAKE` database roles; its role table lists
`SNOWFLAKE_COCO_USAGE_HISTORY` under `USAGE_VIEWER`. I did not find the three per-surface
views in that role table. Source: [Account Usage](https://docs.snowflake.com/en/sql-reference/account-usage),
[Organization Usage](https://docs.snowflake.com/en/sql-reference/organization-usage).

### AI Observability event table

"Every CoCo interaction emits span-level records into the
SNOWFLAKE.LOCAL.AI_OBSERVABILITY_EVENTS event table. Each user prompt is one turn, which
corresponds to one OpenTelemetry trace (trace_id)." The `CodingAgent.Step-0` span "Contains
the user prompt, model response, token counts, tool selection, latency, and a request_id."
The documented cost attribution joins
`RECORD_ATTRIBUTES['snow.ai.observability.agent.planning.request_id']` to `REQUEST_ID` in
`SNOWFLAKE_COCO_USAGE_HISTORY`, and groups on `TRACE['trace_id']` for one turn. The page
warns: "Use the usage views, not the event table, as the source of truth for credits and
tokens. Trace delivery to AI_OBSERVABILITY_EVENTS is best effort, so join results can
under-report cost." The page names no span attribute that carries the CLI session id, so
this table gives turn grain, not session grain (read; the absence is from the pages fetched).
Source: [Observability](https://docs.snowflake.com/en/user-guide/cortex-code/observability),
[AI_OBSERVABILITY_EVENTS](https://docs.snowflake.com/en/sql-reference/local/ai_observability_events).

### Local stats file

Snowflake documents the file in one changelog line under 1.1.41: "Usage tracking: Subagent
token usage is recorded in stats/usage.json alongside the main session." Under 1.1.87: "The
/stats command is now available to everyone. Use it to view statistics about your current
session." Neither `/stats` nor the file appears in the CLI reference or settings pages, and
no page gives the schema (read). Source: [changelog](https://docs.snowflake.com/en/user-guide/cortex-code/changelog),
[CLI reference](https://docs.snowflake.com/en/user-guide/cortex-code/cli-reference).

Key names observed in the file on CLI 1.2.46:

- `version`
- `daily.<date>`: `inputTokens`, `outputTokens`, `cacheReadTokens`, `cacheWriteTokens`,
  `sessionCount`, and `byModel.<model>` with the same four token keys
- `sessions.<session id>`: `date`, `startTime`, `durationMs`, `recentRequestIds`,
  `rootSessionId` (present on some entries), and `models.<model>` with the same four token
  keys

Observed, not documented:

- Every session key in the file matched a conversation file of the same id in
  `~/.snowflake/cortex/conversations/`, so a run is matched by session id alone.
- Entries with `rootSessionId` point at another entry in the same file. Read with the
  changelog line, these are subagent sessions, so a run's total is the root entry plus the
  entries that name it as root (inferred).
- The file held entries for only the two most recent days of use, while conversation files
  from earlier days were still on disk. Either the file is pruned or it was reset recently;
  no page says which. Treat it as short-lived and copy it soon after a run.
- It holds token counts only. Credits come from the Account Usage views or from the
  Snowflake Service Consumption Table rates.

### Headless output and interactive commands

- **Headless flags exist; their schema is not documented.** `cortex --help` lists
  `--output-format stream-json` and `cortex exec --help` lists `--format json` (read). The
  CLI reference describes them only as "JSON output (for scripting)" and gives no event
  schema (read).
- **The Python SDK types a usage field.** The Agent SDK Python reference types the final
  message as `ResultMessage` with `session_id`, `total_cost_usd: float | None` and
  `usage: dict[str, Any] | None`, and says task messages carry `usage (TaskUsage)`. The
  TypeScript reference's `SDKResultMessage` type lists neither field. No page says what keys
  `usage` holds or when it is `None` (read). The SDK requires the CLI and accepts a path to
  it, so the CLI's stream-json result event probably carries the same `usage` object
  (inferred, untested).
- **Interactive displays are not machine-readable.** `/status` shows the 24-hour usage hint
  measured against a daily credit limit, which the limits page calls an estimate over a
  rolling 24-hour window. The status bar shows "an estimated token count" while the model
  thinks (read).
- **Admin charts count requests, not tokens.** The admin page charts requests per week, per
  day and by surface (read).

Source: [Agent SDK Python reference](https://docs.snowflake.com/en/user-guide/cortex-code-agent-sdk/python-reference),
[TypeScript reference](https://docs.snowflake.com/en/user-guide/cortex-code-agent-sdk/typescript-reference),
[daily credit usage limits](https://docs.snowflake.com/en/user-guide/cortex-code/credit-usage-limit),
[admin](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-admin).

### Session files

The known session files were rechecked for usage keys. The conversation file has
`session_break_context_usage.input_tokens` and `.context_window`, a context-window snapshot
and not a running total. History lines have `model`, `user_sent_time`, `assistant_sent_time`
and `created_on`, and no token keys (observed).

## Cursor terminal agent

### Sources

| Source | Reports | Grain | Match to a run | Access | Freshness | Status |
|---|---|---|---|---|---|---|
| Headless output, `-p --output-format stream-json` or `json` | Input, output and cache token totals; `reasoningTokens` when the model reports them | Turn, and run total in the result | `session_id` and `request_id` in the same output | CLI login; current CLI | Live; must be captured when the run happens | read in the changelog; absent from the reference page |
| Hook payloads | "Per-turn token usage and a stable session ID" | Turn | `conversation_id`, `generation_id`, `transcript_path` in every hook input | A hook configured in `~/.cursor/hooks.json` or the project | Live | read in the changelog; field names not documented |
| Custom `statusLine` command | "live token usage data" | Live session | Not documented | CLI config | Live | read in the changelog; payload not documented |
| `/usage`, `/context` | Plan meters and spend; context window breakdown by category | Account billing cycle; current context | Interactive only | None | Live | read in the changelog; neither is on the slash-command page |
| Admin API `POST /teams/filtered-usage-events` | `tokenUsage` with `inputTokens`, `outputTokens`, `cacheWriteTokens`, `cacheReadTokens`, `totalCents`; `chargedCents`; `model` | Usage event (request) | `conversationId`, `userEmail`, `timestamp`, `isHeadless` | Team admin API key; listed for Enterprise teams | "Data is aggregated at the hourly level"; poll at most hourly | read |
| OpenTelemetry Export | `cursor.api.request` logs with input, output, cache-read and cache-creation tokens; `cursor.token.usage` and `cursor.cost.usage` metrics | Request (logs); aggregate (metrics) | `cursor.conversation.id`, `cursor.request.id`, `cursor.usage_event.id` on logs | Enterprise plan; a collector you run | Streamed; no backfill | read |
| Cursor SDK (TypeScript) | `TokenUsage` on `run.usage`, `result.usage` and per-turn `usage` events; billed cost from `Agent.getUsage()` | Turn and run | Agent id and run id | API key; `getUsage()` for local agents is enabled per account | Live | read; a different entry point from `cursor-agent` |

### Headless output

The CLI changelog has two entries:

- February 2026: "Token usage for scripts. Per-turn input/output/cache token totals and a
  `request_id` in `stream-json` output; headless transcripts write Claude Code-compatible
  JSONL."
- v2026.10.28: "Headless runs now include `reasoningTokens` in the per-turn and total
  `usage` of the result output when the model used reasoning tokens, so scripts can track
  the full token cost of a run."

The second entry links to the output-format reference page. That page, fetched the same day,
documents the terminal `result` event with `type`, `subtype`, `is_error`, `duration_ms`,
`duration_api_ms`, `result`, `session_id` and `request_id`, and no `usage` field on any
event. It does say "Field additions may occur over time in a backward-compatible way". So the
field's existence is read in the changelog, and its exact key names are not documented for
the CLI. The SDK reference defines `TokenUsage` as `inputTokens`, `outputTokens`,
`cacheReadTokens`, `cacheWriteTokens`, `totalTokens` and optional `reasoningTokens`; the CLI
object probably uses the same keys (inferred). Source:
[CLI changelog](https://cursor.com/docs/cli/changelog.md),
[output format](https://cursor.com/docs/cli/reference/output-format.md),
[SDK](https://cursor.com/docs/sdk/typescript.md).

Limits that follow:

- **Capture at run time.** The usage is in the process output, not in the transcript under
  `~/.cursor/projects/<proj>/agent-transcripts/`. A run whose output was not kept has no
  token record on disk. The changelog's "Claude Code-compatible JSONL" for headless
  transcripts does not say usage is written to them, and the transcripts checked here have
  only `role`, `message`, `type` and `status` keys (observed).
- **Headless only.** The documented field is on the print-mode output. Interactive sessions
  show token counts in the working status and the status line, with no documented file.
- **The installed build is too old.** The binary on the machine checked reports version
  2025.09.12; the changelog dates the feature to February 2026. Its `--help` lists
  `--output-format text | json | stream-json` and no usage option. I expect it to emit no
  `usage` (inferred from dates, untested). Update the CLI before relying on this.
- **Matching is direct.** Every event in the stream carries `session_id`, and the slash
  commands `/copy-request-id` and `/copy-conversation-id` exist for interactive sessions
  (read).

### Hooks and status line

The March 2026 changelog entry reads "Richer hook payloads. Per-turn token usage and a stable
session ID." The hooks reference documents the common input (`conversation_id`,
`generation_id`, `model`, `transcript_path`, `user_email` and others) and each event's
fields. The only token fields it documents are `context_tokens`, `context_window_size` and
`context_usage_percent` on `preCompact`, which describe context size, not usage. The `stop`,
`sessionEnd`, `afterAgentResponse` and `subagentStop` inputs list no token field. The April
2026 entry for the custom `statusLine` says it renders "with live token usage data"; the
configuration reference does not document `statusLine` or its input. Both are real per the
changelog and unusable from the docs alone: someone has to print a payload to learn the key
names. Source: [hooks](https://cursor.com/docs/hooks.md),
[CLI configuration](https://cursor.com/docs/cli/reference/configuration.md).

### Admin API usage events

`POST /teams/filtered-usage-events` returns one object per usage event with `timestamp`,
`userEmail`, `model`, `kind`, `maxMode`, `isHeadless`, `isTokenBasedCall`, `chargedCents`
and, "present when `isTokenBasedCall` is `true`", a `tokenUsage` object with `inputTokens`,
`outputTokens`, `cacheWriteTokens`, `cacheReadTokens` and `totalCents`. The session key is
documented: `conversationId` is the "ID of the conversation (agent session) that generated
this event. Use it to attribute spend to a session". It is "Omitted for events without an
associated conversation." Filters are `startDate`, `endDate`, `email`, `userId` and others;
there is no filter by conversation, so pull a time window and group by `conversationId`.
"Data is aggregated at the hourly level. We recommend polling this endpoint at most once per
hour." An organization-level twin exists at `/organizations/filtered-usage-events`.

Access: Basic authentication with a team API key that team administrators create, scope
`admin:*`. The API overview table lists the Admin API's availability as "Enterprise teams".
An individual plan has no equivalent documented API. Source:
[Admin API](https://cursor.com/docs/account/teams/admin-api.md),
[API overview](https://cursor.com/docs/api.md).

The neighbouring endpoints do not carry tokens: `/teams/daily-usage-data` is per user and
day with request and line counts, and the Analytics API's model usage is messages per model
per day (read).

### OpenTelemetry Export

Enterprise plan, configured by a team admin, sent server side to a collector the team runs.
The `cursor.api.request` log has `cursor.api.request.input_tokens`, `output_tokens`,
`cache_read_tokens` and `cache_creation_tokens` ("Always" present) and optional
`cursor.model.name`. "`cursor.conversation.id` is the session key. In the IDE and CLI it's
the composer chat UUID." Metrics carry no correlation ids: "use `api.request` logs for
per-conversation token totals." `cursor.cost.usage` is "a best-effort estimate", "not an
invoice". "There is no backfill from before the destination existed." Source:
[OpenTelemetry Export](https://cursor.com/docs/enterprise/opentelemetry-export.md),
[wire reference](https://cursor.com/docs/enterprise/opentelemetry-export/wire.md).

### Dashboard

For an individual account the help center points to **Usage** in the dashboard, or the
**Spending** tab on legacy plans, and says "Check your usage dashboard for request-level cost
details." No page documents the columns of that view, whether it shows token counts or a
conversation id, or an export for individual plans. Team analytics charts offer CSV download
of activity data, not tokens (read). Treat the individual dashboard as a manual, undocumented
source. Source: [usage and limits](https://cursor.com/help/models-and-usage/usage-limits.md),
[analytics](https://cursor.com/docs/account/teams/analytics.md).

### Local files

Besides the transcripts, `~/.cursor/ai-tracking/ai-code-tracking.db` has tables with
`conversationId`, `requestId`, `model` and timestamps for code attribution, and no token
columns. `cli-config.json` and `agent-cli-state.json` hold settings only (observed).

## Cursor IDE

### Sources

| Source | Reports | Grain | Match to a run | Access | Freshness | Status |
|---|---|---|---|---|---|---|
| Local state database `state.vscdb` | `tokenCount.inputTokens` and `.outputTokens` on message records, all zero; context-window fields on conversation records | Message; conversation | Conversation id and timestamps are present | Local file | Live | observed; no usable usage |
| Admin API `POST /teams/filtered-usage-events` | As for the terminal agent | Usage event (request) | `conversationId`, `userEmail`, `timestamp` | Team admin API key; Enterprise teams | Hourly | read |
| OpenTelemetry Export | As for the terminal agent | Request (logs) | `cursor.conversation.id` is "the composer chat UUID" in the IDE | Enterprise plan | Streamed; no backfill | read |
| Hook payloads | As for the terminal agent | Turn | `conversation_id` | A configured hook | Live | changelog claim is in the CLI changelog; field names not documented |
| Dashboard and editor settings | Remaining plan usage; "request-level cost details" | Account; request | Manual | The account | "real-time" on the Spending tab | read; columns not documented |

### Local state database

No Cursor page documents a local file that holds token usage. Key names observed in
`~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`:

- Table `cursorDiskKV`, keys prefixed `bubbleId:` (one per message): `tokenCount` with
  `inputTokens` and `outputTokens`, `requestId`, `modelInfo`, `createdAt`. In the 5,000
  most recent records sampled, `tokenCount` was zero in every one.
- Keys prefixed `composerData:` (one per conversation): `contextTokensUsed`,
  `contextTokenLimit`, `contextUsagePercent`, and `promptTokenBreakdown` with
  `totalUsedTokens`, `maxTokens` and `categories[].estimatedTokens`. These describe how full
  the context window is, some of them as estimates. They are not cumulative input and output
  usage, and they say nothing about cache tokens or cost. `usageData` exists and was empty.
- Table `composerHeaders`: `composerId`, `createdAt`, `lastUpdatedAt`, `isSubagent`.

So the database gives a conversation id and timestamps for matching, and no token usage
(observed).

### Matching an IDE or terminal run to a server-side event

Nearly all agent transcript directory names under `~/.cursor/projects/` appear as a
`composerId` in `composerHeaders` (observed). Cursor's docs say the composer chat UUID is the
conversation id for the IDE and the CLI in the OpenTelemetry export, and the Admin API
describes `conversationId` as the agent session. So the transcript's id should be the join
key to `conversationId` in usage events (inferred from those two reads and one observation,
untested). `userEmail` and `timestamp` narrow the window to pull.

## What the docs do not say

- **Cortex Code.** The schema and retention of `stats/usage.json`; what `/stats` prints; the
  event schema of `--output-format stream-json` and `exec --format json`; the keys of the
  SDK's `usage` dict; whether locally stored request ids equal `REQUEST_ID`; any session
  attribute on observability spans; latency of the event table.
- **Cursor.** The `usage` field on the output-format reference page, though the changelog
  links there for it; the token fields in hook payloads; the `statusLine` input; `/usage` and
  `/context` on the slash-command page; the columns and export of the individual usage
  dashboard; any local file with token usage.
- **Conflict found.** The Cursor CLI changelog and the output-format reference disagree on
  whether the result event has `usage`. The changelog is the newer statement.

## What this means for a token-cost comparison

- **Cortex Code:** include it. Use the local stats file for token counts per session when the
  run is recent, and the Account Usage view for credits and as the authoritative record.
  Before trusting either, test one known run: check that the session's request ids appear as
  `REQUEST_ID`, and that summed tokens agree between the file and the view.
- **Cursor terminal agent:** include it only for runs made headless with a current CLI and
  with the output stream saved. Test one run first to learn the `usage` key names. Existing
  transcripts have no cost record unless a team admin can pull usage events.
- **Cursor IDE:** exclude it unless the account sits in a team whose admin can call the Admin
  API or has the OpenTelemetry export on. No source at session grain exists for an individual
  account.

## Sources

Snowflake, fetched 2026-11-21:
[CORTEX_CODE_CLI_USAGE_HISTORY](https://docs.snowflake.com/en/sql-reference/account-usage/cortex_code_cli_usage_history),
[SNOWFLAKE_COCO_USAGE_HISTORY](https://docs.snowflake.com/en/sql-reference/account-usage/snowflake_coco_usage_history),
[Account Usage](https://docs.snowflake.com/en/sql-reference/account-usage),
[Organization Usage](https://docs.snowflake.com/en/sql-reference/organization-usage),
[AI_OBSERVABILITY_EVENTS](https://docs.snowflake.com/en/sql-reference/local/ai_observability_events),
[Observability](https://docs.snowflake.com/en/user-guide/cortex-code/observability),
[AI Observability](https://docs.snowflake.com/en/user-guide/snowflake-cortex/ai-observability),
[cost controls](https://docs.snowflake.com/en/user-guide/cortex-code/cost-controls),
[daily credit usage limits](https://docs.snowflake.com/en/user-guide/cortex-code/credit-usage-limit),
[CLI reference](https://docs.snowflake.com/en/user-guide/cortex-code/cli-reference),
[settings](https://docs.snowflake.com/en/user-guide/cortex-code/settings),
[admin](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-admin),
[changelog](https://docs.snowflake.com/en/user-guide/cortex-code/changelog),
[Agent SDK Python reference](https://docs.snowflake.com/en/user-guide/cortex-code-agent-sdk/python-reference),
[Agent SDK TypeScript reference](https://docs.snowflake.com/en/user-guide/cortex-code-agent-sdk/typescript-reference),
[Agent SDK streaming output](https://docs.snowflake.com/en/user-guide/cortex-code-agent-sdk/streaming-output).

Cursor, fetched 2026-11-21:
[output format](https://cursor.com/docs/cli/reference/output-format.md),
[CLI changelog](https://cursor.com/docs/cli/changelog.md),
[slash commands](https://cursor.com/docs/cli/reference/slash-commands.md),
[CLI parameters](https://cursor.com/docs/cli/reference/parameters.md),
[CLI configuration](https://cursor.com/docs/cli/reference/configuration.md),
[headless](https://cursor.com/docs/cli/headless.md),
[hooks](https://cursor.com/docs/hooks.md),
[API overview](https://cursor.com/docs/api.md),
[Admin API](https://cursor.com/docs/account/teams/admin-api.md),
[Analytics API](https://cursor.com/docs/account/teams/analytics-api.md),
[analytics](https://cursor.com/docs/account/teams/analytics.md),
[dashboard](https://cursor.com/docs/account/teams/dashboard.md),
[OpenTelemetry Export](https://cursor.com/docs/enterprise/opentelemetry-export.md),
[wire reference](https://cursor.com/docs/enterprise/opentelemetry-export/wire.md),
[SDK](https://cursor.com/docs/sdk/typescript.md),
[Cloud Agents API](https://cursor.com/docs/cloud-agent/api/endpoints.md),
[usage and limits](https://cursor.com/help/models-and-usage/usage-limits.md).

Local, read 2026-11-21: `cortex --help`, `cortex exec --help`, `cortex conversations --help`,
`cursor-agent --help` and its subcommand help; file names under `~/.snowflake/cortex/` and
`~/.cursor/`; key names in the files named above. No file content, id or account detail is
reproduced here.
