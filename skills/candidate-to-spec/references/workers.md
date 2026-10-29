# Worker contracts

## Briefs

Every brief follows `orchestrator-mode`'s handoff rules: task with done-when, owned paths, and
permissions already granted (tracker writes for the planning, spec, and tickets workers; label
creation for the setup worker, granted on resume after the user says create; one file in the
target project for the policy and ADR writers); goal; decisions so far with their reasons, and
open questions to flag rather than guess; prior findings quoted word for word; run directory;
skills by path; a return contract. Add the paths in `<run>/setup.md`, the policy file, and the
project's tracker and triage-label docs. Briefs that run `gh` set `export GH_REPO=<owner/repo>`
from `<run>/setup.md`, since workers run from the run directory, not the repo. Every shell
block in these references runs as one `bash` call (`bash -c '…'` or a heredoc to `bash`): the
Bash tool may be zsh, which aborts on an unmatched glob and expands a leading `=`. When `technical-writing` or `unslop` is `absent`, the
brief says "write plainly" in place of the path, and the run report names the gap.

**Vocabulary.** Every brief names the `codebase-design` vocabulary (module, interface,
implementation, seam, adapter, depth, leverage, locality) and the terms of the project's
[glossary](#designer), and the worker uses both exactly.

## Candidate file

`<run>/candidates/<slug>.md` holds, in the card's own words: Title, Files, Dependency category
(the card's tag: `in-process`, `local-substitutable`, `ports & adapters`, `mock`), Problem,
Solution, Wins (the field `improve-codebase-architecture`'s own `SKILL.md` calls Benefits),
Strength, the ADR callout when present, and the before/after diagram source in a fenced block.

A deferred candidate travels as a comment on the spec that blocks it. The comment body is the
heading line `## Deferred candidate: <slug>`, then the file verbatim, then, when the user
answered a hold, a line `hold-answer: reopen ADR <n>` (or `hold-answer: park`), which the
planner reads as the recorded answer on a re-run. On a re-run from a spec number, with `SPEC_N`
that number, the loader reads the spec's comments and writes one candidate file per comment
that starts with that heading:

```bash
set -euo pipefail
gh issue view "$SPEC_N" --json comments --jq '.comments[].body'
```

## Planning

One dispatch per invocation, before any design. Inputs: every `<run>/candidates/<slug>.md`, the
policy file, and the repository.

1. **Draw the edges.** Candidate A precedes B when A's deepened module sits in B's Files, when
   A's seam is one B relies on, or when the two share any file, the shared-file edge taking
   review report order. Independent candidates keep the review report's order: `Strong`, then
   `Worth exploring`, then `Speculative`, ties in review report order.
2. **Find prior specs.** For each pick, and for each candidate that precedes a pick in the
   edges, with `SLUG` its slug, find the spec whose body has the exact line `candidate: <slug>`:

   ```bash
   set -euo pipefail
   : "${SLUG:?}"
   gh issue list --state all --label spec --search "\"candidate: $SLUG\" in:body" \
     --json number,state,stateReason,url,body \
     --jq '[.[] | select(.body | split("\n") | index("candidate: '"$SLUG"'")) | del(.body)]'
   ```

   With `SPEC_N` the matched spec's number, read its state and sub-issues, and its comments
   with the [Candidate file](#candidate-file) command:

   ```bash
   set -euo pipefail
   gh issue view "$SPEC_N" --json state,stateReason,labels,subIssues,closedByPullRequestsReferences
   ```

   Record one state per candidate: `absent` (no match); `reopened` (open, `stateReason`
   `REOPENED`, labelled `needs-triage` and without `ready-for-agent`); `needs-tickets` (open,
   labelled `ready-for-agent`, with no comment starting with `## Breakdown`); `in-flight` (every
   other open spec; one still labelled `needs-triage` is reported with "close and reopen it, then
   re-run with the slug as a pick, to finish it"); `done` (closed `COMPLETED` with
   `closedByPullRequestsReferences` non-empty); `rejected` (closed `NOT_PLANNED` or
   `DUPLICATE`). Two cases are `open_questions` entries,
   skipped until the user answers: a spec closed `COMPLETED` with no PR reference ("treat as
   done?"), and a `needs-tickets` spec whose `subIssues` is non-empty ("finish by hand, or
   re-ticket?"). A `done`, `in-flight`, or `rejected` candidate is reported with its spec URL
   and skipped. On a re-run from a spec number, record that spec's state the same way: it
   precedes every candidate it carries.
3. **Hold.** A candidate whose card carries an ADR callout, or whose Files fall in the policy's
   off-limits areas, is `held`, with the ADR number or the area named. A `hold-answer` line in
   its deferred comment is the recorded answer; otherwise the user answers per candidate:
   **reopen** (the design proceeds with the superseded ADR as a decision in the designer's
   brief, and the spec's docs ticket supersedes it), **park** (it stays `held` and the run report
   carries it), or **drop** (`rejected`, with the reason).
4. **Split the sets.** The this-run set holds every `reopened` and `needs-tickets` spec and
   every candidate outside the held set whose every predecessor is `done`, or sits outside the
   picks with no spec (`absent`). Everything else is deferred, each naming the spec or candidate
   that blocks it. The planner writes each deferred candidate's comment body, per
   [Candidate file](#candidate-file), to `<run>/<blocker slug>/deferred/<slug>.md`, with
   `<blocker slug>` the slug of the nearest this-run or `in-flight` spec on the candidate's
   blocker chain, so every deferred candidate lands under a spec that this run publishes or
   that already exists; the spec worker posts them when it publishes that spec. When that spec
   is `in-flight` from an earlier run, the planner posts the file now, with `DEFERRED` that file
   and `SPEC_N` the spec's number, when no comment on the spec starts with the file's heading
   line:

   ```bash
   set -euo pipefail
   heading=$(head -n 1 "$DEFERRED")
   comments=$(gh issue view "$SPEC_N" --json comments --jq '.comments[].body')
   if ! grep -qxF -- "$heading" <<<"$comments"; then
     gh issue comment "$SPEC_N" --body-file "$DEFERRED"
   fi
   ```

5. **Re-validate on a re-run.** For every remaining candidate, confirm its Files exist and its
   Problem holds on the current tree. A file a predecessor's merged PR moved is re-mapped to its
   successor from that PR's diff. A candidate is `dissolved` only when its Problem no longer
   holds; cite the commit or PR, and drop it from the sets.

Write `<run>/plan.md`: an ordered table of slug, strength, blockers, and status (`this-run`,
`deferred`, `held`, `dissolved`, `done`, `in-flight`, `reopened`, `needs-tickets`, `rejected`),
one line per edge with its reason, and one line per held candidate with its question and, once
the main thread resumes the planner with it, the user's answer. Return `status`, `plan_path`,
`order` (slugs in plan order), `edges` (from, to, reason), `this_run`, `deferred` (slug,
blocker), `held` (slug, ADR number or area, question, and after the resume `answer`),
`open_questions`.

## Design loop

Per candidate, in order: designer; the alternative wave, when the designer returns
`alternatives_needed`; reviewer; designer revision. The designer and the reviewer are different
workers.

### Designer

Inputs: the candidate file, the policy file, the glossary and ADRs, `codebase-design`'s
`SKILL.md`, `DEEPENING.md`, and `DESIGN-IT-TWICE.md` by path, and `to-spec`'s `SKILL.md` by path
for its seam heuristics (step 2: prefer existing seams, use the highest seam, ideally one). Add
`prototype`'s `SKILL.md` path when recorded. For a `reopened` spec, add the spec's comments, with
the rejection reason quoted as a decision in the brief, so the redesign starts past the rejected
design. The **glossary and ADRs** are `GLOSSARY.md` or
`CONTEXT.md` at the repo root, or, when `GLOSSARY-MAP.md` or `CONTEXT-MAP.md` is there, the
context file it assigns the candidate's Files, and that same context's `docs/adr/`.

#### Method: the design tree

The root is the candidate's Solution. Its nodes are: the constraints; where the seam goes; what
sits behind it; the interface (signature, invariants, ordering, error modes, configuration,
performance); the adapters and their dependency category; what each caller changes; which tests
survive, which move to the new interface, and which are new; the migration phases (expand,
switch, contract), named as phases rather than tickets; the glossary terms the deepened module
needs; and the decisions that meet the [ADR test](#adr-test). The tree is done when every node
has a row in the Decisions table.

#### Evidence

Each `decided` row carries one of:

- a code citation (`path:line`) that shows the constraint or the current behaviour;
- a design-it-twice comparison, below;
- a prototype, below;
- a user answer, quoted.

#### Design it twice

When the interface shape is genuinely open, the designer writes the problem framing
(`DESIGN-IT-TWICE.md` step 1) and step 2's technical brief (file paths, coupling details,
dependency category, what sits behind the seam) into the log. It returns `alternatives_needed`
(the brief numbers: 1 and 3 always, and 4 in place of 2 when the dependency category is
`ports & adapters` or `mock`; plus the log section holding the framing) and `technical_brief`.
The main thread dispatches three alternative workers in parallel, each with the framing, the
technical brief, the candidate file, its brief, and the vocabulary; each returns
`DESIGN-IT-TWICE.md`'s five outputs. The main thread resumes the designer with the three outputs
quoted. The designer writes the comparison (depth, locality, seam placement) and its pick, or a
hybrid, into the log as the node's evidence. The spec carries the pick; the designs stay in the
run directory.

#### Prototype

A runnable script or test under `<run>/<slug>/prototype/`, named as a prototype, that answers
one question inside the designer's own dispatch with the project's existing toolchain and runs
with one command. From `prototype`, take only marking, throwaway state, no polish, and surfacing
state; a prototype here may be a test file, overriding its no-tests rule. The question it
settled is the row's evidence. A question whose prototype would need an install or a running
service, or one that only a prototype could settle when `prototype` is `absent`, stays `open`.
Prototypes die with the run.

#### ADR test

Propose an ADR only when the decision is hard to reverse, surprising without context, the result
of a real trade-off, and needed by a future explorer to avoid re-suggesting the same thing.

#### Policy

Taste questions take the policy file's answer. External behaviour stays as the policy file's
Behaviour line says.

#### Open questions

A node is `open`, and the designer keeps working the rest, when it has no evidence, or when the
decision would change behaviour visible to callers outside the repository, contradict an ADR,
add or remove a dependency or infrastructure, or touch files outside the candidate's Files. The
glossary, the ADRs, and the files the project's conventions require per change (such as version
files) are inside scope: they go in the docs ticket or the tickets' acceptance criteria. An ADR
the user reopened in planning enters the brief as a decision; a question that would contradict
any other ADR recommends the answer that keeps it. Write each as one plain paragraph for a
reader who does not know the architecture vocabulary: what is being decided, the recommended
answer, and what happens under each answer.

#### Log and return

Write `<run>/<slug>/decision-log.md` with these sections: Summary (plain English), Decisions (a
table of node, decision, evidence, status), Proposed glossary terms, Proposed ADRs, Test plan,
Open questions. A row's status is one of `decided`, `contested`, or `open`: the designer writes
`decided` and `open`, and the revision adds `contested`. Return `status`, `decision_log_path`,
`alternatives_needed`, `technical_brief`, `open_questions`, `prototypes_built`.

### Reviewer

Briefed as the future maintainer of the result. Inputs: the glossary and ADRs, the policy file,
the test layout (test directories and one representative test file), the decision log, and the
candidate file, or for a `needs-tickets` spec the spec body and its decision-log comment.

Add the **lean checklist** when `ponytail-review` is recorded, quoted from its "Lean" item:
delete, reuse, stdlib or native, yagni, merge, split. Map it onto deep-module rules: one adapter is
a hypothetical seam, so a seam with a single implementation needs a named second adapter, and a test
fake counts only when the test plan uses it; an interface wider than its callers use is shallow.
When `ponytail-review` is `absent`, the brief omits the checklist and the return says so.

The reviewer makes one pass. Each finding names the node, a concrete case ("with this caller or
input, this decision leads to this result"), and the evidence that would resolve it. The reviewer
drops a finding without a case. Return `status` and `findings`; an empty list is a valid return
and the revision dispatch still runs, so the log records that the review found nothing. On the
quiz resume ([Tickets](spec-and-tickets.md#tickets) step 2) the return adds `quiz_answers`
(granularity, blocking edges, merge or split).

### Revision

Resume the designer with the findings quoted verbatim and any user answer that arrived during
the loop, quoted; each answer makes its row `decided` with the quoted answer as evidence. For
each finding it does one of:

- **revise**: change the decision and cite new evidence;
- **reject**: keep the decision, set its status to `contested`, and state both sides and the
  evidence in a Contested decisions section;
- **concede**: it cannot be answered with evidence, so the node becomes `open`.

Done when every finding has one disposition and the log is rewritten in place. Return `status`,
`decision_log_path`, `revised` (one line per revised node: what changed), `contested`,
`open_questions`, `rows_without_evidence` (the count of `decided` rows with an empty evidence
cell).
