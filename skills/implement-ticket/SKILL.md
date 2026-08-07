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

When a feature orchestrator (e.g. the `implement-feature` skill) dispatches this skill, its prompt may set these overrides — sanctioned branches of this workflow, not contradictions to argue with:

- **Ticket number is always given** — skip step 0's auto-pick.
- **`base_branch: <integration branch>`** — replaces step 2 and step 3's branch-cut commands entirely; blockers are pre-merged into it, so skip all blocked-by detection. Cut the ticket branch **without checking out the base** (it may be checked out in the main tree or a sibling worktree): `git switch -c feat/ticket-<N>-<slug> <base_branch>` — the shared local ref is already at the tip the orchestrator pushed. `git fetch origin <base_branch>` only if that ref is missing, retrying once on a ref-lock error (parallel siblings fetch too). Never `git switch <base_branch>` itself. Step 3's dirty-tree check and prior-attempt detection still apply: a `feat/ticket-<N>-*` branch already on origin with no `resume_branch` given → treat it as `resume_branch` rather than colliding with it on push.
- **`resume_branch: <name>`** — a prior attempt's pushed WIP branch. First test whether the base alone already satisfies the ticket: on a detached checkout of `origin/<base_branch>` (`git switch --detach`, before touching the WIP), run the prior attempt's failing tests — if at least one exists and they pass, return `status: already_satisfied` (the orchestrator drops the ticket); an empty test set proves nothing. Otherwise fetch and switch to the WIP branch and rebase onto `origin/<base_branch>`; if the rebase conflicts, abandon the WIP and reimplement fresh from `<base_branch>` (the findings comment is still context) — a conflict is never `already_satisfied`. Claim per step 1 (a `needs-info` label a prior attempt's own stop applied is not a stop condition — swap it back to `ready-for-agent`), read the findings comment, and continue from wherever it says the prior attempt stopped — finish step 5's implementation before step 6's loop if that is where it died.
- **`open_pr: false`** — skip every PR step (the draft PR in step 5, the finalise/`gh pr ready` parts of step 8, and step 8's Verification plan and its `awaiting-verification` label — the orchestrator authors the feature-level plan and labels the spec). Step 8's review becomes a direct read of `git diff <base_branch>...HEAD` — **still fix what it surfaces, including the refactors deferred from step 5** (the orchestrator's review is authoritative but is not your refactoring pass; no `code-review` sub-agent fan-out). Push the branch after the final commit on the success and stop paths alike. Return `status: success` plus the pushed `branch`, `worktree_path`, `files_changed`, `tests_run` (including the smoke-check result), and `open_questions` instead of a PR URL; on a stop condition return `status: failed`, the pushed WIP `branch`, `worktree_path`, and `root_cause` (omit `branch`/`worktree_path` when stopping before the branch is cut). `status` is always exactly one of `success` / `already_satisfied` / `failed`.
- **"Stop and ask" remaps** — you cannot reach the user: stop, return `status: failed` with the question in `open_questions` and as `root_cause`; the orchestrator asks.

Everything else — claiming (step 1), environment setup before the baseline (the orchestrator dispatches you inside a fresh worktree, which starts without installed dependencies — run the project's install command after any branch work and before the step 4 baseline, and report the worktree's path as `worktree_path`), the types+tests loop, the smoke check, and the WIP push + findings comment on failure — is unchanged. One stop-path exception: leave the assignment and labels untouched (no `needs-info` swap) — the orchestrator owns the ticket's lifecycle and retries.

## Workflow

**Implement what the ticket asks, at the scope it asks for.** Adjacent bugs, drive-by refactors, and missing tests outside the acceptance criteria get reported in the PR body (or `open_questions` under an orchestrated dispatch), not fixed here.

**No em dashes (—) in anything published to git or GitHub** — commit messages, PR titles and bodies, ticket comments. Use a comma, colon, or parentheses, or rewrite the sentence.

**Run network commands outside the sandbox.** Run every `gh` and `git fetch`/`pull`/`push` with sandboxing disabled — a sandboxed shell blocks network and fails with a misleading DNS/connection error; on a connection error, suspect the sandbox first.

### 0. Resolve the ticket number

If the user provided a number, use it as `<N>`. Otherwise auto-pick the **lowest-numbered** open `ready-for-agent` ticket, **excluding specs** (spec documents, not tickets). The body-heading regex is the primary spec detector — current `to-spec` puts `ready-for-agent` on the spec itself and applies no `spec` label; the `spec`/`prd` labels are extra hints some repos carry:

```bash
gh issue list --state open --label ready-for-agent --limit 200 --json number,title,body,labels,assignees \
  --jq 'sort_by(.number)
        | map(select((.assignees | length) == 0))
        | map(select([.labels[].name] | any(. == "spec" or . == "prd" or . == "needs-info" or . == "wontfix" or . == "needs-triage" or . == "blocked") | not))
        | map(select(((.body // "") | gsub("(?s)```.*?```"; "")) | test("(?im)^#{2,3} (Problem Statement|User Stories|Implementation Decisions|Testing Decisions|Out of Scope)") | not))
        | .[0]'
```

The inline `(?im)` flags are load-bearing (line-anchored and case-insensitive in jq — the `; "m"` flag form does not work), the `gsub` strips fenced code blocks so a ticket *quoting* a spec template is not excluded, and `--limit` matters: the default 30 newest issues can miss the lowest-numbered ticket entirely. Assigned tickets and stop-condition labels are filtered up front so step 1 doesn't immediately stop on them. If it returns a ticket, announce the pick (number + title) before proceeding; if the user declines it, exclude that number and take the next survivor — never re-run the identical query expecting a different answer. If it returns `null` or nothing, stop and ask — do not guess, and do not implement a spec directly (specs get broken into tickets first, e.g. via a `to-tickets` skill).

### 1. Read the ticket and claim it

`gh issue view <N> --comments` — read the body AND comments. Note title, acceptance criteria, blocked-by links, and scope labels (`needs-info`, `wontfix`, etc. → stop and ask — with one exception: `needs-info` applied by a prior agent's own stop (its findings comment is on the ticket) when the user explicitly named this ticket is the human weighing in — swap it back to `ready-for-agent` and proceed). `awaiting-verification` is not a stop: a prior run's PR awaits human verification — say so when announcing, proceed, and let step 8's re-authored Verification plan supersede the old one (under an orchestrated dispatch, mention it in `open_questions` instead — the orchestrator's feature-level plan is what supersedes it). Before claiming, confirm it is a **ticket, not a spec**: a body with no concrete acceptance criteria that reads as a multi-ticket document (solution/scope sections, user stories, several independent deliverables) is a spec the step 0 regex missed — stop and ask. Then claim it so two agents don't work it simultaneously: `gh issue edit <N> --add-assignee @me` plus a brief "starting work, branch `feat/ticket-<N>-<slug>`" comment. If already assigned to someone else, stop and ask; already assigned to you from a prior attempt → proceed.

### 2. Pick a base branch

- Default base: the repo's default branch (`gh repo view --json defaultBranchRef`).
- **Detecting blocked-by:** check GitHub's native issue-dependency (blocked-by) data first (`gh api` dependencies endpoint — sub-issue parentage is not a blocking relation), then **also** scan the body: a `## Blocked by` section, lines like `Blocked by #12` / `Depends on #12`, task-list references, or a `blocked` label — either source alone may carry an edge.
- If blocked by a ticket/PR whose branch exists but isn't merged, branch off that branch and note it in the PR description (reviewer rebases onto main once the blocker lands).
- If the blocker has **no branch yet**, stop and surface to the user — don't branch off nothing or implement the blocker yourself.

### 3. Create the ticket branch

First run `git status --porcelain`. Any output → **stop and ask** (stash, commit, or abort) — never silently drag uncommitted changes onto the new branch.

Check `AGENTS.md` / `CONTRIBUTING.md` for a branch naming convention before guessing. Default:

```bash
git switch <base> && git pull --ff-only
git switch -c feat/ticket-<N>-<short-kebab-slug>
```

The `ticket-<N>` prefix is load-bearing for branch→ticket tooling; keep it, and treat the legacy `issue-<N>` prefix as equivalent when detecting existing branches. Slug = kebab of the ticket title, ≤5 words, drop filler. If a `feat/ticket-<N>-*` (or legacy) branch already exists locally or on origin, it is a prior attempt: switch to it, rebase onto the base, read the findings comment on the ticket, and resume from where it stopped instead of branching fresh, noting in your claim comment that this is a resume.

### 4. Explore before editing

Grep/search for the modules the ticket touches. Read `AGENTS.md`, `CONTEXT.md`, and ADRs in `docs/adr/` for invariants. Match existing patterns; don't introduce new infrastructure (test framework, linter config) unless the ticket asks for it.

Identify the **feedback-loop commands** — the type-checker/linter (e.g. `mypy`, `pyright`, `ruff`) and the **test command** (e.g. `pytest`) — plus the **run command** (`AGENTS.md`, `pyproject.toml`, `Makefile`, `package.json` scripts, CI workflows, `docker-compose.yml`). Run the test suite **once now, before editing**, to baseline — note any pre-existing failures so you don't mistake them for regressions later.

Done when you have: (a) the type-check and test commands, (b) the run command, and (c) a recorded list of any pre-existing test failures from the baseline run.

### 5. Implement

Before choosing a path: an acceptance criterion that is subjective or unverifiable ("looks right", "feels fast") is the **ambiguous-acceptance-criteria stop condition, whichever kind of work the ticket is** — untestable is not the same as unspecified. A criterion tied to a concrete reference artifact (design mockup, screenshot, spec doc) is untestable but specified: take the "everything else" path and record the manual comparison against the artifact in the PR body. The stop is per criterion — name the ambiguous ones in your question rather than declaring the whole ticket ambiguous. Then **recognise what kind of work the ticket is** — it decides how you build:

- **Testable backend work** (a service, pipeline, API, library function with a working test suite and acceptance criteria that describe verifiable behaviour): build it in **tracer bullets** — the **red → green** loop, one test at a time. One failing test (**red**), then the minimal code to pass it (**green**). Don't write all the tests up front; each test responds to what the last one taught you. Refactoring is not part of the loop — it belongs to the step 8 review pass. Follow the `tdd` skill for the full loop. The `tdd` skill expects tests at **pre-agreed seams**: with no user in the loop, the ticket is that agreement — place tests at the seams its acceptance criteria and the existing test layout imply. If no sensible seam exists for a criterion, treat it as ambiguous acceptance criteria (a stop condition), not a licence to test implementation details.
- **Everything else** — frontend code (the suite doesn't cover it), exploratory data analysis, notebooks, one-off scripts, or any change where no test can pin the behaviour: implement directly and lean on the step 6 feedback loop and the step 7 smoke check instead. Mixed tickets split by part: tracer bullets for the testable seams, direct implementation for the rest. Say which path you took.

Throughout:

- Open a **draft PR within the first 1–2 commits**: `git push -u origin HEAD` then `gh pr create --draft --title "<title>" --body "Closes #<N>. <one-paragraph plan>"`. Use the repo's PR template (`.github/pull_request_template.md`) if one exists, keeping the `Closes #<N>` line. If `gh pr create` fails (permissions, branch protection), keep committing locally and surface the error at the end — don't abort. If an open PR already exists for this branch (a prior attempt), update its body — stripping any stale stop-reason text — instead of creating a new one.
- Keep the loop **tight** while building: type-check and run the single test file you're touching as you go; save the full suite for step 6.
- Keep commits scoped and conventional (`feat:`, `fix:`, `test:`, …).

### 6. Feedback loop: types + tests (REQUIRED before marking ready)

Run the **type-checker/linter, then the test suite** from step 4, and loop until both are clean: type-check → fix → test → fix. Everything green at baseline must still be green; new failures and new type errors are yours to fix. If acceptance criteria describe verifiable behaviour and the project has a test suite, add tests covering it — matching existing style. Never add a type-checker or test framework to a project that has none; if either is absent, note it and rely on the step 7 smoke check.

### 7. Runtime smoke check (REQUIRED before marking ready)

**Do not declare done until you've observed the project actually run without errors.** Pick the branch matching the project type:

- **Long-running app (server/web):** start it in the background with the run command; wait for the ready signal (port listening, "compiled successfully", health 200); hit a basic endpoint; read the last ~50 log lines for tracebacks/warnings introduced by your change; stop it cleanly.
- **CLI / library / script / pipeline (no port):** run the entrypoint once with a representative invocation — `<cli> --help` plus one real subcommand, import the package and call the changed API, or execute the flow once against safe inputs. Confirm exit code 0 and no new tracebacks.

If it fails, **fix and retry** — don't push the failure onto the reviewer. Loop until green.

### 8. Review, then finalise the PR

- Read the full `git diff <base>...HEAD` yourself before marking ready, and fix what it surfaces — including refactoring the new code deferred from step 5 (adjacent-code refactors stay reported-only, per the scope rule). Reach for the `code-review` skill only when the diff is large or touches subsystems you didn't explore in step 4 — one pass, and no review agents beyond it.
- Push final commits; update the PR body with a short **Summary** and **Test plan** (what you ran in steps 6–7, what you observed). Size both to the change: no filler sections, no restating the diff.
- Author the **Verification plan** (see `CONTEXT.md`) as its own PR-body section — the walkthrough a human follows to use the delivered change and inspect its data, not a re-run of tests. An **Environment** block up top (where to run it — the environment steps 6–7 used — and estimated time), then per-scenario: **Goal** (which acceptance criterion), **Preconditions/setup**, copy-paste-ready **Steps**, **What you should see**, **Cleanup** if steps mutate anything. Every criterion is either covered by a scenario or listed as "verified by automated tests only, because <reason>". Execute every command/query yourself before publishing — the observed output becomes the what-you-should-see text, orienting the human's judgement rather than asserting pass/fail; a step you cannot reach is authored anyway, flagged "not executed, requires <env>". If executing a step surfaces something evidently broken, that is a steps 6–7 failure: fix within the shared attempt caps, then re-author. Nothing to walk through (docs-only, config tweak) → a one-line waiver, "No human verification beyond code review: <reason>", never a silently missing section. On a resume, replace any prior plan section rather than appending. Then apply `awaiting-verification` to the ticket (`gh label create` it first if absent; skip when the plan is a waiver) — removing it is the human's, never yours.
- `gh pr ready`, then close out leading with the outcome — PR URL and what landed in the first sentence, detail after. Do **not** merge — leave that to the human.

## Stop conditions

Stop and surface to the user (do not improvise) if:

- The ticket is labelled `needs-info`, `wontfix`, or `needs-triage`, or is already assigned to someone else.
- Acceptance criteria are ambiguous or contradict the codebase's invariants.
- The ticket is blocked by a ticket/PR that has no branch yet.
- The working tree is dirty when it's time to branch.
- Tests or the smoke check still fail after **three fix attempts** at the same root cause, or ten fix attempts total across steps 6–7.

When stopping, don't discard work: if a branch was cut, push it as WIP (if the push itself fails, report the local branch name and the push error instead); always comment your findings — what failed, what you tried, plus any earlier deferred errors such as a failed `gh pr create` — on ticket `<N>` so the next attempt starts from there. Leave any draft PR open with the stop reason noted in its body. Then release the claim (solo runs only — under an orchestrated dispatch leave labels and assignment alone): remove your assignment and swap `ready-for-agent` for `needs-info`, so the ticket is neither auto-picked again nor shown as actively worked before a human weighs in; step 1's exception unwinds the swap when the human sends you back.
