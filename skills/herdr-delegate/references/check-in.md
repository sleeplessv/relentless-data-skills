# Wait deadline and check-ins

A helper gets 30 minutes from its launch to report. Step 4 reads this file
before each wait, and again each time a wait returns without a report from
`ID`. `ID` is the helper's address from step 3.

## Before each wait

Set the seconds left before the deadline, and the check-in for the
foreground and subagent waits:

```sh
LEFT=$(hc get "$ID" --json | jq --argjson limit "${LIMIT:-1800}" '$limit - (now - .created_ms / 1000 | floor)')
CHECK=$(( LEFT < 180 ? LEFT : 180 ))
```

- `LIMIT` is the deadline in seconds after launch: 1800 unless the user
  extended it (step 2 below).
- `created_ms` is the helper's launch time in Unix milliseconds. `LEFT`
  counts from it, not from the wait, so a wait that starts late, or that runs
  again after a wake-up, keeps the same deadline.
- The background wait takes `--timeout "$LEFT"`. The foreground and subagent
  waits take `--timeout "$CHECK"`, so they check in at least every 180 s
  and never after the deadline.
- An empty `LEFT` means hc cannot reach `ID`: `hc get` exits 3 with its
  error on stderr, and `jq` prints nothing. Report that to the user.
  Without `jq`, work out `LEFT` from `created_ms` yourself.
- `LEFT` at 0 or less: the deadline has passed. Do not wait; go to the
  check-in below.

## Each time a wait returns without the report

1. Set `LEFT` again. If the wait returned for another helper's report or a
   message to you, and `LEFT` is above 0, wait again. Otherwise this is a
   check-in: continue.
2. Read the helper's screen with `hc read "$ID" --lines 0`. While `ID` is
   `working`, it returns only the visible screen, so ask for no history. A
   non-zero exit means hc cannot reach `ID`: report that to the user. Keep
   the screen, so that the next check-in can compare against it. Then take
   the first row that fits:

   | The screen shows | Do |
   |---|---|
   | The same output repeating, or no change since the last check-in: the helper is stuck | Run `hc interrupt "$ID" --json`. Show the user the screen and ask what to do |
   | Progress, `LEFT` at 0 or less | Show the user the screen and ask whether to keep waiting. Do not interrupt the helper. If they say keep waiting, set `LIMIT` to the seconds since launch plus the time they name, or plus 1800, and wait again |
   | Progress, `LEFT` above 0 | Wait again with the same wait |

   When you compare screens, ignore elapsed-time counters such as
   `Running… (16s)`. At the first check-in there is no earlier screen, so
   only repeating output counts as stuck.

`hc interrupt` presses the helper's stop key and watches 10 s for an effect.
It exits 0 and prints `"outcome":"stopped"` when the turn ended; then
`hc get "$ID" --json` exits 0 and shows `status.state` `idle`. A non-zero
exit (3 when hc cannot reach `ID`), or any other outcome, such as
`still_working`, goes to the user with the screen. The helper stays alive
with its context, so the user can steer it with `hc send "$ID" "..."`. Kill
the helper only when the user says so: a kill throws its context away.
