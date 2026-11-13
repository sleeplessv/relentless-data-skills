# AGENTS.md

## Working in this repo

- **Version bump.** A PR that changes any tracked file under `skills/<name>/`, docs included, bumps that skill once: `git fetch origin main`, `git add` any new files, run `python3 scripts/skill_versions.py --write`, and commit what it rewrites. `main` requires the `skill-version-check` check on an up-to-date branch, so when another PR merges first, update your branch and run the command again. Bump size and edge cases: [Version skill changes](README.md#version-skill-changes).
- **Checks.** Run `scripts/check.sh` before each commit; the change is ready when it prints `All checks passed.` Tests are stdlib `unittest`: `python3 -m unittest tests.test_<name>` runs one file.
- **Standards.** Before writing or reviewing a change to a skill, script, or test, read `CODING_STANDARDS.md`: the judgement-call rules that lint and CI leave to the author. Review findings cite the rule ID.
- **Installed copies.** A skill invoked by name runs from its installed copy (such as `~/.claude/skills/<name>`), which merging leaves at its old version until it is updated ([Install](README.md#install)). To exercise an edit, follow `skills/<name>/SKILL.md` from this tree, or hand a subagent that path.
- **Shared checkout.** Several sessions use this checkout at once. If your session finds it on a branch other than `main`, or holding uncommitted changes outside your task, those belong to another session: leave them in place and work in a new git worktree cut from `origin/main`.
- **Scratch.** Notes and logs meant to outlive the session go in `.scratch/` (git-ignored).

## Agent skills

### Issue tracker

Issues (and specs) are tracked as GitHub Issues on `sleeplessv/relentless-data-skills` via the `gh` CLI; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage labels are used verbatim: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
