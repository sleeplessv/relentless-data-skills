---
name: gh-weekly-report
description: Generate a weekly GitHub activity report covering everything the authenticated user did on GitHub (issues, PRs, reviews, commits, discussions), optionally narrowed to one owner's repos, bucketed into canonical work types with per-repo narratives, rendered as an interactive HTML file (data embedded; styling and charts load from CDNs, so full rendering needs network). Use when the user asks what they did this week, for a weekly report or activity summary, or to report on their GitHub work.
metadata:
  author: sleeplessv
disable-model-invocation: true
---

# GitHub Weekly Report

One actor's week across every repo they touched, as a fixed-layout
interactive HTML report: headline counters with week-over-week deltas,
canonical work buckets, per-repo breakdown with narratives, and
click-through drill-down to every issue, PR, review, commit, and
discussion. Week 27 looks exactly like week 26, so the eye goes straight
to what changed.

Everything deterministic lives in two bundled stdlib-only scripts; the
agent's job is judgment: bucketing the work, writing the narratives, and
summarising the week.

## Step 1: Resolve parameters

- **Actor**: the authenticated `gh` user (the collector asks
  `gh api user` when no `--actor` is given). **Owner**: an optional
  narrowing filter; by default there is none and the report is
  actor-bounded, covering every repo the actor touched. Nothing is
  derived from the repo the skill is invoked in. The user may set either
  (`owner=someorg`, `actor=somebody`). Never read these from committed
  config, and never commit them.
- **Window**: last complete Mon to Sun week, UTC. An explicit range
  ("from 2026-06-29 to 2026-07-05", "this week so far") maps to
  `--from`/`--to`.

Done when actor, owner filter (or "no owner filter"), and window are
stated to the user in one line.

## Step 2: Collect

```bash
python3 <skill-dir>/scripts/collect.py --out <scratchpad>/gh-weekly \
  [--owner O] [--actor A] [--from YYYY-MM-DD --to YYYY-MM-DD]
```

Emits `week.json` with the report week plus the week before, already
rule-applied: *resolved* means the actor closed it as `completed`
(not-planned closes and abandoned PRs are separate lines), reviews are
window-checked, commits come from `gh search commits` windowed on
committer date and are attributed to their PR or marked direct pushes,
and `discussions` holds items the actor commented on but did not author.
Surface any stderr warnings (result caps) to the user; a capped search
means missing items. Done when `week.json` exists.

## Step 3: Bucket, then narrate

Assign **every** item in `week.json`'s `current` period, discussions
included, to one bucket:

- **feature**: new capability
- **fix**: corrects wrong behaviour
- **refactor**: restructures without behaviour change
- **docs**: documentation, ADRs, glossaries
- **chore/infra**: CI, build, dependencies, tests, housekeeping
- **triage/review**: reviews given, not-planned/wontfix closes, label work
- **other**: a deliberate judgment that nothing above fits

Each item carries a `signal` (conventional-commit prefix) and `labels`,
strong hints but not verdicts; read the title and overrule a misleading
prefix. List the item keys first (e.g. `python3 -c "..."` over
`week.json`) and write `buckets.json` mapping every key to a bucket. An
item missing from the mapping silently lands in `other`, so absence is a
bug, not a choice.

Then write `narratives.json` beside it: an object mapping each repo full
name with current-period activity to a narrative string. Per repo, 2 to
4 sentences that tell the story of the week's work there, weaving in
Markdown links to the items mentioned. For the repo that dominates the
week, extend the narrative with a structured per-work-type breakdown
(one line per bucket present in that repo, with its items). Render keeps
the text verbatim and warns on keys matching no current-period repo.

Done when every current-period key appears in `buckets.json` and every
active repo has a narrative.

## Step 4: Render and open

```bash
python3 <skill-dir>/scripts/render.py --data <...>/week.json \
  --buckets <...>/buckets.json --narratives <...>/narratives.json \
  --out <tmpdir>/gh-week-<iso_week>-<actor>.html
```

Write to the OS temp dir (`$TMPDIR`, fall back to `/tmp`) unless the
user named a destination, and copy `week.json` beside the report; it is
the re-render receipt, so on tweak requests re-run render from it
instead of re-collecting. The report embeds all data but pulls Tailwind
and Chart.js from CDNs: offline, charts are skipped with a visible note
and the page stays readable. Print the absolute paths of both files and
open the report (`open` / `xdg-open` / `start`; on failure just say so).

## Step 5: Summarise

Close with a few sentences in chat: the headline numbers with their
deltas, the dominant bucket, and anything the counters hide (a capped
search, a week dominated by one repo, all-direct-push weeks). The report
carries the detail; the summary carries the story.
