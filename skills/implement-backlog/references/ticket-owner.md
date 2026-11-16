# Ticket owner

Read this when a chief of staff dispatches you as the **ticket owner** of one ticket. You take
that ticket from claim to merged PR inside this thread and report once.

## Role

You are the coordinator of a solo `implement-ticket` run. Read `SKILL.md` and `references/`
under the `implement-ticket` root your dispatch names. Wherever they say "the coordinator" or
"the main thread", that is you: you dispatch the workers, reviewers, and verifier that skill
assigns, and they do the work it gives them. Read the repository's agent instructions and the
wiki pages your dispatch points at before the first dispatch.

Before claiming the ticket, confirm you can dispatch a worker. If you cannot, report
`nested dispatch unavailable` and stop.

Four things differ from a solo run:

- **Ticket.** Step 0 is resolved: the dispatch names the ticket number. `RUN_DIR` is the run
  directory, and you name it in every handoff.
- **The user.** Where `implement-ticket` puts something to the user (a stop condition, a
  one-way door's go-ahead, a finding it sends to the user), finish every step that does not
  depend on the answer, then send an [early report](#report). When the chief of staff resumes
  you with the answer, continue from where you stopped.
- **Waiting.** Hold your turn open until every worker you dispatched has reported: your final
  message is your report, and the chief of staff reads nothing else from you.
- **Shared machine.** Other owners run beside you. Work only in your ticket's worktree and
  `RUN_DIR`, use only the resource block your dispatch gives, and split it among your workers.

## Merge

This section replaces "Leave merging to the human" in `implement-ticket`'s Solo finalization
when your dispatch says merging is granted and the door is two-way. A one-way door's PR stays
draft: send the go-ahead question as an early report. Without the grant, end at the ready PR.

`<PR>` is the PR number and `<final_sha>` the full commit that passed closing verification.
Run `gh` from the main checkout.

1. **CI gate.** Read the checks and route by the JSON, since the command exits non-zero on
   failing, pending, and absent checks alike:

   ```bash
   gh pr checks <PR> --json name,bucket
   ```

   Every bucket `pass` or `skipping` opens the gate. A `fail` or `cancel` is a defect, fixed
   as a late fix. A `pending` waits: rerun `gh pr checks <PR> --watch`, then read again. When
   no checks are reported, look for CI before trusting that:

   ```bash
   gh run list --commit <final_sha> --json name,status
   ```

   An empty list and no workflow under `.github/workflows` triggered by `pull_request` means
   the repository has no CI; record "checks: none reported" in the report. A run or such a
   workflow with no check reported is unknown: read again up to five times, then report the
   merge as blocked.
2. **Merge** the commit that was verified, with the repository's merge method (squash unless
   its docs or merged PRs show another):

   ```bash
   gh pr merge <PR> --squash --match-head-commit <final_sha>
   gh pr view <PR> --json state,mergeCommit
   ```

   Route by `state`, whatever the merge's exit code. `MERGED` is done: record
   `mergeCommit.oid` and the ticket's state. `OPEN` after a refusal for a branch that is
   behind or conflicts is drift: bring the PR base in with a merge commit, then repeat
   Publish, Closing verification, and this section on the new head. `OPEN` with exit 0 is a
   merge queue: report it queued.
3. **Denied.** A merge the permission system refuses is reported as `ready, merge denied`
   with `<final_sha>`; the chief of staff merges it.

Leave the worktree and both branches in place and name them in the report.

## Report

One message of at most 12 lines:

- Ticket, PR URL, and outcome: merged with its merge commit, ready, draft, queued, or stopped.
- `final_sha`, the checks line, each review's verdict, and the number of fix rounds.
- The ticket's state, and any follow-up issue filed.
- Decisions you made, one line each, and anything broken outside the ticket.
- Lessons for the wiki: a tooling gap, a misleading doc, a rule the next owner needs.
- The worktree and branches left behind.

An **early report** has the same shape with the outcome `waiting`, and ends with the question
for the user, written so it stands alone, with your recommendation.
