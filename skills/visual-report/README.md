# visual-report

The **`visual-report`** agent skill turns a subject — a system, a process,
research findings, a decision — into a **single self-contained HTML document
that carries its meaning in visuals**, not paragraphs. One file: portable,
openable anywhere, no build step.

## What it does

- **Explore** — gathers the substance worth drawing (walks the codebase via an `Explore` subagent, organizes what's already in the conversation, or reads the sources you point it at) instead of dumping files into the report.
- **Visualize** — writes one self-contained HTML file (Tailwind + Mermaid via CDN, plus hand-built CSS/SVG) and opens it. Every major idea earns a visual; if a section needs a paragraph to be understood, the visual gets redrawn.
- **Grill loop** — iterates on the same file as you refine sections, diagram patterns, and emphasis.

The only runtime dependencies are the Tailwind CDN and the Mermaid ESM import;
light interactivity is inline vanilla JS only — no extra libraries, no build step.

## How it works

The skill carries a small, named **visual language** (Mermaid graph,
boxes-and-arrows, cross-section, mass diagram, collapse) and an editorial house
style, so reports stay consistent and don't drift into a corporate-dashboard
look. It's ADR-aware: in a repo it reads `docs/adr/`, cites a governing ADR in a
callout when one applies, and offers to record a load-bearing decision the
visualization made explicit.

## Install

See the [repo root README](../../README.md) for the general install patterns
(`npx skills`, Claude Code plugin, manual clone). For this skill specifically:

```bash
npx skills add sleeplessv/relentless-data-skills/skills/visual-report
```

```text
/plugin marketplace add sleeplessv/relentless-data-skills
/plugin install visual-report@relentless-data-skills
```

It activates when you ask for a visual report, an explainer, or a single-file
HTML writeup of a system, process, or set of findings.

## Files

- `SKILL.md` — core: the explore → visualize → grill process, output rules, and ADR handling.
- `references/HTML-REPORT.md` — the HTML scaffold, diagram recipes, interactivity rules, and house style.
- `references/VISUAL-LANGUAGE.md` — the glossary of named diagram patterns and how to pick between them.

## Maintenance / CI

Repo CI lints this skill's `SKILL.md` (frontmatter, "Use when" trigger, line
budget) via `scripts/lint_skill.py` — see the
[root README](../../README.md#maintenance--ci). This skill ships no
`references/docs-map.md`, so the doc-URL liveness check skips it.
