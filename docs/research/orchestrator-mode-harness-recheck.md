# orchestrator-mode: Harness notes rechecked for Claude Code, Codex, Cursor, and Cortex Code

Research date: 2026-11-12. Rechecks every claim in the "Harness notes" section of
`skills/orchestrator-mode/references/reference.md` as it stood at commit `7871cdf` (last
checked September 2026), and records the new facts that went into the rewritten section.
Earlier snapshots: `orchestrator-mode-best-practices.md` and
`orchestrator-mode-harness-mapping.md` (both 2026-09-03). Primary sources only: vendor docs,
official changelogs, and the vendors' own repositories. Blog posts and forum answers were not
counted. Where a claim could not be verified, the earlier wording was kept.

## Versions checked

| Harness | Version or ref | Sources |
|---|---|---|
| Claude Code | CLI and changelog 2.1.322 | code.claude.com docs pages listed below, fetched 2026-11-12 |
| Codex | release `rust-v0.167.2` (2026-11-11) and `main` at `c0cc9fc8` (2026-11-12) | `openai/codex` source; learn.chatgpt.com docs (developers.openai.com/codex 308-redirects there); release notes v0.155.0 to v0.167.2 |
| Cursor | changelog to 2026-11-06 | cursor.com/docs/subagents, cursor.com/changelog, /changelog/2-4, /changelog/2-5 |
| Cortex Code | changelog to 1.2.35 (2026-11-02) | docs.snowflake.com/en/user-guide/cortex-code/ extensibility, tools, settings, changelog |

Claude Code pages: [sub-agents](https://code.claude.com/docs/en/sub-agents.md),
[worktrees](https://code.claude.com/docs/en/worktrees.md),
[workflows](https://code.claude.com/docs/en/workflows.md),
[env-vars](https://code.claude.com/docs/en/env-vars.md),
[model-config](https://code.claude.com/docs/en/model-config.md),
[changelog](https://code.claude.com/docs/en/changelog.md).
Codex permalink base: `https://github.com/openai/codex/blob/rust-v0.167.2/codex-rs/`; docs
[config reference](https://learn.chatgpt.com/docs/config-file/config-reference) and
[subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents). Cursor:
[subagents](https://cursor.com/docs/subagents), [2.4](https://cursor.com/changelog/2-4),
[2.5](https://cursor.com/changelog/2-5). Cortex Code:
[extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility),
[tools](https://docs.snowflake.com/en/user-guide/cortex-code/tools),
[settings](https://docs.snowflake.com/en/user-guide/cortex-code/settings),
[changelog](https://docs.snowflake.com/en/user-guide/cortex-code/changelog).

## Claims at `7871cdf`

| Claim at `7871cdf` | Verdict | Corrected fact | Source |
|---|---|---|---|
| Claude Code withholds `AskUserQuestion` from subagents; only a fork keeps the main tools. | confirmed | Forks "receive the main conversation's exact tool pool"; the first filter removes `AskUserQuestion` for every other subagent. | [sub-agents](https://code.claude.com/docs/en/sub-agents.md) |
| Treat workers in any harness as unable to ask. | changed | Codex `request_user_input` "can only be used by the root thread". A Cursor custom subagent can ask when told to "use the ask question tool". A non-autonomous Cortex Code agent "can pause execution to ask the user questions"; `RunSubagent` launches "an autonomous subagent". The operating rule (questions return in `open_questions`) stands; SKILL.md now says a worker "usually" cannot ask. The docs name no setting that launches a non-autonomous Cortex Code agent. | `core/src/tools/handlers/request_user_input.rs`; [Cursor 2.4](https://cursor.com/changelog/2-4); [extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility), [tools](https://docs.snowflake.com/en/user-guide/cortex-code/tools) |
| Claude Code runs up to 20 subagents (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`). | confirmed | Also: a spawn past the limit fails with "Concurrent subagent limit reached" and no retry; resuming a finished subagent "takes a fresh slot without checking the limit". | [sub-agents](https://code.claude.com/docs/en/sub-agents.md), [env-vars](https://code.claude.com/docs/en/env-vars.md) |
| Codex V2 defaults to 4 open threads (`agents.max_concurrent_threads_per_session`). | changed | The 4 counts the main thread, so 3 subagents; the key is `features.multi_agent_v2.max_concurrent_threads_per_session`. `agents.max_concurrent_threads_per_session` (alias `agents.max_threads`) counts subagents only; V1 defaults to 6. When V2's own key is unset and this one is set, V2 allows this value plus 1; with both unset, V2 uses 4. V2 unloads idle children (LRU, state kept) before failing with "agent thread limit reached". | `core/src/config/mod.rs` (`DEFAULT_MULTI_AGENT_V2_MAX_CONCURRENT_THREADS_PER_SESSION = 4`, `DEFAULT_AGENT_MAX_THREADS = Some(6)`, `resolve_multi_agent_v2_config`); `core/src/agent/control/residency.rs`; [config reference](https://learn.chatgpt.com/docs/config-file/config-reference) |
| Cortex Code allows 50 background agents. | confirmed | "Maximum 50 concurrent background agents". No setting documented. | [extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility), [settings](https://docs.snowflake.com/en/user-guide/cortex-code/settings) |
| Cursor documents no cap. | confirmed | No numeric limit, cap, or queueing on the subagents page or the changelog. | [subagents](https://cursor.com/docs/subagents) |
| Claude Code allows 3 layers below the main thread (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`). | confirmed | Default 3 since 2.1.219; `1` turns nesting off. New: "A fork can't spawn further forks." | [sub-agents](https://code.claude.com/docs/en/sub-agents.md), [env-vars](https://code.claude.com/docs/en/env-vars.md), [changelog](https://code.claude.com/docs/en/changelog.md) |
| Cursor allows 2; a grandchild cannot spawn. | confirmed | "a subagent launched by another subagent can't launch further ones." No setting. | [subagents](https://cursor.com/docs/subagents) |
| Codex V1 allows 1 (`agents.max_depth`); V2 has no depth setting. | confirmed, reworded | `max_depth`: "Maximum nesting depth for V1 agent threads. Ignored by V2." V2 sets no depth limit, but a nested child gets collaboration tools only if its own model's catalog entry is V2. | `config/src/config_toml.rs`; `core/src/config/mod.rs` (`DEFAULT_AGENT_MAX_DEPTH = 1`); `core/src/tools/spec_plan.rs` |
| A Cortex Code background agent cannot spawn background agents. | confirmed | "Background agents cannot spawn other background agents". | [extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility) |
| A Claude Code fork runs the parent's model and ignores a model override. | changed | Runs on the main session's model and effort. No source says a `model` passed on a fork is ignored, so "ignores" was dropped. | [sub-agents](https://code.claude.com/docs/en/sub-agents.md) |
| A Codex spawn inherits the whole conversation by default; pass `fork_turns: "none"` for a clean worker. | changed | True for V2 (`fork_turns` defaults to `all`; only `all` and `none` exist). A full-history fork rejects model and reasoning-effort overrides. V1 uses `fork_context`, which starts clean unless true. | `core/src/tools/handlers/multi_agents_spec.rs`, `multi_agents_v2/spawn.rs`; `prompts/src/multi_agent_instructions.rs` |
| Codex's spawn tool does not count a request for depth or thoroughness as permission. | changed | V1 only. In V2 the rule is a `<multi_agent_mode>` developer message: below Ultra effort (ExplicitRequestOnly), spawn only when the user or applicable AGENTS.md or skill instructions explicitly ask; it drops the depth sentence. At Ultra the mode is Proactive, and a model catalog or `features.multi_agent_v2.multi_agent_mode_hint_text` can replace either text. It is an instruction to the model, not enforced behaviour. "Activating this skill is that permission" still holds. | `multi_agents_spec.rs`; `core/src/session/multi_agents.rs`; `prompts/src/model_messages/multi_agent.rs`; release v0.156.0 (#46264) |
| Claude Code worktree isolation starts from `origin/<default>` unless `worktree.baseRef` is `head`. | confirmed | `fresh` (default) or `head`; with no remote, or `origin/HEAD` neither cached nor fetchable, it falls back to local HEAD. | [worktrees](https://code.claude.com/docs/en/worktrees.md) |
| Claude Code workers run in the background and report through completion notifications. | changed (qualified) | Holds for workers the main conversation spawns. By default (fork mode on), a subagent's own Agent calls run in the foreground in `claude -p`, the Agent SDK, desktop and VS Code (2.1.302); with fork mode off (`CLAUDE_CODE_FORK_SUBAGENT=0`) in `claude -p` or the SDK, nested subagents start in the background and report to the main conversation if they outlast the spawning subagent; in an interactive terminal a subagent waits for its background subagents before finishing. | [sub-agents](https://code.claude.com/docs/en/sub-agents.md), [changelog](https://code.claude.com/docs/en/changelog.md) |
| Use a scripted workflow tool for wide, uniform fan-out when exposed and opted in. | confirmed | Claude Code's `Workflow` tool is in the first tool filter, so subagents other than forks never get it. "Dispatch directly when each step depends on the last" is an inference from the docs' "who decides what runs next" table, not a quoted rule. | [workflows](https://code.claude.com/docs/en/workflows.md), [sub-agents](https://code.claude.com/docs/en/sub-agents.md) |

## New facts added to the section

- **Codex versions.** `MultiAgentVersion::{Disabled, V1, V2}`. `features.multi_agent_v2`
  forces V2; otherwise the model catalog's `multi_agent_version` decides. In
  `models-manager/models.json` at 0.167.2, every picker model is `v2` except gpt-5.6-luna
  (`v1`) and gpt-5.5 (none, so the feature flag gives V1). Feature `multi_agent` (V1) is
  `Stage::Deprecated` on `main`, not in 0.167.2. V2's `spawn_agent` requires `task_name` and
  `message` and takes `fork_turns`; V1's takes `fork_context`. Source:
  `multi_agents_spec.rs`, `Config::multi_agent_version_for_model`.
- **Model and effort, Claude Code.** Order: per-call `model`, definition `model` (`inherit`
  selects the main model), `CLAUDE_CODE_SUBAGENT_MODEL`, main model.
  `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` (2.1.257+) ignores definition `model` fields and refuses
  a per-call model. A per-call `effort` overrides the definition's; `CLAUDE_CODE_EFFORT_LEVEL`
  beats both. [sub-agents](https://code.claude.com/docs/en/sub-agents.md),
  [model-config](https://code.claude.com/docs/en/model-config.md).
- **Model and effort, Codex.** Subagents inherit the parent's model and reasoning effort;
  `agents.default_subagent_model` and `agents.default_subagent_reasoning_effort` set defaults;
  spawn `model` and `reasoning_effort` take precedence.
  [config reference](https://learn.chatgpt.com/docs/config-file/config-reference),
  `config/src/config_toml.rs`.
- **Model, Cursor and Cortex Code.** Cursor: set in the subagent definition, `model` or
  `inherit`. Cortex Code: the subagent definition sets `model` (or `inherit`); the `task`
  tool call accepts `model: "inherit"` (1.1.52), and no other per-call model is documented.
  `CORTEX_AGENT_MODEL` "Overrides model selection" (settings page); the docs do not say
  whether that reaches workers.
  [subagents](https://cursor.com/docs/subagents);
  [extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility) and
  changelog 1.1.52.
- **Worktrees.** Codex: "All agents use the same current working directory"
  (`prompts/src/multi_agent_instructions.rs`). Cursor: "Subagents share the parent agent's
  checkout by default"; isolation is a local worktree or a cloud VM; base undocumented
  ([subagents](https://cursor.com/docs/subagents)). Cortex Code: isolation is requested in
  the prompt, on branch `agent/<agentId>`
  ([extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility));
  `--worktree-base` chooses the start revision (changelog 1.2.14, 2026-10-12), but where the
  flag goes and the default base are undocumented.
- **Completion.** Codex V2: the child's final answer reaches the parent automatically;
  `wait_agent` "Does not return the content" (`multi_agents_spec.rs`). Cursor: "Background
  subagents write output to `~/.cursor/subagents/`. The parent agent can read these files"
  ([subagents](https://cursor.com/docs/subagents)). Cortex Code: "When the agent completes, you
  can retrieve its output using its ID"
  ([extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility)).
- **Resume.** Claude Code: Explore and Plan "are one-shot and return no agent ID"; a subagent
  the user stopped refuses a message
  ([sub-agents](https://code.claude.com/docs/en/sub-agents.md)). Codex V2: `followup_task`
  triggers a turn if the target is idle; `send_message` does not (`multi_agents_spec.rs`).
  Cursor: "You can resume a subagent after it completes" by agent ID
  ([subagents](https://cursor.com/docs/subagents)). Cortex Code: "You can resume a killed
  agent using its ID"
  ([extensibility](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility)).
- **Project instructions and skills.** Claude Code subagents load the CLAUDE.md hierarchy and
  `AGENTS.md` files; "The built-in Explore and Plan agents skip this", as do definitions with
  `omitClaudeMd: true`; background subagents keep `Skill`
  ([sub-agents](https://code.claude.com/docs/en/sub-agents.md)). Codex passes
  `inherited_instructions()` to the child (`core/src/agent/control/spawn.rs`); docs: "Skills
  inherit from the parent" ([subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)).
  Cursor and Cortex Code document neither, so the notes tell the coordinator to carry the
  project rules a task needs in the handoff.
- **Workflows.** Claude Code workflows run "Up to 16 concurrent agents by default, fewer when
  Claude Code has fewer CPUs", set by `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` (1 to 256),
  separate from the 20-subagent cap
  ([workflows](https://code.claude.com/docs/en/workflows.md)).

## Left out, with reasons

- Claude Code agent teams: experimental and off by default
  (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`).
- Ultracode lifting Claude Code's 20 cap, and Codex Ultra-effort proactive delegation: a
  coordinator under this skill does not act on either.
- `CLAUDE_CODE_SUBAGENT_EFFORT` and `isolation: "remote"`: no docs page describes them.
- Codex wait timeouts (default 30 s, `features.multi_agent_v2.{default,min,max}_wait_timeout_ms`),
  Cortex Code `tools:` casing and `model: auto`, Cursor's "Start with 2-3 focused subagents":
  detail a coordinator does not act on.
- What Cortex Code does with a 51st spawn, and whether Cursor or Cortex Code subagents load
  rules files: undocumented, so nothing is asserted.

## Open questions from the research

- Whether Codex will document `features.multi_agent_v2.*`; the public docs describe only the
  `agents.*` key, which excludes the primary thread (openai/codex#40211 tracks the gap).
- When Codex V1 (`multi_agent`) goes away: it is deprecated on `main` but not in 0.167.2, and no
  release note gives a date.
- Cortex Code: the parameter that selects an autonomous or non-autonomous agent and its
  default; whether `--worktree-base` is a startup flag or a tool parameter, and the default
  base; how deep foreground subagents can nest (changelog 1.1.8 mentions "subagent spawn
  chains"); whether a background agent can spawn foreground subagents.
- Cursor: whether built-in or background subagents can surface a question; the base revision
  of an isolated worktree.
- Cortex Code naming: the tools page calls the spawn tool `RunSubagent`, the changelog (1.1.52)
  calls it `task`.
