# Implement feature reference

Pass absolute paths and the needed section to each worker. Full ticket bodies, command logs,
and decisions stay in artifacts; returns contain compact outcomes and an index.

## Work-set resolution

Resolve the repository, default branch, spec, and explicit ticket arguments using `gh` and git.
For spec-only input, collect its open tickets. For explicit tickets, keep that list authoritative
and resolve any shared parent as context. Reject conflicting parent specs with concrete evidence.
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

Setup returns proposed `work_set`, `skipped_closed`, `spec_open_tickets`, coverage completeness,
`graph`, eligibility evidence, `resume_state`, integration candidate and default branch, plus
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

- `spec.md`, when a spec exists, holds context; `tickets/<N>.md` holds each full body and criteria.
- `scope.md` identifies selected tickets and their completion obligations for review.
- `handoff.md` holds command/resource setup, original baseline, current verified wave tip,
  branch identities, decision log, failures, and unresolved questions. Append decisions.
- A run record tracks exact owned worktrees/branches, initial and current SHAs, claim ownership,
  integration evidence per ticket, artifact paths, and push results. Report its absolute path.

Create native or manual ticket worktrees from the wave SHA in writable locations. Record creation
ownership and initial branch names rather than later guessing by patterns. Return `integration_branch`,
`integration_tip`, `original_base_sha`, original failures, `pr_base`, and all handoff/run-record paths.

## Wave integration

Read worker artifacts using implement-ticket's orchestrated result contract. Record the
wave-start SHA and last preserved remote SHA before merging. Confirm each success's `base_sha`
matches the wave and its tested/pushed head matches the expected branch tip. A failed push,
dirty worktree, or missing criterion evidence is not success.

Merge successful tips in ticket-number order. Keep both writers' intent available for conflicts.
Escalate semantic decisions to a resolver; even apparently mechanical changes require tests.
On failure, abort only an active merge and report actual HEAD and earlier successful merges.
Retain WIP and recovery evidence. Do not use an unconditional hard reset to make a report true.

Run affected tests and relevant checks on the merged tree. An unchanged original baseline
failure is reported separately; newly introduced failures require a fix. If anyone resolved
hunks or added a fix, a separate worker runs Post-resolution tests before dependants proceed.
Only after verification, push the integration tip and confirm the remote SHA. Append decisions,
criterion evidence, and exact integrated commits to the durable record. Comment integration
progress only with messaging authorization, including the commit SHA when posting.

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
one worker fixes in scope, then a separate worker verifies again. Do not advance the wave tip,
publish an unverified fix as integration success, or clean up until this loop passes.

## Integration review

Review `scope.md` and the selected ticket snapshots as completion obligations. The full spec is
context only. Supply these sources explicitly to `code-review` so it need not rediscover intent
from commit mentions. Use the recorded fixed PR-base commit and tested integration SHA. Report
unselected criteria as out of scope. A no-spec run still has scope.md and ticket snapshots.
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

Refresh complete open-ticket coverage before adding `Closes #<spec>`. Add closing lines only
for tickets with current satisfaction evidence in the integrated head; close the spec only
when every open ticket is covered. Use explicit `--base` and `--head` and the repo PR template.
Create or update the existing feature PR, with Summary, actual Test plan, and Verification plan.
Apply `awaiting-verification` only within authorized lifecycle ownership and when the plan has
human scenarios. Preserve the final body locally if publication is blocked. Never merge the PR.
