# Timeout check-in with no report

Read this when a wait in step 4 returns because it timed out, while `ID` is
still `working` and no report from `ID` has arrived. `ID` is the helper's
address from step 3.

## The 30-minute limit

A helper gets 30 minutes from its launch to report. Count from the launch
time, `created_ms` in `hc get "$ID" --json`, so another helper's report or
a message to you does not restart the count. Each wait in step 4 reaches the
limit:

- The background wait, `hc wait --children any --timeout 1800`, checks in
  at the limit.
- The foreground wait and the subagent's `hc wait "$ID"` check in every
  180 s (hc's `wait_timeout`), so about the tenth check-in passes the limit.

## At each check-in

1. Read the helper's screen and the whole minutes since its launch:

   ```sh
   hc read "$ID" --lines 0
   hc get "$ID" --json | jq '(now * 1000 - .created_ms) / 60000 | floor'
   ```

   While `ID` is `working`, `hc read` returns only the visible screen, so
   ask for no history. Without `jq`, subtract `created_ms` (Unix time in
   milliseconds) from the current time yourself. A non-zero exit from either
   command means hc cannot reach `ID`: report that to the user. Keep the
   screen, so that the next check-in can compare against it.

2. Take the first row that fits:

   | The screen shows | Do |
   |---|---|
   | The same output repeating, or no change since the last check-in: the helper is stuck | Run `hc interrupt "$ID" --json`. Show the user the screen and ask what to do |
   | Progress, 30 or more minutes since launch | Show the user the screen and ask whether to keep waiting. Do not interrupt the helper |
   | Progress, under 30 minutes since launch | Wait again with the same wait |

`hc interrupt` presses the helper's stop key and watches 10 s for an effect.
It prints `"outcome":"stopped"` when the turn ended, and `hc get "$ID" --json`
then shows `status.state` `idle`. Any other outcome goes to the user with the
screen. The helper stays alive with its context, so the user can steer it with
`hc send "$ID" "..."`. Kill the helper only when the user says so: a kill
throws its context away.
