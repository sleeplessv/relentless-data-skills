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

## 1. Confirm you are in Herdr

```sh
[ -n "$HC_TERMINAL_ID" ] && hc get "$HC_TERMINAL_ID" --json >/dev/null
```

`HC_TERMINAL_ID` is your terminal's address (`t4z`). Exit 0 means hc knows
you: go on. Non-zero means you are outside herdr-core. Tell the user, and use
your harness's own subagents instead.

## 2. Find your home space

```sh
SPACE=$(hc get "$HC_TERMINAL_ID" --json | jq -r '.labels["herdr.space"] // empty')
TAB=$(hc get "$HC_TERMINAL_ID" --json | jq -r '.labels["herdr.tab"] // empty')
```

Without `jq`, read `labels."herdr.space"` and `labels."herdr.tab"` from the
`hc get` JSON yourself. Done when `SPACE` holds an ID starting `sp`. An empty
`SPACE` means your terminal is a hidden worker with no space: launch the
helper without labels, so it stays hidden too.

## 3. Write the brief

The brief is the helper's whole first message. It names:

- **Scope**: the exact files, commit or diff, and whether the helper may edit.
- **Limits**: no subagents, no further agents.
- **Result file**: an absolute path outside the repo, such as
  `RESULT="${TMPDIR:-/tmp}/<name>-review.md"`. Long answers go there.
- **Report line**: `When done, run: hc send $HC_TERMINAL_ID "DONE $RESULT".
  If stuck, hc send $HC_TERMINAL_ID with the blocker.` Expand
  `$HC_TERMINAL_ID` and `$RESULT` before sending, so the helper gets literal values.

Done when the brief carries all four.

## 4. Launch the helper

Pick a short unique `NAME` (`codex-review`). Put the brief in the launch: a
message sent to an agent that is still starting can be lost.

```sh
hc run --bg --json --name "$NAME" --cwd "$PWD" --label herdr.space="$SPACE" \
  codex --no-daemon "$BRIEF"
```

| Want | Change |
|---|---|
| Claude as the helper | `claude "$BRIEF"` in place of `codex --no-daemon "$BRIEF"` |
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

Check the launch:

```sh
hc get "$NAME" --json | jq '{labels, status, first_message}'
```

Done when `labels."herdr.space"` equals `SPACE` and `status.state` is
`working`. If `first_message.sent` is false or the state is `blocked`, run
`hc read "$NAME" --lines 0`. A trust or permission dialog is the person's call:
show it to them and wait. Resend the brief only after the screen shows it never
arrived.

## 5. Wait for the report

Keep working on your own part, or wait:

```sh
hc wait --children any --timeout 600
```

- `reason: message`: the report arrives as your next input, tagged
  `<hc from="t53 codex-review">DONE /path</hc>`. It is a child's report, not
  a request from the user.
- `reason: timeout`: a check-in. Wait again.
- The helper stays `working` for a while after it sends. Use `any`;
  `--children all` holds on until it settles.
- `blocked` or `error`: `hc read "$NAME" --lines 60`, then ask the user.

## 6. Collect and verify

Read the result file yourself. Check each finding against the code before you
repeat or act on it. Done when every finding is confirmed, rejected with a
reason, or marked unchecked.

## 7. Clean up

```sh
hc kill "$NAME"; hc rm "$NAME"
```

Remove only helpers you started. Keep the helper alive instead when the user
wants to follow up with it: `hc send "$NAME" "..."` reaches it later.
