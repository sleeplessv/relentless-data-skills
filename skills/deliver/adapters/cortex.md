# Deliver on Cortex Code

Read this before you start an agent. Where the skill names a Claude Code step, do this instead.

- Start the reader with `task`. `task` runs the agent in the background, and a headless session
  that ends first cancels it before it writes anything. So wait for it: run it in the
  foreground, or call `agent_output` with wait set.
- Start the two reviewers in one step with two `task` calls, then wait for each with `agent_output`
  and wait set: the foreground form runs them one after the other.
- A call-back is a fresh agent started with `task`, never a resumed one.
- Typed-only is not enforced, and the skill's description does not ask for it. Cortex Code has no
  switch that keeps the model from starting `deliver` from its description. A run the model started goes through the same preflight, guard
  and merge script as a typed one.
- The reader's file withholds the edit and agent-start tools in its lowercase `tools` list.
- The reader's file names no effort: Cortex Code takes one effort per process, so the agent runs
  at the session's effort.
- The guard knows an agent by the `agent_id` in its hook input, so only you can run
  `deliver.py merge`.
