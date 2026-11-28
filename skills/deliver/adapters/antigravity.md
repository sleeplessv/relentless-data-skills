# Deliver on Antigravity

Read this before you start an agent. Where the skill names a Claude Code step, do this instead.

- Start the reader with `invoke_subagent`. Call an agent back with `send_message` to its
  conversation id.
- Typed-only is asked, not enforced. Antigravity has no switch that keeps the model from starting
  `deliver`; the description asks that it start only when typed.
- The reader's file withholds the edit and agent-start tools in its `tools` list, in
  Antigravity's tool names.
- The reader's file names no effort, and its model tier is `inherit`: the agent runs on the
  session's model and effort.
- The guard knows an agent by the file Antigravity writes for each agent it starts, and refuses
  `deliver.py merge` to an agent. That file is undocumented, so also write in every agent's brief
  that it never runs `deliver.py merge`.
