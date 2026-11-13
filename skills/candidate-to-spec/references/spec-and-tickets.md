# Spec and tickets

`RUN` is the run directory, `SPEC_URL` the spec's URL, `SPEC_N` its number (assigned before the
publish block only for a spec the planner recorded as `reopened`), and `TITLE` the spec title.
Files in `<run>/<slug>/`: `BODY` is `spec-body.md`, `LOG` is `decision-log.public.md` (the decision
log with run-directory paths removed, its first line `## Decision log`), `REASON` is
`rejection.md`, `BREAKDOWN` is `breakdown.md`,
starting with the line `## Breakdown`, and `DEFERRED_DIR` is `deferred/`, one file per deferred
candidate this spec blocks, directly or through other deferred candidates, each a deferred
comment body per [Candidate file](workers.md#candidate-file). `DEFERRED` is the file the publish
loop is on. Every path variable holds an absolute path. Ticket variables are defined under
[Tickets](#tickets).

The worker runs each block per [Shell](workers.md#briefs); `set -euo pipefail` stops the call at
the first failing command, and the worker returns that command and its output for the main
thread to report. After each command exits, the worker records its exit status and result in
`<run>/<slug>/spec.md` or `tickets.md`, keyed by step, item (ticket or deferred file), and
command; a step resumed after a failure skips the items recorded as succeeded, so a retry adds
no second spec, ticket, or comment. A write the harness blocks goes back to the main thread per
[Blocked writes](workers.md#blocked-writes).

## Labels

The setup worker lists the repo's labels and compares them, case-insensitively, with the three the
skill applies:

```bash
gh label list --limit 1000 --json name --jq '.[].name'
```

`LABEL` is a missing label and `DESCRIPTION` its meaning: `needs-triage` and
`ready-for-agent` take theirs from the triage-label doc, or, in a project without one,
"Maintainer needs to evaluate this issue" and "Fully specified, ready for an agent"; `spec` is
"Spec document, broken into tickets before implementation". The setup worker, resumed after the
user's yes, creates each missing label:

```bash
gh label create "$LABEL" --description "$DESCRIPTION"
```

## Spec

The spec worker (the designer, resumed, or a fresh worker given the decision log) reads
`to-spec`'s `SKILL.md` by path for its template and per-section guidance, and writes the body
from the decision log. Two of `to-spec`'s steps are replaced here: its check with the user on
seams, and its `ready-for-agent` label; the [User decision](#user-decision) below does both.
The sections, with this skill's additions marked **added**:

1. **Title**: `Deepen <module>: <one-line outcome>`, with `<module>` the glossary term or, for a
   new module, the term the spec proposes. After a `smaller` verdict that adds no module:
   `Tidy <area>: <one-line outcome>`.
2. **Markers** (first lines of the body): `candidate: <slug>`, `report: <file name>` (the
   report's base name, so no local path reaches the tracker),
   `policy: docs/architecture-policy.md` (or `policy: defaults` when the user declined a policy
   file), and one `after: #<n>` per spec the candidate is stacked on or the designer returned
   in `depends_on`. The planning worker searches these on a re-run.
3. **What changes for you, what stays the same** (added): plain English, as
   [Open questions](workers.md#open-questions) defines it. What callers will notice (by default,
   nothing), what maintainers get, and what the risk is if the refactor is wrong. A spec with
   `after:` markers says it assumes those specs land first.
4. **Problem Statement**: the friction, from the maintainer's or caller's perspective.
5. **Solution**: the deepened module in one paragraph.
6. **User Stories**: written for callers and maintainers ("As a maintainer of the Order intake
   module, I want ... so that ..."), one per need and ten at most, in place of `to-spec`'s
   long list; a story that restates an implementation decision is cut.
7. **Implementation Decisions**: each `decided` row of the decision log as a prose decision. The
   evidence stays in the log, which the comment below carries, so no path enters the section. A
   prototype snippet of at most twenty lines, trimmed to the decision it encodes, is the one
   exception to prose.
8. **Testing Decisions**: which tests survive, which move to the new interface, which are new, and
   the behaviour gate and baseline failures as the log's Test plan states them, per
   [Baseline](workers.md#baseline). Tests
   on shallow modules that the deepened interface's tests replace are deleted in the contract
   phase and listed here.
9. **Contested decisions** (added): each `contested` row, both sides, and the evidence, in the
   same plain English as section 3.
10. **Open questions** (added): each `open` row the user has not answered, with its recommended
    answer.
11. **Proposed glossary and ADR changes** (added): terms and decisions that the tickets will
    add, or "None".
12. **Out of Scope**: other candidates, behaviour changes, files outside the candidate's scope.
13. **Further Notes**: the policy answers relied on, prototypes built and discarded, the run date.

Publish (a `reopened` spec is edited in place), then attach the decision log, then each deferred
candidate's file as its own comment. The grep keeps the run directory out of the tracker:

```bash
set -euo pipefail
if grep -qF "$RUN" "$LOG"; then echo "run directory path in $LOG" >&2; exit 1; fi
if [ -n "${SPEC_N:-}" ]; then
  gh issue edit "$SPEC_N" --body-file "$BODY" --add-label needs-triage
  SPEC_URL=$(gh issue view "$SPEC_N" --json url --jq .url)
else
  SPEC_URL=$(gh issue create --title "$TITLE" --label spec --label needs-triage --body-file "$BODY")
  SPEC_N=${SPEC_URL##*/}
fi
case $SPEC_N in ''|*[!0-9]*) echo "bad issue url: $SPEC_URL" >&2; exit 1;; esac
gh issue comment "$SPEC_N" --body-file "$LOG"
for DEFERRED in "$DEFERRED_DIR"/*.md; do
  [ -e "$DEFERRED" ] || continue
  gh issue comment "$SPEC_N" --body-file "$DEFERRED"
done
```

Return `status`, `spec_url`, `spec_n`, and `checkpoint`: sections 3, 9, and 10 verbatim, then
the revision's `revised` lines, one per line, then the spec URL.

**Checkpoint.** Show the user the worker's `checkpoint` as returned, so the changes the review
caused are visible even when nothing is contested or open. Ask with the harness's question tool
when it has one, so a background session surfaces the question, for one of three answers:
approve, reject with a reason, or reject the candidate.

## User decision

- **Approve.** Open questions still unanswered take their recommended answers. The spec worker
  (resumed) edits the body so each moves from Open questions into Implementation Decisions and
  marks the same rows `decided` in the log. When a row changed, it first runs the update block
  under Reject with a reason, so the tracker holds the current log. Then it flips the label and
  returns the spec's labels and state:

  ```bash
  set -euo pipefail
  gh issue edit "$SPEC_N" --body-file "$BODY" --remove-label needs-triage --add-label ready-for-agent
  gh issue view "$SPEC_N" --json labels,state
  ```

  An answer the user gives to an open question after publication goes the same way: resume the
  spec worker with it. An answer that changes a decided row is a rejection with a reason.
  Continue to [Tickets](#tickets).
- **Reject with a reason.** The spec worker, resumed with the user's reason, appends it to
  `<run>/<slug>/constraints.md`. The main thread resumes the designer for one redesign pass with
  the constraint; it returns `revised` lines. The spec worker, resumed, rewrites the body and the
  public log, updates the issue, and returns `checkpoint` built as above from the redesign's
  `revised` lines, for a second checkpoint:

  ```bash
  set -euo pipefail
  if grep -qF "$RUN" "$LOG"; then echo "run directory path in $LOG" >&2; exit 1; fi
  gh issue edit "$SPEC_N" --body-file "$BODY"
  gh issue comment "$SPEC_N" --body-file "$LOG"
  ```

  A second rejection ends the candidate: write the reason to `REASON`, run the close block below,
  and report it. The planner then sees the spec as `rejected`; the user reopens the issue and
  re-runs from the review report with the slug as a pick; the planner records it as `reopened`
  and the spec worker edits it in place.
- **Reject the candidate.** The module should not be deepened. Write the user's reason to
  `REASON`; the spec worker (resumed) posts it, closes the spec, and returns its state:

  ```bash
  set -euo pipefail
  [ -s "$REASON" ] || { echo "empty reason: $REASON" >&2; exit 1; }
  gh issue comment "$SPEC_N" --body-file "$REASON"
  gh issue close "$SPEC_N" --reason "not planned"
  gh issue view "$SPEC_N" --json labels,state
  ```

  When the reason meets the [ADR test](workers.md#adr-test), offer: "Want me to record this as
  an ADR so future architecture reviews don't re-suggest it?" On yes, the spec worker (resumed)
  writes `<next-number>-<slug>.md`, uncommitted, in the `docs/adr/` that the glossary-and-ADRs
  definition in [Designer](workers.md#designer) assigns the candidate, in `domain-modeling`'s
  `ADR-FORMAT.md` when recorded, else in the format of the project's existing ADRs, and reports
  the path. A project with neither has the closing comment as its record, and the offer is
  skipped. On no, nothing is written.
- **Change after approval.** A change the user asks for once the spec is `ready-for-agent` goes
  to the spec worker (resumed): it edits the body, adds a line under the log's heading saying
  what changed and why, and runs the update block under Reject with a reason, which posts that
  log. A change that reaches a published ticket is listed in the run report for the user to
  apply. The run report lists each edit.

## Tickets

Three dispatches. The tickets worker gets the approved spec, the decision log, `<run>/<slug>/`,
the tracker doc, the triage-label doc, and `to-tickets`'s `SKILL.md` by path (it is user-only, so
the path is how a worker loads it). Where this skill and `to-tickets` differ, this skill wins:
the quiz goes to the reviewer, the answers apply once, and the breakdown comment below is a
write to the parent issue that `to-tickets` would otherwise forbid. For a `needs-tickets` spec
the decision log is the spec's last comment starting `## Decision log` (on a spec published
before that heading, the comment holding the Decisions table), `<run>/<slug>/` is created fresh,
and the quiz goes to a fresh reviewer briefed per [Reviewer](workers.md#reviewer) with the spec
and that comment.

1. **Draft.** The tickets worker's sources are the spec body and the decision-log comment;
   comments headed `## Deferred candidate:` belong to other candidates and get no tickets. It
   follows `to-tickets` steps 1 to 3 as written: tracer-bullet vertical slices, blocking edges,
   and expand–contract sequencing when the deepening is a wide refactor.
   `to-tickets`' rule that tickets name no file paths applies; a per-change file, per
   [Open questions](workers.md#open-questions), is stated as behaviour ("the version record
   names this change"). When the spec proposes
   glossary or ADR changes, it adds one docs ticket for them, blocked by the ticket that
   delivers the deepened module, so the terms describe code that exists; the quiz may merge it
   into that ticket. A check that only verifies the other tickets is an acceptance criterion of
   the last one. For a spec with `after:` markers, each ticket with no blocker inside its own
   spec is blocked by the last ticket of every `after:` spec, read from that spec's
   `## Breakdown` comment: a **cross-spec blocker**, so `implement-feature` stops on a
   predecessor that has not merged. A ticket only a human can do (access an agent lacks, a
   manual check in a live system) is marked human-only, with the reason in its body. It returns
   the numbered breakdown (title, blocked by, what it delivers, human-only or not).
2. **Quiz.** The main thread resumes the reviewer with the breakdown as drafted and
   `to-tickets` step 4's three questions, and nothing else: granularity, blocking edges, merge
   or split. The reviewer answers once.
3. **Publish.** The main thread resumes the tickets worker with the answers. It applies them
   once, records question and answer in `<run>/<slug>/tickets.md`, and publishes per
   `to-tickets` step 5: one issue per ticket in dependency order, each a sub-issue of the spec
   with native blocking edges and a triage label. `TICKET_TITLE` and `TICKET_BODY`
   are the ticket's title and body file; `TICKET_LABEL` is `ready-for-agent`, or `needs-triage`
   for a human-only ticket, the label `implement-feature` stops on; `TICKET_URL`
   and `TICKET_N` are the created ticket's URL
   and number, recorded in `tickets.md`; `BLOCKED_BY` is the comma-separated numbers of the
   tickets that block this one, cross-spec blockers included, empty for a ticket with none;
   `EDGES` is `native` (the default)
   or `body`. The ticket is created first and its edges added by edit, so a failed edge leaves
   one ticket to fix rather than a retry to duplicate:

   ```bash
   set -euo pipefail
   case $EDGES in native|body) ;; *) echo "EDGES is native or body: $EDGES" >&2; exit 1 ;; esac
   TICKET_URL=$(gh issue create --title "$TICKET_TITLE" --label "$TICKET_LABEL" --body-file "$TICKET_BODY")
   TICKET_N=${TICKET_URL##*/}
   case $TICKET_N in ''|*[!0-9]*) echo "bad issue url: $TICKET_URL" >&2; exit 1;; esac
   if [ "$EDGES" = native ] && [ -n "$BLOCKED_BY" ]; then
     gh issue edit "$TICKET_N" --parent "$SPEC_N" --add-blocked-by "$BLOCKED_BY"
   elif [ "$EDGES" = native ]; then
     gh issue edit "$TICKET_N" --parent "$SPEC_N"
   fi
   gh issue view "$TICKET_N" --json labels,parent,blockedBy
   ```

   `TICKET_BODY` keeps `to-tickets`' template sections `## Parent` (naming the spec) and
   `## Blocked by` (one `#<n>` per blocker): they are the edges `implement-feature` reads when
   the native ones are missing. When the edge edit fails, the worker runs
   `gh issue edit "$TICKET_N" --parent "$SPEC_N"` once on its own, then the view line: a
   repository without issue dependencies keeps the parent and the body carries the blockers.
   When that edit fails too, the repository has no sub-issues either (older GitHub Enterprise):
   the worker records `edges: body` in `tickets.md`, runs the view line for the ticket it just
   created, and runs the block with `EDGES` as `body` for every later ticket. Then it posts the
   final breakdown (title, blocked by, what it delivers, URL) on the spec:

   ```bash
   gh issue comment "$SPEC_N" --body-file "$BREAKDOWN"
   ```

Return `status`, `tickets` (URL, parent, blockers, and label each), `edges` (`native` or
`body`), `tickets_path`.
