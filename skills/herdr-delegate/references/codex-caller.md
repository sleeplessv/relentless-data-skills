# Find your terminal as Codex

A shared Codex app-server inherits the Herdr terminal ID of the session that
started it. That ID can still point to a live terminal in another space.

## Check how this shell was started

Run this block in one shell call. It walks from the shell's process ID
(`pid`) to PID 1, checking each program and its arguments for a managed daemon.

```sh
pid=$$
while [ "$pid" != 1 ]; do
  program=$(ps -o comm= -p "$pid") || exit 1
  args=$(ps -o args= -p "$pid") || exit 1
  case "${program##*/}:$args" in
    codex:*" app-server "*--managed-daemon*) echo managed-daemon; exit 0 ;;
  esac
  parent=$(ps -o ppid= -p "$pid") || exit 1
  pid=${parent##* }
  case "$pid" in ''|0|*[!0-9]*) echo "Invalid parent PID: $parent" >&2; exit 1 ;; esac
done
printf 'CALLER=%s\n' "${HC_TERMINAL_ID:-}"
```

Use the output only on exit 0:

- `CALLER=…` (including empty): resume step 1 with the inherited
  `HC_TERMINAL_ID`. Step 1 handles an empty ID as outside Herdr.
- `managed-daemon`: identify the terminal below.

If the sandbox denies `ps`, request approval to rerun the whole block outside
the sandbox. If the lookup still fails or approval is unavailable, stop before
launch and report the error.

## Identify a managed-daemon caller

Run `hc ls --json`. On a sandbox denial, request approval to rerun that
lookup outside the sandbox. Continue only on exit 0 with a live terminal list.
If the lookup fails, stop and report the error.

Show the user the `address`, `where` and `cwd` of the live `terminals` entries
whose `agent` is `codex`. A matching working directory can help the user find
their terminal. Ask which address is theirs, even for a single match, and
include “outside Herdr” as a choice. With no candidates, or if the user
identifies none as theirs, use the outside-Herdr fallback in step 1.

When the user confirms a listed address, start **every subsequent shell call**
in this delegation with `export HC_TERMINAL_ID=<confirmed-address>;`, replacing
the placeholder with the literal address. Each call starts a fresh shell. Resume
step 1 with that ID for the space lookup, the brief, the helper name and parent,
and the wait.
