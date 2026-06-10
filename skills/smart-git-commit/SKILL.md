---
name: smart-git-commit
description: Groups changed files by affected area, creates one conventional commit per group, then pushes to remote. Use when the user asks to commit changes, create commits, stage and commit, or commit and push. Follows conventional commit format with lowercase type prefixes.
---

# Smart Git Commit

Inspect all changes, group them by affected area, create one commit per group using conventional commit format, then push to remote.

## Workflow

### Step 1: Inspect changes

Run these in parallel:

- `git status` — see all modified/untracked files
- `git diff` — see unstaged changes
- `git diff --cached` — see staged changes
- `git log --oneline -10` — learn the repo's commit conventions (scopes, area names)

If there is nothing to commit, say so and stop.

### Step 2: Group files by area

Split the changes into logical groups, each independently reviewable:

- Group by subsystem or top-level directory (e.g. `api/`, `docs/`, `.github/workflows/`, a service, a model layer).
- Keep a change together with its own tests and docs when they belong to the same logical change.
- Take area names from the repo's own conventions — recent commit subjects, `CLAUDE.md`, `README` — rather than inventing new ones.
- Bundle files that don't fit neatly with the closest related group.
- Treat already-staged files like any other change: they join their group and are re-staged with it.

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

History wins on flavor, the skill wins on format: if recent commits use scopes (`feat(api): …`), use the same scopes; otherwise use bare types. Always produce conventional commits, even when the repo's history doesn't.

### Step 4: Commit each group

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
- Imperative mood: "add", "fix", "update" — not "added", "fixes"
- Max ~72 chars on the subject line
- No period at the end of the subject line
- Body only when the why isn't obvious from the subject

**Examples:**

```
feat: add customer metrics endpoint
fix: handle null totals in order aggregation
docs: document retry behavior for ingestion jobs
refactor: simplify date-parsing helpers
test: cover empty-cart checkout path
chore: update CI workflow schedule
```

### Step 5: Push to remote

After all commits are created:

```bash
git push
```

If the branch has no upstream yet:

```bash
git push -u origin HEAD
```

**Run the push outside the sandbox.** `git push` needs network access to reach the remote; a sandboxed shell blocks it, and the failure surfaces as a DNS/connection error that looks like an auth or remote problem. If the push fails with a connection error, suspect the sandbox first.

## Safety Rules

- NEVER amend commits that have already been pushed
- NEVER force push to `main` or `master`
- NEVER skip hooks (`--no-verify`)
- NEVER commit files that likely contain secrets (`.env`, credentials, tokens)
- If `git push` is rejected (non-fast-forward), stop and tell the user — do not force push
