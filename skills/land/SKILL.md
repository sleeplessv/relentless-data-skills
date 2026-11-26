---
name: land
description: Branches off the default branch for the current changes, commits them smart-git-commit style, opens a PR, then squash-merges and deletes the local and remote branch without asking. Waits for CI and never merges a PR with a failing check.
disable-model-invocation: true
---

# Land

Take the current working-tree changes from branch to merged PR in one pass: branch off the default branch, commit smart-git-commit style, open a PR, then squash-merge and clean up the local and remote branch.

**Argument:** land merges and cleans up by default once the Step 5 CI gate is green; `clean` is accepted and changes nothing. "Don't merge" or "ask first" stops at Step 5 with the PR open, or asks there. Any other argument text is a user instruction that overrides the Step 1 and Step 2 decisions it speaks to: "separate PR" means a fresh branch off the default branch even from a live branch, and "staged changes" means ship only the index.

**Scope:** ship the changes already in the working tree, as they are. Do not fix, refactor, tidy, or reformat anything on the way through. A problem you notice in passing goes in the close-out, not into a commit. The PR's checks are the test gate: the flow runs git and gh commands plus what the `smart-git-commit` and `pr` skills read, and nothing that executes the code.

## Step 0: Preflight

Run `git status`, `gh auth status`, and `gh repo view --json url,defaultBranchRef`. From the result take the GitHub `host`, `repo` (`OWNER/REPO`), and `default_branch` (`defaultBranchRef.name`). Confirm both `git remote get-url origin` and every URL from `git remote get-url --push --all origin` identify this repository. Stop on any failure, mismatch, or missing value. Then run:

```bash
git fetch origin "refs/heads/$default_branch:refs/remotes/origin/$default_branch"
git log --oneline "origin/$default_branch..HEAD"
if [ "$(git branch --show-current)" = "$default_branch" ]; then git merge-base --is-ancestor HEAD "origin/$default_branch"; fi
```

Stop on any failure. Ancestry exit 1 on the default branch means it has local-only commits. Report the commits listed above and leave the branch and working tree intact. On a clean feature branch, resume at Step 5 for an open PR found by Step 2, or at the Step 3 push for commits ahead with no PR. A clean tree with neither has nothing to ship.

**Run all `gh` and `git fetch`/`pull`/`push`/`ls-remote` outside the sandbox.** It blocks network, and the failure looks like a `gh`/remote auth error; on a connection error, suspect the sandbox first.

## Step 1: Group the changes, detect unrelated work

Form the commit groups **before** any branching (the `smart-git-commit` grouping pass: inspect `git status`/`git diff`, group by affected area); branch decisions depend on them.

**Unrelated-work detection:** if the groups would not sit honestly under a single PR title, because they are disjoint subsystems with different intents (e.g. a `feat` in `api/` plus an unrelated `fix` in `.github/workflows/`), ask: "These look like unrelated changes: <one line per group>. Ship as separate branches/PRs, or together?" A feature plus its own tests/docs is NOT a split; when in doubt, default to one branch. This prompt always fires; silently bundling unrelated work into a merge nobody confirms is what it prevents.

**If splitting:** run Steps 2–5 once per group, using the fresh-branch mechanics in Step 2 between groups to carry the remaining uncommitted changes along. Disjoint files mean later PRs merge cleanly after earlier ones.

## Step 2: Pick the branch

On the default branch, create a fresh branch. On a feature branch, set `branch` to the nonempty output of `git branch --show-current`. Check ancestry and PRs against the fetched default:

```bash
git merge-base --is-ancestor HEAD "origin/$default_branch" && echo ancestor-merged
gh api --hostname "$host" -X GET "repos/$repo/pulls" --paginate -f state=all -f head="${repo%/*}:$branch" -f base="$default_branch" --jq 'map({number, source: .head.repo.full_name, head: .head.ref, base: .base.ref, state, merged_at})'
```

Ancestry exit 0 means merged, 1 means check PR history, and any other exit stops. Require a successful, complete API read of every page. Use only rows matching `repo`, `branch`, and `default_branch` exactly. An open row supplies the PR number and takes precedence. A `merged_at` timestamp records a merge. Stop if a lookup fails or its result is ambiguous.

| Current state | Action |
|---|---|
| On the default branch | Create a fresh branch off the updated default branch |
| Feature branch, already merged, no commits beyond `origin/$default_branch` | Stale. Create a fresh branch from the fetched default |
| Feature branch, not merged (unmerged commits or an open PR) | Live work. Use it as-is, skip branch creation. When splitting, only the group related to this branch's work stays here; the rest get fresh branches off the default branch |
| Merged AND new local commits on top | The one ambiguous case. Ask: fresh branch off the default branch, or continue on this one? |

Fresh-branch mechanics: `git checkout --no-track -b <branch> "origin/$default_branch"`. The checkout carries uncommitted changes and stops if it would overwrite them.

**Branch name (fixed format):** `<type>/<short-slug>`. `type` is the conventional-commit type of the dominant change group, slug is 2-4 kebab-case words. Examples: `feat/land-skill`, `fix/null-order-totals`.

## Step 3: Commit

Commit using the **`smart-git-commit`** skill workflow, reusing the groups from Step 1: one conventional commit per group. If that skill is unavailable, fall back to one conventional commit (lowercase type, imperative subject) per group. Either way, land pushes the branch itself, whether or not smart-git-commit pushed:

```bash
git push -u origin HEAD
```

Done when the push succeeds; if the push is rejected (e.g. non-fast-forward), stop and report. Do not open the PR.

## Step 4: Open the PR

Reuse the matching open PR from Step 2 if its head is still the current branch. Otherwise write the body to a file and run `gh pr create --base "$default_branch" --head <current-branch> --title "<conventional subject>" --body-file <body-file>`.

- The title is the conventional-commit subject of the dominant change (e.g. `feat: add land skill`). Squash merge makes the title the commit on the default branch, so it must itself be a valid conventional commit.
- Load the **`pr`** skill with the Skill tool (`Skill: pr`) and write the body to its template: Summary, Evidence, Merge Danger. Evidence comes only from what this session actually ran or saw; never invent test runs or output. If that skill is unavailable, fall back to `## Summary` with one bullet per commit group (a single group gets one or two bullets; don't pad to fill) and no test-plan boilerplate.
- On a live branch, when the PR includes commits that predate this run, the title and body describe the whole PR (everything the squash lands on the default branch), not just this session's groups.
- Do not use em dashes in the title or body. Use a comma, colon, or parentheses, or rewrite the sentence. Same rule as the commit messages.

## Step 5: Merge and clean up

`<number>` is the PR number from Step 4, or the open PR Step 0 found. Name it in every `gh pr` command, because the current branch may not be the PR's.

**CI gate.** Before any merge, wait for each PR's checks to settle, then read them:

```bash
gh pr checks <number> --watch --fail-fast >/dev/null 2>&1   # blocks until every check finishes or one fails; the JSON below is the read
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

  - No `git grep` hit **and** an empty `gh run list` → the repo has no PR CI. Continue with the checks line "checks: none reported", which the close-out carries so the user knows nothing gated the merge.
  - A hit, or any run listed (push-triggered CI also checks the PR head) → re-read `gh pr checks <number> --json name,bucket` and `gh run list` up to 5 times; as soon as a check appears, rerun the watch and route again. Still no check after 5 reads → stop and ask the user whether to merge without CI.

Then, with the gate green:

- Merge without asking; the checks line goes in the close-out.
- Only when the user said "don't merge" or "ask first": stop, or ask "Merge and clean up (squash-merge the PR, delete the local and remote branch)?" with the checks line. On no, leave the PR open, print its URL, and stop. Delete nothing.

Merge, then, once the merge has returned, read the PR's end state whatever the merge's exit code. The state routes this step: a merge that landed exits 1 when local branch deletion fails, and a merge-queue enqueue exits 0 with the PR still open.

```bash
gh pr merge <number> --squash --delete-branch
gh pr view <number> --json state,mergeCommit,autoMergeRequest,headRefName
```

| End state | Action |
|---|---|
| `MERGED` | Finish on the default branch (below) |
| `OPEN`, `autoMergeRequest` set | Auto-merge armed; it lands once the PR's requirements are met. Stop |
| `OPEN`, the plain merge refused as not mergeable (branch policy or required checks; `gh`'s error suggests `--auto`) | Retry with `gh pr merge <number> --squash --delete-branch --auto`, re-read the state, and route it again. A refused `--auto` falls to the last row |
| `OPEN`, no `autoMergeRequest`, the merge command exited 0 | Queued (a merge queue). Stop; run no pull |
| Anything else | Report the actual state and `gh`'s message. Stop |

On every row that stops, nothing has been deleted: both branches still exist and the session stays on the PR's head branch (`headRefName`).

**Finish on the default branch** (`MERGED` only). `gh` may leave you on another branch (it does when local cleanup fails), so check out the default branch and pull either way; this is part of the flow, not recovery. Then confirm, with `<branch>` from `headRefName`:

```bash
git checkout "$default_branch" && git pull --ff-only origin "$default_branch"
git merge-base --is-ancestor <mergeCommit.oid> "$default_branch"   # exit 0 = merge commit on the local default branch
git ls-remote --exit-code --heads origin <branch>      # exit 2 = remote branch gone
git rev-parse --verify --quiet refs/heads/<branch>     # non-zero = local branch gone
```

All three confirm → **merged**. Any miss → **merged, but cleanup incomplete**; say which check missed.

**Close-out:** lead with the confirmed outcome in one sentence (merged; merged, but cleanup incomplete; auto-merge armed; queued; stopped on failing checks; PR left open; or the actual state) with the PR URL and checks line. Name every branch that outlives the run. Anything worth flagging goes after it.

## Safety rules

- The smart-git-commit rules apply: no force-push, no skipped hooks (`--no-verify`), no likely secrets (`.env`, credentials, tokens) in a commit.
- Delete branches only through `--delete-branch` in the Step 5 merge, which acts only once the PR has merged; an unmerged branch may hold the only copy of the work.
- Merge only once the Step 5 CI gate is green; running land is the user's go-ahead for the squash-merge, the one irreversible step, unless they said "don't merge" or "ask first".
- If a step fails mid-flow (rejected push, conflict on `git checkout` or `git pull`), stop and report rather than improvising recovery; a half-recovered state is harder to fix than a stopped one. A non-zero exit from `gh pr checks` or `gh pr merge` is not such a failure: Step 5 routes by the state it reads, and a failing check stops the flow through the CI gate.
