# Coding standards

Judgement-call rules for reviewing changes to this repo's skills, scripts, and docs. A reviewer
applies them to the diff at review time and cites the rule ID. Mechanical checks (frontmatter keys,
line budget, description length, registry sync) belong to `scripts/lint_skill.py`,
`scripts/sync_registry.py`, and CI, so they are left out here.

Each rule is one statement followed by why it exists or an example. The background research is in
[docs/research/skill-authoring-best-practices.md](docs/research/skill-authoring-best-practices.md).

## Side effects

- **SE1. A skill whose steps have outward side effects is user-only (`disable-model-invocation: true`),
  unless it performs them only when the user asked for them.** Side effects include pushing, merging,
  PR or issue comments, and claiming issues.
  Why: a model-invocable `implement-ticket` could claim issues unasked; `smart-git-commit` pushed on a plain "commit".
- **SE2. Any merge or ship path stops on failing or pending CI, and treats "no checks reported" as
  unknown until it has looked for CI (workflow triggers, `gh run list` for the head SHA).**
  Why: `ship clean` could squash-merge a red PR, and push-only Actions CI can register after the first read.
- **SE3. Pushes never force; a rejected push stops and reports.** One rule, stated once.
  Why: `ship` and `smart-git-commit` drifted into two different force-push policies.
- **SE4. Destructive git steps (branch delete, worktree remove) check the expected tip, ancestry, and
  that no worktree has the branch checked out, before acting.**
  Why: `git update-ref -d` deleted a branch under a live worktree and stranded its uncommitted work.
- **SE5. Model-invocable skills whose runs are expensive (large fan-out, installs, publishing) justify
  staying model-invocable, or become user-only.**
  Why: a stray "what feeds this table?" could trigger `fabric-lineage-dag`'s seven-agent run.

## Commands and scripts

- **CS1. Skills never edit their installed scripts or files; a run that patches a script copies it to
  a scratch location first and logs the patch.**
  Why: parallel extractors patching the installed `lineage_common.py` would race each other and change the skill for every later run.
- **CS2. A shell command added to a skill names every variable it uses, states its guard semantics
  (which exit codes pass), and is exercised in a throwaway repo or covered by a test in `tests/`.**
  Why: an untested `git ls-remote --exit-code` guard returned 2 on every fresh run and dead-ended integration.
- **CS3. The runner or command a skill records in its context file is the one the skill and its
  scripts invoke.**
  Why: `dbt-runner --connect` ran bare `dbt debug` while the context file said `uv run dbt`.
- **CS4. Commands in reference files and examples obey the same rules as SKILL.md.**
  Why: the agent copies from the reference it just loaded; bare `dbt` in `failures.md` undid "never bare `dbt`".
- **CS5. Skills resolve the default branch (`gh repo view --json defaultBranchRef`) instead of
  hard-coding `main`.** Why: `ship` and `review-pbi-diff` broke on `master`-default repos.
- **CS6. Every "done" gate a skill relies on is checkable by a command with an exit code or output,
  and the skill asks for that evidence.** Why: `render.py` warned on unmapped keys and still wrote the report.
- **CS7. A safety boundary that must hold every time (a wrapper the agent must not bypass) is enforced
  by a hook, or the change says why prose is enough.**
  Why: raw `snow sql` or `curl` was one Bash call away from bypassing `snowman` and `metabase`.

## Contracts between skills

- **CT1. A change to a shared contract between skills updates the README's minimum compatible pair and
  both call sites in the same PR.** Example: `implement-feature` reads `implement-ticket`'s
  `references/review-and-pr.md`.
- **CT2. Cross-skill references resolve from each installed skill's root by path, not by relative
  sibling links.** Why: plugin installs put each skill in its own directory, so `../implement-ticket/` breaks.
- **CT3. Every optional dependency (another skill, an external CLI, the Artifact tool) has a stated
  fallback in the step that uses it.**
  Why: steps gated on `unslop` or the Artifact tool had no ending when either was missing.
- **CT4. A skill's description competes with no sibling skill for the same request.**
  Why: `snowman` and `metabase` both matched "run this SQL against our warehouse".

## Content

- **CN1. Each rule lives in one place; other sites link to it.**
  Why: `implement-ticket` stated the `needs-info` stop twice, with and without its exception.
- **CN2. One term per concept, defined once.**
  Why: `implement-feature` used several names for the verified integration tip.
- **CN3. Material only some branches need moves to `references/` behind a pointer that says when to
  read it; long packed lines that fit the line budget count as that material.**
  Why: `implement-ticket` fit its 150-line budget only by packing 120-word paragraphs into single lines.
- **CN4. General skills hold no client- or project-specific names or paths.**
  Why: hard-coded `dataops/modelling/.env` could make `metabase` read another project's API key.
