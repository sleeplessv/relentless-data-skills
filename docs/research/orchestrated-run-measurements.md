# Research: where time and tokens go in orchestrated runs

Dated 2026-11-16. This note measures where spend and time went in 281 Claude Code sessions that used this repo's `orchestrator-mode`, `implement-ticket`, `implement-feature` or `candidate-to-spec` skills between 2026-10-05 and 2026-11-15, and how often each verification and review stage found a real defect. These measurements are the evidence behind the redesign of the skills' check pipeline, in which reviews run as one parallel wave, the fix loop is capped, and independent verification moves to a single closing step. The note describes the pipeline as it ran in that window. It does not measure the redesigned pipeline, it does not establish how important any defect was, and it does not establish what a clean verification is worth as assurance. Roles are regular-expression classifications and yield labels are model judgements on truncated reports, so every figure below should be read with [Data quality and caveats](#data-quality-and-caveats). The measured sessions include work in private projects, so this note is aggregate only and the per-run data was not retained in the repo.

## Findings

A run is one session. A leg is one dispatch: a fresh spawn of a subagent or one resume of it. Spend is a cost weight in input-token equivalents (see [Cost weight](#cost-weight)). "Real defect" means the behaviour was wrong and the code (or an agent instruction that would be acted on) changed. It says nothing about importance: several were edge cases the reviewer itself rated low.

- **Checking is about a quarter of spend and a third of worker time, not the majority.** Across 281 runs, verify + review + final review take 23.7% of spend and 31.0% of worker time. In `implement-ticket` runs it is 29.5% of spend and 39.6% of worker time. Writing code (implement + fix + integrate) is 45.4% of spend, and the coordinator's own context is 15.8%.
- **The fix and re-check loop costs more than the first-pass checks.** In ticket runs, first-pass checks are 19.0% of spend, re-checks 10.5% and fix legs 14.0%, so the loop (fix + re-check) is 24.5%. 60% of check-stage legs start after a fix.
- **Wall-clock is mostly one worker at a time.** 67% of active wall-clock has exactly one worker running, 19% has two or more, and 14% is the coordinator alone. In ticket runs a lone verifier, reviewer or final reviewer holds the clock for about 18% of active time and a lone fix worker for 13%.
- **Independent verification almost never finds a defect.** Of 97 verifier legs read, 1 raised a real defect in the change. 70% found nothing, and 11 of the 29 that reported anything reported something about the environment (branch moved, permission denial, CI outage). Verification is 10.6% of spend and 17.4% of worker time, and per leg it is slower than a review or a final review (a fresh verify leg has a median of 3m44s and a p90 of 13m07s). What a clean verification is worth as assurance was not measured.
- **First-pass reviews and the final review are where defects are found.** Spec reviews raised a real defect in 52% of legs, combined reviews in 62%, and standards reviews in 23% (plus 58% substantive documentation or standards findings). The final review raised a real defect in 32% of 116 legs, and 31 of those 37 were in code an earlier stage had already examined. The final review is 2.3% of spend. False positives are rare: 6 of 453 labelled check legs (1%) had a finding later shown to be wrong.
- **Follow-up reviews mostly find problems that the fixes created.** Of 166 follow-up review legs, 25 raised a real defect and 51 a substantive non-behavioural one. 63 of those 76 were introduced by the preceding fix, 11 were missed earlier, and 2 were repeats. 54% of follow-up legs found nothing or nits only.
- **Tiny dispatches are not where the cost is.** Fresh workers with 5 or fewer substantive tool calls are 13.9% of spawns and 2.2% of worker spend. All fresh-start first requests together are 6.5% of worker spend. The housekeeping role as a whole (git, PR, finalize) is 5.2% of spend and holds the clock alone for 7% of ticket-run active time.

## The population is 281 runs and 4104 dispatch legs over six weeks

A scan covered 1,262 main session transcripts across every local project. A session counts as using a skill if it has a Skill tool call for it, a `<command-name>` for it, or an `attributionSkill` field naming it. 289 sessions used at least one of the four skills, and 281 of them dispatched at least one subagent. These 281 are the runs. All of them were measured, since extraction is scripted.

The transcripts available start on 2026-10-05, so the window is six weeks (to 2026-11-15), in 22 projects. A run is a whole session. Its family is the most specific skill seen in it: implement-feature, then implement-ticket, then candidate-to-spec, else orchestrator-only.

The runs hold **4104** dispatch legs: 3451 fresh spawns and 653 resumes. 116 of them are nested (depth 2).

| family (by skills seen in session) | runs | legs | share of worker spend |
|---|---|---|---|
| implement-ticket | 118 | 1862 | 39.9% |
| implement-feature | 28 | 684 | 21.5% |
| candidate-to-spec | 10 | 145 | 2.9% |
| orchestrator-only | 125 | 1413 | 35.7% |

## Method

### Dispatches were extracted per leg from the transcripts

- One subagent transcript is one agent. A **leg** is one fresh spawn or one resume of an agent (a `SendMessage` whose result carries a resumed or revived agent id). Messages queued to a running worker are not legs.
- Token usage is summed per leg after de-duplicating by API message id, because the transcript repeats the same usage on every content block of one response.
- Duration is the first to the last transcript line of the leg, minus any stretch of more than 10 minutes in which neither the coordinator nor any worker wrote a line.
- Wall-clock classes come from a per-run timeline of coordinator turns and depth-1 worker intervals. Nested workers (116 legs) are counted in spend by their own role and left out of concurrency.

### Roles are a regular-expression classification

The role of a leg comes from a regular expression over the dispatch description and the head of the prompt. The roles are explore, research, setup, implement, fix, integrate, verify, review, verify+review, final_review, housekeeping and other. A resume takes its role from the resume message: finalize, merge or push wording gives housekeeping, fix, finding or address wording gives fix, and otherwise the agent keeps its original role. The check stages are verify, review, verify+review and final_review. The classification is a guess from wording, and the yield readers found that 4% of the legs tagged as checks were not checks (see [Classification](#classification)).

### Cost weight

Cost weight = uncached input + 1.25 x cache write + 0.1 x cache read + 5 x output, in input-token equivalents. It is summed without regard to model, so it ignores price differences between models. "Spend" in this note always means this cost weight. Worker time is the sum of leg durations with stalls removed. It is in agent-seconds, so parallel legs both count.

### Review yield was labelled by reader subagents on a sample

- For 21 runs chosen for size and spread across families, a dossier was built listing every depth-1 check-stage leg in time order: the prompt head, the final report (cut in the middle above 6,000 characters, or 3,800 for the two largest runs), and the coordinator's next actions. These 21 runs hold 20.6% of worker spend.
- For the other runs, every final-review leg was packed with the heads of the earlier check reports of the same run (107 packets).
- Eleven reader subagents read these and labelled each leg with one rubric: the stage, the severity of the top finding (0 nothing, 1 nits or style, 2 substantive but not behavioural, 3 real defect), what happened to it (fixed, deferred, declined, rejected as wrong), where it came from (first stage to look, missed by an earlier stage, introduced by a fix, repeat), and whether any change followed.
- 498 labels came back and 497 were usable, from 105 runs. 21 of them are legs the role classifier had tagged as checks but which were implementers, fix workers or finalizers. They are kept apart as "mis-tagged". 23 are checks of something other than a change under a ticket (design critiques, whole-app audits, CI status) and are kept apart as "other check". The yield figures use the remaining 453.
- One run (9 legs) was labelled by the analyst before the readers labelled it. The reader's stage and severity matched on 8 of 9 and differed by one severity step on the ninth. Three labelled reports were also read in full afterwards, and all three labels were defensible.

The labels are model judgements on truncated reports. The readers gave their own confidence as high for 282 labels, medium for 195 and low for 20.

## Checking takes 23.7% of spend and 31.0% of worker time

Writing code takes more spend and more worker time than checking it, overall and in each of the three families tabulated here. The tables give each role's legs, its share of spend and of worker time, and its token counts by kind. No separate role table was produced for the 10 candidate-to-spec runs.

### All 281 runs

| role | legs | fresh | resume | spend share (incl. coordinator) | share of worker spend | share of worker time | uncached in | cache write | cache read | output |
|---|---|---|---|---|---|---|---|---|---|---|
| setup | 56 | 49 | 7 | 1.1% | 1.3% | 1.5% | 5k | 4.97M | 91.20M | 689k |
| explore | 216 | 203 | 13 | 4.3% | 5.1% | 4.5% | 13k | 19.57M | 340.51M | 2.57M |
| research | 136 | 126 | 10 | 3.7% | 4.4% | 4.3% | 12k | 15.24M | 299.15M | 2.57M |
| implement | 819 | 736 | 83 | 29.8% | 35.4% | 33.2% | 77k | 101.04M | 2779.98M | 18.70M |
| fix | 545 | 299 | 246 | 13.0% | 15.4% | 14.7% | 37k | 50.04M | 1163.83M | 7.50M |
| integrate | 141 | 126 | 15 | 2.6% | 3.1% | 3.8% | 7k | 10.82M | 223.05M | 1.51M |
| verify | 644 | 579 | 65 | 10.6% | 12.6% | 17.4% | 33k | 45.09M | 815.03M | 7.85M |
| review | 907 | 807 | 100 | 10.5% | 12.4% | 10.7% | 33k | 55.18M | 692.62M | 7.31M |
| verify+review | 16 | 16 | 0 | 0.3% | 0.4% | 0.5% | 1k | 1.22M | 27.61M | 265k |
| final_review | 139 | 138 | 1 | 2.3% | 2.8% | 2.5% | 5k | 9.96M | 169.69M | 1.86M |
| housekeeping | 455 | 344 | 111 | 5.2% | 6.2% | 6.3% | 18k | 24.99M | 394.29M | 3.34M |
| other | 30 | 28 | 2 | 0.7% | 0.9% | 0.7% | 3k | 2.85M | 59.75M | 495k |
| **all workers** | 4104 | 3451 | 653 | 84.2% | 100% | 100% | 245k | 340.97M | 7056.70M | 54.66M |
| **coordinator** | - | - | - | 15.8% | - | - | 69k | 51.65M | 1322.03M | 13.47M |

Grouped: checking stages (verify + review + verify+review + final_review) = **23.7%** of spend and **31.0%** of worker time; producing (implement + fix + integrate) = **45.4%** of spend, 51.7% of worker time; fix alone = 13.0% of spend; setup + housekeeping = 6.4% of spend, 7.8% of time; explore + research = 8.0%; coordinator = **15.8%** of spend.

### implement-ticket runs only

| role | legs | fresh | resume | spend share (incl. coordinator) | share of worker spend | share of worker time | uncached in | cache write | cache read | output |
|---|---|---|---|---|---|---|---|---|---|---|
| setup | 14 | 11 | 3 | 0.8% | 1.0% | 1.2% | 3k | 1.61M | 26.24M | 183k |
| explore | 27 | 27 | 0 | 0.8% | 0.9% | 0.7% | 1k | 1.53M | 19.30M | 273k |
| research | 32 | 32 | 0 | 2.8% | 3.3% | 2.7% | 2k | 4.98M | 79.57M | 843k |
| implement | 269 | 237 | 32 | 28.2% | 33.4% | 29.4% | 22k | 34.68M | 1070.90M | 7.31M |
| fix | 243 | 132 | 111 | 14.0% | 16.6% | 16.1% | 12k | 21.80M | 483.71M | 3.44M |
| integrate | 26 | 25 | 1 | 1.4% | 1.6% | 2.0% | 1k | 2.16M | 42.99M | 434k |
| verify | 309 | 286 | 23 | 9.9% | 11.7% | 19.9% | 10k | 17.77M | 285.18M | 3.02M |
| review | 591 | 519 | 72 | 14.8% | 17.5% | 14.4% | 17k | 31.37M | 359.95M | 4.58M |
| verify+review | 15 | 15 | 0 | 0.8% | 1.0% | 1.0% | 1k | 1.14M | 26.29M | 264k |
| final_review | 115 | 114 | 1 | 4.0% | 4.8% | 4.2% | 3k | 7.16M | 108.32M | 1.40M |
| housekeeping | 212 | 133 | 79 | 6.6% | 7.8% | 7.8% | 6k | 12.49M | 193.49M | 1.71M |
| other | 9 | 9 | 0 | 0.4% | 0.5% | 0.4% | 0k | 625k | 12.80M | 143k |
| **all workers** | 1862 | 1540 | 322 | 84.4% | 100% | 100% | 78k | 137.31M | 2708.76M | 23.60M |
| **coordinator** | - | - | - | 15.6% | - | - | 15k | 20.79M | 506.29M | 5.34M |

Grouped: checking stages (verify + review + verify+review + final_review) = **29.5%** of spend and **39.6%** of worker time; producing (implement + fix + integrate) = **43.5%** of spend, 47.6% of worker time; fix alone = 14.0% of spend; setup + housekeeping = 7.4% of spend, 9.1% of time; explore + research = 3.6%; coordinator = **15.6%** of spend.

### implement-feature runs only

| role | legs | fresh | resume | spend share (incl. coordinator) | share of worker spend | share of worker time | uncached in | cache write | cache read | output |
|---|---|---|---|---|---|---|---|---|---|---|
| setup | 21 | 21 | 0 | 3.0% | 3.5% | 3.6% | 1k | 2.43M | 52.88M | 432k |
| explore | 4 | 4 | 0 | 0.4% | 0.5% | 0.4% | 0k | 339k | 7.52M | 65k |
| research | 4 | 4 | 0 | 1.2% | 1.4% | 1.1% | 0k | 557k | 29.30M | 140k |
| implement | 132 | 130 | 2 | 32.9% | 38.2% | 35.4% | 11k | 23.14M | 672.01M | 3.89M |
| fix | 85 | 61 | 24 | 13.8% | 16.1% | 15.0% | 10k | 9.56M | 292.26M | 1.48M |
| integrate | 81 | 70 | 11 | 6.4% | 7.5% | 10.1% | 3k | 6.30M | 112.94M | 679k |
| verify | 89 | 86 | 3 | 7.6% | 8.9% | 14.6% | 4k | 7.00M | 123.23M | 1.15M |
| review | 147 | 144 | 3 | 12.4% | 14.4% | 11.3% | 8k | 12.36M | 198.37M | 1.67M |
| verify+review | 1 | 1 | 0 | 0.1% | 0.1% | 0.2% | 1k | 82k | 1.32M | 0k |
| final_review | 17 | 17 | 0 | 2.3% | 2.7% | 2.3% | 1k | 1.79M | 42.28M | 359k |
| housekeeping | 101 | 94 | 7 | 5.4% | 6.2% | 5.7% | 3k | 5.96M | 77.47M | 729k |
| other | 2 | 2 | 0 | 0.5% | 0.6% | 0.4% | 0k | 261k | 11.50M | 69k |
| **all workers** | 684 | 634 | 50 | 86.1% | 100% | 100% | 42k | 69.77M | 1621.08M | 10.66M |
| **coordinator** | - | - | - | 13.9% | - | - | 8k | 8.24M | 277.04M | 2.17M |

Grouped: checking stages (verify + review + verify+review + final_review) = **22.5%** of spend and **28.3%** of worker time; producing (implement + fix + integrate) = **53.1%** of spend, 60.5% of worker time; fix alone = 13.8% of spend; setup + housekeeping = 8.3% of spend, 9.4% of time; explore + research = 1.7%; coordinator = **13.9%** of spend.

### orchestrator-only runs only

| role | legs | fresh | resume | spend share (incl. coordinator) | share of worker spend | share of worker time | uncached in | cache write | cache read | output |
|---|---|---|---|---|---|---|---|---|---|---|
| setup | 8 | 8 | 0 | 0.3% | 0.4% | 0.4% | 0k | 555k | 9.41M | 37k |
| explore | 168 | 160 | 8 | 10.2% | 12.2% | 11.7% | 12k | 16.70M | 299.32M | 2.11M |
| research | 88 | 83 | 5 | 6.3% | 7.5% | 8.2% | 10k | 9.28M | 185.62M | 1.53M |
| implement | 370 | 334 | 36 | 29.3% | 35.4% | 35.4% | 42k | 38.20M | 967.97M | 6.51M |
| fix | 199 | 106 | 93 | 11.6% | 14.0% | 13.0% | 15k | 17.48M | 364.32M | 2.35M |
| integrate | 34 | 31 | 3 | 1.9% | 2.3% | 2.2% | 3k | 2.36M | 67.11M | 394k |
| verify | 243 | 204 | 39 | 13.8% | 16.6% | 16.8% | 18k | 19.94M | 403.57M | 3.59M |
| review | 149 | 134 | 15 | 4.5% | 5.5% | 5.6% | 9k | 9.44M | 115.31M | 810k |
| final_review | 7 | 7 | 0 | 0.6% | 0.7% | 0.7% | 1k | 1.01M | 19.08M | 103k |
| housekeeping | 128 | 113 | 15 | 3.2% | 3.9% | 4.5% | 9k | 5.38M | 93.09M | 699k |
| other | 19 | 17 | 2 | 1.2% | 1.5% | 1.4% | 2k | 1.97M | 35.45M | 283k |
| **all workers** | 1413 | 1197 | 216 | 83.0% | 100% | 100% | 121k | 122.30M | 2560.27M | 18.43M |
| **coordinator** | - | - | - | 17.0% | - | - | 45k | 20.33M | 496.63M | 5.55M |

Grouped: checking stages (verify + review + verify+review + final_review) = **18.9%** of spend and **23.1%** of worker time; producing (implement + fix + integrate) = **42.9%** of spend, 50.6% of worker time; fix alone = 11.6% of spend; setup + housekeeping = 3.5% of spend, 4.9% of time; explore + research = 16.4%; coordinator = **17.0%** of spend.

## A fresh verify leg takes a median of 3m44s, against 1m36s for a fresh review

Per-dispatch distribution by role, all runs. Fresh spawns and resumes are separate rows.

| role | kind | n | median dur | p90 dur | median tokens (all kinds) | p90 tokens | median cost weight | p90 cost weight | median output | median tool calls | p90 tool calls |
|---|---|---|---|---|---|---|---|---|---|---|---|
| setup | fresh | 49 | 4m23s | 11m22s | 1.07M | 4.26M | 250k | 733k | 5k | 24 | 47 |
| setup | resume | 7 | 0m30s | 10m10s | 228k | 3.01M | 40k | 470k | 0k | 4 | 28 |
| explore | fresh | 203 | 2m29s | 9m33s | 850k | 4.26M | 222k | 677k | 5k | 16 | 45 |
| explore | resume | 13 | 0m34s | 4m37s | 481k | 1.93M | 75k | 296k | 1k | 5 | 12 |
| research | fresh | 126 | 4m20s | 13m53s | 1.72M | 5.32M | 371k | 925k | 14k | 25 | 51 |
| research | resume | 10 | 0m23s | 3m21s | 205k | 1.70M | 45k | 305k | 1k | 2 | 22 |
| implement | fresh | 736 | 4m58s | 20m59s | 1.84M | 10.10M | 377k | 1.64M | 14k | 27 | 79 |
| implement | resume | 83 | 2m02s | 9m43s | 1.14M | 4.98M | 221k | 776k | 2k | 9 | 32 |
| fix | fresh | 299 | 3m57s | 14m27s | 1.29M | 5.49M | 287k | 978k | 11k | 24 | 55 |
| fix | resume | 246 | 2m00s | 9m18s | 1.16M | 4.04M | 217k | 773k | 4k | 10 | 24 |
| integrate | fresh | 126 | 3m57s | 12m01s | 1.18M | 3.50M | 231k | 680k | 9k | 21 | 41 |
| integrate | resume | 15 | 0m57s | 2m21s | 630k | 1.23M | 76k | 243k | 0k | 8 | 10 |
| verify | fresh | 579 | 3m44s | 13m07s | 832k | 3.63M | 196k | 657k | 8k | 17 | 43 |
| verify | resume | 65 | 1m25s | 8m23s | 403k | 1.06M | 72k | 339k | 0k | 5 | 11 |
| review | fresh | 807 | 1m36s | 5m06s | 489k | 1.94M | 141k | 404k | 6k | 10 | 26 |
| review | resume | 100 | 0m42s | 1m44s | 346k | 858k | 101k | 240k | 1k | 4 | 7 |
| verify+review | fresh | 16 | 5m36s | 9m43s | 561k | 4.17M | 154k | 733k | 8k | 13 | 49 |
| final_review | fresh | 138 | 2m12s | 7m46s | 618k | 3.68M | 166k | 669k | 9k | 13 | 42 |
| housekeeping | fresh | 344 | 1m24s | 6m50s | 480k | 1.90M | 121k | 415k | 5k | 12 | 29 |
| housekeeping | resume | 111 | 1m02s | 3m13s | 583k | 1.92M | 114k | 338k | 3k | 6 | 12 |
| other | fresh | 28 | 3m24s | 10m22s | 1.19M | 5.77M | 277k | 1.01M | 9k | 20 | 50 |

## The median run makes 10 dispatches, and the median count of check-stage legs is 4

In implement-ticket runs the median run has 11 legs, the median count of check-stage legs is 6, and check-stage legs are 55% of all legs.

| family | runs | p25 legs | median legs | p75 | p90 | max | median fresh spawns | median check-stage legs | p90 check-stage legs | check-stage share of legs |
|---|---|---|---|---|---|---|---|---|---|---|
| implement-ticket | 118 | 8 | 11 | 17 | 30 | 118 | 8 | 6 | 14 | 55% |
| implement-feature | 28 | 10 | 20 | 31 | 48 | 93 | 19 | 6 | 14 | 37% |
| candidate-to-spec | 10 | 6 | 13 | 20 | 28 | 32 | 7 | 2 | 4 | 16% |
| orchestrator-only | 125 | 5 | 9 | 14 | 23 | 64 | 8 | 2 | 6 | 28% |
| ALL | 281 | 7 | 10 | 18 | 29 | 118 | 9 | 4 | 12 | 42% |

## 60% of check-stage legs start after a fix

A loop is a fix leg (a fresh fix worker, or a resumed writer told to fix findings) that is followed later in the same run by at least one verify, review or final-review leg. Re-check legs are check-stage legs that start after the first fix leg of the run has ended. Which ticket a loop belongs to is not attributed, so multi-ticket runs show higher counts.

| family | runs | runs with 0 loops | median loops | p75 | p90 | max | check legs before any fix | check legs after a fix | share of check legs that are re-checks |
|---|---|---|---|---|---|---|---|---|---|
| implement-ticket | 118 | 28% | 1 | 2 | 4 | 18 | 385 | 645 | 63% |
| implement-feature | 28 | 29% | 1 | 3 | 6 | 19 | 70 | 184 | 72% |
| candidate-to-spec | 10 | 30% | 1 | 1 | 3 | 5 | 10 | 13 | 57% |
| orchestrator-only | 125 | 58% | 0 | 2 | 3 | 14 | 216 | 183 | 46% |
| ALL | 281 | 42% | 1 | 2 | 4 | 19 | 681 | 1025 | 60% |

Counted by wording instead (the description says follow-up, re-verify, round N or fix head, or the leg is a resumed checker), 664 of 1706 check-stage legs (39%) are re-checks, carrying 35% of check-stage spend.

## Small dispatches are 13.9% of fresh spawns and 2.2% of worker spend

| class | n | share of fresh spawns | median dur | median cost weight | median first-request context | share of worker spend | share of worker time | first-request context / all tokens |
|---|---|---|---|---|---|---|---|---|
| tiny: <=2 substantive tool calls | 72 | 2.1% | 0m18s | 47k | 35k | 0.3% | 0.2% | 33% |
| small: <=5 substantive tool calls | 479 | 13.9% | 0m35s | 63k | 35k | 2.2% | 1.7% | 18% |
| small and under 60 s | 392 | 11.4% | 0m32s | 61k | 35k | 1.7% | 1.1% | 19% |
| git/gh commands only (any count) | 65 | 1.9% | 0m27s | 52k | 35k | 0.3% | 0.2% | 21% |
| housekeeping role (any size) | 344 | 10.0% | 1m24s | 121k | 36k | 4.9% | 5.2% | 4% |
| all fresh spawns | 3449 | 100.0% | 2m49s | 208k | 36k | 88.7% | 90.2% | 2% |

The last row counts 3449 fresh spawns, against 3451 in the population count. The measurement output does not explain the difference of 2.

**Fresh-start overhead.** The first request of a fresh worker carries a median **36k** tokens (p10 34k, p90 38k) of system prompt, tool definitions, project instructions and the handoff, before any work. Across fresh spawns 45% of that was served from cache (0.1x) and the rest written (1.25x). Summed, first requests cost 6.5% of worker spend.

**Resume overhead.** Resumes are not free either. The first request of a resumed worker carries a median 109k tokens of accumulated context, of which 63% was a cache read and the rest re-written at 1.25x (worker caches use the 5-minute TTL, and only the coordinator uses 1-hour caching). The median resume has a cost weight of 142k, against 208k for a fresh spawn.

**Coordinator side.** The coordinator spent 264.16M cost weight over 4104 legs, an average of **64k per dispatch** (writing the handoff at 5x, then re-reading its whole context on every hand-back). The coordinator made 12690 API requests. The median handoff prompt was 3267 characters and the median returned report 3605 characters.

## 67% of active wall-clock has exactly one worker running

Per run the timeline is cut into five classes: the coordinator working with no worker running, exactly one depth-1 worker running, two or more running, nothing running and under 10 minutes of silence (a short wait for the human), and stalls. A stall is more than 10 minutes with no transcript line from the coordinator or any worker: the machine asleep, a permission prompt, the human away, or occasionally a long command. Active wall-clock is the first three classes. Stalls are split by whether a worker was nominally still running. Columns marked "(excl.)" are excluded from active time.

| family | runs | total active | median active per run | p90 | coordinator only | one worker running | 2+ workers running | mean workers when parallel | short idle (excl.) | stall with a worker open (excl.) | stall, nothing running (excl.) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| implement-ticket | 118 | 112h | 32m13s | 1.7h | 12% | 68% | 21% | 2.5 | 9h | 5h | 118h |
| implement-feature | 28 | 60h | 1.2h | 5.5h | 11% | 71% | 18% | 2.3 | 4h | 5h | 68h |
| candidate-to-spec | 10 | 8h | 40m25s | 1.6h | 20% | 73% | 8% | 2.6 | 1h | 0h | 22h |
| orchestrator-only | 125 | 91h | 29m18s | 1.8h | 18% | 63% | 19% | 2.9 | 17h | 9h | 330h |
| ALL | 281 | 271h | 32m58s | 2.0h | 14% | 67% | 19% | 2.6 | 30h | 19h | 537h |

Which role was the lone worker, as a share of all active wall-clock:

| family | setup | explore | research | implement | fix | integrate | verify | review | verify+review | final_review | housekeeping | 2+ workers | of which all were check-stage | coordinator only |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| implement-ticket | 1% | 0% | 1% | 25% | 13% | 1% | 11% | 3% | 0% | 4% | 7% | 21% | 7% | 12% |
| implement-feature | 4% | 0% | 1% | 25% | 14% | 8% | 8% | 2% | 0% | 2% | 5% | 18% | 5% | 11% |
| orchestrator-only | 0% | 6% | 4% | 22% | 10% | 2% | 12% | 2% | 0% | 0% | 3% | 19% | 2% | 18% |
| ALL | 1% | 2% | 2% | 24% | 12% | 3% | 10% | 3% | 0% | 2% | 5% | 19% | 5% | 14% |

## 87.2% of worker legs ran on one model

| worker model | legs | share of legs | share of worker cost weight |
|---|---|---|---|
| claude-opus-5-5 | 3577 | 87.2% | 82.2% |
| claude-fable-5-1 | 274 | 6.7% | 6.5% |
| claude-fable-5-2 | 140 | 3.4% | 9.1% |
| claude-sonnet-5-5 | 106 | 2.6% | 2.1% |
| claude-opus-4-8 | 4 | 0.1% | 0.0% |
| claude-haiku-5-5 | 3 | 0.1% | 0.0% |

Coordinator requests by model: claude-opus-5-5 10292, claude-fable-5-1 1410, claude-fable-5-2 830, claude-sonnet-5-5 146, claude-opus-4-8 12.

Share of each role's legs by worker model:

| role | opus-5-5 | fable-5-1 | fable-5-2 | sonnet-5-5 |
|---|---|---|---|---|
| setup | 80% | 12% | 5% | 2% |
| explore | 74% | 9% | 6% | 10% |
| research | 79% | 11% | 4% | 6% |
| implement | 84% | 9% | 4% | 3% |
| fix | 86% | 7% | 4% | 3% |
| integrate | 95% | 4% | 1% | 1% |
| verify | 86% | 5% | 6% | 3% |
| review | 93% | 5% | 2% | 0% |
| verify+review | 94% | 6% | 0% | 0% |
| final_review | 93% | 3% | 3% | 1% |
| housekeeping | 90% | 6% | 1% | 3% |
| other | 83% | 7% | 10% | 0% |

## First-pass verification is the largest check sub-stage, at 7.3% of total spend

Check-stage sub-stages, all runs. The sub-stage (first pass against follow-up, standards against spec) comes from the wording of the dispatch description, so the boundaries are approximate.

| sub-stage | legs | median dur | p90 dur | median cost weight | share of check-stage spend | share of total spend | median tool calls |
|---|---|---|---|---|---|---|---|
| verify: first pass | 425 | 3m52s | 13m03s | 196k | 30.8% | 7.3% | 17 |
| verify: re-check after fix | 219 | 3m01s | 12m48s | 166k | 13.9% | 3.3% | 12 |
| review (spec): first pass | 195 | 1m32s | 4m32s | 138k | 9.5% | 2.3% | 10 |
| review (standards): first pass | 201 | 1m18s | 3m36s | 134k | 9.1% | 2.2% | 9 |
| final review | 123 | 2m11s | 7m30s | 155k | 8.1% | 1.9% | 13 |
| review (other/both): first pass | 94 | 3m50s | 8m45s | 257k | 7.5% | 1.8% | 17 |
| review (standards): follow-up | 171 | 1m07s | 3m20s | 119k | 6.3% | 1.5% | 7 |
| review (spec): follow-up | 141 | 1m20s | 4m37s | 137k | 6.0% | 1.4% | 9 |
| review (other/both): follow-up | 105 | 1m25s | 5m02s | 134k | 5.6% | 1.3% | 9 |
| final review: follow-up on its fixes | 16 | 2m47s | 9m39s | 219k | 1.6% | 0.4% | 13 |
| verify+review combined | 16 | 5m36s | 9m43s | 154k | 1.4% | 0.3% | 13 |

### Single-ticket implement-ticket runs

68 runs in the implement-ticket family have exactly one fresh implementer dispatch. This is the cleaner view of one ticket, because multi-ticket sessions inflate legs and loops per run. Per run:

| measure | p25 | median | p75 | p90 | max |
|---|---|---|---|---|---|
| all legs | 7.0 | 9.0 | 13.0 | 18.3 | 36.0 |
| check-stage legs | 4.0 | 5.0 | 7.0 | 11.0 | 26.0 |
| verify legs | 1.0 | 1.0 | 2.0 | 3.0 | 9.0 |
| review legs | 2.0 | 3.0 | 4.2 | 6.0 | 14.0 |
| final-review legs | 0.0 | 1.0 | 1.0 | 1.0 | 4.0 |
| fix legs | 0.0 | 1.0 | 2.0 | 4.0 | 8.0 |
| fix -> re-check loops | 0.0 | 1.0 | 2.0 | 4.0 | 8.0 |
| housekeeping + setup legs | 1.0 | 1.0 | 2.0 | 2.0 | 3.0 |
| active wall-clock (min) | 14.1 | 25.1 | 48.9 | 72.7 | 227.6 |
| total cost weight (M, incl. coordinator) | 1.3 | 2.0 | 3.8 | 5.7 | 13.3 |

Loop count distribution: 0 loops in 21 runs, 1 loop in 20 runs, 2 loops in 15 runs, 3 loops in 4 runs, 4 loops in 4 runs, and 5 or more loops in 4 runs.

## Reviews and the final review find the defects, and verification rarely does

All labelled legs with mis-tagged legs and other checks excluded (n = 453, from 105 runs). These are model judgements on truncated reports, and the first-pass rows are small samples.

| stage | legs read | found nothing | nits only | substantive, not behavioural | real defect | led to any change | had a finding rejected as wrong | cost weight per real defect fixed | share of all spend (population) |
|---|---|---|---|---|---|---|---|---|---|
| verify, first pass | 28 | 64% | 21% | 11% | 4% (1 leg) | 25% | 0 | 6.75M | 7.3% |
| verify, re-check | 69 | 72% | 13% | 14% | 0% | 13% | 0 | none found | 3.3% |
| standards review, first pass | 31 | 0% | 19% | 58% | 23% | 100% | 1 | 1.26M | 2.2% |
| spec review, first pass | 27 | 15% | 11% | 22% | 52% | 81% | 1 | 474k | 2.3% |
| combined or other first-pass review | 16 | 0% | 0% | 38% | 62% | 100% | 1 | 499k | 1.8% |
| follow-up review (before final) | 105 | 18% | 39% | 27% | 16% | 57% | 1 | 1.36M | 4.2% |
| final review | 116 | 31% | 22% | 16% | 32% | 47% | 1 | 840k | 1.9% |
| follow-up after final review | 61 | 18% | 31% | 38% | 13% | 56% | 1 | 1.66M | 0.4% |
| all | 453 | 30% | 24% | 25% | 21% | 52% | 6 (1%) | 1.16M | 23.7% |

The last column is from the wording-based sub-stage split of the whole population, so its stage boundaries are approximate. "Follow-up review" there sums the standards, spec and other follow-up rows.

### Full yield tables

Labelled check-stage legs: **497**, from 105 runs (1 label line dropped as unparseable, duplicate or unmatched). In these tables "other check" is a check of something other than a change under a ticket, "mis-tagged" is a leg the role classifier tagged as a check that was not one, and the last row is the checks of a ticket change, without those two rows.

#### All labelled legs (n=497)

| stage | n | found nothing | nits only | substantive, not behavioural | real defect raised | real defect fixed | substantive non-behavioural fixed | any change made | had a finding rejected as wrong | legs whose finding was environmental | mean cost weight per leg | cost weight per real defect fixed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| verify, first pass | 28 | 64% | 21% | 11% | 4% | 1 (4%) | 2 (7%) | 25% | 0 (0%) | 3 | 241k | 6.75M |
| verify, re-check | 69 | 72% | 13% | 14% | 0% | 0 (0%) | 7 (10%) | 13% | 0 (0%) | 8 | 218k | - |
| standards review, first pass | 31 | 0% | 19% | 58% | 23% | 7 (23%) | 17 (55%) | 100% | 1 (3%) | 0 | 283k | 1.26M |
| spec review, first pass | 27 | 15% | 11% | 22% | 52% | 14 (52%) | 6 (22%) | 81% | 1 (4%) | 0 | 246k | 474k |
| combined or other first-pass review | 16 | 0% | 0% | 38% | 62% | 10 (62%) | 5 (31%) | 100% | 1 (6%) | 0 | 312k | 499k |
| follow-up review (before final) | 105 | 18% | 39% | 27% | 16% | 16 (15%) | 27 (26%) | 57% | 1 (1%) | 0 | 207k | 1.36M |
| final review | 116 | 31% | 22% | 16% | 32% | 37 (32%) | 13 (11%) | 47% | 1 (1%) | 0 | 268k | 840k |
| follow-up after final review | 61 | 18% | 31% | 38% | 13% | 7 (11%) | 19 (31%) | 56% | 1 (2%) | 0 | 190k | 1.66M |
| other check | 23 | 22% | 13% | 43% | 22% | 4 (17%) | 9 (39%) | 65% | 0 (0%) | 4 | 335k | 1.92M |
| mis-tagged | 21 | 95% | 0% | 5% | 0% | 0 (0%) | 1 (5%) | 0% | 0 (0%) | 1 | 608k | - |
| all checks of a ticket change | 453 | 30% | 24% | 25% | 21% | 92 (20%) | 96 (21%) | 52% | 6 (1%) | 11 | 235k | 1.16M |

#### Fully read runs only, whole runs read in sequence (n=391)

| stage | n | found nothing | nits only | substantive, not behavioural | real defect raised | real defect fixed | substantive non-behavioural fixed | any change made | had a finding rejected as wrong | legs whose finding was environmental | mean cost weight per leg | cost weight per real defect fixed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| verify, first pass | 28 | 64% | 21% | 11% | 4% | 1 (4%) | 2 (7%) | 25% | 0 (0%) | 3 | 241k | 6.75M |
| verify, re-check | 69 | 72% | 13% | 14% | 0% | 0 (0%) | 7 (10%) | 13% | 0 (0%) | 8 | 218k | - |
| standards review, first pass | 31 | 0% | 19% | 58% | 23% | 7 (23%) | 17 (55%) | 100% | 1 (3%) | 0 | 283k | 1.26M |
| spec review, first pass | 27 | 15% | 11% | 22% | 52% | 14 (52%) | 6 (22%) | 81% | 1 (4%) | 0 | 246k | 474k |
| combined or other first-pass review | 15 | 0% | 0% | 40% | 60% | 9 (60%) | 5 (33%) | 100% | 1 (7%) | 0 | 305k | 509k |
| follow-up review (before final) | 105 | 18% | 39% | 27% | 16% | 16 (15%) | 27 (26%) | 57% | 1 (1%) | 0 | 207k | 1.36M |
| final review | 24 | 8% | 12% | 21% | 58% | 14 (58%) | 5 (21%) | 79% | 0 (0%) | 0 | 377k | 647k |
| follow-up after final review | 55 | 18% | 33% | 38% | 11% | 6 (11%) | 18 (33%) | 56% | 1 (2%) | 0 | 198k | 1.81M |
| other check | 21 | 19% | 14% | 43% | 24% | 4 (19%) | 8 (38%) | 67% | 0 (0%) | 4 | 359k | 1.89M |
| mis-tagged | 16 | 94% | 0% | 6% | 0% | 0 (0%) | 1 (6%) | 0% | 0 (0%) | 1 | 558k | - |
| all checks of a ticket change | 354 | 29% | 24% | 27% | 19% | 67 (19%) | 87 (25%) | 55% | 5 (1%) | 11 | 236k | 1.25M |

#### implement-ticket runs (n=344)

| stage | n | found nothing | nits only | substantive, not behavioural | real defect raised | real defect fixed | substantive non-behavioural fixed | any change made | had a finding rejected as wrong | legs whose finding was environmental | mean cost weight per leg | cost weight per real defect fixed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| verify, first pass | 23 | 61% | 26% | 13% | 0% | 0 (0%) | 2 (9%) | 26% | 0 (0%) | 3 | 240k | - |
| verify, re-check | 47 | 62% | 17% | 21% | 0% | 0 (0%) | 7 (15%) | 19% | 0 (0%) | 7 | 227k | - |
| standards review, first pass | 21 | 0% | 19% | 57% | 24% | 5 (24%) | 11 (52%) | 100% | 0 (0%) | 0 | 248k | 1.04M |
| spec review, first pass | 21 | 19% | 14% | 24% | 43% | 9 (43%) | 5 (24%) | 76% | 1 (5%) | 0 | 209k | 487k |
| combined or other first-pass review | 2 | 0% | 0% | 100% | 0% | 0 (0%) | 2 (100%) | 100% | 1 (50%) | 0 | 407k | - |
| follow-up review (before final) | 66 | 18% | 47% | 23% | 12% | 8 (12%) | 15 (23%) | 50% | 0 (0%) | 0 | 196k | 1.62M |
| final review | 100 | 32% | 23% | 14% | 31% | 31 (31%) | 11 (11%) | 47% | 1 (1%) | 0 | 231k | 744k |
| follow-up after final review | 44 | 18% | 32% | 34% | 16% | 6 (14%) | 12 (27%) | 57% | 1 (2%) | 0 | 177k | 1.30M |
| other check | 7 | 29% | 0% | 43% | 29% | 1 (14%) | 2 (29%) | 43% | 0 (0%) | 3 | 570k | 3.99M |
| mis-tagged | 13 | 92% | 0% | 8% | 0% | 0 (0%) | 1 (8%) | 0% | 0 (0%) | 1 | 491k | - |
| all checks of a ticket change | 324 | 31% | 27% | 23% | 19% | 59 (18%) | 65 (20%) | 49% | 4 (1%) | 10 | 217k | 1.19M |

#### implement-feature runs (n=121)

| stage | n | found nothing | nits only | substantive, not behavioural | real defect raised | real defect fixed | substantive non-behavioural fixed | any change made | had a finding rejected as wrong | legs whose finding was environmental | mean cost weight per leg | cost weight per real defect fixed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| verify, first pass | 5 | 80% | 0% | 0% | 20% | 1 (20%) | 0 (0%) | 20% | 0 (0%) | 0 | 248k | 1.24M |
| verify, re-check | 22 | 95% | 5% | 0% | 0% | 0 (0%) | 0 (0%) | 0% | 0 (0%) | 1 | 200k | - |
| standards review, first pass | 6 | 0% | 0% | 67% | 33% | 2 (33%) | 4 (67%) | 100% | 1 (17%) | 0 | 318k | 953k |
| spec review, first pass | 6 | 0% | 0% | 17% | 83% | 5 (83%) | 1 (17%) | 100% | 0 (0%) | 0 | 375k | 451k |
| combined or other first-pass review | 5 | 0% | 0% | 20% | 80% | 4 (80%) | 0 (0%) | 100% | 0 (0%) | 0 | 492k | 615k |
| follow-up review (before final) | 34 | 21% | 24% | 38% | 18% | 6 (18%) | 12 (35%) | 74% | 1 (3%) | 0 | 241k | 1.36M |
| final review | 14 | 29% | 14% | 21% | 36% | 5 (36%) | 2 (14%) | 50% | 0 (0%) | 0 | 494k | 1.38M |
| follow-up after final review | 17 | 18% | 29% | 47% | 6% | 1 (6%) | 7 (41%) | 53% | 0 (0%) | 0 | 222k | 3.78M |
| other check | 8 | 25% | 12% | 25% | 38% | 3 (38%) | 2 (25%) | 62% | 0 (0%) | 1 | 251k | 670k |
| mis-tagged | 4 | 100% | 0% | 0% | 0% | 0 (0%) | 0 (0%) | 0% | 0 (0%) | 0 | 680k | - |
| all checks of a ticket change | 109 | 36% | 15% | 28% | 22% | 24 (22%) | 26 (24%) | 54% | 2 (2%) | 1 | 286k | 1.30M |

## The final review finds what earlier stages missed, and follow-up reviews find what the fix introduced

Legs whose top finding was severity 2 or 3, by where that finding came from:

| stage | legs with severity 2 or 3 | first stage to look | missed by an earlier stage | introduced by a fix | repeat of earlier finding | unclear |
|---|---|---|---|---|---|---|
| verify, first pass | 4 | 3 | 0 | 0 | 0 | 1 |
| verify, re-check | 10 | 1 | 0 | 1 | 4 | 4 |
| standards review, first pass | 25 | 23 | 1 | 1 | 0 | 0 |
| spec review, first pass | 20 | 20 | 0 | 0 | 0 | 0 |
| combined or other first-pass review | 16 | 16 | 0 | 0 | 0 | 0 |
| follow-up review (before final) | 45 | 0 | 8 | 35 | 2 | 0 |
| final review | 55 | 2 | 43 | 0 | 7 | 3 |
| follow-up after final review | 31 | 0 | 3 | 28 | 0 | 0 |
| other check | 15 | 11 | 0 | 0 | 1 | 3 |
| mis-tagged | 1 | 1 | 0 | 0 | 0 | 0 |

The same for severity 3 only:

| stage | legs with severity 3 | first stage to look | missed by an earlier stage | introduced by a fix | repeat of earlier finding | unclear | of which environmental |
|---|---|---|---|---|---|---|---|
| verify, first pass | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| standards review, first pass | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| spec review, first pass | 14 | 14 | 0 | 0 | 0 | 0 | 0 |
| combined or other first-pass review | 10 | 10 | 0 | 0 | 0 | 0 | 0 |
| follow-up review (before final) | 17 | 0 | 3 | 14 | 0 | 0 | 0 |
| final review | 37 | 0 | 31 | 0 | 4 | 2 | 0 |
| follow-up after final review | 8 | 0 | 1 | 7 | 0 | 0 | 0 |
| other check | 5 | 5 | 0 | 0 | 0 | 0 | 0 |

- **The final review finds new things.** 43 of 55 substantive final-review findings (31 of 37 real defects) were in code or text an earlier stage had examined and passed. 7 repeated something an earlier stage had raised. In at least 2 of those the earlier finding had been deferred and the final review's evidence turned it into a fix.
- **Follow-up reviews mostly police the fix.** 63 of 76 substantive follow-up findings were in what the fix round had just written, often prose (a runbook sentence, a changelog line, a comment). Three runs show the pattern at its worst: three successive follow-up rounds each finding a new real defect in the previous fix, four prose-only rounds after a final review, and three final-follow-up rounds each finding another way round the same test until the coordinator deferred the class.
- **Verification repeats itself.** Re-verification legs reproduced the implementer's recorded checks in 59 of 69 cases with nothing substantive to report. The 10 substantive notes were branch drift, environment divergences repeated from the first verification, and missing-test notes. One re-check mattered: it noticed the target branch had shipped the same version number mid-run.
- **In one run the substantive later fixes came from outside.** The two later fix rounds came from an external review that the user supplied, on code the internal verifier and both review axes had passed.

"Missed by an earlier stage" is inferred from the heads of earlier reports for the final reviews that were read as packets, so the direction is sound and the exact count is not (see [Yield](#yield)).

## Most findings were fixed, and final-review findings were deferred most often

Disposition of the top finding, for legs with any finding. "Fixed" means the coordinator dispatched a fix. Whether the fix was correct was not checked, except where a later leg reported on it.

| stage | legs with findings | fixed | deferred | declined | rejected as wrong | unknown |
|---|---|---|---|---|---|---|
| verify, first pass | 10 | 7 | 1 | 0 | 0 | 2 |
| verify, re-check | 19 | 8 | 3 | 6 | 0 | 2 |
| standards review, first pass | 31 | 30 | 0 | 1 | 0 | 0 |
| spec review, first pass | 23 | 22 | 0 | 1 | 0 | 0 |
| combined or other first-pass review | 16 | 15 | 1 | 0 | 0 | 0 |
| follow-up review (before final) | 86 | 59 | 8 | 18 | 1 | 0 |
| final review | 80 | 53 | 19 | 5 | 1 | 2 |
| follow-up after final review | 50 | 32 | 10 | 8 | 0 | 0 |
| other check | 18 | 16 | 2 | 0 | 0 | 0 |
| mis-tagged | 1 | 1 | 0 | 0 | 0 | 0 |

## 37% of the labelled check spend went to legs after which nothing changed

37% of the check spend read, and 47% of the check worker time, went to legs after which nothing changed. Verification accounts for most of that. This counts changes only: what a clean verification is worth as assurance was not measured.

| stage | n | cost weight | spent on legs that found nothing | nits only | substantive non-behavioural | real defect | spent on legs that led to no change | worker time | time on legs that led to no change |
|---|---|---|---|---|---|---|---|---|---|
| verify, first pass | 28 | 6.75M | 57% | 22% | 19% | 2% | 72% | 3.7h | 76% |
| verify, re-check | 69 | 15.07M | 66% | 16% | 18% | 0% | 85% | 7.2h | 84% |
| standards review, first pass | 31 | 8.79M | 0% | 16% | 53% | 31% | 0% | 1.5h | 0% |
| spec review, first pass | 27 | 6.64M | 8% | 6% | 18% | 68% | 9% | 1.3h | 7% |
| combined or other first-pass review | 16 | 4.99M | 0% | 0% | 30% | 70% | 0% | 1.5h | 0% |
| follow-up review (before final) | 105 | 21.76M | 10% | 31% | 39% | 20% | 26% | 4.2h | 24% |
| final review | 116 | 31.09M | 18% | 15% | 19% | 49% | 36% | 6.4h | 36% |
| follow-up after final review | 61 | 11.59M | 14% | 25% | 48% | 12% | 37% | 2.3h | 34% |
| other check | 23 | 7.70M | 7% | 6% | 36% | 51% | 28% | 1.6h | 28% |
| mis-tagged | 21 | 12.78M | 95% | 0% | 5% | 0% | 100% | 3.3h | 100% |
| all checks of a ticket change | 453 | 106.67M | 22% | 19% | 29% | 30% | 37% | 28.1h | 47% |

## Patterns seen in the labelled runs

These are generic descriptions of what individual labelled legs showed. They illustrate the tables and carry no weight beyond them.

- A final review found a defect that earlier checks had passed because they exercised the code with synthetic events and not real input.
- A final review found several problems that test stubs had hidden from every earlier stage.
- A final review found a defect in existing code that two first-pass reviews and two follow-up rounds had not reported.
- A follow-up after a final review found that the final review's own fix had introduced a defect. It was fixed with a test that failed first.
- A false positive: a follow-up review's finding was acted on, the next round showed the state cannot occur with real data, and the fix was reverted.
- A repeat: a final review's one point was a cleanup that an earlier review had already raised and the coordinator had deferred. No change followed.

## Data quality and caveats

### Classification

- **Roles are regex guesses.** On a 100-leg manual check about 94 agreed with the analyst's reading. The readers then showed the check tags are less clean than that: 21 of 497 labelled legs (4%) tagged verify, review or final review were implementers, fix workers or finalizers whose descriptions contain words like "check" or "test". They carried 10% of the labelled cost weight, because writers are more expensive than checkers. If the sample is typical, the population check share (23.7%) is overstated by roughly two points, and implement and fix are understated by the same amount. The converse error (a check tagged as something else) was not measured.
- 28 fresh legs and 2 resumes stayed `other` (0.7% of spend).
- **Sub-stages in the check-stage sub-stage table** (first pass against follow-up, standards against spec) come from description wording. The reader labels are better but cover a sample.
- **"Fix" includes fixes the user asked for** mid-run, not only fixes prompted by a review.
- **Run = session.** A session that used `orchestrator-mode` for one task and `implement-ticket` for another is one run in the ticket family. Multi-ticket sessions inflate legs and loops per run. The single-ticket table is the cleaner view of one ticket.
- **Loops** are counted as fix legs followed by any later check leg in the same run, not matched to a ticket.

### Time

- Durations are transcript timestamps. Any silence over 10 minutes across the whole run is removed. A permission prompt or a short absence under 10 minutes counts as work.
- 19 hours of stall happened with a worker nominally running. Some of that is real work (a long command) that the rule discards.
- 537 hours of stall with nothing running are sessions left open. They are excluded, so "active" time is a lower bound on elapsed time and an upper bound on nothing.
- The parallel share counts depth-1 workers only.

### Cost

- The cost weights are a fixed convention (output 5x, cache write 1.25x, cache read 0.1x) and take no account of model price. 87% of worker legs ran on one model, so shares by role are little affected. Absolute comparison across runs with different coordinators is not valid.
- The coordinator writes its cache with the 1-hour TTL, which is priced at 2x, not 1.25x. Priced that way the coordinator share is 17.7%, not 15.8%.
- Usage was de-duplicated by message id. Requests that failed before returning usage are not in the transcript.

### Yield

- **Labels are model judgements on cut reports.** Reader subagents saw the middle of long reports removed and the coordinator's reaction as a short excerpt. Finding counts for long reports rest on the reviewer's own totals. Reader confidence: high 282, medium 195, low 20.
- **Severity 2 against 3 is a judgement call** for documentation and agent-instruction findings. Readers rated a contradictory instruction as 3 when an agent would act wrongly on a realistic path, and prose that contradicts the code as 2 even where the reviewer called it low. Shifting that boundary moves the standards-review and follow-up rows most.
- **Severity says nothing about importance.** A real defect in a corrupt-input edge case and one that would break production both count as 3.
- **"Fixed" means the coordinator dispatched a fix**, as seen in the dossier. Whether the fix was correct was not checked, except where a later leg reported on it.
- **"Missed by an earlier stage" in the 107 final-review packets** is inferred from the heads of earlier reports, not from full reading. In the 21 fully read runs the same pattern holds (14 of 24 final reviews raised a real defect), so the direction is sound. The exact count is not.
- **The dossier sample is biased to large runs**: 21 runs, 20.6% of worker spend. Final reviews are covered almost completely (116 usable labels of 139 tagged legs). First-pass reviews (74 legs) and first-pass verification (28 legs) are small samples, and per-family splits of them are smaller still.
- **Verification after a final-review fix** is labelled as a verify re-check, not as final follow-up.
- **Environmental findings** (11 verifier legs) are counted at the severity the reader gave. Treating them as non-findings would raise "found nothing" for verification from 70% to about 81%.
- **What a clean verification is worth was not measured.** A verifier that finds nothing may still be what lets the coordinator trust a result. This measurement only shows it rarely changes the outcome.
- One label row had no severity and was dropped. One final-review packet could not be labelled.

### Not done

- No attribution of loops to tickets, so "loops per ticket" exists only for the 68 single-ticket runs.
- No measure of yield by follow-up round number.
- No comparison of worker models on yield: 93% of review legs ran on one model.

## Source data

The extraction scripts, per-leg and per-run data, reader dossiers and labels were working files of the measurement session and were not retained in the repo, because they describe individual sessions.
