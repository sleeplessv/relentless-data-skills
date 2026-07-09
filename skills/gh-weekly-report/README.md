# gh-weekly-report

The **`gh-weekly-report`** agent skill: one GitHub user's week across one
account's repos, as a fixed-layout interactive HTML report — headline
counters with week-over-week deltas, canonical work buckets, per-repo
breakdown, and drill-down to every individual issue, PR, review, and
commit. Because the layout never changes, week 27 looks exactly like
week 26 and the eye goes straight to what changed.

## What it does

- **Deterministic collection first.** A bundled stdlib-only script
  (`scripts/collect.py`) shells out to the `gh` CLI — inheriting your
  existing auth, no token handling — and emits one `week.json` covering
  the report week and the week before it. The metric rules are applied in
  the script, not by the agent: *resolved* means the actor closed the
  issue as `completed` (search can't filter on closed-by, so each
  candidate is verified with one API call); not-planned closes and
  closed-unmerged PRs are separate lines rather than noise in the
  headline numbers; reviews are checked against the window per submission
  timestamp; commits on default branches are attributed to the PR that
  carried them or marked as direct pushes — so push-to-main solo weeks
  stay visible. (Commit windowing uses the GitHub API's `since`/`until`,
  which filter on commit dates, not push dates — a commit authored in an
  earlier week but pushed later counts toward the week it was authored.)
- **Nothing committed, nothing hard-coded.** The actor defaults to the
  authenticated `gh` user, the owner to the owner of the repo you invoke
  it in; both are overridable per invocation. The window is the last
  complete Mon–Sun week (UTC), overridable with an explicit range.
- **Agent judgment where it belongs.** The agent assigns every item to
  one canonical bucket — feature, fix, refactor, docs, chore/infra,
  triage/review, other — using conventional-commit signals and labels as
  hints, then a second script (`scripts/render.py`) merges the mapping
  and injects the data into the fixed template.
- **Fully self-contained HTML.** No CDN, no external fetches — the report
  opens offline forever. Vanilla-JS drill-down: click any counter,
  bucket, or repo to see the items behind it, each linking back to
  GitHub. Written to the OS temp dir with `week.json` kept beside it as
  the re-render receipt.

## Layout

```
gh-weekly-report/
├── SKILL.md              # the skill definition (this is what the agent reads)
├── plugin.json           # marketplace metadata
├── scripts/
│   ├── collect.py        # gh → week.json (stdlib only, fully unit-tested)
│   └── render.py         # week.json + buckets.json + template → report.html
└── references/
    └── template.html     # the fixed, self-contained report scaffold
```

Tests live at the repo root: `tests/test_gh_weekly_report.py` — window
math, metric rules, the `week.json` contract, bucket merge, template
injection, and the no-CDN guarantee, all against a canned `gh` fake.
