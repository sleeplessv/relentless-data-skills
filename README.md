# relentless-data-skills

A collection of [agent skills](https://docs.claude.com/en/docs/claude-code/skills)
maintained by **Relentless Data**. Each skill lives in its own directory under
`skills/` and installs independently — pick the ones you want.

## Skills

| Skill | What it does |
| --- | --- |
| [`implement-issue`](skills/implement-issue/) | Take a GitHub issue from open to draft PR: claim, branch, implement, run tests + a runtime smoke check, with explicit stop conditions. |
| [`prefect`](skills/prefect/) | Version-aware Prefect 3 guidance: a live docs-lookup protocol, CLI-first instance queries, and house standards. Prefect 2.x out of scope. |
| [`smart-git-commit`](skills/smart-git-commit/) | Group working-tree changes by affected area, create one conventional commit per group, then push — with safety rules against force-pushes, skipped hooks, and committed secrets. |
| [`ship`](skills/ship/) | Command-only (`/ship`): take working-tree changes from branch to merged PR — branch off main, commit via smart-git-commit, open a PR, then squash-merge and delete local + remote branch (asks first, unless `/ship clean`). Detects unrelated changes and offers to split them into separate branches/PRs. |
| [`visual-report`](skills/visual-report/) | Produce a single self-contained HTML visual report — an explainer or diagram-heavy writeup of a system, process, or findings, built with Tailwind + Mermaid. |
| [`snowman`](skills/snowman/) | Read-only Snowflake exploration via the `snow` CLI: schema discovery, profiling, hypothesis testing, data-quality investigation. Bootstraps a committed per-project context; a wrapper hard-enforces read-only. |
| [`orchestrator-mode`](skills/orchestrator-mode/) | Turns the main thread into a pure coordinator that delegates ALL work to subagents — plan, parallel-dispatch, verify with a separate agent, synthesize. Agent-neutral across Claude Code and Cursor. |
| [`dbt-runner`](skills/dbt-runner/) | Invocation discipline and failure triage for running dbt: a static preflight script catches environment failures before the first command, invocation rules prevent self-inflicted ones, and a signature-indexed catalogue maps error strings to ranked causes and fixes (including dbt-fusion quirks). Bootstraps a committed per-project context. |
| [`dlt-bootstrap`](skills/dlt-bootstrap/) | Bootstrap a dlt ingestion project: install the dltHub AI Workbench project-scoped (only the toolkits the project needs), then commit house conventions (Snowflake, Prefect, DuckDB dev loop) as an always-on rule. Idempotent re-runs add new source types. |

## External skills (references)

Skills we use alongside this collection but don't maintain here — install them
from their upstream repos:

| Skill | Upstream | Install |
| --- | --- | --- |
| `terraform-skill` | [antonbabenko/terraform-skill](https://github.com/antonbabenko/terraform-skill) | `npx skills add antonbabenko/terraform-skill` |
| `llm-council` | based on [karpathy/llm-council](https://github.com/karpathy/llm-council) (methodology) | local SKILL.md adaptation; no upstream package |

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

- `skills/<skill>/` — each skill is self-contained: `SKILL.md`, a `plugin.json`, a `README.md`, and any `references/`.
- `scripts/` — CI integrity checks. Repo tooling only; not installed with any skill.
- `.claude-plugin/marketplace.json` — declares the repo as a Claude Code marketplace, one plugin entry per skill.

## Maintenance / CI

GitHub Actions runs integrity checks on push, PR, and weekly:

- **`scripts/lint_skill.py`** — lints every `skills/*/SKILL.md`: required frontmatter, a "Use when" trigger in the description, and the per-file line budget.
- **`scripts/check_doc_urls.py`** — for skills that ship a `references/docs-map.md`, fetches every doc URL and fails if any no longer resolves (catches upstream docs moving/renaming pages).
- **`scripts/check_registry.py`** — every skill must have a row in the README table and a marketplace.json entry, and the marketplace entry must mirror the skill's `plugin.json` (name, version, description). Catches skills landing unregistered and registry drift.

Both use the Python standard library only — no dependencies to install.

## License

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
