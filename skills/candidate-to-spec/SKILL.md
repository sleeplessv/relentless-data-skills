---
name: candidate-to-spec
argument-hint: "[report-path|spec#] [candidate...]"
disable-model-invocation: true
description: "Turn deepening candidates from an architecture review into approved specs and ready-for-agent tickets, with agents answering the design questions."
---

# Candidate to spec

Take **deepening candidates** from an `improve-codebase-architecture` report and produce, for each,
an approved spec and `ready-for-agent` tickets that `implement-feature` can run. Agents answer the
design questions; the user approves one plain-English spec per candidate. The only code this
skill writes is a throwaway prototype under the run directory.

Load `orchestrator-mode` in standing mode for this run and end it in step 5: the main thread
plans, dispatches, and talks to the user; workers read, design, review, and publish. Every worker
brief follows [Briefs](references/workers.md#briefs) and names the `codebase-design` vocabulary
(module, interface, seam, adapter, depth, leverage, locality) and the project's `CONTEXT.md` or
`GLOSSARY.md` terms, and uses both exactly.

## Setup

One setup worker, with the run directory chosen per `orchestrator-mode`. It:

1. Resolves each skill from its installed root and records the path, or `absent`, in
   `<run>/setup.md`. Required: `orchestrator-mode`, `codebase-design`, `to-spec`, `to-tickets`,
   and `gh`. Optional, each with its fallback at the step that uses it: `prototype`,
   `ponytail-review`, `technical-writing`, `unslop`, `domain-modeling`.
2. Records the project's issue-tracker doc and triage-label doc. The tracker is GitHub through
   `gh`. The references write the canonical label names `needs-triage`, `ready-for-agent`,
   and `spec`; where the triage-label doc maps a canonical name to another string, substitute
   that string in every command.
   It lists the repo's labels per [Labels](references/spec-and-tickets.md#labels) and names
   each of the three that is missing.
3. Records whether `docs/architecture-policy.md` exists in the target project.

A missing required dependency stops the run here, with the gap named. A missing label is one
question to the user: create it (the setup worker, resumed, runs the create command), or stop.
Done when `<run>/setup.md` holds a path or `absent` for
every dependency, the label check result, and the policy file's state.

## Workflow

Track the six stages in the plan tool. Each is done when its evidence is in the run directory.

### 0. Load candidates

Input is a report path (`<tmpdir>/architecture-review-<timestamp>.html`) or, on a re-run, the
number of a spec whose comments hold the deferred candidates. One worker writes one
`<run>/candidates/<slug>.md` per card per [Candidate file](references/workers.md#candidate-file).
The slug is the card's `<article>` id, else its title in kebab-case. Picks come from the
arguments, matched against slug or title; with none, take the report's Top recommendation, or
every candidate the spec carries. The worker returns `status: no_candidates` and the reason when
the input is missing, has no cards, or matches no pick; the run stops and reports it.

Then, when `<run>/setup.md` says the policy file is absent, run
[Policy bootstrap](references/policy.md): the main thread asks, the same worker (resumed) writes
the file and records its path in `<run>/setup.md`. Done when every pick has a candidate file and
`<run>/setup.md` records the policy path.

### 1. Plan the order

One planning worker per [Planning](references/workers.md#planning) orders the picks by
dependency, finds prior specs, and splits them into this-run, deferred, and held sets. Show the
user the order, each edge's reason, the deferred set with what blocks it, and each held
candidate's question: reopen the ADR, park it, or drop it. Resume the planner with the answers.
Done when `<run>/plan.md` exists and records an answer for every held candidate. A run whose
every pick is `done`, `in-flight`, or `rejected` reports that and ends.

### 2. Design each candidate

Stages 2 to 4 run per this-run candidate in plan order, each candidate through to its tickets
before the next starts. Stage 2 is the [Design loop](references/workers.md#design-loop):
designer, the alternative wave when the designer asks for it, reviewer, designer revision. Put
each `open_questions` entry to the user as it arrives, in plain English with a recommended
answer, and keep independent work moving. Done when the Decisions table in
`<run>/<slug>/decision-log.md` has every row at `decided`, `contested`, or `open`, and every
`decided` row cites evidence.

### 3. Publish the spec and take the user's decision

The spec worker publishes per [Spec](references/spec-and-tickets.md#spec). Show the user the
checkpoint that section describes, wait, and apply
[User decision](references/spec-and-tickets.md#user-decision). Done when the spec worker's
return shows the spec labelled `ready-for-agent`, or closed with `<run>/<slug>/rejection.md`
holding the reason.

### 4. Break into tickets

Three dispatches per [Tickets](references/spec-and-tickets.md#tickets): the tickets worker
drafts, the reviewer (resumed) answers the quiz, the tickets worker (resumed) applies the answers
once and publishes. A closed spec skips this stage. Done when the tickets worker's return
lists every ticket in `<run>/<slug>/tickets.md` with labels that include `ready-for-agent`.

### 5. Report

Lead with the specs published and their ticket counts. Then list the deferred and held
candidates with what blocks each, the open questions the specs answered with their recommended
answers, the policy file and any ADR this run wrote for the user to commit, and the exact re-run
command per blocking spec: `candidate-to-spec <spec#>`. A parked candidate is re-run from the
report with its slug as a pick. Next steps: run `implement-feature <spec#>` per spec in plan
order, then `ponytail-review` on each feature PR. End standing mode. Done when the report names
every spec, every deferred or held candidate, every file to commit, and the re-run command.

## Capacity and writes

Stages run one after another, so one worker is live at a time, except the alternative wave of
step 2, where the main thread runs up to three alternative workers in parallel and nothing else.
With the root counted, that stays within `orchestrator-mode`'s worker cap and needs no nesting.

Workers write under the run directory and to the tracker. The target repo receives at most two
uncommitted files, each reported for the user to commit: the policy file from the bootstrap and
the ADR the user asks for when rejecting a candidate. Glossary and ADR changes for an approved
spec go in its docs ticket. Prototypes die with the run.
