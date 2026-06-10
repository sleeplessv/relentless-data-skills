---
name: implement-issue
argument-hint: "[issue-number]"
description: 'Implement a GitHub issue end-to-end on a feature branch and open a PR, with tests and a runtime smoke check that the app still works before declaring done. Use when the user says "implement issue #N", "ship issue #N", "work issue #N", "implement the next issue", "grab the next ready issue", or otherwise asks to take an issue from open to PR.'
---

# Implement Issue

Take a GitHub issue from open → feature branch → working code → green tests + runtime smoke check → draft PR.

## Inputs

- Issue number (optional, e.g. `#8` or `8`). If omitted, auto-select the lowest-numbered open implementation issue labelled `ready-for-agent` (step 0).
- Optional: target repo (defaults to the current `gh` remote).

If no number is given AND no eligible `ready-for-agent` issue exists, ask the user which issue to work on. Do NOT fall back to an unlabelled issue — the label is the explicit signal that triage is done.

## Workflow

**Run network commands outside the sandbox.** Every `gh` call and `git fetch`/`pull`/`push` needs network access to reach GitHub; a sandboxed shell blocks it, and the failure surfaces as a DNS/connection error that looks like an auth or remote problem. Run these commands with sandboxing disabled, and if one fails with a connection error, suspect the sandbox first.

### 0. Resolve the issue number

If the user provided a number, use it as `<N>`. Otherwise auto-pick the **lowest-numbered** open `ready-for-agent` issue, **excluding PRDs** (spec documents, not tickets — filter primarily by the `prd` label, with the body-heading regex as fallback for older PRDs):

```bash
gh issue list --state open --label ready-for-agent --json number,title,body,labels \
  --jq 'sort_by(.number)
        | map(select(.labels | map(.name) | index("prd") | not))
        | map(select(.body | test("(?m)^## (Problem Statement|User Stories|Implementation Decisions)") | not))
        | .[0]'
```

If it returns an issue, announce the pick (number + title) before proceeding. If it returns `null` or nothing, stop and ask — do not guess, and do not implement a PRD directly (PRDs get broken into issues first, e.g. via a `to-issues` skill).

### 1. Read the issue and claim it

`gh issue view <N> --comments` — read the body AND comments. Note title, acceptance criteria, blocked-by links, and scope labels (`needs-info`, `wontfix`, etc. → stop and ask). Then claim it so two agents don't work it simultaneously: `gh issue edit <N> --add-assignee @me` plus a brief "starting work, branch `feat/issue-<N>-<slug>`" comment. If already assigned to someone else, stop and ask.

### 2. Pick a base branch

- Default base: the repo's default branch (`gh repo view --json defaultBranchRef`).
- **Detecting blocked-by:** GitHub has no native field — look for body/comment lines like `Blocked by #12` / `Depends on #12`, task-list references, or a `blocked` label.
- If blocked by an issue/PR whose branch exists but isn't merged, branch off that branch and note it in the PR description (reviewer rebases onto main once the blocker lands).
- If the blocker has **no branch yet**, stop and surface to the user — don't branch off nothing or implement the blocker yourself.

### 3. Create the feature branch

First run `git status --porcelain`. Any output → **stop and ask** (stash, commit, or abort) — never silently drag uncommitted changes onto the new branch.

Check `AGENTS.md` / `CONTRIBUTING.md` for a branch naming convention before guessing. Default:

```bash
git switch <base> && git pull --ff-only
git switch -c feat/issue-<N>-<short-kebab-slug>
```

The `issue-<N>` prefix is load-bearing for branch→issue tooling; keep it. Slug = kebab of the issue title, ≤5 words, drop filler.

### 4. Explore before editing

Grep/search for the modules the issue touches. Read `AGENTS.md`, `CONTEXT.md`, and ADRs in `docs/adr/` for invariants. Match existing patterns; don't introduce new infrastructure (test framework, linter config) unless the issue asks for it.

Identify the **test command** and the **run command** (`AGENTS.md`, `package.json` scripts, `Makefile`, `pyproject.toml`, CI workflows, `docker-compose.yml`). Run the test suite **once now, before editing**, to baseline — note any pre-existing failures so you don't mistake them for regressions later.

### 5. Implement in small commits

- Open a **draft PR within the first 1–2 commits**: `git push -u origin HEAD` then `gh pr create --draft --title "<title>" --body "Closes #<N>. <one-paragraph plan>"`. Use the repo's PR template (`.github/pull_request_template.md`) if one exists, keeping the `Closes #<N>` line. If `gh pr create` fails (permissions, branch protection), keep committing locally and surface the error at the end — don't abort.
- Keep commits scoped and conventional (`feat:`, `fix:`, `refactor:`, …).
- After substantive edits, run the project's linter/type-checker if configured (do NOT add one if missing).

### 6. Tests (REQUIRED before marking ready)

Run the suite from step 4. Everything that passed at baseline must still pass; new failures are yours to fix. If acceptance criteria describe verifiable behaviour and the project has a test suite, add tests covering it — matching existing style. Never add a test framework to a project that has none.

### 7. Runtime smoke check (REQUIRED before marking ready)

**Do not declare done until you've observed the project actually run without errors.** Pick the branch matching the project type:

- **Long-running app (server/web):** start it in the background with the run command; wait for the ready signal (port listening, "compiled successfully", health 200); hit a basic endpoint; read the last ~50 log lines for tracebacks/warnings introduced by your change; stop it cleanly.
- **CLI / library / script / pipeline (no port):** run the entrypoint once with a representative invocation — `<cli> --help` plus one real subcommand, import the package and call the changed API, or execute the flow once against safe inputs. Confirm exit code 0 and no new tracebacks.

If it fails, **fix and retry** — don't push the failure onto the reviewer. Loop until green.

### 8. Finalise the PR

- Push final commits; update the PR body with a short **Summary** and **Test plan** (what you ran in steps 6–7, what you observed).
- `gh pr ready`, then report the PR URL. Do **not** merge — leave that to the human.

## Stop conditions

Stop and surface to the user (do not improvise) if:

- The issue is labelled `needs-info`, `wontfix`, or `needs-triage`, or is already assigned to someone else.
- Acceptance criteria are ambiguous or contradict the codebase's invariants.
- The issue is blocked by an issue/PR that has no branch yet.
- The working tree is dirty when it's time to branch.
- Tests or the smoke check still fail after **three fix attempts** at the same root cause.

When stopping mid-implementation, don't discard the work: push the WIP branch and comment your findings (what failed, what you tried) on issue `<N>` so the next attempt starts from there.
