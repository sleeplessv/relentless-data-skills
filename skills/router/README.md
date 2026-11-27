# router

Pick the model, reasoning effort and harness for each task a session hands to
another agent, across Anthropic, OpenAI and Google models. The skill produces a
route for each task and nothing else: the brief, the launch and the result
belong to the skill doing the work.

## Use

Ask a session to route a plan:

> Load `router` and split this migration into tasks, each on the model that fits it.

Name a harness and its models are used first:

> Use Cortex for the tasks you hand out.

Name a model and it is never swapped, substituted or escalated away:

> Run the design review on Fable 5.2.

Other skills call it to choose a model. A calling skill fixes any of the class,
the model, the effort or the harness for a role, and the router fills in the
rest.

## How a task is routed

1. The model is chosen from the task: the lowest of four model classes
   (`apex`, `strong`, `standard`, `light`) with a row that fits it.
2. The harness is chosen from the model. The task runs in the session's own
   harness when that harness carries the model, and otherwise in the model's
   own vendor harness through Herdr. When neither can be reached, a same-class
   model runs in the session's harness and the substitution is reported.
3. A task that fails its check moves one class up, with a fresh agent.

Cortex Code, Cursor and Antigravity carry more than one vendor's models, so a
session there reaches most models without leaving its harness. Cortex Code is
used only when the session runs in it or the user names it.

## Models covered

| Class | Anthropic | OpenAI | Google |
| --- | --- | --- | --- |
| `apex` | Claude Opus 5.5, then Claude Fable 5.2 | GPT-6.2 Astra | Gemini 4 Carbon, Gemini 4 Argon |
| `strong` | Claude Sonnet 5.5 | GPT-6.2 Sol | Gemini 4 Neon |
| `standard` | Claude Sonnet 5.5 at `low` effort | GPT-6.1 Terra | Gemini 4 Hydrogen |
| `light` | Claude Haiku 5.5 | GPT-6 Luna | Gemini 3.8 Flash |

Prices, input limits, and the ID each harness takes are in
[`references/catalog.md`](references/catalog.md), each with its source and an
as-of date. Probe commands and per-harness parameters are in
[`references/harnesses.md`](references/harnesses.md).

## Requirements

- **Another harness** is reached through the
  [`herdr-delegate`](../herdr-delegate/) skill, `0.1.8` or later, from a session
  running in Herdr. Without either, every task stays in the session's own
  harness.
- **OpenAI models through Codex** need `jq` to resolve the newest model slug.

## Not yet

[`orchestrator-mode`](../orchestrator-mode/) and the skills that take their
model classes from it ([`implement-ticket`](../implement-ticket/),
[`implement-feature`](../implement-feature/) and
[`implement-backlog`](../implement-backlog/)) still choose their own models,
under different class names: their strong class is Opus, which this skill calls
`apex`. Loaded beside one of them, `router` routes only the work the main
session hands out directly; the workers those skills start never load it and
keep their own classes. Load the two together only once
[#331](https://github.com/sleeplessv/relentless-data-skills/issues/331) lands;
generation two follows in
[#328](https://github.com/sleeplessv/relentless-data-skills/issues/328).

## Install

Use the [repository installation instructions](../../README.md#install), or
install this skill directly:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/router
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install router@relentless-data-skills
```
