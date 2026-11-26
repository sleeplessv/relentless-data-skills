---
name: model-router
description: Pick the model and reasoning effort for each delegated task across Google Gemini 4, OpenAI GPT-6, and Anthropic Claude 5, matched by task fit and token cost. Use when an orchestrator routes subagents or cross-agent helpers by workload or budget, or when the user asks which model should handle a task.
argument-hint: "[task or plan to route]"
---

# Route tasks across frontier models

Assign each delegated task to the cheapest model class and vendor that fits its modality, reasoning demand, and failure cost. Four model classes span Google Gemini 4, OpenAI GPT-6, and Anthropic Claude 5:

- **Apex.** Maximum reasoning depth for formal proofs, stuck architecture, whole-repo grounding, and escalation (`Gemini 4 Carbon`, `GPT-6.2 Astra`, `Claude Fable 5.2`).
- **Strong.** Heavy workhorse for autonomous coding, multi-file refactors, reviews, and synthesis (`Gemini 4 Neon`, `GPT-6.2 Sol`, `Claude Opus 5.5`).
- **Standard.** Fast production execution for scoped edits, visual or GUI tasks, and worker fan-outs (`Gemini 4 Hydrogen`, `GPT-6.1 Terra`, `Claude Sonnet 5.5`).
- **Light.** High-volume extraction, classification, file location, and routing (`Gemini 3.5 Flash-Lite`, `GPT-6 Luna`, `Claude Haiku 5.5`).

## 1. Check what the session can reach

Identify the active harness, its vendor, and whether cross-vendor CLIs
(`claude`, `codex`, `agy`) and Herdr (`HC_TERMINAL_ID`) are available. Read
[references/dispatch.md](references/dispatch.md) when you need the probe
script, exact per-harness model parameters, or cross-vendor launch flags.

Stay in the active harness by default. Crossing vendors starts a new process
and drops prompt-cache sharing with the coordinator, which reaches 95 percent
off cached input on Gemini 4 and 50 percent off cache reads on Claude Sonnet
5.5. Cross vendors only when another lab holds a clear capability or cost
advantage on the task, or when an independent review needs a second model
family. When a target CLI or Herdr is unavailable, map the chosen model class
to the active harness's own model in that class and record the substitution.

Done when the reachable harnesses, the session's model class, and whether
cross-vendor dispatch is available are known.

## 2. Match each task to a model

Split work into independent tasks before routing. Keep planning and final
trade-off calls on a `strong` or `apex` coordinator, and send bounded edits,
searches, and transforms to `standard` or `light` helpers. Take the first row
in the table below that fits each task. Prices are standard uncached USD per 1M
tokens (`input, output`). Read [references/catalog.md](references/catalog.md)
when two models tie, when budget caps bind, or when you need context limits,
cache rates, or multi-model pairing stacks.

| Task shape | Class | First pick (in, out USD) | Same-class alternatives | Why it wins |
| --- | --- | --- | --- | --- |
| Formal math, strict proofs, scientific code, rigid constraints | `apex` | `GPT-6.2 Astra` (10.00, 50.00) | `Gemini 4 Carbon` (4.00, 20.00), `Claude Fable 5.2` (8.00, 40.00) | Highest ceiling on formal logic, FrontierMath, ARC-AGI, and strict rules. |
| Ambiguous migrations, fuzzy specs, stuck design decisions | `apex` | `Claude Fable 5.2` (8.00, 40.00) | `Gemini 4 Carbon` (4.00, 20.00), `GPT-6.2 Astra` (10.00, 50.00) | Strongest architectural judgment when under-specified work stalls `Opus 5.5`. |
| Whole-repo audits, cyber defense, grounded long-context work | `apex` | `Gemini 4 Carbon` (4.00, 20.00) | `Claude Fable 5.2` (8.00, 40.00), `GPT-6.2 Astra` (10.00, 50.00) | Unified 1M multimodal window, lowest fabrication rate, half rival `apex` cost (`Argon` saves thinking tokens). |
| Multi-hour autonomous coding, messy refactors, nuanced prose | `strong` | `Claude Opus 5.5` (4.00, 20.00) | `GPT-6.2 Sol` (2.00, 10.00), `Gemini 4 Neon` (3.00, 15.00) | Sustains design judgment and autonomous debugging across sprawling diffs. |
| Scoped feature coding, test suites, multi-source synthesis | `strong` or `standard` | `GPT-6.2 Sol` (2.00, 10.00) or `Claude Sonnet 5.5` (2.00, 10.00) | `Gemini 4 Neon` (3.00, 15.00) | Reaches 95 percent of `apex` coding quality at 2.00 input and 10.00 output USD. |
| Independent defect or requirements review of a change | `strong` or `apex` | Cross-vendor `strong` or `apex` | Fresh same-vendor `strong` helper | A second model family catches defects same-model review misses. Keep weaker models read-only. |
| Invoices, forms, CAD drawings, screenshots, GUI automation | `standard` | `GPT-6.1 Terra` (1.00, 5.00) | `Claude Opus 5.5` (4.00, 20.00), `Gemini 4 Neon` (3.00, 15.00) | Matches `Astra` on visual agentic exams at 1.00 input and 5.00 output USD; pick `Opus 5.5` for novel desktop recovery. |
| Native video, audio, or mixed PDF and media repositories | `standard` or `strong` | `Gemini 4 Hydrogen` (1.50, 7.50) or `Gemini 4 Neon` (3.00, 15.00) | `Gemini 3.5 Flash-Lite` (0.30, 2.50) for bulk media triage | Native audio and video across a unified 1M window with 95 percent cache discounts. |
| Fast routine code edits, CI helpers, wide worker fan-outs | `standard` | `Gemini 4 Hydrogen` (1.50, 7.50) | `Claude Sonnet 5.5` (2.00, 10.00), `GPT-6.1 Terra` (1.00, 5.00) | High-speed Gemini 4 execution for worker handoffs, with 0.075 USD cached reads. |
| File location, log triage, classification, JSON extraction | `light` | `GPT-6 Luna` (0.10, 0.50) or `Claude Haiku 5.5` (0.10, 0.50) | `Gemini 3.5 Flash-Lite` (0.30, 2.50) | Costs 0.10 input and 0.50 output USD; `Luna` fits bulk ETL, `Haiku 5.5` fits live routing and sub-agent skims. |

Done when every task in the plan records one target model, its model class, its dispatch channel, and its fallback model.

## 3. Set reasoning effort

Leave reasoning effort at the model default unless one of three cases applies:

- **Low** (`low`, or `minimal` on `Gemini 3.5 Flash-Lite`) for `light` and `standard` helpers running file search, classification, or recorded commands, and for review passes tuned to cut false positives.
- **High** (`high`) for `apex` and `strong` helpers handling root-cause debugging, formal proofs, security validation, or final defect reviews.
- **Maximum** (`xhigh` on `Neon` and `Hydrogen`, `max` on `Astra`) only after a task failed its check at `high`. Raising effort from `low` to maximum multiplies token spend 2.5 to 5 times and can lower pass rates on routine coding.

Done when every task either leaves effort unset or names one of the three rules above.

## 4. Escalate on failed checks

Agents overestimate their own pass rates, and issue text alone hides coupling. Pair upfront routing with check-driven escalation:

1. Attach an external check (a test command, build, schema check, or independent review) to every write or transform task.
2. When a task fails its check, dispatch a fresh helper one model class up (`light` to `standard`, `standard` to `strong`, `strong` to `apex`) with the failed check output and the prior helper's decisions.
3. Cap retries at three total attempts per task, then report the task blocked with the failing output.
4. Keep any helper with edit rights at or above the author's model class. A weaker reviewer that edits code lowers pass rates while raising spend.

Done when every write or transform task names its check and its next-class escalation model, or sits at `apex`.
