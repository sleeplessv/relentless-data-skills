# What each harness's guards can do: refusing a command, telling a helper from the session, and the owner's prompt

Research date: 2026-11-23. Resolves ticket #213. Issue 178 decided three guards:

- **a.** A raw `gh pr merge` or `gh pr ready` is refused to every agent.
- **b.** The merge script is refused to a helper and allowed to the session the owner started.
- **c.** A command on the one-way list waits for the owner's answer. When prompts are switched
  off the hook refuses, and the agent stops and returns the question.

This note says, for Claude Code, Cortex Code, Codex and Cursor, whether the harness can supply
each guard, and what an adapter has to do where it cannot.

Every claim carries one of four marks:

- **read**: quoted from the vendor's docs or source, with the URL. All pages were fetched on
  2026-11-23.
- **observed**: seen in a run on this machine, with the run name. Every command under test was
  a stand-in that prints a line. No real `gh pr merge`, `gh pr ready` or push ran. The two
  literal `gh pr merge 99999` / `gh pr ready 99999` commands were refused by the hook before
  they started, in directories with no remote.
- **inferred**: a conclusion drawn from read or observed facts. No test has confirmed it.
- **not found**: looked for in the docs, the binary or a run, and not there.

## Answer

A hook that **refuses** works on all four harnesses, for the session and for helpers, and it
holds when prompts are switched off. A hook that **asks** is safe only on Claude Code. On the
other three the command can run with nobody asked:

| Harness | What happened when the hook answered "ask" and prompts were off | Mark |
|---|---|---|
| Claude Code 2.1.330 | Refused in every mode, for the session and for a helper. With something able to answer, the question reached it in every mode, bypass included. | observed |
| Cortex Code 1.2.46 | Session: refused. **Helper under `--bypass`: the command ran**, foreground and background. | observed |
| Codex 0.171.0 | **The command ran.** The docs say "ask" is not supported and the call continues. | read and observed |
| Cursor CLI 2026.11.22 | Without `--force`: refused. **With `--force`: the command ran**, for the session, a helper and a background helper. | observed |

So one hook can supply all three guards on every harness only if the hook itself turns "ask"
into "refuse" whenever it cannot be sure a person will be asked. The table below is the result
with that rule applied.

| Guard | Claude Code | Cortex Code | Codex | Cursor |
|---|---|---|---|---|
| **a.** refuse raw `gh pr merge` / `gh pr ready` to all | **Supplied.** observed | **Supplied**, holds under `--bypass`. observed | **Supplied** by a hook (observed) or a `forbidden` rule (read, checked offline). The hook needs the owner's one-time trust review. | **Supplied** by a hook, and separately by a `permissions.deny` entry. Both hold under `--force`. observed |
| **b.** refuse the merge script to a helper only | **Supplied.** Key on `agent_id`. observed | **Supplied.** Key on `agent_id`. observed, but the field is not in the docs | **Supplied.** Key on `agent_id`. observed, and in the source schema, but not on the docs page | **Partly.** No field marks a helper. A workaround that records session IDs at `sessionStart` worked in one run. Fallback: the text rule, and preflight warns. |
| **c.** one-way command waits for the owner | **Supplied.** "ask" prompts when someone can answer and refuses when nobody can. The terminal prompt itself was not observed. | **Partly.** "ask" is refused for a headless session but runs for a helper under `--bypass`. The hook must refuse when `permission_mode` is `bypassPermissions` or the caller is a helper. | **Not by a hook**: it can only refuse. A `prompt` rule can wait (read), is refused when approvals are off (read in source), and on this machine goes to the auto-reviewer, not the owner. Not run live. | **Partly.** "ask" is refused in print mode and ignored under `--force`, and the hook input does not say which mode is on. The hook must refuse. The owner is never asked by this route when Run Everything is on. |

Three more facts the adapters need:

- **Claude Code: a hook in a skill's own file never fires inside a helper.** It fires only for
  the session. A hook in a settings file or in a plugin's `hooks/hooks.json` fires in both.
  (observed)
- **Claude Code: tell a helper by `agent_id`, not `agent_type`.** A session started with
  `--agent` carries `agent_type` and no `agent_id`. (observed)
- **A helper's definition file can withhold the edit and spawn tools on Cortex Code only**
  among the three non-Claude harnesses. Codex cannot. Cursor has one all-or-nothing `readonly`
  switch.

Four results differ from the docs:

1. Cortex Code's docs show no agent fields in the hook input. A helper's call carries five.
2. Codex's docs list `agent_id` and `agent_type` for other events only. They arrive on
   `PreToolUse` for a helper.
3. Claude Code's docs say `dontAsk` mode "Auto-denies every call that would otherwise prompt".
   With a permission host attached, a hook's "ask" still reached the host and the command ran
   on its "allow".
4. Cursor's docs list a `subagentStart` hook. It did not fire in seven CLI print-mode runs
   that started a subagent.

## Sources and versions

| Source | Version or date | How it was used |
|---|---|---|
| Claude Code docs: [hooks](https://code.claude.com/docs/en/hooks), [permission-modes](https://code.claude.com/docs/en/permission-modes), [permissions](https://code.claude.com/docs/en/permissions), [sub-agents](https://code.claude.com/docs/en/sub-agents), [headless](https://code.claude.com/docs/en/headless), [plugins-reference](https://code.claude.com/docs/en/plugins-reference) | fetched 2026-11-23 | hook input fields, where hooks run, what "ask" does, modes |
| Claude Code CLI | `claude --version`: `2.1.330 (Claude Code)` | 26 headless runs, model alias `haiku` |
| Cortex Code docs: [extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility), [security](https://docs.snowflake.com/en/user-guide/cortex-code/security), [tools](https://docs.snowflake.com/en/user-guide/cortex-code/tools), [cli-reference](https://docs.snowflake.com/en/user-guide/cortex-code/cli-reference), [settings](https://docs.snowflake.com/en/user-guide/cortex-code/settings) | fetched 2026-11-23. The `hooks` and `permissions` pages return 404. | hook events and locations, modes, batch mode, agent `tools:` list |
| Cortex Code CLI | `cortex --version`: `Cortex Code v1.2.46`, build `1.2.46+175654.6f8561fd271f` | 10 headless runs, model `claude-haiku-4-5`; text strings in the binary |
| Codex docs: [hooks](https://learn.chatgpt.com/docs/hooks), [rules](https://learn.chatgpt.com/docs/agent-configuration/rules), [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), [agent-approvals-security](https://learn.chatgpt.com/docs/agent-approvals-security), [config-reference](https://learn.chatgpt.com/docs/config-file/config-reference), [non-interactive-mode](https://learn.chatgpt.com/docs/non-interactive-mode) | fetched 2026-11-23. `developers.openai.com/codex/<page>` redirects to these. | hook decisions, rule decisions, approvals, custom agents |
| Codex source, tag [`rust-v0.171.0`](https://github.com/openai/codex/tree/rust-v0.171.0) | `codex-rs/hooks/schema/generated/pre-tool-use.command.input.schema.json`, `codex-rs/core/src/exec_policy.rs`, `codex-rs/execpolicy/src/decision.rs`, `codex-rs/core/src/agent/role.rs` | hook input schema, how a `prompt` rule is treated, what an agent file can switch off |
| Codex CLI | `codex --version`: `codex-cli 0.171.0` | 9 `codex exec` runs, model `gpt-6-luna`; `codex execpolicy check` |
| Cursor docs: [hooks](https://cursor.com/docs/hooks), [third-party-hooks](https://cursor.com/docs/reference/third-party-hooks), [subagents](https://cursor.com/docs/subagents), [run-modes](https://cursor.com/docs/agent/security/run-modes), [cli/headless](https://cursor.com/docs/cli/headless), [cli/reference/permissions](https://cursor.com/docs/cli/reference/permissions), [cli/reference/parameters](https://cursor.com/docs/cli/reference/parameters), [cli/changelog](https://cursor.com/docs/cli/changelog) | fetched 2026-11-23 | hook events and outputs, run modes, CLI flags, subagent file fields |
| Cursor CLI | `cursor-agent --version`: `2026.11.22-e9042b2`. It was `2025.09.12-4852336` at the start of the session: the first run made the CLI update itself. See [Side findings](#side-findings). | 12 print-mode runs, model Auto |
| Cursor desktop app | `cursor --version`: `3.31.15` | **not driven**. Every Cursor observation is from the CLI. |

All runs were headless. A headless run cannot show a terminal prompt, so "the prompt is shown"
is nowhere observed directly. For Claude Code a stand-in owner answered through
`--permission-prompt-tool`, which shows whether the question is asked at all.

## How the runs were made

One directory per harness, each with its own `git init`, no remote, and project-level config
only. No user-level file was edited. The hook under test writes the JSON it receives to
`logs/hook.jsonl`, then decides:

```python
cmd = (data.get("tool_input") or {}).get("command", "") or ""
is_helper = "agent_id" in data
if "gh pr merge" in cmd or "gh pr ready" in cmd:
    out("deny", "GUARD-A: raw gh pr merge/ready is refused to every agent")
if "merge-script.sh" in cmd and is_helper:
    out("deny", "GUARD-B: the merge script is refused to a helper")
if "oneway-probe" in cmd:
    out("ask", "GUARD-C: one-way command, needs the owner's answer")
```

Stand-ins: `merge-script.sh` prints `MERGE-SCRIPT-RAN`; `oneway-probe.sh <tag>` and
`control-probe.sh <tag>` print a line and create `logs/oneway-ran-<tag>.marker`. A marker file
is the proof that a command ran. The control probe matches no guard and shows that a refusal
came from the hook and not from the mode.

## Claude Code

### Fact 1. Are `agent_id` and `agent_type` both absent when the session makes the call?

**Yes. A hook can refuse helpers only.** observed

- Run `f1-session-and-helper`: the session's `PreToolUse` input had the keys `session_id`,
  `transcript_path`, `cwd`, `prompt_id`, `permission_mode`, `effort`, `hook_event_name`,
  `tool_name`, `tool_input`, `tool_use_id`. The helper's call had the same keys plus
  `agent_id` (`"ab79c9399287ab2b9"`) and `agent_type` (`"helper"`).
- Run `f1b-agent-flag`: with `claude --agent helper`, the session's own call carried
  `agent_type: "helper"` and **no** `agent_id`. A guard keyed on `agent_type` would refuse the
  owner's session. Key on `agent_id`.
- Run `g-ab`, both guards in one run: the session's `gh pr merge 99999` was refused
  (GUARD-A), the session's `./merge-script.sh` ran, the helper's `./merge-script.sh` was
  refused (GUARD-B), the helper's `gh pr ready 99999` was refused (GUARD-A).

The docs agree. read, [hooks](https://code.claude.com/docs/en/hooks):

> `agent_id` | Unique identifier for the subagent or in-process teammate the hook fires in.

> `agent_type` | ... Present when the session uses `--agent` or the hook fires inside a subagent.

### Fact 2. Does a hook declared in a skill's own file fire inside helpers?

**No. It fires for the session only.** A settings-file hook and a plugin `hooks/hooks.json`
hook fire in both. observed

| Where the hook is declared | Fires on the session's calls | Fires on a helper's calls | Run |
|---|---|---|---|
| Project `.claude/settings.json` | yes | yes, with `agent_id` and `agent_type` | every run |
| Plugin `hooks/hooks.json` | yes | yes | `p1-plugin` |
| Skill frontmatter, the session invoked the skill, then started a helper | yes | **no** | `s1-session-loads-skill`, `s1r` |
| Skill frontmatter, the helper invoked the skill | yes, on the session's later call | **no**, not even on the helper's own calls | `s2-helper-loads-skill`, `s2r` |
| Skill frontmatter, skill preloaded through the agent's `skills:` field | n/a, the session made no call | **no** | `s3-helper-preloaded-skill` |
| Frontmatter of a skill shipped in a plugin | yes | **no** | `p1-plugin` |
| The helper's own agent frontmatter | n/a | **no** under `-p` in a folder nobody has trusted | `a1-agent-frontmatter` |

The docs say the first two rows and explain the last. read,
[hooks](https://code.claude.com/docs/en/hooks):

> Hooks from settings files, managed policy settings, and plugins also run inside subagents.
> When a subagent calls a tool, tool events such as `PreToolUse` and `PostToolUse` fire the
> same configured hooks as in the main conversation, and the input carries the `agent_id` and
> `agent_type` common input fields that identify the subagent.

> Frontmatter hooks in a project subagent run only after you accept the workspace trust dialog
> for the folder the agent file came from. A `-p` session doesn't count as accepting it.

The docs do not say that a skill's frontmatter hook stays out of helpers; the runs show it.
Agent frontmatter in a trusted folder was not tested. A plugin cannot use that route anyway.
read, [plugins-reference](https://code.claude.com/docs/en/plugins-reference):

> For security reasons, plugin subagents don't support the `hooks`, `mcpServers`, or
> `permissionMode` frontmatter fields.

### Fact 3. A hook asks for the owner's answer and prompts are switched off

**With nobody able to answer, the call is refused and the command does not run, in every
mode. With something able to answer, the question is asked in every mode, bypass included.**
observed

Nobody to answer (plain `claude -p`):

| Mode | Caller | Result | Run |
|---|---|---|---|
| default | session | refused, no marker | `m-default` |
| default | helper | refused, no marker | `m-default-helper` |
| `acceptEdits` | session | refused, no marker | `m-acceptedits` |
| `auto` | session | refused, no marker | `m-auto` |
| `dontAsk` | session | refused, no marker | `m-dontask` |
| `bypassPermissions` | session | refused, no marker | `m-bypass` |
| `bypassPermissions` | helper | refused, no marker | `m-bypass-helper` |
| `--dangerously-skip-permissions` | session | refused, no marker | `m-skipflag` |
| `--permission-prompts none` | session | refused, no marker | `m-promptsnone` |
| `bypassPermissions`, control probe | session | ran | `c-bypass-control` |

The tool result the agent received was the hook's own reason, "GUARD-C: one-way command, needs
the owner's answer", so the agent can return the question. Under `--permission-prompts none`
the text was instead a generic "Permission for this tool use was denied" line.

A stand-in owner attached with `--permission-prompt-tool`:

| Mode | Caller | Owner answered | Result | Run |
|---|---|---|---|---|
| default | session | allow | asked, ran | `o-default-allow` |
| `auto` | session | allow | asked, ran | `o-auto-allow` |
| `dontAsk` | session | allow | asked, ran | `o-dontask-allow` |
| `bypassPermissions` | session | allow | asked, ran | `o-bypass-allow` |
| `bypassPermissions` | session | deny | asked, refused | `o-bypass-deny` |
| `bypassPermissions` | helper | allow | asked, ran | `o-bypass-helper-allow` |

So bypass mode does not swallow a hook's "ask". The hook input carries `permission_mode`
(`default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions` were all seen, inside helpers
too), so a hook can also refuse outright when it sees prompts off.

What the docs say. read, [hooks](https://code.claude.com/docs/en/hooks):

> `"ask"` prompts the user to confirm.

> When Claude Code denies the call in a `-p` run where no one can answer that prompt, Claude
> reads the reason in the tool result instead.

> In auto mode, a PreToolUse hook's `"ask"` normally sends the tool call to the permission
> prompt, and the classifier doesn't decide it.

read, [sub-agents](https://code.claude.com/docs/en/sub-agents):

> When a background subagent reaches a tool call that needs permission, Claude Code surfaces
> the prompt in your main session and names the subagent that is asking.

The [permission-modes](https://code.claude.com/docs/en/permission-modes) list "Actions no mode
auto-approves" names "Tools matched by an explicit ask rule" and does not name a hook's "ask".
The runs show a hook's "ask" behaves the same way. The `dontAsk` row contradicts
[permissions](https://code.claude.com/docs/en/permissions) ("Auto-denies every call that would
otherwise prompt"): with a permission host the question was asked.

**Not observed:** the terminal prompt in an interactive session running in bypass or auto
mode. The six host runs make it likely the prompt is shown (inferred). The test is in
[Open](#open-with-the-smallest-test).

## Cortex Code

### 1. Can something inspect a shell command before it runs and refuse it? Where is it configured?

**Yes, a `PreToolUse` hook.** read and observed

read, [extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility): the
hook events table lists "PreToolUse | Before tool execution | Yes" under "Can block", and gives
the locations, highest priority first:

> Local | `.claude/settings.local.json` or `.cortex/settings.local.json` | Project |
> `.claude/settings.json` or `.cortex/settings.json` | User | `~/.claude/settings.json` |
> Global | `~/.snowflake/cortex/hooks.json`

The [security](https://docs.snowflake.com/en/user-guide/cortex-code/security) page adds
`~/.snowflake/cortex/settings.json`. The changelog says project settings are read from
`.cortex/settings.json` only ("Cortex Code no longer reads `.claude/settings.json` as project
settings"), which conflicts with the table above; the runs used `.cortex/settings.json`.

observed, run `x2-guards-ab`, under `--bypass`: the session's `gh pr merge 99999` and the
helper's `gh pr ready 99999` were both refused with "[Hook] Blocked: GUARD-A ...". The project
hook ran with no trust step. The matcher `bash` matched, and the hook input's `tool_name` was
`"Bash"`.

Other levers, read: `--disallowed-tools` removes a tool from a run, `--allowed-tools`
pre-approves one, and managed `permissions.deny` patterns match on a command's first token.
None can tell `gh pr merge` from `gh pr view`, so the hook is the lever for guard a.

### 2. Can it tell a helper from the session the owner started?

**Yes, by `agent_id`. The docs do not say so.** observed

Run `x1-session-and-helper`: the session's hook input had no agent fields. The helper's had
`agent_id`, `agent_type` (`"helper"`), `parent_session_id`, `parent_thread_message_id` and
`agent_transcript_path`. The hook's environment differed too: `CORTEX_SESSION_ID` was the
helper's ID while `CORTEX_TASK_CONTEXT_ID` stayed the session's. The binary has the code that
builds these fields, with one more that the run did not show, `parent_thread_id`.

Run `x2-guards-ab`, under `--bypass`: the session's `./merge-script.sh` ran and the helper's
was refused with "[Hook] Blocked: GUARD-B ...".

The sample hook input on the extensibility page shows none of these fields (not found in the
docs). An undocumented field can change without notice, so preflight should check it.

### 3. Can it make a command wait for the owner's answer?

**Only for a session. A helper under `--bypass` runs the command.** observed

The hook's `permissionDecision: "ask"` is understood: the binary carries the verdict
"Approval required by a PreToolUse hook." The docs do not mention it (not found).

| Mode | Caller | Result | Run |
|---|---|---|---|
| default, `--allowed-tools bash` | session | "Auto-denied (non-interactive mode)", no marker | `x3-ask-default` |
| default | helper | auto-denied, no marker | `x8-ask-default-helper` |
| `--bypass` | session | "Auto-denied (non-interactive mode)", no marker | `x4-ask-bypass` |
| `--bypass` | **helper, foreground** | **ran**, marker created | `x5-ask-bypass-helper` |
| `--bypass` | **helper, background** | **ran**, marker created | `x6-ask-bypass-bghelper` |
| `--bypass`, control probe | session | ran | `x7-control-bypass` |

The owner's `cortex` is aliased to `cortex --bypass`, so the two bold rows are the normal
case. The hook input carries `permission_mode` (`default` and `bypassPermissions` were seen)
and `agent_id`, so the hook can refuse where it would otherwise ask.

read, [cli-reference](https://docs.snowflake.com/en/user-guide/cortex-code/cli-reference):

> Bypass mode approves every tool call without prompting you first.

read, [tools](https://docs.snowflake.com/en/user-guide/cortex-code/tools):

> In batch mode (`cortex -p` or `cortex exec`), there's no interactive prompt, so CoCo can't
> ask you to approve a tool call. A tool call that isn't pre-approved is denied, and CoCo
> continues without it.

read, [extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility):
"Agents inherit session permissions", and an autonomous agent "Never blocks for questions".

**Not observed:** an interactive session, in either mode. Whether an interactive `--bypass`
session shows the prompt for a hook's "ask" or runs the command is open.

### 4. Can a helper's definition file withhold the edit tools and the tool that starts helpers?

**Yes.** read and observed

read, [extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility):

> Tool names in a `tools:` list are the runtime tool IDs, which are lowercase, such as `bash`,
> `read`, `write`, `grep`, and `glob`. Capitalized names such as `Bash` don't resolve. An
> unrecognized entry is skipped silently, so an agent whose whole list is capitalized starts
> with no tools at all and reports no error.

observed, run `x9-helper-tools`: a helper defined with `tools: [bash]` reported only `bash`
and `system_todo_write`, had no write tool and no spawn tool, and wrote no file. The binary
carries the refusal "Tool '...' is not allowed for agent '...'. Allowed tools: ...". A stock
helper has no spawn tool in any case (`cortex-code-helper-nesting.md`).

## Codex

The runs passed the hook inline, with
`-c 'hooks.PreToolUse=[{matcher="Bash",hooks=[{type="command",command="python3 <dir>/hooks/guard.py"}]}]'`
and `--dangerously-bypass-hook-trust`. A project `.codex/hooks.json` and `.codex/rules/` load
only in a trusted project, and trusting one writes to `~/.codex/config.toml`, which this
research was not allowed to edit. So rules were checked offline only.

### 1. Can something inspect a shell command before it runs and refuse it? Where is it configured?

**Yes, two ways: a `PreToolUse` hook, and a rule.** read and observed

Hook. read, [hooks](https://learn.chatgpt.com/docs/hooks): `hooks.json` is read from
`/etc/codex/`, `~/.codex/`, a trusted project's `.codex/`, and a plugin's `hooks/`, or inline
under `[hooks]` in `config.toml`. A hook must be trusted first:

> Before a non-managed hook can run, Codex requires you to review and trust the exact hook
> definition. Codex records trust against the hook's current hash, so new or changed hooks are
> marked for review and skipped until trusted.

> Treat tool hooks as a useful guardrail, not a complete enforcement boundary.

observed: run `c2-guards-ab`, the session's `gh pr merge 99999` was refused ("Command blocked
by PreToolUse hook: GUARD-A ..."). Run `c2b-guards-ab`, a helper's `gh pr ready 99999` was
refused the same way. Run `c4-deny-yolo`, under `--dangerously-bypass-approvals-and-sandbox`
(`permission_mode: "bypassPermissions"`): a stand-in was refused by the hook and the control
probe ran.

Rule. read, [rules](https://learn.chatgpt.com/docs/agent-configuration/rules): `.rules` files
in a `rules/` folder beside a config layer (`~/.codex/rules/`, or `<repo>/.codex/rules/` in a
trusted project) hold `prefix_rule` entries whose decision is `allow`, `prompt` or
`forbidden` ("Block the request without prompting"). The page also says "Rules are
experimental and may change".

observed, offline: with this rule,

```python
prefix_rule(pattern = ["gh", "pr", ["merge", "ready"]], decision = "forbidden",
    justification = "raw gh pr merge/ready is refused; use the merge or ready script")
```

`codex execpolicy check --rules guards.rules -- gh pr merge 99999` returns
`"decision": "forbidden"`. The same checker returns no match for
`bash -lc 'echo hi && gh pr ready 5'`. The docs say the runtime splits simple shell chains;
that was not run live.

### 2. Can it tell a helper from the session the owner started?

**A hook can, by `agent_id`. A rule cannot.** observed, and read in source

Runs `c1b-session-and-helper` and `c2b-guards-ab`: the session's `PreToolUse` input had no
`agent_id` or `agent_type`. A spawned helper's had `agent_id` (the helper's thread ID) and
`agent_type: "default"`, with `session_id` still the session's. In `c2b` the helper's
`./merge-script.sh` was refused (GUARD-B); in `c2` the session's ran.

The source schema at `rust-v0.171.0`,
`codex-rs/hooks/schema/generated/pre-tool-use.command.input.schema.json`, lists `agent_id` and
`agent_type` as optional properties. The docs page names them only for `SubagentStart`,
`SubagentStop` and the model-request events ("plus `agent_id` and `agent_type` when
available"), and says "Subagent hooks use the parent session id".

A rule matches on the command alone. Nothing in the rules page or the source lets a rule tell
a helper from the session (not found).

### 3. Can it make a command wait for the owner's answer?

**Not with a hook. A hook's "ask" lets the command run.** read and observed

read, [hooks](https://learn.chatgpt.com/docs/hooks):

> `permissionDecision: "ask"`, legacy `decision: "approve"`, `continue: false`, `stopReason`,
> and `suppressOutput` are parsed but not supported yet. Codex marks the hook run as failed,
> reports the error, and continues the tool call.

observed, run `c3-hook-ask`: the hook answered "ask" for `./oneway-probe.sh codex-ask`; the
command ran and the marker file was created. A Claude Code hook copied to Codex unchanged
would let every one-way command through.

A `prompt` rule is the mechanism that waits. None of this was run live:

- read, [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents): "In
  interactive CLI sessions, approval requests can surface from inactive agent threads even
  while you are looking at the main thread." So a helper's prompt reaches the owner.
- read, same page: "In non-interactive flows, or whenever a run can't surface a fresh
  approval, an action that needs new approval fails and Codex surfaces the error back to the
  parent workflow." And: "Subagents inherit the parent turn's current sandbox and approval
  settings, including changes made with `/permissions` or `--yolo`."
- read in source, `codex-rs/core/src/exec_policy.rs`: when the approval policy is `never`, a
  matched `prompt` rule becomes a refusal with the reason "approval required by policy, but
  AskForApproval is set to Never". So with prompts off a `prompt` rule fails closed.
- read, [agent-approvals-security](https://learn.chatgpt.com/docs/agent-approvals-security):
  "Set `approvals_reviewer = "auto_review"` to route eligible approval requests through a
  reviewer agent before Codex runs the action." This machine's `~/.codex/config.toml` has that
  setting (observed), so a `prompt` rule here would be answered by the reviewer agent and not
  by the owner (inferred).
- read in source, `codex-rs/execpolicy/src/decision.rs`: a fourth decision, `PromptUser`
  ("Requires a fresh human decision, independent of the configured reviewer"), exists in the
  enum, but the rules parser at 0.171.0 accepts only `allow`, `prompt` and `forbidden`.
  observed: a rule with `decision = "prompt_user"` fails to parse.

### 4. Can a helper's definition file withhold the edit tools and the tool that starts helpers?

**No.** read

read, [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents):

> Custom agent instructions can ask an agent to avoid edits, but they don't create a separate
> read-only sandbox.

The same page lists what a custom agent file may switch off: `features.shell_tool`,
`features.apps`, `features.plugins`, `features.memories` and
`features.request_permissions_tool`. The source (`codex-rs/core/src/agent/role.rs`) accepts
exactly those five features. Neither the patch tool nor the spawn tool is among them, so a
helper that keeps its shell keeps both.

A `PreToolUse` hook that refuses the patch and spawn tools when `agent_id` is present would do
the same job (inferred, not tested).

## Cursor

Every observation is from the Cursor CLI in print mode (`cursor-agent -p`), version
2026.11.22. The desktop app was not driven.

### 1. Can something inspect a shell command before it runs and refuse it? Where is it configured?

**Yes, two ways: a `beforeShellExecution` hook, and a `permissions.deny` entry.** read and
observed

Hook. read, [hooks](https://cursor.com/docs/hooks): hooks live in `hooks.json` at
`<project-root>/.cursor/hooks.json` ("Project hooks run in any trusted workspace"),
`~/.cursor/hooks.json`, an enterprise path, the team dashboard, or a plugin. On merging:

> All matching hooks from every source run, and Cursor merges their responses: any `deny` wins
> over `ask`, and `ask` wins over `allow`, regardless of source.

On failure: "Crashes, timeouts, and non-zero exit codes other than `2` fail open by default
... Set `failClosed: true` on the hook definition to block on those failures too."

observed: run `u2-print-trust` (`--trust`, no `--force`), the session's `gh pr merge 99999`
was refused: "Command execution was blocked by a hook: GUARD-A ...". Run `u2f-print-force`
(`--force`), a stand-in was refused the same way and the control probe ran.

Deny entry. read,
[cli/reference/permissions](https://cursor.com/docs/cli/reference/permissions): permissions
are set in `~/.cursor/cli-config.json` or `<project>/.cursor/cli.json`; "Deny rules take
precedence over allow rules"; "Use `command:args` (e.g., `curl:*`) to match both command and
arguments with globs". read, [cli/headless](https://cursor.com/docs/cli/headless): `--force`
runs "every action without approval, except what `permissions.deny` and team policies block".

observed, run `u1-deny-force`, under `--force`, with
`"deny": ["Shell(./merge-script.sh)", "Shell(./control-probe.sh:blocked*)"]` in the project's
`.cursor/cli.json`: `./merge-script.sh` and `./control-probe.sh blocked-arg` were refused
("Command blocked by permissions configuration") and `./control-probe.sh open-arg` ran. The
hooks fired for all three, before the deny entry was applied.

### 2. Can it tell a helper from the session the owner started?

**Not directly. No field marks a helper. Two indirect signals exist, and a workaround built on
them worked once.** observed

Run `u3-helper`: the hooks fire inside a helper. The helper's `beforeShellExecution` input had
the same keys as the session's: `command`, `conversation_id`, `cursor_version`, `cwd`,
`generation_id`, `hook_event_name`, `model`, `sandbox`, `session_id`, `tool_use_id`,
`transcript_path`, `user_email`, `workspace_roots`. There is no `agent_id`, and nothing in the
[hooks](https://cursor.com/docs/hooks) common schema marks a subagent (not found). The
signals:

- `conversation_id` and `session_id` are the helper's own ID, different from the session's.
- `transcript_path`, when set, ends in `.../agent-transcripts/<session>/subagents/<helper>.jsonl`.
  It was `null` on the helper's first shell call in `u3-helper` and set in the three later
  runs, so it cannot be the only test. The CLI
  changelog (v2026.10.17) describes the path: "Subagent transcripts are now saved inside the
  parent conversation's folder, under `agent-transcripts/<parent>/subagents/`."
- A `sessionStart` hook fired once per run, for the session, and never for a helper (six
  runs).

Workaround, run `u6-guard-b`: a `sessionStart` hook appended the session's ID to a file; the
`beforeShellExecution` hook treated a call as a helper's when its `conversation_id` was not in
that file or its `transcript_path` contained `/subagents/`. The session's `./merge-script.sh`
ran and the helper's was refused ("blocked by a hook: GUARD-B ..."). If `sessionStart` does not
fire, for example on a resumed session, this refuses the session too: it fails closed. That
case was not tested.

The documented `subagentStart` hook, whose input carries `subagent_id` and
`parent_conversation_id`, would be the cleaner source. It was registered in all seven
runs that started a subagent and never fired. `subagentStop`, registered in six, did not fire
either.

### 3. Can it make a command wait for the owner's answer?

**In print mode, no: "ask" is refused without `--force` and ignored with it.** read and
observed

read, [hooks](https://cursor.com/docs/hooks): `beforeShellExecution` may return
`"permission": "allow" | "deny" | "ask"`. For the generic hook: "`"ask"` is accepted by the
schema but not enforced for `preToolUse` today."

read, [cli/changelog](https://cursor.com/docs/cli/changelog), v2026.10.28:

> When a `beforeShellExecution` hook asks for approval, the CLI now prompts you even if
> Auto-review would have allowed the shell command. A skip you chose yourself still skips the
> prompt.

read, [cli/headless](https://cursor.com/docs/cli/headless): "Print mode follows the same
approval rules as an interactive session, but it can't stop to ask you. Without `--force`,
anything that runs without approval still runs, and anything that would need approval is
rejected".

| Flags | Caller | Result | Run |
|---|---|---|---|
| `--trust` | session | rejected, no marker | `u2-print-trust` |
| `--trust` | helper | rejected, no marker | `u5-helper-ask-trust` |
| `--force` | **session** | **ran**, marker created | `u2f-print-force` |
| `--force` | **helper, foreground** | **ran**, marker created | `u5f-helper-ask-force` |
| `--force` | **helper, background** | **ran**, marker created | `u5b-bghelper-ask-force` |

Two things make "ask" unusable for guard c on Cursor:

- The hook input has no field for the run mode, so the hook cannot tell that `--force` is on
  and switch to "deny".
- When "ask" is rejected, the agent receives "Rejected: " with an empty reason. The hook's
  `agent_message` is dropped, so the agent has no question to return. A "deny" delivers its
  message.

**Not observed:** an interactive session. The changelog entry says a prompt is shown in
Auto-review mode and skipped where the owner chose to skip prompts.

### 4. Can a helper's definition file withhold the edit tools and the tool that starts helpers?

**Not tool by tool. One switch, `readonly: true`, restricts the whole helper.** read; partly
observed

read, [subagents](https://cursor.com/docs/subagents): the file fields are `name`,
`description`, `model`, `readonly` and `is_background`. There is no tools list.

> `readonly` | If `true`, the subagent runs with restricted write permissions (no file edits,
> no state-changing shell commands).

Files are read from `.cursor/agents/`, and also `.claude/agents/` and `.codex/agents/`. On
spawning, the same page says: "Nested launches also need Task tool access in the current mode,
and hooks or tool policies can block spawning."

observed, runs `u4-readonly-helper` and `u4b-readonly-attempt`: a helper defined with
`readonly: true` still listed `Write`, `StrReplace`, `Delete`, `Shell` and `Task` among its
tools. It reported that "Ask mode is active", made none of the calls, and wrote no file.
Whether the harness would refuse an actual call was not observed, because the helper would not
make one. A read-only helper also could not run the stand-in shell command, so `readonly`
cannot give "shell yes, edits and spawn no".

A `preToolUse` hook with the matcher `Write|StrReplace|Delete|Task` could refuse those tools to
a helper (inferred, not tested, and it needs the helper test from question 2).

## What follows for the adapters

All inferred from the results above.

- **The hook decides, not the harness.** Each adapter's hook returns "deny" for guards a and
  b. For guard c it returns "ask" only on Claude Code. On Cortex Code it returns "deny" when
  `permission_mode` is `bypassPermissions` or `agent_id` is present. On Codex and Cursor it
  always returns "deny", with the question in the message so the agent can return it.
- **Claude Code.** Ship the hook in the plugin's `hooks/hooks.json` or a settings file. A hook
  in a skill's own file leaves every helper unguarded. Test for `agent_id`.
- **Cortex Code.** Register in `.cortex/settings.json` or `~/.snowflake/cortex/hooks.json`.
  Test for `agent_id`. Write the helper's `tools:` list in lowercase.
- **Codex.** Register in `~/.codex/hooks.json`; the owner must trust the hook once, and again
  whenever its definition changes. A `forbidden` rule can back up guard a. A helper file
  cannot withhold edits or spawning: use the text rule, or the untested hook above.
- **Cursor.** Register `beforeShellExecution` in `.cursor/hooks.json`, with `failClosed: true`.
  Guard b needs the `sessionStart` workaround or the text rule. Cursor also loads Claude Code
  hooks from `.claude/settings.json` (read,
  [third-party-hooks](https://cursor.com/docs/reference/third-party-hooks); on by default), so
  a repo that carries both sets may fire two hooks for one command.
- **Preflight.** The helper fields on Cortex Code and Codex are undocumented for `PreToolUse`,
  and the Cursor signals are indirect. A preflight that starts one helper and checks the hook
  log would catch a release that changes them.

## Side findings

- **Cursor CLI updates itself when run.** `cursor-agent` was at `2025.09.12-4852336`. The
  first print-mode run replaced the `~/.local/bin/cursor-agent` link with
  `2026.11.22-e9042b2` and the new build rewrote `~/.cursor/cli-config.json` (same
  `permissions`; the model entry changed from Auto to Auto Balance; default display keys were
  added). Nothing asked for this. The old build ran no hooks at all: project hooks first fired
  on the run after the update. The old build is still on disk.
- **Claude Code ignores a project's `permissions.allow` under `-p` in a folder nobody has
  trusted**, while the same project's hooks still run. The stderr line was "Ignoring 4
  permissions.allow entries from .claude/settings.json: this workspace has not been trusted".
  The runs passed `--allowedTools` instead.
- **Codex: `--ephemeral` breaks spawning.** Run `c2-guards-ab`: "collab spawn failed: ... no
  rollout found for thread id ...". Without the flag the helper started.
- **Codex: a trust override on the command line does not load project config.**
  `-c 'projects."<dir>".trust_level="trusted"'` still printed "Untrusted project-local
  configuration is disabled".
- **Cortex Code: the matcher and the input disagree on case.** The matcher `bash` matched; the
  input's `tool_name` was `"Bash"`.
- **Cursor: the hooks run before the deny entry.** A command that `permissions.deny` blocks
  still reaches `preToolUse` and `beforeShellExecution` first.

## Open, with the smallest test

Each test uses the fixture described in [How the runs were made](#how-the-runs-were-made).
`<fixture>` is the harness's test directory.

1. **Claude Code: is the terminal prompt shown in bypass or auto mode?**
   `cd <fixture> && claude --setting-sources project --permission-mode bypassPermissions`,
   then type `run ./oneway-probe.sh interactive`. Shown and answered "no": no
   `logs/oneway-ran-interactive.marker`. Repeat with `--permission-mode auto`.
2. **Claude Code: does a hook in a helper's own frontmatter fire in a trusted folder?** Open
   `<fixture>` interactively once, accept the trust dialog, then ask it to start the
   `helper-fm` agent and have it run `echo x`. A line with `"source": "agentfm"` in
   `logs/hook.jsonl` means yes.
3. **Cortex Code: what does an interactive `--bypass` session do with a hook's "ask"?**
   `cd <fixture> && cortex --bypass`, then type `run ./oneway-probe.sh cx-interactive`. Then
   the same from a helper. A marker file with no prompt shown means the command ran unasked.
4. **Codex: does a `prompt` rule wait, and fail closed?** The owner copies the fixture's
   `guards.rules` to `~/.codex/rules/`, then runs
   `codex exec --sandbox workspace-write "run ./oneway-rule-probe.sh x"`, the same with
   `-c approval_policy='"never"'`, and the same with
   `--dangerously-bypass-approvals-and-sandbox`. Expected from the source: refused in the last
   two. Then an interactive `codex` session with the same prompt, to see whether the owner or
   the auto-reviewer is asked. Remove the rule file afterwards.
5. **Codex: does the runtime match a `forbidden` rule inside a shell chain?** With the rule
   installed as in 4: `codex exec "run: echo hi && gh pr ready 99999"` in a directory with no
   remote. Refused means yes.
6. **Codex: can a hook withhold the patch and spawn tools from a helper?** Add a `PreToolUse`
   entry with the matcher `apply_patch|spawn_agent` that refuses when `agent_id` is present;
   ask a helper to edit a file and to start a helper.
7. **Cursor: does `subagentStart` fire outside print mode, and does the desktop app behave
   like the CLI?** Open `<fixture>` in the Cursor app, ask it to start a subagent that runs
   `./oneway-probe.sh cu-ide`, and read `logs/hook.jsonl` for a `subagentStart` line and for
   whether a prompt was shown.
8. **Cursor: does `readonly: true` refuse a real call?** Needs a helper that attempts the
   call. A `preToolUse` log line for `Write` from the helper followed by no file is the proof.
9. **Cursor: does `sessionStart` fire on a resumed session?**
   `cursor-agent --resume <id> -p --trust "run ./merge-script.sh"`. No new line in
   `logs/main-sessions.txt` means the workaround would refuse the session.
10. **Cursor: does a Claude Code hook in `.claude/settings.json` fire in the CLI?** Add one
    that logs, run any shell command, and look for its line.

## Fixture reference

Per-harness registration used in the runs:

```json
// Claude Code: .claude/settings.json
{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/hooks/guard.py\" settings"}]}]}}

// Cortex Code: .cortex/settings.json
{"hooks": {"PreToolUse": [{"matcher": "bash", "hooks": [
  {"type": "command", "command": "python3 <dir>/hooks/guard.py settings"}]}]}}

// Cursor: .cursor/hooks.json
{"version": 1, "hooks": {
  "beforeShellExecution": [{"command": "python3 hooks/guard.py beforeShell"}],
  "sessionStart": [{"command": "python3 hooks/guard.py sessionStart"}]}}
```

Commands, with `<prompt>` a one-line instruction to run the stand-ins:

```sh
# Claude Code. The stand-in owner is an MCP server passed with --permission-prompt-tool.
claude -p "<prompt>" --model haiku --setting-sources project --output-format stream-json \
  --verbose --no-session-persistence --allowedTools "Bash(echo:*)" [--permission-mode <mode>]

# Cortex Code
cortex -p "<prompt>" --output-format stream-json --private --max-turns 8 \
  -m claude-haiku-4-5 [--bypass | --allowed-tools bash]

# Codex. No --ephemeral: it breaks spawning.
codex exec --json -m gpt-6-luna --dangerously-bypass-hook-trust \
  -c 'hooks.PreToolUse=[{matcher="Bash",hooks=[{type="command",command="python3 <dir>/hooks/guard.py settings",timeout=20}]}]' \
  --sandbox workspace-write "<prompt>"

# Cursor
cursor-agent -p --output-format stream-json [--trust | --force] "<prompt>"
```

Hook answer shapes: Claude Code, Cortex Code and Codex take
`{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`.
Cursor's `beforeShellExecution` takes
`{"permission": "deny", "user_message": "...", "agent_message": "..."}`.
