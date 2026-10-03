# visual-report

The **`visual-report`** agent skill turns a subject (a system, a process,
research findings, a decision) into a **single self-contained HTML document
that carries its meaning in visuals**, not paragraphs. One file, portable, no
build step, though Tailwind and Mermaid load from CDNs, so it renders fully
only with network access.

## What it does

- **Explore.** Gathers the substance worth drawing: walks the codebase with `Explore` subagents, one per independent area, organizes what's already in the conversation, or reads the sources you point it at, instead of dumping files into the report.
- **Visualize.** Writes one self-contained HTML file (Tailwind + Mermaid via CDN, plus hand-built CSS/SVG), renders it in headless Chromium to prove every diagram drew cleanly as a reader would see it, tabs and toggles included, reads the per-diagram screenshots for legibility and the page screenshots for the hand-built visuals, and opens it. Every major idea earns a visual and the report runs as long as the subject has ideas, with no filler sections; if a section needs a paragraph to be understood, the visual gets redrawn.
- **Grill loop.** Interviews you about what the report gets wrong or underweights, one question at a time with a recommended answer, iterating on the same file.

The only runtime dependencies are the Tailwind CDN and the Mermaid ESM import.
Light interactivity is inline vanilla JS only, no extra libraries, no build step.

The render check needs [Playwright](https://playwright.dev/python/) and a
Chromium build, plus network access for the CDNs. With `uv` installed, the
command in `SKILL.md` fetches Playwright into a throwaway environment, and
the browser installs once:

```bash
uv run --no-project --with playwright playwright install chromium
```

Without them the check reports `BLOCKED`, and the skill hands the report over
as unverified rather than claiming it rendered.

## How it works

The skill carries a small, named **visual language** (Mermaid graph,
boxes-and-arrows, cross-section, mass diagram, collapse, comparison matrix,
timeline, proportion bars) and an editorial house style, so reports stay consistent and don't drift into a corporate-dashboard
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

- `SKILL.md`: core; the explore, visualize, grill process, output rules, and ADR handling.
- `references/HTML-REPORT.md`: the HTML scaffold, diagram recipes, interactivity rules, and house style.
- `references/VISUAL-LANGUAGE.md`: the glossary of named diagram patterns and how to pick between them.
- `scripts/check_render.py`: the headless render check. It waits for Mermaid to finish (including diagrams added by script), opens hidden tabs, toggles, and `<details>`, and fails on Mermaid error diagrams, unrendered blocks, diagrams that collapsed, shrank past legibility, or are clipped, broken images, missing resources, page and console errors, and a frozen tab. It reports `BLOCKED` only when the environment kept it from checking (no browser, CDN unreachable). It writes a screenshot per diagram and the page in viewport-height slices.

## Maintenance / CI

Repo CI lints this skill's `SKILL.md` (frontmatter, "Use when" trigger, line
budget) via `scripts/lint_skill.py`. See the
[root README](../../README.md#maintenance-and-ci). This skill ships no
`references/docs-map.md`, so the doc-URL liveness check skips it.
