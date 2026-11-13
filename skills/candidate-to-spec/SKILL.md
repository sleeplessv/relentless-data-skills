---
name: candidate-to-spec
argument-hint: "[report-path|spec#] [candidate...] [instruction]"
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
[Briefs](references/workers.md#briefs), its vocabulary rule included. A resume this skill names
stands in place of `orchestrator-mode`'s one-resume limit, because each worker keeps its state
in run-directory files; a worker the harness cannot resume is replaced by a fresh one briefed
with those files.

## Setup

One setup worker, with the run directory chosen per `orchestrator-mode`. It:

1. Resolves each skill from its installed root and records the path, or `absent`, in
   `<run>/setup.md`. Required: `orchestrator-mode`, `codebase-design`, `to-spec`, `to-tickets`,
   and a `gh` on which `gh issue create --help | grep -q -- --parent` exits 0 (2.102 or later,
   with the native sub-issue and blocked-by flags); a `gh` that fails it is a missing required
   dependency. Optional, each with its fallback at the step that uses it: `prototype`,
   `ponytail-review`, `technical-writing`, `unslop`, `domain-modeling`.
2. Records the repository root, the tracker repo as `owner/repo`
   (`gh repo view --json nameWithOwner`), and the project's issue-tracker doc and triage-label
   doc, each a path or `absent`. The tracker is GitHub through `gh`: `gh issue list --limit 1`
   run from the repository root exits 0, and a failure is a missing required dependency. The
   references write the canonical label names `needs-triage`, `ready-for-agent`, and `spec`;
   where the triage-label doc maps a canonical name to another string, substitute that string
   in every command. It lists the repo's labels per
   [Labels](references/spec-and-tickets.md#labels), compared case-insensitively, and names each
   of the three that is missing.
3. Records whether `docs/architecture-policy.md` exists in the target project.

Return: `status`, `missing_required`, `missing_labels`, `policy` (path or `absent`). A
non-empty `missing_required` stops the run here, with the gap named. A non-empty
`missing_labels` is one question to the user: create them (the setup worker, resumed, runs the
create command per label), or stop. A create the harness blocks follows
[Blocked writes](references/workers.md#blocked-writes). Done when the setup worker's latest return has
`missing_required` and `missing_labels` empty.

## Workflow

Track the six stages in the harness's plan or task tool.

### 0. Load candidates

One worker gets the arguments word for word, and the path of a review report this conversation
produced, and resolves them per [Arguments](references/workers.md#arguments): the input (a
review report, or the number of a spec whose comments hold deferred candidates), the picks, and
an instruction. It writes one `<run>/candidates/<slug>.md` per card per
[Candidate file](references/workers.md#candidate-file). Return: `status`, `report_path`, `candidates` (slug, title, strength), `unmatched_picks`,
`instruction`. Tell the user which review report the loader took. A non-empty
`unmatched_picks` is reported and the run continues with the matched picks. The worker returns
`status: no_candidates` and the reason when the input is missing, has no cards, or matches no
pick; the run stops and reports it. Quote an `instruction` word for word in every brief it
bears on; where it would override a rule of this skill, name the rule and confirm the reading
with the user before step 2.

Then, when Setup's `policy` is `absent`, run [Policy bootstrap](references/policy.md) once: the
main thread asks, the same worker (resumed) writes the file, records its path in
`<run>/setup.md`, and returns `policy_path`. Done when `candidates` holds every matched pick and
the policy has a path, from Setup's `policy` or the bootstrap's `policy_path`.

### 1. Plan the order

One planning worker per [Planning](references/workers.md#planning) orders the picks by
dependency, finds prior specs, and splits them into this-run, deferred, and held sets. Show the
user its return: `order`, each entry of `edges` (from, to, reason), `stacked` (slug, on),
`deferred` (slug, blocker), `held` (slug, ADR number or area, question), and `open_questions`.
The order and the split are shown as decided; the questions here are the planner's
`open_questions` and, per held candidate: reopen the ADR, park it, or drop it. Resume the
planner with the answers. A spec the user reopened after a rejection is re-run from the review
report with its slug as a pick; the planner records it `reopened`. Done when the return names
`plan_path` and every `held` entry carries `answer`. A run whose this-run set is empty goes
straight to step 5.

### 2. Design each candidate

Stages 2 to 4 run per this-run candidate in plan order, each candidate through to its tickets
before the next starts, so a stacked candidate is designed against its predecessor's approved
spec. A `reopened` spec goes through them like a this-run candidate, with the spec worker
editing its existing issue; a `needs-tickets` spec runs stage 4 only. Stage 2 is the
[Design loop](references/workers.md#design-loop): designer, the alternative wave when the
designer asks for it, reviewer, designer revision. Put each `open_questions` entry to the user
as it arrives, in plain English with a recommended answer, and keep independent work moving.
Once the user has said to decide without asking, scope questions stay `open` with their
recommended answers, which the checkpoint shows and approval applies; behaviour, ADR, and
dependency questions are still asked. Quote an answer that arrives during the loop to the
revision dispatch, or to the spec worker when the revision has already run; its row becomes
`decided` with the quoted answer as evidence. A [verdict](references/workers.md#verdict) other
than `proceed` is always asked, and the loop waits for the answer. Done when the revision's
return reports `rows_without_evidence: 0`, or the candidate is dropped and skips stages 3
and 4.

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
ticket with its triage label and a parent equal to the spec, or returns `edges: body`, or the
stage ended on a [blocked write](references/workers.md#blocked-writes).

### 5. Report

The run report leads with the specs published, their ticket counts, and the order to implement
them in. Then list: the tickets left for a human; the deferred, held, parked, and dropped
candidates with what blocks each or why; the open questions the specs answered with their
recommended answers; every edit made to a spec after its approval; every tracker write still
blocked, with its command; the policy file and any ADR this run wrote for the user to commit;
and the exact re-run command per blocking spec, when any: `candidate-to-spec <spec#>`. Give the review report's path and tell the
user to copy it somewhere durable when it sits in a temp or session directory: a parked
candidate is re-run from it with its slug as a pick. Next steps: run `implement-feature <spec#>`
per spec in plan order, then `ponytail-review` on each feature PR. Done when the run report
names every spec, every candidate left without one, every blocked write, every file to commit,
and the re-run command for every blocking spec.

## Capacity and writes

Stages run one after another and each dispatch follows the previous worker's return, so one
worker is live at a time, except the alternative wave of step 2, where the main thread runs up
to three alternative workers in parallel and nothing else.

Workers write under the run directory and to the tracker. The target repo receives exactly the
uncommitted files the run report names, at most two, in place of `orchestrator-mode`'s
`docs/research/` save: the policy file from the bootstrap and the ADR the user asks for when
rejecting a candidate. Glossary and ADR changes for an approved spec go in its tickets. A
tracker write the harness blocks follows [Blocked writes](references/workers.md#blocked-writes).
