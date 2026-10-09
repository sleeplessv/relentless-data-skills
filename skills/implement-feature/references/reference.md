# Implement feature reference

Pass absolute paths and the needed section to each worker. Full ticket bodies, command logs,
and decisions stay in artifacts; returns contain compact outcomes and an index.

## Work-set resolution

Resolve the repository, default branch, spec, and explicit ticket arguments using `gh` and git.
For spec-only input, set `completion_mode: whole_spec` and collect its open tickets. For explicit
tickets, set `completion_mode: selected_tickets`, keep that list authoritative, and resolve any
shared parent as context. Reject conflicting parent specs with concrete evidence.
Skip closed tickets by name; closure alone does not prove dependency implementation is present.

Paginate every list used to claim complete coverage. The REST issues endpoint includes PRs;
exclude entries with `pull_request`. For body links, inspect an anchored `## Parent` section or
`Part of #N` line, excluding fenced examples. Union these with native sub-issues, deduplicating
open tickets by number. Use `gh api --paginate` for sub-issues and dependency endpoints as well.
Distinguish API errors and unsupported endpoints from successful empty lists. Incomplete lookup
coverage cannot prove the spec is complete.

For each selected ticket, read body, comments, labels, assignees, and native blocked-by edges.
Union native edges with anchored `Blocked by` or `Depends on` declarations and lists inside
those sections. Ordinary issue mentions and parent-child relationships are not blocking edges.
Confirm concrete acceptance criteria and ticket rather than spec classification. Check ownership
before any authorized claim. An assignment to the authenticated actor is advisory and does not
mean an implementer is active. Another active attempt in the run record or an assignment to
someone else requires reconciliation. `needs-info`, `needs-triage`, or `wontfix` needs resolution;
a WIP branch alone does not prove agent-authored triage. An explicit current user instruction can
resolve a prior agent stop. Track which lifecycle changes this run actually owns.

Record pre-existing PRs in the ticket snapshots and evaluate current acceptance criteria.

Build the graph and detect cycles. An unresolved open blocker outside the selected set requires
a dependency decision, not expansion of scope. Check that purportedly satisfied blockers are
present in the integration base. Discover integration and WIP branches from local and remote
refs using the configured and legacy naming conventions. Matches only identify candidates;
resolve multiple candidates through recorded task identity and commits, never arbitrary order.

On resume, comments and commit subjects are leads. Verify recorded integration SHAs are reachable
and inspect intervening reverts or changed behavior. Classify a ticket as satisfied only with
criterion evidence on the current tip. Preserve original baseline and decisions; do not infer
completion or safe deletion from a historical "merged into" comment.

For whole-spec runs, map every spec requirement to ticket criteria or current implementation
evidence. Record missing, contradictory, or ambiguous coverage in `scope.md`. Reconcile a missing
requirement through a ticket or explicit scope decision before assigning its implementation.
Continue independent selected work where safe, but unresolved gaps block readiness and spec
closure. An explicit list remains authoritative even when its parent spec has uncovered work.

Setup returns `completion_mode`, requirement coverage and gaps, proposed `work_set`,
`skipped_closed`, `spec_open_tickets`, coverage completeness, `graph`, eligibility evidence,
`resume_state`, integration candidate and default branch, plus
snapshot paths and any specific gate. The coordinator announces this before tree preparation.

## Tree preparation

Read project conventions and discover install, lint/type-check, test, and run commands from
repo instructions, manifests, and CI. Record missing commands explicitly and allocate external
resources for parallel checks. Use configured execution permissions.

Preserve unrelated dirty work. Use a separate permitted integration checkout if the user's
checkout cannot safely switch. Pin the initial default-branch commit as `original_base_sha`,
create the integration branch from it, and record the explicit PR base. On resume, keep the
existing branch identity and resolve local/remote divergence before fast-forwarding or pushing.
Do not overwrite divergent history or user work.

Run baseline checks on `original_base_sha` before editing. On resume, reuse that baseline and
record current failures separately. If the record is missing, reconstruct the original base
from reliable branch/PR history and test it in an isolated checkout. If it cannot be established,
mark it unknown; do not accept existing integration failures as baseline exemptions.

Keep a durable run directory outside tracked product files, in a permitted location. Reuse it
on resume, updating snapshots while retaining earlier versions needed to explain changes:

- `spec.md`, when a spec exists, holds its requirements; `tickets/<N>.md` holds each body and criteria.
  Keep these canonical snapshots separate from the review input.
- `scope.md` is the composite originating spec for integration review. Record the completion mode,
  selected tickets, source provenance and snapshot paths, spec coverage, gaps, and scope decisions.
  Copy every enforceable obligation for that mode into a requirements section. Put parent-spec or
  unselected requirements that provide context in a separate context-only section.
- `handoff.md` holds command/resource setup, original baseline, current verified integration tip,
  branch identities, decision log, failures, and unresolved questions. Append decisions.
- A run record tracks exact owned worktrees/branches, initial and current SHAs, claim ownership,
  integration evidence per ticket, artifact paths, and push results. Store the feature PR identity,
  draft status, and last published head. Report the run record's absolute path.
- For each ticket attempt, record the worker ID, branch, start-comment URL, stop-comment URL,
  outcome, immutable dispatch SHA, prerequisite evidence, and state: ready, running, completed,
  integrated, satisfied, failed, or blocked. `satisfied` is terminal for a validated
  `already_satisfied` outcome and records the current integration tested SHA plus criterion and
  runtime evidence. It does not claim that a merge occurred. Distinguish worker completion from
  verified integration.
  Record a posting failure and the saved comment body path when a URL is unavailable.
  The tracker worker follows implement-ticket's Ticket lifecycle comments. Check these records
  before dispatch and after each worker stops. Reconcile uncertain posts against GitHub before retrying.

Use environment branch conventions, with `spec-<N>-<slug>` or a descriptive integration slug.
Recognize prior `feat/spec-*`, `feat/prd-*`, `feat/ticket-*`, and `feat/issue-*` names on resume.
Create native or manual ticket worktrees from each dispatch SHA in writable locations. Record creation
ownership and initial branch names rather than later guessing by patterns. If isolation cannot
be established, report the blocker. Return `integration_branch`,
`integration_tip`, `original_base_sha`, original failures, `pr_base`, and all handoff/run-record paths.

## Frontier scheduling

Dispatch from the verified, preserved integration tip. Record the assigned `base_sha`, ticket
snapshot, expected worktree and branch, and evidence that each blocker is satisfied at that SHA.
Pass these with `base_branch`, `original_base_sha`, original failures, resource allocation,
handoff and run-record paths, `open_pr: false`, and any evidence-backed `resume_branch`.
Include the start-comment URL or its recorded posting failure. Pass source-linked exploration
notes by path when available. Keep notes in the shared run directory outside tracked product files.

On a worker completion, prioritize integration when it can release dependants. Recompute the
frontier after each verified, preserved integration, without waiting for unrelated workers.
A worker still running keeps its dispatch SHA when the integration branch advances. Rebase or
redispatch only when dependency changes or integration evidence require it, preserving prior WIP.

Serialize writers on the integration checkout and allocate separate ports, databases, and output
paths for parallel checks. With four slots, the root and three implementers leave no simultaneous
integration slot. Use a slot released by completion before refilling it, or reserve one for
transient setup, tracker, and integration work. Reuse workers for these sequential roles instead
of keeping separate service agents active. Count review children in the same capacity budget.

Reconstruct running, completed, integrated, and satisfied attempts from the run record on resume.
An unowned ticket has no active implementer: no running worker or unresolved active attempt in
the record. Assignment to the authenticated actor remains advisory. Reconcile uncertain worker
state before redispatch so only one worker owns a ticket. A satisfied attempt stays terminal and
does not trigger redispatch on resume. If later integration may have invalidated its evidence,
revalidate the affected criteria at the current tip. Record the new tested SHA and evidence;
create another attempt only if that evidence fails and implementation is needed. Preserve unique WIP.

## Ticket integration

Read worker artifacts using implement-ticket's orchestrated result contract. Match the result's
`base_sha` to its recorded dispatch. Every merge, push, and deletion runs the exact sequences in
[Integration commands](#integration-commands) and [Cleanup](#cleanup), whose guards record the
integration HEAD and remote SHA and prove the tested, pushed head equals the expected branch tip.
A failed push, dirty worktree, or missing criterion evidence is not success.

When a worker returns `already_satisfied`, record `state: completed` until the coordinator
validates every criterion and applicable runtime evidence on the current verified integration
tip. Then record `state: satisfied`, the tested integration SHA, and the evidence, and release
dependants without a merge. Retain unique prior WIP and its branch regardless of this transition.

Accept an older dispatch base when it is an ancestor of the current integration HEAD and the
record proves its prerequisites were satisfied at dispatch. Check intervening changes for
reverted or invalidated prerequisite behavior and verify that dependencies still hold. Resolve
divergence or changed prerequisites before merging. Do not substitute the latest integration
SHA for the worker's immutable base or reuse stale evidence for `already_satisfied`.

Merge completed eligible results in completion order. Ticket number may break a tie among
completed results; a lower-numbered running ticket does not delay them. Keep both writers'
intent available for conflicts. Escalate semantic decisions to a resolver; even apparently
mechanical changes require tests. On failure, report actual HEAD and earlier successful merges,
and retain WIP and recovery evidence.

Run affected tests and relevant checks on the merged tree. An unchanged original baseline
failure is reported separately; newly introduced failures require a fix. If anyone resolved
hunks or added a fix, a separate worker runs Post-resolution tests before dependants proceed.
Only after verification, push the integration tip and confirm the remote SHA. Append decisions,
criterion evidence, and exact integrated commits to the durable record. Only this verified,
preserved tip satisfies dependencies for new dispatches. An integrator that authored no code
can supply independent integration verification. Final gates still check the whole feature.
Comment integration progress only with messaging authorization, including the commit SHA when posting.

Return `status` as merged, satisfied, escalated, or blocked. Use `satisfied` when every processed
ticket was validated without a merge. Include integrated ticket IDs and commits, satisfied ticket
IDs and evidence, actual HEAD, verified and pushed SHAs, checks, conflicts, remaining merge state,
dirty paths, and retained or cleaned resources. Keep detailed logs in the run artifact.

### Integration commands

Run these exactly from the integration checkout, substituting recorded values: `REMOTE`,
`INT` (integration branch), `TB` (ticket branch), `TICKET_SHA` (the result's tested, pushed head),
`BASE_SHA` (its dispatch base), and `VERIFIED_TIP` (the last verified, preserved integration tip).
Each guard must pass before the next command; a failed guard stops the sequence and its
output goes to the run record.

Before the merge, record the starting state and prove the result is the one dispatched:

```sh
git status --porcelain --untracked-files=all        # must print nothing
git rev-parse HEAD                                   # record as PRE_MERGE_HEAD
git ls-remote --exit-code "$REMOTE" "refs/heads/$INT"   # record as last preserved remote SHA
git ls-remote --exit-code "$REMOTE" "refs/heads/$TB"    # SHA must equal TICKET_SHA
git fetch "$REMOTE" "refs/heads/$TB"
git merge-base --is-ancestor "$BASE_SHA" HEAD        # exit 0, else resolve divergence first
```

Merge the pinned SHA, never the moving branch name, so a later push to `TB` cannot slip in:

```sh
git merge --no-ff -m "Merge ticket #<N> ($TB) into $INT" "$TICKET_SHA"
```

If the merge stops and is escalated rather than resolved, abort only an active merge, then
record the actual state. Never run `git reset --hard` to make a report true.

```sh
git rev-parse -q --verify MERGE_HEAD >/dev/null && git merge --abort
git rev-parse HEAD
git status --porcelain --untracked-files=all
```

After checks and any Post-resolution tests pass on the merged tree, push without force and
confirm the remote. A rejected push means the remote moved: fetch, reconcile, and re-verify.

```sh
git rev-parse HEAD                                   # record as the tested SHA
git push --porcelain "$REMOTE" "HEAD:refs/heads/$INT"
git ls-remote --exit-code "$REMOTE" "refs/heads/$INT"   # must equal the tested SHA
```

That SHA becomes `VERIFIED_TIP`.

### Cleanup

Cleanup follows orchestrator-mode's ownership and preservation rules. Use exact recorded
resources this run created only. Failed or unpushed WIP remains, and `already_satisfied`
never authorizes deleting unique WIP. Any non-zero guard below, including a merge-base error
for a commit missing locally, means retain the resource and record why.

Remove a ticket worktree only when it is clean and its HEAD is preserved:

```sh
git -C "$WT" status --porcelain --untracked-files=all      # must print nothing
git merge-base --is-ancestor "$(git -C "$WT" rev-parse HEAD)" "$VERIFIED_TIP"
git worktree remove "$WT"                                   # never --force
```

Delete the local ticket branch with its tip as the expected old value:

```sh
LOCAL_TIP=$(git rev-parse "refs/heads/$TB")
git merge-base --is-ancestor "$LOCAL_TIP" "$VERIFIED_TIP"
git update-ref -d "refs/heads/$TB" "$LOCAL_TIP"
```

Delete the remote ticket branch under a lease on the tip you just verified. An empty
`REMOTE_TIP` means the branch is already gone; stop there. A `rejected ... (stale info)` push means the remote
tip changed after verification: retain the branch and record the new tip.

```sh
REMOTE_TIP=$(git ls-remote "$REMOTE" "refs/heads/$TB" | cut -f1)
git merge-base --is-ancestor "$REMOTE_TIP" "$VERIFIED_TIP"
git push --force-with-lease="refs/heads/$TB:$REMOTE_TIP" --delete "$REMOTE" "refs/heads/$TB"
```

## Post-resolution tests

A separate worker checks every resolved hunk and prior failing test at the supplied integration
SHA. Return tested SHA, commands, results, and original baseline failures separately. On failure,
one worker fixes in scope, then a separate worker verifies again. Do not advance the verified
integration tip, publish an unverified fix as integration success, or clean up until this loop passes.

## Integration review

Before review, materialize `scope.md` from the canonical spec and ticket snapshots. For
`whole_spec`, its requirements section contains every spec requirement, ticket coverage obligation,
and end-to-end behavior. Missing coverage blocks readiness; ticket completion alone does not
satisfy the spec. For `selected_tickets`, the requirements section contains every selected ticket
criterion. Put the parent spec and unselected requirements in the context-only section. A no-spec
run still materializes the selected ticket criteria in `scope.md`.

Follow implement-ticket's [Independent review](../../implement-ticket/references/review-and-pr.md#independent-review)
contract in an isolated checkout at the tested integration SHA. Pass the recorded PR-base commit
as `base_sha`, that integration SHA as `review_sha`, and `scope.md` as the authoritative source.
Retain separate Standards and Spec reports in the run record. Ticket workers perform self-review;
this gate owns independent review of the complete feature.

## Feature PR

Prepare a draft body during setup with the intended scope and links to the spec and tickets.
Every draft, update, and final body follows implement-ticket's shared
[PR body](../../implement-ticket/references/review-and-pr.md#pr-body) contract and invokes `pr`.
Create or reuse one draft PR as soon as the verified, preserved integration branch has a
publishable diff. Use explicit `--base`, `--head`, and `--body-file`. A branch with
no diff may not support PR creation; record that pending state and retry after verified work
lands. Do not create empty commits or product changes solely to open a PR.

Record the PR identity and draft state in the run record. Keep intended scope separate from
completed work, and update actual results as tickets integrate. Partial or blocked work stays
draft. On resume, inspect the existing PR and reconcile its head and readiness with current
evidence; any incomplete or invalidated completion obligations require draft status.

After all gates pass, refresh complete open-ticket coverage. Add closing
lines only for tickets with current satisfaction evidence in the integrated head. Add
`Closes #<spec>` only when every open ticket is covered and every spec requirement has current
completion evidence, including in a selected-ticket run that happens to cover the whole spec.
Publish the `pr` body, then mark the same PR ready for review. Preserve the current body locally
if publication is blocked. Never merge the PR.
