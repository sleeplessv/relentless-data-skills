# Research: a Sonnet-class implementer against an Opus-class one, and how each harness names a model class

Dated 2026-11-16. This note records the evidence behind the model classes in `orchestrator-mode` 0.8.0 and their assignment in `implement-ticket` 0.8.0 and `implement-feature` 0.6.0. The earlier replay of the check wave is in [check-wave-replay.md](check-wave-replay.md), and the outside evidence on model tiers is in [orchestration-cost-and-model-tiers.md](orchestration-cost-and-model-tiers.md).

## Findings

- **A Sonnet-class implementer cut list-price cost by 31% and active time by 9%** over three replayed tickets, with Opus-class reviewers in both arms.
- **The time result is not a speedup.** One ticket took 61% longer, one took the same time, and one took 38% less. The spread comes from how many fix rounds each run happened to need.
- **The two classes' first builds were closer than their final commits.** On the largest ticket the Opus-built first commit held five code defects and the Sonnet-built one held four of the same five. The Opus arm's reviewers reported all five and they were fixed. The Sonnet arm's reviewers, on the same class of model, reported one, which the coordinator left as an author decision, so all four shipped. That difference is in what the reviews caught, and one pair of runs cannot assign it to the implementer.
- **Differences that do belong to the implementer went both ways.** The Sonnet worker left out a command the Opus worker built, broke a browser test it never ran, and wrote two fixes that a re-check sent back. It also avoided three defects the Opus worker's final code has.
- **A Sonnet-class closing verification reproduced every recorded check** in all three runs, at 37% of the Opus-class cost for that stage.
- **Decision:** the implementing worker and the reviewers are assigned the strong class, and the closing verification the standard class. The owner ranks quality first, then time, then spend. The test shows a saving in spend, no dependable saving in time, and weak, mixed evidence on quality, so it gives no reason to accept a quality risk for it. A user who wants the saving on a small ticket can name the implementer's model, which wins over the skill's assignment.

## Method

- **Tickets.** The three two-way-door tickets of the check-wave replay: `clean`, `final-catch` and `looper`.
- **Arm A** is that replay: every worker on the Opus-class model.
- **Arm B** reran each ticket from the same base commit, with the merged `implement-ticket` 0.7.0, in the same sandbox harness. The implementing worker and the closing verification ran on the Sonnet-class model, and its resumes for fixes and finalization kept that model. Every reviewer and re-checker ran on the Opus-class model. A re-check that found an accepted finding still open sent the next fix to a fresh Opus-class worker.
- **Both coordinators** were Opus-class subagents, so coordinator cost is comparable between the arms.
- **Models were confirmed from the transcripts:** every leg ran on the class it was assigned.
- **Cost** is list price in dollars, from each leg's token counts by kind, at the prices below.
- **Defects.** Every probe built for the originals and for arm A was rerun against arm B's final commits, offline. Each arm's tests were also run against the other arm's final code where they were compatible.

## Results

| A → B | clean | final-catch | looper | Total |
|---|---|---|---|---|
| Active time, s | 894 → 1439 | 1369 → 1368 | 2572 → 1602 | 4835 → 4410 (−9%) |
| Time to the implementer's hand-back, s | 548 → 308 | 675 → 629 | 1046 → 663 | 2269 → 1600 (−29%) |
| Time after it, s | 346 → 1131 | 694 → 740 | 1526 → 939 | 2566 → 2810 (+10%) |
| Worker cost | $5.75 → $5.41 | $6.15 → $3.41 | $11.78 → $6.19 | $23.68 → $15.00 (−37%) |
| Coordinator cost | $1.76 → $1.95 | $2.03 → $1.91 | $2.87 → $2.21 | $6.65 → $6.07 (−9%) |
| Total cost | $7.51 → $7.36 | $8.18 → $5.32 | $14.65 → $8.40 | $30.33 → $21.07 (−31%) |
| Legs | 7 → 11 | 9 → 9 | 11 → 10 | 27 → 30 |
| Fix rounds | 0 → 2 | 1 → 1 | 2 → 2 | 3 → 5 |

Every figure is rounded from unrounded data, so sums of printed cells can differ by one in the last digit.

By stage, summed over the three tickets:

| Stage | Arm A | Arm B |
|---|---|---|
| Implement | 2153 s, $10.31 | 1472 s, $3.48 |
| First-pass reviews (Standards, Spec) | 494 s, $3.04 | 585 s, $3.17 |
| Final review | 350 s, $1.74 | 424 s, $1.75 |
| Fix | 836 s, $3.25 | 648 s, $1.86 |
| Re-check | 416 s, $1.98 | 723 s, $3.36 |
| Verification | 299 s, $1.14 | 221 s, $0.42 |
| Finalization | 332 s, $2.22 | 214 s, $0.96 |

- **The implement stage was faster as well as cheaper** on the Sonnet-class model: 32% less time and 66% less cost.
- **Re-checks cost more in arm B,** because it ran five fix rounds against three.

## Quality, ticket by ticket

- **clean.** The code at the wave head was equivalent in the two arms. Arm B's Standards reviewer tiered a known limitation as should-fix, where both final reviews called it nice-to-have, so arm B fixed it and arm A deferred it. The Sonnet worker's fix left a false docstring and tests that still passed with part of the fix reverted. The re-check caught both, and the second round repaired them. Arm B's final code is the better of the two, at 61% more time.
- **final-catch.** Both arms' final reviews found the same defect and both fixes close the original reproduction. The same leftover variant is in both final commits. Arm B's change made a browser smoke test in the repository fail, because the ticket's own change altered the page that test expects. No stage of the run executed that test. The repository's CI runs it on pull requests, so a real run would have met it as a failing check after publication.
- **looper.** Arm A's first commit held five code defects, one of them a missing safety check, and its wave reported all five. Arm B's first commit held four of the same five. Its reviewers reported mostly prose findings and one of the four, the missing safety check, which the coordinator accepted as an author decision. So arm B's final code has those four and arm A's has none of the five. Arm B also omits one command arm A implemented. Arm B's final code lacks three defects that arm A's has. The first Sonnet fix left an accepted finding partly open, which triggered the one class escalation of the three runs; the Opus-class worker closed it for $0.50.

## What this supports

These are inferences from three pairs of single runs.

- **The saving in spend is real.** About four-fifths of the worker saving comes from the implement stage.
- **The test does not show that a Sonnet-class implementer builds worse code.** The first builds were similar where they can be compared, and each arm's final code has defects the other's lacks.
- **What the reviews catch varies more than the implementer did.** In one pair, reviewers on the same class of model reported five code defects in one run and one of the same defects in the other.
- **Closing verification is mechanical enough for the standard class.** It reruns recorded commands and compares results, and it did so correctly in all three runs.
- **Class escalation from the standard class fired once, on the right trigger,** and the stronger worker finished the run. The skills assign no implementer to the standard class, so in `implement-ticket` this step runs only when a user names one. The step from the strong class to the session class never ran.

## Prices used

List prices per million tokens, from Anthropic's pricing page on 2026-11-16.

| Model | Input | 5-minute cache write | 1-hour cache write | Cache read | Output |
|---|---|---|---|---|---|
| Fable 5.2 | $8 | $10 | $16 | $0.20 | $40 |
| Opus 5.5 | $4 | $5 | $8 | $0.20 | $20 |
| Sonnet 5.5 | $2 | $2.50 | $4 | $0.10 | $10 |

Subscription plans do not publish a per-model usage weight. Anthropic documents a weekly limit across all models with a separate weekly limit for Fable, and says that how fast a limit is reached depends on the model.

## How each harness names a model for a spawned worker

Checked against vendor documentation and source on 2026-11-16. These facts are the basis of the per-harness aliases and ids in `skills/orchestrator-mode/references/reference.md`. Which family that file assigns to the strong and standard class on Codex and Cursor is this repo's choice and not a vendor statement. Its ranking of the Codex families is read from the vendor's one-line description of each model.

| Harness | Per-spawn model | Alias that follows the newest version | Notes |
|---|---|---|---|
| Claude Code | `model` on the Agent tool call | Yes: `fable`, `opus`, `sonnet`, `haiku`. The call takes an alias, not a full model id | An alias resolves to the provider's recommended version, which can be older on a third-party provider. A nested worker without a model inherits its spawner's |
| Codex CLI | `model` and `reasoning_effort` on `spawn_agent` | No: exact catalog ids only. An unknown id fails with the list of available models | Families are Astra, Sol, Terra and Luna. A custom agent file's model wins over the spawn's. `features.multi_agent_v2.expose_spawn_agent_model_overrides` set to false removes both parameters |
| Cursor | The definition's `model`, and the parent can name a model at launch | No: exact ids only | Team restrictions, plan limits and the legacy Max Mode setting cause a silent fallback to another model |
| Cortex Code | The definition's `model`; the spawn call documents only `inherit` | Yes, in settings and definitions: `auto`, `auto-intelligent`, `auto-efficient` | What the `auto` aliases map to depends on the account's configuration |

### Could not confirm

- The name of Cursor's launch-time model parameter.
- Any OpenAI alias that follows the newest model, and Codex's default model when none is set.
- Cortex Code spawn-call model values other than `inherit`, and a per-spawn effort setting.
- Any published per-model usage multiplier for Claude subscription plans.

### Sources

- Claude Code: <https://code.claude.com/docs/en/sub-agents>, <https://code.claude.com/docs/en/model-config>, <https://code.claude.com/docs/en/env-vars>
- Anthropic models and prices: <https://platform.claude.com/docs/en/about-claude/models/overview>, <https://platform.claude.com/docs/en/about-claude/pricing>, <https://claude.com/pricing>, <https://support.claude.com/en/articles/11049741-what-is-the-max-plan>
- Codex: <https://learn.chatgpt.com/docs/models>, <https://learn.chatgpt.com/docs/agent-configuration/subagents>, <https://learn.chatgpt.com/docs/config-file/config-reference>, and in <https://github.com/openai/codex> the files `codex-rs/core/src/tools/handlers/multi_agents_spec.rs`, `codex-rs/core/src/agent/child_config.rs` and `codex-rs/core/config.schema.json`
- Cursor: <https://cursor.com/docs/subagents>, <https://cursor.com/docs/models-and-pricing>
- Cortex Code: <https://docs.snowflake.com/en/user-guide/cortex-code/extensibility>, <https://docs.snowflake.com/en/user-guide/cortex-code/configure-model-settings>, <https://docs.snowflake.com/en/user-guide/cortex-code/settings>, <https://docs.snowflake.com/en/user-guide/cortex-code/cli-reference>

## Caveats

- **One run per arm per ticket.** The `clean` result turned on one reviewer's tiering of one finding.
- **No GitHub and no CI** in either arm, so the smoke-test failure in `final-catch` was found by the comparison and not by the run.
- **The three replays of an arm ran at the same time** on one machine.
- **The one-way-door ticket was not rerun,** so the rule that moves reviewers to the session's class on a one-way door is untested.
- **No run used a session above the Opus class.** Until 0.8.0 a worker inherited the session's model. On such a session the implementing worker and the reviewers now move down to the strong class, and no run measured that.

## Source data

The sandboxes, transcripts and per-ticket reports were working files of the session and are not in the repo, because they describe work in other repositories.
