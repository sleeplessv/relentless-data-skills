---
name: implement-ticket
argument-hint: "[ticket-number]"
description: 'Implement a ticket (GitHub issue) end-to-end on a feature branch and open a PR, with tests and a runtime smoke check that the app still works before declaring done. Use when the user says "implement ticket #N", "implement issue #N", "implement the next ready ticket", or otherwise asks to take a ticket from open to PR.'
---

# Implement Ticket

Take a ticket (on GitHub: an issue) from open → feature branch → working code → green tests + runtime smoke check → draft PR.

## Inputs

- Ticket number (optional, e.g. `#8` or `8`). If omitted, auto-select (see step 0).
- Optional: target repo (defaults to the current `gh` remote).

## Orchestrated dispatch

When a feature orchestrator (e.g. the `implement-feature` skill) dispatches this skill, its prompt may set these overrides — sanctioned branches of this workflow, not contradictions to argue with:

- **Ticket number is always given** — skip step 0's auto-pick.
- **`base_branch: <integration branch>`** — replaces step 2 entirely; blockers are pre-merged into it, so skip all blocked-by detection. Cut the ticket branch **without checking out the base** (it may be checked out in the main tree or a sibling worktree): `git switch -c feat/ticket-<N>-<slug> <base_branch>` — the shared local ref is already at the tip the orchestrator pushed. `git fetch origin <base_branch>` only if that ref is missing, retrying once on a ref-lock error (parallel siblings fetch too). Never `git switch <base_branch>` itself.
- **`resume_branch: <name>`** — a prior attempt's pushed WIP branch: fetch and switch to it instead of creating one, rebase onto `origin/<base_branch>`, read the findings comment on the ticket, and continue from step 6. If the rebase conflicts, or the base alone already satisfies the ticket (its previously failing tests pass on `origin/<base_branch>` before your changes), abandon the WIP and return `status: already_satisfied` — the orchestrator drops the ticket.
- **`open_pr: false`** — skip every PR step (the draft PR in step 5, the finalise/`gh pr ready` parts of step 8). Step 8's review becomes a direct read of `git diff <base_branch>...HEAD` (no `code-review` sub-agent fan-out — the orchestrator runs the authoritative review). Return `branch`, `worktree_path`, `files_changed`, `tests_run`, and `open_questions` instead of a PR URL; on a stop condition return `status: failed`, the pushed WIP `branch`, `worktree_path`, and `root_cause`.
- **"Stop and ask" remaps** — you cannot reach the user: stop, put the question in `open_questions`, and return; the orchestrator asks.

Everything else — claiming (step 1), environment setup before the baseline (a fresh worktree starts without installed dependencies — run the project's install command first), the types+tests loop, the smoke check, and the WIP push + findings comment on failure — is unchanged.

## Workflow

**No em dashes (—) in anything published to git or GitHub** — commit messages, PR titles and bodies, ticket comments. Use a comma, colon, or parentheses, or rewrite the sentence.

**Run network commands outside the sandbox.** Run every `gh` and `git fetch`/`pull`/`push` with sandboxing disabled — a sandboxed shell blocks network and fails with a misleading DNS/connection error; on a connection error, suspect the sandbox first.

### 0. Resolve the ticket number

If the user provided a number, use it as `<N>`. Otherwise auto-pick the **lowest-numbered** open `ready-for-agent` ticket, **excluding specs** (spec documents, not tickets — filter primarily by the `spec` label, plus the legacy `prd` label, with the body-heading regex as fallback for older specs):

```bash
gh issue list --state open --label ready-for-agent --json number,title,body,labels \
  --jq 'sort_by(.number)
        | map(select([.labels[].name] | any(. == "spec" or . == "prd") | not))
        | map(select(.body | test("(?m)^## (Problem Statement|User Stories|Implementation Decisions)") | not))
        | .[0]'
```

If it returns a ticket, announce the pick (number + title) before proceeding. If it returns `null` or nothing, stop and ask — do not guess, and do not implement a spec directly (specs get broken into tickets first, e.g. via a `to-tickets` skill).

### 1. Read the ticket and claim it

`gh issue view <N> --comments` — read the body AND comments. Note title, acceptance criteria, blocked-by links, and scope labels (`needs-info`, `wontfix`, etc. → stop and ask). Then claim it so two agents don't work it simultaneously: `gh issue edit <N> --add-assignee @me` plus a brief "starting work, branch `feat/ticket-<N>-<slug>`" comment. If already assigned to someone else, stop and ask.

### 2. Pick a base branch

- Default base: the repo's default branch (`gh repo view --json defaultBranchRef`).
- **Detecting blocked-by:** check GitHub's native issue-dependency data first (`gh api` — sub-issues and blocked-by relationships), then fall back to body/comment lines like `Blocked by #12` / `Depends on #12`, task-list references, or a `blocked` label.
- If blocked by a ticket/PR whose branch exists but isn't merged, branch off that branch and note it in the PR description (reviewer rebases onto main once the blocker lands).
- If the blocker has **no branch yet**, stop and surface to the user — don't branch off nothing or implement the blocker yourself.

### 3. Create the feature branch

First run `git status --porcelain`. Any output → **stop and ask** (stash, commit, or abort) — never silently drag uncommitted changes onto the new branch.

Check `AGENTS.md` / `CONTRIBUTING.md` for a branch naming convention before guessing. Default:

```bash
git switch <base> && git pull --ff-only
git switch -c feat/ticket-<N>-<short-kebab-slug>
```

The `ticket-<N>` prefix is load-bearing for branch→ticket tooling; keep it, and treat the legacy `issue-<N>` prefix as equivalent when detecting existing branches. Slug = kebab of the ticket title, ≤5 words, drop filler.

### 4. Explore before editing

Grep/search for the modules the ticket touches. Read `AGENTS.md`, `CONTEXT.md`, and ADRs in `docs/adr/` for invariants. Match existing patterns; don't introduce new infrastructure (test framework, linter config) unless the ticket asks for it.

Identify the **feedback-loop commands** — the type-checker/linter (e.g. `mypy`, `pyright`, `ruff`) and the **test command** (e.g. `pytest`) — plus the **run command** (`AGENTS.md`, `pyproject.toml`, `Makefile`, `package.json` scripts, CI workflows, `docker-compose.yml`). Run the test suite **once now, before editing**, to baseline — note any pre-existing failures so you don't mistake them for regressions later.

Done when you have: (a) the type-check and test commands, (b) the run command, and (c) a recorded list of any pre-existing test failures from the baseline run.

### 5. Implement

First **recognise what kind of work the ticket is** — it decides how you build:

- **Testable backend work** (a service, pipeline, API, library function with a working test suite and acceptance criteria that describe verifiable behaviour): build it in **tracer bullets** — **red → green → refactor**, one test at a time. One failing test (**red**), the minimal code to pass it (**green**), then **refactor**. Don't write all the tests up front; each test responds to what the last one taught you. Follow the `tdd` skill for the full loop.
- **Everything else** — frontend code (the suite doesn't cover it), exploratory data analysis, notebooks, one-off scripts, or any change where no test can pin the behaviour: implement directly and lean on the step 6 feedback loop and the step 7 smoke check instead. Say which path you took.

Throughout:

- Open a **draft PR within the first 1–2 commits**: `git push -u origin HEAD` then `gh pr create --draft --title "<title>" --body "Closes #<N>. <one-paragraph plan>"`. Use the repo's PR template (`.github/pull_request_template.md`) if one exists, keeping the `Closes #<N>` line. If `gh pr create` fails (permissions, branch protection), keep committing locally and surface the error at the end — don't abort.
- Keep the loop **tight** while building: type-check and run the single test file you're touching as you go; save the full suite for step 6.
- Keep commits scoped and conventional (`feat:`, `fix:`, `refactor:`, …).

### 6. Feedback loop: types + tests (REQUIRED before marking ready)

Run the **type-checker/linter, then the test suite** from step 4, and loop until both are clean: type-check → fix → test → fix. Everything green at baseline must still be green; new failures and new type errors are yours to fix. If acceptance criteria describe verifiable behaviour and the project has a test suite, add tests covering it — matching existing style. Never add a type-checker or test framework to a project that has none; if either is absent, note it and rely on the step 7 smoke check.

### 7. Runtime smoke check (REQUIRED before marking ready)

**Do not declare done until you've observed the project actually run without errors.** Pick the branch matching the project type:

- **Long-running app (server/web):** start it in the background with the run command; wait for the ready signal (port listening, "compiled successfully", health 200); hit a basic endpoint; read the last ~50 log lines for tracebacks/warnings introduced by your change; stop it cleanly.
- **CLI / library / script / pipeline (no port):** run the entrypoint once with a representative invocation — `<cli> --help` plus one real subcommand, import the package and call the changed API, or execute the flow once against safe inputs. Confirm exit code 0 and no new tracebacks.

If it fails, **fix and retry** — don't push the failure onto the reviewer. Loop until green.

### 8. Review, then finalise the PR

- Review the diff before marking ready: run the `code-review` skill over the branch's changes if it's installed, otherwise read the full `git diff <base>...HEAD` yourself. Fix what the review surfaces.
- Push final commits; update the PR body with a short **Summary** and **Test plan** (what you ran in steps 6–7, what you observed).
- `gh pr ready`, then report the PR URL. Do **not** merge — leave that to the human.

## Stop conditions

Stop and surface to the user (do not improvise) if:

- The ticket is labelled `needs-info`, `wontfix`, or `needs-triage`, or is already assigned to someone else.
- Acceptance criteria are ambiguous or contradict the codebase's invariants.
- The ticket is blocked by a ticket/PR that has no branch yet.
- The working tree is dirty when it's time to branch.
- Tests or the smoke check still fail after **three fix attempts** at the same root cause.

When stopping mid-implementation, don't discard the work: push the WIP branch and comment your findings (what failed, what you tried) on ticket `<N>` so the next attempt starts from there.
