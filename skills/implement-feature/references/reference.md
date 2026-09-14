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
before any authorized claim. `needs-info`, `needs-triage`, or `wontfix` needs resolution; a WIP
branch alone does not prove agent-authored triage. An explicit current user instruction can
resolve a prior agent stop. Track which lifecycle changes this run actually owns.

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
- `scope.md` records completion mode, selected tickets, spec coverage, gaps, and scope decisions.
- `handoff.md` holds command/resource setup, original baseline, current verified integration tip,
  branch identities, decision log, failures, and unresolved questions. Append decisions.
- A run record tracks exact owned worktrees/branches, initial and current SHAs, claim ownership,
  integration evidence per ticket, artifact paths, and push results. Store the feature PR identity,
  draft status, and last published head. Report the run record's absolute path.
- For each ticket attempt, record the worker ID, branch, start-comment URL, stop-comment URL,
  outcome, immutable dispatch SHA, prerequisite evidence, and state: ready, running, completed,
  integrated, failed, or blocked. Distinguish worker completion from verified integration.
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

Reconstruct running, completed, and integrated attempts from the run record on resume. Reconcile
uncertain worker state before redispatch so only one worker owns a ticket. An `already_satisfied`
result requires current criterion evidence before releasing dependants, just like a merged result.

## Ticket integration

Read worker artifacts using implement-ticket's orchestrated result contract. Before each merge,
record the actual integration HEAD and last preserved remote SHA. Match the result's `base_sha`
to its recorded dispatch and confirm its tested, pushed head equals the expected branch tip.
A failed push, dirty worktree, or missing criterion evidence is not success.

Accept an older dispatch base when it is an ancestor of the current integration HEAD and the
record proves its prerequisites were satisfied at dispatch. Check intervening changes for
reverted or invalidated prerequisite behavior and verify that dependencies still hold. Resolve
divergence or changed prerequisites before merging. Do not substitute the latest integration
SHA for the worker's immutable base or reuse stale evidence for `already_satisfied`.

Merge completed eligible results in completion order. Ticket number may break a tie among
completed results; a lower-numbered running ticket does not delay them. Keep both writers'
intent available for conflicts. Escalate semantic decisions to a resolver; even apparently
mechanical changes require tests. On failure, abort only an active merge and report actual HEAD
and earlier successful merges. Retain WIP and recovery evidence. Do not use an unconditional
hard reset to make a report true.

Run affected tests and relevant checks on the merged tree. An unchanged original baseline
failure is reported separately; newly introduced failures require a fix. If anyone resolved
hunks or added a fix, a separate worker runs Post-resolution tests before dependants proceed.
Only after verification, push the integration tip and confirm the remote SHA. Append decisions,
criterion evidence, and exact integrated commits to the durable record. Only this verified,
preserved tip satisfies dependencies for new dispatches. An integrator that authored no code
can supply independent integration verification. Final gates still check the whole feature.
Comment integration progress only with messaging authorization, including the commit SHA when posting.

Cleanup follows orchestrator-mode's ownership and preservation rules. Use exact recorded
resources only. Before removing any checkout, check uncommitted and untracked work and prove
all needed commits are preserved. Failed or unpushed WIP remains. Before deleting a branch,
prove its current local and remote tips are ancestors of the verified preserved integration
head and it belongs to this run. Use an expected-tip lease for remote deletion where available;
a changed remote tip is retained. `already_satisfied` never authorizes deleting unique WIP.

Return `status` as merged, escalated, or blocked; integrated ticket IDs and commits, actual HEAD,
verified and pushed SHAs, checks, conflicts, remaining merge state, dirty paths, and retained or
cleaned resources. Keep detailed logs in the run artifact.

## Post-resolution tests

A separate worker checks every resolved hunk and prior failing test at the supplied integration
SHA. Return tested SHA, commands, results, and original baseline failures separately. On failure,
one worker fixes in scope, then a separate worker verifies again. Do not advance the verified
integration tip, publish an unverified fix as integration success, or clean up until this loop passes.

## Integration review

Review `scope.md` and the selected ticket snapshots at the tested integration SHA. For
`whole_spec`, also review every spec requirement, its ticket coverage, and end-to-end behavior.
Missing coverage blocks readiness until reconciled; ticket completion alone does not satisfy
the spec. For `selected_tickets`, the parent spec supplies context and unselected requirements
remain out of scope. Supply these sources and the completion mode explicitly to `code-review`.
Use the recorded fixed PR-base commit. A no-spec run still has scope.md and ticket snapshots.
Schedule any review children within capacity, or use independent direct reviews of standards
and acceptance criteria when the review skill is unavailable.

## Verification plan

Use at most three critical scenarios requiring human judgement beyond automated checks.
Each has copy-paste-ready steps, preconditions and cleanup where needed, and one "What you
should see" line grounded in observed results. Execute reachable steps with safe inputs;
label inaccessible ones "not executed, requires <environment>". Preserve uncovered acceptance
criteria in the evidence record rather than silently declaring them verified. If none qualify,
write "No human verification beyond code review: <reason>". Replace a prior plan on resume.

## Feature PR

Prepare a draft body during setup with the intended scope and links to the spec and tickets.
Create or reuse one draft PR as soon as the verified, preserved integration branch has a
publishable diff. Use explicit `--base` and `--head` and the repo PR template. A branch with
no diff may not support PR creation; record that pending state and retry after verified work
lands. Do not create empty commits or product changes solely to open a PR.

Record the PR identity and draft state in the run record. Keep intended scope separate from
completed work, and update actual results as tickets integrate. Partial or blocked work stays
draft. On resume, inspect the existing PR and reconcile its head and readiness with current
evidence; any incomplete or invalidated completion obligations require draft status.

After all gates and the verification plan, refresh complete open-ticket coverage. Add closing
lines only for tickets with current satisfaction evidence in the integrated head. Add
`Closes #<spec>` only when every open ticket is covered and every spec requirement has current
completion evidence, including in a selected-ticket run that happens to cover the whole spec.
Publish Summary, actual Test plan, and Verification plan, then mark the same PR ready for review.
Apply `awaiting-verification` only within authorized lifecycle ownership and when the plan has
human scenarios. Preserve the current body locally if publication is blocked. Never merge the PR.
