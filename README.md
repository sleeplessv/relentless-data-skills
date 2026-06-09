# relentless-data-skills

A collection of [agent skills](https://docs.claude.com/en/docs/claude-code/skills)
maintained by **Relentless Data**. Each skill lives in its own directory under
`skills/` and installs independently — pick the ones you want.

## Skills

| Skill | What it does |
| --- | --- |
| [`implement-issue`](skills/implement-issue/) | Take a GitHub issue from open to draft PR: claim, branch, implement, run tests + a runtime smoke check, with explicit stop conditions. |
| [`prefect-skill`](skills/prefect-skill/) | Prefect 3 greenfield scaffolding, existing-project audit, and a live docs-lookup protocol. Prefect 2.x out of scope. |
| [`visual-report`](skills/visual-report/) | Produce a single self-contained HTML visual report — an explainer or diagram-heavy writeup of a system, process, or findings, built with Tailwind + Mermaid. |

## Install

Every skill installs the same three ways. Substitute `<skill>` with a skill
directory name from the table above (e.g. `prefect-skill`).

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

Both use the Python standard library only — no dependencies to install.

## License

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
