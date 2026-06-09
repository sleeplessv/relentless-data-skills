# smart-git-commit

The **`smart-git-commit`** agent skill: inspect all working-tree changes, group
them by affected area, create one conventional commit per group, then push to
remote.

## What it does

- **Grouping** — splits changes into independently-reviewable commits by
  subsystem or directory, keeping a change together with its own tests and
  docs, and borrowing area names from the repo's own conventions (recent
  commit subjects, `CLAUDE.md`, `README`).
- **Conventional commits** — lowercase type prefixes (`feat`, `fix`, `docs`,
  `refactor`, `test`, `chore`, `style`), imperative mood, ~72-char subjects.
  History wins on flavor (adopts `feat(scope):` if the repo uses scopes), the
  skill wins on format (always conventional, even in repos that aren't).
- **Push on completion** — pushes after all commits are created, setting the
  upstream if the branch doesn't have one yet.
- **Safety rules** — never amends pushed commits, never force-pushes
  `main`/`master`, never skips hooks, never commits likely secrets, and stops
  (rather than force-pushing) on a rejected push.

## Install

See the [repo root README](../../README.md) for the general install patterns
(`npx skills`, Claude Code plugin, manual clone). For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/smart-git-commit
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install smart-git-commit@relentless-data-skills
```

It activates when you ask to commit changes, create commits, stage and commit,
or commit and push.

## Files

- `SKILL.md` — the full workflow: inspect, group, type, commit, push, safety rules.
- `plugin.json` — Claude Code plugin manifest.

## Requirements

- `git`, with a remote configured if you want the final push to succeed.
