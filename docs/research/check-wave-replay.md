# Research: replaying four past tickets under the check wave

Dated 2026-11-16. This note records the replay that tested the check restructuring of `implement-ticket` 0.7.0 (one check wave, at most two fix rounds, one closing verification, door outcomes) before it merged. The measurements of earlier runs that motivated the change are in [orchestrated-run-measurements.md](orchestrated-run-measurements.md).

## Findings

- **The agreed pass test was not met.** It asked for lower active time and lower spend with every defect the original run fixed caught again or absent. Spend did not drop, and two of the originals' fixed defects were not fixed in the replays.
- **Time after implementation fell where the two sides are comparable.** On the two tickets where the original pipeline also ran a final review on its own, the replay took 18% less time from the implementer's hand-back to the end.
- **Against the runs as they happened, the review pipeline was 32% faster and 18% cheaper.** In two of the four originals the user asked for a final review by hand after the pipeline had finished, and it found the decisive defect both times. The wave runs that review on every full-route ticket.
- **Against the originals' own pipeline, the review pipeline was 12% slower and 31% dearer,** because two of those four pipelines contained no final review.
- **The implement leg, which the change does not touch, grew by 20% in time and 56% in cost,** and holds 56% of the replays' extra worker cost. The replay cannot say why.
- **Rounds past the first mostly repaired the previous fix,** in the replays and in the originals.
- These are four pairs of single runs. They cannot separate the redesign from run-to-run variation.

## Method

- **Tickets.** Four finished tickets from other repositories, one per slot: `clean` (no fix round in the original), `final-catch` (a final review found a real defect), `looper` (four fix rounds), and `door` (a one-way door).
- **Replay.** Each ticket was rerun from its original base commit by a coordinator following `skills/implement-ticket/SKILL.md` from the change's tree. Each ran in a local clone with a local bare remote that held history only up to the base commit. GitHub was unavailable to the replays, so claims, PRs and CI were drafted to files and not executed.
- **Models.** Originals and replays ran every leg on the same Opus-class model.
- **Measures.** Active wall-clock time (silences over 10 minutes removed) and cost weight (uncached input + 1.25 × cache write + 0.1 × cache read + 5 × output), from the transcripts, with the scripts behind the earlier measurements.
- **Two cuts of each original.** "Own pipeline" stops where the original's pipeline first reported the work finished and drops every stage the user asked for afterwards. "As it ran" keeps those stages and drops only a duplicated finalization leg.
- **Defects.** Each original run's fixed and deferred defects were listed beforehand from its transcript. Each was then checked against the replay's final commit, by running the original's reproduction where one could run offline, otherwise by reading the code.

## Per ticket

Original cells read "own pipeline / as it ran"; one figure means the cuts are the same.

| Measure | clean | final-catch | door | looper |
|---|---|---|---|---|
| Active time, s | 746 → 894 | 853 / 1210 → 1369 | 1775 / 3173 → 2359 | 2858 → 2572 |
| Active time after the implementer's hand-back, s | 423 → 346 | 353 / 710 → 694 | 677 / 2075 → 1138 | 1869 → 1526 |
| Worker cost | 1.111M → 2.030M | 927k / 1.456M → 2.113M | 2.044M / 3.817M → 3.466M | 4.053M → 3.890M |
| Worker cost after the hand-back | 677k → 817k | 391k / 920k → 1.237M | 1.038M / 2.811M → 1.843M | 2.652M → 2.325M |
| Legs | 6 → 7 | 7 / 11 → 9 | 10 / 19 → 10 | 20 → 11 |
| Fix rounds | 0 → 0 | 1 / 2 → 1 | 2 / 4 → 2 | 4 → 2 |
| Hand-back to last first-pass check back, s | 210 (333 with its final review) → 185 | 124, no final review → 148 | 288, no final review → 265 | 128, no final review → 198 |

The originals' own pipelines for `final-catch` and `door` had no final review: the user requested it afterwards. The `door` original's implement leg includes about 340 s of waiting on a live CI run (estimate), which the replay had no equivalent of.

## Totals over the four tickets

"As it ran" here counts every leg of the four sessions, the duplicated finalization legs included, so its figures exceed the sum of the per-ticket cells. The implement leg is counted up to the implementer's first hand-back.

| Measure | Original, own pipeline | Original as it ran | Replay | vs own pipeline | vs as it ran |
|---|---|---|---|---|---|
| Active time | 6231 s | 8436 s | 7194 s | +15% | −15% |
| Active time after the hand-back | 3322 s | 5482 s | 3704 s | +12% | −32% |
| Worker cost | 8.134M | 10.933M | 11.499M | +41% | +5% |
| Worker cost after the hand-back | 4.757M | 7.556M | 6.223M | +31% | −18% |
| Implement leg, time | 2792 s | 2792 s | 3338 s | +20% | +20% |
| Implement leg, cost | 3.377M | 3.377M | 5.275M | +56% | +56% |

## By stage, summed over the four tickets

Legs, worker-seconds (parallel legs add) and cost. The implement row counts one original's whole implement leg, including a stretch after its first hand-back, so it exceeds the totals table.

| Stage | Original, own pipeline | Original as it ran | Replay |
|---|---|---|---|
| Implement | 4 legs, 2981 s, 3.460M | 4 legs, 2981 s, 3.460M | 4 legs, 3338 s, 5.275M |
| First-pass checks (Standards, Spec) | 8 legs, 566 s, 890k | 8 legs, 566 s, 890k | 8 legs, 716 s, 1.357M |
| Final review | 2 legs, 216 s, 259k | 4 legs, 513 s, 589k | 4 legs, 553 s, 830k |
| Fix | 7 legs, 1234 s, 1.720M | 10 legs, 2111 s, 2.734M | 5 legs, 1232 s, 1.580M |
| Re-check | 11 legs, 461 s, 725k | 16 legs, 748 s, 1.408M | 5 legs, 604 s, 1.064M |
| Verification | 7 legs, 764 s, 502k | 10 legs, 1248 s, 652k | 4 legs, 485 s, 521k |
| Finalization | 4 legs, 329 s, 578k | 8 legs, 702 s, 1.199M | 7 legs, 366 s, 871k |
| All worker legs | 43 legs, 6551 s, 8.134M | 60 legs, 8868 s, 10.933M | 37 legs, 7294 s, 11.499M |

- **Fewer, larger legs.** The replays ran 37 legs against 43 to 60, and each review leg cost more: first-pass checks 170k against 111k, final review 208k against 130k to 147k, re-checks 213k against 66k to 88k. The replay's re-check is one leg covering both review axes, where the originals mostly ran one short leg per axis.
- **Verification.** One closing verification per run cost about what the originals' 7 to 10 per-head verifications cost in total, in less time.
- **Resuming was cheaper than a fresh worker** in the one rough comparison available: a resumed second-round fix cost 107k against 334k for a fresh one, and resumed finalization 77k against 355k. The workloads differ.

## Defects

| Slot | Defects the original fixed | Replay outcome |
|---|---|---|
| clean | None (one known limitation, deferred) | Same limitation found and deferred |
| final-catch | 1, found only by the user-requested final review | The wave's final review flagged the same code path for a different harm, and the fix closes the original's reproduction. One variant remains, unreported |
| door | 1, found only by the user-requested final review | Not found. The original's reproduction fails against the replay's final code. The replay's different design appears to reduce the harm (read, not run) |
| looper | 3 fixed, 2 deferred | 2 never arose, 2 caught by the wave and fixed, 1 named by two reviewers and deferred at triage (the original fixed it). The wave also found 3 defects that are in the original's final code |

- **The round cap left two should-fix items open** on `looper`, both introduced by the replay's own first fix. One also exists, in a wider form, in the original's final code.
- **Rounds past the first mostly repaired the previous fix.** Replay `looper` round 2: 4 of 4 findings. Replay `door` round 2: all of it, and 10 of that ticket's 12 fixed findings were prose. Original `looper` rounds 2 and 4: 5 of 6. The original's round 3 fixed two original defects and existed because its final review ran after the loop.

## Caveats

- **Skill version.** The originals ran earlier versions of the skill, two of them without an automatic final review. The replays also carry the review-reporting rules that changed in the same period.
- **Harness.** Each replay coordinator was a subagent with a five-minute cache, where the originals' coordinator was the session's main thread. Coordinator cost is therefore left out of the tables. It was 2.776M over the four replays, 29% of it on turns that only acknowledged a worker's return while others were still running.
- **No GitHub.** The replays ran no claim, PR or CI step. The `door` ticket stopped at the door as designed and was never taken through it.
- **Concurrency.** The four replays ran at the same time on one machine.

## Source data

The sandboxes, transcripts, defect ledgers and per-ticket reports were working files of the session and are not in the repo, because they describe work in other repositories.
