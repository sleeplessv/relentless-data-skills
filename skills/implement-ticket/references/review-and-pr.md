# Review and PR contracts

Solo ticket owners and feature coordinators use these contracts. Orchestrated ticket workers
return implementation evidence through their dispatch contract.

## Independent review

Independently review every nonempty solo change and the complete feature integration.
Use the installed `code-review` instructions for both axes, including the full smell baseline.

Commit all intended changes and use a clean review checkout at the tested `review_sha`.
Resolve the immutable base and review commits, record `git diff <base_sha>...<review_sha>` and
`git log <base_sha>..<review_sha> --oneline`, and confirm the diff includes the intended work.
Set the review checkout's `HEAD` to `review_sha` so the skill's `...HEAD` command sees that tree.
An empty diff requires evidence for every acceptance criterion before reporting already satisfied.
Post the required stop comment and report that no-change outcome without creating an empty PR
or claiming a review ran. For solo runs, release only a claim this run added and leave the issue
open unless closure is already authorized.

Pass `base_sha` as the fixed point and an absolute path to the authoritative review scope.
For a solo ticket, save its current body, relevant comments, acceptance criteria, and scope
decisions in a requirements section. Put parent-spec context in a context-only section.
A feature uses its materialized `scope.md`. Explicitly instruct this invocation to use the supplied
snapshot, skip spec discovery and issue-tracker setup, and enforce only its requirements section.
Commit issue references must not replace that scope. Use context-only requirements for
interpretation, not additional work.

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

Fix actionable in-scope findings. Record a reason for dismissing or deferring optional suggestions
under their original axis. A preference alone does not require a refactor. Commit fixes and rerun
affected checks. Follow-up review examines those fixes and their consequences, carrying forward
unaffected findings and dispositions. Reopen a settled preference only when new evidence changes
the reasoning. A newly affected requirement or code path still needs review.

Reassess review depth if fixes expand the change. Record the final head, fixes reviewed, and why
prior outcomes still cover unchanged work. Readiness requires both axes and check evidence to
cover the final committed tree, with in-scope correctness, requirement, and documented-standard defects
resolved. New defects require fixes; optional preferences do not extend the completion loop.

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

After independent review, push the checked head and confirm the remote tip. Author the PR body.
A new defect returns to implementation, checks, and review.
Update or reuse the ticket's draft PR with `Closes #<N>` and the observed results.
Mark it ready only when required checks, review outcomes, and the remote tip cover the same head.
Post and record the stop comment with the PR URL and outcome, then report them to the user.
Leave merging to the human. A blocked publication preserves the branch and body.
