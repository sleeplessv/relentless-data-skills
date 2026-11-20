# Research: like-for-like cost of the implement and orchestrator skills against a single agent

Dated 2026-11-20. This note compares sessions that used this repo's `orchestrator-mode` or an `implement-*` skill ("stack" sessions) with sessions that committed or opened a PR without them ("direct" sessions), for pull requests of similar size, over 2026-10-21 to 2026-11-20. It asks what each group cost in tokens and time and how often each got the change right first time. The measured sessions include work in private projects, so projects are labelled A to N and no session ids are given; the mapping stays outside the repo. The script that produced every number is [gen1-like-for-like-cost.py](gen1-like-for-like-cost.py).

## Answer

For changes of the same size, a stack session cost about 5 to 6 times the total tokens of a direct session (7 to 9 times excluding cache reads), took about 3 times the active minutes, and got the change right first time at the same rate: 84% of stack PRs against 86% of direct PRs, with no size bucket where the stack did measurably better at a usable sample size. Users typed about as many prompts after the start in both groups. On the evidence GitHub records, the extra spend is not buying fewer reworked PRs. GitHub records little rework of any kind here, though (98% of PRs in both groups merged, no change requests are possible on a solo repo, failed checks are rare), so this does not show the stack's checks are worthless. It shows that their value, if any, does not appear in post-PR rework.

## Findings

- **Size-matched cost ratio is 5 to 6 times in tokens, 3 times in time, in every bucket with enough sessions.** Medians, stack against direct (Table 2): up to 50 changed lines 5.7M against 1.1M total tokens and 27 against 9 active minutes (n=22/40); 51 to 300 lines 10.5M against 1.8M and 38 against 13 minutes (n=52/45); 301 to 1,500 lines 20.5M against 3.8M and 59 against 22 minutes (n=33/12). Changed lines and files changed match closely within each bucket. Interquartile ranges do not overlap for any token measure in these three buckets.
- **The gap is wider without cache reads and in output.** Tokens excluding cache reads: 401k against 59k (6.8x), 638k against 81k (7.9x), 1.1M against 128k (8.6x). Output tokens: 7 to 8 times. Stack sessions median 6, 9 and 13 subagent calls in the three buckets; direct sessions median 0.
- **First-pass rate is the same.** "First-pass" (definition below): stack 61/68 (90%) against 51/55 (93%) up to 50 lines; 120/143 (84%) against 44/50 (88%) at 51 to 300; 60/75 (80%) against 10/17 (59%) at 301 to 1,500, where the direct n is too small to read as a stack advantage. Commits after the opening session ended: 3% against 2%. A PR with any failed check run: 8/303 against 1/125, none of them on the commit the session handed off.
- **The ratio holds inside one project.** In project B, 51 to 300 lines: 8.1M against 1.5M tokens and 31 against 7 minutes (n=16/5). The one cell where the stack costs no more is project B up to 50 lines: 2.1M against 2.1M tokens, 14 against 8 minutes (n=6/5).
- **User steering is not reduced.** User prompts after the start, medians: 2.5 against 2, 2 against 3, 4 against 3.5. The stack does not take more input from the user for the same size of change, and it does not take less.
- **The strict reading of "first time" is an artefact of the draft-PR design.** 70% of stack PRs were opened as drafts, as `implement-ticket` directs ("open a draft PR within the first 1–2 commits", skills/implement-ticket/SKILL.md), so 73% have commits after opening against 23% of direct PRs. Counted strictly (no commit after opening), 26% of stack PRs and 74% of direct PRs pass. That measures the workflow, not rework, and is not used for the answer.

## Method

**Sessions.** Rows of `usage-sessions.csv` from the 30-day skill usage scan (`usage_scan.py`, run with the session doing this research excluded). Stack = orchestrator-mode or an implement-* skill signalled in the main thread (359 sessions). Direct = no such skill, and a commit or PR seen (168). The scan was extended by one column, `pr_urls`: the github.com pull URLs found in the output of a call that ran `gh pr create` (the scan's existing verified-outcome signal), added with `pr_urls='|'.join(sorted(s.pr_urls)) if s.verified else ''` in the row it writes. The extended scan reproduced the original counts exactly (20,470 events, 1,385 sessions, 359 and 168).

**Size.** Each PR URL was read once with a read-only `gh api graphql` query: additions, deletions, changed files, commits with their dates and check runs, reviews, ready-for-review and force-push events. A PR is attributed to a session only if GitHub's `createdAt` falls between the session's first line minus 2 minutes and its last line plus 5 minutes, which drops URLs a session merely listed; no URL was dropped this way. Changed lines = additions + deletions, summed over every PR a session opened; 24 stack and 14 direct sessions opened more than one PR. Buckets were chosen from the size distribution (Table 1): direct sessions have a median of 67 lines and a 90th percentile of 379, so the break points are 50, 300 and 1,500.

**Cost.** Per session, from the scan: total tokens (input + output + cache creation + cache read), tokens excluding cache reads, output tokens, active minutes (sum of gaps under 30 minutes between transcript lines, subagents included), subagent calls, and user prompts after the first. All compared sessions are Claude Code except 2 Codex stack sessions, so every compared session has token counts.

**First-pass.** A PR is first-pass when it merged, no commit on it is dated more than 5 minutes after it was opened for review (for a draft, the first ready-for-review event; otherwise its creation), and it received no change-request review. A session is first-pass when every PR it opened is. Three other readings are reported for comparison: strict (no commit at all after creation, no failed check run, no change request), hand-off (no commit after the opening session ended and the last commit the session pushed passed its checks), and a 7-day follow-up check (below).

**Follow-up fix PRs.** A later PR in the same repository, opened within 7 days, titled fix, revert or hotfix, that touches a file the PR touched, and names the PR as `#N` in its title or body. This found 33/303 stack PRs (11%) against 5/125 direct (4%). Reading the matched titles shows most are the next PR in a series of small fixes that cites its predecessor, not a repair of it, and stack PR bodies cross-reference more, so this is an upper bound that leans against the stack. Without the `#N` condition the rule matches 61% and 44%, almost all shared version or changelog files, so it is not used.

## Tables

All values: n: median [interquartile range]. "n too small" marks cells where one group has fewer than 10 sessions.

### Table 1: who is in the comparison

| step | stack | direct |
|---|---|---|
| sessions | 359 | 168 |
| no PR URL seen (left out of the size comparison) | 138 | 34 |
| PR URLs only in repositories this GitHub account cannot read | 91 | 34 |
| in the size comparison | 130 | 100 |
| of which opened more than one PR (sizes summed) | 24 | 14 |
| changed lines, median [p25-p75] | 202 [75-919] | 67 [33-169] |
| changed lines, p90 | 3,472 | 379 |

643 distinct PR URLs were seen: 428 read and all attributed, 212 in repositories of an organisation this account has no access to, and 3 placeholder URLs from documentation text.

### Table 2: cost per session by size

| bucket (changed lines) | metric | stack | direct | ratio of medians |
|---|---|---|---|---|
| up to 50 | total tokens | n=22: 5.7M [4.4M-8.1M] | n=40: 1.1M [678k-2.1M] | 5.2 |
| up to 50 | tokens excl. cache reads | 401k [261k-628k] | 59k [42k-111k] | 6.8 |
| up to 50 | output tokens | 55k [46k-89k] | 6.9k [4.6k-13k] | 8.0 |
| up to 50 | active minutes | 27.3 [17.7-32.1] | 9.4 [4.8-14.9] | 2.9 |
| up to 50 | subagent calls | 6 [4.2-8] | 0 [0-0] | |
| up to 50 | user prompts after start | 2.5 [1-3] | 2 [1-4] | |
| up to 50 | changed lines / files | 22.5 / 3 | 30.5 / 3 | |
| 51-300 | total tokens | n=52: 10.5M [7.7M-14.6M] | n=45: 1.8M [1.2M-3.6M] | 5.8 |
| 51-300 | tokens excl. cache reads | 638k [437k-1.2M] | 81k [63k-131k] | 7.9 |
| 51-300 | output tokens | 100k [67k-201k] | 14k [8.4k-22k] | 7.1 |
| 51-300 | active minutes | 38.3 [20.1-69.3] | 12.9 [5.8-23.7] | 3.0 |
| 51-300 | subagent calls | 9 [5.8-12] | 0 [0-0] | |
| 51-300 | user prompts after start | 2 [1-7] | 3 [2-6] | |
| 51-300 | changed lines / files | 108 / 6 | 105 / 6 | |
| 301-1,500 | total tokens | n=33: 20.5M [13.8M-30.3M] | n=12: 3.8M [2.1M-5.4M] | 5.4 |
| 301-1,500 | tokens excl. cache reads | 1.1M [854k-1.6M] | 128k [73k-232k] | 8.6 |
| 301-1,500 | output tokens | 200k [127k-291k] | 28k [9.1k-53k] | 7.1 |
| 301-1,500 | active minutes | 58.8 [40-82] | 22 [15.4-33.8] | 2.7 |
| 301-1,500 | subagent calls | 13 [9-19] | 0 [0-0] | |
| 301-1,500 | user prompts after start | 4 [2-6] | 3.5 [1.8-5.2] | |
| 301-1,500 | changed lines / files | 604 / 13 | 457 / 12.5 | |
| over 1,500 (n too small) | total tokens | n=23: 92.7M [34.9M-195.8M] | n=3: 5.3M [3.3M-27.8M] | |
| over 1,500 (n too small) | active minutes | 189 [91-296] | 17.8 [11.7-40.4] | |

Restricting to single-PR Claude Code sessions changes no ratio by more than about a third: 51 to 300 lines, 10.5M against 1.5M tokens and 38 against 10 minutes (n=50/36).

### Table 3: right first time, per PR, by the PR's own size

| bucket | group | PRs | merged | first-pass | strict | hand-off | commit after session end | any failed check | opened as draft | fix PR naming it within 7 days |
|---|---|---|---|---|---|---|---|---|---|---|
| up to 50 | stack | 68 | 99% | 90% | 44% | 97% | 1% | 1% | 54% | 4% |
| up to 50 | direct | 55 | 100% | 93% | 78% | 96% | 4% | 0% | 0% | 2% |
| 51-300 | stack | 143 | 99% | 84% | 25% | 97% | 2% | 3% | 71% | 15% |
| 51-300 | direct | 50 | 96% | 88% | 78% | 94% | 2% | 0% | 0% | 6% |
| 301-1,500 | stack | 75 | 97% | 80% | 9% | 95% | 3% | 4% | 80% | 11% |
| 301-1,500 | direct (n small) | 17 | 94% | 59% | 53% | 94% | 0% | 0% | 0% | 6% |
| over 1,500 | stack | 17 | 100% | 76% | 35% | 88% | 12% | 0% | 76% | 0% |
| over 1,500 | direct (n too small) | 3 | 100% | 3/3 | 2/3 | 3/3 | 0% | 33% | 0% | 0% |
| all | stack | 303 | 98% | 84% | 26% | 96% | 3% | 3% | 70% | 11% |
| all | direct | 125 | 98% | 86% | 74% | 95% | 2% | 1% | 0% | 4% |

No PR in either group received a change-request review. 87% of stack PRs and 91% of direct PRs had at least one check run.

### Table 4: same project, same bucket (both groups n of 3 or more)

| bucket | project | stack tokens | direct tokens | stack active min | direct active min |
|---|---|---|---|---|---|
| up to 50 | B | n=6: 2.1M | n=5: 2.1M | 14 | 8 |
| 51-300 | A | n=4: 25.0M | n=27: 2.5M | 60.9 | 13.9 |
| 51-300 | B | n=16: 8.1M | n=5: 1.5M | 30.6 | 7.3 |
| 301-1,500 | A | n=3: 11.7M | n=5: 4.4M | 58.1 | 22.4 |

## Confounds that could not be removed

- **Task type and project.** Direct sessions are concentrated in project A, a notes and documentation repository: 27 of 40 small and 27 of 45 medium direct sessions. Stack sessions spread over 5 to 10 projects per bucket, mostly code (projects B, C, D). A line of prose is cheaper to change than a line of code with tests, so the pooled ratio overstates the stack's premium for the same kind of work. The within-project rows (Table 4) still show about 5 times in project B at 51 to 300 lines, so the premium is not only a project effect, but those cells are small.
- **Who chose the stack, and why.** The user picks the stack for tickets, multi-step work and changes they want reviewed, and works directly on quick fixes. Equal line counts can hide unequal difficulty (a stack ticket may need reading more code or a design decision), which inflates the stack's cost and could hide a quality benefit on harder work. The data cannot separate the two.
- **What counts as rework.** On solo repositories GitHub cannot record a change request, the owner merges almost everything (98%), and checks rarely fail, so "first-pass" mostly measures commits after review-ready. Rework that happened inside the session (the stack's review and fix loop, a direct session's back and forth) is in the cost, not in the first-pass rate. Defects found weeks later, or fixed without citing the PR, are not seen.
- **Harnesses without tokens and repositories without access.** Cortex Code and Cursor record no tokens, and their PRs here sit in repositories this GitHub account cannot read, so the comparison is Claude Code (plus 2 Codex sessions). 91 stack and 34 direct sessions whose PRs are in another organisation's repositories are out, as are 138 stack and 34 direct sessions with no PR URL (planning, review and analysis runs, or commits without a PR). If stack work in the inaccessible organisation differs, the result may not carry over.
- **Session boundaries.** One session can open many PRs (one opened 52); sizes and costs are summed, which keeps cost and size consistent but mixes batch runs with single tickets in the large buckets. Active minutes count time when transcripts were being written, including subagent time while the user was away, so they are agent time, not user time.

## What this note cannot support

- That the stack produces better or worse code: no measure here reads the code.
- Any conclusion for changes over 1,500 lines, where only 3 direct sessions exist.
- A causal ratio: the groups were not randomised, and the confounds above point in both directions.

## Reproduce

1. Extend `usage_scan.py` with the `pr_urls` column as in [Method](#method) and run it into a run directory.
2. `python3 docs/research/gen1-like-for-like-cost.py RUN_DIR` reads `RUN_DIR/usage-sessions.csv`, caches every GitHub response under `RUN_DIR/pr-cache/`, and writes `l4l-prs.csv`, `l4l-sessions.csv`, `l4l-tables.md` and the private `l4l-project-labels.csv`. GraphQL calls back off on GitHub's rate limit; `--no-graphql` reuses the cache only. All GitHub calls are reads.

## Sources

- Session transcripts of Claude Code, Codex, Cortex Code and Cursor on the owner's machine, 2026-10-21 to 2026-11-20, via the usage scan.
- GitHub GraphQL API `repository.pullRequest` (additions, deletions, changedFiles, commits with checkSuites and status, reviews, timelineItems) and REST `GET /repos/{owner}/{repo}/pulls` and `/pulls/{n}/files`, read 2026-11-20.
- skills/implement-ticket/SKILL.md, the draft-PR rule, at origin/main 6a878a1.
