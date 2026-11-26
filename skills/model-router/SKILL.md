---
name: model-router
description: Pick the model, reasoning effort and harness for each task a session hands to another agent, across Anthropic, OpenAI and Google models. Use when a session or another skill delegates work and must choose which model runs it, or when the user asks which model should handle a task.
argument-hint: "[task or plan to route]"
---

# Route each task to a model

A **route** is the model, reasoning effort and harness for one task, with the same-class model to use when that one cannot be reached. This skill produces routes and nothing else: the brief, the launch and the result belong to the skill doing the work.

Five words carry the rules:

- **Main session.** The session a person started and talks to.
- **Delegator.** A session that hands whole tasks to executors and checks their results. The main session is one whenever it hands tasks out; any other agent is one only when the session that started it said so. Only a delegator routes.
- **Executor.** An agent a delegator starts for one whole task. It chooses no model or harness and starts no other executor. When it thinks part of its task belongs on another model, it reports that to its delegator.
- **Helper.** An agent started for a small piece of its starter's own task, to keep bulk out of the starter's context. A delegator routes its helpers. An executor's helpers run on the model its own skill names, or the harness default.
- **Carry.** A harness carries a model when it can run a session or an agent on it. One harness can carry several vendors' models.

## What is already fixed

Take as given, in this order, a model, class, effort or harness that the user named, then one the calling skill fixed. Route only what is left open.

A model the user named is never swapped, substituted or escalated away. A model the calling skill fixed is never substituted or escalated either: that skill gets the blocked route or the failing output back and decides. The session's own model never changes; only the user can change it.

## 1. Find what the session can reach

Establish four facts. [references/harnesses.md](references/harnesses.md) holds the probe commands; read it for any fact you do not already have.

- The **home harness**: the harness the user named for this work ("use Cortex"), otherwise the one the session runs in. A harness the user did not name and the session does not run in is reached only as a model's own vendor harness.
- Which models the home harness carries.
- Whether Herdr and the `herdr-delegate` skill are present.
- Which vendor CLIs are installed: `claude` for Anthropic, `codex` for OpenAI, `agy` for Google.

Done when all four are written down.

## 2. Choose the class and the model

Give each task the lowest class with a row that fits it, and that row's first pick. The alternatives are in the order to try them. [references/catalog.md](references/catalog.md) holds each model's price, input limits and IDs; read it when a budget binds, or when the task's input is large or is not text.

| Class | Task | First pick | Same-class alternatives |
| --- | --- | --- | --- |
| `light` | File location, log triage, classification, JSON extraction | `Claude Haiku 5.5` | `GPT-6 Luna`, `Gemini 3.8 Flash` |
| `standard` | Routine edits, CI steps, wide batches of small tasks | `Gemini 4 Hydrogen` | `GPT-6.1 Terra`, `Claude Sonnet 5.5` at `low` effort |
| `standard` | Invoices, forms, drawings, screenshots, GUI automation | `GPT-6.1 Terra` | `Gemini 4 Hydrogen` |
| `strong` | Scoped feature coding, test suites, multi-source synthesis | `Claude Sonnet 5.5` | `GPT-6.2 Sol`, `Gemini 4 Neon` |
| `strong` | A review of a change by an agent that wrote none of it | The first of `Claude Sonnet 5.5`, `GPT-6.2 Sol` and `Gemini 4 Neon` from a vendor other than the author's | A fresh agent on the author's vendor |
| `apex` | Long autonomous coding, sprawling refactors, ambiguous migrations, stuck design | `Claude Opus 5.5` | `Gemini 4 Carbon`, `GPT-6.2 Astra` |
| `apex` | Formal mathematics, proofs, scientific code, rigid constraints | `GPT-6.2 Astra` | `Gemini 4 Carbon`, `Claude Opus 5.5` |
| `apex` | Whole-repository audits and other work grounded in very long input | `Gemini 4 Carbon` | `Claude Opus 5.5`, `GPT-6.2 Astra` |

- **Input fit.** The model must accept the task's input kind and size. The catalog lists both, with the price step above each long-input threshold. A task whose input is audio or video goes to a model the catalog lists for it, in the class its row gives.
- **Rank.** Within one vendor's models in a class, a rank orders them for escalation. `apex` has one: `Claude Opus 5.5`, then `Claude Fable 5.2`. Route to `Fable 5.2` directly only when the user names it.
- **Reviewers.** A reviewer on a lower class than the author reads and reports; it edits nothing.

Done when every task names one class and one model.

## 3. Choose the harness

A harness is **reachable** when the session runs in it, or when Herdr, `herdr-delegate` and that harness's CLI are all present. It carries the model **for a task** when its own list has the model and the task's input fits the model's window there.

Take the first that holds:

1. The home harness is reachable and carries the model for the task. The task runs there: as an agent of the session when the session runs in it, through Herdr otherwise.
2. The model's own vendor harness is reachable and carries the model for the task.
3. Neither holds. Route to the first same-class alternative in the task's row that the home harness carries for the task, and record the substitution. When the home harness is not reachable, use the session's own.

A model the user named or the calling skill fixed has no substitute: when neither 1 nor 2 holds, the task is **blocked** and step 6 applies. A task is also blocked when rule 3 finds no model.

Under 1 or 2, name the route's substitute as well: the model rule 3 would give, or `none`.

Each task gets its own route and its own agent. Grouping tasks under one agent is the calling skill's decision.

[references/harnesses.md](references/harnesses.md) gives the model parameter for an agent of each harness and the flags `herdr-delegate` needs for each CLI. The catalog gives each harness's own ID for the model.

Done when every task names its harness and its substitute or `none`, or is blocked.

## 4. Set the effort

Leave reasoning effort at the model's default except in two cases:

- **`low`** for `light` and `standard` tasks that search, classify or run recorded commands.
- **`high`** for `apex` and `strong` tasks of root-cause debugging, proof, security validation or a final review of a change.

Some harnesses cannot set effort for one agent; [references/harnesses.md](references/harnesses.md) names them. There the agent runs at the session's effort, and the route records the effort that was asked for and not applied.

Done when every task leaves effort unset, names one of the two cases, or records an effort not applied.

## 5. Check and escalate

Give every task that writes or transforms a check: a command that ends in pass or fail, such as a test, a build or a schema check.

When a task fails its check, give its next route. That route is for a fresh agent, handed the failing output and the first agent's decisions, on the next rung:

1. One class up: `light` to `standard`, `standard` to `strong`, `strong` to `apex`.
2. At `apex`, the next rank of the same vendor.
3. At the top rank, the same model at its maximum effort, where the harness can set effort for that agent.

Stop after three attempts in all, or when no rung is left, and report the task blocked with the failing output. A task on a model the user named, or one the calling skill fixed, climbs no rung: step 6 applies.

Done when every task that writes or transforms names its check and its next rung, or is marked as having none.

## 6. Say what was routed

Before the first task starts, say in one line each case where your pick differs from a model the user named, or where the work the session keeps for itself fits a higher class than the session's own model.

Then carry on, except in three cases:

- A model the user named cannot be reached.
- A task on a model the user named failed its check.
- A model the user named for a task is a lower class than that task's row, or the session's own model is a lower class than the row of work the session keeps.

In those the main session waits for the user's answer. Any other agent reports the case to the session that started it, which decides.

When the work ends, list every substitution and every effort not applied.

Done when each difference was said before its task started, and the closing list is given or there was nothing to list.
