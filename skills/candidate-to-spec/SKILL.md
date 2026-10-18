---
name: candidate-to-spec
argument-hint: "[report-path] [candidate...]"
disable-model-invocation: true
description: "Turn deepening candidates from an architecture review into approved specs and ready-for-agent tickets, with agents answering the design questions."
---

# Candidate to spec

Take **deepening candidates** from an `improve-codebase-architecture` report and produce, for each,
an approved spec and `ready-for-agent` tickets that `implement-feature` can run. Agents answer the
design questions; the user approves one plain-English spec per candidate. This skill writes no
production code.

Load `orchestrator-mode` in standing mode: the main thread plans, dispatches, and talks to the user;
workers read, design, review, and publish. Every worker brief names the `codebase-design`
vocabulary (module, interface, seam, adapter, depth, leverage, locality) and the project's
`CONTEXT.md` or `GLOSSARY.md` terms, and uses both exactly.

## Setup

Resolve each dependency from its installed root by path and record the paths for worker briefs:

- Required: `gh`, `codebase-design`, `to-tickets`. A missing `codebase-design` stops the run before
  design. A missing `to-tickets` stops after spec approval; report it with the approved spec URLs.
- Optional: `prototype` (without it, a question a prototype would settle stays open);
  `ponytail-review` (without it, the reviewer brief drops the lean checklist and says so);
  `technical-writing` and `unslop` (workers read them by path before authoring prose; without them,
  write plainly and note the gap in the report).
- The project's issue tracker doc and triage-label vocabulary, as `to-tickets` expects. Default to
  GitHub through `gh` with the labels `spec`, `needs-triage`, and `ready-for-agent`.

Choose the run directory per `orchestrator-mode`. When the target project has no
`docs/architecture-policy.md`, follow [Policy bootstrap](references/policy.md) before any design work.

Done when every dependency is a recorded path or a reported gap, the run directory exists, and the
policy file exists or its defaults are recorded.

## Workflow

Copy this checklist into `<run>/handoff.md` and tick each item when its evidence is recorded:

```text
- [ ] 0. Candidates loaded; picks and policy recorded
- [ ] 1. Plan written: order, edges, this-run set, deferred set
- [ ] 2. Per candidate: decision log reviewed and revised
- [ ] 3. Per candidate: spec published at needs-triage; user decision recorded
- [ ] 4. Per candidate: tickets published; breakdown comment posted
- [ ] 5. Report delivered with next steps
```

### 0. Load candidates

Input is the report path (`<tmpdir>/architecture-review-<timestamp>.html`) or, in the session that
produced it, the conversation. A worker reads the report and writes one `<run>/candidates/<slug>.md`
per candidate card: Files, Problem, Solution, Benefits, Strength, and any ADR-conflict callout, in
the card's own words. Picks come from the arguments; with none, take the report's Top recommendation.
Done when every pick has a candidate file.

### 1. Plan the order

Dispatch one planning worker with [Planning](references/workers.md#planning). It orders the picks by
dependency, splits them into a this-run set and a deferred set, and on a re-run re-validates each
candidate against the current tree. Done when `<run>/plan.md` exists and the user has seen the
order, each edge's reason, and the deferred set.

### 2. Design each candidate

For each this-run candidate, in plan order, run the three dispatches of
[Design loop](references/workers.md#design-loop) one after another: designer, reviewer, designer
revision. Put each `open_questions` entry to the user as it arrives, in plain English with a
recommended answer, and keep independent work moving. An ADR conflict holds that candidate's design
until the user reopens the ADR or drops the candidate. Done when `<run>/<slug>/decision-log.md`
holds, for every node of the design tree, a decision with evidence, a contested entry, or an open
question.

### 3. Publish the spec and take the user's decision

One worker writes and publishes the spec per [Spec](references/spec-and-tickets.md#spec): labels
`spec` and `needs-triage`, decision log as a comment. Show the user the "What changes for you"
section, the contested decisions, and the open questions, then wait. Apply
[User decision](references/spec-and-tickets.md#user-decision). Done when the spec carries
`ready-for-agent`, or the candidate is recorded as rejected with its reason.

### 4. Break into tickets

One worker follows [Tickets](references/spec-and-tickets.md#tickets): it reads `to-tickets` by
path, drafts the breakdown, sends the granularity and blocking-edge quiz to the reviewer worker
instead of the user, publishes the tickets as sub-issues of the spec with `ready-for-agent`, and
posts the breakdown as a spec comment. Done when every ticket URL and its blockers are in
`<run>/<slug>/tickets.md`.

### 5. Report

Lead with the specs published and their ticket counts. Then the deferred candidates and what blocks
each, unanswered open questions, and the next steps: run `implement-feature <spec#>` per spec in
plan order, run `ponytail-review` on each feature PR, and re-run this skill from the same report
path once a blocking spec has merged. Done when the user can act from the report alone.

## Capacity and writes

Stages run one after another, so one worker is live at a time; a designer running design-it-twice
may spawn up to three alternatives beneath it, which keeps the tree within `orchestrator-mode`'s
four-worker cap. Workers write only under the run directory and to the tracker. Nothing lands in
the target repo before the spec is approved: glossary and ADR changes travel as a docs ticket, and
prototypes live in `<run>/<slug>/prototype/` and die with the run. The policy file is the one
exception, because the user authors it in the bootstrap interview.
