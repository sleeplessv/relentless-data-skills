# model-router

Choose the model, reasoning effort, and dispatch channel for each delegated task
across Google Gemini 4, OpenAI GPT-6, and Anthropic Claude 5. Pairs task shape
and modality with API token economics across four model classes (`apex`,
`strong`, `standard`, and `light`), defaults to staying in the active harness to
preserve prompt caching, and crosses vendors when capability or review
independence justifies a fresh session.

## Use

Ask an orchestrator session to route a plan or delegate with model routing:

> Load `model-router` and break this migration into tasks assigned to the best model and effort for our budget.

Or combine it with [`orchestrator-mode`](../orchestrator-mode/) and
[`herdr-delegate`](../herdr-delegate/):

> In orchestrator mode with `model-router`, audit the repo, implement the fix, and get a cross-vendor defect review.

## Model classes covered

| Class | Google | OpenAI | Anthropic | Input USD per 1M | Output USD per 1M |
| --- | --- | --- | --- | --- | --- |
| `apex` | Gemini 4 Carbon, Argon | GPT-6.2 Astra | Claude Fable 5.2 | 4.00 to 10.00 | 20.00 to 50.00 |
| `strong` | Gemini 4 Neon | GPT-6.2 Sol | Claude Opus 5.5 | 2.00 to 4.00 | 10.00 to 20.00 |
| `standard` | Gemini 4 Hydrogen | GPT-6.1 Terra | Claude Sonnet 5.5 | 1.00 to 2.00 | 5.00 to 10.00 |
| `light` | Gemini 3.5 Flash-Lite | GPT-6 Luna | Claude Haiku 5.5 | 0.10 to 0.30 | 0.50 to 2.50 |

Full capability notes, prompt-cache discounts, and multi-model pairing stacks
live in [`references/catalog.md`](references/catalog.md). Harness parameter
mappings and Herdr cross-vendor launch commands live in
[`references/dispatch.md`](references/dispatch.md).

## Install

Use the [repository installation instructions](../../README.md#install), or
install this skill directly:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/model-router
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install model-router@relentless-data-skills
```
