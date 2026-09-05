---
name: implement-ticket
argument-hint: "[ticket-number]"
description: 'Implement a ticket (GitHub issue) end-to-end on a ticket branch and open a PR, with tests and a runtime smoke check that the app still works before declaring done. Use when the user says "implement ticket #N", "implement issue #N", "implement the next ready ticket", or otherwise asks to take a ticket from open to PR.'
---

# Implement Ticket

Take a ticket (on GitHub: an issue) from open → ticket branch → working code → green tests + runtime smoke check → PR ready with a Verification plan.

## Inputs

- Ticket number (optional, e.g. `#8` or `8`). If omitted, auto-select (see step 0).
- Optional: target repo (defaults to the current `gh` remote).

## Orchestrated dispatch

For a feature dispatch, read [references/orchestrated.md](references/orchestrated.md)
first. It owns the pinned-base, resume, lifecycle, no-PR, and return contracts; the
implementation and verification steps below still apply. Solo runs skip that reference.

## Workflow

**Implement what the ticket asks, at the scope it asks for.** Adjacent bugs, drive-by refactors, and missing tests outside the acceptance criteria get reported in the PR body (or `open_questions` under an orchestrated dispatch), not fixed here.

**Make the smallest change that solves the ticket.** Prefer deletion over addition, keep the call hierarchy flat, and put each decision in one place; a diff a maintainer would find exhausting is the wrong solution. The `principle-laziness-protocol` skill, when installed, is the full protocol; follow it.

**Before writing any prose published to git or GitHub (commit messages, PR titles and bodies, ticket comments, the Summary, Test plan, and Verification plan), invoke the `technical-writing` and `unslop` skills if installed, and write that prose to their standard.** This governs prose the skill authors, not the ticket body it reads; reuse guidance already loaded; explicit user and environment skill requirements still apply. Baked-in minimum either way: plain words, active voice, one thought per sentence, and no em dashes (use a comma, colon, or parentheses, or rewrite the sentence).

**Use configured execution permissions.** Run commands normally. If a necessary command
is blocked, use the available scoped escalation and report a denial accurately. The task's
existing authorization governs external mutations. Issue comments require explicit messaging
authorization; otherwise keep the proposed findings in a local artifact. Record which
assignments and labels this run changes and alter only those on a stop path.

### 0. Resolve the ticket number

If the user provided a number, use it as `<N>`. Otherwise auto-pick the **lowest-numbered** open `ready-for-agent` ticket, **excluding specs**, unassigned and free of stop-condition labels, with the query in [references/auto-pick.md](references/auto-pick.md) (read it first: it paginates before selection). If it returns a ticket, announce the pick (number + title) before proceeding; if the user declines it, exclude that number and take the next survivor. Never re-run the identical query expecting a different answer. If it returns `null` or nothing, stop and ask: do not guess, and do not implement a spec directly (specs get broken into tickets first, e.g. via a `to-tickets` skill).

### 1. Read the ticket and claim it

`gh issue view <N> --comments`: read the body AND comments. Note title, acceptance criteria, blocked-by links, and scope labels (`needs-info`, `wontfix`, etc. → stop and ask, with one exception: `needs-info` applied by a prior agent's own stop (its findings comment is on the ticket) when the user explicitly named this ticket resolves that prior stop; defer any label change until ownership and workspace preflight pass). `awaiting-verification` is not a stop: a prior run's PR awaits human verification; say so when announcing, proceed, and let step 8's re-authored Verification plan supersede the old one (under an orchestrated dispatch, mention it in `open_questions` prefixed `pre-existing:` instead: the orchestrator's feature-level plan is what supersedes it). Before claiming, confirm it is a **ticket, not a spec**: a body with no concrete acceptance criteria that reads as a multi-ticket document (solution/scope sections, user stories, several independent deliverables) is a spec the auto-pick regex missed. Stop and ask. If assigned to someone else, surface that before any issue mutation. An assignment to
self is advisory, not an exclusive lock. Complete the base and workspace preflight first;
then claim within existing authorization and record whether this run added the assignment.
Comment the chosen branch only when messaging is authorized.

### 2. Pick a base branch

- Default base and `pr_base`: the repo's default branch (`gh repo view --json defaultBranchRef`).
- **Detecting blocked-by:** check GitHub's native issue-dependency (blocked-by) data first (`gh api` dependencies endpoint, sub-issue parentage is not a blocking relation), then **also** scan the body: a `## Blocked by` section, lines like `Blocked by #12` / `Depends on #12`, task-list references inside a dependency section, or a `blocked` label requiring investigation, either source alone may carry an edge.
- If open blockers have branches, choose a base containing every required blocker tip. For a stacked ticket, record the blocker branch as the PR target and explain the dependency. Independent blocker branches need a combined authorized base or a surfaced dependency decision; selecting one does not satisfy the others. Record both the immutable `base_sha` and explicit `pr_base`.
- If the blocker has **no branch yet**, stop and surface to the user. Don't branch off nothing or implement the blocker yourself.

### 3. Create the ticket branch

Check applicable branch conventions and `git status --porcelain`. Preserve unrelated dirty
work in place and use an isolated checkout if needed. Ask only about required uncommitted
inputs or overlapping edits whose ownership is unclear; do not automatically stash or reset.
Fetch the intended base and pin `base_sha`. Use the environment's branch prefix, keeping
`ticket-<N>-<slug>` in the name. Recognize older `feat/ticket-<N>-*` and `feat/issue-<N>-*`
branches when investigating resumes. Create the branch from the SHA, not a moving branch ref.

For a prior attempt, read its findings and compare local and remote tips before choosing it.
Multiple candidates require evidence of which attempt belongs to this task. Preserve the
existing WIP tip; work on a fresh attempt branch before rebasing onto `base_sha` when rewriting
a pushed branch is not already authorized. Abort an unsuccessful rebase explicitly. Keep
its saved tip and findings available if rebuilding from the base is necessary. Report the
actual branch and preservation state, including any push failure.

### 4. Explore before editing

Grep/search for the modules the ticket touches. Read `AGENTS.md`, `CONTEXT.md`, and ADRs in `docs/adr/` for invariants. Match existing patterns; don't introduce new infrastructure (test framework, linter config) unless the ticket asks for it.

Identify the **feedback-loop commands**: the type-checker/linter (e.g. `mypy`, `pyright`, `ruff`) and the **test command** (e.g. `pytest`), plus the **run command** (`AGENTS.md`, `pyproject.toml`, `Makefile`, `package.json` scripts, CI workflows, `docker-compose.yml`). Run the configured type-check/lint and test commands on the pinned clean `base_sha` before editing, or reuse an original baseline with that proven SHA. On resume, use a separate checkout for this base check; failures on the WIP branch remain separate and cannot become baseline exemptions. Record commands, checked SHA, and original failures.

Done when you have: (a) the type-check and test commands, (b) the run command, and (c) recorded baseline results for all configured checks. Mark absent commands as absent, not passing.

### 5. Implement

Before choosing a path: an acceptance criterion that is subjective or unverifiable ("looks right", "feels fast") is the **ambiguous-acceptance-criteria stop condition, whichever kind of work the ticket is**. Untestable is not the same as unspecified. A criterion tied to a concrete reference artifact (design mockup, screenshot, spec doc) is untestable but specified: take the "everything else" path and record the manual comparison against the artifact in the PR body. The stop is per criterion: name the ambiguous ones in your question rather than declaring the whole ticket ambiguous. Then **recognise what kind of work the ticket is**; it decides how you build:

- **Testable backend work** (a service, pipeline, API, library function with a working test suite and acceptance criteria that describe verifiable behaviour): build it in **tracer bullets**: the **red → green** loop, one test at a time. One failing test (**red**), then the minimal code to pass it (**green**). Don't write all the tests up front; each test responds to what the last one taught you. Refactoring is not part of the loop. It belongs to the step 8 review pass. Follow the `tdd` skill for the full loop. The `tdd` skill expects tests at **pre-agreed seams**: with no user in the loop, the ticket is that agreement: place tests at the seams its acceptance criteria and the existing test layout imply. If no sensible seam exists for a criterion, treat it as ambiguous acceptance criteria (a stop condition), not a licence to test implementation details.
- **Everything else**: frontend code (the suite doesn't cover it), exploratory data analysis, notebooks, one-off scripts, or any change where no test can pin the behaviour: implement directly and lean on the step 6 feedback loop and the step 7 smoke check instead. Mixed tickets split by part: tracer bullets for the testable seams, direct implementation for the rest. Say which path you took.

Throughout:

- Open a **draft PR within the first 1–2 commits**: `git push -u origin HEAD` then `gh pr create --draft --base <pr_base> --head <ticket_branch> --title "<title>" --body "Closes #<N>. <one-paragraph plan>"`. Use the repo's PR template (`.github/pull_request_template.md`) if one exists, keeping the `Closes #<N>` line. If `gh pr create` fails (permissions, branch protection), keep committing locally and surface the error at the end. Don't abort. If an open PR already exists for this branch (a prior attempt), update its body, stripping any stale stop-reason text, instead of creating a new one.
- Keep the loop **tight** while building: type-check and run the single test file you're touching as you go; save the full suite for step 6.
- Keep commits scoped and conventional (`feat:`, `fix:`, `test:`, …).

### 6. Feedback loop: types + tests (REQUIRED before marking ready)

Run the **type-checker/linter, then the test suite** from step 4, and loop until both are clean: type-check → fix → test → fix. Everything green at baseline must still be green; new failures and new type errors are yours to fix. If acceptance criteria describe verifiable behaviour and the project has a test suite, add tests covering it, matching existing style. Never add a type-checker or test framework to a project that has none; if either is absent, note it and rely on the step 7 smoke check.

### 7. Runtime smoke check (REQUIRED before marking ready)

**Verify the changed artifact before declaring done.** Pick the applicable branch:

- **Long-running app (server/web):** start it in the background with the run command; wait for the ready signal (port listening, "compiled successfully", health 200); exercise the changed behavior through a relevant endpoint or UI; read the last ~50 log lines for tracebacks/warnings introduced by your change; stop it cleanly.
- **CLI / library / script / pipeline (no port):** run the entrypoint once with a representative invocation: `<cli> --help` plus one real subcommand, import the package and call the changed API, or execute the flow once against safe inputs. Confirm exit code 0 and no new tracebacks.

- **Docs or configuration with no runnable entrypoint:** run the relevant validator and inspect the rendered or consumed artifact. Record why runtime execution does not apply.

Allocate separate ports and test resources for parallel workers, or serialize shared-state checks. Missing credentials or tools are blocked checks, not passes. Fix failures and retry proportionately; preserve a concrete blocker when further authorized progress is unavailable.

### 8. Review, then finalise the PR

- Read the full `git diff <base_sha>...HEAD` yourself before marking ready, and fix what it surfaces: including refactoring the new code deferred from step 5 (adjacent-code refactors stay reported-only, per the scope rule). Reach for the `code-review` skill only when the diff is large or touches subsystems you didn't explore in step 4: one pass, and no review agents beyond it. A refactor re-enters step 6 (and step 7 when it touched a runtime path): green again before you push.
- Push final commits; update the PR body with a short **Summary** and **Test plan** (what you ran in steps 6–7, what you observed). Size both to the change: no filler sections, no restating the diff.
- Author the **Verification plan** (see `CONTEXT.md`) as its own PR-body section: at most **three scenarios**, each earning its place only because automated tests could not have covered it (UI, data shape, an integration). If more qualify, keep the three with the highest cost of being wrong; drop the rest silently: no traceability list, the Test plan already records what ran. Optionally one line up top, "Run against <env>, ~N min", omitted when obvious. Each scenario is numbered copy-paste-ready **Steps** (preconditions and cleanup fold in as steps) plus one **What you should see** line. Execute every step yourself before publishing: the observed output becomes the what-you-should-see text, orienting the human's judgement rather than asserting pass/fail; a step you cannot reach is authored anyway, flagged "not executed, requires <env>". If executing a step surfaces something evidently broken, that is a steps 6–7 failure: fix within the authorized scope, then re-author. Nothing qualifies (docs-only, config tweak, fully covered by tests) → a one-line waiver, "No human verification beyond code review: <reason>", never a silently missing section. On a resume, replace any prior plan section rather than appending. Then apply `awaiting-verification` to the ticket (`gh label create` it first if absent; skip when the plan is a waiver). Removing it is the human's, never yours.
- `gh pr ready`, then close out leading with the outcome: PR URL and what landed in the first sentence, detail after. Do **not** merge; leave that to the human.

## Stop conditions

Stop and surface to the user (do not improvise) if:

- The ticket is labelled `needs-info`, `wontfix`, or `needs-triage`, or is already assigned to someone else.
- Acceptance criteria are ambiguous or contradict the codebase's invariants.
- The ticket is blocked by a ticket/PR that has no branch yet.
- Required uncommitted inputs or overlapping work cannot be used safely without a user decision.
- A required check is blocked and diagnosis or a different authorized approach cannot make further useful progress. Repeated identical failures call for a changed approach, not an arbitrary claim of completion.

When stopping, preserve work and report the actual branch, HEAD, worktree path, dirty files,
and push outcome. Push WIP when authorized; a failed push leaves local work that must remain.
Record the failure, attempts, and pending decisions in a local findings artifact. Publish it
only when messaging is authorized. Leave any draft PR open and report its state accurately.
In solo runs, release only a claim this run added; label changes require lifecycle ownership
and existing authorization. In orchestrated runs, the feature coordinator owns the lifecycle.
