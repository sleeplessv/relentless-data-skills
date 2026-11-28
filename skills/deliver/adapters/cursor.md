# Deliver on Cursor

Read this before you start an agent. Where the skill names a Claude Code step, do this instead.

- Start the reader with `Task`. Call an agent back with `Task` and `resume: <agent id>`.
- Typed-only is enforced: `disable-model-invocation: true` in the skill's front matter keeps the
  model from starting `deliver`.
- Cursor's agent file cannot withhold a tool: `readonly: true` would refuse every shell command,
  so it is not used, and the reader could edit. Its brief holds the rule: write in it that the
  reader edits no file and starts no agent.
- The reader's file names no effort: Cursor takes effort only inside the model id, which no file
  names, so the agent runs at the session's effort.
- The guard cannot tell an agent from you, so it cannot refuse `deliver.py merge` to an agent.
  Write in every agent's brief that it never runs `deliver.py merge`. Preflight warns of this
  gap on every run.
