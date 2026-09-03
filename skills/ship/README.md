# ship

The `ship` agent skill takes the current working-tree changes from branch
to merged PR in one pass: branch off `main`, commit smart-git-commit style,
open a PR, then squash-merge and clean up the local and remote branch.

Command-only (`disable-model-invocation: true`): it never auto-triggers from
conversation; invoke it explicitly as `/ship`, or `/ship clean` to skip the
merge confirmation.

## What it does

- Branch selection is decided from git/gh state, not by asking. On `main`
  it branches off updated main; on a stale already-merged branch it carries
  the changes onto a fresh branch off main (detecting squash merges via
  `gh pr list`, since they aren't git ancestors); on a live feature branch it
  stays put. Only the genuinely ambiguous case (merged branch with new local
  commits) prompts.
- Unrelated-work detection groups the changes first. If they wouldn't
  sit honestly under one PR title, it asks whether to split into separate
  branches/PRs (this prompt fires even under `clean`; silently bundling
  unrelated work is exactly what `clean` must not do).
- Branch names follow a fixed format: `<type>/<short-slug>`, e.g. `feat/ship-skill`.
- Commits go through the [`smart-git-commit`](../smart-git-commit)
  skill: grouped, conventional, pushed.
- The PR gets a conventional-commit title (it becomes the squash commit on `main`)
  and a short bulleted Summary body.
- Merge and cleanup run as `gh pr merge --squash --delete-branch`, then `git pull`
  on main; it asks first unless invoked with `clean`. It falls back to `--auto` when
  required checks are still pending. Declining leaves the PR open and deletes
  nothing.

## Install

See the [repo root README](../../README.md) for the general install patterns
(`npx skills`, Claude Code plugin, manual clone). For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/ship
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install ship@relentless-data-skills
```

## Files

- `SKILL.md` has the full workflow: preflight, branch selection, commit, PR, merge, cleanup, safety rules.
- `plugin.json` is the Claude Code plugin manifest.

## Requirements

- `git` with an `origin` remote.
- `gh` (GitHub CLI), authenticated.
- Network access to GitHub. `gh` and `git fetch`/`pull`/`push` must run
  outside any sandboxed shell, or they fail with misleading DNS/connection
  errors.
- The `smart-git-commit` skill installed (a condensed fallback is built in).
- For fully unattended `/ship clean` runs (background or auto modes), a
  permission rule allowing `gh pr merge`. Merging a just-created PR otherwise
  stops at a permission prompt.
