# What Antigravity can do: helpers, definition files, guards, token records and a terminal entry point

Research for issue #248, done 2026-11-23 on macOS (arm64). It answers nine questions about Google
Antigravity so that skills written for Claude Code can also run there through an adapter. Nothing
was built.

Every claim is marked **read** (a document or a file says so), **observed** (a command or run on
this machine showed it) or **not found**. Where the documentation and the running tool disagree,
both are given and the observed one is the one to build on.

## Answer

| # | Question | Short answer | Mark |
| --- | --- | --- | --- |
| 1 | Helpers | Yes. `invoke_subagent` starts one helper with a fresh context per call; several calls in one turn run together (four ran at once). Nesting limit 10 (depth 2 ran). A finished helper is idle, not gone: `send_message` to its conversation id wakes it with its context, also from a new `agy` process. A killed helper cannot be woken. No cap on helpers at once was found. | observed, limit read |
| 2 | Role definition files | `.agents/agents/<name>.md` (project) or `~/.gemini/config/agents/<name>.md` (global), Markdown with YAML front matter. `model` takes a tier (`inherit`, `flash_lite`, `flash`, `pro`), not an exact id: a file with an exact id is silently not loaded. There is no effort field. `invoke_subagent` has a `Model` argument with the same four tiers. The `tools` list withholds the edit tools and the helper-starting tools. | observed |
| 3 | Models | Exact ids are `<family>-<effort>`, for example `gemini-4-neon-high`. Three levels: `gemini-4-carbon-*` (strongest), `gemini-4-neon-*` (middle, the default), `gemini-4-hydrogen-*` (cheapest). Efforts: `low`, `medium`, `high`, plus `xhigh` on Neon and Hydrogen. Other vendors: Claude Opus 5.5, Claude Sonnet 5.5, GPT-OSS 120B. | observed |
| 4 | Working directory | A helper runs in its parent's directory (`inherit`), in a new git worktree that Antigravity makes (`branch`), or in a shared-storage copy (`share`). It cannot be started in a directory the caller names. A separate `agy -p` process can: it runs in the directory it is started from. | observed, `share` read |
| 5 | Skills and run rules | Skills: `<repo>/.agents/skills/`, `~/.gemini/config/skills/`, plugins, and two CLI-only folders. Not `~/.claude/skills` and not `~/.agents/skills`. `AGENTS.md` is loaded unprompted for the session and for a helper. `CLAUDE.md` is not read. | observed |
| 6 | Detection | A command run by the agent gets `ANTIGRAVITY_AGENT=1` and nine more `ANTIGRAVITY_*` variables. A helper gets the same names; only the conversation id differs. | observed |
| 7 | Guards | A `PreToolUse` hook refuses a command to the session and to a helper, also with prompts switched off. A `permissions.deny` rule does the same. No field marks a helper, but a hook can tell one by a file the parent writes. `ask` waits for the owner only in an interactive session: headless or with prompts off the command runs. | observed |
| 8 | Token records | Yes. `--output-format json` gives the run total; `stream-json` gives one `usage` per model request; `transcript.jsonl` on disk keeps per-request counts afterwards. A helper's tokens are not in its parent's total: they are in the helper's own transcript. No cost figure anywhere. | observed |
| 9 | Terminal entry point | Yes: `agy -p "<task>" --output-format json`. The process ends when the turn ends, the exit code and `status` say how, `.response` holds the result, and `--conversation <id>` continues it. | observed |

Antigravity has an equivalent for every thing the ticket asks about. The three places where the
equivalent is weaker than Claude Code's: a helper's model can be set only as a tier, a guard cannot
wait for the owner outside an interactive session, and a hook has to work out for itself whether it
is looking at a helper.

## Sources and versions

| Source | What | Version or date |
| --- | --- | --- |
| Web docs | `https://antigravity.google/docs/<page>` (each page has a Markdown mirror at `<page>.md`, indexed at `https://antigravity.google/llms.txt`) | read 2026-11-23 |
| Changelog | `https://antigravity.google/docs/changelog` and `agy changelog` | up to CLI 1.5.15 |
| Model posts | `https://antigravity.google/blog/gemini-4-{neon,carbon,argon,hydrogen}-in-google-antigravity` | Oct 13 to Nov 18, 2026 |
| Gemini API docs | `https://ai.google.dev/gemini-api/docs/{pricing,models,choosing-a-model,thinking}` | read 2026-11-23 |
| CLI | `~/.local/bin/agy` | `agy --version` = `1.5.15` before and after every run; it did not update itself |
| CLI binary | `strings -n 6 ~/.local/bin/agy` (Go, arm64, 229 MB) | same build |
| Bundled docs | `~/.gemini/antigravity-cli/builtin/skills/{agy-customizations,antigravity_guide,native_swarm,conversations}/` | same build |
| App | `/Applications/Antigravity.app`, `CFBundleShortVersionString` = `2.34.0` | read only, never opened |
| Local state | `~/.gemini/antigravity-cli/` (logs, `brain/`, `conversations/`), `~/.gemini/config/` | read only |

Gemini 4 Neon is a real model: Google's "frontier-level intelligence with fast end-to-end task
completion", announced for Antigravity on Nov 18, 2026 and the default for new conversations
(**read**, `/docs/models`, `/blog/gemini-4-neon-in-google-antigravity`).

## How the runs were made

All runs were headless (`agy -p`), in two throwaway folders under the session scratchpad, each
with its own `git init` and no remote. Nothing was installed, no sign-in or sign-out was done, the
app was not opened, and no file under the home directory was edited by hand. The model was
`gemini-4-neon-low` in every run.

The fixture: an `AGENTS.md` holding a codeword, `.agents/hooks.json` with one hook that logs its
input and answers by command name, stand-in commands that print a line and write a marker file,
and three agent files in `.agents/agents/`.

```json
{ "guard": {
    "PreToolUse": [ { "matcher": "", "hooks": [ { "type": "command", "command": "python3 hook.py pre", "timeout": 20 } ] } ],
    "SessionStart": [ { "type": "command", "command": "python3 hook.py log" } ] } }
```

| Stand-in | The hook answers | Stands for |
| --- | --- | --- |
| `./deny-probe.sh` | `deny` | a command refused to every agent |
| `./merge-script.sh` | `deny` when the caller is a helper, else `allow` | a command only the session may run |
| `./oneway-probe.sh` | `ask` | a one-way command that needs the owner |
| `./forceask-probe.sh` | `force_ask` | the same, ignoring earlier grants |
| `./dupg-probe.sh` | `deny_unless_prior_grant` | the same, refused without a stored grant |
| `./rule-probe.sh` | `allow` (a `permissions.deny` rule covers it) | a command refused by a rule, not a hook |
| `./probe.sh`, `./control-probe.sh` | `allow` | controls |

| Run | Command line beyond `agy -p "<prompt>" --model gemini-4-neon-low` | What it did |
| --- | --- | --- |
| P | `agy -p "/hooks"`, `"/agents"`, `"/skills"`, `"/permissions"`, `"/help"` | Prints what the CLI loaded. No model turn, zero tokens, no conversation. |
| A | `--output-format stream-json` | Session and one `self` helper ran the stand-ins; the session messaged the helper a second time. |
| B0 | `--output-format stream-json --settings '{"permissions":{"deny":["command(./rule-probe.sh)"]}}'` | First attempt at B1; stopped early (see question 7). |
| B1 | as B0 | Four helpers at once: three custom agents and one `self` with `Model: flash`, `Workspace: branch`, which started a nested helper. |
| B2 | as B0 plus `--dangerously-skip-permissions` | Session and a custom-agent helper ran every stand-in with prompts off. |
| C | `--conversation <run A id> --output-format json` | A new process continued run A and messaged its old helper. |

Never run: `gh pr merge`, `gh pr ready`, anything outside the two fixture folders.

## 1. Helpers

- **Starting one.** The tool is `invoke_subagent`. Its live schema, as the model printed it in run
  A and as the hook saw its arguments (**observed**): required `TypeName`, `Role`, `Prompt`;
  optional `Model` (`inherit`, `flash_lite`, `flash`, `pro`) and `Workspace` (`inherit`, `branch`,
  `share`). The docs describe a `Subagents` array instead (**read**, `/docs/subagents`,
  `/docs/hooks`); the running tool has no such argument: one call starts one helper.
- **Fresh context.** The helper said it could see no earlier conversation; its transcript starts
  with a system message carrying the parent's prompt (**observed**, run A). The docs: a subagent
  "does not inherit the parent's existing conversation history" (**read**).
- **Types.** Built in: `research`, `browser`, `self` (a copy of the caller's instructions and
  tools) (**read**). Custom: any agent file with `subagent: true`, the default (**observed**).
  `define_subagent` makes a one-off type in the conversation: `Name`, `Description`,
  `SystemPrompt`, `EnableWriteTools`, `EnableSubagentTools`, `EnableMCPTools` (**observed** schema).
- **Two at once.** Four `invoke_subagent` calls in one model turn started four helpers that ran
  together: all four were alive at the same moment (**observed**, run B1, hook timestamps). The call
  returns at once with the helper's conversation id; the helper reports back by `send_message` and
  the parent is woken by that message ("There is no need to poll").
- **How many at once.** No limit **found** in the docs, the changelog or the binary. The string
  "Maximum concurrent direct subagents: 128" in the binary is text in a `/teamwork` prompt, not a
  cap the harness enforces.
- **Depth.** Limit 10 layers below the session (**read**, `/docs/subagents`; the binary has the
  error "maximum subagent nesting depth (%d) exceeded"). Depth 2 ran, and the depth-2 helper still
  had `invoke_subagent` (**observed**, run B1). The limit itself was not hit.
- **Resume.** A helper that has reported is idle. `send_message` with `Recipient` = its
  conversation id woke it with its context: it answered "received 2 messages" (**observed**, run
  A). From a new process, `agy -p ... --conversation <session id>` plus the same `send_message`
  also worked: "received 3 messages", and it named its first command (**observed**, run C).
  `manage_subagents` (`list`, `kill`, `kill_all`) manages them; a killed helper "cannot be
  re-awoken" (**read**; kill not run).
- **Other ways to fan out** (**read**, not run): `/swarm` (a coordinator plus workers on a shared
  board; `swarm add` takes an exact `model`), `/teamwork`, `/boost`, `/run-workflow`. All four
  start from a slash command the user types; the swarm skill is marked
  `disable-model-invocation: true`.

## 2. Role definition files

- **Where** (**read**, `/docs/customization-discovery`; project path **observed**):
  `<workspace>/.agents/agents/<name>.md` or `.../<name>/agent.md`, in the workspace and each parent
  folder up to the repository root; `~/.gemini/config/agents/`; a plugin's `agents/` folder. One
  level deep. `agy agents` or `agy -p "/agents"` lists what loaded.
- **Format.** Markdown; YAML front matter; the body is the system prompt.
- **Fields** (**read**, `/docs/subagents`, plus keys found in the binary): `name` and
  `description` (required), `tools`, `model`, `mainAgent`, `subagent`, `commandExecutionPolicy`
  (`off`, `auto`, `eager`, `sandbox`), `mcpServers`, `skills`, `plugins`, `rules`, `agents`,
  `hooks`, `hidden`, `inheritMcp`, `excludeDefaultComponents`.
- **Exact model: no.** `model` is a tier. A file with `model: gemini-4-hydrogen-low` did not appear
  in `/agents`, with no error on screen; the same file with `model: pro` or `model: flash_lite`
  did (**observed**, run P).
- **Effort: no field.** A file with `effort: low` loaded, and the helper ran at
  `gemini-4-hydrogen-tiered-xhigh` all the same: the key is ignored (**observed**, run B1).
- **What the tiers resolve to on this account** (**observed**, the hook's `modelName`, run B1):

  | Tier | Model the helper ran |
  | --- | --- |
  | `inherit` (default) | the parent's exact id and effort (`gemini-4-neon-low`) |
  | `flash_lite` | `gemini-3.5-flash-lite` |
  | `flash` | `gemini-4-hydrogen-tiered-high` |
  | `pro` | `gemini-4-hydrogen-tiered-xhigh` |

  The mapping depends on how the account signs in: with an API key `pro` is Gemini 4 Argon and
  `flash` is Gemini 3.8 Flash (**read**, CLI changelog 1.5.x). So the only way to put a helper on
  Neon or Carbon is `inherit` from a session started on that model.
- **Value at start against the file.** `invoke_subagent` has `Model`, tiers only; its description
  tells the model to leave it at `inherit` "unless the user explicitly requests a different model"
  (**observed**). Which wins when the call and the file both name a tier: **not observed**.
- **Withholding tools: yes.** A file with `tools: [view_file, run_command]` gave its helper
  `run_command`, `read_file`, `manage_task`, `send_message` and nothing else: no edit tools, no
  `invoke_subagent`, no `define_subagent`. Three helpers reported the same list. A `self` helper
  by contrast listed `write_file`, `edit_file`, `invoke_subagent`, `define_subagent` and `swarm`
  (**observed**, runs A and B1; the lists are the helpers' own reports, no write was attempted).
  Known issue: a misspelled tool name in `tools` "may cause the subagent process to hang"
  (**read**).
- `agy --agent <name>` runs a custom agent as the session itself (**read**).

## 3. Models

`agy models` on this account (**observed**, 2026-11-23):

| Family | Exact ids | Efforts |
| --- | --- | --- |
| Gemini 4 Neon | `gemini-4-neon-low`, `-medium`, `-high`, `-xhigh` | low, medium, high, xhigh |
| Gemini 4 Carbon | `gemini-4-carbon-low`, `-medium`, `-high` | low, medium, high |
| Gemini 4 Argon | `gemini-4-argon-low`, `-medium`, `-high` | low, medium, high |
| Gemini 4 Hydrogen | `gemini-4-hydrogen-low`, `-medium`, `-high`, `-xhigh` | low, medium, high, xhigh |
| Gemini 3.8 Flash | `gemini-3.8-flash-low`, `-medium`, `-high` | low, medium, high |
| Orchestrator | `gemini-pro-orchestrator-neon`, `gemini-pro-orchestrator` (Carbon), `gemini-pro-orchestrator-argon` | fixed; `--effort` does not apply |
| Claude Opus 5.5 | `claude-opus-5-5-low`, `-medium`, `-high` | low, medium, high |
| Claude Sonnet 5.5 | `claude-sonnet-5-5-low`, `-medium`, `-high` | low, medium, high |
| GPT-OSS 120B | `gpt-oss-120b-medium` | medium |

- The effort is the last part of the id. `--effort <level>` on the command line changes it for one
  run; the flag accepts `low`, `medium`, `high`, `xhigh`, `max`, but no model on this account has a
  `max` id (**observed** `agy --help`; **read** `/docs/cli/commands/effort`). The app calls
  `xhigh` "Extra" (**read**, `/docs/models`).
- An unknown `--model` in headless mode exits 1 with `status: ERROR`; it does not fall back
  (**read**, `/docs/cli/headless`).
- Orchestrator pairs a planner (Neon by default, or Carbon, Argon, Claude Opus 5.5) with an
  executor (Hydrogen by default, or Claude Sonnet 5.5) in one conversation (**read**).
- The list depends on the plan: Neon is not on Free or Plus; Carbon is Ultra or Enterprise only;
  Claude Sonnet and Opus 4.6 and GPT-OSS 120B leave on November 30, 2026 (**read**, `/docs/models`).
- Ids seen in hook input but not in `agy models`: `gemini-4-hydrogen-tiered-high`,
  `gemini-4-hydrogen-tiered-xhigh`, `gemini-3.5-flash-lite` (**observed**). They are what the
  tiers resolve to; whether `--model` accepts them was not tried.

### The four Gemini 4 families ranked

By capability, from Google's own wording (**read**):

| Rank | Family | Google's description | Source |
| --- | --- | --- | --- |
| 1 | Carbon | "Our strongest reasoning model"; "Our most capable reasoning model"; thinks "Deliberate"; "escalate to Carbon when Neon at `high` or `xhigh` thinking gets stuck" | Gemini API models, pricing, choosing-a-model |
| 2 | Neon | "Frontier-level intelligence with fast end-to-end task completion"; "deeper reasoning than Hydrogen while finishing faster with fewer output tokens than Carbon"; "the sweet spot between Gemini 4 Carbon ... and Gemini 4 Hydrogen" | choosing-a-model; Antigravity Neon post |
| 2 or 3 | Argon | "Our efficient Gemini 4 frontier reasoning model ... faster responses and lower token spend per turn compared to Gemini 4 Carbon"; "an ideal choice for most advanced engineering and knowledge work" | Gemini API models; Antigravity Carbon post |
| 4 | Hydrogen | "speed and efficiency for everyday coding and agentic workflows"; "Fast and cost-efficient"; suited to "parallel worker subagents" | Gemini API models, choosing-a-model |

Carbon above Neon above Hydrogen is stated outright. A direct Neon against Argon ranking was
**not found**: Google's choosing-a-model page compares Carbon, Neon and Hydrogen and leaves Argon
out. Argon is the oldest of the four (Oct 13, 2026), Neon the newest (Nov 18).

By list price, Gemini API paid tier, USD per 1M tokens, standard mode (**read**,
`https://ai.google.dev/gemini-api/docs/pricing`, 2026-11-23):

| Family | Input | Output (thinking included) | Note |
| --- | --- | --- | --- |
| Carbon | $4.00 | $20.00 | $2.00 and $10.00 through November 30, 2026 |
| Argon | $4.00 | $20.00 | $2.00 and $10.00 through November 30, 2026 |
| Neon | $3.00 | $15.00 | no promotional price |
| Hydrogen | $1.50 | $7.50 | also has a free tier |

From December 1, 2026 the order is Carbon = Argon, then Neon, then Hydrogen. Until then Neon is
the dearest per token. Google also says Neon at `high` shows "a 32% lower cost per task than
Carbon" (**read**, Neon post). Inside an Antigravity plan nothing is billed per token: models draw
on a quota, and list price applies only with Pay As You Go or an API key (**read**, `/docs/plans`,
`/docs/pay-as-you-go`).

The three levels to use:

| Level | Family | Ids | Why |
| --- | --- | --- | --- |
| Strongest | Carbon | `gemini-4-carbon-{low,medium,high}` | Google names it the strongest, and prices it highest from December 1. |
| Middle | Neon | `gemini-4-neon-{low,medium,high,xhigh}` | Stated to sit between Carbon and Hydrogen in reasoning and in price; Antigravity's default. |
| Cheapest | Hydrogen | `gemini-4-hydrogen-{low,medium,high,xhigh}` | Lowest price, half of Neon's; the model Google names for worker subagents, and what the `flash` and `pro` helper tiers ran on here. |

Argon is left out because it costs the same as Carbon while Google describes it as Carbon's
lighter sibling, so it adds no rung of its own. One limit on the choice: Carbon is not offered on
Google AI Pro, so there the strongest available is Neon or Argon.

Thinking levels each family accepts in Antigravity are the efforts in the first table
(**observed**), and they match the Gemini API's table: Carbon and Argon `low`, `medium`, `high`;
Neon and Hydrogen add `xhigh` (**read**, Gemini API thinking page). The default differs by
product: Antigravity says Medium for all four, the API says `high` for Neon and Hydrogen
(**read**).

## 4. Working directory

- `invoke_subagent` `Workspace` (**observed** schema): `inherit` (default, the parent's
  directory), `branch` ("a new isolated workspace branched or cloned from the parent"), `share`
  ("a new workspace sharing the parent's underlying repository directory ... similar to a git
  worktree").
- `branch` **observed** (run B1): `git worktree list` in the helper showed a second worktree at
  `~/.gemini/antigravity-cli/worktrees/<session conversation id>/subagent-<Role>-<type>-<hash>`,
  on a new branch of the same name cut from the parent's HEAD. Untracked files in the parent
  folder were copied into it. A nested helper with `inherit` ran in that same worktree. The
  worktree and its branch were still there after the run ended; the docs say they are removed when
  the helper is killed (**read**).
- `share` was not run.
- **A directory the caller names: no.** Nothing in `invoke_subagent`, `define_subagent` or the
  agent file takes a path (**observed** schemas; **not found** elsewhere). The nearest things: the
  helper's `run_command` has a `Cwd` argument (**read**, `/docs/hooks`), so a prompt can tell it to
  work in a path; the session takes `--add-dir` (**observed**, `agy --help`); and a separate
  `agy -p` process started inside a worktree uses that worktree as its workspace (**observed**,
  every run reported the start folder as `cwd`).

## 5. Skills and run rules

- **Where skills are looked for** (**read**, `/docs/skills`, `/docs/customization-discovery`):
  `<workspace>/.agents/skills/<name>/SKILL.md` and the same in each parent folder up to the
  repository root; `~/.gemini/config/skills/<name>/` (shared with the app); a plugin's `skills/`;
  CLI only, `~/.gemini/antigravity-cli/skills/` and `~/.gemini/skills/`; a `skills.json` manifest
  for other paths inside the repository. One level deep. Front matter: `description` required,
  `name` optional (defaults to the folder name). Each skill is also a slash command.
- **On this machine** (**observed**, `agy -p "/skills" --output-format json`): 109 skills, 102 from
  `~/.gemini/config/skills/` and 7 built in. The 102 are symlinks into `~/.agents/skills/`. None
  came from `~/.claude/skills/` or straight from `~/.agents/skills/`: neither is a search path.
  The binary mentions `~/.claude/skills` only in a one-time import table (`agy plugin import
  claude`, the `migrate-agent-settings` skill).
- **`AGENTS.md`, session: loaded unprompted** (**observed**, run A: the session gave the codeword).
  Read from the workspace folder and each parent up to the repository root, as `AGENTS.md`,
  `GEMINI.md`, `.agents/AGENTS.md` or `.agents/rules/*.md`; globally from `~/.gemini/AGENTS.md`,
  `~/.gemini/GEMINI.md` and `~/.gemini/config/`. Not from folders below the workspace. Limits:
  24,000 bytes a file, 20,000 tokens in total (**read**, `/docs/rules`).
- **`AGENTS.md`, helper: loaded unprompted** (**observed**: a `self` helper in run A and a
  custom-agent helper in run B1 each gave the codeword, which was not in their prompts).
- **`CLAUDE.md`: not read** (**not found** in the docs; the binary names it only as a file to
  protect from edits and in the import table). This repository's `CLAUDE.md` is a one-line
  `@AGENTS.md`, so nothing is lost. Inside a rule file `@name` only rewrites a path; `@[label](path)`
  inlines the file (**read**).
- The workspace-trust question the CLI asks interactively did not gate anything headless: hooks,
  agents and `AGENTS.md` all loaded in a folder that is not in `trustedWorkspaces` (**observed**).

## 6. Detection

A command started by the agent's `run_command` gets these (**observed**, `probe.sh`, runs A and B1):

| Variable | Value seen |
| --- | --- |
| `ANTIGRAVITY_AGENT` | `1` |
| `ANTIGRAVITY_CONVERSATION_ID` | the conversation id of the agent that ran the command |
| `ANTIGRAVITY_TRAJECTORY_ID` | another id, different per agent |
| `ANTIGRAVITY_PROJECT_ID` | `default-cli-project` |
| `ANTIGRAVITY_APP_DATA_DIR` | `~/.gemini/antigravity-cli` (the app and the IDE use other folders, **read**) |
| `ANTIGRAVITY_LS_VERSION` | `cli-1.5.15` |
| `ANTIGRAVITY_LS_ADDRESS`, `ANTIGRAVITY_CSRF_TOKEN` | address and token of the local agent API |
| `ANTIGRAVITY_AGENTAPI_EXE` | path of `agy` |
| `ANTIGRAVITY_SOURCE_METADATA` | JSON with the conversation id, step index and the tool call |

- Test `ANTIGRAVITY_AGENT`. A helper's command gets the same ten names; only the ids differ, so
  no variable says "helper" (**observed**).
- The parent shell's variables pass through. These runs were started from Claude Code, so
  `CLAUDECODE=1` and `AI_AGENT=claude-code_...` were present inside Antigravity's commands too. A
  script that checks for Claude Code first will misjudge a run launched this way: check
  `ANTIGRAVITY_AGENT` first (**observed**).
- A hook process gets only `ANTIGRAVITY_CONVERSATION_ID` of the ten (**observed**).

## 7. Guards

**The hook route.** `.agents/hooks.json` in the workspace, `~/.gemini/config/hooks.json`, or a
plugin (**read**, `/docs/hooks`). Top-level keys are hook names; under each, event names. Events:
`SessionStart`, `PreInvocation`, `PreToolUse`, `PostToolUse`, `PostInvocation`, `Stop`. A
`PreToolUse` handler gets JSON on stdin (`toolCall.name`, `toolCall.args`, `conversationId`,
`transcriptPath`, `artifactDirectoryPath`, `workspacePaths`, `modelName`, `lastUserInput`,
`stepIdx`, `cwd`) and prints `{"decision": ..., "reason": ...}`. It runs with the folder that
holds `hooks.json` as its working directory.

What each decision did (**observed**; "ran" means the marker file was written):

| Hook answers | Headless, default | Headless, `--dangerously-skip-permissions` |
| --- | --- | --- |
| `allow` | ran | ran |
| `deny` | refused: "tool call denied by pre-tool hook: <reason>" | refused, same text |
| `deny_unless_prior_grant` | refused: "Permission denied ... <reason>" | refused, same text |
| `ask` | **ran**, no notice | **ran** |
| `force_ask` | refused as "user denied permission"; the run then ended with an empty response, exit 0, `denied_actions` in the result and a notice on stderr | **ran** |
| `{}` (no decision) | refused: "tool call denied by pre-tool hook:" | not run |
| `permissions.deny` rule, hook says `allow` | refused: "Matches user-configured deny rule." | refused, same text |

- **Refusing to the session and to a helper, prompts off: yes.** The same hook fired for every
  tool call of the session, of each helper and of the nested helper, and `deny` held in both modes
  (**observed**, runs A, B1, B2). Headless default reports `permission_mode: request-review` and
  runs commands through an automatic reviewer; `--dangerously-skip-permissions` reports
  `always-proceed`.
- **Telling a helper from the session.** No field in the hook input or the environment says so
  (**observed**: same keys for both). Two tests that worked:
  1. When a helper is started, its parent writes
     `<artifactDirectoryPath of the parent>/.system_generated/subagents/<helper conversation id>.json`.
     The hook globs `<dirname of its own artifactDirectoryPath>/*/.system_generated/subagents/<conversationId>.json`:
     a match means helper. With this, `./merge-script.sh` ran for the session and was refused to a
     depth-1 helper in both modes, and the file was there for the depth-2 helper too (**observed**,
     runs B1, B2).
  2. `lastUserInput` was `""` in every helper event and the prompt text in every session event
     (**observed**). Weaker: the docs let a user message a helper directly in the terminal UI.

  Neither is documented, so either can change with a release.
- **Waiting for the owner.** The docs: `ask` is to "Prompt the user for permission", `force_ask`
  to "Always prompt the user, ignoring cached permissions", and a helper's request "automatically
  bubbles up to the main UI" (**read**). That is an interactive session, which was not driven
  here, so the wait itself is **not observed**. Without a person the result is in the table: `ask`
  lets the command run. A guard that must hold with prompts off has to answer `deny`.
- **The rule route.** `permissions.deny` entries such as `command(gh pr merge)` in
  `~/.gemini/antigravity-cli/settings.json`, in project or shared scope through `/permissions`, or
  for one run through `--settings '<json>'`. Deny beats ask beats allow, and "Deny rules apply in
  every mode" (**read**, `/docs/permissions`). A rule passed with `--settings` refused the command
  to the session and to a helper in both modes (**observed**). A rule cannot tell a helper from
  the session. Matching is by command prefix, and a line with shell constructs that could hide a
  command is not prefix-matched (**read**).
- **Two traps.** A `PreToolUse` hook must print an explicit `allow`: `{}` refuses the call. A
  malformed `hooks.json` is skipped with a line in the CLI log and nothing on screen, leaving no
  guard at all; `agy -p "/hooks"` shows what loaded (**observed**, runs P and B0).
- In a `branch` helper both the worktree's copy of `hooks.json` and the parent workspace's fired,
  so each tool call was checked twice (**observed**, run B1).

## 8. Token records

| Source | Grain | Fields | Mark |
| --- | --- | --- | --- |
| `agy -p --output-format json`, `.usage` | the run (one conversation, all turns so far) | `input_tokens`, `output_tokens`, `thinking_tokens`, `cache_read_tokens`, `total_tokens`; beside it `conversation_id`, `num_turns`, `duration_seconds` | observed |
| `--output-format stream-json`, `step_update.usage` | one model request | same five fields | observed |
| `<app data dir>/brain/<conversation id>/.system_generated/logs/transcript.jsonl` | one model request (`type: PLANNER_RESPONSE`) | `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `created_at`, `step_index` | observed |
| Status line JSON | the conversation so far | `context_window.total_input_tokens`, `total_output_tokens` | read |
| `conversations/<id>.db` | SQLite, protobuf blobs | not readable as plain columns | observed |
| `/usage`, `/credits` | account | quota and credits, no token counts | read |

- The three per-request sources agree: the transcript's sums for run A's session (input 31,545,
  output 2,926, cache read 98,251) equal the run's `usage` (**observed**). `total_tokens` is
  input plus output; thinking is inside output; the transcript has no separate thinking count.
- **A helper's tokens are not in the parent's total.** Run A's helper used input 30,806, output
  1,086 by its own transcript, and none of it is in the run's `usage`. The stream carries only the
  parent's steps. To cost a run, add each helper's transcript; the ids come from the
  `subagent_info` step in the stream or from the parent's `subagents/` folder (**observed**).
- With `--conversation`, `usage` and `num_turns` count the whole conversation, not the new turn
  (**observed**, run C).
- No cost in any of them (**not found**).

## 9. A terminal entry point

`agy` is that entry point (**observed** unless marked):

| Need | How |
| --- | --- |
| Start a run with a task | `agy -p "<task>"` from the folder to work in. Useful flags: `--model <id>`, `--effort`, `--agent <name>`, `--mode (accept-edits, auto, plan)`, `--add-dir`, `--settings '<json or path>'`, `--print-timeout 15m`, `--sandbox`, `--json-schema`. |
| Know it has finished | The process exits when the turn ends. Exit 0 with `status: SUCCESS`; non-zero and `ERROR` on failure (**read**). The parent waits for its helpers' reports before finishing if the prompt says to. |
| Read the result | `--output-format json`: one object with `response`, `status`, `conversation_id`, `usage`, and `denied_actions` when something was refused. `stream-json`: an `init` event (model, tools, `permission_mode`), `step_update` events, one `result`. Diagnostics go to stderr. |
| Continue it | `--conversation <id>` or `--continue`. |
| Several turns, one process | `--input-format stream-json`, one `{"event":"user",...}` line per turn on stdin (**read**, `/docs/cli/headless`). |
| Sign-in | Uses the cached sign-in. Not signed in and no terminal: exits with `authentication required` (**read**). |

- A refused action does not fail the run: exit 0, `status: SUCCESS`, a line on stderr. Check
  `denied_actions` and the response text, not the exit code.
- Other routes (**read**, not run): `agy acp` (Agent Client Protocol over stdio), the Python SDK
  (`pip install google-antigravity`), and the local HTTP `ConversationService` that an agent's own
  commands can reach through `ANTIGRAVITY_LS_ADDRESS`.

## What follows for the adapter

- A helper's model: choose a tier, or start the session on the wanted model and let helpers
  inherit. For an exact model per helper, start a separate `agy -p --model <id>` process instead.
- A helper in a chosen worktree: start a separate `agy -p` process in it, or accept the worktree
  Antigravity makes with `Workspace: branch`.
- Guards: one `PreToolUse` hook answering `deny`, with the parent-file test for helper-only rules,
  plus a `permissions.deny` rule as a second line. Do not rely on `ask`.
- Skills must be linked or copied into `.agents/skills/` or `~/.gemini/config/skills/`.
- Token totals must add the helpers' transcripts to the run's `usage`.

## Side effects of the runs

Under the home directory, all written by `agy` itself inside `~/.gemini/antigravity-cli/`:

- One conversation database, one `brain/<id>/` folder and one `presence/` lock for each session
  and helper (eleven conversations), new files in `log/`, lines added to `history.jsonl`, updates
  to `cache/`, `conversation_summaries.db`, `bin/agentapi` and `~/.gemini/sandbox/profiles`.
  Five more conversations appeared in the same folder during the session; another `agy` session
  was live on the machine, and these could not be attributed.
- One git worktree left behind by run B1:
  `~/.gemini/antigravity-cli/worktrees/5c34f218-0e14-40b6-81e6-5aac6787663f/subagent-Branch-Self-Probe-self-06439db3`.
  It belongs to the scratch repository, not to this one. It was left in place.
- `settings.json` there was rewritten during the session and now holds a `title` hook and
  `allowNonWorkspaceAccess`, with a `settings.json.bak` beside it. The timestamps (18:21 to 18:23)
  and the hook's name point at another program on the machine, not at these runs, which passed no
  such settings; `trustedWorkspaces` is unchanged. This was not proven either way.

## Left unverified

| Open point | Smallest test |
| --- | --- |
| The owner-wait in an interactive session, for the session and for a helper | In the terminal UI, run the fixture's `./oneway-probe.sh` from the session and from a helper; see whether a prompt appears and blocks. |
| `ask` in headless with `--mode accept-edits` or `--mode plan` (only the default was run) | Rerun run A's last step with each mode. |
| Call `Model` against the file's `model` | Start a `flash` agent file with `Model: pro`; read `modelName` in the hook log. |
| A cap on helpers at once; the depth limit of 10 | Start 20 `self` helpers in one turn; chain helpers until one refuses. |
| `Workspace: share`; cleanup of a `branch` worktree on kill | One helper with `share`; `manage_subagents kill` on a `branch` helper, then `git worktree list`. |
| Whether a withheld tool is truly absent, not just unlisted | Ask the `reader` helper to write a file and watch for the tool call in the hook log. |
| Hooks and helpers in the app and the IDE (only the CLI was run) | Repeat run A from the app's agent panel. |
| Whether the tier ids (`gemini-4-hydrogen-tiered-high`) work with `--model` | `agy -p "hi" --model gemini-4-hydrogen-tiered-high`. |
| A direct Neon against Argon capability ranking from Google | Not found in the pages read; check the model cards at `ai.google.dev/gemini-api/docs/models/gemini-4-argon`. |
| `/swarm`, `/teamwork`, `/run-workflow`, `agy acp`, the SDK | Read only. |
