# Cortex Code: whether a helper can start its own helpers

Research date: 2026-11-21. Resolves ticket #195. It closes two questions that
`orchestrator-mode-harness-recheck.md` (2026-11-12) left open: how deep Cortex Code subagents
nest, and whether a background agent can start foreground subagents. Snowflake's docs now call
the product "CoCo CLI" in places; the binary is still `cortex`.

Every claim carries one of three marks:

- **read**: quoted from a Snowflake page, with the URL. All pages were fetched on 2026-11-21.
- **observed**: seen on the locally installed CLI, with the command. Nothing here started a
  session, called a model or spent credits.
- **inferred**: a conclusion drawn from read or observed facts. No test has confirmed it.

## Answer

| Part | Answer | Mark |
|---|---|---|
| 1. Can a helper start helpers, and how deep? | Not on a stock install. The limit is **1 layer below the session** by default: a helper is not given the spawn tools. An undocumented experimental key, `maxSubagentDepth`, raises the limit, capped at **5**. The design's two layers need that key set to 2 or more. The docs give no figure. | observed (binary 1.2.46); docs silence is read |
| 2. Can a background agent start foreground helpers? | By default no, because no helper at layer 1 can start anything. With `maxSubagentDepth` at 2 or more, yes: a background agent's spawn call runs in the foreground unless it asks for background, and it may also ask for background. | observed (binary 1.2.46) |
| 3. Can the session resume a stopped helper with new input? | Yes. The docs say a killed agent keeps its context and can be resumed by ID. The spawn tool takes `resume` (an agent ID) together with a new `prompt`, which is added to the old conversation as a new user message. Earlier sessions on this machine resumed helpers 171 times with no failed resume. A helper that is still running cannot be resumed. Resuming a helper that was killed, as opposed to one that finished, was not singled out in the logs. | read (docs), observed (binary 1.2.46, logs) |

Corrected comparison line for the harness notes: Claude Code 3 layers, Cursor 2, Codex no depth
limit, **Cortex Code 1 by default (up to 5 with an undocumented experimental key)**.

No agent was run for this note. Parts 1 and 2 rest on reading the binary and on logs of earlier
sessions; the tests that would confirm them are in
[Open, with the smallest test](#open-with-the-smallest-test).

## Sources and versions

| Source | Version or date | How it was used |
|---|---|---|
| [extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility) | fetched 2026-11-21 | subagent rules, limits, resume |
| [tools](https://docs.snowflake.com/en/user-guide/cortex-code/tools) | fetched 2026-11-21 | `RunSubagent` description |
| [changelog](https://docs.snowflake.com/en/user-guide/cortex-code/changelog) | newest entry 1.2.46 (Nov 16, 2026) | every entry naming subagents, background agents, spawn, nesting, depth, resume or teams |
| [settings](https://docs.snowflake.com/en/user-guide/cortex-code/settings), [cli-reference](https://docs.snowflake.com/en/user-guide/cortex-code/cli-reference), [code-mode](https://docs.snowflake.com/en/user-guide/cortex-code/code-mode), [workflows](https://docs.snowflake.com/en/user-guide/cortex-code/workflows), [cortex-code-cli](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-cli), [managed-settings](https://docs.snowflake.com/en/user-guide/cortex-code/managed-settings), [cortex-code-acp](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-acp), [cortex-code-automations](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-automations), [Agent SDK overview](https://docs.snowflake.com/en/user-guide/cortex-code-agent-sdk/cortex-code-agent-sdk) | fetched 2026-11-21 | searched for a depth figure or nesting rule; none found |
| Installed CLI | `cortex --version` prints `Cortex Code v1.2.46`; build `1.2.46+175654.6f8561fd271f` | `cortex --help`, `cortex exec --help`, and the text strings inside the binary |
| Older installed builds | 1.2.18, 1.2.35, 1.2.37, 1.2.41, 1.2.45 (`cortex versions`) | same constants checked |
| CLI logs | `~/.snowflake/cortex/logs/coco.log*`, 2026-09-01 to 2026-11-21 | counts of what earlier, ordinary sessions did |

The binary is a single executable with its JavaScript bundled and minified. "Observed (binary)"
means a fragment found with:

```sh
strings -n 6 ~/.local/share/cortex/1.2.46+175654.6f8561fd271f/cortex > /tmp/cortex-strings.txt
grep -a -o -E '<pattern>' /tmp/cortex-strings.txt
```

Minified names such as `mqe` and `WLt` change with every build. The quoted error strings and
the names `DEFAULT_MAX_SUBAGENT_DEPTH`, `MAX_ALLOWED_SUBAGENT_DEPTH` and `maxSubagentDepth` are
the stable things to search for. The patterns are listed in
[Patterns used](#patterns-used).

Reading minified code shows what the code says, not what a run does. A server-side setting
that changes behaviour would not show up here.

## 1. How deep helpers nest

### What the docs say

- **read** The limits listed for subagents are: "Maximum 50 concurrent background agents",
  "Agents inherit session permissions", "Background agents cannot spawn other background
  agents". No line gives a depth, and no line says whether a foreground subagent can spawn.
  ([extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility), "Agent
  limits")
- **read** `RunSubagent`: "Launch an autonomous subagent to handle a specific subtask." "Each
  subagent runs independently and returns its results when finished." Nothing on nesting.
  ([tools](https://docs.snowflake.com/en/user-guide/cortex-code/tools))
- **read** The 1.1.8 entry, under Fixed: "Profile inheritance through subagent spawn chains
  applies the intended profile and skill paths." This is the only mention of chains in the
  changelog. It is about profile inheritance and states no depth.
  ([changelog](https://docs.snowflake.com/en/user-guide/cortex-code/changelog))
- **read** None of the other pages in the table above mentions `maxSubagentDepth`, a nesting
  depth, or a rule for helpers that start helpers.

### What build 1.2.46 does

- **observed (binary)** The depth limit is a function that reads one setting and falls back to
  a default of 1, with a ceiling of 5:
  `function mqe(){let t=vhn(Sf().maxSubagentDepth);return t===null?WLt:Math.min(t,LGl)}`,
  with `WLt=1,LGl=5`, exported as `DEFAULT_MAX_SUBAGENT_DEPTH` and
  `MAX_ALLOWED_SUBAGENT_DEPTH`. The setting must be a positive number; it is rounded down.
- **observed (binary)** `Sf()` is the experimental-features object. It is parsed from the
  environment variable `CORTEX_CODE_EXPERIMENTAL_FEATURES` when that is set, and otherwise from
  `env.CORTEX_CODE_EXPERIMENTAL_FEATURES` in `~/.snowflake/cortex/settings.json`. The two are
  not merged: the environment variable replaces the settings value.
- **observed (binary)** The session is depth 0 (`parseInt(process.env.CORTEX_SUBAGENT_DEPTH||"0",10)`).
  Each spawn passes `subagentDepth:(t.context.subagentDepth??0)+1` to the child, on the
  foreground path and on the background path alike. A helper the session starts is depth 1.
- **observed (binary)** A helper at or past the limit loses the spawn tools. The filter is
  `if(n>=mqe()&&sa1.has(t))return!1` with
  `sa1=new Set(["task","agent","agent_output","kill_agent"])`, where `n` is the helper's own
  depth. The subagent runner applies it twice: when it builds the tool list sent to the model,
  and again before it runs a tool call (the refusal reads "Tool '...' is not allowed for agent
  '...'").
- **observed (binary)** The spawn handler has its own check with the message "Maximum subagent
  nesting depth of N reached. Subagents at this depth cannot create further subagents." That
  check is skipped when the call sets `run_in_background=false`
  (`a=t.runInBackground===!1;if(o>=s&&!a)`). The tool filter above does not have that
  exception, so the filter is the gate that holds.
- **observed (binary)** Two built-in agent types never get the spawn tools at any depth:
  `explore` and `snowflake-object-discovery`. No helper gets `send_message`, `team_create` or
  `team_delete`.
- **observed (binary)** Builds 1.2.18, 1.2.35, 1.2.37, 1.2.41 and 1.2.45 hold the same setting
  name, the same default of 1 and the same ceiling of 5.
- **observed (settings)** The local `settings.json` does not set `maxSubagentDepth`, and the
  environment variable is not set in the shell, so this install runs at the default. Checked
  by listing the keys of `env.CORTEX_CODE_EXPERIMENTAL_FEATURES`.
- **observed (logs)** In 732 helper runs logged between 2026-09-01 and 2026-11-21, helpers ran
  25,515 tool calls. None was `task`, `agent`, `agent_output` or `kill_agent`. This fits a
  helper that is not offered those tools. It does not prove it, because the logs do not record
  the tool list each helper was sent. Command:
  `cat ~/.snowflake/cortex/logs/coco.log* | grep -a -o -E 'Subagent executing tool: [A-Za-z_]+' | sort | uniq -c`
- **observed (binary)** The bundle also carries a second spawn handler, exported as the SDK's
  `runSubagentTool`, with the limit written in as 2 (`let n=2;if(jin>=n)`). The CLI's own tool
  list uses the other handler, the one with the configurable limit: the CLI's `task` and
  `agent` tools both execute it, and the only spawn-handler logger that appears in the CLI
  logs is `coco.tools.task_runtime` (3 lines, against 0 for `coco.tools.run_subagent`).
- **inferred** A program built on the Agent SDK may therefore allow 2 layers where the CLI
  allows 1. This was not looked into further; the ticket is about the CLI.

### What follows for the design

- **inferred** On a stock install the chain session -> author -> two reviewers does not work.
  The author is depth 1, the default limit is 1, and the author has no spawn tool. The session
  has to start the reviewers itself.
- **inferred** With `{"maxSubagentDepth":2}` the chain fits: the author (depth 1) keeps the
  spawn tools and the reviewers (depth 2) lose them. A helper runs the tool calls of one model
  turn together (`executing N tool(s) in parallel` followed by `await Promise.all`, observed in
  the binary), so two spawn calls in one message should run the two reviewers at once.
- **inferred** The key is a poor base for a skill other people install. It is experimental and
  appears in no Snowflake page, so it can change or go away without a changelog entry, and
  each user would have to set it.

## 2. A background agent starting foreground helpers

- **read** "Background agents cannot spawn other background agents". The docs say nothing
  about a background agent starting a foreground one.
  ([extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility))
- **observed (binary)** At the default limit the question does not arise: a background agent
  the session starts is depth 1 and is not given `task` or `agent`, so it can start nothing,
  foreground or background.
- **observed (binary)** The handler picks the mode like this, where `i` means "the limit was
  raised above the default" and `a` means "the call set `run_in_background=false`":
  `let l=i&&e.isSubagent===!0&&t.runInBackground===void 0&&!t.teamName,d=a||l?"inline":"background"`.
  With the limit raised, a spawn call from any helper that leaves `run_in_background` unset
  runs inline, which is the foreground mode: the caller waits and gets the result back.
- **observed (binary)** The background-to-background refusal is tied to the default limit:
  `if(!i&&Z9())throw new Error("Background agents cannot spawn other background agents. Use
  run_in_background=false for synchronous subagent execution.")`. With the limit raised, that
  line no longer fires, so a background agent may also start background helpers.
- **observed (binary)** A foreground helper asking for a background child is always refused
  unless it names a team: "Foreground subagents cannot spawn background agents. Use
  run_in_background=false for synchronous subagent execution, or set team_name to launch a
  detached teammate." The tool description a foreground helper sees says the same: "Agents you
  launch run in the foreground and return their result to you directly. Do not set
  run_in_background — only the top-level agent can fan out to background agents."
- **inferred** With the limit at 2 or more, the answer is yes, and the error text itself
  points a background agent to `run_in_background=false`. Summary for a helper below the limit:

| Caller | Foreground child | Background child |
|---|---|---|
| Session | yes | yes (the default when `run_in_background` is unset) |
| Background helper, limit raised | yes (the default) | yes |
| Foreground helper, limit raised | yes (the default) | no, unless `team_name` is set |
| Any helper, default limit | no | no |

## 3. Resuming a stopped helper with new input

- **read** "Killed agents stop running, but retain their context indefinitely. You can resume
  a killed agent using its ID", with the example "Resume agent abc1234 and continue from where
  it left off".
  ([extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility),
  "Running subagents")
- **observed (binary)** The `task` tool description: "Agents can be resumed using the resume
  parameter by passing the agent ID from a previous invocation. When resumed, the agent
  continues with its full previous context preserved." The `agent` tool's parameter:
  `resume`: "agentId of a previous agent to continue."
- **observed (binary)** `prompt` stays a required parameter on a resume call. The runner loads
  the stored conversation for that ID, then adds the prompt as a new user message. That is the
  new input.
- **observed (binary)** A foreground helper's result ends with
  "agentId: ... (for resuming to continue this agent's work if needed)", so a finished
  foreground helper can be resumed too, not only a killed background one.
- **observed (binary)** Limits on resume: a running agent is refused ("Agent ... is still
  running and cannot be resumed yet ... Wait for it with agent_output (wait=true), or stop it
  with kill_agent, then resume."); an unknown ID fails ("Agent session '...' not found. Cannot
  resume."); `resume` cannot be combined with `fork_conversation_history`.
- **observed (logs)** The runner logged "Resuming subagent ... from session ..." 171 times
  between 2026-09-03 and 2026-11-19, and "Cannot resume" never. In one case a session's `task`
  call resumed a background helper 31 minutes after that helper had finished; the call blocked
  for another 31 minutes and the helper ended with "completed successfully". Commands:
  `cat ~/.snowflake/cortex/logs/coco.log* | grep -a -c -F 'Resuming subagent'` and the same with
  `'Cannot resume'`.
- **observed (binary)** A second path exists for background agents: a message sent to a
  running one is queued and picked up at its next turn, and a message sent to a finished one
  resumes it. A control request named `send_agent_message` uses it. A foreground helper is
  refused on this path ("is a foreground conversation and cannot be resumed as a background
  agent"). The agent viewer's input box delivers only to a running agent; for a finished one
  it prints "This subagent has already finished, so the message was not delivered. Spawn or
  resume it to keep going."
- **inferred** The session can resume because it holds the spawn tool. A helper at the depth
  limit cannot, since it has no spawn tool. The docs' word "indefinitely" was not tested
  across a CLI restart, and the logs do not show whether any of the 171 resumed helpers had
  been killed first.

## Side findings

- **observed (binary)** The cap on running agents is 20 per session by default, not 50:
  `getMaxAgentsPerSession()` returns the `maxAgentsPerSession` setting or `LSs=20`, and the
  refusal reads "Maximum concurrent agent limit (N) reached for this session. M subagents and
  background agents are currently active." Foreground and background helpers both count. The
  count is kept under the top session's ID, so helpers at every depth share it. The docs still say "Maximum 50
  concurrent background agents" (**read**), and the settings page does not list
  `maxAgentsPerSession`. A search of the binary for "Maximum 50" and "50 concurrent" found
  nothing. Which figure a run enforces is untested.
- **observed (logs)** On 2026-11-18 a top-level session made three `task` calls in one turn and
  all three failed with "Background agents cannot spawn other background agents." The same
  session had started background agents earlier that day. The failing turn came 37 seconds
  after an `agent_output` call that had waited 30 seconds for a background agent to finish.
  24 seconds later the session made three `task` calls again; these ran in the foreground, at
  the same time, and completed. **inferred** For one turn the session was treated as a
  background agent, which looks like a defect around waiting on a background agent. It
  happened once in the logs. A coordinator that fans out right after such a wait may hit it;
  the session here got past it by spawning in the foreground.
- **observed (binary)** The spawn handler reads the caller's depth from a variable shared by
  the whole process, which each agent sets just before its spawn call. **inferred** When the
  session and a helper spawn at the same moment, one may read the other's depth. No run has
  shown this.

## Open, with the smallest test

Nothing above was run. Each test below is one headless command in an empty directory and costs
a few short model turns. The prompts are drafts and have not been tried. `task` needs no
permission prompt, and the first three tests use no other tool.

**Test 1: the default limit is 1 layer (parts 1 and 2).**

```sh
cortex exec --no-mcp --max-turns 6 "Call the task tool once with subagent_type general-purpose, run_in_background false and this prompt: 'Use no tools except the ones named here. First say which of these tools you have: task, agent, agent_output, kill_agent. If you have task or agent, call it once with subagent_type general-purpose, run_in_background false and the prompt: Reply with the single word LEAF. Report its reply or the exact error text.' Then print the helper's reply word for word and stop."
```

Expected from the code: the helper says it has none of the four tools and no `LEAF` comes back.
If `LEAF` comes back, the reading of the tool filter is wrong and the default is deeper than 1.
Repeat with `run_in_background true` on the outer call, then read the result with
`agent_output` and `wait true`, to cover a background helper.

**Test 2: the key gives two layers, with two reviewers at once (part 1).**

```sh
CORTEX_CODE_EXPERIMENTAL_FEATURES='{"maxSubagentDepth":2}' cortex exec --no-mcp --max-turns 8 "Call the task tool once with subagent_type general-purpose, run_in_background false and this prompt: 'In ONE message make two task calls, both with subagent_type general-purpose and run_in_background false. Prompt for the first: Say which of task, agent, agent_output, kill_agent you have, then reply LEAF-A. Prompt for the second: the same, ending LEAF-B. Return both replies word for word.' Then print the helper's reply word for word and stop."
grep -a -E "executing 2 tool\(s\) in parallel|Subagent executing tool: task" ~/.snowflake/cortex/logs/coco.log | tail -5
```

Pass: `LEAF-A` and `LEAF-B` both come back; each leaf reports none of the four tools; the log
shows `Subagent 'general-purpose' executing 2 tool(s) in parallel` and two
`Subagent executing tool: task` lines. The environment variable replaces the experimental
flags in `settings.json` for that one run.

**Test 3: a background agent starts foreground helpers (part 2).** Run test 2 with
`run_in_background true` on the outer call and add: "Then call agent_output with that agent_id
and wait true, and print the output word for word." Pass: both leaf replies come back. Run it
once more with `run_in_background true` on the inner calls as well, to see whether a background
agent may start background helpers once the limit is raised.

**Test 4: resume with new input (part 3).**

```sh
cortex exec --no-mcp --max-turns 8 "Step 1: call task with subagent_type general-purpose, run_in_background false and the prompt 'Remember the word PLUM. Reply READY.' Note the agentId in the result. Step 2: call task again with resume set to that agentId, subagent_type general-purpose, run_in_background false and the prompt 'Which word did I ask you to remember? Reply with only that word.' Print the second reply word for word."
```

Pass: `PLUM`. For a killed background helper, start it with `run_in_background true` and the
prompt "Remember the word PLUM, then run the bash command sleep 300", call `kill_agent`, then
resume as in step 2; this variant needs `--allowed "Bash(sleep *)"`.

Also open, with no test written:

- Whether a server-side or account setting changes the depth limit. Test 1 on the account in
  question answers it for that account.
- Whether team mode (`--team`, `spawn_teammate`, `team_name`) gives a second layer by another
  route. The code blocks plain spawn calls from team-workflow workers; the rest of team mode
  was not read.
- Whether the Agent SDK's 2-layer handler is what SDK programs run.
- Which concurrent-agent cap a run enforces, 20 or 50.

## Patterns used

Each line is the `-E` pattern for the `grep` command in [Sources and versions](#sources-and-versions).

```text
DEFAULT_MAX_SUBAGENT_DEPTH:\(\)=>[A-Za-z0-9_$]+,MAX_ALLOWED_SUBAGENT_DEPTH:\(\)=>[A-Za-z0-9_$]+
WLt=[0-9]+,LGl=[0-9]+
function [A-Za-z0-9_$]+\(\)\{let t=[^;]{0,40}maxSubagentDepth\);return[^}]{0,60}\}
if\(n>=[A-Za-z0-9_$]+\(\)&&[A-Za-z0-9_$]+\.has\(t\)\)return!1
new Set\(\["task","agent","agent_output","kill_agent"\]\)
subagentDepth:\(t\.context\.subagentDepth\?\?0\)\+1
Maximum subagent nesting depth of [^.]+\. Subagents at this depth cannot create further subagents\.
let o=e\.subagentDepth\?\?0,s=[A-Za-z0-9_$]+\(\),i=s>[A-Za-z0-9_$]+,a=t\.runInBackground===!1;if\(o>=s&&!a\)
let l=i&&e\.isSubagent===!0&&t\.runInBackground===void 0&&!t\.teamName,d=a\|\|l\?"inline":"background"
(Background agents|Foreground subagents) cannot spawn[^"`]{0,170}
foregroundOnly\?"[^"]{0,220}"
Agents can be resumed using the resume parameter[^.]+\.[^.]+\.
Agent [^ ]+ is still running and cannot be resumed yet[^`]{0,200}
is a foreground conversation and cannot be resumed as a background agent
getMaxAgentsPerSession\(\)\{let e=this\.getSettings\(\)\.maxAgentsPerSession;[^}]{0,90}\}
Maximum concurrent agent limit \([^)]+\) reached for this session\.[^`]{0,160}
```

The second pattern uses 1.2.46's minified names; take the names for another build from the
first pattern's output.
