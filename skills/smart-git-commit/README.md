# smart-git-commit

The **`smart-git-commit`** agent skill: inspect all working-tree changes, group
them by affected area, create one conventional commit per group, and push to
remote when asked.

## What it does

- **Grouping.** Splits changes into independently-reviewable commits by
  subsystem or directory, keeps a change together with its own tests and
  docs, and borrows area names from the repo's own conventions (recent
  commit subjects, `CLAUDE.md`, `README`).
- **Conventional commits.** Lowercase type prefixes (`feat`, `fix`, `docs`,
  `refactor`, `test`, `chore`, `style`), imperative mood, ~72-char subjects.
  History wins on flavor (adopts `feat(scope):` if the repo uses scopes); the
  skill wins on format, always conventional, even in repos that aren't.
- **Push only when asked.** Pushes after all commits are created when the
  request asks for it ("commit and push", or a calling skill such as `ship`),
  setting the upstream if the branch doesn't have one yet. A plain "commit"
  leaves the commits local and the close-out says nothing was pushed.
- **Safety rules.** Never amends pushed commits, never force-pushes
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

- `SKILL.md`: the full workflow (inspect, group, type, commit, optional push, safety rules).
- `plugin.json`: Claude Code plugin manifest.

## Requirements

- `git`, with a remote configured if you ask for the push.
- Network access to the remote when pushing. `git push` must run outside any
  sandboxed shell, or it fails with a misleading DNS/connection error.
