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

Stop on any failure. Ancestry exit 1 on the default branch means it has local-only commits. Report the commits listed above and leave the branch and working tree intact. On a clean feature branch, run the Step 2 lookup first. Resume an exact open PR at Step 5 only if its SHA equals local HEAD. If they differ, report both tips and stop before pushing, merging or deleting. With commits ahead and no PR, resume at the Step 3 push. A clean tree with neither has nothing to ship.

**Run all `gh` and `git fetch`/`pull`/`push`/`ls-remote` outside the sandbox.** It blocks network, and the failure looks like a `gh`/remote auth error; on a connection error, suspect the sandbox first.

## Step 1: Group the changes, detect unrelated work

Form the commit groups **before** any branching (the `smart-git-commit` grouping pass: inspect `git status`/`git diff`, group by affected area); branch decisions depend on them.

**Unrelated-work detection:** if the groups would not sit honestly under a single PR title, because they are disjoint subsystems with different intents (e.g. a `feat` in `api/` plus an unrelated `fix` in `.github/workflows/`), ask: "These look like unrelated changes: <one line per group>. Ship as separate branches/PRs, or together?" A feature plus its own tests/docs is NOT a split; when in doubt, default to one branch. This prompt always fires; silently bundling unrelated work into a merge nobody confirms is what it prevents.

**If splitting:** run Steps 2–5 once per group, using the fresh-branch mechanics in Step 2 between groups to carry the remaining uncommitted changes along. Disjoint files mean later PRs merge cleanly after earlier ones.

## Step 2: Pick the branch

On the default branch, create a fresh branch. On a feature branch, set `branch` to the nonempty output of `git branch --show-current`. Set `land_dir` to the directory containing this SKILL.md. Check ancestry and look up PRs across all bases:

```bash
git merge-base --is-ancestor HEAD "origin/$default_branch" && echo ancestor-merged
bash "$land_dir/scripts/lookup-pr.sh" "$host" "$repo" "$branch" "$default_branch"
```

Ancestry exit 0 means merged, 1 means check PR history, and any other exit stops. The lookup prints `open <number> <sha>`, `merged`, or `none`. Stop on nonzero exit, including an open PR from this source targeting another base. For clean resumption, pin `number` and `sha` from the open row before checking CI.

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

After a push, repeat the Step 2 lookup for the pushed branch. Reuse the exact open PR. Otherwise write the body to a file and run `gh pr create --base "$default_branch" --head <current-branch> --title "<conventional subject>" --body-file <body-file>`.

After creation or reuse, require the lookup to return the intended open PR and the SHA from `git rev-parse HEAD`. Pin its `number`, `branch`, and `sha` for Step 5. Stop if they differ.

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
  git grep -lwE 'pull_request(_target)?' "$sha" -- .github/workflows   # any hit = PR-triggered CI exists
  gh run list --commit "$sha" --json name,status                      # runs queued or started for that commit
  ```

  - No `git grep` hit **and** an empty `gh run list` → the repo has no PR CI. Continue with the checks line "checks: none reported", which the close-out carries so the user knows nothing gated the merge.
  - A hit, or any run listed (push-triggered CI also checks the PR head) → re-read `gh pr checks <number> --json name,bucket` and `gh run list` up to 5 times; as soon as a check appears, rerun the watch and route again. Still no check after 5 reads → stop and ask the user whether to merge without CI.

Then, with the gate green:

- Merge without asking; the checks line goes in the close-out.
- Only when the user said "don't merge" or "ask first": stop, or ask "Merge and clean up (squash-merge the PR, delete the local and remote branch)?" with the checks line. On no, leave the PR open, print its URL, and stop. Delete nothing.

Run the guarded merge below. Stop on a local or remote head mismatch. After a merge attempt, read the PR state even if GitHub refused the merge.

```bash
bash "$land_dir/scripts/merge-head.sh" "$host" "$repo" "$number" "$branch" "$default_branch" "$sha"
gh pr view <number> --json state,mergeCommit,autoMergeRequest,headRefName,headRefOid,baseRefName
```

| End state | Action |
|---|---|
| `MERGED` | Finish on the default branch (below) |
| `OPEN`, `autoMergeRequest` set | Auto-merge armed; it lands once the PR's requirements are met. Stop |
| `OPEN`, the plain merge refused as not mergeable (branch policy or required checks; `gh`'s error suggests `--auto`) | Repeat the guarded merge command above with `--auto` appended, then re-read the state and route it again. A refused `--auto` falls to the last row |
| `OPEN`, no `autoMergeRequest`, the merge command exited 0 | Queued (a merge queue). Stop; run no pull |
| Anything else | Report the actual state and `gh`'s message. Stop |

**Finish on the default branch** (`MERGED` only). Require the returned head name, head OID and base to match `branch`, `sha` and `default_branch`. Set `merge_commit` from `mergeCommit.oid`. Run in order and stop on failure:

```bash
git checkout "$default_branch" && git pull --ff-only origin "$default_branch"
bash "$land_dir/scripts/cleanup.sh" "$branch" "$sha" "$merge_commit" "$default_branch"
git ls-remote --exit-code --heads origin "refs/heads/$branch"   # exit 2 = remote branch gone
git rev-parse --verify --quiet "refs/heads/$branch"             # exit 1 = local branch gone
```

Cleanup requires the squash commit on the default branch, the expected tips and a free source branch across worktrees. A moved or occupied branch, failed guard or missing confirmation means **merged, but cleanup incomplete**. Report which check stopped cleanup.

**Close-out:** lead with the confirmed outcome in one sentence (merged; merged, but cleanup incomplete; auto-merge armed; queued; stopped on failing checks; PR left open; or the actual state) with the PR URL and checks line. Name every branch that outlives the run. Anything worth flagging goes after it.

## Safety rules

- The smart-git-commit rules apply: no force-push, no skipped hooks (`--no-verify`), no likely secrets (`.env`, credentials, tokens) in a commit.
- Merge only once the Step 5 CI gate is green; running land is the user's go-ahead for the squash-merge, the one irreversible step, unless they said "don't merge" or "ask first".
- If a step fails mid-flow (rejected push, conflict on `git checkout` or `git pull`), stop and report rather than improvising recovery; a half-recovered state is harder to fix than a stopped one. A non-zero exit from `gh pr checks` or `gh pr merge` is not such a failure: Step 5 routes by the state it reads, and a failing check stops the flow through the CI gate.
