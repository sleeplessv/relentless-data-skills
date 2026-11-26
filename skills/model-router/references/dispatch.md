# Dispatching the chosen model across harnesses

Use this reference once `SKILL.md` picks a target model and reasoning effort.

## 1. Probe reachable harnesses and CLIs

Run this read-only check when you do not yet know which cross-vendor CLIs or Herdr context are present. Every variable is local to the command, and the command always exits `0`:

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

Read the printed `=yes` and `=no` lines:

- `herdr=yes` with the target CLI `=yes` enables cross-vendor dispatch through `herdr-delegate`.
- `herdr=no` or the target CLI `=no` means cross-vendor Herdr tabs are unavailable. Stay inside the active harness and use its model from the same model class (`apex`, `strong`, `standard`, `light`).

## 2. Pass the model inside the active harness

| Harness | Parameter | `apex` | `strong` | `standard` | `light` | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Code | `model` alias on subagent call | `fable` | `opus` | `sonnet` | `haiku` | Forks inherit the parent model and effort. `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` blocks per-call overrides. |
| Codex | `model` on `spawn_agent` | `gpt-6.2-astra` | `gpt-6.2-sol` | `gpt-6.1-terra` | `gpt-6-luna` | Takes exact catalog slugs, never aliases. Set `fork_turns: "none"` whenever setting `model` or `reasoning_effort`. |
| Antigravity | `Model` on `invoke_subagent` | `pro` (or `inherit` on Carbon) | `pro` or `inherit` | `flash` | `flash_lite` | `browser` subagents default to `flash`. `inherit` reuses the coordinator's Gemini model. |
| Cursor | `model` on worker or launch | Exact catalog ID | Exact catalog ID | Exact catalog ID | Exact catalog ID | Plan limits can fall back silently to another model. |
| Cortex Code | `model` on `task` call | Exact catalog ID | Exact catalog ID | Exact catalog ID | Exact catalog ID | Bare aliases (`opus`, `sonnet`, `haiku`) warn and fall back to `inherit`. |

### Resolve the newest Codex slug for an OpenAI family

Codex updates point versions (`gpt-6.1-sol` to `gpt-6.2-sol`). Before passing a hardcoded OpenAI slug to `spawn_agent` or `codex -m`, resolve the newest visible slug for `FAMILY` (`astra`, `sol`, `terra`, or `luna`):

```sh
FAMILY="${FAMILY:-sol}"
CATALOG=$(codex debug models) || { echo "codex debug models failed: $?" >&2; exit 1; }
MODEL=$(printf '%s' "$CATALOG" | jq -r --arg suffix "-$FAMILY" '[.models[] | select(.visibility == "list" and (.slug | endswith($suffix)))] | sort_by(.priority) | .[0].slug // empty')
[ -n "$MODEL" ] || { echo "no visible -$FAMILY model in catalog" >&2; exit 1; }
printf 'MODEL=%s\n' "$MODEL"
```

Exit code `0` prints `MODEL=<slug>`. A non-zero exit means `codex` failed, `jq` is missing, or the signed-in account lists no model in `FAMILY`. Without `jq`, read `CATALOG` directly and pick the `visibility: "list"` entry whose `slug` ends with `-$FAMILY` and has the lowest `priority` number. On an empty match, fall back to the next class available in the catalog.

## 3. Cross vendors through Herdr

When `herdr=yes` and the chosen model belongs to another vendor's CLI, locate `herdr-delegate` from the installed skill roots and follow its full launch, wait, verification, and clean-up procedure:

```sh
DELEGATE=$(find -L ~/.agents/skills ~/.claude/skills ~/.codex/skills -maxdepth 2 -path '*/herdr-delegate/SKILL.md' 2>/dev/null | head -n 1)
printf 'DELEGATE=%s\n' "$DELEGATE"
```

`find` exits `0` even when nothing matches, so check that `DELEGATE` is non-empty and readable. When `DELEGATE` is empty, skip cross-vendor launch and run the task on the active harness's same-class fallback model.

When `DELEGATE` is present, substitute the model-specific program into step 3 of `herdr-delegate` (`RESULT`, `BRIEF`, `HC_TERMINAL_ID`, and `MODEL` expanded as literal strings first):

- **OpenAI via Codex (`Astra`, `Sol`, `Terra`, `Luna`).** Resolve `MODEL` with the catalog block above, then launch `codex --no-daemon -m "$MODEL" -c model_reasoning_effort="$EFFORT" "$BRIEF"` (omit `-c model_reasoning_effort=...` when effort is unset; add `--approve-for-me --add-dir "$(dirname "$RESULT")"` when the helper writes `RESULT` autonomously).
- **Anthropic via Claude Code (`fable`, `opus`, `sonnet`, `haiku`).** Launch `claude --model "$ALIAS" "$BRIEF" --allowedTools "Bash(hc send $HC_TERMINAL_ID *)" "Edit(/$RESULT)"` (drop `Bash(hc send ...)` and add `--no-notify` on `hc run` when the caller is itself a subagent).
- **Google via Antigravity (`gemini-4-carbon`, `gemini-4-neon`, `gemini-4-hydrogen`, `gemini-3.5-flash-lite`).** Check `agy --help` for the installed build's model flag; when `--model` is supported, pass `--model "$MODEL"`, otherwise launch `agy --dangerously-skip-permissions --add-dir "$(dirname "$RESULT")" -i "$BRIEF"` to run on its configured Gemini default.
