# Spec and tickets

Shell commands below name every variable they use. `REPO` is the target repository as
`owner/name` (`gh repo view --json nameWithOwner --jq .nameWithOwner`), `SPEC_URL` the created
spec's URL, `SPEC_N` its number, `SLUG` the candidate slug, and `TITLE` the spec title. Files
in `<run>/<slug>/`: `BODY` is `spec-body.md`, `LOG` is `decision-log.public.md` (the decision
log with run-directory paths removed), `REASON` is `rejection.md`, `BREAKDOWN` is `breakdown.md`,
and `DEFERRED` is a deferred candidate's file with its heading line prepended. Every command
passes on exit code 0.
A non-zero exit stops the step, and the worker returns the failing command and its output for the
main thread to report. The worker records each command's result in `<run>/<slug>/spec.md` or
`tickets.md` as it completes, and a step resumed after a failure skips the commands already
recorded, so a retry adds no second spec or ticket.

## Labels

The setup worker lists the repo's labels and compares them with the three the skill applies;
`LABEL` is a missing label and `DESCRIPTION` its meaning from the triage-label doc:

```bash
gh label list --json name --jq '.[].name'
gh label create "$LABEL" --description "$DESCRIPTION"
```

## Spec

The spec worker (the designer, resumed, or a fresh worker given the decision log) reads
`to-spec`'s `SKILL.md` by path for its template and per-section guidance, and writes the body
from the decision log. Two of `to-spec`'s steps are replaced here: its check with the user on
seams, and its `ready-for-agent` label; the [User decision](#user-decision) below does both.
The sections, with this skill's additions marked **added**:

1. **Title**: `Deepen <module>: <one-line outcome>`, with `<module>` the glossary term or, for a
   new module, the term the spec proposes.
2. **Markers** (first lines of the body): `candidate: <slug>`, `report: <file name>` (the
   report's base name, so no local path reaches the tracker), and
   `policy: docs/architecture-policy.md`. The planning worker searches these on a re-run.
3. **What changes for you, what stays the same** (added): plain English for a reader who does not
   know the architecture vocabulary. What callers will notice (by default, nothing), what
   maintainers get, and what the risk is if the refactor is wrong.
4. **Problem Statement**: the friction, from the maintainer's or caller's perspective.
5. **Solution**: the deepened module in one paragraph.
6. **User Stories**: written for callers and maintainers ("As a maintainer of the Order intake
   module, I want ... so that ...").
7. **Implementation Decisions**: the `decided` rows of the decision log. As `to-spec` says, this
   section describes decisions in prose; a prototype snippet trimmed to the decision it encodes
   is the one exception.
8. **Testing Decisions**: which tests survive, which move to the new interface, which are new, and
   the behaviour-preservation gate: the existing suite stays green throughout.
9. **Contested decisions** (added): each `contested` row, both sides, and the evidence.
10. **Open questions** (added): each `open` row the user has not answered, with its recommended
    answer.
11. **Proposed glossary and ADR changes** (added): terms and decisions that the docs ticket will
    add.
12. **Out of Scope**: other candidates, behaviour changes, files outside the candidate's Files.
13. **Further Notes**: the policy answers relied on, prototypes built and discarded, the run date.

Publish, then attach the decision log, then for each deferred candidate this spec blocks,
directly or through other deferred candidates, its candidate file as a comment headed
`## Deferred candidate: <slug>`:

```bash
SPEC_URL=$(gh issue create --title "$TITLE" --label spec --label needs-triage --body-file "$BODY")
SPEC_N=${SPEC_URL##*/}
gh issue comment "$SPEC_N" --body-file "$LOG"
gh issue comment "$SPEC_N" --body-file "$DEFERRED"
```

Return `status`, `spec_url`, `spec_n`, and `checkpoint`: sections 3, 9, and 10 verbatim, then
the revision's `revised` lines, one per line.

**Checkpoint.** Show the user the worker's `checkpoint` as returned, so the changes the review
caused are visible even when nothing is contested or open. Ask for one of three answers: approve,
reject with a reason, or reject the candidate.

## User decision

- **Approve.** Open questions still unanswered take their recommended answers. The spec worker
  (resumed) edits the body so each moves from Open questions into Implementation Decisions, then
  flips the label, and returns the spec's labels and state:

  ```bash
  gh issue edit "$SPEC_N" --body-file "$BODY" --remove-label needs-triage --add-label ready-for-agent
  gh issue view "$SPEC_N" --json labels,state
  ```

  An answer the user gives to an open question after publication goes the same way: resume the
  spec worker with it. An answer that changes a decided row is a rejection with a reason.
  Continue to [Tickets](#tickets).
- **Reject with a reason.** Append the reason to `<run>/<slug>/constraints.md`, resume the
  designer for one redesign pass with it as a constraint, rewrite the body, update the issue with
  `gh issue edit "$SPEC_N" --body-file "$BODY"`, and show the checkpoint again. A second rejection
  ends the candidate: write the reason to `REASON`, close the spec with the command below, and
  report it. The planner then sees it as `rejected`; the user reopens the issue to try again.
- **Reject the candidate.** The module should not be deepened. Write the user's reason to
  `REASON`; the spec worker (resumed) closes the spec and returns its state:

  ```bash
  gh issue close "$SPEC_N" --reason "not planned" --comment "$(cat "$REASON")"
  gh issue view "$SPEC_N" --json labels,state
  ```

  When the reason meets the [ADR test](workers.md#designer), offer: "Want me to record this as
  an ADR so future architecture reviews don't re-suggest it?" On yes, the spec worker (resumed)
  writes `docs/adr/<next-number>-<slug>.md` in the target
  project, uncommitted, in `domain-modeling`'s `ADR-FORMAT.md` when recorded, else in the format
  of the project's existing ADRs, and reports the path. A project with neither has the closing
  comment as its record, and the offer is skipped. On no, nothing is written.

## Tickets

Three dispatches. The tickets worker gets the approved spec, the decision log, `<run>/<slug>/`,
the tracker doc, the triage-label doc, and `to-tickets`'s `SKILL.md` by path (it is user-only, so
the path is how a worker loads it). Where this skill and `to-tickets` differ, this skill wins:
the quiz goes to the reviewer, the answers apply once, and the breakdown comment below is a
write to the parent issue that `to-tickets` would otherwise forbid.

1. **Draft.** The tickets worker follows `to-tickets` steps 1 to 3 as written: tracer-bullet
   vertical slices, blocking edges, and expand–contract sequencing when the deepening is a wide
   refactor. It adds one docs ticket for the spec's proposed glossary and ADR changes, blocked by
   the ticket that delivers the deepened module, so the terms describe code that exists. It
   returns the numbered breakdown (title, blocked by, what it delivers).
2. **Quiz.** The main thread resumes the reviewer with the breakdown and `to-tickets` step 4's
   three questions: granularity, blocking edges, merge or split. The reviewer answers once.
3. **Publish.** The main thread resumes the tickets worker with the answers. It applies them
   once, records question and answer in `<run>/<slug>/tickets.md`, and publishes per
   `to-tickets` step 5: one issue per ticket in dependency order, each a sub-issue of the spec
   with native blocking edges and the `ready-for-agent` label. `TICKET_TITLE` and `TICKET_BODY`
   are the ticket's title and body file; `TICKET_URL`, `TICKET_N`, and `TICKET_ID` are the
   created ticket's URL, number, and database id, recorded in `tickets.md`; `BLOCKER_ID` is a
   blocker's `TICKET_ID`. Both `gh api` calls take database ids, never issue numbers; the
   `blocked_by` call runs once per blocker and is skipped for a ticket with none:

   ```bash
   TICKET_URL=$(gh issue create --title "$TICKET_TITLE" --label ready-for-agent --body-file "$TICKET_BODY")
   TICKET_N=${TICKET_URL##*/}
   TICKET_ID=$(gh api "repos/$REPO/issues/$TICKET_N" --jq .id)
   gh api --method POST "repos/$REPO/issues/$SPEC_N/sub_issues" -F sub_issue_id="$TICKET_ID"
   gh api --method POST "repos/$REPO/issues/$TICKET_N/dependencies/blocked_by" -F issue_id="$BLOCKER_ID"
   gh issue view "$TICKET_N" --json labels
   ```

   When a `gh api` call fails with 404 because the repo has no sub-issues or dependencies, the
   worker uses the tracker doc's fallback instead: a `## Parent` section naming the spec and a
   `Blocked by: #<n>` line at the top of the ticket body, which `implement-feature` reads. For
   the ticket already created it prepends those lines to `TICKET_BODY` and runs
   `gh issue edit "$TICKET_N" --body-file "$TICKET_BODY"`; later tickets carry them from the
   start. Then it posts the final breakdown (title, blocked by, what it delivers, URL) on the spec:

   ```bash
   gh issue comment "$SPEC_N" --body-file "$BREAKDOWN"
   ```

Return `status`, `tickets` (URL, blockers, and labels each), `tickets_path`.
