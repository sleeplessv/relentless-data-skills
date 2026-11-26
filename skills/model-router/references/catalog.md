# Frontier model catalog and economics

Snapshot dated `2026-11`. Update prices, slugs, and capability notes together when a lab ships a new generation or retires a model.

## Core four-class matrix

Prices are uncached USD per 1M tokens. Every core model below accepts roughly 1M input tokens.

| Class | Vendor | Model | API ID | Input USD | Output USD | Cache read note | Context and max output | Reasoning control |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `apex` | Google | Gemini 4 Carbon | `gemini-4-carbon` | 4.00 | 20.00 | About 0.15 USD (95% off); promo 2.00 in, 10.00 out through 2026-11-30 | 1M unified, 64K sync out (1M background decode) | `low`, `medium` (default), `high` |
| `apex` | OpenAI | GPT-6.2 Astra | `gpt-6.2-astra` | 10.00 | 50.00 | 30% to 40% batch and cache discounts | 1.05M input, 128K output | Adjustable (`low` to `max`) |
| `apex` | Anthropic | Claude Fable 5.2 | `claude-fable-5-2` | 8.00 | 40.00 | Standard prompt cache discounts | 1M input, 128K output | Adaptive thinking with effort |
| `strong` | Google | Gemini 4 Neon | `gemini-4-neon` | 3.00 | 15.00 | 0.15 USD (95% off repeated context) | 1M unified, 64K sync out (1M background decode) | `low`, `medium`, `high` (default), `xhigh` |
| `strong` | OpenAI | GPT-6.2 Sol | `gpt-6.2-sol` | 2.00 | 10.00 | 30% to 40% batch and cache discounts | 1.05M input, 128K output | Adjustable effort |
| `strong` | Anthropic | Claude Opus 5.5 | `claude-opus-5-5` | 4.00 | 20.00 | Standard prompt cache discounts | 1M input, 128K output | Adaptive thinking with effort |
| `standard` | Google | Gemini 4 Hydrogen | `gemini-4-hydrogen` | 1.50 | 7.50 | 0.075 USD (95% off); AI Studio free tier | 1M unified, 64K sync out (1M background decode) | `low`, `medium`, `high`, `xhigh` |
| `standard` | OpenAI | GPT-6.1 Terra | `gpt-6.1-terra` | 1.00 | 5.00 | 30% to 40% batch and cache discounts | 1.05M input, 128K output | Adjustable effort |
| `standard` | Anthropic | Claude Sonnet 5.5 | `claude-sonnet-5-5` | 2.00 | 10.00 | Halved cache-read rate versus prior Sonnet | 1M input, 128K output | Adaptive thinking with effort |
| `light` | Google | Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite` | 0.30 | 2.50 | Standard cache discounts | 1M input, 64K output | `minimal` (default), `low`, `medium`, `high` |
| `light` | OpenAI | GPT-6 Luna | `gpt-6-luna` | 0.10 | 0.50 | Standard cache discounts | 1.05M input, 128K output | Minimal fast mode |
| `light` | Anthropic | Claude Haiku 5.5 | `claude-haiku-5-5` | 0.10 | 0.50 | Base rate applies under 100K input tokens | 1M input, 128K output | Lightweight adaptive |

## Model notes by class

### Apex class

- **Gemini 4 Carbon (`gemini-4-carbon`).** Google's heaviest deep-reasoning model. Best at multi-day software engineering loops, whole-repository comprehension, defensive cybersecurity validation, and cross-modal tasks mixing code, PDFs, audio, and video. Leads anti-fabrication benchmarks (AA-Omniscience) while costing half as much as `Claude Fable 5.2` and 60 percent less than `GPT-6.2 Astra` even at its December 2026 standard rate (`4.00` input, `20.00` output USD). Trade-off: slower per turn than `Neon`; pick `Neon` when tasks do not need deep `Carbon` deliberation.
- **GPT-6.2 Astra (`gpt-6.2-astra`).** OpenAI's flagship, shipped November 2026 to succeed `GPT-6 Astra` and legacy `o3`. Best at formal mathematics (FrontierMath, ARC-AGI), strict constraint adherence, bioinformatics and scientific computing, and complex hosted-shell or browser tool chains. Trade-off: highest price in the catalog (`10.00` input, `50.00` output USD, five times `Sol`), and can over-index on exhaustive detail when requirements are intentionally loose.
- **Claude Fable 5.2 (`claude-fable-5-2`).** Anthropic's apex model sitting above `Opus 5.5`. Best at sprawling software migrations, ambiguous architectural trade-offs, and serving as an escalation advisor when `Opus 5.5` or `Sonnet 5.5` hits a structural wall. Trade-off: at `8.00` input and `40.00` output USD, Anthropic recommends starting heavy runs on `Opus 5.5` and consulting `Fable 5.2` selectively.

### Strong class

- **Gemini 4 Neon (`gemini-4-neon`).** Distilled and adapted from `Carbon` to finish complex multi-step engineering and knowledge tasks faster with fewer wasted output tokens. Scores roughly 61 on the Artificial Analysis Intelligence Index, ranks near the top of Zapier's AutomationBench for business workflow execution, and supports `xhigh` thinking. Its `0.15` USD per 1M cache-read rate makes iterative long-context sessions cheap.
- **GPT-6.2 Sol (`gpt-6.2-sol`).** OpenAI's professional engineering workhorse. Reaches 95 to 99 percent of `Astra` capability on coding benchmarks (55 to 58 percent on Terminal-Bench 4.0 versus 58 to 59 percent for `Astra`) at 20 percent of the price (`2.00` input, `10.00` output USD). Default pick inside Codex and OpenAI stacks for feature implementation, refactors, and structured synthesis. Trade-off: lacks native audio and video inputs, and costs twice `Terra` for screenshot-heavy UI jobs.
- **Claude Opus 5.5 (`claude-opus-5-5`).** Anthropic's primary model for multi-hour autonomous coding, cross-system refactoring, desktop computer use, and high-craft analytical writing. Excels when human prompts are under-specified and design taste matters. Trade-off: costs twice `GPT-6.2 Sol` and `Claude Sonnet 5.5` (`4.00` input, `20.00` output USD), and `Sonnet 5.5` often matches it on tightly scoped terminal tasks.

### Standard class

- **Gemini 4 Hydrogen (`gemini-4-hydrogen`).** Replaces older Flash models as Google's everyday developer default. Completes routine edits and sub-agent handoffs roughly 2.5 times faster than `Gemini 3.8 Flash`, keeps the full 1M multimodal window and `xhigh` thinking option, and drops cached reads to `0.075` USD per 1M tokens.
- **GPT-6.1 Terra (`gpt-6.1-terra`).** OpenAI's visual and GUI specialist (`1.00` input, `5.00` output USD). Tuned for parsing dense invoices, engineering drawings, forms, and UI screenshots, matching `Astra` on select visual agentic evaluations at one-tenth the cost. Trade-off: trails `Sol` by roughly 8 points on heavy terminal software engineering (about 50 percent versus 58 percent on Terminal-Bench 4.0), so keep backend coding on `Sol`.
- **Claude Sonnet 5.5 (`claude-sonnet-5-5`).** Anthropic's balanced daily driver (`2.00` input, `10.00` output USD). Roughly 30 percent more token-efficient than earlier Sonnet releases, with halved cache-read pricing. Trades blows with `Opus 5.5` on scoped developer benchmarks while returning much faster.

### Light class

- **Gemini 3.5 Flash-Lite (`gemini-3.5-flash-lite`).** Retained in Google AI Studio as the lowest-latency utility option (`0.30` input, `2.50` output USD) with a `minimal` default thinking mode and 1M multimodal input. Pick it over `Luna` and `Haiku 5.5` when high-volume streams contain audio, video, or huge PDFs; pick `Luna` or `Haiku 5.5` for plain text.
- **GPT-6 Luna (`gpt-6-luna`).** OpenAI's bulk economy model (`0.10` input, `0.50` output USD, one-twentieth of `Sol`). Built for high-throughput classification, JSON schema extraction, PII redaction, and bulk summarization. Unsuited for open-ended coding (about 16 percent on Terminal-Bench 4.0).
- **Claude Haiku 5.5 (`claude-haiku-5-5`).** Anthropic's fastest model (`0.10` input, `0.50` output USD under 100K input tokens, roughly 75 percent cheaper than prior Haiku). Strong text and basic logic parity for its size; best choice for live chat routing, file skimming, and nimble read-only helpers under `Opus 5.5` or `Sonnet 5.5`.

## Sibling and specialized models

- **Gemini 4 Argon (`gemini-4-argon`).** Token-frugal reasoning sibling to `Carbon` at identical pricing (`2.00` input and `10.00` output USD promo through `2026-11-30`, then `4.00` input and `20.00` output USD; cache read `0.10` shifting to `0.20` USD). Use when extended analytical or math runs burn too many output tokens on `Carbon`.
- **Gemini 3.8 Flash (`gemini-3.8-flash`).** Previous-generation high-throughput Flash model retained for existing high-speed video and audio pipelines; prefer `Gemini 4 Hydrogen` for new agentic code workflows.
- **Claude Mythos 5.2.** Same weights as `Claude Fable 5.2`, restricted to vetted defensive cybersecurity and biological research programs. Standard API accounts route `apex` work to `claude-fable-5-2`.
- **OpenAI specialized endpoints.** Use `GPT-Live-1` or `gpt-realtime-2.1` for low-latency bidirectional voice, `GPT-Image-2.6` for image generation, `text-embedding-3` for vector retrieval, and `gpt-oss` when weights must run locally. Legacy `GPT-5` snapshots and standalone `o3` and `o4-mini` endpoints are deprecated in favor of `GPT-6` model classes with adjustable reasoning effort.

## Cost-efficient multi-model stacks

- **Google stack (`Carbon` or `Neon`, `Hydrogen`, and `3.5 Flash-Lite`).** Plan and audit whole repositories on `Carbon` or `Neon`, fan out file edits and test runs to `Hydrogen`, and pre-index media or logs with `3.5 Flash-Lite`. Keeping the run inside Gemini preserves 95 percent prompt-cache discounts across the 1M window.
- **OpenAI stack (`Sol`, `Terra`, and `Luna`, with `Astra` on escalation).** Run everyday implementation on `GPT-6.2 Sol`, route screenshot and document steps to `GPT-6.1 Terra`, run extraction and triage on `GPT-6 Luna`, and escalate to `GPT-6.2 Astra` only when a formal proof or `Sol` check fails.
- **Anthropic stack (`Opus 5.5` or `Sonnet 5.5` with `Haiku 5.5`, and `Fable 5.2` advisor).** Default scoped tickets to `Sonnet 5.5` and open-ended refactors to `Opus 5.5`, skim files with `Haiku 5.5`, and consult `Fable 5.2` at fixed checkpoints (before locking in a risky design, or after a failed check). In Anthropic's Advisor tool, advisor reads are uncached across calls; cap advisor `max_tokens` near `2048` and gate calls by explicit checkpoints rather than open-ended self-doubt.
- **High-return cross-vendor pairs.** Three cross-vendor hops repay losing cache sharing:
  1. `Claude Opus 5.5` or `Gemini 4 Carbon` author paired with a read-only `GPT-6.2 Astra` defect reviewer (`astra-review`).
  2. `Claude` or `Codex` coordinator handing video, audio, or million-token repo grounding to `Gemini 4 Carbon` or `Hydrogen`.
  3. Any coordinator handing high-volume invoice, schematic, or GUI automation batches to `GPT-6.1 Terra`.
