# Worker contracts

## Briefs

Every brief follows `orchestrator-mode`'s handoff rules: task with done-when, owned paths, and
permissions already granted (tracker writes for the planning, spec, and tickets workers; label
creation for the setup worker; one file in the target project for the policy and ADR writers);
goal; decisions
so far; prior findings quoted word for word; run directory; skills by path; a return contract.
Add the paths in `<run>/setup.md`, the policy file, and the project's tracker and triage-label
docs. When `technical-writing` or `unslop` is `absent`, the brief says "write plainly" in place
of the path, and the step-5 report names the gap.

## Candidate file

`<run>/candidates/<slug>.md` holds, in the card's own words: Title, Files, Dependency category
(the card's tag: `in-process`, `local-substitutable`, `ports & adapters`, `mock`), Problem,
Solution, Wins (older reports label them Benefits), Strength, the ADR callout when present, and
the before/after diagram source in a fenced block. On a re-run from a spec number, the worker
reads each comment on that spec headed `## Deferred candidate: <slug>`; the comment body is
the same file verbatim.

## Planning

One dispatch per invocation, before any design. Inputs: every `<run>/candidates/<slug>.md`, the
policy file, and the repository.

1. **Find prior specs.** For each pick, with `SLUG` the candidate slug:

   ```bash
   gh issue list --state all --label spec --search "\"candidate: $SLUG\" in:body" --json number,state,stateReason,url
   ```

   Record `absent` (no match), `in-flight` (open), `done` (closed, `stateReason` `COMPLETED`:
   the feature PR merged and closed it), or `rejected` (closed, `NOT_PLANNED`). A `done`,
   `in-flight`, or `rejected` pick is reported with its spec URL, not re-specified. On a re-run
   from a spec number, with `SPEC_N` that number, record that spec's state the same way from
   `gh issue view "$SPEC_N" --json state,stateReason`: it precedes every candidate it carries.
2. **Draw the edges.** Candidate A precedes B when A's deepened module sits in B's Files, when A's
   seam is one B relies on, or when the two share any file. Shared files are ordered, never run
   side by side. Independent candidates keep the report's order: `Strong`, then `Worth exploring`,
   then `Speculative`, ties in report order.
3. **Hold.** A candidate whose card carries an ADR callout, or whose Files fall in the policy's
   off-limits areas, is `held`, with the ADR number or the area named. The user answers per
   candidate: **reopen** (the design proceeds with the superseded ADR as a decision in the
   designer's brief, and the spec's docs ticket supersedes it), **park** (it stays `held` and the
   report carries it), or **drop** (`rejected`, with the reason).
4. **Split the sets.** The this-run set holds candidates that are not held and whose every
   predecessor is `done`, or sits outside the picks with no spec (`absent`). Everything else is
   deferred, each naming the spec or candidate that blocks it. The planner posts a candidate
   deferred behind an `in-flight` spec from an earlier run on that spec, as the comment
   [Candidate file](#candidate-file) describes, so a re-run from that spec picks it up.
5. **Re-validate on a re-run.** For every remaining candidate, confirm its Files still exist and
   its Problem still holds on the current tree. Mark a candidate that an earlier refactor
   dissolved as `dissolved`, cite the commit or PR that did it, and drop it from the sets.

Write `<run>/plan.md`: an ordered table of slug, strength, blockers, and status (`this-run`,
`deferred`, `held`, `dissolved`, `done`, `in-flight`, `rejected`), one line per edge with its
reason, and one line per held candidate with its question and, once the main thread resumes the
planner with it, the user's answer. Return `status`, `plan_path`, `this_run`, `deferred`, `held`,
`open_questions`.

## Design loop

Per candidate, in order: designer; the alternative wave, when the designer returns
`alternatives_needed`; reviewer; designer revision. The designer and the reviewer are different
workers.

### Designer

Inputs: the candidate file, the policy file, `CONTEXT.md` or `GLOSSARY.md`, the ADRs touching the
candidate's Files, and `codebase-design`'s `SKILL.md`, `DEEPENING.md`, and `DESIGN-IT-TWICE.md`
by path. Add `prototype`'s `SKILL.md` path when recorded.

**Method: the design tree.** The root is the candidate's Solution. Its nodes are: the
constraints; where the seam goes; what sits behind it; the interface (signature, invariants,
ordering, error modes, configuration, performance); the adapters and their dependency category;
what each caller changes; which tests survive, which move to the new interface, and which are
new; the migration phases (expand, switch, contract), named as phases rather than tickets; the
glossary terms the deepened module needs; and the decisions that meet the ADR test. The tree is
done when every node has a row in the Decisions table.

**Evidence.** Each `decided` row carries one of:

- a code citation (`path:line`) that shows the constraint or the current behaviour;
- a design-it-twice comparison, below;
- a prototype, below.

**Design it twice.** When the interface shape is genuinely open, the designer writes the problem
framing (`DESIGN-IT-TWICE.md` step 1) into the log and returns `alternatives_needed` with three
briefs: briefs 1 and 3 always, and brief 4 in place of brief 2 when the dependency category is
`ports & adapters` or `mock`. The main thread dispatches three alternative workers in parallel,
each with the framing, the candidate file, its brief, and the vocabulary; each returns
`DESIGN-IT-TWICE.md`'s five outputs. The main thread resumes the designer with the three outputs
quoted. The designer writes the comparison (depth, locality, seam placement) and its pick, or a
hybrid, into the log as the node's evidence. The user sees the pick in the spec, not the designs.

**Prototype.** A runnable script or test under `<run>/<slug>/prototype/`, named as a prototype,
that answers one question inside the designer's own dispatch with the project's existing
toolchain. From `prototype`'s rules, marking, no persistence, no polish, and surfacing state
apply; its shape, location, and capture rules do not. The question it settled is the row's
evidence. A question whose prototype would need an install or a running service, or one that
only a prototype could settle when `prototype` is `absent`, stays `open`.

**ADR test.** Propose an ADR only when the decision is hard to reverse, surprising without
context, and the result of a real trade-off.

**Policy.** Taste questions take the policy file's answer. External behaviour stays as the policy
file's Behaviour line says.

**Open questions.** A node is `open`, and the designer keeps working the rest, when it has no
evidence, or when the decision would change behaviour visible to callers outside the repository,
contradict an ADR, add or remove a dependency or infrastructure, or touch files outside the
candidate's Files. The glossary, the ADRs, and the files the project's conventions require per
change (such as version files) are inside scope: they go in the docs ticket or the tickets'
acceptance criteria. An ADR the user reopened in planning is a decision in the brief, not a
question; a question that would contradict any other ADR recommends the answer that keeps it.
Write each as one plain paragraph for a reader who does not know the architecture
vocabulary: what is being decided, the recommended answer, and what happens under each answer.

Write `<run>/<slug>/decision-log.md` with these sections: Summary (plain English), Decisions (a
table of node, decision, evidence, status `decided` or `open`), Proposed glossary terms,
Proposed ADRs, Test plan, Open questions. Return `status`, `decision_log_path`,
`alternatives_needed`, `open_questions`, `prototypes_built`.

### Reviewer

A fresh worker that did not write the log, briefed as the future maintainer of the result. Inputs:
`CONTEXT.md` or `GLOSSARY.md`, the ADRs, the policy file, the test layout (test directories and
one representative test file), the candidate file, and the decision log.

Add the **lean checklist** when `ponytail-review` is recorded, quoted from its "Lean" item:
delete, reuse, stdlib or native, yagni, merge, split. Map it onto deep-module rules: one adapter is
a hypothetical seam, so a seam with a single implementation needs a named second adapter, and a test
fake counts only when the test plan uses it; an interface wider than its callers use is shallow.
When `ponytail-review` is `absent`, the brief omits the checklist and the return says so.

The reviewer makes one pass. Each finding names the node, a concrete case ("with this caller or
input, this decision leads to this result"), and the evidence that would resolve it. The reviewer
drops a finding without a case. Return `status` and `findings`; an empty list is a valid return
and the revision dispatch still runs, so the log records that the review found nothing.

### Revision

Resume the designer with the findings quoted verbatim. For each finding it does one of:

- **revise**: change the decision and cite new evidence;
- **reject**: keep the decision, set its status to `contested`, and state both sides and the
  evidence in a Contested decisions section;
- **concede**: it cannot be answered with evidence, so the node becomes `open`.

There is no second review round. Done when every finding has one disposition and the log is
rewritten in place. Return `status`, `decision_log_path`, `revised` (one line per revised node:
what changed), `contested`, `open_questions`.
