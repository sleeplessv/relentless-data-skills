# Reaching a model from each harness

Facts for steps 1, 3, 4 and 5 of `SKILL.md`. Each harness's model IDs are in [catalog.md](catalog.md).

## Probe the CLIs and Herdr

Run this when you do not yet know which CLIs and Herdr are present. It reads only, sets no variable outside itself, and always exits `0`:

```sh
HERDR=no
if [ -n "${HC_TERMINAL_ID:-}" ] && command -v hc >/dev/null 2>&1; then
	HERDR=yes
fi
for BIN in claude codex agy cortex; do
	if command -v "$BIN" >/dev/null 2>&1; then
		printf '%s=yes\n' "$BIN"
	else
		printf '%s=no\n' "$BIN"
	fi
done
printf 'herdr=%s\n' "$HERDR"
```

Another harness is reachable only when the output has `herdr=yes`, that harness's CLI `=yes`, and `herdr-delegate` is found (see [Through Herdr](#through-herdr-to-another-harness)).

## What a harness carries

| Harness | Carries | How to list it |
| --- | --- | --- |
| Claude Code | Anthropic models | No command. It takes the aliases `fable`, `opus`, `sonnet` and `haiku`. |
| Codex | OpenAI models | `codex debug models`, through the resolver below. |
| Antigravity | Google models, and others the account adds | `agy models` |
| Cortex Code | Several vendors' models, set per account, role and region | The Cortex probe below. |
| Cursor | Several vendors' models, set per plan | No command. Pass the ID and read the result. |

A list is true for the account and the day it was read. Read it once per session.

### List what Cortex Code carries

Cortex Code has no list command. Asking it for a model that does not exist makes it reject the request and print the account's list:

```sh
OUT=$(command cortex exec -m __model_probe__ --no-history --no-mcp --max-turns 1 "hi" 2>&1 </dev/null)
LIST=$(printf '%s\n' "$OUT" | sed -n 's/^- Available models: //p')
[ -n "$LIST" ] || { echo "no model list in the cortex output" >&2; exit 1; }
printf '%s\n' "$LIST" | tr ',' '\n' | sed 's/^ *//'
```

Exit code `0` prints one Cortex ID per line. Exit code `1` means Cortex printed no list: it is signed out, or its error text changed. Then route without a list, pass the Cortex ID, and read the result as the next section says.

### Resolve the newest Codex slug for an OpenAI family

Codex moves point versions within a family. Set `FAMILY` to `astra`, `sol`, `terra` or `luna` on the same command line as the block; it stops when `FAMILY` is unset:

```sh
: "${FAMILY:?set FAMILY to astra, sol, terra or luna}"
CATALOG=$(codex debug models) || { echo "codex debug models failed: $?" >&2; exit 1; }
MODEL=$(printf '%s' "$CATALOG" | jq -r --arg suffix "-$FAMILY" '[.models[] | select(.visibility == "list" and (.slug | endswith($suffix)))] | sort_by(.priority) | .[0].slug // empty')
[ -n "$MODEL" ] || { echo "no visible -$FAMILY model in catalog" >&2; exit 1; }
printf 'MODEL=%s\n' "$MODEL"
```

Exit code `0` prints `MODEL=<slug>`. A non-zero exit means `FAMILY` is unset, `codex` failed, `jq` is missing, or the account lists no model in that family. Then Codex does not carry the model: take the next harness in step 3.

## An agent of the session's own harness

| Harness | Parameter | Value | Effort for one agent |
| --- | --- | --- | --- |
| Claude Code | `model` on the agent call | `opus`, `fable`, `sonnet` or `haiku` | `effort` on the same call |
| Codex | `model` on `spawn_agent` | The slug the resolver printed | `reasoning_effort` on the same call |
| Antigravity | `Model` on `invoke_subagent` | `pro`, `flash`, `flash_lite`, or `inherit` for the session's model | None. The agent runs at the session's effort. |
| Cortex Code | `model` on `task` | The Cortex ID from the catalog, or `inherit` for the session's model | None. The agent runs at the session's effort. |
| Cursor | `model` on the worker | The ID from Cursor's model list. Pass none when you do not have it. | Part of the model ID |

- **Claude Code.** `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` in the environment overrides the `model` you pass. A fork runs on the session's model and effort.
- **Codex.** Set `fork_turns: "none"` whenever you set `model` or `reasoning_effort`.
- **Cortex Code.** An ID Cortex lacks does not fail the call. The agent returns as completed and its result begins `Error: <id> is not authorized or not available`. Read every result for that text, treat it as "does not carry", and take the next harness in step 3. The setting `subagentModelOverrides` and the variable `CORTEX_SUBAGENT_MODEL_OVERRIDES` override the `model` you pass. The aliases `opus`, `sonnet` and `haiku` are rejected like any unknown ID.
- **Cursor.** A plan limit can replace the model you passed without an error. Ask the agent to state its model in its result.

## Through Herdr to another harness

Find `herdr-delegate`. When your skill list already shows it, use that and skip the lookup:

```sh
DELEGATE=$(find -L ~/.agents/skills ~/.claude/skills ~/.codex/skills ~/.cursor/skills ~/.snowflake/cortex/skills -maxdepth 2 -path '*/herdr-delegate/SKILL.md' 2>/dev/null | head -n 1)
printf 'DELEGATE=%s\n' "$DELEGATE"
```

`find` exits `0` whether or not it matches, so the test is whether the line prints a path. `DELEGATE=` with nothing after it means the skill is absent and no other harness is reachable.

`herdr-delegate` owns the launch: the brief, the labels, the tool grants and the wait. Follow it whole, and add only these flags to the program in its "Launch the helper" step, before the brief:

| CLI | Model flag | Effort flag |
| --- | --- | --- |
| `claude` | `--model "$ALIAS"` | `--effort "$EFFORT"` |
| `codex` | `-m "$MODEL"` | `-c model_reasoning_effort="$EFFORT"` |
| `agy` | `--model "$ID"` | None. The effort is the end of the ID. |
| `cortex` | `-m "$ID"` | `--effort "$EFFORT"` |

- `ALIAS` is `fable`, `opus`, `sonnet` or `haiku`.
- `MODEL` is the slug the Codex resolver printed.
- `ID` is the harness's own ID for the model, from the catalog.
- `EFFORT` is the route's effort. Leave the effort flag out when the route leaves effort unset.
- **Antigravity IDs end in the effort**, as `gemini-4-carbon-high`. Take the ID from `agy models` whose ending is the route's effort, and the `-medium` ID when the route leaves effort unset.
- **A Cortex launch with an ID it lacks** exits `1` and prints `Error: <id> is not authorized or not available` on stderr. Treat it as "does not carry" and take the next harness in step 3.
