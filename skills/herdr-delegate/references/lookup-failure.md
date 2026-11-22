# When `hc get` fails

Read this when step 1's block printed `hc get failed: <code>` with
`HC_TERMINAL_ID` set. Go by the error `hc get` printed above that line, not
the exit code: the exit code alone does not tell a sandbox denial from other
failures.

## The sandbox blocked it

The error says `cannot open core lock: Operation not permitted`. Your
sandbox, such as Codex's `workspace-write`, stopped `hc` from opening the
core lock. You are still inside herdr-core.

Ask for approval to rerun the same lookup outside the sandbox: in Codex, run
step 1's block again as one command with escalated permissions.

- **The rerun prints no `hc get failed:` line**: go back to step 1 and read
  the labels, as after a first run with no such line, hidden worker included.
- **You cannot ask, the user declines, or the rerun prints `hc get failed:`**:
  stop before any launch. Tell the user the sandbox blocked `hc get`, show
  its error, and name the approval it needs.

## Any other error

Stop before any launch, and show the user the error `hc get` printed.
