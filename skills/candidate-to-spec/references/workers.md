# Worker contracts

Every brief follows `orchestrator-mode`'s handoff rules: task with done-when, goal, decisions so
far, prior findings quoted, run directory, skills by path, and a return contract. Add the paths
recorded in Setup and the project's policy file to each brief below.

## Planning

One dispatch per invocation, before any design. Inputs: every `<run>/candidates/<slug>.md`, the
policy file, and the repository.

1. **Find prior specs.** Search the tracker for issues whose body carries `candidate: <slug>` for
   each pick. Record each as `done` (closed, feature PR merged), `in-flight` (open spec or open
   feature PR), or `absent`.
2. **Draw the edges.** Candidate A precedes B when A's deepened module sits in B's Files, when A's
   seam is one B relies on, or when the two share any file. Shared files are ordered, never run
   side by side. Independent candidates keep the report's order: `Strong`, then `Worth exploring`,
   then `Speculative`, ties in report order.
3. **Split the sets.** The this-run set holds candidates whose predecessors are all `done` or
   absent from the picks. Everything else is deferred, each naming the spec or candidate that
   blocks it.
4. **Re-validate on a re-run.** For every remaining candidate, confirm its Files still exist and
   its Problem still holds on the current tree. A candidate an earlier refactor dissolved is marked
   `dissolved` with the commit or PR that did it, and leaves the sets.

Write `<run>/plan.md`: an ordered table of slug, strength, blockers, and status (`this-run`,
`deferred`, `dissolved`, `done`, `in-flight`), followed by one line per edge with its reason.
Return `status`, `plan_path`, `this_run`, `deferred`, `open_questions`.

## Design loop

Three dispatches per candidate, in order. The designer and the reviewer are different workers.

### Designer

Inputs: the candidate file, the policy file, `CONTEXT.md` or `GLOSSARY.md`, the ADRs touching the
candidate's Files, and `codebase-design`'s `SKILL.md`, `DEEPENING.md`, and `DESIGN-IT-TWICE.md`
by path. Add `prototype`'s `SKILL.md` path when installed.

**Method: the design tree.** The root is the candidate's Solution. Its branches are the
constraints, where the seam goes, what sits behind it, the interface (signature, invariants,
ordering, error modes, configuration, performance), the adapters and their dependency category,
what each caller changes, which tests survive, which move to the new interface and which are new,
the migration order, glossary terms the deepened module needs, and decisions that meet the ADR test.
Work it frontier by frontier, the way `grilling` would with a human: settle every node whose
prerequisites are settled, then recompute. The tree is done when no node is silently assumed.

**Evidence.** Each decision carries one of:

- a code citation (`path:line`) that shows the constraint or the current behaviour;
- a design-it-twice comparison, run per `DESIGN-IT-TWICE.md` with at most three alternatives,
  only when the interface shape is genuinely open;
- a prototype, following `prototype`'s rules except location: it lives in
  `<run>/<slug>/prototype/`, is small enough to build and run inside the designer's own dispatch,
  and is never committed.

A node with no evidence is an open question, not a decision.

**Policy.** External behaviour does not change unless the policy or the user says otherwise.
Answer taste questions from the policy file before asking anyone.

**Escalate** a node to `open_questions`, and keep working the rest, when the decision would change
behaviour visible to callers outside the repository, contradict an ADR, add or remove a dependency
or infrastructure, or touch files outside the candidate's Files. Write each escalation as one plain
paragraph for a reader who does not know the architecture vocabulary: what is being decided, the
recommended answer, and what happens under each answer.

Write `<run>/<slug>/decision-log.md` with these sections: Summary (plain English), Decisions (a
table of node, decision, evidence, status `decided` or `escalated`), Proposed glossary terms,
Proposed ADRs, Test plan, Open questions. Return `status`, `decision_log_path`, `open_questions`,
`prototypes_built`.

### Reviewer

A fresh worker that did not write the log, briefed as the maintainer who will live with the
result. Inputs: `CONTEXT.md` or `GLOSSARY.md`, the ADRs, the policy file, the test layout (test
directories and one representative test file), the candidate file, and the decision log.

Add the **lean checklist** when `ponytail-review` is installed, quoted from its "Lean" item:
delete, reuse, stdlib or native, yagni, merge, split. Map it onto deep-module rules: one adapter is
a hypothetical seam, so a seam with a single implementation needs a named second adapter, and a test
fake counts only when the test plan uses it; an interface wider than its callers use is shallow.

One pass. Each finding names the node, a concrete case ("with this caller or input, this decision
leads to this result"), and the evidence that would resolve it. A finding without a case is not
reported. Return `status` and `findings`; an empty list is a valid return.

### Revision

Resume the designer with the findings quoted verbatim. For each finding it does one of:

- **revise**: change the decision and cite new evidence;
- **reject**: keep the decision, cite the evidence, and move the pair to a Contested decisions
  section with both sides stated;
- **concede**: it cannot be answered with evidence, so the node becomes an open question.

There is no second review round. Done when every finding has one disposition and the log is
rewritten in place. Return `status`, `decision_log_path`, `contested`, `open_questions`.
