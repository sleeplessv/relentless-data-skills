# Find your terminal as Codex

Read this before step 1 when you are Codex.

A Codex TUI (0.17x) runs your shell commands in a shared
`codex app-server --managed-daemon` process, not in its own terminal. That
daemon keeps the environment of the terminal that started it, so the
`HC_TERMINAL_ID` your commands see belongs to that terminal, which may be in
another space or already closed. With that address, `hc get` fails with
`not_found` or reads another terminal's space, the helper gets no parent (so
`hc wait --children` never sees it), and its report goes to the wrong terminal.
Codex started with `--no-daemon` runs commands in its own terminal and passes
this check unchanged.

## Find the caller

Run as one command:

```sh
CALLER=$HC_TERMINAL_ID; p=$$
while [ "${p:-0}" -gt 1 ]; do
  case "$(basename "$(ps -o comm= -p "$p")"):$(ps -o args= -p "$p")" in
    codex:*" app-server "*--managed-daemon*)
      CALLER=
      LS=$(hc ls --json) || echo "hc ls failed: $?"
      CALLER=$(printf '%s' "$LS" | jq -r --arg cwd "$PWD" '[.terminals[]? |
        select(.agent == "codex" and .cwd == $cwd)] | if length == 1 then .[0].address else empty end')
      break ;;
  esac
  p=$(ps -o ppid= -p "$p" | tr -d ' ')
done
echo "CALLER=$CALLER"
```

- `p` walks from this shell up its parent processes. A daemon is a process
  whose program is `codex` and whose arguments hold `app-server` and
  `--managed-daemon`; the program check keeps this shell, whose arguments hold
  this text, from matching. No daemon among them: `CALLER` stays `HC_TERMINAL_ID`.
- A daemon among them: `CALLER` is the one live terminal whose program is
  Codex and whose folder is your `PWD`, or empty when there is none or more than one.
- `hc ls failed:` means a sandbox may have blocked `hc`: follow
  [lookup-failure.md](lookup-failure.md) for this command, as for `hc get`.
- Without `jq`, read `hc ls --json` yourself: the `terminals` entry with
  `agent` `codex` and `cwd` equal to your `PWD`.

Done when the block printed `CALLER=t…` and no `hc ls failed:` line. An empty
`CALLER`: show the user the `address` and `where` of each `agent` `codex`
terminal in `hc ls --json`, ask which one is yours, and use that address.

## Use it

When `CALLER` differs from `HC_TERMINAL_ID`, start every later shell command
in this delegation with `export HC_TERMINAL_ID=<CALLER>;`, the address
written out. Each command runs in a fresh shell, so the export does not carry
over. Then step 1's `hc get`, the brief's report line, the helper's name, and
`hc run`'s parent all use your own terminal.
