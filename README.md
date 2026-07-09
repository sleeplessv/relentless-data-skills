# relentless-data-skills

A collection of [agent skills](https://docs.claude.com/en/docs/claude-code/skills)
maintained by **Relentless Data**. Each skill lives in its own directory under
`skills/` and installs independently — pick the ones you want.

## Skills

<!-- skills-table:begin -->
| Skill | What it does |
| --- | --- |
| [`dbt-runner`](skills/dbt-runner/) | Invocation discipline and failure triage for running dbt — a static preflight script kills environment failures before the first command, invocation rules prevent the self-inflicted ones (sandboxed shells, piped output, silent empty selections), and a signature-indexed catalogue maps error strings to ranked causes and fixes, including dbt-fusion quirks. Bootstraps a committed per-project context file. |
| [`dlt-bootstrap`](skills/dlt-bootstrap/) | Bootstrap a dlt ingestion project: install the dltHub AI Workbench project-scoped (only the toolkits the project needs), then layer Relentless Data house conventions (Snowflake, Prefect, DuckDB dev loop) as a committed always-on rule. Idempotent re-runs add new source types. |
| [`gh-weekly-report`](skills/gh-weekly-report/) | Generate a weekly GitHub activity report — the authenticated user's issues, PRs, reviews, and commits across one account's repos, bucketed into canonical work types (feature, fix, refactor, docs, chore/infra, triage/review), rendered as a fully self-contained interactive HTML file with week-over-week deltas, per-repo breakdown, and drill-down to every item. |
| [`implement-feature`](skills/implement-feature/) | Implement a whole feature as one PR: orchestrate subagents over a spec's tickets on a shared integration branch — waves of ticket branches, integrated review + tests, and a single feature PR to main. |
| [`implement-ticket`](skills/implement-ticket/) | Implement a ticket (GitHub issue) end-to-end: claim it, branch, code in small commits, run tests + a runtime smoke check, and open a draft PR — with explicit stop conditions instead of improvising. Formerly implement-issue. |
| [`orchestrator-mode`](skills/orchestrator-mode/) | Forces the main thread to act as an orchestrator and delegate ALL work to subagents instead of doing it itself — plan, dispatch, verify with a separate agent, synthesize. Agent-neutral across Claude Code, Cursor, and Cortex Code. |
| [`prefect`](skills/prefect/) | Version-aware Prefect 3 guidance: a live docs-lookup protocol, CLI-first instance queries, and house standards. Prefect 2.x out of scope. |
| [`review-pbi-diff`](skills/review-pbi-diff/) | Turn a Power BI (PBIP) git diff into a manager-ready review artifact — a deterministic extractor builds a structured change model from hash-named visual.json and TMDL files, then the agent draws to-scale page wireframes, spec-checks every added/modified measure's DAX against the repo's metric definitions, and runs eleven evidence-backed red-flag checks (dangling measure references, ripple effects, hidden filters, visible scratch pages). |
| [`ship`](skills/ship/) | Take working-tree changes from branch to merged PR in one pass — branch off main, commit smart-git-commit style, open a PR, then squash-merge and delete the local and remote branch. Command-only: /ship asks before merging, /ship clean goes straight through. Detects unrelated changes and offers to split them into separate branches/PRs. |
| [`smart-git-commit`](skills/smart-git-commit/) | Groups changed files by affected area, creates one conventional commit per group, then pushes to remote — with safety rules against force-pushes, skipped hooks, and committed secrets. |
| [`snowman`](skills/snowman/) | Read-only Snowflake exploration via the snow CLI — schema discovery, profiling, hypothesis testing, and data-quality investigation. Bootstraps a committed per-project context; a guardrail wrapper hard-enforces read-only execution and stages user-requested DML/DDL as scripts for manual execution. |
| [`visual-report`](skills/visual-report/) | Produce a single self-contained HTML visual report — an explainer, writeup, or diagram-heavy document built with Tailwind and Mermaid via CDN plus hand-crafted CSS/SVG. |
<!-- skills-table:end -->

This table is generated from each skill's `plugin.json` — edit there, then
run `python scripts/sync_registry.py --write`.

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
- `.claude-plugin/marketplace.json` — declares the repo as a Claude Code marketplace, one plugin entry per skill. The `plugins` array is generated from each skill's `plugin.json` by `scripts/sync_registry.py`.

## Maintenance / CI

GitHub Actions runs integrity checks on push, PR, and weekly:

- **`scripts/lint_skill.py`** — lints every `skills/*/SKILL.md`: required frontmatter, a "Use when" trigger in the description, the per-file line budget, and YAML-safe frontmatter values (an unquoted `: ` or ` #` makes `npx skills` drop the skill silently).
- **`scripts/check_doc_urls.py`** — for skills that ship a `references/docs-map.md`, fetches every doc URL and fails if any no longer resolves (catches upstream docs moving/renaming pages).
- **`scripts/sync_registry.py`** — generates the marketplace.json `plugins` array and the README skills table from each skill's `plugin.json` (the source of truth). CI runs `--check` to fail on drift or hand-edits; after changing a `plugin.json`, run `python scripts/sync_registry.py --write` and commit.

All scripts use the Python standard library only — no dependencies to install.

## License

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
