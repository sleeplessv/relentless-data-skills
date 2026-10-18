---
name: candidate-to-spec
argument-hint: "[report-path|spec#] [candidate...]"
disable-model-invocation: true
description: "Turn deepening candidates from an architecture review into approved specs and ready-for-agent tickets, with agents answering the design questions."
---

# Candidate to spec

Take **deepening candidates** from an `improve-codebase-architecture` review report and produce,
for each, an approved spec and `ready-for-agent` tickets that `implement-feature` can run.
Agents answer the design questions; the user approves one plain-English spec per candidate. The
only code this skill writes is a [prototype](references/workers.md#prototype) under the run
directory.

Load `orchestrator-mode` in standing mode for this run: the main thread plans, dispatches, and
talks to the user; workers read, design, review, and publish. Every exit, the early stops in
Setup and steps 0 and 1 included, ends standing mode and reports why. Every worker brief follows
[Briefs](references/workers.md#briefs), its vocabulary rule included.

## Setup

One setup worker, with the run directory chosen per `orchestrator-mode`. It:

1. Resolves each skill from its installed root and records the path, or `absent`, in
   `<run>/setup.md`. Required: `orchestrator-mode`, `codebase-design`, `to-spec`, `to-tickets`,
   and a `gh` on which `gh issue create --help | grep -q -- --parent` exits 0 (2.102 or later,
   with the native sub-issue and blocked-by flags); a `gh` that fails it is a missing required
   dependency. Optional, each with its fallback at the step that uses it: `prototype`,
   `ponytail-review`, `technical-writing`, `unslop`, `domain-modeling`.
2. Records the project's issue-tracker doc and triage-label doc. The tracker is GitHub through
   `gh`. The references write the canonical label names `needs-triage`, `ready-for-agent`,
   and `spec`; where the triage-label doc maps a canonical name to another string, substitute
   that string in every command.
   It lists the repo's labels per [Labels](references/spec-and-tickets.md#labels), compared
   case-insensitively, and names each of the three that is missing.
3. Records whether `docs/architecture-policy.md` exists in the target project.

Return: `status`, `missing_required`, `missing_labels`, `policy` (path or `absent`). A
non-empty `missing_required` stops the run here, with the gap named. Each label in
`missing_labels` is one question to the user: create it (the setup worker, resumed, runs the
create command), or stop. Done when the setup worker's latest return has `missing_required` and
`missing_labels` empty.

## Workflow

Track the six stages in the plan tool.

### 0. Load candidates

Input is a review report path (`<tmpdir>/architecture-review-<timestamp>.html`) or, on a re-run,
the number of a spec whose comments hold the deferred candidates. One worker writes one
`<run>/candidates/<slug>.md` per card per [Candidate file](references/workers.md#candidate-file).
The slug is the card's `<article>` id, else its title in kebab-case. Picks come from the
arguments, matched against slug or title; with none, take the review report's Top
recommendation, or every candidate the spec carries. Return: `status`, `candidates` (slug,
title, strength), `unmatched_picks`. A non-empty `unmatched_picks` is reported and the run
continues with the matched picks. The worker returns `status: no_candidates` and the reason
when the input is missing, has no cards, or matches no pick; the run stops and reports it.

Then, when Setup's `policy` is `absent`, run [Policy bootstrap](references/policy.md): the main
thread asks, the same worker (resumed) writes the file, records its path in `<run>/setup.md`,
and returns `policy_path`. Done when `candidates` holds every matched pick and the policy has a
path, from Setup's `policy` or the bootstrap's `policy_path`.

### 1. Plan the order

One planning worker per [Planning](references/workers.md#planning) orders the picks by
dependency, finds prior specs, and splits them into this-run, deferred, and held sets. Show the
user its return: `order`, each entry of `edges` (from, to, reason), `deferred` (slug, blocker),
`held` (slug, ADR number or area, question), and `open_questions`, and ask per held candidate:
reopen the ADR, park it, or drop it. Resume the planner with the answers, the open questions'
included. A spec the user
reopened after a rejection is re-run from the review report with its slug as a pick; the
planner records it `reopened`. Done when the return names `plan_path` and every `held` entry
carries `answer`. A run whose this-run set is empty goes straight to step 5.

### 2. Design each candidate

Stages 2 to 4 run per this-run candidate in plan order, each candidate through to its tickets
before the next starts. A `reopened` spec goes through them like a this-run candidate, with
the spec worker editing its existing issue; a `needs-tickets` spec runs stage 4 only. Stage 2 is
the [Design loop](references/workers.md#design-loop): designer, the alternative wave when the
designer asks for it, reviewer, designer revision. Put each `open_questions` entry to the user
as it arrives, in plain English with a recommended answer, and keep independent work moving.
Quote
an answer that arrives during the loop to the revision dispatch, or to the spec worker when the
revision has already run; its row becomes `decided` with the quoted answer as evidence. Done
when the revision's return reports `rows_without_evidence: 0`.

### 3. Publish the spec and take the user's decision

The spec worker publishes per [Spec](references/spec-and-tickets.md#spec). Show the user the
checkpoint that section describes, wait, and apply
[User decision](references/spec-and-tickets.md#user-decision). Done when the spec worker's
return shows the spec labelled `ready-for-agent`, or closed with `<run>/<slug>/rejection.md`
holding the reason.

### 4. Break into tickets

Three dispatches per [Tickets](references/spec-and-tickets.md#tickets): the tickets worker
drafts, the reviewer (resumed) answers the quiz, the tickets worker (resumed) applies the answers
once and publishes. A closed spec skips this stage. For a `needs-tickets` spec the log is its
decision-log comment and the quiz goes to a fresh reviewer briefed per
[Reviewer](references/workers.md#reviewer). Done when the tickets worker's return lists every
ticket with labels that include `ready-for-agent` and a parent equal to the spec, or returns
`edges: body`.

### 5. Report

The run report leads with the specs published and their ticket counts. Then list the deferred
and held candidates with what blocks each, the open questions the specs answered with their
recommended answers, the policy file and any ADR this run wrote for the user to commit, and the
exact re-run command per blocking spec, when any: `candidate-to-spec <spec#>`. Tell the user to
keep the review report file: a parked candidate is re-run from it with its slug as a pick. Next
steps: run `implement-feature <spec#>` per spec in plan order, then `ponytail-review` on each
feature PR. Done when the run report names every spec, every deferred or held candidate, every
file to commit, and the re-run command for every blocking spec.

## Capacity and writes

Stages run one after another, so one worker is live at a time, except the alternative wave of
step 2, where the main thread runs up to three alternative workers in parallel and nothing else.

Workers write under the run directory and to the tracker. The target repo receives exactly the
uncommitted files the run report names, at most two, in place of `orchestrator-mode`'s
`docs/research/` save: the policy file from the bootstrap and the ADR the user asks for when
rejecting a candidate. Glossary and ADR changes for an approved spec go in its docs ticket.
