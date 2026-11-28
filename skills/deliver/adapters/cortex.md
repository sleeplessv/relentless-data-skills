# Deliver on Cortex Code

Read this before you start an agent. Where the skill names a Claude Code step, do this instead.

- Start the reader with `task`. `task` runs the agent in the background, and a headless session
  that ends first cancels it before it writes anything. So wait for it: run it in the
  foreground, or call `agent_output` with wait set.
- Call an agent back with `task` and `resume: <agent id>`. Under `--private` that fails with
  "Agent session '<id>' not found"; start a fresh agent and give it the earlier report.
- Typed-only is asked, not enforced. Cortex Code has no switch that keeps the model from starting
  `deliver` from its description. A run the model started goes through the same preflight, guard
  and merge script as a typed one.
- The reader's file withholds the edit and agent-start tools in its lowercase `tools` list.
- The reader's file names no effort: Cortex Code takes one effort per process, so the agent runs
  at the session's effort.
- The guard knows an agent by the `agent_id` in its hook input, so only you can run
  `deliver.py merge`.
