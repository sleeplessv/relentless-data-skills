# land

The `land` agent skill takes the changes in your working tree to a merged pull
request in one run. It creates a branch off `main`, commits the changes in the
`smart-git-commit` style, and opens a PR. It then squash-merges the PR and
deletes the local and remote branches.

The skill sets `disable-model-invocation: true`, so it never starts from
conversation. Run it as `/land`: it merges and cleans up without asking
once CI is green. Add "don't merge" or "ask first" to stop or ask before the
merge. On a clean tree it resumes from where the branch stands: an open
PR goes to the CI wait and merge, commits that are not pushed yet go to the push
and PR. On `main` with unpushed commits it stops and names them.

## What it does

The skill runs these steps in order:

1. **Groups the changes.** It groups the changes by the area they affect before
   it creates any branch. If the groups have different intents and don't fit
   under one PR title, it asks whether to ship them as separate PRs. It always
   asks, because a merge nobody confirms must never bundle unrelated work.
2. **Picks the branch.** It reads the git and `gh` state and asks only in the
   one ambiguous case:
   - On `main`, it creates a branch off the updated `main`.
   - On a branch that is already merged, it moves the changes to a new branch
     off `main`. It uses `gh pr list` to detect squash merges, because a squash
     merge is not a git ancestor.
   - On a branch with unmerged commits or an open PR, it stays on that branch.
   - On a merged branch with new local commits, it asks which branch to use.

   New branch names use the format `<type>/<short-slug>`, for example
   `feat/land-skill`.
3. **Commits and pushes.** It commits through the
   [`smart-git-commit`](../smart-git-commit) skill, one conventional commit per
   group. Then it pushes the branch itself.
4. **Opens the PR.** The title is a conventional-commit subject, because the
   squash merge makes the title the commit on `main`. The `pr` skill writes the
   body. If `pr` isn't installed, the body is a short Summary with one bullet
   per commit group.
5. **Waits for CI.** It runs `gh pr checks --watch --fail-fast` before it
   merges. A failing or cancelled check stops the run and
   leaves the PR open. If no checks appear but the repo has PR-triggered
   workflows, it reads the checks up to five more times, then asks you before
   it merges. It merges without checks only when the repo has no PR CI, and the
   final report says so.
6. **Merges.** It runs `gh pr merge <number> --squash --delete-branch`. It does not
   ask first unless you said "don't merge" or "ask first". If you decline, it
   leaves the PR open and deletes nothing.
7. **Confirms the outcome.** It reads the PR state from GitHub and ignores the
   exit code of `gh`. For a merged PR, it checks out and pulls `main`, then
   confirms that the squash commit is on local `main` and that both branches
   are gone. If branch policy or required checks refuse the merge, it retries
   with `--auto`. If the repo uses a merge queue, it reports the PR as queued.

The final report starts with the outcome: merged, merged with incomplete
cleanup, auto-merge armed, queued, stopped on failing checks, or PR left open.
It also names every branch that still exists after the run.

## Install

See the [repo root README](../../README.md) for the general install patterns
(`npx skills`, Claude Code plugin, manual clone). For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/land
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install land@relentless-data-skills
```

## Files

- `SKILL.md` has the full workflow: preflight, branch selection, commit, PR, merge, cleanup, and safety rules.
- `plugin.json` is the Claude Code plugin manifest.

## Requirements

- `git` with an `origin` remote.
- The GitHub CLI (`gh`), authenticated.
- Network access to GitHub. Run `gh`, `git fetch`, `git pull`, and `git push`
  outside any sandbox. Inside one, they fail with misleading DNS and connection
  errors.
- The `smart-git-commit` skill. Without it, land uses a shorter built-in
  commit workflow.
- The `pr` skill, loaded with the Skill tool during Step 4. Without it, land
  writes a plain Summary body.
- A permission rule that allows `gh pr merge`, for unattended `/land`
  runs in background or auto mode. Without the rule, the merge stops at a
  permission prompt.
