---
name: ship
description: Branches off main for the current changes, commits them smart-git-commit style, opens a PR, then squash-merges and deletes the local and remote branch after confirmation - or without asking when invoked with the clean argument. Use when the user runs /ship to take working-tree changes all the way to a merged PR.
disable-model-invocation: true
---

# Ship

Take the current working-tree changes from branch to merged PR in one pass: branch off `main`, commit smart-git-commit style, open a PR, then squash-merge and clean up the local and remote branch.

**Argument:** `clean` — skip the merge confirmation and go straight through (`/ship clean`).

## Step 0: Preflight

Run in parallel:

- `git status` — if the tree is clean and there is nothing to commit, say so and stop.
- `gh auth status` and `git remote get-url origin` — if `gh` is missing or unauthenticated, or there is no `origin` remote, stop with a clear message before touching anything.

**Run network commands outside the sandbox.** Every `gh` call and `git fetch`/`pull`/`push` needs network access to reach GitHub; a sandboxed shell blocks it, and the failure surfaces as a DNS/connection error that looks like an auth or remote problem. Run these commands with sandboxing disabled, and if one fails with a connection error, suspect the sandbox first — do not start debugging `gh` auth or the remote URL.

## Step 1: Group the changes, detect unrelated work

Form the commit groups **before** any branching (the `smart-git-commit` grouping pass: inspect `git status`/`git diff`, group by affected area) — branch decisions depend on them.

**Unrelated-work detection:** if the groups would not sit honestly under a single PR title — disjoint subsystems with different intents (e.g. a `feat` in `api/` plus an unrelated `fix` in `.github/workflows/`) — ask: "These look like unrelated changes: <one line per group>. Ship as separate branches/PRs, or together?" A feature plus its own tests/docs is NOT a split; when in doubt, default to one branch. This prompt fires even under `clean` — silently bundling unrelated work is exactly what `clean` must not do.

**If splitting:** run Steps 2–5 once per group, each on its own branch off updated main (`git checkout main && git pull && git checkout -b …` between groups carries the remaining uncommitted changes along). Disjoint files mean later PRs merge cleanly after earlier ones. Ask the Step 5 merge question once, listing all PRs.

## Step 2: Pick the branch

Decide where the changes should live from git/gh state — only ask when it is genuinely ambiguous. Detect "merged" two ways, because squash merges are not git ancestors:

```bash
git fetch origin main
git merge-base --is-ancestor HEAD origin/main && echo ancestor-merged
gh pr list --head "$(git branch --show-current)" --state merged --json number
```

| Current state | Action |
|---|---|
| On `main` | Create a fresh branch off updated main |
| Feature branch, already merged, no commits beyond `origin/main` | Stale — create a fresh branch off updated main; uncommitted changes carry over with the checkout (stash → pull → branch → pop if the checkout conflicts) |
| Feature branch, not merged (unmerged commits or an open PR) | Live work — use it as-is, skip branch creation. When splitting, only the group related to this branch's work stays here; the rest get fresh branches off main |
| Merged AND new local commits on top | The one ambiguous case — ask: fresh branch off main, or continue on this one? |

Fresh-branch mechanics: `git checkout main && git pull && git checkout -b <branch>`.

**Branch name (fixed format):** `<type>/<short-slug>` — `type` is the conventional-commit type of the dominant change group, slug is 2–4 kebab-case words. Examples: `feat/ship-skill`, `fix/null-order-totals`.

## Step 3: Commit

Commit using the **`smart-git-commit`** skill workflow, reusing the groups from Step 1: one conventional commit per group, then push. If that skill is unavailable, fall back to one conventional commit (lowercase type, imperative subject) per group, pushed with `git push -u origin HEAD`.

## Step 4: Open the PR

```bash
gh pr create --base main --title "<conventional subject>" --body "$(cat <<'EOF'
## Summary
- one bullet per commit group

EOF
)"
```

- **Title** — the conventional-commit subject of the dominant change (e.g. `feat: add ship skill`). Squash merge makes the title the commit on `main`, so it must itself be a valid conventional commit.
- **Body** — `## Summary` with 2–4 bullets, one per commit group. No test-plan boilerplate.
- **No em dashes (—)** in the title or body — use a comma, colon, or parentheses, or rewrite the sentence. Same rule as the commit messages.

## Step 5: Merge and clean up

- Invoked with `clean` → proceed without asking.
- Otherwise ask: "Merge and clean up (squash-merge the PR, delete the local and remote branch)?"
  - **No** → leave the PR open, print its URL, and stop. Delete nothing.

On yes (or `clean`):

```bash
gh pr merge --squash --delete-branch
```

This squash-merges the PR, deletes the remote and local branch, and checks out `main`. Finish with `git pull` so the session ends on an up-to-date main.

**If the merge is blocked** (required checks pending, branch protection):

```bash
gh pr merge --squash --delete-branch --auto
```

Report "checks pending — auto-merge armed; it will land when green" and stop. The local branch stays for now; the next `/ship` run's stale-branch detection cleans it up.

## Safety rules

- NEVER force-push, never skip hooks (`--no-verify`), never commit likely secrets (`.env`, credentials, tokens) — same rules as smart-git-commit.
- NEVER delete a branch that is not confirmed merged.
- NEVER merge without either the `clean` argument or an explicit yes.
- If anything fails mid-flow (rejected push, conflict on `git pull`), stop and report — do not improvise recovery.
