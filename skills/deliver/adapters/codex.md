# Deliver on Codex

Read this before you start an agent. Where the skill names a Claude Code step, do this instead.

- Start the reader with `spawn_agent` and `fork_turns: "none"`, so that it starts with a fresh
  context, then wait for it with `wait_agent`. Call an agent back with `followup_task`.
- Typed-only is enforced: `allow_implicit_invocation: false` in the skill's `agents/openai.yaml`
  keeps the model from starting `deliver`.
- Codex's agent file cannot withhold a tool, so the reader could edit. Its brief holds the rule:
  write in it that the reader edits no file and starts no agent.
- The reader's file sets effort `high`.
- The guard knows an agent by the `agent_id` in its hook input, so only you can run
  `deliver.py merge`. Codex runs no hook its owner has not trusted, and asks again after each
  change to the hook file. When preflight stops with `preflight.guards-off`, ask the owner to
  trust the `deliver` hook in Codex.
