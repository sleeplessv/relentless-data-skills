# Model catalog

As of 2026-11-26. Every figure was read on that date from the vendor page listed under [Sources](#sources). When a vendor ships or reprices a model, update its row here, its row in [The ID each harness takes](#the-id-each-harness-takes), and the as-of date together.

## Models

Prices are USD per 1M tokens at the standard rate, for the price in force on the as-of date.

| Class | Vendor | Model | API ID | Input | Output | Cache read | Long input | Input kinds | Effort values (default) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `apex` | Anthropic | Claude Fable 5.2 | `claude-fable-5-2` | 8.00 | 40.00 | 0.20 | None | Text, image, PDF | `low`, `medium`, `high`, `xhigh`, `max` (`high`) |
| `apex` | Anthropic | Claude Opus 5.5 | `claude-opus-5-5` | 4.00 | 20.00 | 0.20 | None | Text, image, PDF | `low`, `medium`, `high`, `xhigh`, `max` (`medium`) |
| `apex` | OpenAI | GPT-6.2 Astra | `gpt-6.2-astra` | 8.00 | 40.00 | 0.40 | Above 272K | Text, image | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` (`low`) |
| `apex` | Google | Gemini 4 Carbon | `gemini-4-carbon` | 2.00 | 10.00 | 0.10 | None | Text, image, PDF, audio, video | `low`, `medium`, `high` (`medium`) |
| `apex` | Google | Gemini 4 Argon | `gemini-4-argon` | 2.00 | 10.00 | 0.10 | None | Text, image, PDF, audio, video | `low`, `medium`, `high` (`medium`) |
| `strong` | Anthropic | Claude Sonnet 5.5 | `claude-sonnet-5-5` | 2.00 | 10.00 | 0.10 | None | Text, image, PDF | `low`, `medium`, `high`, `xhigh`, `max` (`high`) |
| `strong` | OpenAI | GPT-6.2 Sol | `gpt-6.2-sol` | 2.00 | 10.00 | 0.10 | Above 272K | Text, image | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` (`low`) |
| `strong` | Google | Gemini 4 Neon | `gemini-4-neon` | 3.00 | 15.00 | 0.15 | None | Text, image, PDF, audio, video | `low`, `medium`, `high`, `xhigh` (`high`) |
| `standard` | OpenAI | GPT-6.1 Terra | `gpt-6.1-terra` | 1.00 | 5.00 | 0.05 | Above 272K | Text, image | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` (`low`) |
| `standard` | Google | Gemini 4 Hydrogen | `gemini-4-hydrogen` | 1.50 | 7.50 | 0.075 | None | Text, image, PDF, audio, video | `low`, `medium`, `high`, `xhigh` (`high`) |
| `light` | Anthropic | Claude Haiku 5.5 | `claude-haiku-5-5` | 0.10 | 0.50 | 0.01 | Above 100K | Text, image, PDF | `low`, `medium`, `high`, `xhigh`, `max` (`medium`) |
| `light` | OpenAI | GPT-6 Luna | `gpt-6-luna` | 0.10 | 0.50 | 0.01 | Above 272K | Text, image | `low`, `medium`, `high`, `xhigh`, `max` (`medium`) |
| `light` | Google | Gemini 3.8 Flash | `gemini-3.8-flash` | 0.75 | 3.75 | 0.075 | None | Text, image, PDF, audio, video | `low`, `medium`, `high` (`medium`) |

- **Anthropic has no `standard` model.** A session that reaches only Anthropic models runs `standard` tasks on `Claude Sonnet 5.5` at `low` effort.
- **`Gemini 4 Argon`** is carried by the same harnesses as `Carbon` at the same price. No row of the task table picks it; use it when the user names it.
- **Maximum effort** is the last value in a model's list.
- **OpenAI effort values and defaults** are the ones Codex lists (`codex debug models`), since Codex is the harness that runs these models. OpenAI's API pages do not state them for `Astra` and `Sol`.

## Long input

A model's price or reach changes above a threshold. Count the whole prompt, cached tokens included.

| Model | Threshold | Above it |
| --- | --- | --- |
| Claude Haiku 5.5 | 100,000 prompt tokens | Input 0.50, output 2.50, cache read 0.05. Up to 272,000 tokens `GPT-6 Luna` is then the cheaper `light` pick. |
| GPT-6.2 Astra, GPT-6.2 Sol, GPT-6.1 Terra, GPT-6 Luna | 272,000 input tokens | Input and cache read double and output is 1.5 times, for the whole request. |
| GPT-6.2 Astra and GPT-6 Luna, in Codex | 272,000 tokens | Codex's default window for these two. Larger input fits only in a session whose `model_context_window` is set higher, to 872,000 at most. |
| GPT-6.2 Sol and GPT-6.1 Terra, in Codex | 500,000 tokens | Codex's default window for these two, with the same setting and the same maximum. |

Every other window is about 1M tokens: 1M on Anthropic's API, 922,000 input tokens on OpenAI's, and 1,048,576 on Google's. The Gemini 4 models share that figure between input and output. `Gemini 3.8 Flash` takes it as input alone, with 65,536 output tokens on top.

## Dated changes

Apply each from its date:

- **2026-12-01.** `Gemini 4 Carbon` and `Gemini 4 Argon` become input 4.00, output 20.00, cache read 0.20.
- **2027-01-01.** `Gemini 3.8 Flash` becomes input 1.50, output 7.50, cache read 0.15.

## The ID each harness takes

`none` means the harness had no ID for that model on the as-of date. This table maps names; it does not say what an account can use. The harness's own list, read as [harnesses.md](harnesses.md) describes, decides what it carries.

| Model | Claude Code | Codex | Antigravity | Cortex Code |
| --- | --- | --- | --- | --- |
| Claude Fable 5.2 | `fable` | none | none | none |
| Claude Opus 5.5 | `opus` | none | `claude-opus-5-5-<effort>` | `claude-opus-5-5` |
| Claude Sonnet 5.5 | `sonnet` | none | `claude-sonnet-5-5-<effort>` | `claude-sonnet-5-5` |
| Claude Haiku 5.5 | `haiku` | none | none | `claude-haiku-5-5` |
| GPT-6.2 Astra | none | Resolver family `astra` | none | `openai-gpt-6.2-astra` |
| GPT-6.2 Sol | none | Resolver family `sol` | none | `openai-gpt-6.2-sol` |
| GPT-6.1 Terra | none | Resolver family `terra` | none | `openai-gpt-6.1-terra` |
| GPT-6 Luna | none | Resolver family `luna` | none | `openai-gpt-6-luna` |
| Gemini 4 Carbon | none | none | `gemini-4-carbon-<effort>` | `gemini-4-carbon` |
| Gemini 4 Argon | none | none | `gemini-4-argon-<effort>` | `gemini-4-argon` |
| Gemini 4 Neon | none | none | `gemini-4-neon-<effort>` | `gemini-4-neon` |
| Gemini 4 Hydrogen | none | none | `gemini-4-hydrogen-<effort>` | `gemini-4-hydrogen` |
| Gemini 3.8 Flash | none | none | `gemini-3.8-flash-<effort>` | `gemini-3.8-flash` |

- **Cortex Code** prefixes every OpenAI model with `openai-`.
- **Antigravity** IDs end in the effort; `<effort>` stands for an effort `agy models` lists for that model, which can be fewer than the model's row above gives.
- **Cursor** has no column: its IDs come from its own model list.

## Sources

- Anthropic prices, cache and long input: <https://platform.claude.com/docs/en/about-claude/pricing>
- Anthropic windows and default effort: <https://platform.claude.com/docs/en/models/overview>
- Anthropic effort values: <https://platform.claude.com/docs/en/build-with-claude/effort>
- OpenAI prices and the 272K threshold: <https://developers.openai.com/api/docs/pricing.md>
- OpenAI limits and input kinds: the model pages under <https://developers.openai.com/api/docs/models/>
- Google prices and dated changes: <https://aistudio.google.com/docs/pricing>
- Google limits and input kinds: the model pages under <https://aistudio.google.com/docs/models/>
- Google effort values: <https://aistudio.google.com/docs/thinking>
- Codex windows and effort values: `codex debug models`, on the as-of date. The window setting: <https://learn.chatgpt.com/docs/config-file/config-reference>
- Antigravity and Cortex Code IDs: `agy models` and the Cortex probe in [harnesses.md](harnesses.md), on one account on the as-of date.
