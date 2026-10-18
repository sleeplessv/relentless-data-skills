# Spec and tickets

Shell commands below name every variable they use. `SPEC_N` is the spec issue number, `TITLE` the
spec title, and `BODY`, `LOG`, `REASON`, and `BREAKDOWN` are files in `<run>/<slug>/`. Each `gh` command passes on exit code 0 and
stops the step otherwise; the worker records the returned URL in `<run>/<slug>/spec.md`.

## Spec

The spec worker (the designer, resumed, or a fresh worker given the decision log) writes the body
from the decision log. Use the `to-spec` template so `to-tickets` and `implement-feature` see a
familiar shape, with the additions marked **added**. No file paths or code in the body, following
`to-spec`'s rule; a prototype snippet that encodes a decision more precisely than prose may be
inlined, trimmed to the decision.

1. **Title**: `Deepen <module>: <one-line outcome>`, with `<module>` from the glossary.
2. **Markers** (first lines of the body): `candidate: <slug>`, `report: <path>`,
   `policy: docs/architecture-policy.md` or `policy: defaults`. The planning worker reads these
   on a re-run.
3. **What changes for you, what stays the same** (added): plain English for a reader who does not
   know the architecture vocabulary. What callers will notice (by default, nothing), what
   maintainers get, and what the risk is if the refactor is wrong.
4. **Problem Statement**: the friction, from the maintainer's or caller's perspective.
5. **Solution**: the deepened module in one paragraph.
6. **User Stories**: written for callers and maintainers ("As a maintainer of the Order intake
   module, I want ... so that ...").
7. **Implementation Decisions**: the `decided` rows of the decision log.
8. **Testing Decisions**: which tests survive, which move to the new interface, which are new, and
   the behaviour-preservation gate: the existing suite stays green throughout.
9. **Contested decisions** (added): each reviewer finding the designer rejected, both sides, and
   the evidence.
10. **Open questions** (added): escalations the user has not answered, each with its recommended
    answer.
11. **Proposed glossary and ADR changes** (added): terms and decisions that will land through a
    docs ticket.
12. **Out of Scope**: other candidates, behaviour changes, files outside the candidate's Files.
13. **Further Notes**: policy defaults used, prototypes built and discarded, the run date.

Publish, then attach the full decision log:

```bash
gh issue create --title "$TITLE" --label spec --label needs-triage --body-file "$BODY"
gh issue comment "$SPEC_N" --body-file "$LOG"
```

Show the user sections 3, 9, and 10 verbatim, and ask for one of three answers: approve, reject
with a reason, or reject the candidate.

## User decision

- **Approve.** Open questions still unanswered take their recommended answers: edit the body so
  each moves from Open questions into Implementation Decisions, then flip the label:

  ```bash
  gh issue edit "$SPEC_N" --body-file "$BODY" --remove-label needs-triage --add-label ready-for-agent
  ```

  Continue to [Tickets](#tickets).
- **Reject with a reason.** Append the reason to `<run>/<slug>/constraints.md`, resume the designer
  for one redesign pass with it as a constraint, rewrite the body, update the issue with
  `gh issue edit "$SPEC_N" --body-file "$BODY"`, and show the same three sections again. A second
  rejection ends the candidate: record the reason as a spec comment, leave the label at
  `needs-triage`, and report it.
- **Reject the candidate.** The module should not be deepened. Close the spec:

  ```bash
  gh issue close "$SPEC_N" --comment "$(cat "$REASON")"
  ```

  When the reason is hard to reverse, surprising without context, and the result of a real
  trade-off, offer: "Want me to record this as an ADR so future architecture reviews don't
  re-suggest it?" On yes, a worker writes `docs/adr/<next-number>-<slug>.md` in the target
  project in the project's ADR format, uncommitted, and reports the path. On no, nothing is written.

## Tickets

One worker, with the approved spec, the decision log, `<run>/<slug>/`, the tracker doc, and
`to-tickets`'s `SKILL.md` by path (it is user-only, so the path is how a worker loads it).

1. Follow `to-tickets` steps 1 to 3 as written: tracer-bullet vertical slices, blocking edges, and
   expand–contract sequencing when the deepening is a wide refactor.
2. Add one docs ticket for the spec's proposed glossary and ADR changes, blocked by the ticket that
   lands the deepened module, so the terms describe code that exists.
3. For `to-tickets` step 4, send the numbered breakdown to the reviewer worker (resumed) with the
   three quiz questions: granularity, blocking edges, merge or split. Apply its answers once and
   record question and answer in `<run>/<slug>/tickets.md`.
4. Publish per `to-tickets` step 5 and the tracker doc: one issue per ticket in dependency order,
   each a sub-issue of the spec with native blocking edges, labelled `ready-for-agent`.
5. Post the final breakdown (title, blocked by, what it delivers, URL) as a comment on the spec with
   `gh issue comment "$SPEC_N" --body-file "$BREAKDOWN"`.

Return `status`, `tickets` (URL and blockers each), `tickets_path`.
