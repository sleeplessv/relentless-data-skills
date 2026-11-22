# Waiting on a helper

A helper gets 30 minutes from its launch to report. Read this before each
wait in step 4, and each time a wait returns without a report from `ID`.
`ID` is the helper's address from step 3.

## Set the timeout

Print the seconds left before the limit:

```sh
hc get "$ID" --json | jq '1800 - (now - .created_ms / 1000 | floor)'
```

- `created_ms` is the helper's launch time in Unix milliseconds. The count
  runs from it, so a wait that starts late, or that runs again after a
  wake-up, keeps the same limit.
- Write the number into the wait as `<left>`. The background wait takes
  `--timeout <left>`. The foreground and subagent waits take
  `--timeout <check>`, the smaller of `<left>` and 180, so they check in at
  least every 180 s and never after the limit.
- Without `jq`, work out `<left>` from `created_ms` yourself. With `jq`,
  no number means hc cannot reach `ID`: tell the user.
- At 0 or less the limit has passed: do not wait. Run `hc get "$ID" --json`
  and take the rows below, as for a wait that returned with `reason`
  `timeout`.

## When a wait returns without a report

First handle anything else that woke you, such as another helper's report
or a message to you. It does not move the limit. Then run
`hc get "$ID" --json` and take the first row that fits:

| `ID` | Do |
|---|---|
| `hc get` exits non-zero (3, `not_found`) | hc cannot reach `ID`: tell the user |
| `state` `finished`: it exited | `hc read "$ID" --lines 60`; report the exit to the user |
| `status.state` `blocked` or `error` | `hc read "$ID" --lines 60`, then ask the user |
| `status.state` `idle` or `done` | `hc read "$ID" --lines 60`. If `RESULT` holds the helper's report, go to step 5; a DONE that arrives later is the same news. Otherwise show the user the screen and ask |
| `status.state` `working` | Print `<left>` again. If the wait's `reason` is `timeout`, or `<left>` is 0 or less, take the check-in. Otherwise set the timeout and wait again |
| Anything else, such as `status` `null`: no agent status | `hc read "$ID" --lines 60`; show the user the screen and ask |

## Check-in

Read the screen with `hc read "$ID" --lines 0`. While `ID` is `working`,
it returns only the visible screen, so ask for no history. Keep the screen,
so that the next check-in can compare against it. When you compare, ignore
elapsed-time counters such as `Running… (16s)`. Take the first row that fits:

| The screen shows | Do |
|---|---|
| The same output repeating, or, after the first check-in, no change since the last one: the helper is stuck | Run `hc interrupt "$ID" --json`. Show the user the screen and ask what to do |
| Anything else, `<left>` at 0 or less | Show the user the screen and ask whether to keep waiting. Do not interrupt the helper. If they say keep waiting, extend the limit as below, then set the timeout and wait again |
| Anything else, `<left>` above 0 | Set the timeout and wait again with the same wait |

To extend the limit, print the seconds since launch when the answer
arrives, however late:

```sh
hc get "$ID" --json | jq 'now - .created_ms / 1000 | floor'
```

No number means hc cannot reach `ID`: tell the user. Otherwise add the
time the user names, in seconds, or 1800, and write the sum in place of the
limit (1800 at first) in the command under "Set the timeout".

`hc interrupt` presses the helper's stop key and watches 10 s for an effect.
It exits 0 and prints `"outcome":"stopped"` when the turn ended; then
`hc get "$ID" --json` exits 0 and shows `status.state` `idle`. A non-zero
exit (3 when hc cannot reach `ID`), or any other outcome, such as
`still_working`, goes to the user with the screen. The helper stays alive
with its context, so the user can steer it with `hc send "$ID" "..."`. Kill
the helper only when the user says so: a kill throws its context away.
