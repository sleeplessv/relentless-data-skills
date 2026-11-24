# PROTOTYPE: cross-harness test driver

Throwaway. This branch is never merged. It is the primary source for the wayfinder ticket
[Running the cross-harness test from Claude Code through Herdr](https://github.com/sleeplessv/relentless-data-skills/issues/188);
the decision is in that ticket's resolution.

**Question.** How does a Claude Code session start each supported harness, hand it a task,
know the run has finished, and read the result and the run's measurements?

**Answer.** Start the harness's headless command in a Herdr terminal with `hc run --bg`. The
run has finished when `hc get` reports `state: finished`. The result, session id, model and
tokens come from the output the harness printed, plus the session log on Codex. `xh.py` does
this for all five harnesses.

## Run it

From a terminal inside Herdr (`HC_TERMINAL_ID` set):

```sh
python3 xh.py all --connection <snowflake connection>   # every harness, one row each
python3 xh.py run codex                                 # one harness
python3 xh.py run cursor --prompt "/xh-probe T1"        # start the stand-in skill
```

Each run makes a fresh fixture folder under `$TMPDIR` with its own `git init` and no remote:
an `AGENTS.md` holding a codeword, a `notes.txt` to edit, and a skill `xh-probe` that is closed
to model invocation, as `deliver` will be. The default task appends a line to `notes.txt` and
replies with the codeword. Raw output stays in the fixture as `.xh-out.txt` and `.xh-err.txt`.

Without `--connection` the Cortex Code run is skipped: every Snowflake connection on the
owner's machine belongs to a client, so the driver never falls back on the default.

## What was observed

Runs on 2026-11-24 from a Claude Code 2.1.331 session, with Herdr 0.9.5, Codex 0.172.0, Cursor
CLI 2026.11.22, `agy` 1.5.16 and Cortex Code 1.2.56. Light-class models. Every run exited 0,
made the edit and returned the codeword, in 5 to 18 seconds.

| | Claude Code | Codex | Cursor | Antigravity | Cortex Code |
|---|---|---|---|---|---|
| Command | `claude -p "<prompt>" --output-format json --permission-mode acceptEdits` | `codex exec --json --sandbox workspace-write --skip-git-repo-check "<prompt>"` | `cursor-agent -p --output-format stream-json --force "<prompt>"` | `agy -p "<prompt>" --output-format stream-json --mode accept-edits` | `cortex -p "<prompt>" --output-format stream-json --private --bypass -c <connection>` |
| Result text | `result` event, `.result` | last `item.completed` with an `agent_message`, `.item.text` | `result` event, `.result`; it joins every assistant message, not only the last | `result` event, `.result.response` | `result` event, `.result`; joins messages as Cursor does |
| Session id | `.session_id` | `thread.started`, `.thread_id` | `.session_id` | `.conversation_id` | `.session_id` |
| Model | keys of `.modelUsage` | not in the output; `turn_context` in `~/.codex/sessions/<y>/<m>/<d>/rollout-*-<thread id>.jsonl`, with the effort | `system init` event, `.model`, as a display name (`Claude Haiku 5.5 300K High No Thinking`) | `init` event, `.init.model` | `system init` event, `.model`; keys of `.modelUsage` |
| Tokens | `.usage`, `.modelUsage`, `.total_cost_usd` | `turn.completed`, `.usage` | `result` event, `.usage` | `result` event, `.result.usage` | `result` event, `.usage` and `.modelUsage` |
| Refusals | `.permission_denials` | none seen | none seen | `denied_actions` (from the research, not seen here) | `.permission_denials` |
| Typed skill command | `/xh-probe T1` | `/xh-probe T1` and `$xh-probe T1` | `/xh-probe T1` | `/xh-probe T1` | `$xh-probe T1` only |

Facts the driver had to be changed for:

- **`hc wait` returns before the process exits** when hc knows the program as an agent. On
  Cortex Code it returned twice with reason `status` and then with `exit`. The driver waits
  again until `hc get` reports `state: finished`.
- **Terminal names are unique machine-wide.** Two runs of one harness at once clashed on the
  name, so the name carries the driver's process id.
- **Claude Code's `--output-format json` printed an array** of every event on this machine,
  not one object. The driver reads the last element.
- **Antigravity and Cursor name the model only in the stream.** Their `json` format has no
  model field, so the driver asks for `stream-json`.
- **Cortex Code does not take `/xh-probe` as a skill command** in a headless prompt. It
  answered that it did not recognise the command, though its `init` event listed the skill.
  `$xh-probe T1` started it.

Other facts:

- A terminal started with `hc run` gets herdr-core's environment, not the caller's. `CLAUDECODE`
  and `CLAUDE_CODE_ENTRYPOINT` were absent, so a harness started this way does not look like a
  child of Claude Code.
- `hc get` holds `exit_code`, `created_ms` and `finished_ms`, so the driver takes the run's
  duration from Herdr and not from the harness.
- Cursor's and Cortex Code's headless output carries token counts. The token research had
  read this for Cursor and inferred it for Cortex Code; both are now seen.
- Antigravity's `init` event reported `permission_mode: request-review` under
  `--mode accept-edits`, and the edit was still made.

## Not shown by this prototype

- No run started a helper. A helper's model and tokens, and anything two layers down, are
  unseen here.
- No hook was registered, so no guard refused anything.
- No GitHub remote: no PR, no CI, no merge.
- No interactive session.
- Whether the harness or the model resolved the typed skill command was not separated. On
  Codex, Cursor and Antigravity the model may have found the skill file by itself, which a
  skill closed to model invocation should prevent.
