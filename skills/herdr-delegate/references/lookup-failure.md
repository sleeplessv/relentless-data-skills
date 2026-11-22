# When `hc get` fails

Read this when step 1's `hc get "$HC_TERMINAL_ID" --json` exits non-zero
with `HC_TERMINAL_ID` set. Go by the error it printed, not the exit code:
the exit code alone does not tell a sandbox denial from other failures.

## The sandbox blocked it

The error says `cannot open core lock: Operation not permitted`. Your
sandbox, such as Codex's `workspace-write`, stopped `hc` from opening the
core lock. You are still in Herdr.

Ask for approval to rerun the same lookup outside the sandbox: in Codex, run
step 1's block again as one command with escalated permissions.

- **It exits 0**: go back to step 1 and read the labels, as after a first
  run that exits 0, hidden worker included.
- **You cannot ask, the person declines, or the rerun fails**: stop before
  any launch. Tell the user the sandbox blocked `hc get`, show its error,
  and name the approval it needs.

## Any other error

Stop before any launch, and show the user the error `hc get` printed.
