# Review and PR contracts

Solo ticket owners and feature coordinators use these contracts. Orchestrated ticket workers
return implementation evidence through their dispatch contract.

After step 8's self-review a solo run takes these sections in order: the [Check wave](#check-wave),
[Fix rounds](#fix-rounds), then [Closing verification](#closing-verification) beside
[Solo finalization](#solo-finalization). The [Door](#door) decides where a finding still open
after the last round goes.

## Review workspace

These rules bind the workers whose briefs cite this section: each `code-review` reviewer, the
final reviewer, the re-check reviewer, and the verifier. Each brief names the run directory and
links here.

Set `REPO` to the main checkout, `RUN_DIR` to the run directory, `SHA` to the full commit SHA
the brief pins, and `ROLE` to the worker's job (`standards`, `spec`, `review`, `final`,
`recheck`, or `verify`). If `$RUN_DIR/$ROLE-$SHA` already exists, add a numeric suffix to `ROLE`.

**Writes.** The worker writes only under `$RUN_DIR/$ROLE-$SHA`. That directory holds its
checkout, temporary files, lists of changed paths, and captured command output. `/tmp`, other
shared paths, and the rest of the run directory stay untouched. Git's worktree metadata, the
remote-tracking ref a fetch updates, and the uniquely named temporary files that tools create
for themselves are outside this rule.

**Returns.** Verifiers, reviewers, and fix workers return results inline and the coordinator
saves them; the harness may block their report-file writes. Only implementers write the
evidence artifact, and one whose write is blocked returns its content inline.

**Checkout.** The worker creates its own detached checkout, so it owns what it later removes.
Exit 0 passes. On any other exit, the worker reports a blocked check with the error.

```sh
git -C "$REPO" worktree add --detach "$RUN_DIR/$ROLE-$SHA/checkout" "$SHA"
```

A worker that dispatches children, as `code-review` does, shares its checkout with them. That
worker alone removes the checkout, after every child returns.
The parent passes each child `RUN_DIR`, `SHA`, the checkout path, and a link to this section. A child
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

## Door

A change is a **one-way door** when reverting its PR would leave an effect in place: a data
migration or backfill, a destructive data or schema change, a published release, a deleted
external resource, a permissions or secrets change, or a workflow whose first run deploys or
sends. Every other change is a **two-way door**. Classify by what the change does when it runs:
a workflow file reverts cleanly, and the deploy it triggered does not. A change of uncertain
type is one-way. This is the door `pr` reports under Merge Danger.

The worker that completes step 1 records `door:` with a one-line reason at the top of
`ticket-snapshot.md`, from the ticket text. The implementing worker's step 8 return, and each
later return that carries a commit, confirms the door against the committed diff or raises it
to one-way. The coordinator copies the door to the decision list, and only the user lowers a
one-way door. A feature run classifies each ticket at work-set
resolution. The feature is one-way when any ticket in its work-set is, and `scope.md` records
its door.

| | Two-way door | One-way door |
|---|---|---|
| A finding still open after the last [fix round](#fix-rounds) | Listed in the PR body under Merge Danger | Returned through `open_questions`, each with a recommended disposition |
| The PR once every gate has passed and no escalation is pending | Marked ready | Stays draft; the report asks the user for the go-ahead |

On the user's yes to a one-way door, the coordinator dispatches a worker to mark the PR ready
and update the stop comment. A fix the user orders instead is a [late fix](#fix-rounds).

## Model classes

The coordinator sets each dispatch's model by class. The Model classes section of
orchestrator-mode's `references/reference.md` defines the classes, their alias in each
harness, and class escalation.

- **Strong class**: the implementing worker, with its fixes and finalization, and every
  reviewer of the check wave and of a re-check.
- **Session class**: those reviewers when the door is one-way. A solo run dispatches the
  implementing worker before step 1 records the door, so the door changes the reviewers'
  class and leaves the implementing worker's. A door raised to one-way after the wave moves
  each later re-check to the session class and leaves the wave as it ran.
- **Standard class**: the closing verification, and a fresh worker that marks a one-way
  door's PR ready.

A failed check, for class escalation, is a re-check that leaves an accepted finding open or a
closing-verification divergence, and the two kinds count together across the run. The wave's
findings on the first commit are not one. After a class escalation, the replacing worker is
the worker that made the last commit wherever this file names one.

## Check wave

The wave is every review of the change, dispatched together on one commit. It starts when the
implementing worker returns step 8's self-review with steps 6 and 7 passing on a committed
`head_sha`; that recorded output is the wave's check evidence, and
[Closing verification](#closing-verification) reruns it once at the end.

The coordinator (the solo run's main thread) dispatches the wave in one message, each worker
pinned to `head_sha`: the Standards reviewer and the Spec reviewer under
[Independent review](#independent-review), and the final reviewer under
[Final review](#final-review). It dispatches the two axes directly, with the installed
`code-review` prompts and baseline, so the wave fits four slots. The trivial route's wave is
its one reviewer.

When every reviewer has returned, the coordinator triages the reports into one list. Each
finding keeps its axis (Standards, Spec, or Final), and a finding two reviewers raised is one
item. Dispositions follow [Independent review](#independent-review) and the tiers in
[Final review](#final-review). Done when every finding has a recorded disposition. Accepted
fixes go to [Fix rounds](#fix-rounds); a wave with none goes to
[Closing verification](#closing-verification).

## Fix rounds

A **round** is one fix dispatch and its re-check. A run takes at most two rounds.

**Fix.** Every accepted finding goes in one brief to the implementing worker (solo) or one fix
worker (feature). Fix a finding that names a class as the class. Its fix brief covers every
instance the named search finds, and the fix worker returns a table of every site it considered
with a verdict for each. A fix too large to close the class goes back to the coordinator as an
open question with its size. Fix an unconfirmed runtime finding only after a probe confirms it.
The fix worker probes first; where no probe can run, it returns the finding unfixed, and the
coordinator accepts or defers it from the reviewer's reasoning and the size of the fix, recording
it as unprobed. An accepted one joins the next round's fix; with no round left it follows the
[Door](#door).
The fix worker commits, reruns steps 6 and 7 for the affected paths, and returns the commands,
their output, and the checked `fix_sha`. For each factual sentence it changed in prose, it
returns the file and line that back the sentence.

**Re-check.** A code-touching fix gets one fresh reviewer, briefed as
[Independent review](#independent-review) describes, with the wave's `head_sha` as the fixed
point, `fix_sha` as the commit to review, the same scope file and reporting instructions, and
the list of accepted findings. It applies both `code-review` axes to
`git diff <head_sha>...<fix_sha>` and returns separate Standards and Spec reports without
spawning children. It first confirms that each accepted finding is closed; one the fix left
open, or closed at only some of its sites, keeps its tier. Any other finding requires a fix
(should-fix) only when it is a defect that the fix diff introduced or exposed, such as one that lets a check pass something weaker
than its criterion, or a false statement in text the fix changed. A pre-existing defect in the
class the fix addresses goes to the coordinator once, as a class with a proposed fix that
closes it, and the coordinator decides whether it blocks. Other findings are nice-to-have and
deferred. The coordinator carries forward unaffected findings and dispositions, and reopens a
settled preference only when new evidence changes the reasoning.

A **prose-only fix** touches no code, test, configuration, dependency, CI, or agent-instruction
semantics. The fix worker reruns the validators and lint that cover the changed files and
returns the diff for the findings artifact. A prose-only fix takes no re-check and is not a
round. A false sentence the second re-check finds is still fixed, in one prose-only fix before
Publish and closing verification; one a late-fix re-check finds follows the [Door](#door).

A second round fixes every finding the first re-check leaves requiring a fix and is re-checked
the same way, over `git diff <fix_sha>...<second fix_sha>`. After the second re-check the
rounds are spent, and each should-fix or must-fix finding still open, except a false sentence
a prose-only fix closes, follows the [Door](#door). A step 6 or 7
command that fails after a fix is fixed before the fix worker returns; one that cannot be made
to pass falls under SKILL.md's stop conditions and never takes a door outcome.
Reassess review depth when fixes expand the change: a trivial change whose fix alters behavior
takes the full route's wave on the new head.

A **late fix** is a change committed after the rounds: the fix for a closing-verification
divergence, a target merge that edits a shared path, the fix for a failing CI check, or a fix
the user orders. A late fix that touches code gets one re-check under the rule above, outside
the two rounds, of its own diff or, for a target merge, of the merge's edits to the shared
paths. A should-fix finding from that re-check follows the [Door](#door). Every late fix is
pushed and voids the closing verification before it, so CI and closing verification rerun on
the new head. A required CI check that fails again after its late fix stops the run as blocked.

Done when no should-fix or must-fix finding is open, or the rounds are spent and each remaining
finding is recorded with its tier, evidence, and door outcome.

## Closing verification

Closing verification is the one clean-checkout rerun of the change's checks, on the commit that
ships. The coordinator dispatches it on the final committed head (`final_sha`) after the last
fix round, beside [Solo finalization](#solo-finalization)'s publish steps. A pass holds for
that commit alone: a later commit voids it, and a fresh one runs on the new head. The verifier is a
worker that wrote none of the change, and it reports without editing: its writes stay in its
[Review workspace](#review-workspace). Pass it the run directory, the main checkout path
(`REPO`), `final_sha` as `SHA`, the findings artifact path, the install or build commands step 4
recorded, the check commands from step 6, the smoke commands or script from step 7, the implementing worker's resource
allocation, and `REMOTE` and `PR_BASE` (the remote name and the branch the PR targets).

The verifier uses a clean checkout at `SHA`, confirms `HEAD` matches, reruns every recorded
command changed only where a path must point at its own checkout or workspace, or as the
wrong-record rule below allows, records each such substitution, captures each command's exit
code before any pipe, and returns its own exit codes, output excerpts, and checked SHA. A command it
cannot run is a blocked check reported with its reason. Reuse the implementing worker's ports
and resources, or serialize with any still in use.

It then checks the target branch for drift, from its checkout. A non-zero exit the comments
do not name is a blocked check, reported with its output, and the verifier stops there:

```sh
git fetch "$REMOTE" "refs/heads/$PR_BASE"                    # exit 0 = fetched
TARGET_TIP=$(git rev-parse FETCH_HEAD)
git merge-base --is-ancestor "$TARGET_TIP" "$SHA"            # exit 0 = no drift; exit 1 = the target gained commits
```

On exit 1 it returns `TARGET_TIP`, what the target gained, and where the two sides meet:

```sh
git log --oneline "$SHA..$TARGET_TIP"                        # the commits the target gained
git merge-tree --write-tree --name-only "$SHA" "$TARGET_TIP" # exit 0 = merges cleanly; exit 1 = conflicts, paths listed
comm -12 <(git diff --no-renames --name-only "$TARGET_TIP...$SHA" | sort) <(git diff --no-renames --name-only "$SHA...$TARGET_TIP" | sort)   # paths both sides changed; a rename counts at its old and new path
```

A recorded install or build command that fails on the unchanged tree, such as one that omits
a dependency group, is a wrong record. The verifier reruns with the corrected command and
reports both, and the coordinator records the correction with its reason. A step 6 check or
step 7 smoke command is never corrected this way: its failure is a divergence.

The coordinator acts on the return:

- **Checks reproduce, and no drift or drift with no shared path:** the evidence covers the
  final head. Record drift in the PR body's Evidence.
- **A check diverges from the recorded result:** the output goes back to the worker that made
  the last commit. Its fix is a [late fix](#fix-rounds) that reruns steps 6 and 7, and the PR
  body's Evidence names it. A second divergence stops the run as blocked.
- **Drift with a conflict or a shared path:** two sides can change one line to the same text
  and merge cleanly, as when both bump a version to the same number. The worker that made the
  last commit merges `TARGET_TIP` into the branch without rewriting it, compares both sides'
  diffs of each shared path, and edits where the merged text no longer serves both (a version
  both sides bumped takes the next number). It reruns steps 6 and 7, pushes, and returns the
  new head with what it edited; an edit makes the merge a [late fix](#fix-rounds).

Readiness requires a passing closing verification on the final committed tree. Feature runs use
the coordinator's Verify gate as theirs.

## No-change outcome

A ticket whose every acceptance criterion already holds on `base_sha` gets no implementation,
no empty PR, and no claim that a review ran. The outcome is still a claim, so it needs evidence:
per-criterion evidence on `base_sha`, including runtime or artifact criteria, with the commits
that satisfied them when history shows them. [Closing verification](#closing-verification)
applies with `base_sha` as its `SHA`: a worker that gathered none of the evidence reruns the
recorded checks and smoke commands there. A divergence means the criteria do not hold, and the
ticket resumes at the step that took this outcome (step 1 or step 4). On drift, a fresh closing verification runs with `TARGET_TIP` as its
`SHA`.

Post the stop comment with that evidence. Leave the issue open unless closure is already
authorized, and release a claim this run added. Report in `open_questions` whether to close the
ticket and whether to remove `ready-for-agent`, since auto-pick will keep selecting it while the
label stays. Orchestrated workers return `already_satisfied` under their dispatch contract instead.

## Independent review

Independently review every nonempty solo change and the complete feature integration.
Use the installed `code-review` instructions for both axes, including the full smell baseline.

Commit all intended changes and use a clean review checkout at the tested `review_sha` (the
wave's `head_sha`), set up as [Review workspace](#review-workspace) describes.
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
context-only requirements for interpretation, not additional work. Instruct it to report by
class. When a finding is one instance of a pattern, such as one fact restated at several sites
or a parser that reads input differently from the runtime it imitates, the reviewer names the
pattern and the search that finds every instance. A finding that asks for a fix because of how a
browser or other runtime behaves includes a probe or a doctored artifact that shows the
behavior; without one, the reviewer reports it as unconfirmed.

Choose review depth from the complete diff, recording the reason:

- **Trivial solo change:** spelling, formatting, or comments whose meaning and behavior are
  unchanged. Load `code-review` and pass both prompts and the full baseline to one fresh reviewer
  independent of the author. Instruct it to return separate Standards and Spec reports without
  spawning children. This is a local adaptation of the skill's normal two-agent dispatch.
- **All other changes:** separate Standards and Spec reviewers in the [Check wave](#check-wave).
  Use this route for behavioral changes, uncertainty, and every feature integration. Diff size
  alone does not qualify a change as trivial. Changes to agent instructions, acceptance
  criteria, configuration, dependencies, CI, migrations, or APIs use this route even when the
  diff is small.

Both routes inspect the whole initial diff with the same pinned commits, authoritative scope,
standards, and baseline. Keep reports, finding counts, dispositions, and the worst issue separate
by axis. Baseline smells are judgement calls; repo rules take precedence. Count all reviewers
against capacity.

Accept actionable in-scope findings for [Fix rounds](#fix-rounds). A finding that identifies a
factual inaccuracy in prose (docs, comments, PR body, commit text) is a defect and gets fixed
whatever severity label the reviewer gave it; "optional" covers preferences only. Record a
reason for dismissing or deferring optional suggestions under their original axis. A preference
alone does not require a refactor, and optional preferences do not extend the rounds.

## Final review

The final review is one quality pass by a worker that wrote none of the change and sees none
of the other reviews. The coordinator dispatches it once per run, in the
[Check wave](#check-wave). The trivial solo route and orchestrated ticket dispatches skip it;
record the reason. Feature runs take it once at integration, under implement-feature's
Integration review.

Brief the reviewer with the run directory, the main checkout path (`REPO`), the reviewed
`head_sha` (or integration SHA) to check out, `base_sha` as the fixed point, the absolute path
to the scope file (`ticket-snapshot.md` or `scope.md`) so lean findings respect what the ticket
requires, and the instruction to run the installed `ponytail-review` skill on `git diff <base_sha>...HEAD`.
Add the two reporting instructions from [Independent review](#independent-review): report by
class with the search for every instance, and back each runtime claim with a probe or a
doctored artifact. The reviewer follows
[Review workspace](#review-workspace). The pass is blind:
those are its only inputs, and it receives no Standards or Spec report, findings artifact, or
disposition. The brief supplies the run directory only as a place to write. An
unavailable `ponytail-review` skips the gate; the findings artifact and PR body record "final
review not run: skill missing" and readiness is unaffected.

The coordinator decides every finding and records the disposition itself, with no user prompt:

- **Must fix:** fix in this PR, including defects in pre-existing code the diff did not cause.
  This is the exception named by the scope rule at the top of SKILL.md's Workflow; the PR body
  names each such fix under Evidence.
- **Should fix:** fix in this PR, including lean refactors (delete, merge, split) and a
  missing test for changed behaviour.
- **Nice to have:** record and leave; list under deferred cleanup with the follow-up offer.
- **Oversized fix:** a must-fix or should-fix whose fix would be larger than the reviewed diff
  (`base_sha...HEAD`) is escalated through `open_questions` with the proposed fix and its size. The PR stays
  draft and the stop comment names it.

Accepted fixes join the wave's one fix brief under [Fix rounds](#fix-rounds).

Record a `## Final review` section in the findings artifact: each finding with its tier,
disposition (fixed, open, escalated, recorded), fixing commit, and a one-line reason for
anything not fixed. The PR body's Evidence states the tier counts and outcomes. An escalated
finding keeps the PR draft until the user answers, whatever the door. Nice-to-haves never block
readiness.

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
Missing required checks keep the PR draft; a repo whose workflow files and `gh run list` for the
head SHA show no CI has no required checks, and Evidence says so. Explain rollback cost and affected consumers in
Merge Danger using the actual change. Its Door line states the recorded [Door](#door) and its
reason. Under it, list each finding the round cap left open, with its tier and the reviewer's
evidence, and offer a follow-up issue for them. Replace stale draft claims on resume.

## Solo finalization

The implementing worker owns this section, in two parts. Every dispatch this file sends it
(fix rounds, a prose-only fix, late fixes, Publish, Ready) resumes it, replacing
orchestrator-mode's one-resume rule. Where the harness cannot resume it, or a class escalation
has replaced it, the replacing worker, briefed by artifact path, takes these dispatches.

**Publish.** After the last fix round, push the checked head (`final_sha`) and confirm the
remote tip. Author the PR body from the coordinator's brief, which carries the door with its
reason and each finding's axis, tier, disposition, fixing commit, and, where it stays open, the
reviewer's evidence. Mark the closing verification pending. Update or reuse the ticket's draft
PR with the closing line chosen in [PR body](#pr-body) and the observed results. After the
push, run `gh pr checks <PR> --watch`; a failing required CI check is a defect, and a pending
one counts as unexecuted evidence. Its fix is a [late fix](#fix-rounds).
Return the pushed head, the PR URL, and the check results. The coordinator dispatches
[Closing verification](#closing-verification) beside this part.

**Ready.** Once the coordinator holds a passing closing verification, required CI checks, and
review outcomes that cover the same remote tip, it sends this worker the [Door](#door) outcome:
mark a two-way door's PR ready, and leave a one-way door's PR draft until the user's go-ahead.
The worker first writes the closing verification's result, any drift, and any late fix into
the body's Evidence.
The report lists temporary code, post-merge manual steps, and deferred cleanup, and offers a
follow-up issue with acceptance criteria for them.
Post and record the stop comment with the PR URL and outcome, then report them to the user.
Leave merging to the human. A blocked or denied publication step preserves the branch and body,
keeps the PR a draft, and takes the stop path with a stop comment that states what remains.
