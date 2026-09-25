# relentless-data-skills

A collection of [agent skills](https://code.claude.com/docs/en/skills)
maintained by **Relentless Data**. Each skill lives in its own directory under
`skills/` and installs independently. Pick the ones you want.

## Skills

<!-- skills-table:begin -->
| Skill | What it does |
| --- | --- |
| [`dbt-runner`](skills/dbt-runner/) | Run dbt commands and diagnose failures with project setup checks and captured output. |
| [`dlt-bootstrap`](skills/dlt-bootstrap/) | Set up dlt projects with the dltHub AI Workbench and Relentless Data conventions. |
| [`fabric-lineage-dag`](skills/fabric-lineage-dag/) | Build interactive lineage graphs and coverage reports from Microsoft Fabric workspaces exported to Git. |
| [`gh-weekly-report`](skills/gh-weekly-report/) | Create interactive weekly reports of a GitHub user's activity across repositories. |
| [`implement-feature`](skills/implement-feature/) | Implement a feature specification or selected tickets as one verified pull request. |
| [`implement-ticket`](skills/implement-ticket/) | Implement a GitHub ticket, verify the result, and prepare a pull request for review. |
| [`metabase`](skills/metabase/) | Query and manage Metabase questions and dashboards, trace dependencies, and check dashboard configuration. |
| [`orchestrator-mode`](skills/orchestrator-mode/) | Coordinate work through subagents with scoped delegation, shared evidence, and verification. |
| [`prefect`](skills/prefect/) | Build, review, and debug Prefect 3 projects using documentation and live instance evidence. |
| [`qualify-delegation`](skills/qualify-delegation/) | Qualify assignments for human colleagues or contractors and produce clear handoffs with explicit outcomes, authority, and constraints. |
| [`review-pbi-diff`](skills/review-pbi-diff/) | Review Power BI PBIP changes with page layouts, DAX checks, and ranked findings. |
| [`ship`](skills/ship/) | Commit, publish, and merge working-tree changes through a pull request. |
| [`smart-git-commit`](skills/smart-git-commit/) | Group working-tree changes into conventional commits and push them to the remote. |
| [`snowman`](skills/snowman/) | Explore Snowflake data, investigate data quality, and prepare SQL changes for manual execution. |
| [`visual-report`](skills/visual-report/) | Create single-file HTML reports that explain systems, processes, findings, or decisions through diagrams and interactive visuals. |
<!-- skills-table:end -->

This table is generated from each skill's `plugin.json`. Edit there, then
run `python scripts/sync_registry.py --write`.

## External skills (references)

Skills we run alongside this collection but don't maintain here. Install them
from their upstream repos.

### Matt Pocock's engineering skills

[mattpocock/skills](https://github.com/mattpocock/skills) is the flow the
`implement-*` skills here plug into: `grill-with-docs` sharpens an idea,
`to-spec` turns the thread into a spec, `to-tickets` splits it into tickets, and
`implement` builds each one by driving `tdd`, closing with `code-review`. Run
`setup-matt-pocock-skills` once per repo first. It writes the issue-tracker,
triage-label, and domain-doc conventions the rest assume, which is where this
repo's `docs/agents/` files and the `## Agent skills` block in `CLAUDE.md` come
from. `ask-matt` is the router if you forget which one to reach for.

The rest we keep installed, by job:

- Planning and shaping: `grilling`, `grill-me`, `batch-grill-me`,
  `to-questionnaire`, `wayfinder` (for work too big for one session),
  `prototype`, `handoff` and `claude-handoff` for moving a thread between
  sessions.
- Code: `triage`, `diagnosing-bugs`, `codebase-design`,
  `improve-codebase-architecture`, `domain-modeling`,
  `resolving-merge-conflicts`.
- Everything else: `research`, `wizard`, `wait-what`, `writing-for-agents`,
  `writing-great-skills`.

```bash
npx skills add mattpocock/skills -g -y \
  -s setup-matt-pocock-skills -s ask-matt \
  -s grill-with-docs -s to-spec -s to-tickets -s implement -s tdd -s code-review \
  -s grilling -s grill-me -s batch-grill-me -s to-questionnaire -s wayfinder \
  -s prototype -s handoff -s claude-handoff \
  -s triage -s diagnosing-bugs -s codebase-design \
  -s improve-codebase-architecture -s domain-modeling -s resolving-merge-conflicts \
  -s research -s wizard -s wait-what -s writing-for-agents -s writing-great-skills
```

Skill names are flat, so the folder a skill sits in upstream (`engineering/`,
`productivity/`, `in-progress/`) does not appear in the command. Drop `-g` to
install into the current project instead of `~/.claude/skills`, add
`-a '*'` to link into every detected agent, and `-l` lists what a repo offers
without installing anything.


### Cursor's pstack

[cursor/plugins](https://github.com/cursor/plugins) is Cursor's plugin repo.
`pstack` is the one worth having in every agent, and it has grown well past
`unslop`:

- `unslop` strips AI tells from anything you write. It is an always-on rule, not
  something you invoke.
- `technical-writing` is the standard behind docs, RFCs, PR bodies and commit
  messages (Diataxis structure, Google developer style, STE instruction rules,
  Global English syntax).
- `why` answers "why does this work this way" by querying whatever MCPs are
  connected, across git history, the issue tracker, docs, chat and
  observability, and citing what it found. `teach` runs it and explains the
  result plainly.
- `blast-radius` looks for what a change breaks outside its own diff, then runs
  code to prove the one fact that makes it safe.
- Seven `principle-*` rules load per situation rather than on request:
  `fix-root-causes`, `prove-it-works`, `laziness-protocol`,
  `guard-the-context-window`, `make-operations-idempotent`,
  `sequence-verifiable-units`, `encode-lessons-in-structure`. Together they
  are most of what stops an agent declaring done on a proxy.
- `bro` is the tone knob.

From the same repo, `thermos`, `thermo-nuclear-review` and the `cursor-team-kit`
version, `thermo-nuclear-code-quality-review`, are a harsher code-quality pass
than `code-review`, for when you want the diff torn apart rather than reviewed.

```bash
npx skills add cursor/plugins -g -y \
  -s unslop -s technical-writing -s why -s teach -s blast-radius -s bro \
  -s principle-fix-root-causes -s principle-prove-it-works \
  -s principle-laziness-protocol -s principle-guard-the-context-window \
  -s principle-make-operations-idempotent -s principle-sequence-verifiable-units \
  -s principle-encode-lessons-in-structure \
  -s thermos -s thermo-nuclear-review -s thermo-nuclear-code-quality-review
```

Use `-s` to select skills from the repo's plugins.
`npx skills add cursor/plugins -l` lists the available skills.


Inside Cursor these install as plugins from the built-in registry instead, and
Cursor's own bundled skills are already there. `split-to-prs` is the one we
reach for outside Cursor too, so it is worth symlinking into `~/.claude/skills`.

### Others

| Skill | Upstream | Install |
| --- | --- | --- |
| `find-skills` | [vercel-labs/skills](https://github.com/vercel-labs/skills) | `npx skills add vercel-labs/skills -g -y -s find-skills` |
| `frontend-design` | [anthropics/claude-code](https://github.com/anthropics/claude-code) | `npx skills add anthropics/claude-code -g -y -s frontend-design` |
| `terraform-skill` | [antonbabenko/terraform-skill](https://github.com/antonbabenko/terraform-skill) | `npx skills add antonbabenko/terraform-skill -g -y` |
| `llm-council` | based on [karpathy/llm-council](https://github.com/karpathy/llm-council) (methodology) | local SKILL.md adaptation, no upstream package |

## Install

Every skill installs the same three ways. Substitute `<skill>` with a skill
directory name from the table above (e.g. `prefect`).

### `npx skills` (cross-agent: Claude Code, Cursor, Codex, OpenCode, …)

```bash
npx skills add sleeplessv/relentless-data-skills/skills/<skill>
```

`npx skills list` / `update` / `remove` manage installed skills afterward.

### Claude Code plugin

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install <skill>@relentless-data-skills
```

(Or from the shell: `claude plugin marketplace add sleeplessv/relentless-data-skills`
then `claude plugin install <skill>@relentless-data-skills`.)
Update later with `/plugin marketplace update relentless-data-skills`.

### Manual clone (any SKILL.md-aware agent)

```bash
git clone https://github.com/sleeplessv/relentless-data-skills.git
# symlink (or copy) just the skill dir you want:
ln -s "$(pwd)/relentless-data-skills/skills/<skill>" ~/.claude/skills/<skill>
```

## Repo layout

- `skills/<skill>/`: each skill is self-contained, with `SKILL.md`, a `plugin.json`, a `README.md`, and any `references/`.
- `scripts/`: CI integrity checks. Repo tooling only; not installed with any skill.
- `.claude-plugin/marketplace.json`: declares the repo as a Claude Code marketplace, one plugin entry per skill. The `plugins` array is generated from each skill's `plugin.json` by `scripts/sync_registry.py`.

## Maintenance and CI

GitHub Actions runs validation on pushes to `main`, pull requests, a weekly
schedule, and manual dispatch. See [the CI workflow](.github/workflows/ci.yml)
for the schedule and Python versions.

- `python3 -m unittest discover -s tests -v` runs the repository's Python tests.
- `python3 scripts/lint_skill.py` checks skill frontmatter, invocation triggers,
  description lengths, line budgets, and YAML-safe values.
- `python3 scripts/check_doc_urls.py` checks HTTPS URLs marked with `=>` in
  `skills/*/references/docs-map.md`. It fails when a marked URL no longer resolves.
- `python3 scripts/sync_registry.py --check` checks that the marketplace entries
  and README skills table match each skill's `plugin.json`.
- `python3 scripts/skill_versions.py --check --base origin/main` checks skill
  versions against the fetched `main` branch. CI compares the proposed merge
  with its base branch, or a push with its previous commit. Scheduled and manual
  runs validate current metadata without requiring a historical bump.

After editing a skill's `plugin.json`, run
`python3 scripts/sync_registry.py --write` to regenerate the catalog.

The root Python validation scripts use only the standard library and require
no dependency installation. Individual skills can have additional dependencies.

### Version skill changes

Every pull request that changes a tracked file inside a skill folder requires
one version bump for that skill. This includes README edits, assets, scripts,
file deletions, and permission changes. Changes outside skill folders do not
require skill bumps. The final diff determines which skills changed.

Fetch `main` before preparing a bump:

```bash
git fetch origin main
```

Merge or rebase onto `origin/main` if it has advanced. Stage new skill files
with `git add` so the command can include them. Then run:

```bash
python3 scripts/skill_versions.py --write
```

The command compares tracked working-tree files, including staged and committed
changes, with `origin/main`. It bumps changed skills and regenerates the registry.
Review and stage the resulting changes before committing. Re-running the command
preserves versions already higher than the baseline. If another PR has consumed
your version number, update your branch and run the command again.

The default bump increments the patch number. Use `--bump minor` or `--bump major`
for a deliberate larger bump. These options apply to changed skills that still
need a bump. To choose a different bump for one skill, edit its `plugin.json`
before running the command. Use `--base <commit-or-ref>` for an explicit baseline.

Versions use three numeric components, such as `0.2.1`, without prerelease or
build suffixes. New and renamed skills start at `0.1.0`. Removing an entire skill
removes its registry entry. Reverting content still requires a newer version.
The marketplace's own version and nested package versions remain independent.
Skill folders, `SKILL.md`, and `plugin.json` must be regular tracked files and
directories within this repo, rather than symlinks to content elsewhere.

The `main` ruleset requires pull requests, the `skill-version-check` check, and
an up-to-date branch. That check also validates the generated registry.
See the [versioning decision](docs/adr/0001-skill-version-boundary.md) for the
scope and rationale.

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
