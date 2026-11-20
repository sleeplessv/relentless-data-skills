# Research: what "When to fold subagents" and "Building multi-agent systems" add to the three guiding articles

Dated 2026-11-20. This note reads two Anthropic articles that the three guiding articles cite but that were not read with them. It asks what decision rules they give on when one agent beats several, and on how a multi-agent run should be structured, beyond principles P1 to P14 of the earlier synthesis of those three articles (a run-directory note, not in the repo; the principles are restated in short below where they are compared). It closes with what the two pieces imply for three open design decisions. Text in quotation marks is copied word for word from the article. Text marked **Inference** is this reader's view, not the article's.

## Sources and method

| Short name | Article | Author, date on page | URL | Fetched |
| --- | --- | --- | --- | --- |
| Fold | Building agents: When to fold subagents into your main agent loop | Diane Sarkis, October 22, 2026 | <https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop> | 2026-11-20, HTTP 200 |
| MAS | Building multi-agent systems: When and how to use them | Cara Phillips with Paul Chen, Andy Schumeister, Brad Abrams, Theo Chu, January 23, 2026 | <https://claude.com/resources/articles/building-multi-agent-systems-when-and-how-to-use-them> | 2026-11-20, HTTP 200 |

Both links were taken from the raw text of the guiding articles: Fold is linked from "Which Claude model should you build with?" (A1) and from "Multi-agent coordination patterns" (A2); MAS is linked from A2, which calls it "our previous post". Each page was downloaded with curl and converted to plain text locally; no summarising reader was used. Both were read in full, code samples included.

Both are vendor articles about building agents on Anthropic's platform. Fold is about enterprise, customer-facing agents; MAS uses support, research and coding examples. Neither reports a method, sample size or confidence for its numbers. MAS's code samples name `claude-sonnet-4-5` and its text names Claude Opus 4.5, so it reflects the models of early 2026. MAS also links to Fold, which was published nine months later, so the MAS page has been edited since its stated date.

P1 to P14, for reference: P1 default to one agent; P2 subagents keep the expensive context lean for verbose reading; P3 concrete verification before any other escalation; P4 cap loops and name the fallback; P5 model by role and cost per finished task; P6 judgement and edits on the strong model; P7 cheap pass first, strong pass on failures; P8 decompose by context and partition shared resources; P9 durable shared project state; P10 workers pull work; P11 limits in the environment, in layers; P12 do not let agents give up on hard work; P13 code, not a model, applies simple routing rules; P14 carry a short written plan across model switches and fresh workers.

## Fold: when to fold subagents into the main agent loop

### Claims, rules and numbers

- **Single agent with skills wins more often than expected.** "In our comparisons across several enterprise deployments, a single agent with skills frequently outperformed both the one-prompt-for-everything design and the subagent design on quality, and often at a lower cost and latency per task." No figures are given for quality or cost. The one number: "One customer that evaluated their multi-agent harness against a single agent loop saw a roughly 2x faster runtime with the latter."
- **Most structure is no longer needed.** On designs built from a classifier, a fixed pipeline, segment buckets, branches and an orchestrator: "most of this structure was doing work the model no longer needed done for it, and that one clear system prompt, 4-5 thin data tools, and firm output guardrails would cover most of the use case."
- **Three conditions for keeping subagents.** The article's list reads, item by item: "A single agent loop hits measurable performance degradation from context bloat, or"; "Multiple tasks need to be tackled in parallel with fresh context windows that can be discarded once the task is done, or"; "A single agent struggles to select appropriate tools or there are conflicting instructions in the system prompt."
- **Do not split by owner or problem type.** "too often we see enterprises give each team or problem type its own subagent, with the agent architecture becoming a copy of their org chart (Conway's law at work)." Named failure modes: lossy context exchange, "Subagent sprawl", "The Frankenprompt" (each team adds a sentence, "resulting in conflicting rules"), local evals no one owns, and latency.
- **Shared context gives better answers.** "An agent that has seen the result of each earlier step can connect them, which leads to richer outputs and better insights than a set of summaries handed back by subagents. It also means fewer context windows and fewer lossy handoffs."
- **Progressive disclosure replaces the main reason to split.** Skills and deferred tools are loaded only when needed, which "removes the main reason teams previously split work across subagents." Anthropic "reduced Claude Code's system prompt for more advanced models by over 80%".
- **Models now check themselves; harness structure can get in the way.** "recent models increasingly narrate their progress and check their work as they go, which makes some harness elements redundant." And: "in migrations we have helped customers with, rigid multi-agent structures were often what stopped the new model from doing more of the work."
- **The single-loop design.** "One model and one context window running an open-ended tool loop, with limits (turn and cost budgets, write gates) set in the harness." The harness runs each turn's tool calls in parallel. "The loop stops when the model answers or hits a budget. A goal or verifier check can optionally run after the answer." "The model writes its plan in context on the first turn and revises it as results arrive. ... the model that writes the plan is also the one carrying it out, so it can change the plan mid-turn." "Ordering and domain procedure move into skills." "Hard limits (validation, approval gates) ... move into the tools."
- **Preconditions live in tools.** "if Y needs X's output, Y's tool checks for it and returns an instruction the model can act on." Per-user permission checks work the same way, returning "a plain refusal the model can read".
- **If multi-agent, keep it simple and split by context.** "start with the simplest pattern (generator-verifier, orchestrator-subagent, or other) that could work. ... give each subagent a piece of work that needs little from the rest of the system and have it hand back a compact result". Split by problem type, agents play a "telephone game".
- **What to merge.** "Merge specialists that chain on each other's output, touch the same data, or are often called together." A specialist usually followed by a second one is "a tightly coupled pair".
- **Call subagents as tools, not handoffs.** A kept subagent is best called as a tool so the main agent keeps the conversation; "We'd only recommend a full handoff, where the subagent takes over the conversation, when it needs to talk to the user directly." This allows "a shared response schema for subagents" and lets the main agent "verify the conclusion against real data". Remaining costs: each call "still hands back a lossy summary" and "is a nested model loop that adds latency".
- **Measure each fold.** "Even a set of 10 golden examples is enough to start." Fold "one at a time", "Compare eval performance with and without the subagent", and look at "which tasks flipped", not only the score. In their test, a fold lowered latency but broke a passing process (the main agent answered without asking the shipping specialist). "make sure your eval has a task for every chain of agents that runs together in production and for every rule the agent must not break, and run each task more than once, since a break like this one only showed up in one run out of two." Closing rule: "fold in one subagent, and keep it as a subagent only if the folded version scores worse". General principle: "measure, change one thing at a time, and keep what holds up."
- **Tool count threshold.** Group tools by user intent, "because once you exceed 30-50 tool definitions in the system prompt, tool choice tends to degrade."
- **Ownership and pruning.** "One central team should own end-to-end quality and the system prompt". Skills get a named owner and evals; `/skill-doctor` shows "what each skill in your library costs and how often it's actually used" so owners can "delete dead weight". `/claude-api prompt-audit` flags "instructions written for older models" that make the agent "slower or more rigid".

### Against P1 to P14

| Fold rule | Relation | Note |
| --- | --- | --- |
| Single agent with skills beats subagents; most structure is unneeded | Repeats P1, stronger | P1 says default to one agent. Fold adds that this held across several deployments on quality, cost and latency, with one 2x runtime figure. |
| Three conditions for subagents | Repeats P1 and P2, adds a third | The tool-selection or conflicting-instructions condition is new. "Measurable" degradation sets an evidence bar the P list does not. |
| Do not split by owner or problem type (Conway's law) | Repeats P8 | Adds the named failure modes (Frankenprompt, sprawl, unowned evals). |
| Shared context gives better answers; progressive disclosure removes the main reason to split | Tension with P2 | P2 sends verbose reading to subagents. Fold says one context that has seen every step connects them better than summaries. MAS (below) gives the thresholds that reconcile the two. |
| Models check their own work; rigid structure blocks new models; prompt-audit for old-model rules | New | No P addresses harness rules that outlive the model they were written for. |
| Plan written and carried out by the same model; planner code removed | New; mild tension with P13 | P13 keeps simple routing in code. Fold keeps code for limits and mechanical steps but gives planning to the model. They agree that hard limits belong in code. |
| Budgets and write gates in the harness; preconditions and permissions in tools | Repeats P4 and P11 | Adds the pattern of a tool that refuses with an instruction the model can act on. |
| Post-answer verifier is optional | New; pulls against the guiding articles' generator-verifier default | P3 is about concrete checks, which Fold keeps; it does not require a separate verifying agent. |
| Merge agents that chain, share data or run together | New | A concrete merge test. |
| Call kept subagents as tools; full handoff only to talk to the user | New | Bears on handoff depth (the guiding synthesis quoted A2: details are lost "After several such handoffs"). |
| 10 golden tasks, one change at a time, run each task more than once, read which tasks flipped | New | A1's "Measure on your own work" is in the guiding articles but is not one of P1 to P14. |
| 30-50 tool definitions | New number | |
| Central owner of end-to-end quality; usage-based pruning of skills | New | |

## MAS: building multi-agent systems, when and how

### Claims, rules and numbers

- **Three situations, and nothing else.** "we've identified three situations where multiple agents consistently outperform a single agent: when context pollution degrades performance, when tasks can run in parallel, and when specialization improves tool selection or task focus. Outside these situations, the coordination costs typically exceed the benefits."
- **Single agent first.** "Today, multi-agent systems are often applied in situations where a single agent would perform better". "we've seen teams invest months building elaborate multi-agent architectures only to discover that improved prompting on a single agent achieved equivalent results."
- **Token cost.** "In our testing, multi-agent implementations typically use 3-10x more tokens than single-agent approaches for equivalent tasks." Causes given: context duplicated across agents, coordination messages, and summaries for handoffs.
- **Role pipelines fail.** "We've observed teams build elaborate multi-agent systems with separate agents for planning, execution, review, and iteration, only to discover that they suffered from lost context at each handoff and spent more tokens coordinating than executing." And: "In one experiment with agents specialized by software development role (planner, implementer, tester, reviewer), the subagents spent more tokens on coordination than on actual work." No figures are given for either.
- **When context isolation pays.** "Context isolation is most effective when subtasks generate high context volume (more than 1000 tokens) but most of that information is irrelevant to the main task, when the subtask is well-defined with clear criteria for what information to extract, and for lookup or retrieval operations that require filtering before use." In the example, the main agent receives "only the 50-100 tokens it actually needs".
- **Parallelism buys coverage, not speed.** "multi-agent systems often take longer overall than single-agent systems because of the sheer increase in total computation." "The primary benefit of parallelization is thoroughness, not speed." The same article later says independent pieces such as "tests for multiple components" in parallel "can provide substantial speedups", so it is not fully consistent.
- **Specialization signals.** Tool quantity: "An agent with too many tools (often 20+) struggles to select the appropriate one", domain confusion, and new tools degrading existing tasks. Elsewhere: "When an agent has 15-20+ tools" consider the Tool Search Tool first, which "can reduce token usage by up to 85% while improving tool selection accuracy." Example: "A single agent with 40+ tools often struggles to select correctly". Conflicting behavioural modes (empathetic support against a "precise and critical" code reviewer) justify separate system prompts. "Specialization works best when domains are clearly separable and routing decisions are unambiguous." Compaction is "reducing this limitation" on context. "These thresholds will shift as models improve."
- **Context-centric decomposition.** "Dividing by type of work (one agent writes features, another writes tests, a third reviews code) creates constant coordination overhead." "an agent handling a feature should also handle its tests, because it already possesses the necessary context. Work should only be split when context can be truly isolated." Good boundaries: independent research paths, "Separate components with clean interfaces", "Blackbox verification". Bad boundaries: "Sequential phases of the same work. Planning, implementation, and testing of the same feature share too much context"; tightly coupled components; work needing shared state.
- **Verification subagent: works, but may be unneeded with a strong orchestrator.** It is "One multi-agent pattern that consistently works well across domains". But "more capable orchestrator models (like Claude Opus 4.5) are increasingly able to evaluate subagent work directly without a separate verification step. However, verification subagents remain valuable when using less capable orchestrators, when verification requires specialized tools, or when you want to enforce explicit verification checkpoints in your workflow." "The verifier does not need to understand why the artifact was built as it was. It only needs to determine whether the artifact meets the specified criteria." The sample loop retries up to `max_attempts: int = 3`, feeding the verifier's issues back into the requirements.
- **Early victory problem.** "The most significant failure mode for verification subagents is marking outputs as passing without thorough testing." Mitigations: concrete criteria ("Run the full test suite and report all failures"), multiple scenarios and edge cases, "Negative tests. Direct the verifier to attempt inputs that should fail and confirm they do", and explicit wording: "The instruction \"You MUST run the complete test suite before marking as passed\" is essential."
- **Checklist before going multi-agent.** Genuine constraints exist; "Decomposition follows context, not problem type"; "Clear verification points exist where subagents can validate work without requiring full context." "Start with the simplest approach that works, and add complexity only when evidence supports it."

### Against P1 to P14

| MAS rule | Relation | Note |
| --- | --- | --- |
| Three situations; elsewhere coordination costs exceed benefits | Repeats P1 | Same three conditions as Fold. |
| 3-10x tokens for equivalent tasks | New number | The guiding articles give no multi-agent token multiple. |
| Role pipelines (planner, implementer, tester, reviewer) spend more on coordination than work | New evidence for P8 | P8 states context-centric decomposition; MAS gives the failure it came from, in a coding setting. |
| Isolation pays above about 1000 tokens of mostly irrelevant output with clear extraction criteria; return 50-100 tokens | Refines P2 | Gives the threshold that separates P2's verbose reading from Fold's shared-context case. |
| Parallelism buys thoroughness, not speed; often slower overall | New; partly self-contradicted | The guiding articles credit parallel dispatch with speed. |
| 20+ (or 15-20+) tools; Tool Search first, up to 85% fewer tokens; 40+ example | New numbers | Fold's 30-50 is a later, higher threshold for the same signal. |
| Conflicting personas justify separate prompts | Repeats Fold's third condition | Partly supports a separate critical reviewer persona. |
| A feature's owner writes its tests; do not split plan, build and test of one feature | Repeats P8, sharper | Settles the guiding articles' "who edits code" split for one feature: the same agent. |
| Capable orchestrators can verify directly; a verifier is worth it for weaker orchestrators, special tools or enforced checkpoints | New; pulls against generator-verifier as default | P3 holds; the separate agent becomes conditional. |
| Blackbox verifier given criteria only | Repeats P3 | |
| Early victory problem; negative tests; explicit "MUST run the complete test suite" | Repeats P3 and P12, adds negative tests | A2 cites this problem from MAS. P12 is about the worker giving up; this is the verifier passing too early. |
| Retry up to 3 with feedback | Repeats P4 | A code sample, not a stated rule. |

Neither piece addresses P5, P6, P7, P9, P10 or P14 (model tiers, cheap-then-rerun, shared claimable state, written plans across fresh workers). Fold's `cost-optimize` skill lists "effort, and model choice" among levers but gives no rule.

## What the two pieces imply for the open design decisions

All three subsections are **Inference**.

### When a small change should run as one agent

Both pieces set one agent as the default and name three exits: measured context degradation, independent parallel work, or tool and instruction conflicts. A single ticket meets none of them by default. MAS's experiment with a planner, implementer, tester and reviewer, in which coordination outweighed the work, is the closest published evidence to a ticket pipeline, and Fold's single-loop design has the model that writes the plan carry it out. So a small change would run as one agent that plans, edits, writes its tests and runs the checks, with turn and cost budgets and write gates set outside it. Subagents would be used only for reading that returns more than about 1000 tokens of mostly irrelevant material, under a clear extraction brief, returning about 50-100 tokens. A coordinator that does no work itself is the structure both pieces warn against for work that fits one context.

### How a single ticket should be reviewed

The pieces support one review step built on runnable criteria, not several reviewers split by concern. MAS: a strong orchestrator can evaluate work directly, and a separate verifier earns its cost when the orchestrator is weaker, when checks need special tools, or when a checkpoint must be enforced. If a separate verifier is kept, it should be blackbox, given only the artifact and the criteria, told to run the full suite, and told to try inputs that should fail. Separate Standards, Spec and final reviewers are a split by problem type, which both pieces count as a source of lossy handoffs; MAS's point on conflicting personas supports at most one separate critical reviewer. Fold's method decides between these on evidence: about 10 golden tickets, one reviewer removed at a time, each ticket run at least twice, and attention to which tickets flipped, not only to the pass rate.

### How a multi-ticket run should be coordinated

Split by context, not by role: one owner per ticket carries implementation and tests together. Run tickets in parallel only when they are independent or meet at a clean interface. Tickets that chain on each other's output, touch the same data, or always land together go to one owner (Fold's merge test). Expect 3-10x the tokens of a single agent, and treat parallelism as a throughput gain whose wall-clock benefit must be measured, not assumed. Keep the hierarchy flat: Fold's "subagents called as tools" with a shared result schema, checked by the caller against real data, beats chained full handoffs (coordinator to owner to sub-coordinator to worker). Put ordering, preconditions and permissions in tools and the environment, not in prose the coordinator must apply. One owner is responsible for end-to-end quality, and skill rules that served an earlier model are audited and pruned by usage.

## Limits

- Both are first-party vendor articles with no stated method. The 3-10x token figure, the role-pipeline experiment, Fold's "frequently outperformed" and the 2x runtime come with no sample size, task set or variance.
- Fold is about enterprise, customer-facing agents with a user in the loop, not unattended coding pipelines. Its evidence on coding work is indirect.
- MAS's examples date from the Claude Sonnet 4.5 and Opus 4.5 generation; both pieces say the thresholds move as models improve. Fold's 30-50 tools and MAS's 15-20+ already disagree.
- Neither piece measures a review wave, multi-reviewer setups, or model tiering by role, so they cannot settle those questions alone.
- The three design implications above are this reader's inferences from the articles, not their claims.
