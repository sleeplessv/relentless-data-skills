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
| [`fabric-lineage-dag`](skills/fabric-lineage-dag/) | Build an interactive data-lineage DAG for a Microsoft Fabric Git-exported medallion workspace — five parallel stdlib extractors (pipelines and schedules, JSON-config Silver, JSON-config Gold and wrapper notebooks, notebook code, TMDL semantic models and PBIR reports) write one agreed graph schema, a merge step aliases ids, derives live/fork flags and writes a validation report, and a dagre+d3 single-file page renders overview and focus lineage with a Coverage & gaps panel. |
| [`gh-weekly-report`](skills/gh-weekly-report/) | Generate a weekly GitHub activity report covering everything the authenticated user did on GitHub (issues, PRs, reviews, commits, discussions), optionally narrowed to one owner's repos, bucketed into canonical work types (feature, fix, refactor, docs, chore/infra, triage/review) with per-repo narratives, and rendered as an interactive HTML file with week-over-week deltas, per-repo breakdown, and drill-down to every item (data embedded; Tailwind and Chart.js load from CDNs). |
| [`implement-feature`](skills/implement-feature/) | Implement a whole feature as one PR: orchestrate subagents over a spec's tickets on a shared integration branch — waves of ticket branches, integrated review + tests, and a single feature PR to main. |
| [`implement-ticket`](skills/implement-ticket/) | Implement a ticket (GitHub issue) end-to-end: claim it, branch, code in small commits, run tests + a runtime smoke check, and open a draft PR — with explicit stop conditions instead of improvising. Formerly implement-issue. |
| [`metabase`](skills/metabase/) | Operate a Metabase instance through its REST API via a wrapper that treats cards as live objects — read-only ad-hoc SQL, MBQL-to-SQL compilation, source-chain and blast-radius tracing, and dashboard filter-wiring audits that catch field ids pointing at the wrong database. Every mutation captures a restore point first; there is no execute path for DML/DDL. |
| [`orchestrator-mode`](skills/orchestrator-mode/) | Forces the main thread to act as an orchestrator and delegate ALL work to subagents instead of doing it itself — plan, dispatch, verify with a separate agent, synthesize. Agent-neutral across Claude Code, Cursor, and Cortex Code. |
| [`prefect`](skills/prefect/) | Version-aware Prefect 3 guidance: a live docs-lookup protocol, CLI-first instance queries, and house standards. Prefect 2.x out of scope. |
| [`review-dbt-diff`](skills/review-dbt-diff/) | Read-only, diff-scoped reviewer for dbt model changes — twelve defect checks derived from the target repo's own fix history (grain, join cardinality, incremental coherence, NULL semantics, CDC ordering, contract drift), row-count deltas against production, evidence-rung grading, an Act-On cap of five with a visible Dismissed section, and a committed dismissal log that learns which patterns the owner keeps overriding. |
| [`review-pbi-diff`](skills/review-pbi-diff/) | Turn a Power BI (PBIP) git diff into a manager-ready review artifact — a deterministic extractor builds a structured change model from hash-named visual.json and TMDL files, then the agent draws to-scale page wireframes, spec-checks every added/modified measure's DAX against the repo's metric definitions, and runs eleven evidence-backed red-flag checks (dangling measure references, ripple effects, hidden filters, visible scratch pages). |
| [`ship`](skills/ship/) | Take working-tree changes from branch to merged PR in one pass — branch off main, commit smart-git-commit style, open a PR, then squash-merge and delete the local and remote branch. Command-only: /ship asks before merging, /ship clean goes straight through. Detects unrelated changes and offers to split them into separate branches/PRs. |
| [`smart-git-commit`](skills/smart-git-commit/) | Groups changed files by affected area, creates one conventional commit per group, then pushes to remote — with safety rules against force-pushes, skipped hooks, and committed secrets. |
| [`snowman`](skills/snowman/) | Read-only Snowflake exploration via the snow CLI — schema discovery, profiling, hypothesis testing, and data-quality investigation. Bootstraps a committed per-project context; a guardrail wrapper hard-enforces read-only execution and stages user-requested DML/DDL as scripts for manual execution. |
| [`visual-report`](skills/visual-report/) | Produce a single self-contained HTML visual report — an explainer, writeup, or diagram-heavy document built with Tailwind and Mermaid via CDN plus hand-crafted CSS/SVG. |
<!-- skills-table:end -->

This table is generated from each skill's `plugin.json` — edit there, then
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

One repo, 80-odd skills across its plugins, so `-s` is doing the picking here.
`npx skills add cursor/plugins -l` prints the full list if you want more of it.


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
