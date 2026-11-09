# Review and PR contracts

Solo ticket owners and feature coordinators use these contracts. Orchestrated ticket workers
return implementation evidence through their dispatch contract.

## Review workspace

These rules bind the workers whose briefs cite this section: the verifier, each `code-review`
reviewer, and the final reviewer. Each brief names the run directory and links here.

Set `REPO` to the main checkout, `RUN_DIR` to the run directory, `SHA` to the full commit SHA
the brief pins, and `ROLE` to the worker's job (`verify`, `review`, `standards`, `spec`, or
`final`). If `$RUN_DIR/$ROLE-$SHA` already exists, add a numeric suffix to `ROLE`.

**Writes.** The worker writes only under `$RUN_DIR/$ROLE-$SHA`. That directory holds its
checkout, temporary files, lists of changed paths, and captured command output. `/tmp`, other
shared paths, and the rest of the run directory stay untouched. Git's worktree metadata and the
uniquely named temporary files that tools create for themselves are outside this rule. Results
still return inline, as [Independent verification](#independent-verification) says.

**Checkout.** The worker creates its own detached checkout, so it owns what it later removes.
Exit 0 passes. On any other exit, the worker reports a blocked check with the error.

```sh
git -C "$REPO" worktree add --detach "$RUN_DIR/$ROLE-$SHA/checkout" "$SHA"
```

A worker that dispatches children, as `code-review` does, shares its checkout with them. That
worker alone removes the checkout, after every child returns.
The parent passes each child `RUN_DIR`, the checkout path, and a link to this section. A child
writes under its own `$RUN_DIR/$ROLE-$SHA`, creates no checkout, and returns no `checkout:` line.

**Removal.** Before returning, whatever the verdict, the worker runs both commands in order and
stops at the first non-zero exit.

```sh
test "$(git -C "$RUN_DIR/$ROLE-$SHA/checkout" rev-parse HEAD)" = "$SHA" && # exit 0 = still at the pinned commit
git -C "$REPO" worktree remove "$RUN_DIR/$ROLE-$SHA/checkout"              # exit 0 = removed
```

A non-zero exit leaves the checkout in place. Git refuses to remove a dirty tree, and the worker
runs this command without `--force`, because a clean tree does not need it. The return states
`checkout: removed`, or `checkout: retained at <path>` with the reason. Apart from the children
above, a worker handed a checkout it did not create leaves it in place and reports it as
retained, naming its creator.
The coordinator records each retained checkout in the findings artifact or run record.

## Independent verification

The coordinator (the solo run's main thread) dispatches the verifier and the reviewers; a
dispatch from the implementing worker would nest, spending capacity and weakening independence.
Solo runs rerun the implementing worker's evidence before independent review. The verifier is
a worker that wrote none of the change. Pass it the run directory, the main checkout path
(`REPO`), the tested `head_sha`, the findings artifact path, the check commands from step 6, the
smoke commands or script from step 7, and the implementing worker's resource allocation.

Verifiers, reviewers, and fix workers return results inline and the coordinator saves them; the
harness may block their report-file writes. Only implementers write the evidence artifact.

The verifier follows [Review workspace](#review-workspace), uses a clean checkout at `head_sha`,
confirms `HEAD` matches, reruns every recorded command changed only where a path must point at
its own checkout or workspace, records each such substitution, and returns its own exit codes, output excerpts, and checked SHA. A command it
cannot run is a blocked check reported with its reason. Reuse the implementing worker's ports and
resources, or serialize with any still in use.

Divergence from the implementing worker's report goes back to it with the verifier's output.
A code-touching fix commits, reruns steps 6 and 7, and gets a fresh verification on the new head;
a prose-only fix takes the lighter loop defined in [Independent review](#independent-review).
Readiness requires verification evidence covering the final committed tree; the prose-only loop
defines when the last verified head's evidence extends to later commits. Feature runs use the
coordinator's Verify gate instead.

## No-change outcome

A ticket whose every acceptance criterion already holds on `base_sha` gets no implementation,
no empty PR, and no claim that a review ran. The outcome is still a claim, so it needs evidence:
per-criterion evidence on `base_sha`, including runtime or artifact criteria, with the commits
that satisfied them when history shows them. Independent verification applies: a worker that
gathered none of the evidence reruns the recorded checks and smoke commands on `base_sha`.

Post the stop comment with that evidence. Leave the issue open unless closure is already
authorized, and release a claim this run added. Report in `open_questions` whether to close the
ticket and whether to remove `ready-for-agent`, since auto-pick will keep selecting it while the
label stays. Orchestrated workers return `already_satisfied` under their dispatch contract instead.

## Independent review

Independently review every nonempty solo change and the complete feature integration.
Use the installed `code-review` instructions for both axes, including the full smell baseline.

Commit all intended changes and use a clean review checkout at the tested `review_sha`, set up
as [Review workspace](#review-workspace) describes.
Resolve the immutable base and review commits, record `git diff <base_sha>...<review_sha>` and
`git log <base_sha>..<review_sha> --oneline`, and confirm the diff includes the intended work.
Set the review checkout's `HEAD` to `review_sha` so the skill's `...HEAD` command sees that tree.
An empty diff means the [No-change outcome](#no-change-outcome) applies; review does not run.

Pass the run directory, the main checkout path (`REPO`), `base_sha` as the fixed point,
`review_sha` as the commit to review, and an absolute path to the authoritative review scope.
For a solo ticket, that scope is `ticket-snapshot.md` in the run directory. The worker that
completes step 1 saves the ticket's body, relevant comments, and acceptance criteria as its
`## Requirements` section before implementation starts, so the enforced scope predates every
design choice. The implementing worker records its design choices in a separate
`## Author decisions` section of the same file, each tied to the criterion it resolves.
Parent-spec context and a ticket body's own `## Context` section stay in `## Context only`. A feature uses its materialized `scope.md`.
Explicitly instruct this invocation to use the supplied snapshot, skip spec discovery and
issue-tracker setup, enforce only `## Requirements`, and judge each author decision against
them rather than as a requirement. Commit issue references must not replace that scope. Use
context-only requirements for interpretation, not additional work.

Choose review depth from the complete diff, recording the reason:

- **Trivial solo change:** spelling, formatting, or comments whose meaning and behavior are
  unchanged. Load `code-review` and pass both prompts and the full baseline to one fresh reviewer
  independent of the author. Instruct it to return separate Standards and Spec reports without
  spawning children. This is a local adaptation of the skill's normal two-agent dispatch.
- **All other changes:** run `code-review` with parallel Standards and Spec agents. Use this route
  for behavioral changes, uncertainty, and every feature integration. Diff size alone does not
  qualify a change as trivial. Changes to agent instructions, acceptance criteria, configuration,
  dependencies, CI, migrations, or APIs use this route even when the diff is small.

Both routes inspect the whole initial diff with the same pinned commits, authoritative scope,
standards, and baseline. Keep reports, finding counts, dispositions, and the worst issue separate
by axis. Baseline smells are judgement calls; repo rules take precedence. Count all reviewers
against capacity. The full route may dispatch its axes directly using the loaded skill's prompts.

Fix actionable in-scope findings. A finding that identifies a factual inaccuracy in prose (docs,
comments, PR body, commit text) is a defect and gets fixed whatever severity label the reviewer
gave it; "optional" covers preferences only. Record a reason for dismissing or deferring optional
suggestions under their original axis. A preference alone does not require a refactor. Commit
fixes; a code-touching fix returns through [Independent verification](#independent-verification),
and a prose-only fix takes the lighter loop below. Follow-up review examines those fixes and their
consequences, carrying forward unaffected findings and dispositions. Reopen a settled preference
only when new evidence changes the reasoning. A newly affected requirement or code path still
needs review.

A **prose-only fix** touches no code, test, configuration, dependency, CI, or agent-instruction
semantics. Its lighter loop: the implementing worker reruns the validators and lint that cover
the changed files and records the diff in the findings artifact; follow-up review runs only on
the axis that raised the finding; the recorded checks on the last verified head still cover the
unchanged code, so that verification extends to the new head and no fresh verification runs. The
next code-touching fix returns to the full loop.

Reassess review depth if fixes expand the change. Record the final head, fixes reviewed, and why
prior outcomes still cover unchanged work. Readiness requires both axes and verified check evidence to
cover the final committed tree, with in-scope correctness, requirement, and documented-standard defects
resolved. New defects require fixes; optional preferences do not extend the completion loop.

## Final review

The final review is one quality pass by a worker that wrote none of the change and saw none
of the earlier reviews. The coordinator dispatches it once per run, after independent
verification and both review axes pass on the final committed tree, and before any publication
work. The trivial solo route and orchestrated ticket dispatches skip it; record the reason.
Feature runs take it once at integration
([Integration review](../../implement-feature/references/reference.md#integration-review)).

Brief the reviewer with the run directory, the main checkout path (`REPO`), the reviewed
`head_sha` (or integration SHA) to check out, `base_sha` as the fixed point, the absolute path
to the scope file (`ticket-snapshot.md` or `scope.md`) so lean findings respect what the ticket
requires, and the instruction to run the installed `ponytail-review` skill on `git diff <base_sha>...HEAD`. The reviewer follows
[Review workspace](#review-workspace). The pass is blind:
those are its only inputs, and it receives no Standards or Spec report, findings artifact, or
earlier disposition. The brief supplies the run directory only as a place to write. An
unavailable `ponytail-review` skips the gate; the findings artifact and PR body record "final
review not run: skill missing" and readiness is unaffected.

The coordinator decides every finding and records the disposition itself, with no user prompt:

- **Must fix:** fix in this PR, including defects in pre-existing code the diff did not cause.
  This is the exception named by the scope rule at the top of SKILL.md's Workflow; the PR body
  names each such fix under Evidence.
- **Should fix:** fix in this PR, including lean refactors (delete, merge, split) and a
  missing test for changed behaviour. The sole exemption is a finding that restates a disposition an earlier review
  recorded with a reason, with no new evidence; carry that disposition forward.
- **Nice to have:** record and leave; list under deferred cleanup with the follow-up offer.
- **Oversized fix:** a must-fix or should-fix whose fix would be larger than the reviewed diff
  (`base_sha...HEAD`) is escalated through `open_questions` with the proposed fix and its size. The PR stays
  draft and the stop comment names it.

Accepted fixes go to the implementing worker (solo) or one fix worker (feature). A
code-touching fix returns through [Independent verification](#independent-verification) and
follow-up `code-review` on both axes over the fix diff; a prose-only fix takes the
[prose-only loop](#independent-review) with no follow-up review. The final review runs once and
is not repeated after its own fixes.

Record a `## Final review` section in the findings artifact: each finding with its tier,
disposition (fixed, escalated, recorded), fixing commit, and a one-line reason for anything not
fixed. The PR body's Evidence states the tier counts and outcomes. Readiness requires every
must-fix and should-fix fixed; an escalated finding keeps the PR draft until the user answers.
Nice-to-haves never block it.

## PR body

Follow [Writing](setup.md#writing) for all PR prose. Apply `technical-writing` and `unslop`
while retaining the structure supplied by `pr` and required repository templates.

Invoke `pr` whenever creating or updating a draft or final PR body. It owns Summary, Evidence,
and Merge Danger. Keep its template and visual guidance in that skill. For trivial changes,
use one short diff sketch and brief evidence and risk statements. If publication is blocked by
setup's dependency check, retain the material locally and report that limitation.
Use the repo's domain vocabulary from `GLOSSARY.md` or its documented equivalent, such as
`CONTEXT.md`.

Preserve required repository-template fields and the caller's issue links or closing lines.
Put executed commands and observed results in Evidence. If the repo requires a Test plan field,
point it to those results rather than duplicating them.
Use `--body-file` for multiline `gh pr create` and `gh pr edit` bodies.
GitHub applies closing keywords only on PRs into the default branch: when `pr_base` is another
branch, say in the body and the report that `Closes #<N>` takes effect after retargeting.
Choose the closing line by the repo's issue-tracker rule when its docs set one (a repo may, for
example, want `Refs #<N>` while post-merge verification remains); otherwise keep `Closes #<N>` when the only
open items are post-merge or post-deploy checks, and list them. Record the choice under `## Author decisions`
instead of asking.

Gather before/after evidence while implementing. The before observation can be a red test,
reproduction output, screenshot, or prior artifact. Record its commit and command or capture
context. The after observation must describe the delivered behavior on the checked head.
Original baseline checks establish regression attribution; they do not automatically demonstrate
the ticket's previous behavior. Feature authors read worker evidence by path and distinguish
dispatch-base observations from the original feature base and final integration results.

Draft bodies describe intended scope and mark unexecuted evidence as pending. Final bodies use
actual observations. If no before observation is available, say so instead of inventing one.
Missing required checks keep the PR draft. Explain rollback cost and affected consumers in
Merge Danger using the actual change. Replace stale draft claims on resume.

## Solo finalization

The implementing worker owns this section. After the final review, push the checked head and
confirm the remote tip. Author the PR body.
A new defect returns to implementation, checks, and review.
Update or reuse the ticket's draft PR with the closing line chosen in [PR body](#pr-body) and the observed results.
After the push, run `gh pr checks <PR> --watch`; a failing required CI check is a defect, and a
pending one counts as unexecuted evidence.
Mark it ready only when required checks, review outcomes, and the remote tip cover the same head.
The report lists temporary code, post-merge manual steps, and deferred cleanup, and offers a
follow-up issue with acceptance criteria for them.
Post and record the stop comment with the PR URL and outcome, then report them to the user.
Leave merging to the human. A blocked or denied publication step preserves the branch and body,
keeps the PR a draft, and takes the stop path with a stop comment that states what remains.
