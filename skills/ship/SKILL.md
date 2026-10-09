---
name: ship
description: Branches off main for the current changes, commits them smart-git-commit style, opens a PR, then squash-merges and deletes the local and remote branch after confirmation. Waits for CI and never merges a PR with a failing check. The clean argument skips only that merge confirmation, never the CI gate or the unrelated-changes prompt.
disable-model-invocation: true
---

# Ship

Take the current working-tree changes from branch to merged PR in one pass: branch off `main`, commit smart-git-commit style, open a PR, then squash-merge and clean up the local and remote branch.

**Argument:** `clean` skips the Step 5 merge confirmation and goes straight through (`/ship clean`). Only that: the Step 1 unrelated-work prompt and the Step 5 CI gate still apply.

**Scope:** ship the changes already in the working tree, as they are. Do not fix, refactor, tidy, or reformat anything on the way through. A problem you notice in passing goes in the close-out, not into a commit.

## Step 0: Preflight

Run in parallel:

- `git status`. If the tree is clean and there is nothing to commit, say so and stop.
- `gh auth status` and `git remote get-url origin`. If `gh` is missing or unauthenticated, or there is no `origin` remote, stop with a clear message before touching anything.

**Run all `gh` and `git fetch`/`pull`/`push`/`ls-remote` outside the sandbox.** It blocks network, and the failure looks like a `gh`/remote auth error; on a connection error, suspect the sandbox first.

## Step 1: Group the changes, detect unrelated work

Form the commit groups **before** any branching (the `smart-git-commit` grouping pass: inspect `git status`/`git diff`, group by affected area); branch decisions depend on them.

**Unrelated-work detection:** if the groups would not sit honestly under a single PR title, because they are disjoint subsystems with different intents (e.g. a `feat` in `api/` plus an unrelated `fix` in `.github/workflows/`), ask: "These look like unrelated changes: <one line per group>. Ship as separate branches/PRs, or together?" A feature plus its own tests/docs is NOT a split; when in doubt, default to one branch. This prompt fires even under `clean`; silently bundling unrelated work is exactly what `clean` must not do.

**If splitting:** run Steps 2–5 once per group, each on its own branch off updated main (`git checkout main && git pull && git checkout -b …` between groups carries the remaining uncommitted changes along). Disjoint files mean later PRs merge cleanly after earlier ones. Ask the Step 5 merge question once, listing all PRs.

## Step 2: Pick the branch

Decide where the changes should live from git/gh state; only ask when it is genuinely ambiguous. On `main`, skip the detection below and go straight to a fresh branch. On a feature branch, detect "merged" two ways (either signal counts, because squash merges are not git ancestors) and check for an open PR (an open PR means live work):

```bash
git fetch origin main
git merge-base --is-ancestor HEAD origin/main && echo ancestor-merged
gh pr list --head "$(git branch --show-current)" --state merged --json number
gh pr list --head "$(git branch --show-current)" --state open --json number
```

| Current state | Action |
|---|---|
| On `main` | Create a fresh branch off updated main |
| Feature branch, already merged, no commits beyond `origin/main` | Stale. Create a fresh branch off updated main; uncommitted changes carry over with the checkout (stash, pull, branch, pop if the checkout conflicts) |
| Feature branch, not merged (unmerged commits or an open PR) | Live work. Use it as-is, skip branch creation. When splitting, only the group related to this branch's work stays here; the rest get fresh branches off main |
| Merged AND new local commits on top | The one ambiguous case. Ask: fresh branch off main, or continue on this one? |

Fresh-branch mechanics: `git checkout main && git pull && git checkout -b <branch>`.

**Branch name (fixed format):** `<type>/<short-slug>`. `type` is the conventional-commit type of the dominant change group, slug is 2-4 kebab-case words. Examples: `feat/ship-skill`, `fix/null-order-totals`.

## Step 3: Commit

Commit using the **`smart-git-commit`** skill workflow, reusing the groups from Step 1: one conventional commit per group. If that skill is unavailable, fall back to one conventional commit (lowercase type, imperative subject) per group. Either way, ship pushes the branch itself, whether or not smart-git-commit pushed:

```bash
git push -u origin HEAD
```

Done when the push succeeds; if the push is rejected (e.g. non-fast-forward), stop and report. Do not open the PR.

## Step 4: Open the PR

```bash
gh pr create --base main --title "<conventional subject>" --body "$(cat <<'EOF'
## Summary
- one bullet per commit group

EOF
)"
```

- The title is the conventional-commit subject of the dominant change (e.g. `feat: add ship skill`). Squash merge makes the title the commit on `main`, so it must itself be a valid conventional commit.
- The body has `## Summary`, one bullet per commit group (a single group gets one or two bullets; don't pad to fill). No test-plan boilerplate.
- On a live branch, when the PR includes commits that predate this run, the title and bullets describe the whole PR (everything the squash lands on `main`), not just this session's groups.
- Do not use em dashes in the title or body. Use a comma, colon, or parentheses, or rewrite the sentence. Same rule as the commit messages.

## Step 5: Merge and clean up

`<number>` is the PR number from Step 4. Name it in every `gh pr` command, because the current branch may not be the PR's.

**CI gate, under `clean` too.** Before any merge question, wait for each PR's checks to settle, then read them:

```bash
gh pr checks <number> --watch --fail-fast   # blocks until every check finishes or one fails
gh pr checks <number> --json name,bucket
```

The watch runs as long as CI does, so give it a long command timeout (e.g. 10 minutes) rather than the shell default.

Route by the JSON (or the "no checks reported" message), never by either command's exit code (1 = a check failed, 8 = pending, non-zero when none are reported):

- Any check in bucket `fail` or `cancel` → stop. Report the failing check names and the PR URL; leave the PR open and delete nothing. Never merge a red PR: a repo without branch protection would take it.
- Any check still `pending` (the watch was cut short, e.g. by a command timeout) → rerun the watch; merge never runs on a pending check.
- Every check `pass` or `skipping` → summarise them as one checks line, e.g. "checks: 4 pass, 1 skipping", and continue.
- No checks reported → CI may not have registered yet. Check whether the PR's head tree defines PR-triggered GitHub Actions workflows:

  ```bash
  sha=$(gh pr view <number> --json headRefOid -q .headRefOid)
  git grep -lwE 'pull_request(_target)?' "$sha" -- .github/workflows   # any hit = PR-triggered CI exists
  gh run list --commit "$sha" --json name,status                      # runs queued or started for that commit
  ```

  - No hit → the repo has no PR CI. Continue with the checks line "checks: none reported", which the close-out carries so the user knows nothing gated the merge.
  - A hit → re-read `gh run list` and `gh pr checks <number> --json name,bucket` up to 5 times; as soon as a run or check appears, rerun the watch and route again. Still none after 5 reads → stop and ask the user whether to merge without CI, even under `clean`.

Then, with the gate green:

- Invoked with `clean` → proceed without asking; the checks line goes in the close-out.
- Otherwise ask: "Merge and clean up (squash-merge the PR, delete the local and remote branch)?", followed by the checks line.
  - **No** → leave the PR open, print its URL, and stop. Delete nothing.

On yes (or `clean`), merge, then, once the merge has returned, read the PR's end state whatever the merge's exit code. The state routes this step: a merge that landed exits 1 when local branch deletion fails, and a merge-queue enqueue exits 0 with the PR still open.

```bash
gh pr merge <number> --squash --delete-branch
gh pr view <number> --json state,mergeCommit,autoMergeRequest,headRefName
```

| End state | Action |
|---|---|
| `MERGED` | Finish on `main` (below) |
| `OPEN`, `autoMergeRequest` set | Auto-merge armed; it lands once the PR's requirements are met. Stop |
| `OPEN`, the plain merge refused as not mergeable (branch policy or required checks; `gh`'s error suggests `--auto`) | Retry with `gh pr merge <number> --squash --delete-branch --auto`, re-read the state, and route it again. A refused `--auto` falls to the last row |
| `OPEN`, no `autoMergeRequest`, the merge command exited 0 | Queued (a merge queue). Stop; run no pull |
| Anything else | Report the actual state and `gh`'s message. Stop |

On every row that stops, nothing has been deleted: both branches still exist and the session stays on the PR's head branch (`headRefName`).

**Finish on `main`** (`MERGED` only). `gh` may leave you on another branch (it does when local cleanup fails), so check out `main` and pull either way; this is part of the flow, not recovery. Then confirm, with `<branch>` from `headRefName`:

```bash
git checkout main && git pull
git merge-base --is-ancestor <mergeCommit.oid> main   # exit 0 = merge commit on local main
git ls-remote --exit-code --heads origin <branch>      # exit 2 = remote branch gone
git rev-parse --verify --quiet refs/heads/<branch>     # non-zero = local branch gone
```

All three confirm → **merged**. Any miss → **merged, but cleanup incomplete**; say which check missed.

**Close-out:** lead with the confirmed outcome in one sentence (merged; merged, but cleanup incomplete; auto-merge armed; queued; stopped on failing checks; PR left open; or the actual state) with the PR URL and checks line. Name every branch that outlives the run. Anything worth flagging goes after it.

## Safety rules

- The smart-git-commit rules apply: no force-push, no skipped hooks (`--no-verify`), no likely secrets (`.env`, credentials, tokens) in a commit.
- Delete branches only through `--delete-branch` in the Step 5 merge, which acts only once the PR has merged; an unmerged branch may hold the only copy of the work.
- Merge only once the Step 5 CI gate is green, and only with the `clean` argument or an explicit yes; the squash-merge is the one irreversible step and the user owns it.
- If a step fails mid-flow (rejected push, conflict on `git checkout` or `git pull`), stop and report rather than improvising recovery; a half-recovered state is harder to fix than a stopped one. A non-zero exit from `gh pr checks` or `gh pr merge` is not such a failure: Step 5 routes by the state it reads, and a failing check stops the flow through the CI gate.
