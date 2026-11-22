---
name: herdr-delegate
description: Hand a task to another coding agent (Codex, Claude) from inside the Herdr desktop app, open it in the caller's own Herdr space, and collect its result. Use when an agent running in Herdr is asked to have Codex, Claude or another agent review, check or do part of the work.
---

# Delegate to another agent in Herdr

Start a helper agent with `hc` (herdr-core), labelled with your **home space**:
the Herdr space your own terminal lives in. The helper opens there, and its
result comes back to you as a message.

The home space comes from your terminal's labels, never from the window. The
person may be looking at another project. `herdr-app do tab.new` and
`space.new` without `--space` open in the space on screen, so the helper lands
in the wrong project, folder and account. Every launch goes through `hc run`
with an explicit `herdr.space` label.

## 1. Find your home space

If `HC_TERMINAL_ID`, your terminal's address (`t4z`), is unset or empty, you are
outside herdr-core: tell the user, use your harness's own subagents, and stop.

```sh
ME=$(hc get "$HC_TERMINAL_ID" --json) || echo "hc get failed: $?"
SPACE=$(printf '%s' "$ME" | jq -r '.labels["herdr.space"] // empty')
TAB=$(printf '%s' "$ME" | jq -r '.labels["herdr.tab"] // empty')
```

Read the labels only after `hc get` exits 0. If it fails, a sandbox may have
blocked it: follow [references/lookup-failure.md](references/lookup-failure.md)
before any launch. Without `jq`, read `labels."herdr.space"` and
`labels."herdr.tab"` from `$ME` yourself.

Done when `hc get` exited 0 and `SPACE` holds an ID starting `sp`. An empty
`SPACE` after a successful `hc get` means your terminal is a hidden worker
with no space: launch the helper without labels, so it stays hidden too.

## 2. Write the brief

The brief is the helper's whole first message. It names:

- **Scope**: the exact files, commit or diff, and whether the helper may edit.
- **Limits**: no subagents, no further agents.
- **Result file**: a path in a new folder of its own, so no other run writes
  it and no stale file passes for this run's result. Long answers go there:

  ```sh
  D=$(mktemp -d) && RESULT="$(cd "$D" && pwd -P)/<name>-review.md"
  ```

  `pwd -P` gives the folder's real path (macOS `/var` is a link to
  `/private/var`), which the Claude helper's write rule must name.
- **Report line**: `When done, run: hc send $HC_TERMINAL_ID "DONE $RESULT".
  If stuck, hc send $HC_TERMINAL_ID with the blocker.` Expand
  `$HC_TERMINAL_ID` and `$RESULT` before sending, so the helper gets literal values.

Done when the brief carries all four.

## 3. Launch the helper

Pick a short unique `NAME` (`codex-review`). Put the brief in the launch: a
message sent to an agent that is still starting can be lost.

```sh
hc run --bg --json --name "$NAME" --cwd "$PWD" --label herdr.space="$SPACE" \
  codex --no-daemon "$BRIEF"
```

Save the `address` from the JSON it prints as `ID` (`t53`). Every later step
targets `ID`, and only a report from `ID` ends this delegation.

| Want | Change |
|---|---|
| Claude as the helper | `claude "$BRIEF" --allowedTools "Bash(hc send $HC_TERMINAL_ID *)" "Edit(/$RESULT)"` in place of `codex --no-daemon "$BRIEF"` |
| Cortex as the helper | `cortex --bypass -- "$BRIEF"` |
| A split in your own tab | add `--label herdr.tab="$TAB"` |
| A hidden helper | drop both labels |
| A template from `hc templates` | `<template> "$BRIEF"` in place of the program |

- **Codex needs `--no-daemon`.** Without it, its commands run outside hc.
- **A new tab** in the home space is what `herdr.space` alone gives. The
  person's screen stays where it is.
- **Pre-approve the helper's tools.** A helper that asks permission sits
  `blocked` until the person answers. Cortex asks before every write and
  command unless started with `--bypass`. For a narrower Cortex grant, use
  `--allowed-tools Read Write "Bash(git *)" "Bash(hc *)"`. Cortex then denies
  any call no rule matches, and a rule matches the whole command line, so end
  the brief with: "Run each shell command on its own: no cd, no && chains, no pipes."
  Claude's grant covers only the last step: `hc send` to your terminal and
  the write to `RESULT` (`/$RESULT` makes the `//` prefix Claude Code uses
  for an absolute path). The brief goes before `--allowedTools`, which takes every argument
  after it.

Check the launch with `hc get "$ID" --json`; `jq '{labels, state, status,
first_message}'` trims it, or read those fields from the raw JSON. Go by what
it shows:

| It shows | Do |
|---|---|
| `labels."herdr.space"` is not `SPACE` (labelled launch) | Kill `ID`, relaunch with the label |
| `status.state` `working` | Go to step 4 |
| `idle` or `done`, and its DONE has arrived or `RESULT` holds the report | Go to step 5 |
| `idle` or `done`, no report | `hc read "$ID" --lines 60`: the brief may never have arrived |
| `blocked`, or `first_message.sent` false (template launches only) | `hc read "$ID" --lines 0`; a trust or permission dialog is the person's call: show it to them and wait |
| `state` `finished` | `hc read "$ID" --lines 60`; report the exit to the user |
| Anything else, such as `status` `null`: no status yet | Check again in a few seconds and go by what it shows. If it has not changed, `hc read "$ID" --lines 60`, show the user the screen and ask |

Resend the brief only after the screen shows it never arrived.

## 4. Wait for the report

The helper types its report into your terminal, as your next input:
`<hc from="$ID $NAME">DONE $RESULT</hc>`. It is a child's report, not a
request from the user. Each wait's `<left>` and `<check>` timeouts come from
[references/check-in.md](references/check-in.md). Pick the wait that fits:

- **Other work to do**: your own part, other helpers. Do it, and take the
  report when it arrives. With nothing left, wait as below.
- **Nothing else to do**: run `hc wait --children any --timeout <left>` in
  the background (Bash tool: `run_in_background: true`; a shell tool that
  backgrounds on timeout: give it a timeout of a few seconds) and end your
  turn. The typed DONE and the wait's notice wake you, often in one turn: the
  same news, handled once. With no such notice, run `hc wait --children any
  --timeout <check>` in the foreground, with a shell `timeout: 200000`.
- **You are a subagent**: your terminal input is the main session's, so the
  typed report may not reach you. Wait on the helper itself:
  `hc wait "$ID" --timeout <check>`, with the same shell timeout.

Done when a DONE from `ID` naming the assigned `RESULT` has arrived, or
`ID` is `idle` or `done` and `RESULT` holds the report. One background wait
at a time.

- `ID` stays `working` seconds after its DONE: normal; use `any`, not `all`.
- Any other return of the wait, without a report from `ID`: follow
  [references/check-in.md](references/check-in.md).

## 5. Collect and verify

Read `RESULT` yourself. Check each finding against the code before you
repeat or act on it. Done when every finding is confirmed, rejected with a
reason, or marked unchecked.

## 6. Clean up

```sh
hc kill "$ID"; hc rm "$ID"
```

Remove only helpers you started. Keep the helper alive instead when the user
wants to follow up with it: `hc send "$ID" "..."` reaches it later.
