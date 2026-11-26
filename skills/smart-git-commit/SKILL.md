---
name: smart-git-commit
description: Groups changed files by affected area and creates one conventional commit per group, pushing to remote only when asked. Use when the user asks to commit changes or commit and push.
---

# Smart git commit

## Workflow

Commit what has already changed: grouping and staging are the only edits this skill makes. Don't fix lint, reformat, or touch file contents on the way past. Mention anything the diff surfaces when you report back instead.

### Step 1: Inspect changes

Run these in parallel:

- `git status`: see all modified/untracked files
- `git diff`: see unstaged changes
- `git diff --cached`: see staged changes
- `git log --oneline -10`: learn the repo's commit conventions (scopes, area names)

If there is nothing to commit, say so and stop.

### Step 2: Group files by area

Split the changes into atomic commits, one logical change per commit:

- Group by subsystem or top-level directory (e.g. `api/`, `docs/`, `.github/workflows/`, a service, a model layer).
- Keep a change together with its own tests and docs when they belong to the same logical change.
- Take area names from the repo's own conventions (recent commit subjects, `CLAUDE.md`, `README`) rather than inventing new ones.
- Bundle files that don't fit neatly with the closest related group.
- Treat already-staged files like any other change: they join their group and are re-staged with it.

Done when every changed file from `git status` is assigned to exactly one group, and no group spans two unrelated top-level areas.

### Step 3: Determine commit type per group

| Type | When to use |
|------|-------------|
| `feat` | New feature, model, endpoint, workflow |
| `fix` | Bug fix, correcting logic, fixing a broken test |
| `docs` | Documentation-only changes |
| `refactor` | Restructuring without behavior change |
| `test` | Adding or updating tests |
| `chore` | Config, dependency, CI/CD, tooling changes |
| `style` | Formatting, whitespace, no logic change |

If recent commits use scopes (`feat(api): …`), use the same scopes; otherwise use bare types. Always produce conventional commits, even when the repo's history doesn't.

### Step 4: Commit each group

Before the first group, run `git reset -q` so already-staged files join only their own group. If a file shows in both `git diff --cached` and `git diff` (a partial `git add -p`), ask first: the reset discards that split.

For each group, stage only its files and commit:

```bash
git add <files in group>
git commit -m "$(cat <<'EOF'
type: short imperative description

Optional body if the change needs explanation.
EOF
)"
```

**Message rules:**

- Lowercase type prefix
- Imperative mood: "add", "fix", "update"; not "added", "fixes"
- Max ~72 chars on the subject line
- No period at the end of the subject line
- Body only when the why isn't obvious from the subject
- No em dashes anywhere in the message. Use a comma, colon, or parentheses, or rewrite the sentence

**Examples:**

```
feat: add customer metrics endpoint
fix: handle null totals in order aggregation
docs: document retry behavior for ingestion jobs
refactor: simplify date-parsing helpers
test: cover empty-cart checkout path
chore: update CI workflow schedule
```

### Step 5: Push when asked

After all commits are created, confirm `git status` is clean, so no changed file was silently dropped from a commit.

Push only when the request asked for it: the user said "push" ("commit and push", "push it"), or a calling skill's workflow includes the push. A plain "commit" ends here, with the commits local.

Set `skill_dir` to the directory containing this SKILL.md and `local_branch` to the nonempty output of `git branch --show-current`. Stop on failure. Set `mode=tracked` for an existing upstream, or `mode=new` to publish the local branch at the same name on origin. Preview that push:

```bash
bash "$skill_dir/scripts/preview-push.sh" "$mode"
```

Stop on nonzero exit. The helper runs `git push --dry-run --porcelain --no-verify` to keep pre-push hooks from publishing during inspection. It rejects force, deletion, rejected updates and unknown output. Each tab-separated output row gives one push URL and one new or updated destination branch. Check every row across all push URLs. Unchanged refs need no review lookup.

- On GitHub, take `host` and the push repository from the row’s URL and `branch` from its destination branch. Use `gh api --hostname "$host" "repos/<push-owner>/<push-repo>" --jq '{full_name, fork, parent: .parent.full_name}'` to get the canonical source (`source` = `full_name`). Set `target` to that source, then repeat for its upstream PR target when it is a fork (normally `parent`). Keep the same source and branch in both lookups.

  ```bash
  gh api --hostname "$host" -X GET "repos/$target/pulls" --paginate -f state=closed -f head="${source%/*}:$branch" --jq 'map({number, source: .head.repo.full_name, head: .head.ref, merged_at})'
  ```

  A PR counts only when its source and head match `source` and `branch` exactly and `merged_at` has a timestamp. A lookup clears only after exit 0 and every page shows no matching merge.
- On another forge, check its merged requests for the same source project and branch using its CLI or web interface. For example, look for merged merge requests on GitLab. A plain Git remote with no review service needs only the Git preview.
- If a merge is found, a review target is unknown, or a required lookup fails or returns incomplete data, keep the commits local and report why. After every destination clears its check, use the command for the previewed mode. Repeat the preview and lookups if the branch or push configuration changes.

For `tracked`:

```bash
git push
```

For `new`, set the upstream with the same explicit refspec used in the preview:

```bash
git push -u origin "HEAD:refs/heads/$local_branch"
```

**Run the push outside the sandbox.** `git push` needs network access to reach the remote; a sandboxed shell blocks it, and the failure surfaces as a DNS/connection error that looks like an auth or remote problem. If the push fails with a connection error, suspect the sandbox first.

**Close out** with the outcome first: the commit subjects and whether the push landed, or that nothing was pushed, in a line or two. No per-commit writeup.

## Safety rules

These hold on every run; each one is either unrecoverable or moves a problem onto someone else:

- Don't amend commits that have already been pushed; rewriting shared history breaks every other checkout of the branch.
- Keep hooks enabled on commits and on the actual push.
- Don't commit files that likely contain secrets (`.env`, credentials, tokens); a pushed secret is compromised even after it is removed.
- Stop and report any rejected push. Never force a branch update.
