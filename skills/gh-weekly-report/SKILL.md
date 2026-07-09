---
name: gh-weekly-report
description: Generate a weekly GitHub activity report — the authenticated user's issues, PRs, reviews, and commits across one account's repos, bucketed into canonical work types, rendered as a self-contained interactive HTML file with drill-down. Use when the user asks what they did this week, for a weekly report or activity summary, or to report on their GitHub work.
metadata:
  author: sleeplessv
disable-model-invocation: true
---

# GitHub Weekly Report

One actor's week across one owner's repos, as a fixed-layout interactive
HTML report: headline counters with week-over-week deltas, canonical work
buckets, per-repo breakdown, and click-through drill-down to every issue,
PR, review, and commit. Week 27 looks exactly like week 26 — the eye goes
straight to what changed.

Everything deterministic lives in two bundled stdlib-only scripts; the
agent's job is judgment: bucketing the work and summarising the week.

## Step 1 — Resolve parameters

- **Actor** — the authenticated `gh` user; **owner** — the owner of the
  current repo's `origin` remote. The user may override either
  (`owner=someorg`, `actor=somebody`). Never read these from committed
  config, and never commit them.
- **Window** — last complete Mon–Sun week, UTC. An explicit range
  ("from 2026-06-29 to 2026-07-05", "this week so far") maps to
  `--from`/`--to`.

Done when actor, owner, and window are stated to the user in one line.

## Step 2 — Collect

```bash
python3 <skill-dir>/scripts/collect.py --out <scratchpad>/gh-weekly \
  [--owner O] [--actor A] [--from YYYY-MM-DD --to YYYY-MM-DD]
```

Emits `week.json` — report week plus the week before, already
rule-applied: *resolved* means the actor closed it as `completed`
(not-planned closes and abandoned PRs are separate lines), reviews are
window-checked, commits are attributed to their PR or marked direct
pushes. Surface any stderr warnings (result caps) to the user — a capped
search means missing items. Done when `week.json` exists.

## Step 3 — Bucket

Assign **every** item in `week.json`'s `current` period to one bucket:

- **feature** — new capability
- **fix** — corrects wrong behaviour
- **refactor** — restructures without behaviour change
- **docs** — documentation, ADRs, glossaries
- **chore/infra** — CI, build, dependencies, tests, housekeeping
- **triage/review** — reviews given, not-planned/wontfix closes, label work
- **other** — a deliberate judgment that nothing above fits

Each item carries a `signal` (conventional-commit prefix) and `labels` —
strong hints, not verdicts; read the title and overrule a misleading
prefix. List the item keys first (e.g.
`python3 -c "..."` over `week.json`) and write
`buckets.json` mapping every key to a bucket. Done when every
current-period key appears in `buckets.json` — an item missing from the
mapping would silently land in `other`, so absence is a bug, not a choice.

## Step 4 — Render and open

```bash
python3 <skill-dir>/scripts/render.py --data <...>/week.json \
  --buckets <...>/buckets.json --out <tmpdir>/gh-week-<iso_week>-<owner>.html
```

Write to the OS temp dir (`$TMPDIR`, fall back to `/tmp`) unless the user
named a destination, and copy `week.json` beside the report — it is the
re-render receipt; on tweak requests re-run render from it instead of
re-collecting. Print the absolute paths of both files and open the report
(`open` / `xdg-open` / `start`; on failure just say so).

## Step 5 — Summarise

Close with a few sentences in chat: the headline numbers with their
deltas, the dominant bucket, and anything the counters hide (a capped
search, a week dominated by one repo, all-direct-push weeks). The report
carries the detail; the summary carries the story.
