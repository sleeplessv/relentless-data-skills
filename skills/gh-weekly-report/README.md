# gh-weekly-report

The **`gh-weekly-report`** agent skill: one GitHub user's week across
every repo they touched, as a fixed-layout interactive HTML report with
headline counters and week-over-week deltas, canonical work buckets,
per-repo breakdown with narratives, and drill-down to every individual
issue, PR, review, commit, and discussion. Because the layout never
changes, week 27 looks exactly like week 26 and the eye goes straight to
what changed.

## What it does

- **Actor-bounded collection.** A bundled stdlib-only script
  (`scripts/collect.py`) shells out to the `gh` CLI, inheriting your
  existing auth with no token handling, and emits one `week.json`
  covering the report week and the week before it. The scope is the
  actor, not a repo list: every component is a GitHub search bounded by
  the authenticated user (overridable with `--actor`), and `--owner` is
  an optional narrowing filter. Nothing is derived from the repo you
  invoke the skill in, and nothing is read from committed config.
- **Metric rules in the script, not the agent.** *Resolved* means the
  actor closed the issue as `completed` (search cannot filter on
  closed-by, so each candidate is verified with one API call);
  not-planned closes and closed-unmerged PRs are separate lines rather
  than noise in the headline numbers; reviews are checked against the
  window per submission timestamp; commits are attributed to the PR that
  carried them or marked as direct pushes, so push-to-main solo weeks
  stay visible. Discussions are issues and PRs the actor commented on
  but did not author, with each candidate's comment times verified
  against the window via the API.
- **Agent judgment where it belongs.** The agent assigns every item,
  discussions included, to one canonical bucket (feature, fix, refactor,
  docs, chore/infra, triage/review, other) using conventional-commit
  signals and labels as hints, and writes a short linked narrative per
  active repo plus a per-work-type breakdown for the week's dominant
  repo. A second script (`scripts/render.py`) merges the bucket mapping
  and the narratives and injects everything into the fixed template.
- **Embedded data, CDN chrome.** Every byte of report data is embedded
  in the HTML; styling and charts come from the Tailwind and Chart.js
  CDNs. Written to the OS temp dir with `week.json` kept beside it as
  the re-render receipt.

## Scope and limitations

- **Actor-bounded, search-backed.** Every number comes from GitHub
  search scoped to the actor. There is no repo discovery step and no
  cache: each run is one search call per component per period, so runs
  are stateless and cheap, but only work the search index can see is
  counted.
- **Committer-date commit windowing.** Commits are found with
  `gh search commits` windowed on the committer date, so work is
  credited to the week it landed; a squash-merge commit carries the
  merge moment, not the original authoring dates. Commit search has two
  accepted limits: it indexes default branches only, and it matches the
  actor by GitHub account, which requires the commit email to be linked
  to that account.
- **Closed-issue edge.** Search has no closed-by qualifier, so closed
  candidates are gathered with `--involves` (authored, assigned,
  mentioned, or commented) and then filtered by actual closer. An issue
  the actor closed without any such involvement is not found. Closes
  with a null `state_reason` count as resolved; that is a deliberate
  decision, not an oversight.
- **Search-index consistency.** GitHub's search index is eventually
  consistent; very recent activity can lag. For the default
  last-complete-week window this is a non-issue.
- **CDN degradation.** With no network, the Chart.js charts are skipped
  behind a visible fallback note and the page renders unstyled but
  fully readable; every counter, bucket row, narrative, and drill-down
  item is plain HTML built from the embedded payload.

## Layout

```
gh-weekly-report/
├── SKILL.md              # the skill definition (this is what the agent reads)
├── plugin.json           # marketplace metadata
├── scripts/
│   ├── collect.py        # gh → week.json (stdlib only, fully unit-tested)
│   └── render.py         # week.json + buckets.json + narratives.json → report.html
└── references/
    └── template.html     # the fixed report scaffold (Tailwind + Chart.js via CDN)
```

Tests live at the repo root: `tests/test_gh_weekly_report.py` covers
window math, metric rules, the `week.json` contract (discussions
included), bucket and narrative merge, template injection, and the
template's offline degradation, all against a canned `gh` fake.
