# Orchestrated ticket contract

Read only for a feature dispatch. The coordinator owns ticket eligibility, assignment,
labels, external comments, and the feature PR. The worker implements its named ticket and
returns evidence; it opens no ticket PR and does not change the issue lifecycle.

## Inputs and setup

Read the ticket snapshot and handoff files at the supplied absolute paths. The selected
ticket's acceptance criteria define completion; the full spec informs design decisions.
Inputs include `base_branch` as integration destination, immutable `base_sha`, original
baseline SHA and failures, `worktree_path`, resource allocation, and optional `resume_branch`.
The coordinator records eligibility before dispatch. If live evidence contradicts its
snapshot, return that discrepancy rather than claiming or silently overriding triage.

Confirm this is the assigned isolated checkout. Record its path, initial branch and HEAD,
and which resources this run created. Cut the ticket branch from `base_sha`, verifying HEAD
before edits, without checking out the integration branch. Native isolation may start at a
different tip. Follow environment branch conventions. Install dependencies after choosing the
actual attempt checkout. Use configured permissions and the recorded command/resource setup.

## Resume

1. Inspect any selected prior attempt's findings and local/remote tips. Branch-name matches
   are candidates, not proof of identity. Resolve multiple or divergent candidates using
   their recorded task and commits; surface ambiguity rather than guessing.
2. Check whether the pinned base already satisfies **every** acceptance criterion, including
   runtime or artifact criteria. Return `already_satisfied` only with per-criterion evidence
   and the tested SHA equal to `base_sha`. Passing an old failing test alone is insufficient;
   an absent test proves nothing. Missing environment evidence remains unresolved.
3. Otherwise preserve the prior WIP tip. Use a fresh attempt branch based on that tip before
   rebasing onto `base_sha` unless rewriting the pushed branch is already authorized. Abort
   a conflicting rebase explicitly. Resolve with preserved context or rebuild on a new branch
   from `base_sha`, retaining the original WIP and reporting what was reused or omitted.

## Implementation and verification

Follow SKILL.md's scope, implementation, feedback-loop, artifact check, and full-diff review
steps. Skip solo selection, claiming, PR creation and publication. Reuse loaded guidance;
explicit skill requirements remain in force. No helper-agent fan-out inside the ticket.

Reuse the original recorded baseline failures. Compare a newly observed failure against
`base_sha` in a safe separate checkout if needed, recording both SHAs. A failure introduced
by this ticket must be fixed; a failure on the current integration base is reported separately
and does not silently become an original baseline failure. Review `git diff <base_sha>...HEAD`,
fix in-scope findings, and rerun affected checks before the final commit.

## Result and preservation

Push success or WIP when authorized, then verify the remote tip. A push failure cannot be
reported as durable remote WIP. Write detailed evidence to an artifact and return:

- `status`: `success`, `already_satisfied`, or `failed`.
- `branch`, `base_sha`, `head_sha`, `tested_sha`, `worktree_path`, `initial_branch`, and
  explicitly recorded task-created resources. Use null for facts unavailable before setup.
- `push_status`, `remote_sha`, `dirty_files`, and any saved prior WIP tip.
- `files_changed`, compact `tests_run`, per-criterion evidence, relevant `decisions_made`,
  `open_questions`, `root_cause` on failure, and `artifact_path` for full details.

`success` requires every criterion and applicable check to be satisfied on `head_sha` plus
confirmed publication of that head to the ticket branch. `already_satisfied` makes no claim
that unique WIP commits can be deleted. `failed` preserves all uncommitted or unpushed work.
The coordinator handles questions and may continue independent tickets.
